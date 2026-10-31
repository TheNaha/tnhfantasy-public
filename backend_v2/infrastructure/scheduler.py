# Background task scheduler using APScheduler
# Consolidates all periodic tasks (reconciliation, cleanup, etc.)

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import hashlib
import time
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from infrastructure.logging import scheduler_logger

logger = scheduler_logger()


# Global scheduler instance
_scheduler: AsyncIOScheduler | None = None

# Advisory-lock key for "this process owns the scheduled jobs".
#
# Every key here names one job id, so the lock is held PER RUN and released
# immediately. That is not an optimisation: the alternative — one lock held for
# the scheduler's lifetime — would designate a single owning process and take
# that job off the other processes entirely, which is a bigger behaviour change
# than this change is meant to be. Per-run locking keeps the existing
# "every process schedules, only one acts" shape, so a process that dies simply
# stops taking the lock and the others pick up on the next tick.
_SCHEDULER_LOCK_NAMESPACE = 4_118_227_004_771_902_337


def _advisory_lock_key(job_id: str) -> int:
    """A lock key that is the SAME integer in every process that asks for it.

    This was `namespace + abs(hash(job_id)) % 1_000_000_007`, and
    `str.__hash__` is salted per process (PYTHONHASHSEED) — the salt is derived
    from a per-process random value at interpreter start. So two processes
    scheduling the same job id derived two different keys, `pg_try_advisory_lock`
    was called with a key no other session held, it always returned true, and the
    lock excluded nobody. Every process ran every tick, which is duplicated spend
    for the two jobs that bill an LLM. `blake2b` is the fix: a cryptographic
    digest has no per-process state, so the key is a pure function of the job id.

    Truncated to the same 1,000,000,007 window the old expression used, so the
    key range is unchanged and the sum with the namespace stays inside the
    signed 64-bit range `pg_advisory_lock(bigint)` accepts — the namespace
    already occupies most of it. The migration lock in the sibling module is a
    hardcoded constant, which is the same guarantee by a different route.
    """
    digest = hashlib.blake2b(job_id.encode("utf-8"), digest_size=8).digest()
    return _SCHEDULER_LOCK_NAMESPACE + (
        int.from_bytes(digest, "big") % 1_000_000_007
    )


class _AdvisoryRunLock:
    """Context manager holding a per-run advisory lock for a scheduled job.

    Entered by the wrapper below so the lock is released as soon as the job
    finishes, on every path including an exception. `pg_try_advisory_lock` is
    re-entrant per session, so it is taken at most once per acquire.
    """

    def __init__(self, job_id: str):
        self._job_id = job_id
        self._session = None
        self._held = False
        self._granted = True
        # Derived once, so the unlock below cannot disagree with the lock.
        self._key = _advisory_lock_key(job_id)

    def __enter__(self) -> bool:
        from infrastructure.database import engine

        if engine.dialect.name != "postgresql":
            return True
        from sqlalchemy import text
        from sqlmodel import Session

        try:
            self._session = Session(engine)
            self._held = bool(
                self._session.exec(
                    text("SELECT pg_try_advisory_lock(:key)"), params={"key": self._key}
                ).scalar()
            )
            return self._held
        except Exception as exc:
            logger.warning(
                "scheduler_lock_failed", job_id=self._job_id, error=str(exc)
            )
            self._session = None
            self._held = False
            return True

    def __exit__(self, *_exc) -> None:
        if self._session is None:
            return
        try:
            if self._held:
                from sqlalchemy import text

                self._session.exec(
                    text("SELECT pg_advisory_unlock(:key)"),
                    params={"key": self._key},
                )
                self._session.commit()
        except Exception as exc:
            if self._held:
                logger.error("scheduler_lock_release_failed", job_id=self._job_id, error=str(exc))
        finally:
            try:
                self._session.close()
            except Exception as exc:
                logger.warning("scheduler_session_close_failed", job_id=self._job_id, error=str(exc))
            self._session = None


