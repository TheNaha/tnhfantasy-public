import asyncio
from dataclasses import dataclass
from typing import Optional
from types import SimpleNamespace

from infrastructure.http_client import get_http_client
from api.deps import get_session_sync
from infrastructure.logging import get_logger

logger = get_logger("provider_runtime")


@dataclass(frozen=True)
class ProviderRuntimeTarget:
    """Resolved execution/runtime target for a provider."""

    provider_id: str
    mode: str
    worker_url: Optional[str] = None
    container_name: Optional[str] = None
    supports_setup: bool = False
    supports_reconciliation: bool = False
    connected: bool = False
    status: Optional[str] = None
    healthy: Optional[bool] = None


def resolve_provider_runtime(provider) -> ProviderRuntimeTarget:
    """Resolve the canonical runtime target for a provider."""
    from api.routes.worker_ws import is_worker_connected

    container_config = getattr(provider, "container_config", None) or {}
    provider_id = getattr(provider, "id")
    provider_type = getattr(provider, "type", "")
    provider_config = getattr(provider, "config", None) or {}

    if container_config:
        container_name = container_config.get("container_name", f"comfy-provider-{provider_id}")
        connected = False
        healthy = None
        status = "unknown"
        docker_available = False
        try:
            from api.deps import get_container_manager

            container_manager = get_container_manager()
            if container_manager and getattr(container_manager, "client", None) is not None:
                docker_available = True
                container = container_manager.running_containers.get(provider_id)
                if container is None:
                    try:
                        container = container_manager.client.containers.get(container_name)
                    except Exception:
                        container = None

                if container is not None:
                    try:
                        container.reload()
                    except Exception:
                        pass
                    status = getattr(container, "status", "unknown") or "unknown"
                    health_status = getattr(container, "attrs", {}).get("State", {}).get("Health", {}).get("Status")
                    healthy = health_status == "healthy" if health_status else None
                    connected = status == "running" and healthy is not False
        except Exception as exc:
            logger.debug("provider_runtime_status_probe_failed", provider_id=provider_id, error=str(exc))

        if docker_available:
            return ProviderRuntimeTarget(
                provider_id=provider_id,
                mode="container_http",
                worker_url=f"http://{container_name}:8000",
                container_name=container_name,
                supports_setup=provider_type == "modal",
                supports_reconciliation=True,
                connected=connected,
                status=status,
                healthy=healthy,
            )
        # Docker not available — fall through to discovery / worker_ws checks

    if is_worker_connected(provider_id):
        return ProviderRuntimeTarget(
            provider_id=provider_id,
            mode="external_worker",
            supports_setup=False,
            supports_reconciliation=False,
            connected=True,
            status="connected",
            healthy=True,
        )

    provider_config = getattr(provider, "config", None) or {}
    discovery_url = provider_config.get("discovery_url") if isinstance(provider_config, dict) else None
    if discovery_url:
        return ProviderRuntimeTarget(
            provider_id=provider_id,
            mode="discovery",
            worker_url=discovery_url,
            supports_setup=provider_type == "modal",
            supports_reconciliation=True,
            connected=True,
            status="discovered",
            healthy=True,
        )

    return ProviderRuntimeTarget(
        provider_id=provider_id,
        mode="unavailable",
        supports_setup=False,
        supports_reconciliation=False,
        connected=False,
        status="unavailable",
        healthy=False,
    )


async def run_reconciliation_for_all_providers():
    """Trigger reconciliation for all enabled containerized providers."""
    logger.info("reconciliation_periodic")

    session = get_session_sync()
    try:
        from services.provider_service import ProviderService

        service = ProviderService(session)
        providers_list = await service.list_providers()
        http_client = get_http_client()

        for provider in providers_list:
            if not provider.get("enabled", True):
                continue

            runtime = resolve_provider_runtime(SimpleNamespace(**provider))
            if runtime.mode not in ("container_http", "discovery"):
                continue

            provider_id = provider.get("id")

            try:
                response = await http_client.post(
                    f"{runtime.worker_url}/reconcile",
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
    from services.job_queue import job_queue

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
