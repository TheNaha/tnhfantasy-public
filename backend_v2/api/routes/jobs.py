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
    service: JobService = Depends(get_job_service)
):
    """List jobs with pagination. Uses deduplication to prevent duplicate work."""
    
    # Deduplicate concurrent identical requests
    return await deduplicated(
        make_key("list_jobs", limit, offset),
        lambda: service.list_jobs(limit=limit, offset=offset)
    )



@router.get("/active")
def get_active_jobs(service: JobService = Depends(get_job_service)):
    """Get all active (pending/running) jobs to rehydrate frontend state."""
    pending = service.get_pending_jobs()
    running = service.get_running_jobs()
    
    jobs_data = []
    
    for job in running:
        jobs_data.append(service._job_to_dict(job))
        
    for i, job in enumerate(pending):
        job_dict = service._job_to_dict(job)
        job_dict["queue_position"] = i + 1
        jobs_data.append(job_dict)
        
    return {"jobs": jobs_data}


@router.get("/queue")
def get_queue_status(service: JobService = Depends(get_job_service)):
    """
    Get queue status with ETA estimates.
    Returns pending and running jobs with estimated completion times.
    """
    
    pending = service.get_pending_queue_items()
    running = service.get_running_queue_items()
    avg_duration = service.get_average_duration()
    
    # Build queue items with ETA
    queue = []
    cumulative_time = 0
    
    # Add running jobs first (ETA based on progress)
    for job in running:
        remaining = avg_duration * (1 - (job.overall_progress / 100)) if job.overall_progress else avg_duration
        queue.append({
            "id": job.id,
            "status": "generating",
            "position": 0,
            "progress": job.overall_progress,
            "eta_seconds": remaining,
            "prompt": job.metadata_.get("prompt", "")[:50] if job.metadata_ else "",
        })
        cumulative_time = remaining
    
    # Add pending jobs with cumulative ETA
    for i, job in enumerate(pending):
        eta = cumulative_time + avg_duration
        queue.append({
            "id": job.id,
            "status": "pending",
            "position": i + 1,
            "progress": 0,
            "eta_seconds": eta,
            "prompt": job.metadata_.get("prompt", "")[:50] if job.metadata_ else "",
        })
        cumulative_time += avg_duration
    
    return {
        "queue": queue,
        "avg_duration_seconds": avg_duration,
        "has_history": avg_duration != 30.0,  # False if using default
        "total_pending": len(pending),
        "total_running": len(running),
    }


@router.get("/stats/summary")
def get_job_stats(service: JobService = Depends(get_job_service)):
    """Get job statistics."""
    return service.get_job_stats()


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
