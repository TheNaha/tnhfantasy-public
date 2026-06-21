# Job Service - Business logic for job management
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from sqlmodel import Session

from core.entities import Job, JobStatus
from core.dtos import JobQueueItem
from core.events import event_bus, Event, EventType, emit_job_event
from core.exceptions import NotFoundError, JobError
from infrastructure.repositories import JobRepository
from infrastructure.logging import job_logger

logger = job_logger()


class JobService:
    """
    Handles job lifecycle and business logic.
    Publishes events for real-time updates.
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.repo = JobRepository(session)
    
    async def create_job(self, workflow: Dict[str, Any], metadata: Dict[str, Any]) -> Job:
        """
        Create a new job.
        
        Args:
            workflow: ComfyUI workflow JSON
            metadata: Job metadata (prompt, seed, etc.)
            
        Returns:
            Created job
        """
        job = self.repo.create(workflow=workflow, metadata=metadata)
        
        logger.info("job_created", job_id=job.id)
        
        # Emit creation event
        await emit_job_event(EventType.JOB_CREATED, self._job_to_dict(job))
        
        return job
    
    async def get_job(self, job_id: str) -> Job:
        """Get a job by ID."""
        job = self.repo.get(job_id)
        if not job:
            logger.warning("job_not_found", job_id=job_id)
            raise NotFoundError("Job", job_id)
        try:
            self.session.refresh(job)
        except Exception as e:
            logger.debug("job_refresh_failed", job_id=job_id, error=str(e))
        return job
    
    async def list_jobs(self, limit: int = 20, offset: int = 0) -> Dict[str, Any]:
        """
        List jobs with pagination.
        
        Returns:
            Dict with 'jobs' list and 'total' count
        """
        jobs, total = self.repo.get_all(limit=limit, offset=offset)
        
        jobs_data = []

        # Gather all pending jobs on the current page
        pending_job_ids = [job.id for job in jobs if job.status == JobStatus.PENDING]

        # Fetch queue positions for all pending jobs in a single query
        queue_positions = {}
        if pending_job_ids:
            queue_positions = self.repo.get_queue_positions(pending_job_ids)

        for job in jobs:
            job_dict = self._job_to_dict(job)
            if job.status == JobStatus.PENDING:
                # Assign pre-calculated queue position
                job_dict["queue_position"] = queue_positions.get(job.id, 0)
            jobs_data.append(job_dict)
        
        return {"jobs": jobs_data, "total": total}
    
    async def update_job(self, job_id: str, **updates) -> Job:
        """
        Update a job.
        
        Args:
            job_id: Job ID
            **updates: Fields to update
            
        Returns:
            Updated job
        """
        # Track timing based on status changes
        job = self.repo.get(job_id)
        if not job:
            logger.warning("job_update_not_found", job_id=job_id)
            raise NotFoundError("Job", job_id)
            
        # Set started_at for first active state
        active_states = {JobStatus.SENT_TO_PROVIDER, JobStatus.CONNECTED, JobStatus.PRE_GENERATION, JobStatus.GENERATING, JobStatus.RUNNING, JobStatus.POST_PROCESSING}
        status = updates.get("status")
        if status in active_states and not job.started_at:
            updates["started_at"] = datetime.now(timezone.utc)
        elif status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            updates["completed_at"] = datetime.now(timezone.utc)
        
        job = self.repo.update(job_id, **updates)
        
        if status:
            logger.info("job_status_changed", job_id=job_id, status=status.value if hasattr(status, 'value') else status)
        
        # Determine event type based on status
        if status == JobStatus.COMPLETED:
            event_type = EventType.JOB_COMPLETED
        elif status == JobStatus.POST_PROCESSING:
            event_type = EventType.JOB_POST_PROCESSING
        elif status == JobStatus.FAILED:
            event_type = EventType.JOB_FAILED
        elif status == JobStatus.CANCELLED:
            event_type = EventType.JOB_CANCELLED
        elif "progress" in updates:
            event_type = EventType.JOB_PROGRESS
        else:
            event_type = EventType.JOB_UPDATED
        
        await emit_job_event(event_type, self._job_to_dict(job))
        
        return job
    
    async def delete_job(self, job_id: str) -> bool:
        """Delete a job."""
        success = self.repo.delete(job_id)
        if not success:
            logger.warning("job_delete_not_found", job_id=job_id)
            raise NotFoundError("Job", job_id)
        logger.info("job_deleted", job_id=job_id)
        return True
    
    async def clear_all_jobs(self) -> int:
        """Clear all jobs. Returns count of deleted jobs."""
        count = self.repo.delete_all()
        logger.info("jobs_cleared", count=count)
        return count
    
    def get_pending_jobs(self) -> List[Job]:
        """Get all pending jobs in FIFO order."""
        return self.repo.get_pending()
    
    def get_running_jobs(self) -> List[Job]:
        """Get all running/processing jobs."""
        active_states = [JobStatus.SENT_TO_PROVIDER, JobStatus.CONNECTED, JobStatus.PRE_GENERATION, JobStatus.GENERATING, JobStatus.RUNNING, JobStatus.POST_PROCESSING]
        return self.repo.get_by_statuses(active_states)

    def get_pending_queue_items(self) -> List[JobQueueItem]:
        """Get pending queue items (lightweight)."""
        return self.repo.get_queue_items([JobStatus.PENDING])

    def get_running_queue_items(self) -> List[JobQueueItem]:
        """Get running/processing queue items (lightweight)."""
        active_states = [JobStatus.SENT_TO_PROVIDER, JobStatus.CONNECTED, JobStatus.PRE_GENERATION, JobStatus.GENERATING, JobStatus.RUNNING, JobStatus.POST_PROCESSING]
        return self.repo.get_queue_items(active_states)
    
    def get_average_duration(self, sample_size: int = 10) -> float:
        """
        Calculate average job duration from recent completed jobs.
        
        Args:
            sample_size: Number of recent jobs to sample
            
        Returns:
            Average duration in seconds, or 30.0 as default if no data
        """
        completed_jobs = self.repo.get_recently_completed(sample_size)
        
        durations = []
        for job in completed_jobs:
            if job.started_at and job.completed_at:
                duration = (job.completed_at - job.started_at).total_seconds()
                if duration > 0:
                    durations.append(duration)
        
        if len(durations) >= 3:
            return sum(durations) / len(durations)
        
        # Default estimate if not enough data
        return 30.0
    
    def get_job_stats(self) -> Dict[str, int]:
        """Get job counts by status."""
        return self.repo.count_by_status()
    
    def get_job_stats_detailed(self, days: int = 7) -> Dict[str, Any]:
        """
        Get comprehensive job statistics in a single optimized query.
        More efficient than multiple separate count/average queries.
        
        Args:
            days: Number of days to look back for statistics (default 7)
            
        Returns:
            Dict with 'by_status', 'total', 'avg_durations' keys
        """
        from sqlalchemy import text
        
        result = self.session.exec(text("""
            SELECT 
                status,
                COUNT(*) as count,
                AVG(
                    CASE 
                        WHEN completed_at IS NOT NULL AND started_at IS NOT NULL 
                        THEN (julianday(completed_at) - julianday(started_at)) * 86400 
                        ELSE NULL 
                    END
                ) as avg_duration_seconds
            FROM jobs
            WHERE created_at > datetime('now', :days_ago)
            GROUP BY status
        """).bindparams(days_ago=f'-{days} days')).all()
        
        stats = {
            'by_status': {},
            'total': 0,
            'avg_durations': {},
            'period_days': days
        }
        
        for row in result:
            status, count, avg_duration = row
            stats['by_status'][status] = count
            stats['total'] += count
            if avg_duration is not None:
                stats['avg_durations'][status] = round(avg_duration, 2)
        
        return stats
    
    def _job_to_dict(self, job: Job) -> Dict[str, Any]:
        """Convert job to dictionary for API responses."""
        return {
            "id": job.id,
            "status": job.status.value,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "workflow": job.workflow,
            "metadata": job.metadata_,
            "outputs": job.outputs,
            "progress": job.progress,
            "overall_progress": job.overall_progress,
            "message": job.message,
            "error": job.error,
            "provider_id": job.provider_id,
        }
