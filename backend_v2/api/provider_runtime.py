import asyncio

from api.deps import get_session_sync
from infrastructure.http_client import get_http_client
from infrastructure.logging import get_logger
from services.job_queue import job_queue
from services.provider_service import ProviderService

logger = get_logger("provider_runtime")


async def run_reconciliation_for_all_providers():
    """Trigger reconciliation for all enabled containerized providers."""
    logger.info("reconciliation_periodic")

    session = get_session_sync()
    try:
        service = ProviderService(session)
        providers_list = await service.list_providers()
        http_client = get_http_client()

        for provider in providers_list:
            if not provider.get("enabled", True):
                continue

            container_config = provider.get("container_config")
            if not container_config:
                continue

            provider_id = provider.get("id")
            container_name = f"comfy-provider-{provider_id}"
            worker_url = f"http://{container_name}:8000"

            try:
                response = await http_client.post(
                    f"{worker_url}/reconcile",
                    timeout=5.0,
                )
                if response.status_code == 200:
                    logger.info("reconciliation_triggered", provider=provider_id)
                else:
                    logger.warning(
                        "reconciliation_failed",
                        provider=provider_id,
                        status=response.status_code,
                    )
            except Exception as exc:
                logger.debug("reconciliation_unreachable", provider=provider_id, error=str(exc))
    finally:
        session.close()


async def monitor_provider_changes():
    """Resize worker pool as provider availability changes."""
    from core.events import EventType, event_bus
    from infrastructure.repositories import ProviderRepository

    logger.info("provider_monitor_start")
    subscription = event_bus.subscribe("provider")

    try:
        async for event in subscription:
            if event.type == EventType.PROVIDER_STATUS:
                try:
                    logger.info("provider_status_changed", data=event.data)

                    def count_enabled_providers():
                        session = get_session_sync()
                        try:
                            repo = ProviderRepository(session)
                            return len(repo.get_enabled())
                        finally:
                            session.close()

                    enabled_count = await asyncio.to_thread(count_enabled_providers)
                    target_workers = max(1, enabled_count)

                    if target_workers != job_queue.max_workers:
                        await job_queue.resize(target_workers)
                except Exception as exc:
                    logger.error("provider_monitor_error", error=str(exc))
    except asyncio.CancelledError:
        logger.info("provider_monitor_stop")
    except Exception as exc:
        logger.error("provider_monitor_fatal", error=str(exc))