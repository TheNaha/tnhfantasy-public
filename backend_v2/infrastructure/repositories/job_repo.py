# Job Repository - Data access layer for jobs
from sqlmodel import Session, select, col, delete
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
    
    def get_all(self, limit: int = 20, offset: int = 0) -> tuple[List[tuple[Job, Optional[int]]], int]:
        """
        Get jobs with pagination and queue positions.
        
        Returns:
            Tuple of (results list of (Job, queue_position), total count)
        """
        total = self.session.exec(select(func.count()).select_from(Job)).one()
        
        pending_subq = (
            select(
                Job.id,
                func.row_number().over(order_by=[Job.created_at, Job.id]).label("queue_position")
            )
            .where(Job.status == JobStatus.PENDING)
            .subquery()
        )
        
        stmt = (
            select(Job, pending_subq.c.queue_position)
            .outerjoin(pending_subq, Job.id == pending_subq.c.id)
            .order_by(col(Job.created_at).desc())
            .offset(offset)
            .limit(limit)
        )
        
        results = list(self.session.exec(stmt).all())
        return results, total
    
    def get_pending(self) -> List[Job]:
        """Get all pending jobs, ordered by creation time (FIFO)."""
        stmt = select(Job).where(Job.status == JobStatus.PENDING).order_by(Job.created_at)
        return list(self.session.exec(stmt).all())



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
        count = self.session.scalar(select(func.count()).select_from(Job))
        self.session.exec(delete(Job))
        self.session.commit()
        return count or 0
    
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

