# Job Repository - Data access layer for jobs
from datetime import datetime, timezone
import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, text
from sqlmodel import Session, col, delete, select, update

from core.dtos import JobQueueItem
from core.entities import Job, JobStatus

# Far more than any queue a person can act on, and it bounds the `metadata_`
# jsonb this query pulls. See `get_queue_items`.
MAX_QUEUE_ITEMS = 500


class JobRepository:
    """Data access layer for Job entities."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def create(self, workflow: dict[str, Any], metadata: dict[str, Any], task_type: str = "image") -> Job:
        """Create a new job."""
        job = Job(
            task_type=task_type,
            workflow=workflow,
            metadata_=metadata,
            status=JobStatus.PENDING
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job
    
    def get(self, job_id: str) -> Job | None:
        """Get a job by ID."""
        return self.session.get(Job, job_id)
    
    def get_all(
        self,
        limit: int = 20,
        offset: int = 0,
        cursor: tuple[datetime, str] | None = None,
    ) -> tuple[list[tuple[Job, int | None]], int]:
        """
        Get jobs with pagination and queue positions.

        Keyset pagination: when `cursor` is provided (a (created_at, id) tuple
        from the last row of a previous page), rows are fetched with a seek
        predicate instead of OFFSET — O(log n) page fetches on PostgreSQL.
        Falls back to OFFSET pagination when no cursor is given.

        Returns:
            Tuple of (results list of (Job, queue_position), total count)
        """
        total = self.session.exec(select(func.count()).select_from(Job)).one()
        
        pending_subq = (
            select(
                Job.id,
                func.row_number()
                .over(
                    order_by=[Job.created_at, Job.id],
                    partition_by=[Job.task_type],
                )
                .label("queue_position")
            )
            .where(Job.status == JobStatus.PENDING)
            .subquery()
        )
        
        stmt = (
            select(Job, pending_subq.c.queue_position)
            .outerjoin(pending_subq, Job.id == pending_subq.c.id)
            .order_by(col(Job.created_at).desc(), col(Job.id).desc())
        )
        if cursor is not None:
            stmt = stmt.where(
                (col(Job.created_at) < cursor[0])
                | ((col(Job.created_at) == cursor[0]) & (col(Job.id) < cursor[1]))
            )
        else:
            stmt = stmt.offset(offset)
        stmt = stmt.limit(limit)
        
        results = list(self.session.exec(stmt).all())
        return results, total
    
    def get_pending(self) -> list[Job]:
        """Get all pending jobs, ordered by creation time (FIFO)."""
        stmt = select(Job).where(Job.status == JobStatus.PENDING).order_by(Job.created_at)
        return list(self.session.exec(stmt).all())



    def get_by_status(self, status: JobStatus) -> list[Job]:
        """Get all jobs with a specific status."""
        stmt = select(Job).where(Job.status == status)
        return list(self.session.exec(stmt).all())
    
    def get_by_statuses(self, statuses: list[JobStatus]) -> list[Job]:
        """Get all jobs with any of the specified statuses."""
        stmt = select(Job).where(Job.status.in_(statuses)).order_by(Job.created_at)
        return list(self.session.exec(stmt).all())

    def get_failed(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
        task_type: str | None = None,
        include_acknowledged: bool = False,
    ) -> tuple[list[Job], int]:
        """Get failed jobs newest-first, plus the total failure count.

        Backs the failed-job diagnostics view; the `task_type` filter is
        applied in SQL so the totals line up with the returned page.

        Acknowledged jobs are hidden unless asked for. They are filtered in SQL
        rather than in the route so `total` — which drives the panel's count —
        counts the same set the page returns.
        """
        filters = [Job.status == JobStatus.FAILED]
        if task_type:
            filters.append(Job.task_type == task_type)
        if not include_acknowledged:
            filters.append(Job.acknowledged_at.is_(None))

        total = self.session.exec(select(func.count()).select_from(Job).where(*filters)).one()

        stmt = (
            select(Job)
            .where(*filters)
            .order_by(col(Job.created_at).desc(), col(Job.id).desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.exec(stmt).all()), total

    def set_acknowledged(self, job_ids: Sequence[str], acknowledged: bool) -> int:
        """Set or clear `acknowledged_at` on the given jobs. Idempotent.

        Returns the number of rows actually changed, so a caller can tell a
        no-op from a real update.
        """
        if not job_ids:
            return 0
        value = datetime.now(timezone.utc) if acknowledged else None
        stmt = (
            update(Job)
            .where(Job.id.in_(list(job_ids)))
            .values(acknowledged_at=value, updated_at=datetime.now(timezone.utc))
        )
        result = self.session.exec(stmt)
        self.session.commit()
        return result.rowcount or 0

    def count_acknowledged_failed(self, task_type: str | None = None) -> int:
        """Count dismissed failures, so the UI can offer to show them again."""
        filters = [Job.status == JobStatus.FAILED, Job.acknowledged_at.is_not(None)]
        if task_type:
            filters.append(Job.task_type == task_type)
        return self.session.exec(
            select(func.count()).select_from(Job).where(*filters)
        ).one()

    def set_acknowledged_filtered(
        self, *, acknowledged: bool, task_type: str | None = None
    ) -> int:
        """Acknowledge (or un-acknowledge) every FAILED job matching the filter.

        Deliberately ignores the current acknowledged state, so "dismiss all" is
        idempotent and "show everything again" restores the full set rather than
        only the un-acknowledged part.
        """
        value = datetime.now(timezone.utc) if acknowledged else None
        filters = [Job.status == JobStatus.FAILED]
        if task_type:
            filters.append(Job.task_type == task_type)
        stmt = (
            update(Job)
            .where(*filters)
            .values(acknowledged_at=value, updated_at=datetime.now(timezone.utc))
        )
        result = self.session.exec(stmt)
        self.session.commit()
        return result.rowcount or 0

    def get_queue_items(
        self, statuses: list[JobStatus], limit: int = MAX_QUEUE_ITEMS
    ) -> list[JobQueueItem]:
        """
        Get lightweight queue items for specified statuses.
        Avoids loading heavy workflow JSON.

        `Job.metadata_` is a jsonb blob and is still selected here — the ETA logic
        reads a handful of keys out of it — so an uncapped query meant one
        `GET /api/v2/jobs/queue` pulled the metadata of every pending AND every
        active job in the system, twice over (it calls this for pending and then
        for running). The cap is well above any queue a person can act on, and
        the response carries a `truncated` signal so the UI can say so rather
        than silently showing a short queue.
        """
        stmt = (
            select(
                Job.id,
                Job.status,
                Job.created_at,
                Job.overall_progress,
                Job.metadata_,
                Job.task_type,
            )
            .where(Job.status.in_(statuses))
            .order_by(Job.created_at)
            .limit(limit + 1)
        )

        rows = self.session.exec(stmt).all()
        if len(rows) > limit:
            rows = rows[:limit]

        return [
            JobQueueItem(
                id=row[0],
                status=row[1],
                created_at=row[2],
                overall_progress=row[3],
                metadata_=row[4] or {},
                task_type=row[5] or "image",
            )
            for row in rows
        ]
    
    def get_recently_completed(self, limit: int = 10) -> list[Job]:
        """Get recently completed jobs, ordered by completion time descending."""
        stmt = (
            select(Job)
            .where(Job.status == JobStatus.COMPLETED)
            .order_by(col(Job.completed_at).desc())
            .limit(limit)
        )
        return list(self.session.exec(stmt).all())
    
    def update(self, job_id: str, **kwargs) -> Job | None:
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
    
    def count_by_status(self) -> dict[str, int]:
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

    def get_metadata_key_counts(
        self, key: str, *, statuses: list[JobStatus] | None = None, limit: int = 25
    ) -> list[tuple[str, int]]:
        """
        Aggregate jobs by a top-level metadata_ key (e.g. "model").

        Uses JSONB path access on PostgreSQL and the JSON1 extension on SQLite,
        so the same query shape works on both backends. Statuses come from the
        JobStatus enum (controlled vocabulary) so they are inlined safely.
        """
        status_clause = ""
        if statuses:
            # The status column stores the enum member NAME (COMPLETED) on both
            # PostgreSQL (native enum) and SQLite (VARCHAR via SQLAlchemy Enum).
            quoted = ", ".join(f"'{s.name}'" for s in statuses)
            status_clause = f"AND status IN ({quoted})"

        dialect = self.session.bind.dialect.name if self.session.bind is not None else "sqlite"
        if dialect == "postgresql":
            # GIN-index-friendly JSONB containment query
            stmt = text(
                f"""
                SELECT COALESCE(metadata_->>'{key}', '(none)') AS value,
                       COUNT(*) AS count
                FROM jobs
                WHERE metadata_ ? '{key}'
                {status_clause}
                GROUP BY 1
                ORDER BY count DESC
                LIMIT {int(limit)}
                """
            )
            rows = self.session.execute(stmt).all()
        else:
            # SQLite JSON1 extension
            stmt = text(
                f"""
                SELECT COALESCE(json_extract(metadata_, '$.{key}'), '(none)') AS value,
                       COUNT(*) AS count
                FROM jobs
                WHERE json_extract(metadata_, '$.{key}') IS NOT NULL
                {status_clause}
                GROUP BY 1
                ORDER BY count DESC
                LIMIT {int(limit)}
                """
            )
            rows = self.session.execute(stmt).all()

        return [(str(row[0]), int(row[1])) for row in rows]

    def search_prompts(self, query: str, *, limit: int = 25) -> list[Job]:
        """
        Full-text search over job prompts.

        PostgreSQL: index-backed tsvector match (generated prompt_tsv column)
        ranked by relevance. SQLite: LIKE fallback over the JSON1 extraction.
        """
        if not query:
            return []

        dialect = self.session.bind.dialect.name if self.session.bind is not None else "sqlite"
        if dialect == "postgresql":
            stmt = text(
                """
                SELECT jobs.*
                FROM jobs
                WHERE prompt_tsv @@ plainto_tsquery('english', :q)
                ORDER BY ts_rank(prompt_tsv, plainto_tsquery('english', :q)) DESC,
                         created_at DESC
                LIMIT :limit
                """
            )
            rows = self.session.execute(stmt, {"q": query, "limit": int(limit)}).all()
        else:
            stmt = text(
                """
                SELECT jobs.*
                FROM jobs
                WHERE json_extract(metadata_, '$.prompt') LIKE :like
                ORDER BY created_at DESC
                LIMIT :limit
                """
            )
            rows = self.session.execute(
                stmt, {"like": f"%{query}%", "limit": int(limit)}
            ).all()

        return [self._row_to_job(row) for row in rows]

    @staticmethod
    def _row_to_job(row) -> Job:
        """Rehydrate a Job from a raw column select (SQLAlchemy Row)."""
        job = Job()
        for key in Job.__table__.columns.keys():
            if key not in row._mapping:
                continue
            raw = row._mapping[key]
            if key == "status" and isinstance(raw, str):
                raw = JobStatus[raw]
            elif isinstance(raw, str):
                try:
                    col_type = Job.__table__.columns[key].type.python_type
                except (NotImplementedError, AttributeError):
                    col_type = None
                if col_type is datetime:
                    raw = datetime.fromisoformat(raw)
                elif col_type is dict:
                    raw = json.loads(raw)
            setattr(job, key, raw)
        return job