# In-memory execution history for scheduled jobs
_JOB_HISTORY: dict[str, dict[str, Any]] = {}


def _guarded(func: Callable, job_id: str) -> Callable:
    """Wrap a scheduled job so only one process runs each tick.

    `max_instances=1` stops one *process* from overlapping itself and does
    nothing about two processes. Every job registered here then fires in all of
    them, which is duplicated spend for the two that bill an LLM — the idle
    simulation and memory extraction — and merely duplicated work for the rest.

    Non-blocking, and the lock is released as soon as the job returns. If a
    process dies mid-run the database closes its session and releases the lock,
    so there is no lease to expire and nothing to clean up.
    """
    import functools
    import inspect as _inspect

    if _inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def _async_wrapper(*args, **kwargs):
            with _AdvisoryRunLock(job_id) as granted:
                if not granted:
                    logger.debug("scheduler_tick_skipped", job_id=job_id, reason="held_by_another_process")
                    if job_id not in _JOB_HISTORY:
                        _JOB_HISTORY[job_id] = {
                            "last_run_at": None,
                            "last_status": "skipped",
                            "last_duration_seconds": 0.0,
                            "last_error": None,
                        }
                    return None
                start_time = time.monotonic()
                run_at = datetime.now(timezone.utc).isoformat()
                try:
                    res = await func(*args, **kwargs)
                    duration = round(time.monotonic() - start_time, 3)
                    _JOB_HISTORY[job_id] = {
                        "last_run_at": run_at,
                        "last_status": "success",
                        "last_duration_seconds": duration,
                        "last_error": None,
                    }
                    return res
                except Exception as exc:
                    duration = round(time.monotonic() - start_time, 3)
                    _JOB_HISTORY[job_id] = {
                        "last_run_at": run_at,
                        "last_status": "failed",
                        "last_duration_seconds": duration,
                        "last_error": str(exc),
                    }
                    raise

        return _async_wrapper

    @functools.wraps(func)
    def _wrapper(*args, **kwargs):
        with _AdvisoryRunLock(job_id) as granted:
            if not granted:
                logger.debug("scheduler_tick_skipped", job_id=job_id, reason="held_by_another_process")
                if job_id not in _JOB_HISTORY:
                    _JOB_HISTORY[job_id] = {
                        "last_run_at": None,
                        "last_status": "skipped",
                        "last_duration_seconds": 0.0,
                        "last_error": None,
                    }
                return None
            start_time = time.monotonic()
            run_at = datetime.now(timezone.utc).isoformat()
            try:
                res = func(*args, **kwargs)
                duration = round(time.monotonic() - start_time, 3)
                _JOB_HISTORY[job_id] = {
                    "last_run_at": run_at,
                    "last_status": "success",
                    "last_duration_seconds": duration,
                    "last_error": None,
                }
                return res
            except Exception as exc:
                duration = round(time.monotonic() - start_time, 3)
                _JOB_HISTORY[job_id] = {
                    "last_run_at": run_at,
                    "last_status": "failed",
                    "last_duration_seconds": duration,
                    "last_error": str(exc),
                }
                raise

    return _wrapper


def get_scheduler() -> AsyncIOScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


def start_scheduler():
    """Start the background task scheduler."""
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("scheduler_started")


