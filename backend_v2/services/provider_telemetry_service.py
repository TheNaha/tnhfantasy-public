"""Continuous provider telemetry collection.

Polls all enabled providers with in-process engines on a configurable
interval, calling ``engine.check_health()`` to keep telemetry fields
fresh (``detected_gpu``, ``concurrency_policy``, ``warm_workload``,
``components``). The provider status card already reads these from the
engine cache (``services/provider_status_service.py``), so no database
schema change is needed.

Polling is intentionally cheap: it only touches providers whose engine
can be constructed, wraps each health check in a timeout, and never lets
one provider's failure break the loop. Blocking I/O (DB reads, engine
construction) runs off the event loop via ``asyncio.to_thread``.
"""

import asyncio
import os
from typing import Any

from infrastructure.deps import get_session_sync
from infrastructure.logging import get_logger
from infrastructure.repositories import ProviderRepository
from services.engines.engine_factory import can_create_engine, get_engine

logger = get_logger("provider_telemetry")

TELEMETRY_INTERVAL_SECONDS = float(
    os.getenv("COMFY_PROVIDER_TELEMETRY_INTERVAL_SECONDS", "30.0")
)
TELEMETRY_TIMEOUT_SECONDS = float(
    os.getenv("COMFY_PROVIDER_TELEMETRY_TIMEOUT_SECONDS", "10.0")
)


class ProviderTelemetryService:
    """Polls provider engines for telemetry on a background interval."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the background polling task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(
            self._poll_loop(), name="provider_telemetry"
        )
        logger.info(
            "provider_telemetry_started",
            interval_seconds=TELEMETRY_INTERVAL_SECONDS,
        )

    async def stop(self) -> None:
        """Stop the background polling task."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("provider_telemetry_stopped")

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                await self._poll_once()
            except Exception as exc:  # never crash the loop
                logger.warning(
                    "provider_telemetry_poll_failed", error=str(exc)
                )
            await asyncio.sleep(TELEMETRY_INTERVAL_SECONDS)

    async def _poll_once(self) -> None:
        """One polling pass over all enabled providers."""

        def _list_enabled() -> list[Any]:
            session = get_session_sync()
            try:
                repo = ProviderRepository(session)
                return repo.get_enabled()
            finally:
                session.close()

        providers = await asyncio.to_thread(_list_enabled)

        for provider in providers:
            try:
                await self._poll_provider(provider)
            except Exception as exc:  # one provider must not break the rest
                logger.debug(
                    "provider_telemetry_provider_failed",
                    provider_id=getattr(provider, "id", "?"),
                    error=str(exc),
                )

    async def _poll_provider(self, provider: Any) -> None:
        """Poll one provider's engine for health/telemetry.

        ``can_create_engine`` guards on credentials/config, so providers
        that aren't configured are skipped without a health probe.
        """
        if not can_create_engine(provider):
            return

        engine = get_engine(provider.id, provider)
        if engine is None:
            return

        try:
            health = await asyncio.wait_for(
                engine.check_health(), timeout=TELEMETRY_TIMEOUT_SECONDS
            )
            # Engines store ``_last_health``, ``detected_gpu``,
            # ``concurrency_policy``, ``warm_workload`` during
            # ``check_health()``. The provider status card reads these
            # from ``_ENGINE_CACHE``, so nothing else needs to change.
            _ = health  # health check runs for its side effects on the engine
        except asyncio.TimeoutError:
            logger.debug(
                "provider_telemetry_timeout",
                provider_id=provider.id,
            )
        except Exception as exc:
            logger.debug(
                "provider_telemetry_check_failed",
                provider_id=provider.id,
                error=str(exc),
            )


# Module-level singleton
telemetry_service = ProviderTelemetryService()


async def start_telemetry_polling() -> None:
    """Entry point for application startup."""
    await telemetry_service.start()


async def stop_telemetry_polling() -> None:
    """Entry point for application shutdown."""
    await telemetry_service.stop()
