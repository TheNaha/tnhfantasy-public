# Job routes - CRUD + validation endpoints for the job lifecycle
#
# KEY ENDPOINTS:
#   POST   /api/jobs            – Create and enqueue a new job
#   GET    /api/jobs            – List jobs with pagination
#   GET    /api/jobs/{id}       – Get a single job by ID
#   DELETE /api/jobs/{id}       – Delete a job record
#   DELETE /api/jobs            – Clear all job records
#   POST   /api/jobs/{id}/retry – Re-submit a failed job with the same workflow
#   POST   /api/jobs/validate   – Pre-flight model-availability check
#
# Optional idempotency:
#   - POST /api/jobs accepts `Idempotency-Key` for short-window response reuse
#     to prevent duplicate submissions from client retries.
#
# Real-time updates are delivered via WebSocket (routes/websocket.py).
# The job queue itself lives in services/job_queue.py.

from datetime import datetime

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from api.deps import (
    api_logger,
    deduplicated,
    get_job_service,
    get_job_submission_service,
    make_key,
)
from core.entities import JobStatus
from core.exceptions import ValidationError
from services.job_service import JobService
from services.job_submission_service import JobSubmissionService

logger = api_logger()

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class CreateJobRequest(BaseModel):
    workflow: dict
    metadata: dict = {}
    task_type: str = "image"


class ValidateWorkflowRequest(BaseModel):
    """Request to validate workflow model availability."""
    workflow: dict
    preferred_provider_id: str | None = None


class ValidateWorkflowResponse(BaseModel):
    """Response with model availability information."""
    valid: bool
    eligible_providers: list[str]
    missing_models: dict[str, dict[str, list[str]]]  # {provider: {dir: [files]}}
    global_missing: dict[str, list[str]]  # Models missing on ALL providers
    can_trigger_download: bool
    required_models: dict[str, list[str]]  # What models were found in workflow


@router.post("/validate")
async def validate_workflow(
    request: ValidateWorkflowRequest,
    submission_service: JobSubmissionService = Depends(get_job_submission_service)
):
    """
    Pre-flight validation to check if required models are available.
    
    Use this before job creation to:
    - Check if any provider has all required models
    - Get list of missing models per provider
    - Identify globally missing models (not on any provider)
    - Determine if downloads can be triggered
    
    Returns detailed breakdown to allow UI to show missing models
    and offer download triggers.
    """
    response = submission_service.build_validation_response(
        request.workflow,
        preferred_provider_id=request.preferred_provider_id,
    )
    logger.debug("workflow_validation_start", model_count=len(response["required_models"]))
    return response


@router.post("")
async def create_job(
    request: CreateJobRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        description="Optional request key. Re-using the same key reuses the same response for a short deduplication window.",
    ),
    submission_service: JobSubmissionService = Depends(get_job_submission_service)
):
    """
    Create a new job.
    
    Validates that at least one provider has all required models.
    Returns 400 with detailed missing model info if validation fails.

    Idempotency:
    - If `Idempotency-Key` is provided, duplicate submissions with the same key
      return the same response during a short deduplication window.
    - If omitted, each request creates a new job.
    """

    async def _create_and_enqueue():
        job = await submission_service.create_and_enqueue_job(
            request.workflow,
            request.metadata,
            task_type=request.task_type,
        )
        logger.info("job_enqueued", job_id=job.id)
        return submission_service.job_service._job_to_dict(job)

    # Opt-in idempotency for clients that can safely provide a request key.
    # Default behavior remains unchanged for repeated submissions without the header.
    if idempotency_key:
        dedup_key = make_key("create_job", idempotency_key.strip())
        return await deduplicated(dedup_key, _create_and_enqueue)

    return await _create_and_enqueue()



@router.get("")
async def list_jobs(
    limit: int = 20,
    offset: int = 0,
    cursor: str | None = None,
    service: JobService = Depends(get_job_service)
):
    """List jobs with pagination. Uses deduplication to prevent duplicate work."""
    
    # Keyset pagination: cursor is "ISO8601_created_at|job_id" of the last row
    # of the previous page. When provided it replaces OFFSET (O(log n) fetches
    # on PostgreSQL instead of O(n) row skipping).
    parsed_cursor = None
    if cursor:
        try:
            created_part, _, job_id = cursor.partition("|")
            parsed_cursor = (datetime.fromisoformat(created_part), job_id)
        except (ValueError, TypeError):
            raise ValidationError("Invalid cursor format; expected 'created_at|job_id'")
    
    # Deduplicate concurrent identical requests
    async def _list():
        result = await service.list_jobs(limit=limit, offset=offset, cursor=parsed_cursor)
        if result["jobs"]:
            last = result["jobs"][-1]
            result["next_cursor"] = f"{last['created_at']}|{last['id']}"
        return result

    return await deduplicated(
        make_key("list_jobs", limit, offset, cursor),
        _list,
    )


@router.get("/search")
async def search_jobs(
    q: str,
    limit: int = 25,
    service: JobService = Depends(get_job_service)
):
    """Full-text search over job prompts (tsvector on Postgres, LIKE on SQLite)."""
    if not q.strip():
        return {"jobs": []}
    if limit > 100:
        limit = 100
    results = await deduplicated(
        make_key("search_jobs", q, limit),
        lambda: service.search_jobs(q.strip(), limit=limit),
    )
    return {"jobs": results}



