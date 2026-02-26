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
# Real-time updates are delivered via WebSocket (routes/websocket.py).
# The job queue itself lives in services/job_queue.py.
import json
from typing import Optional, Dict, List, Any
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import Response, JSONResponse
from sqlmodel import Session
from pydantic import BaseModel

from api.deps import get_session, get_event_bus, get_job_service
from services.job_service import JobService
from services.job_queue import job_queue
from services.model_availability_service import ModelAvailabilityService
from core.events import EventBus
from core.exceptions import NotFoundError
from core.workflow_parser import extract_models_from_workflow
from infrastructure.request_dedup import deduplicated, make_key

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class CreateJobRequest(BaseModel):
    workflow: dict
    metadata: dict = {}


class ValidateWorkflowRequest(BaseModel):
    """Request to validate workflow model availability."""
    workflow: dict
    preferred_provider_id: Optional[str] = None


class ValidateWorkflowResponse(BaseModel):
    """Response with model availability information."""
    valid: bool
    eligible_providers: List[str]
    missing_models: Dict[str, Dict[str, List[str]]]  # {provider: {dir: [files]}}
    global_missing: Dict[str, List[str]]  # Models missing on ALL providers
    can_trigger_download: bool
    required_models: Dict[str, List[str]]  # What models were found in workflow


@router.post("/validate")
async def validate_workflow(
    request: ValidateWorkflowRequest,
    session: Session = Depends(get_session)
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
    # Extract models from workflow
    required_models = extract_models_from_workflow(request.workflow)
    
    # Check availability
    availability_service = ModelAvailabilityService(session)
    result = availability_service.check_availability(required_models)
    
    # If preferred provider specified but not eligible, add specific info
    if request.preferred_provider_id and request.preferred_provider_id not in result.eligible_providers:
        # Get specific missing models for preferred provider
        preferred_missing = result.missing_models.get(request.preferred_provider_id, {})
        if preferred_missing:
            result.missing_models[request.preferred_provider_id] = preferred_missing
    
    return {
        "valid": result.valid,
        "eligible_providers": result.eligible_providers,
        "missing_models": result.missing_models,
        "global_missing": result.global_missing,
        "can_trigger_download": result.can_trigger_download,
        "required_models": required_models
    }


@router.post("")
async def create_job(
    request: CreateJobRequest,
    session: Session = Depends(get_session)
):
    """
    Create a new job.
    
    Validates that at least one provider has all required models.
    Returns 400 with detailed missing model info if validation fails.
    """
    # Extract and validate models
    required_models = extract_models_from_workflow(request.workflow)
    
    if required_models:
        availability_service = ModelAvailabilityService(session)
        availability = availability_service.check_availability(required_models)
        
        if not availability.valid:
            # No provider has all required models - return detailed error
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "missing_models",
                    "message": "No provider has all required models installed",
                    "required_models": required_models,
                    "global_missing": availability.global_missing,
                    "missing_by_provider": availability.missing_models,
                    "can_trigger_download": availability.can_trigger_download
                }
            )
    
    service = get_job_service(session)
    job = await service.create_job(request.workflow, request.metadata)
    
    # Enqueue for processing
    await job_queue.enqueue(job.id)
    
    return service._job_to_dict(job)



@router.get("")
async def list_jobs(
    limit: int = 20,
    offset: int = 0,
    session: Session = Depends(get_session)
):
    """List jobs with pagination. Uses deduplication to prevent duplicate work."""
    service = get_job_service(session)
    
    # Deduplicate concurrent identical requests
    return await deduplicated(
        make_key("list_jobs", limit, offset),
        lambda: service.list_jobs(limit=limit, offset=offset)
    )



@router.get("/queue")
async def get_queue_status(session: Session = Depends(get_session)):
    """
    Get queue status with ETA estimates.
    Returns pending and running jobs with estimated completion times.
    """
    service = get_job_service(session)
    
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
            "status": "running",
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
async def get_job_stats(session: Session = Depends(get_session)):
    """Get job statistics."""
    service = get_job_service(session)
    return service.get_job_stats()


# NOTE: Routes with path parameters MUST come AFTER static routes
# Otherwise '/queue' would match as job_id='queue'

@router.get("/{job_id}")
async def get_job(
    job_id: str,
    session: Session = Depends(get_session)
):
    """Get a specific job."""
    service = get_job_service(session)
    job = await service.get_job(job_id)
    return service._job_to_dict(job)


@router.post("/{job_id}/retry")
async def retry_job(
    job_id: str,
    session: Session = Depends(get_session)
):
    """Retry a failed job by creating a new job with the same workflow."""
    service = get_job_service(session)
    original_job = await service.get_job(job_id)
    
    if original_job.status not in ['failed', 'error']:
        raise HTTPException(
            status_code=400,
            detail="Only failed jobs can be retried"
        )
    
    # Create new job with same workflow
    new_job = await service.create_job(
        original_job.workflow,
        original_job.metadata_
    )
    await job_queue.enqueue(new_job.id)
    
    return {
        "status": "success",
        "new_job_id": new_job.id,
        "original_job_id": job_id
    }


@router.delete("/{job_id}")
async def delete_job(
    job_id: str,
    session: Session = Depends(get_session)
):
    """Delete a job."""
    service = get_job_service(session)
    await service.delete_job(job_id)
    return {"status": "success"}


@router.post("/clear")
async def clear_jobs(session: Session = Depends(get_session)):
    """Clear all jobs."""
    service = get_job_service(session)
    count = await service.clear_all_jobs()
    return {"status": "success", "deleted": count}


@router.delete("")
async def delete_all_jobs(session: Session = Depends(get_session)):
    """Delete all jobs (alias for POST /clear)."""
    service = get_job_service(session)
    count = await service.clear_all_jobs()
    return {"status": "success", "deleted": count}
