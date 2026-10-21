# Job Service - Business logic for job management
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from collections.abc import Sequence

from sqlmodel import Session, select

from core.dtos import JobQueueItem
from core.entities import ACTIVE_JOB_STATUSES, Job, JobStatus
from core.events import EventType, emit_job_event
from core.exceptions import NotFoundError, ValidationError
from infrastructure.logging import job_logger
from infrastructure.metrics import metrics
from infrastructure.db_executor import run_db
from infrastructure.repositories import JobRepository

# Imported lazily inside the functions that need it: `config` reads the
# settings module, and importing it at module scope made the import graph
# of every service depend on it.

logger = job_logger()

# ---------------------------------------------------------------------------
# Job diagnostics
# ---------------------------------------------------------------------------
# Attempt history, failure kind and retry linkage are stored in the existing
# metadata_ JSON column under a reserved key. This keeps the diagnostic payload
# available without a schema migration, and legacy rows simply report an empty
# history instead of failing to load.
JOB_DIAGNOSTICS_KEY = "diagnostics"

# Where a RETRY keeps the diagnostics of the job it was retried from.
#
# The retry's own `diagnostics` block starts empty - a retry that has not run
# yet must not report the original's failure kind, attempt count or attempt
# history - so the original's block is preserved under this key instead of
# being extended.
JOB_RETRY_ORIGIN_DIAGNOSTICS_KEY = "retry_origin_diagnostics"

# Bound the stored attempt history so a job that fails over across many
# providers cannot grow its metadata row without limit.
MAX_TRACKED_ATTEMPTS = 20

# Error strings are truncated on write to keep the JSON column small.
MAX_ERROR_DETAIL_LENGTH = 500

# The floor for an EXPLICIT stale window. Startup recovery does not use it:
# it uses each job's own task-type timeout (`get_job_timeout`), because a
# single global window was 300 seconds against a legal image timeout of
# 3600, and recovery failed generations that were still running.
#
# It remains the floor for `POST /api/jobs/recover`, so a manual recover can
# never be more aggressive than the shortest legal job timeout.
STALE_JOB_TIMEOUT_SECONDS = 300
STALE_JOB_ERROR = "Server restart during processing - job timed out"

# A job still PENDING with no `enqueued_at` was never handed to the queue.
# Deliberately much larger than the running-state timeout: a stranded row can
# never be rescued by waiting, but several callers legitimately create a PENDING
# row and then run the work themselves (the agentic narrator holds its parent's
# queue slot), so this pass must not be the shorter of the two windows.
STRANDED_PENDING_TIMEOUT_SECONDS = 900
STRANDED_PENDING_JOB_ERROR = (
    "Job was never handed to the queue - stranded by a failed enqueue"
)

# Failure kinds recorded on the job when it fails, so the diagnostics view can
# group failures without parsing free-text error messages.
FAILURE_STALE = "stale_recovery"
FAILURE_STRANDED_PENDING = "stranded_pending"
FAILURE_TIMEOUT = "timeout"
FAILURE_NO_PROVIDERS = "no_providers"
FAILURE_PROVIDERS_EXHAUSTED = "providers_exhausted"
FAILURE_PROVIDER_ERROR = "provider_error"
FAILURE_PROVIDER_UNAVAILABLE = "provider_unavailable"
FAILURE_FINALIZATION = "finalization_failed"
FAILURE_UNEXPECTED = "unexpected"
FAILURE_CANCELLED = "cancelled"
FAILURE_UNKNOWN = "unknown"

# `ACTIVE_JOB_STATUSES` is defined beside `JobStatus` in `core.entities`, because
# three services need it and two of them had drifted from a private copy.
# Re-exported here so the existing importers keep working.

# A job can be cancelled until it reaches a terminal state.
CANCELLABLE_JOB_STATUSES = (JobStatus.PENDING, *ACTIVE_JOB_STATUSES)

