import asyncio
import os

from sqlmodel import select

from api.deps import get_session_sync
from api.startup_helpers import (
    cleanup_provider_state_artifacts,
    configure_worker_pool,
    recover_pending_jobs,
)
from core.entities import JobStatus
from infrastructure.background_tasks import (
    cancel_background_tasks,
    start_background_task,
)
from infrastructure.database import create_db_and_tables, vacuum_database
from infrastructure.http_client import close_http_client
from infrastructure.logging import get_logger
from infrastructure.scheduler import (
    schedule_cleanup,
    schedule_preview_prefetch,
    schedule_vacuum,
    start_scheduler,
    stop_scheduler,
)
from services.job_queue import queue_manager
from services.job_service import JobService
from services.provider_runtime import monitor_provider_changes

logger = get_logger("lifecycle")


async def _process_image_background_for_recovery(image_path: str, job_id: str) -> None:
    """Apply thumbnail/metadata post-processing when recovering post-processing jobs.

    Jobs stuck in POST_PROCESSING crashed before the asset reconciler ran, so
    this re-runs reconciliation (thumbnails/blurhash/DB row) for each output.
    """
    try:
        from config import settings
        from services.asset_reconciler import reconcile_asset

        session = get_session_sync()
        try:
            job_metadata = None
            from core.entities import Job

            job = session.get(Job, job_id)
            if job:
                job_metadata = job.metadata_

            await asyncio.to_thread(
                reconcile_asset,
                session,
                image_path,
                user_id="default_user",
                workspace=(job_metadata or {}).get("workspace", "main"),
                character_id=(job_metadata or {}).get("character_id"),
                story_id=(job_metadata or {}).get("story_id"),
                job_id=job_id,
                job_metadata=job_metadata,
                output_dir=settings.output_dir,
            )
        finally:
            session.close()
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

            active_states = {JobStatus.SENT_TO_PROVIDER, JobStatus.CONNECTED, JobStatus.PRE_GENERATION, JobStatus.GENERATING}
            if job.status not in active_states:
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




async def run_data_cleanup() -> None:
    """Run all periodic data cleanup tasks in one pass."""
    from api.startup_helpers import cleanup_provider_state_artifacts
    from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2

    logger.info("data_cleanup_start")
    try:
        cleanup_provider_state_artifacts(stale_downloading_after_minutes=120)
    except Exception as exc:
        logger.warning("data_cleanup_provider_state_failed", error=str(exc))

    try:
        await prune_stale_providers()
    except Exception as exc:
        logger.warning("data_cleanup_prune_failed", error=str(exc))

    try:
        session = get_session_sync()
        try:
            model_repo = ModelRepositoryV2(session)
            orphaned = model_repo.cleanup_orphaned_models()
            if orphaned > 0:
                logger.info("data_cleanup_orphaned_models", removed=orphaned)
        finally:
            session.close()
    except Exception as exc:
        logger.warning("data_cleanup_orphaned_failed", error=str(exc))

    logger.info("data_cleanup_complete")


async def prune_stale_providers() -> None:
    """Remove provider records that have not sent a discovery heartbeat in 24 hours."""
    from datetime import datetime, timedelta, timezone

    from infrastructure.deps import get_session_sync
    from infrastructure.repositories import ProviderRepository

    logger.info("prune_stale_providers_start")
    try:
        session = get_session_sync()
        try:
            repo = ProviderRepository(session)
            all_providers = repo.get_all()
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(hours=24)
            pruned = 0
            for p in all_providers:
                config = p.config or {}
                last_seen = config.get("last_seen_at")
                if last_seen and isinstance(last_seen, str):
                    try:
                        seen = datetime.fromisoformat(last_seen)
                        if seen < cutoff:
                            logger.info("pruning_stale_provider", provider_id=p.id, last_seen=last_seen)
                            repo.delete(p.id)
                            pruned += 1
                    except (ValueError, TypeError) as exc:
                        logger.debug("stale_provider_timestamp_parse_failed", provider_id=p.id, last_seen=last_seen, error=str(exc))
            if pruned:
                logger.info("stale_providers_pruned", count=pruned)
            else:
                logger.info("prune_stale_providers_complete")
        finally:
            session.close()
    except Exception as exc:
        logger.warning("prune_stale_providers_failed", error=str(exc))


