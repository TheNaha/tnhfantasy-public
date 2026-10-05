# Provider routes - Complete implementation with feature parity to backend_v1
#
# KEY ENDPOINTS:
#   GET    /api/v2/providers              – List all configured providers
#   POST   /api/v2/providers              – Register a new provider
#   GET    /api/v2/providers/{id}         – Get provider details
#   PATCH  /api/v2/providers/{id}         – Update provider config/credentials
#   DELETE /api/v2/providers/{id}         – Remove provider + cascade status records
#   GET    /api/v2/providers/load-balancing – Current LB strategy
#   PUT    /api/v2/providers/load-balancing – Update LB strategy
#   POST   /api/v2/providers/{id}/reconcile – Trigger model sync
#   GET/POST /api/v2/providers/{id}/container/* – Container lifecycle management
import asyncio
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from api.deps import (
    get_event_bus,
    get_provider_lifecycle_service,
    get_provider_service,
    get_session,
)
from core.events import Event, EventType, emit_provider_stats
from core.exceptions import ComfyError, ProviderError, ValidationError
from infrastructure.logging import api_logger
from services.provider_service import ProviderService

from .lifecycle import _invalidate_provider_runtime_caches

logger = api_logger()




router = APIRouter()


# ============================================================================
# MODEL CACHE ENDPOINTS
# ============================================================================


@router.get("/model-cache")
def get_full_model_cache(session: Session = Depends(get_session)):
    """Get all model metadata from the backend cache."""
    service = get_provider_service(session)
    return {"models": service.get_model_cache()}


@router.get("/model-cache/{directory:path}")
def get_model_cache_for_directory(
    directory: str,
    session: Session = Depends(get_session)
):
    """Get model metadata for a specific directory."""
    service = get_provider_service(session)
    models = service.get_model_cache_for_directory(directory)
    return {
        "directory": directory,
        "models": models,
        "count": len(models)
    }



# ============================================================================
# MODEL RECONCILIATION ENDPOINTS
# ============================================================================


@router.post("/{provider_id}/reconcile")
async def reconcile_provider(
    provider_id: str,
    force: bool = False,
    quick_sync: bool = False,
    lifecycle = Depends(get_provider_lifecycle_service)
):
    """Trigger model reconciliation for a provider."""
    try:
        result = await lifecycle.trigger_reconciliation(provider_id, force=force, quick_sync=quick_sync)
    except ProviderError as exc:
        detail = str(exc)
        raise ComfyError(detail) from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409:
            raise ValidationError("Reconciliation already running in worker") from exc
        raise ProviderError(provider_id, f"Worker error: {exc!s}") from exc
    except httpx.HTTPError as exc:
        raise ComfyError(f"Failed to reach worker: {exc!s}") from exc

    if result.get("status") == "already_running":
        raise ValidationError(result.get("message", "Reconciliation already in progress"))
    return result


@router.get("/{provider_id}/reconciliation-status")
async def get_reconciliation_status(
    provider_id: str,
    lifecycle = Depends(get_provider_lifecycle_service)
):
    """Get current reconciliation status for a provider."""
    try:
        return await lifecycle.get_reconciliation_status(provider_id)
    except httpx.HTTPStatusError as exc:
        raise ProviderError(provider_id, "Failed to get reconciliation status") from exc


class ReconciliationEventRequest(BaseModel):
    """Request model for reconciliation event push from workers."""
    status: str  # reconciling, completed, failed
    phase: str | None = None  # validating, fetching, downloading, deleting
    stats: dict[str, Any] | None = None
    current_download: dict[str, Any] | None = None
    active_downloads: list[dict[str, Any]] | None = None  # For concurrent downloads
    errors: list[str] | None = None
    message: str | None = None


@router.post("/{provider_id}/reconciliation-event")
async def push_reconciliation_event(
    provider_id: str,
    request: ReconciliationEventRequest,
    service: ProviderService = Depends(get_provider_service),
    event_bus = Depends(get_event_bus)
):
    """
    Receive reconciliation events from worker containers.
    Emits them via WebSocket to connected frontends.
    Called by workers during reconciliation to push real-time updates.
    """
    # Map status to event type
    status_to_event = {
        "started": EventType.RECONCILIATION_STARTED,
        "queued": EventType.RECONCILIATION_STARTED,
        "reconciling": EventType.RECONCILIATION_PROGRESS,
        "progress": EventType.RECONCILIATION_PROGRESS,
        "completed": EventType.RECONCILIATION_COMPLETED,
        "failed": EventType.RECONCILIATION_FAILED,
    }
    
    event_type = status_to_event.get(request.status, EventType.RECONCILIATION_PROGRESS)
    
    normalized_status = ProviderService.normalize_reconciliation_status(request.status)

    # Build persistence updates. Keep existing stats when workers omit the field.
    # Some progress heartbeats intentionally skip stats; treating missing as {} would
    # clear previously reported totals and cause status-card regressions.
    persistence_updates = {
        "provider_id": provider_id,
        "status": normalized_status,
        "phase": request.phase,
        "current_download": request.current_download,
        "active_downloads": request.active_downloads or [],
        "errors": request.errors or [],
        "message": request.message,
        "last_contact_at": ProviderService._utcnow_iso(),
    }
    if request.stats is not None:
        persistence_updates["stats"] = request.stats

    # Build event payload for websocket listeners.
    event_data = {
        **persistence_updates,
        "stats": request.stats or {},
    }

    # Synchronous DB merge plus commit behind a decorative `async def` in both
    # `ProviderService` and `ProviderReconciliationService`, run inline on the
    # event loop on every worker heartbeat. The event publish below is genuinely
    # a coroutine but bottoms out at an uncontended `asyncio.Lock` inside
    # `EventBus.publish`, so it is the thread hop here, not the publish, that
    # makes this route safe on the loop.
    persisted_state = await asyncio.to_thread(
        service.upsert_reconciliation_state, provider_id, persistence_updates
    )
    _invalidate_provider_runtime_caches(provider_id)

    # Emit event via EventBus (will be broadcast to WebSocket clients)
    await event_bus.publish(Event(type=event_type, data=event_data))

    # Mirror reconciliation stats to provider.stats_update for event-first storage cards.
    if request.stats:
        await emit_provider_stats(provider_id, request.stats)
    
    return {"status": "ok", "event_type": event_type.value, "reconciliation_state": persisted_state}


