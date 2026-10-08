import asyncio
from dataclasses import dataclass

from infrastructure.deps import get_session_sync
from infrastructure.logging import get_logger
from infrastructure.providers.runtime import provider_container_name

import os

logger = get_logger("provider_runtime")

# Generous enough for a cold Docker socket, short enough that a wedged daemon
# cannot hold a request open. The snapshot cache means this only applies to the
# first provider to miss it.
_RUNTIME_RESOLVE_TIMEOUT_SECONDS = 5.0

# Reported as a target's `status` when the container runtime could not be
# reached at all, as distinct from a runtime that answered and has no such
# container. The resolution still degrades to the same unusable target either
# way — this only makes the reason legible instead of guessing at it.
RUNTIME_UNREACHABLE = "runtime_unreachable"


_DEPRECATION_WARNED = False


def use_in_process_engines() -> bool:
    """Kill-switch for the in-process engine path (default on).

    Deliberately env-only, like the other COMFY_* operational knobs
    (health-check toggles, timeouts, autostart): it must be readable from
    import-time and scheduler paths that never load config.json, and it is
    evaluated on every call so tests can flip it with monkeypatch.setenv.
    """
    return os.getenv("COMFY_USE_IN_PROCESS_ENGINES", "true").lower() in ("true", "1", "yes")


def _warn_container_deprecated(provider_id: str) -> None:
    """Log a one-time deprecation warning when a provider falls back to container mode.

    Provider containers are deprecated. The in-process engine
    (``services/engines/``) is the preferred path and is on by default. When
    ``COMFY_USE_IN_PROCESS_ENGINES`` is false, or a provider has
    ``execution_mode: "container"`` in its config, the backend falls back to the
    containerized path — which is kept only for the transition period.

    Running containers can be safely stopped: providers with in-process-capable
    engines will auto-resolve (``resolve_provider_runtime`` checks
    ``can_create_engine`` first), and existing PENDING/RUNNING jobs re-enqueue on
    the next backend restart and route to the in-process path.
    """
    global _DEPRECATION_WARNED
    if not _DEPRECATION_WARNED:
        _DEPRECATION_WARNED = True
        logger.warning(
            "provider_container_mode_deprecated",
            provider_id=provider_id,
            hint=(
                "Provider containers are deprecated. Set COMFY_USE_IN_PROCESS_ENGINES=true "
                "(default) or remove execution_mode='container' from the provider config. "
                "Stop running provider containers with: "
                "docker compose --profile providers stop"
            ),
        )


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
    # Registry-as-truth (migration 089): container placement may live under
    # either `config` or the legacy `container_config` key. `config` wins —
    # it is the newer write path — but a row healed by the migration (or
    # written by an older client) must resolve identically.
    if not isinstance(container_config, dict):
        container_config = {}
    if not isinstance(provider_config, dict):
        provider_config = {}
    container_settings = {**container_config, **{
        k: provider_config[k] for k in ("container_name", "port") if k in provider_config
    }}
    # Set when the container probe raised rather than answered. Function-scoped:
    # the `if container_settings` block below may not run at all, and the final
    # target still has to be able to say which failure it was.
    runtime_unreachable = False

    # Check for in-process compute engines (Modal, Direct ComfyUI)
    use_in_process = use_in_process_engines()
    explicit_container = isinstance(provider_config, dict) and provider_config.get("execution_mode") == "container"
    if use_in_process and not explicit_container:
        from services.engines.engine_factory import can_create_engine, engine_supports_setup
        if can_create_engine(provider):
            return ProviderRuntimeTarget(
                provider_id=provider_id,
                mode="in_process",
                worker_url=None,
                supports_setup=engine_supports_setup(provider),
                supports_reconciliation=True,
                connected=True,
                status="in_process",
                # Unknown until probed: resolve_* is sync and cannot call
                # the async check_health. The load balancer probes
                # in-process engines (with timeout) at dispatch time, so a
                # hardcoded True here would mark bad-credential providers
                # healthy on every status card.
                healthy=None,
            )

    if container_settings:
        container_name = container_settings.get("container_name", provider_container_name(provider_id))
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
            # Degrading to the worker/discovery fallbacks below is deliberate,
            # but it used to log at debug, which is indistinguishable from "no
            # container was ever there" and made a dead Docker daemon invisible
            # on the page that reports it. The fallbacks still run — the
            # resolution stays best-effort — but the outcome now says which of
            # the two happened: "unreachable" is not "absent".
            runtime_unreachable = True
            status = RUNTIME_UNREACHABLE
            logger.warning(
                "provider_runtime_status_probe_failed",
                provider_id=provider_id,
                container=container_name,
                error=str(exc),
            )

        if docker_available and found:
            _warn_container_deprecated(provider_id)
            port = container_settings.get("port", 8000) if isinstance(container_settings, dict) else 8000
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
        _warn_container_deprecated(provider_id)
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
        # A provider whose container was never found is "unavailable"; one whose
        # runtime could not be asked at all is "unreachable". Both are unusable,
        # and reporting them identically is what let a dead Docker daemon look
        # like a fleet of correctly-stopped containers.
        status=RUNTIME_UNREACHABLE if runtime_unreachable else "unavailable",
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
