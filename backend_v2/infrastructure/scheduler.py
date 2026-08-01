# Background task scheduler using APScheduler
# Consolidates all periodic tasks (reconciliation, cleanup, etc.)

from collections.abc import Callable
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from infrastructure.logging import scheduler_logger

logger = scheduler_logger()


# Global scheduler instance
_scheduler: AsyncIOScheduler | None = None


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
    
    next_run = datetime.now() if start_immediately else datetime.now() + timedelta(seconds=interval_seconds)
    
    scheduler.add_job(
        func,
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
        func,
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


def get_jobs_status() -> list:
    """Get status of all scheduled jobs."""
    scheduler = get_scheduler()
    jobs = []
    
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        })
    
    return jobs


# ============================================================================
# COMMON SCHEDULED TASKS
# ============================================================================



def schedule_reconciliation(func: Callable, interval_seconds: int = 120):
    """Schedule the reconciliation task."""
    add_interval_job(
        func,
        interval_seconds=interval_seconds,
        job_id="reconciliation",
        start_immediately=False,
    )


def schedule_model_sync(func: Callable, interval_seconds: int = 300):
    """Schedule the model sync task."""
    add_interval_job(
        func,
        interval_seconds=interval_seconds,
        job_id="model_sync",
        start_immediately=True,
    )


def schedule_cleanup(func: Callable, interval_seconds: int = 3600):
    """Schedule the cleanup task (jobs, downloads, etc.)."""
    add_interval_job(
        func,
        interval_seconds=interval_seconds,
        job_id="cleanup",
        start_immediately=False,
    )


def schedule_stats_refresh(func: Callable, interval_seconds: int = 600):
    """Schedule statistics cache refresh."""
    add_interval_job(
        func,
        interval_seconds=interval_seconds,
        job_id="stats_refresh",
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

