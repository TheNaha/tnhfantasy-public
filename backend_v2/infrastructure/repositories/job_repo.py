# Job Repository - Data access layer for jobs
from datetime import datetime, timezone
import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, text
from sqlmodel import Session, col, delete, select, update

from core.dtos import JobQueueItem
from core.entities import Job, JobStatus
from core.sql_search import LIKE_ESCAPE_CHAR, like_contains

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

        stmt = select(Job).order_by(col(Job.created_at).desc(), col(Job.id).desc())
        if cursor is not None:
            stmt = stmt.where(
                (col(Job.created_at) < cursor[0])
                | ((col(Job.created_at) == cursor[0]) & (col(Job.id) < cursor[1]))
            )
        else:
            stmt = stmt.offset(offset)
        stmt = stmt.limit(limit)

        jobs = list(self.session.exec(stmt).all())

        # The queue position of a PENDING job, counted among the PENDING jobs
        # of its own task type.
        #
        # This used to be a WINDOW function over the whole PENDING set, JOINED
        # into the page query - so the database numbered every pending job in
        # the table before the LIMIT applied, and the dashboard's main view
        # was O(pending) per request. Measured on 5 000 pending jobs with a
        # 40-node workflow each: 3 506 ms for a 20-row page, against 4.2 ms
        # for the same page without it.
        #
        # It is now a SECOND, narrow query: the page is fetched on its own,
        # and only the three narrow columns the position needs are scanned -
        # never the `workflow` or `metadata_` jsonb. The scan is still
        # O(pending) rows, but it moves 3 small columns instead of two large
        # blobs, and it no longer runs for jobs that are not pending at all.
        positions = self._queue_positions_for(jobs)

        return [(job, positions.get(job.id)) for job in jobs], total

    def _queue_positions_for(self, jobs: list[Job]) -> dict[str, int]:
        """1-based queue position for the PENDING jobs in `jobs`.

        Only the task types that actually appear on the page are scanned,
        and only three narrow columns are read.
        """
        pending = [job for job in jobs if job.status == JobStatus.PENDING]
        if not pending:
            return {}

        task_types = {job.task_type for job in pending}
        rows = self.session.exec(
            select(
                Job.id,
                func.row_number()
                .over(
                    order_by=[Job.created_at, Job.id],
                    partition_by=[Job.task_type],
                )
                .label("pos"),
            )
            .where(
                Job.status == JobStatus.PENDING,
                Job.task_type.in_(task_types),
            )
        ).all()
        return {job_id: int(pos) for job_id, pos in rows}
    
    def get_pending(self, limit: int | None = None) -> list[Job]:
        """Get pending jobs, ordered by creation time (FIFO).

        `limit` bounds the result. The caller that only wants a COUNT used
        to materialise every pending row - with the full `workflow` and
        `metadata_` jsonb of each - just to take its length. Measured on
        5 000 pending jobs with a 40-node workflow each: 802 ms and 5 000
        full rows, for a number.
        """
        stmt = select(Job).where(Job.status == JobStatus.PENDING).order_by(Job.created_at)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.session.exec(stmt).all())

    def count_pending(self) -> int:
        """How many jobs are PENDING - without materialising any of them."""
        return int(
            self.session.exec(
                select(func.count()).select_from(Job).where(Job.status == JobStatus.PENDING)
            ).one()
        )

    def get_stranded_pending(
        self, cutoff: datetime
    ) -> list[Job]:
        """PENDING jobs that were never handed to the queue.

        A row with a null `enqueued_at` can never be claimed, so it can be
        found with a predicate instead of by loading every pending row and
        filtering it in Python.
        """
        stmt = (
            select(Job)
            .where(
                Job.status == JobStatus.PENDING,
                Job.enqueued_at.is_(None),
                Job.created_at < cutoff,
            )
            .order_by(Job.created_at)
        )
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

    def update_where_status(
        self, job_id: str, expected_status: JobStatus, **kwargs
    ) -> Job | None:
        """Update a job only while it is still in `expected_status`.

        The atomic form of `update`'s read-then-write, for callers that decide
        what to write from a status they read earlier. `get` is `session.get`,
        so for a long-lived Session it answers from the identity map and a
        "just read it" status can be arbitrarily old — so the read and the write
        are not one statement and anything can land between them. A cancel
        request, a recovery sweep and a second worker are all writers of the
        same row. Re-stating the status in the `WHERE` closes that window in one
        atomic statement, with no lock and no schema change.

        Returns the refreshed job, or `None` when the predicate matched no row:
        the job moved on, or was deleted. A 0-row result is not an error, it is
        the caller learning its guard was stale, so it is returned rather than
        raised.
        """
        if self.get(job_id) is None:
            return None

        values = {key: value for key, value in kwargs.items() if hasattr(Job, key)}
        values["updated_at"] = datetime.now(timezone.utc)
        stmt = (
            update(Job)
            .where(Job.id == job_id, Job.status == expected_status)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        result = self.session.exec(stmt)
        if not result.rowcount:
            return None
        self.session.commit()
        return self.get(job_id)
    
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

        The fallback needs both halves of the escaping rule and had neither:
        `f"%{query}%"` left `%` and `_` in a user's search term live as
        wildcards (so `100%` matched `100 percent`), and the pattern was bound
        to a raw `text()` fragment with no `ESCAPE` clause, which is invisible
        to the `.like()` guard in `tests/test_like_pattern_escaping.py`.
        `core.sql_search.like_contains` supplies the first half; the clause
        below supplies the second — escaping alone matches nothing.
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
                f"""
                SELECT jobs.*
                FROM jobs
                WHERE json_extract(metadata_, '$.prompt') LIKE :like
                    ESCAPE '{LIKE_ESCAPE_CHAR}'
                ORDER BY created_at DESC
                LIMIT :limit
                """
            )
            rows = self.session.execute(
                stmt, {"like": like_contains(query), "limit": int(limit)}
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
                col = Job.__table__.columns[key]
                # Determine the effective python type. For SQLAlchemy 2.1+,
                # `UTCDateTime` (a TypeDecorator) returns `object` for
                # `python_type` rather than delegating to its `DateTime` impl.
                # Check the impl chain to get the real python type.
                col_type = None
                try:
                    col_type = col.type.python_type
                except (NotImplementedError, AttributeError):
                    pass
                # `python_type` returning `object` is useless for type
                # discrimination — fall through to the impl.
                if col_type is None or col_type is object:
                    if hasattr(col.type, "impl"):
                        try:
                            col_type = col.type.impl.python_type
                        except (NotImplementedError, AttributeError):
                            pass
                # `python_type` can return `object` instead of `datetime`
                # (e.g. SQLAlchemy 2.1's UTCDateTime TypeDecorator). Check
                # issubclass as well to catch datetime subclasses.
                if col_type is datetime or (
                    col_type is not None
                    and isinstance(col_type, type)
                    and issubclass(col_type, datetime)
                ):
                    raw = datetime.fromisoformat(raw)
                elif col_type in (dict, list) or raw.lstrip().startswith(("{", "[")):
                    try:
                        raw = json.loads(raw)
                    except (ValueError, TypeError):
                        pass
            setattr(job, key, raw)
        return job

