import asyncio
from dataclasses import dataclass

from infrastructure.deps import get_session_sync
from infrastructure.logging import get_logger

logger = get_logger("provider_runtime")

# Resolution is cheap now (config reads only), but the async wrapper keeps a
# timeout so a wedged call can never hold a request open.
_RUNTIME_RESOLVE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class ProviderRuntimeTarget:
    """Resolved execution/runtime target for a provider."""

    provider_id: str
    mode: str
    worker_url: str | None = None
    supports_setup: bool = False
    supports_reconciliation: bool = False
    connected: bool = False
    status: str | None = None
    healthy: bool | None = None


def resolve_provider_runtime(provider) -> ProviderRuntimeTarget:
    """Resolve the canonical runtime target for a provider.

    Providers execute in-process via ``services/engines/`` whenever an engine
    is constructible for them. The only other live mode is ``external_worker``
    (a connected remote agent, e.g. ``remote_comfy`` rows whose agent holds
    the ComfyUI socket). Anything else is ``unavailable``.
    """
    from infrastructure.worker_registry import is_worker_connected

    provider_id = provider.id

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
    """`resolve_provider_runtime` with a timeout guard.

    On timeout or failure this degrades rather than raising: an unresolvable
    provider yields an `unavailable` target instead of a 500.
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
                            counts: dict[str, int] = {}
                            for provider in providers:
                                category = getattr(provider, "worker_type", "") or "image"
                                if category not in counts:
                                    counts[category] = 0
                                counts[category] += 1
                            return counts
                        finally:
                            session.close()

                    counts = await asyncio.to_thread(count_enabled_providers)

                    # Only the pools whose size actually changed, so a TTS
                    # provider toggling does not spawn resize tasks for the
                    # image and llm pools. The old code resized both positions on
                    # every event, and the tts pool was not one of them at all.
                    changed = {
                        category: max(1, count)
                        for category, count in counts.items()
                        if category in queue_manager.pools
                        and queue_manager.pools[category].max_workers != max(1, count)
                    }
                    if changed:
                        queue_manager.resize(**changed)
                except Exception as exc:
                    logger.error("provider_monitor_error", error=str(exc))
    except asyncio.CancelledError:
        logger.info("provider_monitor_stop")
    except Exception as exc:
        logger.error("provider_monitor_fatal", error=str(exc))