def _run_asset_migration() -> None:
    """Synchronous asset migration; invoked in a thread at startup."""
    try:
        from config import settings
        from services.asset_reconciler import move_existing_assets

        output_dir = settings.output_dir
        with get_session_sync() as session:
            moved = move_existing_assets(output_dir, lambda: get_session_sync(), user_id="default_user")
        logger.info("asset_migration_complete", moved=moved)
    except Exception as exc:
        logger.warning("asset_migration_failed", error=str(exc))


async def startup_application(process_job, ws_manager):
    """Run application startup side effects and return tracked background tasks."""
    logger.info("startup_init", phase="database")
    create_db_and_tables()

    logger.info("startup_init", phase="provider_state_cleanup")
    cleanup_provider_state_artifacts(skip_orphan_cleanup=True)
    

    logger.info("startup_init", phase="job_processor")
    queue_manager.set_processor(process_job)

    # One-time, idempotent relocation of the legacy flat output tree into the
    # partitioned /{user_id}/{workspace}/ layout + DB-backed asset index.
    # Runs in a background thread so startup isn't blocked (≈15s for 13k files);
    # re-runs are no-ops once files are already partitioned.
    logger.info("startup_init", phase="asset_migration")
    start_background_task(
        asyncio.to_thread(
            _run_asset_migration,
        ),
        task_name="asset_migration",
        timeout=600.0,
    )

    logger.info("startup_init", phase="worker_pool")
    configure_worker_pool()

    logger.info("startup_init", phase="job_queue")
    await queue_manager.start()

    logger.info("startup_init", phase="provider_monitor")
    provider_monitor_task = start_background_task(
        monitor_provider_changes(),
        task_name="provider_monitor",
        timeout=None,
    )

    logger.info("startup_init", phase="job_recovery")
    await recover_pending_jobs()
    await recover_post_processing_jobs()

    logger.info("startup_init", phase="scheduler")
    start_scheduler()
    schedule_vacuum(vacuum_database, interval_seconds=86400)
    from services.model_preview_service import (
        PREVIEW_PREFETCH_INTERVAL_SECONDS,
        prefetch_stale_model_previews,
    )

    schedule_preview_prefetch(
        prefetch_stale_model_previews,
        interval_seconds=PREVIEW_PREFETCH_INTERVAL_SECONDS,
    )

    logger.info("startup_init", phase="data_cleanup")
    schedule_cleanup(run_data_cleanup, interval_seconds=3600)

    from config import get_config
    idle_sim_env = os.getenv("COMFY_IDLE_SIM_ENABLED", "").strip().lower()
    if idle_sim_env in ("1", "true", "yes"):
        idle_sim_enabled = True
    elif idle_sim_env in ("0", "false", "no"):
        idle_sim_enabled = False
    else:
        idle_sim_enabled = bool(get_config().get("ai", {}).get("idleSimEnabled", False))

    from services.agent_simulation import run_idle_simulation_tick
    from infrastructure.scheduler import add_interval_job
    interval_env = os.getenv("COMFY_IDLE_SIM_INTERVAL_SECONDS")
    interval = int(interval_env) if interval_env else int(get_config().get("ai", {}).get("idleSimIntervalSeconds", 600))
    add_interval_job(
        run_idle_simulation_tick,
        interval_seconds=interval,
        job_id="idle_simulation",
        start_immediately=False,
    )
    logger.info("idle_simulation_registered", enabled=idle_sim_enabled, interval_seconds=interval)

    logger.info("startup_init", phase="civitai_resync")
    from api.routes.models.maintenance import run_background_resync
    # Run a full CivitAI resync every 24 hours
    add_interval_job(
        run_background_resync,
        interval_seconds=86400,
        job_id="civitai_resync_job",
        start_immediately=False,
    )

    logger.info("startup_init", phase="websocket")
    broadcast_task = start_background_task(
        ws_manager.start_broadcasting(),
        task_name="websocket_broadcast",
        timeout=None,
    )

    logger.info("startup_init", phase="world_integration")
    from services.world_integration_service import start_world_integration_service
    world_integration_task = start_background_task(
        start_world_integration_service(),
        task_name="world_integration",
        timeout=None,
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
    except (asyncio.CancelledError, TimeoutError):
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
    await queue_manager.stop()

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
    from core.entities import Job
    from services.job_processing import finalize_persisted_job_outputs

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
