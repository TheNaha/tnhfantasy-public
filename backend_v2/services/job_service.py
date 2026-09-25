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

# ---------------------------------------------------------------------------
# Job diagnostics
# ---------------------------------------------------------------------------
# Attempt history, failure kind and retry linkage are stored in the existing
# metadata_ JSON column under a reserved key. This keeps the diagnostic payload
# available without a schema migration, and legacy rows simply report an empty
# history instead of failing to load.
JOB_DIAGNOSTICS_KEY = "diagnostics"

# Bound the stored attempt history so a job that fails over across many
# providers cannot grow its metadata row without limit.
MAX_TRACKED_ATTEMPTS = 20

# Error strings are truncated on write to keep the JSON column small.
MAX_ERROR_DETAIL_LENGTH = 500

# A job still sitting in an active state after this long is assumed wedged
# (worker crash, provider hang) and is failed by recovery instead of blocking
# the queue forever.
STALE_JOB_TIMEOUT_SECONDS = 300
STALE_JOB_ERROR = "Server restart during processing - job timed out"

# Failure kinds recorded on the job when it fails, so the diagnostics view can
# group failures without parsing free-text error messages.
FAILURE_STALE = "stale_recovery"
FAILURE_TIMEOUT = "timeout"
FAILURE_NO_PROVIDERS = "no_providers"
FAILURE_PROVIDERS_EXHAUSTED = "providers_exhausted"
FAILURE_PROVIDER_ERROR = "provider_error"
FAILURE_PROVIDER_UNAVAILABLE = "provider_unavailable"
FAILURE_FINALIZATION = "finalization_failed"
FAILURE_UNEXPECTED = "unexpected"
FAILURE_CANCELLED = "cancelled"
FAILURE_UNKNOWN = "unknown"

# States in which a worker has picked the job up and it is no longer queued.
ACTIVE_JOB_STATUSES = (
    JobStatus.SENT_TO_PROVIDER,
    JobStatus.CONNECTED,
    JobStatus.PRE_GENERATION,
    JobStatus.GENERATING,
    JobStatus.POST_PROCESSING,
    JobStatus.RETRYING,
)

# A job can be cancelled until it reaches a terminal state.
CANCELLABLE_JOB_STATUSES = (JobStatus.PENDING, *ACTIVE_JOB_STATUSES)

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


def as_utc(value: datetime) -> datetime:
    """Return `value` as a timezone-aware UTC datetime.

    Job timestamps live in naive columns (SQLite and PostgreSQL
    `TIMESTAMP WITHOUT TIME ZONE` both hand back naive datetimes), so arithmetic
    against an aware `datetime.now(timezone.utc)` raises TypeError. Normalize
    before comparing.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def classify_job_error(message: str | None) -> str | None:
    """Best-effort failure kind for an error string recorded before failure
    kinds were tracked (legacy rows). Ordered most specific first."""
    if not message:
        return None

    text = str(message).lower()
    if FAILURE_STALE.replace("_", " ") in text or "server restart" in text:
        return FAILURE_STALE
    if "timed out" in text or "timeout" in text:
        return FAILURE_TIMEOUT
    if "no available providers" in text:
        return FAILURE_NO_PROVIDERS
    if "all providers failed" in text or "exhausted retries" in text:
        return FAILURE_PROVIDERS_EXHAUSTED
    if "cancelled" in text or "canceled" in text:
        return FAILURE_CANCELLED
    return FAILURE_UNKNOWN


def extract_job_model(metadata: dict[str, Any] | None) -> str | None:
    """Resolve the model a job ran on from its metadata, if recorded."""
    if not isinstance(metadata, dict):
        return None

    for key in ("checkpoint", "model", "llm_model", "scene_checkpoint", "generator_checkpoint"):
        value = metadata.get(key)
        if isinstance(value, dict):
            value = value.get("name")
        if isinstance(value, str) and value.strip():
            return value
    return None


def get_stored_diagnostics(job: Job) -> dict[str, Any]:
    """Read the reserved diagnostics block out of a job's metadata."""
    metadata = job.metadata_ if isinstance(job.metadata_, dict) else {}
    stored = metadata.get(JOB_DIAGNOSTICS_KEY)
    return stored if isinstance(stored, dict) else {}