def stop_scheduler():
    """Stop the background task scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")
    _scheduler = None


def add_interval_job(
    func: Callable,
    interval_seconds: int,
    job_id: str,
    start_immediately: bool = True,
    misfire_grace_time: int = 60,
    **kwargs
):
    """
    Add a job that runs at fixed intervals.
    
    Args:
        func: Function to run (can be async)
        interval_seconds: Interval between runs in seconds
        job_id: Unique identifier for the job
        start_immediately: Run the job immediately on startup
        **kwargs: Additional arguments passed to func
        
    Usage:
        add_interval_job(
            sync_models,
            interval_seconds=300,
            job_id="model_sync",
            provider_id="modal-primary"
        )
    """
    scheduler = get_scheduler()
    
    # Remove existing job with same ID
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    trigger = IntervalTrigger(seconds=interval_seconds)

    next_run = datetime.now(timezone.utc) if start_immediately else datetime.now(timezone.utc) + timedelta(seconds=interval_seconds)

    scheduler.add_job(
        _guarded(func, job_id),
        trigger=trigger,
        id=job_id,
        kwargs=kwargs,
        replace_existing=True,
        next_run_time=next_run,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=misfire_grace_time,
    )

    logger.info("job_scheduled", job_id=job_id, interval_seconds=interval_seconds)


def add_cron_job(
    func: Callable,
    cron_expr: str,
    job_id: str,
    misfire_grace_time: int = 60,
    **kwargs
):
    """
    Add a job that runs on a cron schedule.
    
    Args:
        func: Function to run (can be async)
        cron_expr: Cron expression (e.g., "0 * * * *" for hourly)
        job_id: Unique identifier for the job
        **kwargs: Additional arguments passed to func
        
    Cron format: minute hour day month day_of_week
        "0 2 * * *" = Daily at 2 AM
        "*/15 * * * *" = Every 15 minutes
        "0 0 * * 0" = Weekly on Sunday at midnight
    """
    scheduler = get_scheduler()
    
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    # Parse cron expression
    parts = cron_expr.split()
    trigger = CronTrigger(
        minute=parts[0] if len(parts) > 0 else '*',
        hour=parts[1] if len(parts) > 1 else '*',
        day=parts[2] if len(parts) > 2 else '*',
        month=parts[3] if len(parts) > 3 else '*',
        day_of_week=parts[4] if len(parts) > 4 else '*',
    )
    
    scheduler.add_job(
        _guarded(func, job_id),
        trigger=trigger,
        id=job_id,
        kwargs=kwargs,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=misfire_grace_time,
    )
    
    logger.info("cron_job_scheduled", job_id=job_id, cron_expr=cron_expr)


def remove_job(job_id: str):
    """Remove a scheduled job by ID."""
    scheduler = get_scheduler()
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info("job_removed", job_id=job_id)


def get_jobs_status() -> list[dict[str, Any]]:
    """Get status of all scheduled jobs including recent execution history."""
    scheduler = get_scheduler()
    jobs = []
    
    for job in scheduler.get_jobs():
        history = _JOB_HISTORY.get(job.id, {})
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
            "last_run_at": history.get("last_run_at"),
            "last_status": history.get("last_status", "idle"),
            "last_duration_seconds": history.get("last_duration_seconds"),
            "last_error": history.get("last_error"),
        })
    
    return jobs


# ============================================================================
# COMMON SCHEDULED TASKS
# ============================================================================



def schedule_cleanup(func: Callable, interval_seconds: int = 3600):
    """Schedule the cleanup task (jobs, downloads, etc.)."""
    add_interval_job(
        func,
        interval_seconds=interval_seconds,
        job_id="cleanup",
        start_immediately=False,
    )


def schedule_vacuum(func: Callable, interval_seconds: int = 86400):
    """
    Schedule database vacuum task (default: daily).
    
    SQLite VACUUM reclaims disk space from deleted rows and
    optimizes database performance.
    """
    add_interval_job(
        func,
        interval_seconds=interval_seconds,
        job_id="database_vacuum",
        start_immediately=False,
        misfire_grace_time=3600,
    )


def schedule_preview_prefetch(func: Callable, interval_seconds: int = 900):
    """Schedule preview cache prefetch with jitter handled by the job implementation."""
    add_interval_job(
        func,
        interval_seconds=interval_seconds,
        job_id="preview_prefetch",
        start_immediately=True,
        misfire_grace_time=300,
    )

