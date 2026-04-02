from datetime import datetime, timedelta

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


def build_provider_worker_images() -> None:
    """Attempt to refresh built provider worker images before container startup."""
    try:
        from services.container_manager import get_container_manager

        container_manager = get_container_manager()
        if not container_manager:
            return
        image_tags = container_manager.build_worker_images()
        logger.info("provider_image_refresh_complete", built=list(image_tags.keys()))
    except Exception as exc:
        logger.warning("provider_image_refresh_failed", error=str(exc))


def autostart_provider_containers() -> None:
    """Start enabled provider containers configured for local management."""
    try:
        from infrastructure.providers import ProviderRegistry
        from infrastructure.repositories import ProviderRepository
        from services.container_manager import get_container_manager

        session = get_session_sync()
        try:
            provider_repo = ProviderRepository(session)
            providers = provider_repo.get_all()
            container_manager = get_container_manager()
            if not container_manager:
                return

            for provider in providers:
                if provider.enabled and provider.container_config:
                    try:
                        logger.info("container_starting", provider=provider.id)
                        port = provider.container_config.get("port", 8000)
                        env_vars = ProviderRegistry.build_container_env(provider)
                        container_manager.start_container(
                            provider_id=provider.id,
                            provider_type=provider.type,
                            port=port,
                            env_vars=env_vars if env_vars else None,
                        )
                        logger.info("container_started", provider=provider.id)
                    except Exception as exc:
                        logger.warning("container_start_failed", provider=provider.id, error=str(exc))
        finally:
            session.close()
    except Exception as exc:
        logger.warning("container_autostart_failed", error=str(exc))


def cleanup_provider_state_artifacts(stale_downloading_after_minutes: int = 120) -> None:
    """Remove orphaned provider statuses and reset stale downloading entries."""
    try:
        from infrastructure.repositories import ProviderRepository
        from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2

        session = get_session_sync()
        try:
            provider_repo = ProviderRepository(session)
            active_provider_ids = [provider.id for provider in provider_repo.get_all()]

            model_repo = ModelRepositoryV2(session)
            orphaned_result = model_repo.cleanup_orphaned_provider_statuses(active_provider_ids)
            stale_before = datetime.utcnow() - timedelta(minutes=stale_downloading_after_minutes)
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
