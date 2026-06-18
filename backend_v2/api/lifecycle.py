import asyncio

from api.deps import get_session_sync
from api.provider_runtime import monitor_provider_changes
from api.startup_helpers import (
    autostart_provider_containers,
    cleanup_provider_state_artifacts,
    configure_worker_pool,
    recover_pending_jobs,
)
from core.entities import JobStatus
from infrastructure.background_tasks import cancel_background_tasks, start_background_task
from infrastructure.database import create_db_and_tables
from infrastructure.http_client import close_http_client
from infrastructure.logging import get_logger
from infrastructure.scheduler import (
    schedule_preview_prefetch,
    schedule_vacuum,
    start_scheduler,
    stop_scheduler,
)
from services.job_queue import job_queue
from services.job_service import JobService
from sqlmodel import select

logger = get_logger("lifecycle")


async def _process_image_background_for_recovery(image_path: str, job_id: str) -> None:
    """Apply thumbnail/metadata post-processing when recovering post-processing jobs."""
    try:
        from infrastructure.image_processor import process_image as img_process

        await asyncio.to_thread(img_process, image_path, save_metadata=True)
    except Exception as exc:
        logger.warning(
            "recovery_image_processing_failed",
            job_id=job_id,
            path=image_path,
            error=str(exc),
        )


def requeue_inflight_jobs_for_shutdown() -> int:
    """Reset in-flight jobs so startup recovery can safely re-enqueue them."""
    session = get_session_sync()
    try:
        job_service = JobService(session)
        inflight_jobs = job_service.get_running_jobs()
        requeued_count = 0

        for job in inflight_jobs:
            # Protect against races where a job transitions to terminal state
            # between the initial query and shutdown requeue mutation.
            try:
                session.refresh(job)
            except Exception:
                continue

            if job.status != JobStatus.RUNNING:
                continue

            job.status = JobStatus.PENDING
            job.started_at = None
            job.completed_at = None
            job.progress = 0.0
            job.overall_progress = 0.0
            job.message = "Requeued after server shutdown"
            job.error = None
            session.add(job)
            requeued_count += 1

        if requeued_count:
            session.commit()

        logger.info("shutdown_jobs_requeued", count=requeued_count)
        return requeued_count
    finally:
        session.close()


async def vacuum_database() -> None:
    """Run SQLite VACUUM to reclaim disk space and optimize performance."""
    from sqlalchemy import text
    from infrastructure.database import engine

    logger.info("vacuum_start")
    try:
        with engine.connect() as conn:
            conn.execute(text("VACUUM"))
            conn.commit()
        logger.info("vacuum_complete")
    except Exception as exc:
        logger.error("vacuum_failed", error=str(exc))


async def startup_application(process_job, ws_manager):
    """Run application startup side effects and return tracked background tasks."""
    logger.info("startup_init", phase="database")
    create_db_and_tables()

    logger.info("startup_init", phase="provider_state_cleanup")
    cleanup_provider_state_artifacts()

    logger.info("startup_init", phase="job_processor")
    job_queue.set_processor(process_job)

    logger.info("startup_init", phase="gallery_indexer")
    try:
        from services.gallery_indexer import gallery_indexer

        gallery_indexer.start()
    except Exception as exc:
        logger.warning("gallery_indexer_not_started", error=str(exc))

    logger.info("startup_init", phase="worker_pool")
    configure_worker_pool()

    logger.info("startup_init", phase="job_queue")
    await job_queue.start()

    logger.info("startup_init", phase="provider_monitor")
    provider_monitor_task = start_background_task(
        monitor_provider_changes(),
        task_name="provider_monitor",
    )

    logger.info("startup_init", phase="job_recovery")
    await recover_pending_jobs()
    await recover_post_processing_jobs()

    logger.info("startup_init", phase="containers")
    autostart_provider_containers()

    logger.info("startup_init", phase="scheduler")
    start_scheduler()
    schedule_vacuum(vacuum_database, interval_seconds=86400)
    from api.routes.models import (
        PREVIEW_PREFETCH_INTERVAL_SECONDS,
        prefetch_stale_model_previews,
    )

    schedule_preview_prefetch(
        prefetch_stale_model_previews,
        interval_seconds=PREVIEW_PREFETCH_INTERVAL_SECONDS,
    )

    logger.info("startup_init", phase="websocket")
    broadcast_task = start_background_task(
        ws_manager.start_broadcasting(),
        task_name="websocket_broadcast",
    )

    logger.info("startup_complete")
    return {
        "provider_monitor_task": provider_monitor_task,
        "broadcast_task": broadcast_task,
    }


async def shutdown_application(ws_manager, provider_monitor_task, broadcast_task) -> None:
    """Run application shutdown side effects in a controlled order."""
    logger.info("shutdown", phase="websocket")
    await ws_manager.stop_broadcasting()
    broadcast_task.cancel()
    try:
        await broadcast_task
    except asyncio.CancelledError:
        pass

    logger.info("shutdown", phase="provider_monitor")
    provider_monitor_task.cancel()
    try:
        await provider_monitor_task
    except asyncio.CancelledError:
        pass

    logger.info("shutdown", phase="background_tasks")
    cancelled_task_count = await cancel_background_tasks()
    logger.info("background_tasks_cancelled", count=cancelled_task_count)

    logger.info("shutdown", phase="scheduler")
    stop_scheduler()

    logger.info("shutdown", phase="job_queue")
    await job_queue.stop()

    logger.info("shutdown", phase="job_requeue")
    try:
        requeue_inflight_jobs_for_shutdown()
    except Exception as exc:
        logger.warning("shutdown_job_requeue_failed", error=str(exc))

    logger.info("shutdown", phase="http_client")
    await close_http_client()

    logger.info("shutdown_complete")


async def recover_post_processing_jobs(process_image_background_fn=None) -> int:
    """Resume jobs that already have persisted outputs but were not marked completed yet."""
    from api.job_processing import finalize_persisted_job_outputs
    from core.entities import Job

    process_image_background_fn = process_image_background_fn or _process_image_background_for_recovery

    session = get_session_sync()
    try:
        job_service = JobService(session)
        post_processing_jobs = session.exec(
            select(Job).where(Job.status == JobStatus.POST_PROCESSING)
        ).all()

        recovered = 0
        for job in post_processing_jobs:
            outputs = job.outputs or []
            if not outputs:
                job.status = JobStatus.FAILED
                job.error = "Job entered post-processing without persisted outputs"
                session.add(job)
                continue

            await finalize_persisted_job_outputs(
                job_service=job_service,
                job_id=job.id,
                outputs=outputs,
                provider_id=job.provider_id,
                load_balancer=None,
                process_image_background_fn=process_image_background_fn,
            )
            recovered += 1

        if post_processing_jobs:
            session.commit()

        if recovered:
            logger.info("post_processing_jobs_recovered", count=recovered)
        return recovered
    finally:
        session.close()
