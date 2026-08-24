import asyncio
from dataclasses import dataclass

from infrastructure.deps import get_session_sync
from infrastructure.logging import get_logger
from infrastructure.providers.runtime import provider_container_name

logger = get_logger("provider_runtime")


@dataclass(frozen=True)
class ProviderRuntimeTarget:
    """Resolved execution/runtime target for a provider."""

    provider_id: str
    mode: str
    worker_url: str | None = None
    container_name: str | None = None
    supports_setup: bool = False
    supports_reconciliation: bool = False
    connected: bool = False
    status: str | None = None
    healthy: bool | None = None


def resolve_provider_runtime(provider) -> ProviderRuntimeTarget:
    """Resolve the canonical runtime target for a provider."""
    from infrastructure.worker_registry import is_worker_connected

    container_config = getattr(provider, "container_config", None) or {}
    provider_id = provider.id
    provider_type = getattr(provider, "type", "")
    provider_config = getattr(provider, "config", None) or {}

    if container_config:
        container_name = container_config.get("container_name", provider_container_name(provider_id))
        connected = False
        healthy = None
        status = "unknown"
        docker_available = False
        found = False
        try:
            from infrastructure.deps import get_container_manager

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
                    found = True
                    try:
                        container.reload()
                    except Exception as exc:
                        logger.debug("container_reload_failed", error=str(exc))
                    status = getattr(container, "status", "unknown") or "unknown"
                    health_status = getattr(container, "attrs", {}).get("State", {}).get("Health", {}).get("Status")
                    healthy = health_status == "healthy" if health_status else None
                    connected = status == "running" and healthy is not False
        except Exception as exc:
            logger.debug("provider_runtime_status_probe_failed", provider_id=provider_id, error=str(exc))

        if docker_available and found:
            port = container_config.get("port", 8000) if isinstance(container_config, dict) else 8000
            return ProviderRuntimeTarget(
                provider_id=provider_id,
                mode="container_http",
                worker_url=f"http://{container_name}:{port}",
                container_name=container_name,
                supports_setup=provider_type in ("modal", "modal_llm"),
                supports_reconciliation=True,
                connected=connected,
                status=status,
                healthy=healthy,
            )
        # Container not found (or Docker unavailable) — fall through to
        # worker_ws / discovery_url checks so healthy discovered workers
        # are reachable instead of being pinned to an unreachable name.

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
            supports_setup=provider_type in ("modal", "modal_llm"),
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


async def monitor_provider_changes():
    """Resize worker pool as provider availability changes."""
    from core.events import EventType, event_bus
    from infrastructure.repositories import ProviderRepository
    from services.job_queue import queue_manager

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
                            providers = repo.get_enabled()
                            image_workers = sum(1 for p in providers if p.worker_type != "llm")
                            llm_workers = sum(1 for p in providers if p.worker_type == "llm")
                            return image_workers, llm_workers
                        finally:
                            session.close()

                    image_workers, llm_workers = await asyncio.to_thread(count_enabled_providers)

                    if image_workers != queue_manager.image.max_workers or llm_workers != queue_manager.llm.max_workers:
                        queue_manager.resize(image_workers, llm_workers)
                except Exception as exc:
                    logger.error("provider_monitor_error", error=str(exc))
    except asyncio.CancelledError:
        logger.info("provider_monitor_stop")
    except Exception as exc:
        logger.error("provider_monitor_fatal", error=str(exc))
