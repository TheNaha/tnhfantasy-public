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
from typing import Dict, Any, List
from fastapi import APIRouter, Depends
from sqlmodel import Session
from pydantic import BaseModel

from api.deps import get_session
from core.exceptions import ValidationError
from infrastructure.logging import api_logger
from services.job_submission_service import JobSubmissionService

logger = api_logger()

router = APIRouter(prefix="/api", tags=["generation"])


class GenerateRequest(BaseModel):
    """Request body for single-image generation."""
    workflow: Dict[str, Any] | None = None  # Full ComfyUI workflow node graph
    metadata: Dict[str, Any] = {}  # Optional: prompt, seed, model info for gallery display


class GenerateBatchRequest(BaseModel):
    workflows: List[Dict[str, Any]] | None = None
    metadata: Dict[str, Any] = {}


@router.post("/generate")
async def generate(
    request: GenerateRequest,
    session: Session = Depends(get_session)
):
    """Create a new generation job.
    
    Accepts a ComfyUI workflow and optional metadata.
    Returns the created job with its ID for tracking.
    """
    try:
        if not request.workflow:
            raise ValidationError("workflow is required", field="workflow")
        
        submission_service = JobSubmissionService(session)
        job = await submission_service.create_and_enqueue_job(
            workflow=request.workflow,
            metadata=request.metadata,
        )
        logger.info("generate_job_created", job_id=job.id)
        return submission_service.job_service._job_to_dict(job)
    except Exception as e:
        logger.error("generate_failed", error=str(e))
        raise


@router.post("/generate/batch")
async def generate_batch(
    request: GenerateBatchRequest,
    session: Session = Depends(get_session)
):
    """Create multiple generation jobs at once.
    
    Accepts an array of workflows and creates one job per workflow.
    Each job gets a `batch_index` and `batch_total` added to its metadata
    so the UI can group the results.
    Returns an array of created job records.
    """
    try:
        if not request.workflows:
            raise ValidationError("workflows array is required", field="workflows")
        
        submission_service = JobSubmissionService(session)
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
    except Exception as e:
        logger.error("generate_batch_failed", error=str(e))
        raise
