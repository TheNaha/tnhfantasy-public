# Generation routes
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlmodel import Session
from pydantic import BaseModel

from api.deps import get_session, get_job_service
from services.job_queue import job_queue

router = APIRouter(prefix="/api", tags=["generation"])


class GenerateRequest(BaseModel):
    workflow: Dict[str, Any]
    metadata: Dict[str, Any] = {}


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
            raise HTTPException(status_code=400, detail="workflow is required")
        
        service = get_job_service(session)
        job = await service.create_job(workflow=workflow, metadata=metadata)
        
        # Enqueue job for processing
        await job_queue.enqueue(job.id)
        print(f"[Generate] Job {job.id} created and enqueued")
        
        return service._job_to_dict(job)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Generate failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate/batch")
async def generate_batch(
    request: Request,
    session: Session = Depends(get_session)
):
    """Create multiple generation jobs at once.
    
    Accepts an array of workflows. Returns array of created jobs.
    """
    try:
        data = await request.json()
        workflows = data.get("workflows", [])
        metadata = data.get("metadata", {})
        
        if not workflows:
            raise HTTPException(status_code=400, detail="workflows array is required")
        
        service = get_job_service(session)
        created_jobs = []
        
        for i, workflow in enumerate(workflows):
            # Add batch index to metadata
            job_metadata = {**metadata, "batch_index": i, "batch_total": len(workflows)}
            job = await service.create_job(workflow=workflow, metadata=job_metadata)
            
            # Enqueue job for processing
            await job_queue.enqueue(job.id)
            
            created_jobs.append(service._job_to_dict(job))
        
        print(f"[Generate] Batch of {len(created_jobs)} jobs created and enqueued")
        return {"jobs": created_jobs, "count": len(created_jobs)}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Batch generate failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
