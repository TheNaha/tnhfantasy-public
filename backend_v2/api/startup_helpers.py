from datetime import datetime, timedelta, timezone

from api.deps import get_session_sync
from infrastructure.logging import get_logger
from services.job_queue import job_queue
from services.job_service import JobService

logger = get_logger("startup_helpers")


def configure_worker_pool() -> None:
    """Set worker counts based on enabled providers split by worker_type."""
    try:
        from infrastructure.repositories import ProviderRepository
        from services.job_queue import queue_manager

        session = get_session_sync()
        try:
            provider_repo = ProviderRepository(session)
            enabled_providers = provider_repo.get_enabled()

            image_providers = []
            llm_providers = []
            for p in enabled_providers:
                w_type = getattr(p, "worker_type", "image")
                if w_type == "llm" or p.id.startswith("llm"):
                    llm_providers.append(p)
                else:
                    image_providers.append(p)

            image_workers = max(1, len(image_providers))
            llm_workers = max(1, len(llm_providers))

            queue_manager.resize(image_workers=image_workers, llm_workers=llm_workers)
            logger.info(
                "worker_pool_configured",
                image_providers=len(image_providers),
                llm_providers=len(llm_providers),
                image_workers=image_workers,
                llm_workers=llm_workers,
            )
        finally:
            session.close()
    except Exception as exc:
        logger.warning("worker_pool_error", error=str(exc))



async def recover_pending_jobs() -> None:
    """Recover pending and in-flight jobs after startup, routed by task_type."""
    try:
        from services.job_queue import queue_manager

        recovery_session = get_session_sync()
        try:
            recovery_job_service = JobService(recovery_session)
            await queue_manager.recover_pending_jobs(recovery_job_service)
        finally:
            recovery_session.close()
    except Exception as exc:
        logger.warning("job_recovery_failed", error=str(exc))



def cleanup_provider_state_artifacts(
    stale_downloading_after_minutes: int = 120,
    *,
    skip_orphan_cleanup: bool = False,
) -> None:
    """Reset stale downloading entries and optionally clean orphaned provider statuses.
    
    Does NOT purge provider records — let the discovery heartbeat system
    (POST /api/v2/providers/discovery) upsert live provider records.
    Providers from old backups are harmless; they get overwritten when
    the live container sends its first discovery heartbeat.
    
    Args:
        stale_downloading_after_minutes: Reset downloading statuses older than this.
        skip_orphan_cleanup: If True, skip deleting orphaned provider statuses.
            Use this on initial startup to avoid a race where providers haven't
            re-registered yet and their statuses would be wrongly deleted.
    """
    try:
        from infrastructure.repositories import ProviderRepository
        from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2

        session = get_session_sync()
        try:
            provider_repo = ProviderRepository(session)
            all_providers = provider_repo.get_all()
            active_provider_ids = [p.id for p in all_providers]

            model_repo = ModelRepositoryV2(session)
            orphaned_result = {"deleted_count": 0, "orphaned_providers": []}
            if not skip_orphan_cleanup:
                orphaned_result = model_repo.cleanup_orphaned_provider_statuses(active_provider_ids)
            stale_before = datetime.now(timezone.utc) - timedelta(minutes=stale_downloading_after_minutes)
            stale_resets = model_repo.reset_stale_downloading_statuses(
                stale_before=stale_before,
                provider_names=active_provider_ids,
            )

            logger.info(
                "provider_state_cleanup_complete",
                active_providers=len(active_provider_ids),
                orphaned_statuses_deleted=orphaned_result.get("deleted_count", 0),
                stale_downloading_reset=stale_resets,
            )
        finally:
            session.close()
    except Exception as exc:
        logger.warning("provider_state_cleanup_failed", error=str(exc))
