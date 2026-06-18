# Job Repository - Data access layer for jobs
from sqlmodel import Session, select, col
from sqlalchemy import func, or_, and_
from sqlalchemy.orm import aliased
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from core.entities import Job, JobStatus
from core.dtos import JobQueueItem


class JobRepository:
    """Data access layer for Job entities."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def create(self, workflow: Dict[str, Any], metadata: Dict[str, Any]) -> Job:
        """Create a new job."""
        job = Job(
            workflow=workflow,
            metadata_=metadata,
            status=JobStatus.PENDING
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job
    
    def get(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        return self.session.get(Job, job_id)
    
    def get_all(self, limit: int = 20, offset: int = 0) -> tuple[List[Job], int]:
        """
        Get jobs with pagination.
        
        Returns:
            Tuple of (jobs list, total count)
        """
        # Get total count efficiently using COUNT()
        total = self.session.exec(select(func.count()).select_from(Job)).one()
        
        # Get paginated results, sorted by created_at descending
        stmt = select(Job).order_by(col(Job.created_at).desc()).offset(offset).limit(limit)
        jobs = list(self.session.exec(stmt).all())
        
        return jobs, total
    
    def get_pending(self) -> List[Job]:
        """Get all pending jobs, ordered by creation time (FIFO)."""
        stmt = select(Job).where(Job.status == JobStatus.PENDING).order_by(Job.created_at)
        return list(self.session.exec(stmt).all())

    def get_queue_position(self, job: Job) -> int:
        """
        Get the queue position for a pending job.
        Returns the number of pending jobs created before this one + 1.
        Returns 0 if job is not pending or not found.
        """
        if not job or job.status != JobStatus.PENDING:
            return 0

        # Count pending jobs created before this one
        stmt = select(func.count()).select_from(Job).where(
            Job.status == JobStatus.PENDING,
            or_(
                Job.created_at < job.created_at,
                and_(Job.created_at == job.created_at, Job.id < job.id)
            )
        )
        count = self.session.exec(stmt).one()
        return count + 1
    
    def get_queue_positions(self, job_ids: List[str]) -> Dict[str, int]:
        """
        Get queue positions for multiple pending jobs efficiently.
        Returns a dictionary mapping job ID to queue position.
        """
        if not job_ids:
            return {}

        JobAlias = aliased(Job)

        # Subquery to count jobs created before the current job
        subq = (
            select(func.count())
            .select_from(JobAlias)
            .where(
                JobAlias.status == JobStatus.PENDING,
                or_(
                    JobAlias.created_at < Job.created_at,
                    and_(JobAlias.created_at == Job.created_at, JobAlias.id < Job.id)
                )
            )
            .correlate(Job)
            .scalar_subquery()
        )

        # Main query to get job ID and its position (count + 1)
        stmt = select(Job.id, subq + 1).where(Job.id.in_(job_ids))
        results = self.session.exec(stmt).all()

        return {row[0]: row[1] for row in results}

    def get_by_status(self, status: JobStatus) -> List[Job]:
        """Get all jobs with a specific status."""
        stmt = select(Job).where(Job.status == status)
        return list(self.session.exec(stmt).all())
    
    def get_by_statuses(self, statuses: List[JobStatus]) -> List[Job]:
        """Get all jobs with any of the specified statuses."""
        stmt = select(Job).where(Job.status.in_(statuses)).order_by(Job.created_at)
        return list(self.session.exec(stmt).all())

    def get_queue_items(self, statuses: List[JobStatus]) -> List[JobQueueItem]:
        """
        Get lightweight queue items for specified statuses.
        Avoids loading heavy workflow JSON.
        """
        stmt = (
            select(
                Job.id,
                Job.status,
                Job.created_at,
                Job.overall_progress,
                Job.metadata_
            )
            .where(Job.status.in_(statuses))
            .order_by(Job.created_at)
        )

        rows = self.session.exec(stmt).all()

        return [
            JobQueueItem(
                id=row[0],
                status=row[1],
                created_at=row[2],
                overall_progress=row[3],
                metadata_=row[4] or {}
            )
            for row in rows
        ]
    
    def get_recently_completed(self, limit: int = 10) -> List[Job]:
        """Get recently completed jobs, ordered by completion time descending."""
        stmt = (
            select(Job)
            .where(Job.status == JobStatus.COMPLETED)
            .order_by(col(Job.completed_at).desc())
            .limit(limit)
        )
        return list(self.session.exec(stmt).all())
    
    def update(self, job_id: str, **kwargs) -> Optional[Job]:
        """Update a job with new values."""
        job = self.get(job_id)
        if not job:
            return None
        
        for key, value in kwargs.items():
            if hasattr(job, key):
                setattr(job, key, value)
        
        job.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(job)
        return job
    
    def delete(self, job_id: str) -> bool:
        """Delete a job."""
        job = self.get(job_id)
        if not job:
            return False
        
        self.session.delete(job)
        self.session.commit()
        return True
    
    def delete_all(self) -> int:
        """Delete all jobs. Returns count of deleted jobs."""
        jobs = self.session.exec(select(Job)).all()
        count = len(jobs)
        for job in jobs:
            self.session.delete(job)
        self.session.commit()
        return count
    
    def count_by_status(self) -> Dict[str, int]:
        """Get count of jobs by status using efficient GROUP BY query."""
        # Single query with GROUP BY instead of N separate queries
        stmt = select(Job.status, func.count()).group_by(Job.status)
        rows = self.session.exec(stmt).all()
        
        # Initialize all statuses to 0
        result = {status.value: 0 for status in JobStatus}
        # Update with actual counts
        for status, count in rows:
            result[status.value] = count
        return result

