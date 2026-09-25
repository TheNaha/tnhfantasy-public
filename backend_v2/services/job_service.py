# Job Service - Business logic for job management
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import Session, select

from core.dtos import JobQueueItem
from core.entities import Job, JobStatus
from core.events import EventType, emit_job_event
from core.exceptions import NotFoundError, ValidationError
from infrastructure.logging import job_logger
from infrastructure.metrics import metrics
from infrastructure.repositories import JobRepository

logger = job_logger()

JOB_STATUS_TRANSITIONS = {
    JobStatus.PENDING: {JobStatus.SENT_TO_PROVIDER, JobStatus.CANCELLED},
    JobStatus.SENT_TO_PROVIDER: {JobStatus.CONNECTED, JobStatus.PRE_GENERATION, JobStatus.GENERATING, JobStatus.POST_PROCESSING, JobStatus.RETRYING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.CONNECTED: {JobStatus.PRE_GENERATION, JobStatus.GENERATING, JobStatus.POST_PROCESSING, JobStatus.RETRYING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.PRE_GENERATION: {JobStatus.GENERATING, JobStatus.POST_PROCESSING, JobStatus.RETRYING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.GENERATING: {JobStatus.POST_PROCESSING, JobStatus.RETRYING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.POST_PROCESSING: {JobStatus.RETRYING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.RETRYING: {JobStatus.SENT_TO_PROVIDER, JobStatus.CONNECTED, JobStatus.PRE_GENERATION, JobStatus.GENERATING, JobStatus.POST_PROCESSING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED: {JobStatus.PENDING},
    JobStatus.CANCELLED: set(),
}


class JobService:
    """
    Handles job lifecycle and business logic.
    Publishes events for real-time updates.
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.repo = JobRepository(session)
    
    async def create_job(self, workflow: dict[str, Any], metadata: dict[str, Any], task_type: str = "image") -> Job:
        """
        Create a new job.
        
        Args:
            workflow: ComfyUI workflow JSON
            metadata: Job metadata (prompt, seed, etc.)
            
        Returns:
            Created job
        """
        job = self.repo.create(workflow=workflow, metadata=metadata, task_type=task_type)
        
        # Populate typed routing columns from metadata for SQL-level filtering
        if metadata:
            job.workspace = metadata.get("workspace")
            job.character_id = metadata.get("character_id")
            job.story_id = metadata.get("story_id")
            job.source = metadata.get("source")
            self.session.add(job)
            self.session.commit()
            self.session.refresh(job)
        
        logger.info("job_created", job_id=job.id)
        metrics.track_job_created()
        
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
            try:
                self.session.get(Job, job_id)
            except Exception:
                raise NotFoundError("Job", job_id)
        return job
    
    async def list_jobs(
        self,
        limit: int = 20,
        offset: int = 0,
        cursor: tuple[datetime, str] | None = None,
    ) -> dict[str, Any]:
        """
        List jobs with pagination.

        `cursor` enables keyset pagination: a (created_at, id) tuple taken
        from the last job of a previous page (see `_job_to_dict` for how
        clients receive it). When provided it replaces OFFSET.

        Returns:
            Dict with 'jobs' list and 'total' count
        """
        results, total = self.repo.get_all(limit=limit, offset=offset, cursor=cursor)
        
        jobs_data = []
        for job, pos in results:
            job_dict = self._job_to_dict(job)
            if job.status == JobStatus.PENDING and pos is not None:
                job_dict["queue_position"] = pos
            jobs_data.append(job_dict)
        
        return {"jobs": jobs_data, "total": total}

    async def get_metadata_key_counts(
        self, key: str, *, statuses: list[JobStatus] | None = None, limit: int = 25
    ) -> list[dict[str, Any]]:
        """Aggregate jobs by a top-level metadata_ key (JSONB/JSON1)."""
        rows = self.repo.get_metadata_key_counts(key, statuses=statuses, limit=limit)
        return [{"value": value, "count": count} for value, count in rows]

    async def search_jobs(self, query: str, *, limit: int = 25) -> list[dict[str, Any]]:
        """Full-text search over job prompts (tsvector on Postgres, LIKE on SQLite)."""
        jobs = self.repo.search_prompts(query, limit=limit)
        return [self._job_to_dict(job) for job in jobs]
    
    async def update_job(self, job_id: str, event_extra: dict | None = None, **updates) -> Job:
        """
        Update a job.
        
        Args:
            job_id: Job ID
            event_extra: Optional dict merged into the emitted event payload
                (used to carry rich fields like type/chat_id/content on completion).
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
        active_states = {JobStatus.SENT_TO_PROVIDER, JobStatus.CONNECTED, JobStatus.PRE_GENERATION, JobStatus.GENERATING, JobStatus.POST_PROCESSING}
        status = updates.get("status")
        
        # Enforce Finite State Machine transitions
        if status and status != job.status:
            allowed = JOB_STATUS_TRANSITIONS.get(job.status, set())
            if status not in allowed:
                logger.warning(
                    "invalid_fsm_transition", 
                    job_id=job_id, 
                    from_status=job.status, 
                    to_status=status
                )
                # Ignore invalid transitions (e.g. updating a cancelled job to completed)
                updates.pop("status")
                status = None

        if status in active_states and not job.started_at:
            updates["started_at"] = datetime.now(timezone.utc)
        elif status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            updates["completed_at"] = datetime.now(timezone.utc)
        
        job = self.repo.update(job_id, **updates)
        
        if status:
            status_value = status.value if hasattr(status, "value") else str(status)
            logger.info("job_status_changed", job_id=job_id, status=status_value)
            if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                duration = None
                if job.started_at and job.completed_at:
                    duration = max((job.completed_at - job.started_at).total_seconds(), 0.0)
                metrics.track_job_completed(status_value, duration)
        
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
        
        await emit_job_event(event_type, {**(self._job_to_dict(job)), **(event_extra or {})})
        
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
        """Clear terminal jobs while preserving active work."""
        if self.get_running_jobs():
            raise ValidationError("Cannot clear jobs while active jobs exist")
        count = self.repo.delete_all()
        logger.info("jobs_cleared", count=count)
        return count
    
    def get_pending_jobs(self) -> list[Job]:
        """Get all pending jobs in FIFO order."""
        return self.repo.get_pending()
    
    def get_running_jobs(self) -> list[Job]:
        """Get all running/processing jobs."""
        active_states = [JobStatus.SENT_TO_PROVIDER, JobStatus.CONNECTED, JobStatus.PRE_GENERATION, JobStatus.GENERATING, JobStatus.POST_PROCESSING, JobStatus.RETRYING]
        return self.repo.get_by_statuses(active_states)

    def get_pending_queue_items(self) -> list[JobQueueItem]:
        """Get pending queue items (lightweight)."""
        return self.repo.get_queue_items([JobStatus.PENDING])

    def get_running_queue_items(self) -> list[JobQueueItem]:
        """Get running/processing queue items (lightweight)."""
        active_states = [JobStatus.SENT_TO_PROVIDER, JobStatus.CONNECTED, JobStatus.PRE_GENERATION, JobStatus.GENERATING, JobStatus.POST_PROCESSING, JobStatus.RETRYING]
        return self.repo.get_queue_items(active_states)
    
    def get_average_duration(self, task_type: str | None = None, sample_size: int = 10) -> float:
        """
        Calculate average job duration from recent completed jobs.

        Args:
            task_type: Optional task type filter ("image", "llm", ...). When None,
                averages across all types (legacy behavior).
            sample_size: Number of recent jobs to sample

        Returns:
            Average duration in seconds, or 30.0 as default if no data
        """
        if task_type is None:
            completed_jobs = self.repo.get_recently_completed(sample_size)
        else:
            from core.entities import Job
            from sqlmodel import col, select

            stmt = (
                select(Job)
                .where(Job.status == JobStatus.COMPLETED, Job.task_type == task_type)
                .order_by(col(Job.completed_at).desc())
                .limit(sample_size)
            )
            completed_jobs = list(self.session.exec(stmt).all())
        
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
    
    def get_job_stats(self) -> dict[str, int]:
        """Get job counts by status."""
        stats = self.repo.count_by_status()
        metrics.set_queue_size(stats.get("pending", 0))
        active_states = (
            JobStatus.SENT_TO_PROVIDER,
            JobStatus.CONNECTED,
            JobStatus.PRE_GENERATION,
            JobStatus.GENERATING,
            JobStatus.POST_PROCESSING,
            JobStatus.RETRYING,
        )
        metrics.set_active_jobs(sum(stats.get(state.value, 0) for state in active_states))
        return stats
    
    def get_job_stats_detailed(self, days: int = 7) -> dict[str, Any]:
        """
        Get comprehensive job statistics in a single optimized query.
        More efficient than multiple separate count/average queries.
        
        Args:
            days: Number of days to look back for statistics (default 7)
            
        Returns:
            Dict with 'by_status', 'total', 'avg_durations' keys
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        rows = self.session.exec(
            select(Job.status, Job.started_at, Job.completed_at)
            .where(Job.created_at > cutoff)
        ).all()
        
        by_status: dict[str, int] = {}
        durations: dict[str, list[float]] = {}
        
        for status, started_at, completed_at in rows:
            status_str = status.value if hasattr(status, 'value') else status
            by_status[status_str] = by_status.get(status_str, 0) + 1
            if started_at and completed_at:
                durations.setdefault(status_str, []).append(
                    (completed_at - started_at).total_seconds()
                )
        
        avg_durations = {
            status: round(sum(durs) / len(durs), 2)
            for status, durs in durations.items()
            if durs
        }
        
        return {
            'by_status': by_status,
            'total': sum(by_status.values()),
            'avg_durations': avg_durations,
            'period_days': days
        }
    
    def _job_to_dict(self, job: Job) -> dict[str, Any]:
        """Convert job to dictionary for API responses."""
        return {
            "id": job.id,
            "task_type": job.task_type,
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
