import logging
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from core.entities import JobStatus
from services.job_service import JobService
from services.job_queue import JobQueue
from services.job_submission_service import JobSubmissionService

logger = logging.getLogger("job_orchestrator")

class JobOrchestrator:
    """
    Unified entry point for job management.
    This class consolidates the sprawling job_* logic.
    """
    def __init__(self, session: Session, job_queue: JobQueue):
        self.session = session
        self.job_service = JobService(session)
        self.job_submission = JobSubmissionService(session, job_queue)
        self.job_queue = job_queue

    async def submit_job(self, params: Dict[str, Any], images: list = None) -> str:
        return await self.job_submission.submit_job(params, images)

    async def get_job(self, job_id: str) -> Optional[Any]:
        return await self.job_service.get_job(job_id)
        
    async def cancel_job(self, job_id: str) -> bool:
        job = await self.job_service.get_job(job_id)
        if job and job.status in (JobStatus.PENDING, JobStatus.RUNNING):
            await self.job_service.update_job(job_id, status=JobStatus.CANCELLED)
            return True
        return False