def job_duration_seconds(job: Job) -> float | None:
    """Wall-clock seconds a job spent between started_at and completed_at."""
    if not job.started_at or not job.completed_at:
        return None
    elapsed = (as_utc(job.completed_at) - as_utc(job.started_at)).total_seconds()
    return round(max(elapsed, 0.0), 3)


def is_job_retryable(job: Job) -> bool:
    """A failed job can be retried when it still carries a workflow to re-run."""
    return job.status == JobStatus.FAILED and bool(job.workflow)


def build_job_diagnostics(job: Job) -> dict[str, Any]:
    """Diagnostic view of a job: provider, model, attempts, timing and error.

    Returned for every job payload so both the job detail modal and the failed
    job diagnostics view can explain *why* something failed without re-deriving
    state from log lines.
    """
    stored = get_stored_diagnostics(job)
    attempts = [entry for entry in (stored.get("attempts") or []) if isinstance(entry, dict)]
    failure_kind = stored.get("failure_kind")
    error_message = job.error

    return {
        "provider_id": job.provider_id,
        "last_provider_id": stored.get("last_provider_id"),
        "model": extract_job_model(job.metadata_ if isinstance(job.metadata_, dict) else None),
        "attempt_count": int(stored.get("attempt_count") or len(attempts)),
        "attempts": attempts,
        "last_outcome": stored.get("last_outcome"),
        "error_type": failure_kind or classify_job_error(error_message),
        "error_message": error_message,
        "duration_seconds": job_duration_seconds(job),
        "is_stale": failure_kind == FAILURE_STALE,
        "stale_seconds": stored.get("stale_seconds"),
        "is_retryable": is_job_retryable(job),
        "retry_of": stored.get("retry_of"),
        "failure_kind": failure_kind,
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

    async def get_failed_jobs(
        self, *, limit: int = 25, offset: int = 0, task_type: str | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        """List failed jobs (newest first) with diagnostics attached.

        Returns the serialized jobs and the total number of failed jobs
        matching the filter.
        """
        jobs, total = self.repo.get_failed(limit=limit, offset=offset, task_type=task_type)
        return [self._job_to_dict(job) for job in jobs], total

    def summarize_failed_jobs(self, jobs: list[dict[str, Any]]) -> dict[str, Any]:
        """Group a page of serialized failed jobs by cause/provider/task type.

        The counters describe the supplied page (not every historical failure);
        the caller passes the page it just returned alongside the global total.
        """
        by_error_type: dict[str, int] = {}
        by_provider: dict[str, int] = {}
        by_task_type: dict[str, int] = {}

        for job in jobs:
            diagnostics = job.get("diagnostics") or {}
            error_type = diagnostics.get("error_type") or FAILURE_UNKNOWN
            by_error_type[error_type] = by_error_type.get(error_type, 0) + 1

            provider = job.get("provider_id") or "(unassigned)"
            by_provider[provider] = by_provider.get(provider, 0) + 1

            task_type = job.get("task_type") or "unknown"
            by_task_type[task_type] = by_task_type.get(task_type, 0) + 1

        return {
            "by_error_type": by_error_type,
            "by_provider": by_provider,
            "by_task_type": by_task_type,
            "retryable": sum(
                1 for job in jobs if (job.get("diagnostics") or {}).get("is_retryable")
            ),
        }

    async def record_attempt(
        self,
        job_id: str,
        *,
        provider_id: str | None,
        attempt: int,
        outcome: str,
        error: str | None = None,
        duration_seconds: float | None = None,
    ) -> Job | None:
        """Append one provider attempt to the job's diagnostics history.

        Called by the job runner once per provider attempt so a failed job can
        explain which providers were tried, in what order, and how long each
        took. Diagnostics are best-effort: a failure to record must never break
        job execution, so errors are swallowed after logging.
        """
        job = self.repo.get(job_id)
        if not job:
            return None

        try:
            metadata = dict(job.metadata_) if isinstance(job.metadata_, dict) else {}
            diagnostics = dict(metadata.get(JOB_DIAGNOSTICS_KEY) or {})
            attempts = [
                entry for entry in (diagnostics.get("attempts") or []) if isinstance(entry, dict)
            ]
            attempts.append(
                {
                    "provider_id": provider_id,
                    "attempt": attempt,
                    "outcome": outcome,
                    "error": (error[:MAX_ERROR_DETAIL_LENGTH] if error else None),
                    "duration_seconds": duration_seconds,
                    "at": datetime.now(timezone.utc).isoformat(),
                }
            )
            diagnostics["attempts"] = attempts[-MAX_TRACKED_ATTEMPTS:]
            diagnostics["attempt_count"] = int(diagnostics.get("attempt_count") or 0) + 1
            diagnostics["last_provider_id"] = provider_id
            diagnostics["last_outcome"] = outcome
            if error:
                diagnostics["failure_kind"] = FAILURE_PROVIDER_ERROR
                diagnostics["failed_at"] = datetime.now(timezone.utc).isoformat()

            metadata[JOB_DIAGNOSTICS_KEY] = diagnostics
            job.metadata_ = metadata
            self.session.add(job)
            self.session.commit()
            self.session.refresh(job)
            return job
        except Exception as exc:  # diagnostics must never break execution
            try:
                self.session.rollback()
            except Exception:
                pass
            logger.warning("job_attempt_record_failed", job_id=job_id, error=str(exc))
            return None

    async def mark_failed(
        self,
        job_id: str,
        *,
        error: str,
        error_type: str | None = None,
        provider_id: str | None = None,
    ) -> Job:
        """Move a job to FAILED while recording *why* it failed.

        Preferred over a bare `update_job(status=FAILED, error=...)` so the
        diagnostics view can group failures by cause. `error_type` defaults to
        classifying the error message; pass it explicitly only when the exact
        cause is known.
        """
        job = self.repo.get(job_id)
        if not job:
            logger.warning("job_mark_failed_not_found", job_id=job_id)
            raise NotFoundError("Job", job_id)

        metadata = dict(job.metadata_) if isinstance(job.metadata_, dict) else {}
        diagnostics = dict(metadata.get(JOB_DIAGNOSTICS_KEY) or {})
        diagnostics["failure_kind"] = error_type or classify_job_error(error) or FAILURE_UNKNOWN
        diagnostics["failed_at"] = datetime.now(timezone.utc).isoformat()
        metadata[JOB_DIAGNOSTICS_KEY] = diagnostics

        updates: dict[str, Any] = {
            "status": JobStatus.FAILED,
            "error": error[:MAX_ERROR_DETAIL_LENGTH],
            "metadata_": metadata,
        }
        if provider_id:
            updates["provider_id"] = provider_id
        return await self.update_job(job_id, **updates)

    async def fail_stale_running_jobs(
        self, timeout_seconds: int = STALE_JOB_TIMEOUT_SECONDS
    ) -> list[Job]:
        """Fail jobs wedged in an active state for longer than the timeout.

        Used by startup recovery and by `POST /api/jobs/recover` so a job whose
        worker died is never left blocking the queue. Rows are written directly
        (not through `update_job`) because the FSM deliberately forbids
        active -> FAILED transitions; recovery has to override that.
        """
        now = datetime.now(timezone.utc)
        stale: list[tuple[Job, float]] = []

        for job in self.get_running_jobs():
            if not job.started_at:
                continue
            elapsed = (now - as_utc(job.started_at)).total_seconds()
            if elapsed > timeout_seconds:
                stale.append((job, elapsed))

        if not stale:
            return []

        try:
            for job, elapsed in stale:
                job.status = JobStatus.FAILED
                job.error = STALE_JOB_ERROR
                job.completed_at = now
                job.updated_at = now

                metadata = dict(job.metadata_) if isinstance(job.metadata_, dict) else {}
                diagnostics = dict(metadata.get(JOB_DIAGNOSTICS_KEY) or {})
                diagnostics["failure_kind"] = FAILURE_STALE
                diagnostics["stale_seconds"] = round(elapsed, 3)
                diagnostics["failed_at"] = now.isoformat()
                metadata[JOB_DIAGNOSTICS_KEY] = diagnostics
                job.metadata_ = metadata

                self.session.add(job)
            self.session.commit()
        except Exception as exc:
            try:
                self.session.rollback()
            except Exception:
                pass
            logger.error("job_recovery_atomic_update_failed", error=str(exc), exc_info=True)
            return []

        failed_jobs: list[Job] = []
        for job, elapsed in stale:
            logger.warning("job_recovery_timeout", job_id=job.id, elapsed=f"{elapsed:.0f}s")
            try:
                await emit_job_event(EventType.JOB_FAILED, self._job_to_dict(job))
            except Exception as exc:
                logger.warning("job_recovery_emit_failed", job_id=job.id, error=str(exc))
            failed_jobs.append(job)

        return failed_jobs

    async def cancel_job(self, job_id: str, *, reason: str | None = None) -> Job:
        """Cancel a queued or in-flight job.

        Terminal jobs are rejected: a completed/failed/cancelled job has no
        provider work left to stop. For in-flight jobs the caller is
        responsible for signalling the provider (see
        `services.job_processing.cancel_job`); this only records the
        terminal state so the runner stops on its next status check.
        """
        job = await self.get_job(job_id)

        if job.status not in CANCELLABLE_JOB_STATUSES:
            raise ValidationError(
                f"Job is {job.status.value} and cannot be cancelled", field="status"
            )

        return await self.update_job(
            job_id,
            status=JobStatus.CANCELLED,
            message=reason or "Cancelled by user",
        )

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

        # Annotate failures with a machine-readable cause so the diagnostics
        # view can group them without parsing free-text errors. Callers that
        # know the exact cause use `mark_failed`; everything else is classified
        # from the message. Skipped when the caller supplied its own metadata so
        # an explicit block is never overwritten.
        if status == JobStatus.FAILED and "metadata_" not in updates:
            failure_kind = classify_job_error(updates.get("error") or job.error)
            if failure_kind:
                metadata = dict(job.metadata_) if isinstance(job.metadata_, dict) else {}
                diagnostics = dict(metadata.get(JOB_DIAGNOSTICS_KEY) or {})
                if not diagnostics.get("failure_kind"):
                    diagnostics["failure_kind"] = failure_kind
                    diagnostics.setdefault("failed_at", datetime.now(timezone.utc).isoformat())
                    metadata[JOB_DIAGNOSTICS_KEY] = diagnostics
                    updates["metadata_"] = metadata

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
        return self.repo.get_by_statuses(list(ACTIVE_JOB_STATUSES))

    def get_pending_queue_items(self) -> list[JobQueueItem]:
        """Get pending queue items (lightweight)."""
        return self.repo.get_queue_items([JobStatus.PENDING])

    def get_running_queue_items(self) -> list[JobQueueItem]:
        """Get running/processing queue items (lightweight)."""
        return self.repo.get_queue_items(list(ACTIVE_JOB_STATUSES))
    
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
        metrics.set_active_jobs(sum(stats.get(state.value, 0) for state in ACTIVE_JOB_STATUSES))
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
            "diagnostics": build_job_diagnostics(job),
        }
