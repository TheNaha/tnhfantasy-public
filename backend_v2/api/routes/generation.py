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
    metadata: dict[str, Any] = {}  # Optional: prompt, seed, model info for gallery display


class GenerateBatchRequest(BaseModel):
    workflows: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] = {}


class SaveImageRequest(BaseModel):
    """Request to save a generated image from worker."""
    image_base64: str
    job_id: str | None = None
    metadata: dict[str, Any] | None = None
    filename: str | None = None
    batch_index: int = 0


@router.post("/providers/save-image")
async def save_generated_image(
    request: SaveImageRequest,
):
    """
    Receive generated image from worker and save with metadata.
    
    Called by worker containers after ComfyUI generates an image.
    Uses ImageService to:
    - Save to date-based folder structure (output/YYYY/MM/DD/)
    - Embed metadata in PNG chunks
    - Generate WebP thumbnail
    - Generate blurhash for placeholder
    
    Returns saved image info for frontend display.
    """
    import asyncio
    import base64

    from services.image_service import get_image_service as _get_image_service
    
    try:
        image_data = base64.b64decode(request.image_base64, validate=True)
    except Exception as e:
        raise ValidationError(f"Invalid base64 image data: {e}")

    service = _get_image_service()
    
    result = await service.save_generated_image(
        image_data=image_data,
        metadata=request.metadata,
        job_id=request.job_id,
        filename=request.filename,
        batch_index=request.batch_index
    )
    
    try:
        from config import settings
        from infrastructure.database import Session as DBSession, engine as db_engine
        from services.asset_reconciler import reconcile_asset

        def _reconcile():
            session = DBSession(db_engine)
            try:
                reconcile_asset(
                    session,
                    result["path"],
                    user_id="default_user",
                    workspace=(request.metadata or {}).get("workspace", "main"),
                    job_id=request.job_id,
                    job_metadata=request.metadata or {},
                    output_dir=settings.output_dir,
                )
            finally:
                session.close()

        await asyncio.to_thread(_reconcile)
    except Exception as e:
        logger.error(f"Error reconciling saved image: {e}")

    return result


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
        if not request.workflow:
            raise ValidationError("workflow is required", field="workflow")

        async def _create_generation_job():
            job = await submission_service.create_and_enqueue_job(
                workflow=request.workflow,
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
        if not request.workflows:
            raise ValidationError("workflows array is required", field="workflows")

        async def _create_batch_jobs():
            created_jobs = []

            for i, workflow in enumerate(request.workflows):
                # Add batch index to metadata
                job_metadata = {
                    **request.metadata,
                    "batch_index": i,
                    "batch_total": len(request.workflows),
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
