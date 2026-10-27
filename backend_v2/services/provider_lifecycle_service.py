from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from sqlmodel import Session

from core.exceptions import ProviderError
from infrastructure.logging import get_logger
from services.provider_runtime import resolve_provider_runtime_async
from services.provider_service import ProviderService
from services.provider_status_service import ProviderStatusService

# In-process reconciliation outcomes that mean "work is in flight" rather
# than "done". Anything else is recorded as a terminal outcome.
_RECONCILIATION_IN_FLIGHT_STATUSES = frozenset(
    {"started", "queued", "already_running", "running", "reconciling", "pending"}
)
_RECONCILIATION_FAILED_STATUSES = frozenset({"error", "failed"})

logger = get_logger("provider_lifecycle")


class ProviderLifecycleService:
    """Orchestrate provider setup and model reconciliation.

    Providers execute in-process via ``services/engines/``; this service is
    the HTTP-facing seam over engine setup and the in-process reconciler.
    """

    def __init__(
        self,
        session: Session,
        *,
        provider_service: ProviderService | None = None,
        invalidate_caches: Callable[[str | None], None] | None = None,
    ) -> None:
        self.session = session
        self.provider_service = provider_service or ProviderService(session)
        self.status_service = ProviderStatusService(session, provider_service=self.provider_service)
        self.invalidate_caches = invalidate_caches or (lambda _provider_id=None: None)

    async def setup_provider(self, provider_id: str) -> dict[str, Any]:
        provider = await self.provider_service.get_provider(provider_id)
        runtime = await resolve_provider_runtime_async(provider)
        if getattr(runtime, "mode", "") != "in_process":
            raise ProviderError(
                provider_id,
                "Setup requires a provider with a reachable in-process engine",
            )
        from services.engines.engine_factory import engine_supports_setup, get_engine

        if not engine_supports_setup(provider):
            # Hosted-LLM/TTS engines own no model tree; setup is a no-op.
            return {
                "status": "success",
                "message": f"Provider '{provider_id}' needs no setup (in-process)",
                "result": {"status": "skipped"},
            }
        engine = get_engine(provider_id, provider)
        if engine is None:
            raise ProviderError(provider_id, "No in-process engine available for setup")
        try:
            # A wedged engine must fail the request, not hang it.
            ok = await asyncio.wait_for(engine.setup_models(), timeout=30.0)
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise ProviderError(provider_id, "In-process setup timed out after 30s") from exc
        except NotImplementedError as exc:
            raise ProviderError(provider_id, f"Setup is not supported by this engine: {exc}") from exc
        except Exception as exc:
            raise ProviderError(provider_id, f"In-process setup failed: {exc}") from exc
        if not ok:
            raise ProviderError(provider_id, "In-process setup reported failure")
        return {
            "status": "success",
            "message": f"Provider '{provider_id}' setup complete (in-process)",
            "result": {"status": "ok"},
        }

    async def sync_provider_models(self, provider_id: str) -> dict[str, Any]:
        return await self.trigger_reconciliation(provider_id, force=True, quick_sync=True)

    async def trigger_reconciliation(self, provider_id: str, force: bool = False, quick_sync: bool = False) -> dict[str, Any]:
        provider = await self.provider_service.get_provider(provider_id)
        runtime = await resolve_provider_runtime_async(provider)
        if getattr(runtime, "mode", "") != "in_process":
            raise ProviderError(
                provider_id,
                "Reconciliation is only available for providers with a reachable in-process engine",
            )
        from services.engines.engine_factory import get_engine
        from services.in_process_reconciliation import trigger_in_process_reconciliation

        engine = get_engine(provider_id, provider)
        if engine is None:
            raise ProviderError(provider_id, "No in-process engine available for reconciliation")
        result = await trigger_in_process_reconciliation(
            provider_id,
            provider=provider,
            engine=engine,
            quick_sync=quick_sync,
            force=force,
        )
        status = result.get("status")
        if status in _RECONCILIATION_IN_FLIGHT_STATUSES:
            persisted_state = await asyncio.to_thread(
                self.provider_service.upsert_reconciliation_state,
                provider_id,
                {
                    "status": "reconciling",
                    "phase": "running",
                    "message": result.get("message", "In-process reconciliation started"),
                    "last_contact_at": ProviderService._utcnow_iso(),
                },
            )
            self.invalidate_caches(provider_id)
            return {
                "status": "triggered",
                "provider_id": provider_id,
                "message": result.get("message"),
                "reconciliation": self.status_service.normalize_reconciliation_for_card(
                    persisted_state
                ),
            }
        # Terminal: skipped (no model tree) or failed to start. Record the
        # outcome rather than work in flight.
        terminal_status = "failed" if status in _RECONCILIATION_FAILED_STATUSES else "completed"
        persisted_state = await asyncio.to_thread(
            self.provider_service.upsert_reconciliation_state,
            provider_id,
            {
                "status": terminal_status,
                "phase": status,
                "message": result.get("message", f"In-process reconciliation {status}"),
                "last_contact_at": ProviderService._utcnow_iso(),
            },
        )
        self.invalidate_caches(provider_id)
        return {
            "status": terminal_status,
            "provider_id": provider_id,
            "message": result.get("message"),
            "reconciliation": self.status_service.normalize_reconciliation_for_card(
                persisted_state
            ),
        }

    async def trigger_model_downloads(
        self,
        provider_id: str,
        file_ids: list[str],
    ) -> dict[str, Any]:
        provider = await self.provider_service.get_provider(provider_id)
        runtime = await resolve_provider_runtime_async(provider)
        if getattr(runtime, "mode", "") != "in_process":
            raise ProviderError(
                provider_id,
                "Model downloads are only available for providers with an reachable in-process engine",
            )
        from services.engines.engine_factory import get_engine
        from services.in_process_reconciliation import trigger_targeted_model_downloads

        engine = get_engine(provider_id, provider)
        if engine is None:
            raise ProviderError(provider_id, "No in-process engine available for model download")
        result = await trigger_targeted_model_downloads(
            provider_id,
            file_ids,
            provider=provider,
            engine=engine,
        )
        self.invalidate_caches(provider_id)
        return result

    async def get_reconciliation_status(self, provider_id: str) -> dict[str, Any]:
        await self.provider_service.get_provider(provider_id)
        persisted_state = await self.provider_service.get_provider_reconciliation_state(provider_id)
        # The runner persists every phase to the same reconciliation state,
        # so the persisted row IS the live state — there is no worker to poll.
        if persisted_state.get("status"):
            return persisted_state
        return {
            "provider_id": provider_id,
            "status": "idle",
            "message": "No reconciliation has run yet for this provider",
        }
