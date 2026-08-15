# Generation routes
#
# These endpoints create ComfyUI generation jobs and enqueue them for
# processing.  The actual execution is handled asynchronously by the job
# queue workers in `services/job_queue.py`.
#
# FLOW:
#   POST /api/generate (or /api/generate/batch)
#     → create Job record in DB (status=PENDING)
#     → enqueue job ID into JobQueue (in-memory asyncio queue)
#     → return job dict immediately (caller tracks progress via WebSocket)
#
# For workflow validation (check model availability before submitting)
# use POST /api/jobs/validate (routes/jobs.py).
#
# Optional idempotency:
#   - POST /api/generate and POST /api/generate/batch accept `Idempotency-Key`
#     to deduplicate duplicate submissions within a short server-side window.
from typing import Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from api.deps import (
    api_logger,
    deduplicated,
    get_job_submission_service,
    make_key,
)
from core.exceptions import ValidationError
from services.job_submission_service import JobSubmissionService

logger = api_logger()

router = APIRouter(prefix="/api", tags=["generation"])


class GenerateRequest(BaseModel):
    """Request body for single-image generation."""
    workflow: dict[str, Any] | None = None  # Full ComfyUI workflow node graph
    options: dict[str, Any] | None = None  # Generator options
    metadata: dict[str, Any] = {}  # Optional: prompt, seed, model info for gallery display


class GenerateBatchRequest(BaseModel):
    workflows: list[dict[str, Any]] | None = None
    options: dict[str, Any] | None = None
    metadata: dict[str, Any] = {}


@router.post("/generate")
async def generate(
    request: GenerateRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        description="Optional request key. Re-using the same key reuses the same response for a short deduplication window.",
    ),
    submission_service: JobSubmissionService = Depends(get_job_submission_service)
):
    """Create a new generation job.
    
    Accepts a ComfyUI workflow and optional metadata.
    Returns the created job with its ID for tracking.

        Idempotency:
        - If `Idempotency-Key` is provided, duplicate submissions with the same key
            return the same response during a short deduplication window.
        - If omitted, each request creates a new job.
    """
    try:
        from core.workflow_builder import WorkflowBuilder
        workflow = request.workflow
        if not workflow and request.options:
            builder = WorkflowBuilder()
            workflow = builder.build(request.options)
            
        if not workflow:
            raise ValidationError("workflow or options is required", field="workflow")

        async def _create_generation_job():
            job = await submission_service.create_and_enqueue_job(
                workflow=workflow,
                metadata=request.metadata,
            )
            logger.info("generate_job_created", job_id=job.id)
            return submission_service.job_service._job_to_dict(job)

        if idempotency_key:
            dedup_key = make_key("generate", idempotency_key.strip())
            return await deduplicated(dedup_key, _create_generation_job)

        return await _create_generation_job()
    except Exception as e:
        logger.error("generate_failed", error=str(e))
        raise


@router.post("/generate/batch")
async def generate_batch(
    request: GenerateBatchRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        description="Optional request key. Re-using the same key reuses the same batch response for a short deduplication window.",
    ),
    submission_service: JobSubmissionService = Depends(get_job_submission_service)
):
    """Create multiple generation jobs at once.
    
    Accepts an array of workflows and creates one job per workflow.
    Each job gets a `batch_index` and `batch_total` added to its metadata
    so the UI can group the results.
    Returns an array of created job records.

    Idempotency:
    - If `Idempotency-Key` is provided, duplicate submissions with the same key
      return the same batch response during a short deduplication window.
    - If omitted, each request creates a new set of jobs.
    """
    try:
        from core.workflow_builder import WorkflowBuilder

        workflows = request.workflows
        
        # If workflows are omitted but options are provided, treat it as a single-workflow batch
        # This isn't commonly needed but ensures we don't break if someone passes options to batch
        if not workflows and request.options:
            builder = WorkflowBuilder()
            workflows = [builder.build(request.options)]

        if not workflows:
            raise ValidationError("workflows array is required", field="workflows")

        async def _create_batch_jobs():
            created_jobs = []

            for i, workflow in enumerate(workflows):
                # Add batch index to metadata; per-workflow metadata (e.g. the
                # frontend's per-prompt entries) wins over the request-level one.
                job_metadata = {
                    **request.metadata,
                    **(workflow.get("metadata") or {}),
                    "batch_index": i,
                    "batch_total": len(workflows),
                }
                job = await submission_service.create_and_enqueue_job(
                    workflow=workflow,
                    metadata=job_metadata,
                )
                created_jobs.append(submission_service.job_service._job_to_dict(job))

            logger.info("generate_batch_created", count=len(created_jobs))
            return {"jobs": created_jobs, "count": len(created_jobs)}

        if idempotency_key:
            dedup_key = make_key("generate_batch", idempotency_key.strip())
            return await deduplicated(dedup_key, _create_batch_jobs)

        return await _create_batch_jobs()
    except Exception as e:
        logger.error("generate_batch_failed", error=str(e))
        raise
