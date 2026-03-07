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
from typing import Dict, Any
from fastapi import APIRouter, Depends, Request
from sqlmodel import Session
from pydantic import BaseModel

from api.deps import get_session, get_job_service
from core.exceptions import ValidationError
from services.job_queue import job_queue
from infrastructure.logging import api_logger

logger = api_logger()

router = APIRouter(prefix="/api", tags=["generation"])


class GenerateRequest(BaseModel):
    """Request body for single-image generation."""
    workflow: Dict[str, Any]   # Full ComfyUI workflow node graph
    metadata: Dict[str, Any] = {}  # Optional: prompt, seed, model info for gallery display


@router.post("/generate")
async def generate(
    request: Request,
    session: Session = Depends(get_session)
):
    """Create a new generation job.
    
    Accepts a ComfyUI workflow and optional metadata.
    Returns the created job with its ID for tracking.
    """
    try:
        data = await request.json()
        workflow = data.get("workflow")
        metadata = data.get("metadata", {})
        
        if not workflow:
            raise ValidationError("workflow is required", field="workflow")
        
        service = get_job_service(session)
        job = await service.create_job(workflow=workflow, metadata=metadata)
        
        # Enqueue job for processing
        await job_queue.enqueue(job.id)
        logger.info("generate_job_created", job_id=job.id)
        
        return service._job_to_dict(job)
    except Exception as e:
        logger.error("generate_failed", error=str(e))
        import traceback
        traceback.print_exc()
        raise


@router.post("/generate/batch")
async def generate_batch(
    request: Request,
    session: Session = Depends(get_session)
):
    """Create multiple generation jobs at once.
    
    Accepts an array of workflows and creates one job per workflow.
    Each job gets a `batch_index` and `batch_total` added to its metadata
    so the UI can group the results.
    Returns an array of created job records.
    """
    try:
        data = await request.json()
        workflows = data.get("workflows", [])
        metadata = data.get("metadata", {})
        
        if not workflows:
            raise ValidationError("workflows array is required", field="workflows")
        
        service = get_job_service(session)
        created_jobs = []
        
        for i, workflow in enumerate(workflows):
            # Add batch index to metadata
            job_metadata = {**metadata, "batch_index": i, "batch_total": len(workflows)}
            job = await service.create_job(workflow=workflow, metadata=job_metadata)
            
            # Enqueue job for processing
            await job_queue.enqueue(job.id)
            
            created_jobs.append(service._job_to_dict(job))
        
        logger.info("generate_batch_created", count=len(created_jobs))
        return {"jobs": created_jobs, "count": len(created_jobs)}
    except Exception as e:
        logger.error("generate_batch_failed", error=str(e))
        raise
