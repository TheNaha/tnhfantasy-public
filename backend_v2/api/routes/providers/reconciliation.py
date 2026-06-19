# Provider routes - Complete implementation with feature parity to backend_v1
#
# KEY ENDPOINTS:
#   GET    /api/providers              – List all configured providers
#   POST   /api/providers              – Register a new provider
#   GET    /api/providers/{id}         – Get provider details
#   PATCH  /api/providers/{id}         – Update provider config/credentials
#   DELETE /api/providers/{id}         – Remove provider + cascade status records
#   GET    /api/providers/load-balancing – Current LB strategy
#   PUT    /api/providers/load-balancing – Update LB strategy
#   POST   /api/providers/{id}/reconcile – Trigger model sync
#   GET/POST /api/providers/{id}/container/* – Container lifecycle management
from typing import Dict, Any, Optional, List
import asyncio
from datetime import datetime, timezone, timedelta
import httpx
from fastapi import APIRouter, Depends
from sqlmodel import Session
from pydantic import BaseModel

from api.deps import get_session, get_provider_service, get_container_manager
from core.events import Event, EventType, emit_provider_stats, event_bus
from services.provider_service import ProviderService
from services.provider_lifecycle_service import ProviderLifecycleService
from services.provider_status_service import ProviderStatusService, invalidate_provider_status_caches
from core.exceptions import NotFoundError, ProviderError, ValidationError, ComfyError
from infrastructure.background_tasks import start_background_task
from infrastructure.http_client import get_http_client
from infrastructure.logging import api_logger
from config import get_worker_backend_url
from .lifecycle import _get_provider_lifecycle_service, _invalidate_provider_runtime_caches

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
    session: Session = Depends(get_session)
):
    """Trigger model reconciliation for a provider."""
    try:
        lifecycle = _get_provider_lifecycle_service(session)
        result = await lifecycle.trigger_reconciliation(provider_id)
    except ProviderError as exc:
        detail = str(exc)
        status_code = 400 if "Reconciliation is only available" in detail else 500
        raise ComfyError(detail) from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409:
            raise ValidationError("Reconciliation already running in worker") from exc
        raise ProviderError(provider_id, f"Worker error: {str(exc)}") from exc
    except httpx.HTTPError as exc:
        raise ComfyError(f"Failed to reach worker: {str(exc)}") from exc

    if result.get("status") == "already_running":
        raise ValidationError(result.get("message", "Reconciliation already in progress"))
    return result


@router.get("/{provider_id}/reconciliation-status")
async def get_reconciliation_status(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """Get current reconciliation status for a provider."""
    try:
        lifecycle = _get_provider_lifecycle_service(session)
        return await lifecycle.get_reconciliation_status(provider_id)
    except httpx.HTTPStatusError as exc:
        raise ProviderError(provider_id, "Failed to get reconciliation status") from exc


class ReconciliationEventRequest(BaseModel):
    """Request model for reconciliation event push from workers."""
    status: str  # reconciling, completed, failed
    phase: Optional[str] = None  # validating, fetching, downloading, deleting
    stats: Optional[Dict[str, Any]] = None
    current_download: Optional[Dict[str, Any]] = None
    active_downloads: Optional[List[Dict[str, Any]]] = None  # For concurrent downloads
    errors: Optional[List[str]] = None
    message: Optional[str] = None


@router.post("/{provider_id}/reconciliation-event")
async def push_reconciliation_event(
    provider_id: str,
    request: ReconciliationEventRequest,
    session: Session = Depends(get_session)
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
        "failed": EventType.RECONCILIATION_COMPLETED,  # Use completed for failure too
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

    service = get_provider_service(session)
    persisted_state = await service.upsert_reconciliation_state(provider_id, persistence_updates)
    _invalidate_provider_runtime_caches(provider_id)

    # Emit event via EventBus (will be broadcast to WebSocket clients)
    await event_bus.publish(Event(type=event_type, data=event_data))

    # Mirror reconciliation stats to provider.stats_update for event-first storage cards.
    if request.stats:
        await emit_provider_stats(provider_id, request.stats)
    
    return {"status": "ok", "event_type": event_type.value, "reconciliation_state": persisted_state}