JOB_STATUS_TRANSITIONS = {
    # PENDING must be able to reach FAILED. A job that is still queued when it
    # discovers no provider is available (all disabled, none healthy) is failed
    # by `job_runner._select_or_fail`, and that write used to be rejected here,
    # dropped by `update_job`, and the row left PENDING. The queue worker then
    # re-picked the same job on its very next pass and repeated forever, which
    # is what spammed the log with no_providers / invalid_fsm_transition for
    # one job id forever. PENDING is also the only state RETRYING is reachable
    # from on a manual retry, so a transient failure that happens before the
    # job is ever dispatched needs the same edge.
    # PENDING -> COMPLETED. A job that holds persisted outputs and is
    # completed from PENDING used to have its transition rejected: the FSM
    # had no edge, `update_job` popped the status, and the job stayed
    # PENDING forever with a 100% progress event instead of a completion.
    # The frontend polls on status, so the job was never finished and never
    # appeared in the gallery.
    JobStatus.PENDING: {JobStatus.SENT_TO_PROVIDER, JobStatus.RETRYING, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.COMPLETED},
    # SENT_TO_PROVIDER -> PENDING. Provider failover puts the job back on
    # the queue so a different provider can take it. The edge was missing,
    # so the failover write was rejected by the FSM and the job was left
    # in SENT_TO_PROVIDER with NO event emitted at all - the frontend
    # never learned the job was still alive.
    #
    # The same edge is needed from every state a provider can fail IN. A
    # provider that dies after its first progress frame leaves the job in
    # CONNECTED / PRE_GENERATION / GENERATING, and the failover write -
    # which always writes PENDING - was rejected from all of them. The
    # rejected write was dropped, the job kept its old status through the
    # whole failover, and every such failover logged a WARNING that looked
    # like a bug. The provider client writes those three statuses during
    # the call, so they are reachable in production, not just in theory.
    JobStatus.SENT_TO_PROVIDER: {JobStatus.CONNECTED, JobStatus.PRE_GENERATION, JobStatus.GENERATING, JobStatus.POST_PROCESSING, JobStatus.RETRYING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.PENDING},
    JobStatus.CONNECTED: {JobStatus.PRE_GENERATION, JobStatus.GENERATING, JobStatus.POST_PROCESSING, JobStatus.RETRYING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.PENDING},
    JobStatus.PRE_GENERATION: {JobStatus.GENERATING, JobStatus.POST_PROCESSING, JobStatus.RETRYING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.PENDING},
    JobStatus.GENERATING: {JobStatus.POST_PROCESSING, JobStatus.RETRYING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.PENDING},
    JobStatus.POST_PROCESSING: {JobStatus.RETRYING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.PENDING},
    JobStatus.RETRYING: {JobStatus.SENT_TO_PROVIDER, JobStatus.CONNECTED, JobStatus.PRE_GENERATION, JobStatus.GENERATING, JobStatus.POST_PROCESSING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.PENDING},
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
        "timings": stored.get("timings"),
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
    
    def _create_job_sync(
        self, workflow: dict[str, Any], metadata: dict[str, Any], task_type: str
    ) -> Job:
        """The database half of `create_job`. One INSERT, one commit, one refresh.

        Two things changed here and both were costing a round trip on the event
        loop on every single submission:

        1. The typed routing columns are set BEFORE the insert. They used to be
           set after `repo.create` had already committed and refreshed, so every
           job that carried metadata — which is most of them — paid a *second*
           commit and a second refresh. Six round trips per submission, half of
           them redundant.
        2. The whole body is synchronous and therefore runs in a worker thread.
           `create_job` is `async def` only so it can await the event emission at
           the end, and it was doing its INSERTs inline on the loop while every
           caller was on the loop waiting for it. This is the hottest path in the
           application: every generate, illustrate, narrate and TTS request comes
           through here.

        The request-scoped session is passed in rather than re-opened, matching
        `_sync_file_to_providers` in `files.py` and the rest of the codebase. The
        app-wide invariant is "no concurrent cross-thread use of a Session", not
        "one Session, one thread" — FastAPI builds the `get_session` dependency in
        a threadpool thread even for `async def` routes, and the existing
        synchronous handlers already rely on that.

        The model records in `metadata` are slimmed here rather than at each call
        site: the client sends the full `GET /api/v2/models/` row for the
        checkpoint and every selected LoRA, which measured 59 KB per job row, and
        `build_job_outputs` copies both verbatim into the PNG sidecar and
        `assets.metadata_`, so it was paid for three times. See
        `services/job_metadata.py` for the measurement and the field list.
        """
        from services.job_metadata import slim_model_metadata

        metadata = slim_model_metadata(metadata) or {}
        job = Job(
            task_type=task_type,
            workflow=workflow,
            metadata_=metadata,
            status=JobStatus.PENDING,
        )
        # Populate typed routing columns from metadata for SQL-level filtering.
        if metadata:
            job.workspace = metadata.get("workspace")
            job.character_id = metadata.get("character_id")
            job.story_id = metadata.get("story_id")
            job.source = metadata.get("source")
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job

    async def create_job(self, workflow: dict[str, Any], metadata: dict[str, Any], task_type: str = "image") -> Job:
        """
        Create a new job.
        
        Args:
            workflow: ComfyUI workflow JSON
            metadata: Job metadata (prompt, seed, etc.)
            
        Returns:
            Created job
        """
        job = await asyncio.to_thread(
            self._create_job_sync, workflow, metadata, task_type
        )

        logger.info("job_created", job_id=job.id)
        metrics.track_job_created()
        
        # Emit creation event
        await emit_job_event(EventType.JOB_CREATED, self._job_to_dict(job))
        
        return job
    
    async def get_job(self, job_id: str) -> Job:
        """Get a job by ID.

        The whole read runs on the offload pool (`run_db`), because this is
        called on every provider attempt and every progress frame, and a sync
        `Session.get` + `refresh` on the event loop stalls the API rather than
        the job. The session is used from the pool's thread and nowhere else
        for the duration, which is what keeps a unit of work single-owner;
        see `infrastructure/db_executor.py`.
        """
        def _read() -> Job:
            job = self.repo.get(job_id)
            if not job:
                logger.warning("job_not_found", job_id=job_id)
                raise NotFoundError("Job", job_id)
            try:
                self.session.refresh(job)
            except Exception as e:
                logger.debug("job_refresh_failed", job_id=job_id, error=str(e))
                # The re-read is the real check. It was written as
                # `try: self.session.get(Job, job_id) except Exception: raise
                # NotFoundError(...)`, which never fired: `Session.get` returns
                # `None` for a missing row, it does not raise. So the result was
                # discarded, the `NotFoundError` was unreachable, and a caller got
                # back a possibly-stale detached object believing it was fresh.
                if self.session.get(Job, job_id) is None:
                    raise NotFoundError("Job", job_id) from e
            return job

        return await run_db(_read)
    
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
            job_dict = self._job_to_dict(job, include_full_metadata=False)
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
        self,
        *,
        limit: int = 25,
        offset: int = 0,
        task_type: str | None = None,
        include_acknowledged: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        """List failed jobs (newest first) with diagnostics attached.

        Returns the serialized jobs and the total number of failed jobs
        matching the filter. Acknowledged jobs are excluded unless asked for, so
        a failure the user has dismissed stops counting towards the panel.
        """
        jobs, total = self.repo.get_failed(
            limit=limit,
            offset=offset,
            task_type=task_type,
            include_acknowledged=include_acknowledged,
        )
        return [self._job_to_dict(job) for job in jobs], total

    async def acknowledge_jobs(
        self, job_ids: Sequence[str], *, acknowledged: bool = True
    ) -> int:
        """Acknowledge (or un-acknowledge) specific jobs.

        Acknowledgement hides a failure the user has read without retrying it and
        without deleting the only record of what the provider did. Returns the
        number of rows changed so a caller can report a no-op honestly.
        """
        return self.repo.set_acknowledged(job_ids, acknowledged)

    def acknowledge_all(
        self, *, acknowledged: bool = True, task_type: str | None = None
    ) -> int:
        """Acknowledge (or restore) every failed job matching the filter.

        Synchronous on purpose: this was `async def` around one synchronous
        UPDATE, so the route awaiting it blocked the event loop for the whole
        filtered write across every failed job.
        """
        return self.repo.set_acknowledged_filtered(
            acknowledged=acknowledged, task_type=task_type
        )

    async def count_acknowledged_failed(self, task_type: str | None = None) -> int:
        """How many failures are currently dismissed, for the 'show dismissed' toggle."""
        return self.repo.count_acknowledged_failed(task_type=task_type)

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

        The whole read/write runs on the offload pool (`run_db`), because this
        is called on every provider attempt and a sync `Session.get` +
        `commit` on the event loop stalls the API rather than the job.
        """

        def _work() -> Job | None:
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

        return await run_db(_work)

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

    def _stale_running_candidates(
        self, timeout_seconds: int | None = None
    ) -> list[tuple[Job, float]]:
        """The active jobs that have been running longer than their timeout.

        `timeout_seconds=None` means "use each job's own task-type timeout",
        which is the only correct default. A single global window was 300
        seconds, against a legal image timeout of 3600: the dashboard's
        "Recover" button therefore failed every generation that was still
        running perfectly well, and the frontend showed it as a failure.

        POST_PROCESSING is never a candidate. A job in that state is writing
        its outputs, which is work in progress, not a wedge - and it is the
        one state where a false failure is most expensive, because the
        generation behind it has already been paid for.
        """
        from config import get_job_timeout

        now = datetime.now(timezone.utc)
        candidates: list[tuple[Job, float]] = []

        for job in self.get_running_jobs():
            if job.status == JobStatus.POST_PROCESSING:
                continue
            if not job.started_at:
                continue
            elapsed = (now - as_utc(job.started_at)).total_seconds()
            limit = (
                timeout_seconds
                if timeout_seconds is not None
                else get_job_timeout(job.task_type or "image")
            )
            if elapsed > limit:
                candidates.append((job, elapsed))

        return candidates

    async def list_stale_running_jobs(
        self, timeout_seconds: int | None = None
    ) -> list[dict[str, Any]]:
        """The stale candidates, without failing anything.

        A report, so an operator can see what recovery WOULD do before
        letting it do it. The dashboard's "Recover" button used to be a
        mutation, and it failed live jobs.
        """
        return [
            {
                "job_id": job.id,
                "task_type": job.task_type,
                "elapsed_seconds": round(elapsed, 1),
                "status": job.status.value if hasattr(job.status, "value") else str(job.status),
            }
            for job, elapsed in self._stale_running_candidates(timeout_seconds)
        ]

    async def fail_stale_running_jobs(
        self, timeout_seconds: int | None = None
    ) -> list[Job]:
        """Fail jobs wedged in an active state for longer than the timeout.

        Used by startup recovery and by `POST /api/jobs/recover` so a job whose
        worker died is never left blocking the queue. Rows are written directly
        (not through `update_job`) because the FSM deliberately forbids
        active -> FAILED transitions; recovery has to override that.
        """
        now = datetime.now(timezone.utc)
        stale = self._stale_running_candidates(timeout_seconds)

        if not stale:
            return []

        failed_jobs: list[Job] = []
        for job, elapsed in stale:
            metadata = dict(job.metadata_) if isinstance(job.metadata_, dict) else {}
            diagnostics = dict(metadata.get(JOB_DIAGNOSTICS_KEY) or {})
            diagnostics["failure_kind"] = FAILURE_STALE
            diagnostics["stale_seconds"] = round(elapsed, 3)
            diagnostics["failed_at"] = now.isoformat()
            metadata[JOB_DIAGNOSTICS_KEY] = diagnostics

            # The atomic guard. A cancel request and this sweep are writers
            # of the same row, and the sweep read its status a moment
            # earlier; a plain read-then-write let a cancellation be
            # overwritten, and both a `job.cancelled` and a `job.failed`
            # event went out for the same id.
            failed = self.repo.update_where_status(
                job.id,
                job.status,
                status=JobStatus.FAILED,
                error=STALE_JOB_ERROR,
                completed_at=now,
                metadata_=metadata,
            )
            if failed is None:
                logger.info(
                    "job_recovery_stale_skipped",
                    job_id=job.id,
                    reason="status_changed",
                )
                continue

            logger.warning("job_recovery_timeout", job_id=job.id, elapsed=f"{elapsed:.0f}s")
            try:
                await emit_job_event(EventType.JOB_FAILED, self._job_to_dict(failed))
            except Exception as exc:
                logger.warning("job_recovery_emit_failed", job_id=job.id, error=str(exc))
            failed_jobs.append(failed)

        return failed_jobs

    async def fail_stranded_pending_jobs(
        self, timeout_seconds: int = STRANDED_PENDING_TIMEOUT_SECONDS
    ) -> list[Job]:
        """Fail PENDING jobs that were never handed to the queue.

        Second line of defence behind `JobQueue._mark_enqueued`'s propagation.
        A row that is PENDING with a null `enqueued_at` can never be claimed —
        the claim query requires the stamp — and nothing else in the tree will
        ever touch it, so before this pass it sat in `summary["pending"]`
        forever, counted in every queue summary, invisible to the user and owned
        by nobody.

        Bounded by age, so a row whose stamp has not landed *yet* is not
        mistaken for a stranded one. Written directly rather than through
        `update_job`, for the same reason as `fail_stale_running_jobs`.
        """
        now = datetime.now(timezone.utc)
        stranded: list[tuple[Job, float]] = []

        # The predicate does the filtering, not a Python loop over every
        # pending row. A stranded row is PENDING with a null `enqueued_at`,
        # and the age bound is the same one the loop applied - so the set is
        # identical and the read is a range scan instead of a full table
        # materialisation.
        cutoff = now - timedelta(seconds=timeout_seconds)
        for job in self.repo.get_stranded_pending(cutoff):
            elapsed = (now - as_utc(job.created_at)).total_seconds()
            if elapsed > timeout_seconds:
                stranded.append((job, elapsed))

        if not stranded:
            return []

        failed_jobs: list[Job] = []
        for job, elapsed in stranded:
            metadata = dict(job.metadata_) if isinstance(job.metadata_, dict) else {}
            diagnostics = dict(metadata.get(JOB_DIAGNOSTICS_KEY) or {})
            diagnostics["failure_kind"] = FAILURE_STRANDED_PENDING
            diagnostics["stale_seconds"] = round(elapsed, 3)
            diagnostics["failed_at"] = now.isoformat()
            metadata[JOB_DIAGNOSTICS_KEY] = diagnostics

            # The atomic guard, for the same reason as `fail_stale_running_jobs`:
            # a cancel racing this sweep must not be overwritten.
            failed = self.repo.update_where_status(
                job.id,
                job.status,
                status=JobStatus.FAILED,
                error=STRANDED_PENDING_JOB_ERROR,
                completed_at=now,
                metadata_=metadata,
            )
            if failed is None:
                logger.info(
                    "job_recovery_stranded_skipped",
                    job_id=job.id,
                    reason="status_changed",
                )
                continue

            logger.warning(
                "job_recovery_stranded",
                job_id=job.id,
                elapsed=f"{elapsed:.0f}s",
            )
            try:
                await emit_job_event(EventType.JOB_FAILED, self._job_to_dict(failed))
            except Exception as exc:
                logger.warning(
                    "job_recovery_stranded_emit_failed", job_id=job.id, error=str(exc)
                )
            failed_jobs.append(failed)

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
    
    async def job_event_payload(
        self, job_id: str, *, include_full_metadata: bool = False
    ) -> dict[str, Any] | None:
        """The job's wire representation, for an event that is not a status change.

        Some announcements are about the job but not a transition of it - "the
        thumbnails are done", for instance. They still have to look like a job
        on the wire: the frontend's realtime handler drops any event payload
        without a `task_type`, because a partial payload merged into the
        cached job drops `task_type` and `provider_id` and can move the
        status backwards.

        So a partial payload is not an option. This returns the job's own
        representation, and the caller adds its extras.
        """
        job = self.repo.get(job_id)
        if not job:
            return None
        return self._job_to_dict(job, include_full_metadata=include_full_metadata)

    async def update_job(
        self,
        job_id: str,
        event_extra: dict | None = None,
        *,
        event_type: EventType | None = None,
        include_full_metadata: bool = True,
        **updates,
    ) -> Job:
        """
        Update a job.

        Args:
            job_id: Job ID
            event_extra: Optional dict merged into the emitted event payload
                (used to carry rich fields like type/chat_id/content on completion).
            event_type: Override the event type the update implies. The event
                type is derived from the new status, which is right for a
                status change and wrong for a progress frame on a job whose
                status did not move - the LLM path streams tokens while the
                job stays `connected`, and its frames have to be
                `job.progress` events or the frontend never sees them.
            include_full_metadata: Whether the emitted payload carries the
                job's whole metadata. False strips the heavyweight
                conversation blobs (`original_messages`, `messages`). An
                event is a notification - the full metadata is one
                `GET /api/jobs/{id}` away - and a deep agentic job's
                metadata can be tens of kilobytes, which is a lot to put on
                the wire per streamed token.
            **updates: Fields to update

        Returns:
            Updated job
        """
        # Everything from here to the metrics block is one unit of sync
        # database work, and it runs on the offload pool. `update_job` is
        # called on every progress frame — throttled to one per second per
        # in-flight job — so a bare `self.session.commit()` here was a
        # blocking commit on the event loop, stalling the whole API rather
        # than the job that caused it. `run_in_executor` on the DEFAULT pool
        # would only move that stall into a queue of N jobs behind six
        # threads, which is why this uses the dedicated pool.
        #
        # Event emission stays OUTSIDE the closure: `emit_job_event` is async
        # and non-blocking, and pulling it onto a worker thread would be
        # work being done in a thread for no reason.
        def _db_work() -> Job:
    # Track timing based on status changes
            job = self.repo.get(job_id)
            if not job:
                logger.warning("job_update_not_found", job_id=job_id)
                raise NotFoundError("Job", job_id)
            
            # Set started_at for first active state
            # The shared tuple, not a transcription of it. This copy omitted
            # `RETRYING`, so `started_at` was never stamped for a job entering retry
            # backoff.
            active_states = ACTIVE_JOB_STATUSES
            status = updates.get("status")
            requested_status = status

            # Enforce Finite State Machine transitions
            #
            # The check below is only half the guard, and the half that used to be
            # missing is the half that mattered. `repo.get` is `session.get`, so it
            # answers from the identity map with no SELECT — for a long-lived
            # Session `job.status` is whatever that Session last loaded, which for a
            # request-scoped one can be arbitrarily old. SENT_TO_PROVIDER's allowed
            # set contains FAILED, so a CANCELLED committed by another Session in
            # between was authorised away and then overwritten, taking the user's
            # cancellation and its reason with it. `expected_status` carries the
            # status this decision was made against into the write itself, so the
            # write re-checks it atomically.
            expected_status: JobStatus | None = None
            if status and status != job.status:
                expected_status = job.status
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
                    expected_status = None

            # Fields this method derives from `status`. They are undone if the
            # transition is rejected below, so a rejected write does not leave a
            # `completed_at` on a job that never completed.
            derived_keys: set[str] = set()

            if status in active_states and not job.started_at:
                updates["started_at"] = datetime.now(timezone.utc)
                derived_keys.add("started_at")
            elif status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                updates["completed_at"] = datetime.now(timezone.utc)
                derived_keys.add("completed_at")

            timings = updates.pop("timings", None)
            if timings is not None and "metadata_" not in updates:
                metadata = dict(job.metadata_) if isinstance(job.metadata_, dict) else {}
                diagnostics = dict(metadata.get(JOB_DIAGNOSTICS_KEY) or {})
                diagnostics["timings"] = timings
                metadata[JOB_DIAGNOSTICS_KEY] = diagnostics
                updates["metadata_"] = metadata
                derived_keys.add("metadata_")

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
                    derived_keys.add("metadata_")

            if expected_status is not None:
                job = self.repo.update_where_status(job_id, expected_status, **updates)
                if job is None:
                    # 0 rows: the row was no longer in the state this guard read, so
                    # some other writer got there first. Same verdict, same
                    # consequence, one source: drop the transition and everything
                    # derived from it, and let the remaining fields through exactly
                    # as the rejected-transition path above does.
                    for key in derived_keys:
                        updates.pop(key, None)
                    updates.pop("status", None)
                    status = None
                    job = self.repo.update(job_id, **updates)
                    if job is not None:
                        logger.warning(
                            "invalid_fsm_transition",
                            job_id=job_id,
                            from_status=expected_status,
                            to_status=requested_status,
                            actual_status=job.status,
                            reason="concurrent_status_change",
                        )
            else:
                job = self.repo.update(job_id, **updates)

            if job is None:
                # Deleted by the writer that beat us to it. Reporting the update and
                # emitting an event for a row that no longer exists would put a
                # terminal event on the wire for a job nobody can fetch.
                logger.warning("job_update_deleted_concurrently", job_id=job_id)
                return job
        
            if status:
                status_value = status.value if hasattr(status, "value") else str(status)
                logger.info("job_status_changed", job_id=job_id, status=status_value)
                if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                    duration = None
                    if job.started_at and job.completed_at:
                        duration = max((job.completed_at - job.started_at).total_seconds(), 0.0)
                    metrics.track_job_completed(status_value, duration)
            # `status` and `updates` are mutated in place by the FSM guard
            # above (a rejected transition pops them), so the event emission
            # below has to read the POST-WRITE values rather than recomputing
            # from the caller's arguments. Handing them back is what keeps the
            # emission on the loop while the write stays on the pool.
            return job, status, updates

        job, status, updates = await run_db(_db_work)
        
        # Determine event type based on status
        if event_type is not None:
            selected_event_type = (
                event_type if isinstance(event_type, EventType) else EventType(event_type)
            )
        elif status == JobStatus.COMPLETED:
            selected_event_type = EventType.JOB_COMPLETED
        elif status == JobStatus.POST_PROCESSING:
            selected_event_type = EventType.JOB_POST_PROCESSING
        elif status == JobStatus.FAILED:
            selected_event_type = EventType.JOB_FAILED
        elif status == JobStatus.CANCELLED:
            selected_event_type = EventType.JOB_CANCELLED
        elif "progress" in updates:
            selected_event_type = EventType.JOB_PROGRESS
        else:
            selected_event_type = EventType.JOB_UPDATED

        job_dict = self._job_to_dict(job, include_full_metadata=include_full_metadata)
        await emit_job_event(selected_event_type, self._build_event_payload(job_dict, event_extra))

        return job

    @staticmethod
    def _build_event_payload(job_dict: dict, event_extra: dict | None) -> dict:
        """The job row plus the caller's event extras, with `metadata` merged.

        The merge used to be shallow, so an `event_extra` carrying a `metadata`
        key replaced the job's whole metadata dict rather than adding to it.
        Several completion paths build `event_extra["metadata"]` from two or
        three keys of their own (`chat_id`, `type`, `regenerated`), which meant
        every other key the job actually carried was discarded on the way to
        the event — and the world-integration handler downstream reads them
        from there.

        What that silently broke, all on the job-completion path:

          - `character_id` never reached `Message`, so every AI reply in a
            group chat was attributed to the primary character
          - `is_swipe` / `target_message_id` never arrived, so the alternate
            branch in the world-integration service was unreachable and
            "generate an alternate reply" appended a new message instead
          - `orchestrator_depth` was never stamped on the message
          - `is_suggestion` was lost

        The route-level tests could not see any of it: they exercise the route
        directly, and the service tests hand-build a complete metadata dict,
        bypassing the merge that drops it.

        `event_extra` still wins on a per-key basis, so a caller can correct a
        value; it just can no longer delete its neighbours.
        """
        payload = {**job_dict, **(event_extra or {})}
        extra_metadata = (event_extra or {}).get("metadata")
        if isinstance(extra_metadata, dict):
            job_metadata = job_dict.get("metadata")
            merged = dict(job_metadata) if isinstance(job_metadata, dict) else {}
            merged.update(extra_metadata)
            payload["metadata"] = merged
        return payload
    
    async def delete_job(self, job_id: str) -> bool:
        """Delete a job, refusing while it is still live.

        `repo.delete` is `session.get` → `session.delete` → `commit` with no
        status predicate, so this accepted a job in any state. Deleting one that
        a worker still owns means the worker finishes, then
        `finalize_persisted_job_outputs` calls `get_job()`, which raises
        `NotFoundError`, which is swallowed with a `job_finalize_not_found`
        warning: the images are on disk but never reconciled into `assets`, never
        shown, and `wait_for_gallery_outputs` never runs. A paid generation
        silently discarded, with the load-balancer slot released by the generic
        exception handler rather than the normal path.

        The frontend gates the button to terminal statuses, but the API has no
        auth at all, so that gate is cosmetic. `clear_all_jobs` already refused
        while work was running; this is the same rule for the single-row path.

        `CANCELLABLE_JOB_STATUSES` is the codebase's existing answer to "is this
        job still live" — PENDING plus everything in `ACTIVE_JOB_STATUSES` — and
        is reused rather than re-derived. The error names cancel so the API is
        self-describing rather than making the caller guess.
        """
        job = self.repo.get(job_id)
        if not job:
            logger.warning("job_delete_not_found", job_id=job_id)
            raise NotFoundError("Job", job_id)
        if job.status in CANCELLABLE_JOB_STATUSES:
            raise ValidationError(
                f"Cannot delete a job that is still {job.status.value}. "
                "Cancel it first, then delete it."
            )
        success = self.repo.delete(job_id)
        if not success:
            logger.warning("job_delete_not_found", job_id=job_id)
            raise NotFoundError("Job", job_id)
        logger.info("job_deleted", job_id=job_id)
        return True
    
    def clear_all_jobs(self) -> int:
        """Clear terminal jobs while preserving active work.

        Synchronous on purpose: `async def` around a synchronous DELETE, so the
        route awaiting it blocked the event loop for the duration of the wipe.
        """
        if self.get_running_jobs():
            raise ValidationError("Cannot clear jobs while active jobs exist")
        count = self.repo.delete_all()
        logger.info("jobs_cleared", count=count)
        return count
    
    def get_pending_jobs(self, limit: int | None = None) -> list[Job]:
        """Get pending jobs in FIFO order."""
        return self.repo.get_pending(limit=limit)

    def count_pending_jobs(self) -> int:
        """How many jobs are pending - without loading any of them."""
        return self.repo.count_pending()
    
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
    
    #: Keys dropped from `metadata` in LIST payloads. `original_messages` holds
    #: the entire agentic conversation, and each chained hop stores the previous
    #: hop's context plus the new turns, so a single deep job's metadata can be
    #: tens of kilobytes. Serialising that for every row of a page dominated the
    #: response. The full metadata is still returned by GET /api/jobs/{id}.
    LIST_METADATA_OMIT = ("original_messages", "messages")

    def _job_to_dict(self, job: Job, *, include_full_metadata: bool = True) -> dict[str, Any]:
        """Convert job to dictionary for API responses.

        `include_full_metadata=False` is for list endpoints: it strips the
        heavyweight conversation blobs from `metadata` while keeping the small
        keys the UI filters on (chat_id, story_id, provider, agentic depth...).
        """
        metadata = job.metadata_
        if not include_full_metadata and isinstance(metadata, dict):
            metadata = {
                key: value
                for key, value in metadata.items()
                if key not in self.LIST_METADATA_OMIT
            }
        return {
            "id": job.id,
            "task_type": job.task_type,
            "status": job.status.value,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            # Present so a client can tell a dismissed failure from one that has
            # not been seen yet, and so the "show dismissed" toggle can label
            # what it is about to show.
            "acknowledged_at": job.acknowledged_at.isoformat() if job.acknowledged_at else None,
            "workflow": job.workflow,
            "metadata": metadata,
            "outputs": job.outputs,
            "progress": job.progress,
            "overall_progress": job.overall_progress,
            "message": job.message,
            "error": job.error,
            "provider_id": job.provider_id,
            "diagnostics": build_job_diagnostics(job),
        }
