from datetime import datetime, timezone, timedelta

from api.deps import get_session_sync
from infrastructure.logging import get_logger
from services.job_service import JobService
from services.job_queue import job_queue

logger = get_logger("startup_helpers")


def configure_worker_pool() -> None:
    """Set worker count based on enabled providers."""
    try:
        from infrastructure.repositories import ProviderRepository

        session = get_session_sync()
        try:
            provider_repo = ProviderRepository(session)
            enabled_providers = provider_repo.get_enabled()
            num_workers = max(1, len(enabled_providers))
            job_queue.max_workers = num_workers
            logger.info("worker_pool_configured", providers=len(enabled_providers), workers=num_workers)
        finally:
            session.close()
    except Exception as exc:
        logger.warning("worker_pool_error", error=str(exc))


async def recover_pending_jobs() -> None:
    """Recover pending and in-flight jobs after startup."""
    try:
        recovery_session = get_session_sync()
        try:
            recovery_job_service = JobService(recovery_session)
            await job_queue.recover_pending_jobs(recovery_job_service)
        finally:
            recovery_session.close()
    except Exception as exc:
        logger.warning("job_recovery_failed", error=str(exc))


def cleanup_provider_state_artifacts(stale_downloading_after_minutes: int = 120) -> None:
    """Reset stale downloading entries and clean orphaned provider statuses.
    
    Does NOT purge provider records — let the discovery heartbeat system
    (POST /api/v2/providers/discovery) upsert live provider records.
    Providers from old backups are harmless; they get overwritten when
    the live container sends its first discovery heartbeat.
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
