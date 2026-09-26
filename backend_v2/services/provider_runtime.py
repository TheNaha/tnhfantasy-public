import asyncio
from dataclasses import dataclass

from infrastructure.deps import get_session_sync
from infrastructure.logging import get_logger
from infrastructure.providers.runtime import provider_container_name

logger = get_logger("provider_runtime")

# Generous enough for a cold Docker socket, short enough that a wedged daemon
# cannot hold a request open. The snapshot cache means this only applies to the
# first provider to miss it.
_RUNTIME_RESOLVE_TIMEOUT_SECONDS = 5.0


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
                # One cached accessor rather than a containers.get() plus a
                # reload() here. Both are blocking round trips to the Docker
                # socket, and this function is called twice per provider on the
                # providers list route, serially, from async handlers.
                snapshot = container_manager.get_container_snapshot(provider_id, container_name)
                if snapshot is not None:
                    found = True
                    status = snapshot.status
                    healthy = snapshot.healthy
                    connected = snapshot.running and healthy is not False
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


async def resolve_provider_runtime_async(provider) -> ProviderRuntimeTarget:
    """`resolve_provider_runtime` without blocking the event loop.

    Resolving a provider's runtime target can talk to the Docker socket, which is a
    blocking HTTP round trip with no timeout. Called directly from `async def`
    handlers — and the providers list route does it twice per provider in a serial
    loop — that stalled the entire event loop for the sum of every connect timeout
    when `DOCKER_HOST` pointed at an unreachable endpoint. No other request,
    WebSocket or job-queue worker could progress meanwhile.

    On timeout or failure this degrades rather than raising: the probe falls
    through to the external-worker and discovery_url branches below, which is what
    the old `except Exception` did, so an unreachable Docker socket yields an
    `unavailable` target instead of a 500.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(resolve_provider_runtime, provider),
            timeout=_RUNTIME_RESOLVE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "provider_runtime_resolve_timeout",
            provider_id=getattr(provider, "id", None),
            timeout=_RUNTIME_RESOLVE_TIMEOUT_SECONDS,
        )
        return ProviderRuntimeTarget(
            provider_id=getattr(provider, "id", "") or "",
            mode="unavailable",
            connected=False,
            status="probe_timeout",
            healthy=None,
        )
    except Exception as exc:
        logger.warning(
            "provider_runtime_resolve_failed",
            provider_id=getattr(provider, "id", None),
            error=str(exc),
        )
        return ProviderRuntimeTarget(
            provider_id=getattr(provider, "id", "") or "",
            mode="unavailable",
            connected=False,
            status="probe_failed",
            healthy=None,
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