@router.get("/active")
def get_active_jobs(service: JobService = Depends(get_job_service)):
    """Get all active (pending/running) jobs to rehydrate frontend state."""
    pending = service.get_pending_jobs()
    running = service.get_running_jobs()
    
    jobs_data = []
    per_type_position = {}
    
    for job in running:
        jobs_data.append(service._job_to_dict(job))
        
    for job in pending:
        job_dict = service._job_to_dict(job)
        per_type_position[job.task_type] = per_type_position.get(job.task_type, 0) + 1
        job_dict["queue_position"] = per_type_position[job.task_type]
        jobs_data.append(job_dict)
        
    return {"jobs": jobs_data}


@router.get("/queue")
def get_queue_status(service: JobService = Depends(get_job_service)):
    """
    Get queue status with ETA estimates.
    Returns pending and running jobs with estimated completion times.
    ETAs are computed per task_type so LLM jobs (seconds) don't pollute
    image job (minutes) estimates.
    """

    pending = service.get_pending_queue_items()
    running = service.get_running_queue_items()
    running_by_type = {}
    pending_by_type = {}
    for job in running:
        running_by_type.setdefault(job.task_type, []).append(job)
    for job in pending:
        pending_by_type.setdefault(job.task_type, []).append(job)

    avg_durations = {
        task_type: service.get_average_duration(task_type=task_type)
        for task_type in set(list(running_by_type.keys()) + list(pending_by_type.keys()))
    }

    # Build queue items with ETA (per task_type)
    queue = []
    cumulative_by_type = {}

    for job in running:
        avg_duration = avg_durations.get(job.task_type, 30.0)
        remaining = avg_duration * (1 - (job.overall_progress / 100)) if job.overall_progress else avg_duration
        queue.append({
            "id": job.id,
            "task_type": job.task_type,
            "status": "generating",
            "position": 0,
            "progress": job.overall_progress,
            "eta_seconds": remaining,
            "prompt": job.metadata_.get("prompt", "")[:50] if job.metadata_ else "",
        })
        cumulative_by_type[job.task_type] = remaining

    # Add pending jobs with cumulative ETA (per task_type)
    for job in pending:
        avg_duration = avg_durations.get(job.task_type, 30.0)
        cumulative = cumulative_by_type.get(job.task_type, 0)
        eta = cumulative + avg_duration
        queue.append({
            "id": job.id,
            "task_type": job.task_type,
            "status": "pending",
            "position": pending_by_type[job.task_type].index(job) + 1,
            "progress": 0,
            "eta_seconds": eta,
            "prompt": job.metadata_.get("prompt", "")[:50] if job.metadata_ else "",
        })
        cumulative_by_type[job.task_type] = eta

    return {
        "queue": queue,
        "avg_duration_seconds": avg_durations,
        "has_history": any(v != 30.0 for v in avg_durations.values()),
        "total_pending": len(pending),
        "total_running": len(running),
    }


@router.get("/stats/summary")
def get_job_stats(service: JobService = Depends(get_job_service)):
    """Get job statistics."""
    return service.get_job_stats()


@router.get("/breakdown")
async def get_jobs_breakdown(
    key: str = "model",
    limit: int = 25,
    service: JobService = Depends(get_job_service),
):
    """
    Aggregate jobs by a top-level metadata_ key using JSONB (PostgreSQL) /
    JSON1 (SQLite). E.g. GET /api/jobs/breakdown?key=model returns the most
    common checkpoint models across jobs.
    """
    import re

    if not re.fullmatch(r"[A-Za-z0-9_]+", key):
        raise ValidationError("key must be alphanumeric/underscore only", field="key")
    statuses = [JobStatus.COMPLETED, JobStatus.FAILED]
    items = await service.get_metadata_key_counts(key, statuses=statuses, limit=limit)
    return {"key": key, "breakdown": items}


# NOTE: Routes with path parameters MUST come AFTER static routes
# Otherwise '/queue' would match as job_id='queue'

@router.get("/{job_id}")
async def get_job(
    job_id: str,
    service: JobService = Depends(get_job_service)
):
    """Get a specific job."""
    job = await service.get_job(job_id)
    return service._job_to_dict(job)


@router.post("/{job_id}/retry")
async def retry_job(
    job_id: str,
    service: JobService = Depends(get_job_service),
    submission_service: JobSubmissionService = Depends(get_job_submission_service)
):
    """Retry a failed job by creating a new job with the same workflow."""
    original_job = await service.get_job(job_id)
    
    if original_job.status != JobStatus.FAILED:
        raise ValidationError("Only failed jobs can be retried")
    
    new_job = await submission_service.create_and_enqueue_job(
        original_job.workflow,
        original_job.metadata_,
        task_type=original_job.task_type,
    )
    
    logger.info("job_retried", original_job_id=job_id, new_job_id=new_job.id)
    
    return {
        "status": "success",
        "new_job_id": new_job.id,
        "original_job_id": job_id
    }


@router.delete("/{job_id}")
async def delete_job(
    job_id: str,
    service: JobService = Depends(get_job_service)
):
    """Delete a job."""
    await service.delete_job(job_id)
    return {"status": "success"}


@router.delete("")
async def delete_all_jobs(service: JobService = Depends(get_job_service)):
    """Delete all jobs."""
    count = await service.clear_all_jobs()
    return {"status": "success", "deleted": count}
