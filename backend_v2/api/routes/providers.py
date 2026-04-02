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
from datetime import datetime, timedelta
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from pydantic import BaseModel

from api.deps import get_session, get_provider_service, get_container_manager
from core.events import Event, EventType, event_bus
from services.provider_service import ProviderService
from services.provider_lifecycle_service import ProviderLifecycleService
from services.provider_status_service import ProviderStatusService, invalidate_provider_status_caches
from core.exceptions import NotFoundError, ProviderError, ValidationError
from infrastructure.background_tasks import start_background_task
from infrastructure.http_client import get_http_client
from infrastructure.logging import api_logger
from config import get_worker_backend_url

logger = api_logger()

router = APIRouter(prefix="/api/providers", tags=["providers"])


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class ProviderRequest(BaseModel):
    id: str
    type: str = "modal"
    enabled: bool = True
    priority: int = 1
    credentials: Dict[str, Any] = {}
    runtime_config: Optional[Dict[str, Any]] = None
    deploy_config: Optional[Dict[str, Any]] = None
    # Legacy compatibility fields accepted on write only.
    config: Dict[str, Any] = {}
    container_config: Optional[Dict[str, Any]] = None


class ProviderUpdateRequest(BaseModel):
    type: Optional[str] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None
    credentials: Optional[Dict[str, Any]] = None
    runtime_config: Optional[Dict[str, Any]] = None
    deploy_config: Optional[Dict[str, Any]] = None
    # Legacy compatibility fields accepted on write only.
    config: Optional[Dict[str, Any]] = None
    container_config: Optional[Dict[str, Any]] = None


class LoadBalancingConfigRequest(BaseModel):
    strategy: Optional[str] = None
    fallback_enabled: Optional[bool] = None


class SaveImageRequest(BaseModel):
    """Request to save a generated image from worker."""
    image_base64: str
    job_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    filename: Optional[str] = None
    batch_index: int = 0


class AddCustomProviderModelRequest(BaseModel):
    directory: str
    model_data: Dict[str, Any]
    provider_ids: List[str]


# ============================================================================
# IMAGE SAVING ENDPOINT (must be before /{provider_id} route)
# ============================================================================

@router.post("/save-image")
async def save_generated_image(request: SaveImageRequest):
    """
    Receive generated image from worker and save with metadata.
    
    Called by worker containers after ComfyUI generates an image.
    Uses ImageService to:
    - Save to date-based folder structure (output/YYYY/MM/DD/)
    - Embed metadata in PNG chunks
    - Generate WebP thumbnail
    - Generate blurhash for placeholder
    
    Returns saved image info for frontend display.
    """
    import base64
    from services.image_service import get_image_service
    
    try:
        image_data = base64.b64decode(request.image_base64, validate=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 image data: {e}")

    service = get_image_service()
    
    result = await service.save_generated_image(
        image_data=image_data,
        metadata=request.metadata,
        job_id=request.job_id,
        filename=request.filename,
        batch_index=request.batch_index
    )
    
    try:
        from services.gallery_indexer import gallery_indexer
        await asyncio.to_thread(gallery_indexer.add_file, result['path'])
    except Exception as e:
        logger.error(f"Error updating gallery indexer: {e}")

    return result


# ============================================================================
# MODEL CACHE ENDPOINTS (must be before /{provider_id} route)
# ============================================================================

@router.get("/model-cache")
async def get_full_model_cache(session: Session = Depends(get_session)):
    """Get all model metadata from the backend cache."""
    service = get_provider_service(session)
    return {"models": service.get_model_cache()}


@router.get("/model-cache/{directory:path}")
async def get_model_cache_for_directory(
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
# LOAD BALANCER CONFIG  (must be before /{provider_id} route)
# ============================================================================

@router.get("/config/load-balancing")
async def get_load_balancing_config(session: Session = Depends(get_session)):
    """Get load balancing configuration with stats."""
    service = get_provider_service(session)
    config = service.get_load_balancing_config()
    stats = service.get_load_balancer_stats()
    return {
        "config": {
            "strategy": config.strategy,
            "fallback_enabled": config.fallback_enabled
        },
        "stats": stats
    }


@router.put("/config/load-balancing")
async def update_load_balancing_config(
    request: LoadBalancingConfigRequest,
    session: Session = Depends(get_session)
):
    """Update load balancing configuration."""
    service = get_provider_service(session)
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    config = await service.update_load_balancing_config(**updates)
    return {
        "status": "success",
        "strategy": config.strategy,
        "fallback_enabled": config.fallback_enabled
    }


@router.get("/load-balancer/stats")
async def get_load_balancer_stats(session: Session = Depends(get_session)):
    """Get load balancer statistics."""
    service = get_provider_service(session)
    stats = service.get_load_balancer_stats()
    return stats


# Alias paths for frontend compatibility
@router.get("/load-balancing")
async def get_load_balancing_alias(session: Session = Depends(get_session)):
    """Alias for /config/load-balancing."""
    return await get_load_balancing_config(session)


@router.put("/load-balancing")
async def update_load_balancing_alias(
    request: LoadBalancingConfigRequest,
    session: Session = Depends(get_session)
):
    """Alias for /config/load-balancing."""
    return await update_load_balancing_config(request, session)


# ============================================================================
# CONTAINER MANAGEMENT ENDPOINTS (must be before /{provider_id} route)
# ============================================================================

@router.get("/containers/list")
async def list_all_containers():
    """List all provider containers."""
    container_manager = get_container_manager()
    if not container_manager:
        return {
            "containers": [],
            "container_runtime_available": False
        }
    
    containers = container_manager.list_containers()
    return {
        "containers": containers,
        "container_runtime_available": True
    }


# Cache for batch container status (10 second TTL)
from cachetools import TTLCache
_container_status_cache = TTLCache(maxsize=1, ttl=10)


def _invalidate_provider_runtime_caches(provider_id: Optional[str] = None) -> None:
    """Clear route-level and provider-status caches after runtime changes."""
    _container_status_cache.clear()
    invalidate_provider_status_caches(provider_id)


def _get_provider_lifecycle_service(session: Session) -> ProviderLifecycleService:
    provider_service = get_provider_service(session)
    return ProviderLifecycleService(
        session,
        provider_service=provider_service,
        container_manager=get_container_manager(),
        invalidate_caches=_invalidate_provider_runtime_caches,
    )


@router.get("/containers/status")
async def get_all_container_statuses(session: Session = Depends(get_session)):
    """
    Get status of all provider containers in a single call.
    Cached for 10 seconds to reduce Docker/Podman queries.
    """
    # Check cache first
    if 'all_statuses' in _container_status_cache:
        return _container_status_cache['all_statuses']
    
    container_manager = get_container_manager()
    if not container_manager:
        return {
            "statuses": {},
            "cached": False,
            "container_runtime_available": False
        }
    
    # Get all providers
    service = get_provider_service(session)
    providers = await service.list_providers()
    
    statuses = {}
    for provider in providers:
        provider_id = provider["id"]
        container_name = f"comfy-provider-{provider_id}"
        
        try:
            container = container_manager.client.containers.get(container_name)
            container.reload()
            
            # Check health
            healthy = False
            health_status = container.attrs.get('State', {}).get('Health', {}).get('Status')
            if health_status:
                healthy = health_status == 'healthy'
            
            statuses[provider_id] = {
                "status": container.status,
                "running": container.status == "running",
                "healthy": healthy,
                "container_id": container.short_id
            }
            
            # Update in-memory dict
            if container.status == "running":
                container_manager.running_containers[provider_id] = container
        except Exception:
            statuses[provider_id] = {
                "status": "stopped",
                "running": False,
                "healthy": False
            }
    
    result = {
        "statuses": statuses,
        "cached": False,
        "container_runtime_available": True
    }
    _container_status_cache['all_statuses'] = {**result, "cached": True}
    return result


@router.get("/status-cards")
async def get_provider_status_cards(session: Session = Depends(get_session)):
    """Return canonical provider status payloads for all configured providers."""
    service = get_provider_service(session)
    providers = await service.list_providers()
    status_service = ProviderStatusService(session, provider_service=service)
    cards = await status_service.build_provider_status_cards(providers)

    return {
        "status_cards": cards,
        "count": len(cards),
    }


@router.get("/{provider_id}/status-card")
async def get_provider_status_card(provider_id: str, session: Session = Depends(get_session)):
    """Return canonical provider status payload for a single provider."""
    service = get_provider_service(session)
    status_service = ProviderStatusService(session, provider_service=service)
    return await status_service.build_provider_status_card(provider_id)


@router.get("/{provider_id}/modal-stats")
async def get_provider_modal_stats(provider_id: str, session: Session = Depends(get_session)):
    """
    Get model counts directly from provider storage via worker container.
    Cached for 30 seconds to reduce load.
    Works with both Modal and Beam providers.
    """
    # Get provider to verify it exists
    service = get_provider_service(session)
    provider = await service.get_provider(provider_id)
    status_service = ProviderStatusService(session, provider_service=service)
    return await status_service.get_provider_storage_stats(provider_id, provider)


@router.get("/{provider_id}/sync-status")
async def get_provider_sync_status(provider_id: str, session: Session = Depends(get_session)):
    """Return V2-backed sync counts for a provider."""
    status_service = ProviderStatusService(session)
    return await status_service.get_provider_sync_status(provider_id)


@router.get("/{provider_id}/models")
async def get_provider_models(provider_id: str, status: Optional[str] = None, session: Session = Depends(get_session)):
    """Return provider models grouped by directory using the V2 schema."""
    sync_status = await get_provider_sync_status(provider_id, session)
    grouped: Dict[str, List[Dict[str, Any]]] = {}

    for model in sync_status["models"]:
        model_status = model["provider_status"]["status"]
        if status and model_status != status:
            continue
        grouped.setdefault(model["directory"], []).append(model)

    return {
        "provider": provider_id,
        "models": grouped,
    }


@router.delete("/{provider_id}/models")
async def remove_model_from_provider(
    provider_id: str,
    directory: str,
    filename: str,
    session: Session = Depends(get_session)
):
    """Delete a model file from one provider and mark it pending again in V2."""
    from services.model_service_v2 import ModelServiceV2
    from infrastructure.providers import create_provider_client

    normalized_directory = directory.replace("models/", "", 1)
    service = ModelServiceV2(session)
    file = service.repo.get_file_by_storage_path(normalized_directory, filename)
    if not file:
        raise HTTPException(status_code=404, detail="Model file not found")

    provider_service = get_provider_service(session)
    provider = await provider_service.get_provider(provider_id)
    provider_client = create_provider_client(provider_id, {
        "type": provider.type,
        "credentials": provider.credentials,
        "config": provider.config,
        "container_config": provider.container_config or {}
    })

    storage_path = f"models/{normalized_directory}/{filename}"
    try:
        await provider_client.get_file_proxy().delete_file(storage_path)
    except Exception as exc:
        logger.warning("provider_model_delete_failed", provider_id=provider_id, path=storage_path, error=str(exc))

    await service.update_provider_file_status(
        file_id=file.id,
        provider_name=provider_id,
        status="pending",
        storage_path=storage_path,
        size_bytes=None,
        error_message=None,
    )

    return {
        "status": "success",
        "provider_id": provider_id,
        "directory": f"models/{normalized_directory}",
        "filename": filename,
    }


@router.post("/models/custom")
async def add_custom_model_to_providers(
    request: AddCustomProviderModelRequest,
    session: Session = Depends(get_session)
):
    """Create a V2 custom model entry and trigger downloads for the selected providers."""
    from services.model_service_v2 import ModelServiceV2

    model_name = request.model_data.get("name", "").strip()
    model_url = request.model_data.get("url", "").strip()
    model_type = request.model_data.get("type")

    if not model_name or not model_url:
        raise HTTPException(status_code=400, detail="Model name and URL are required")

    service = ModelServiceV2(session)
    result = await service.add_custom_model(
        name=model_name,
        directory=request.directory,
        download_url=model_url,
        provider_ids=request.provider_ids,
        model_type=model_type,
    )
    return {
        "status": "success",
        "model": result,
        "provider_ids": request.provider_ids,
    }


# ============================================================================
# PROVIDER CRUD ENDPOINTS
# ============================================================================

@router.post("/wake")
async def wake_providers(session: Session = Depends(get_session)):
    """Ping enabled provider containers to wake them up from cold start."""
    service = get_provider_service(session)
    providers = service.get_enabled_providers()
    active_providers = [provider for provider in providers if provider.container_config]
    
    if not active_providers:
        return {"status": "success", "message": "No active containerized providers to wake"}

    async def ping_containers():
        http_client = get_http_client()

        async def ping_worker(provider_id: str):
            try:
                await http_client.get(
                    f"http://comfy-provider-{provider_id}:8000/health",
                    timeout=5.0,
                )
            except Exception:
                return None
            return None

        await asyncio.gather(
            *(ping_worker(provider.id) for provider in active_providers),
            return_exceptions=True,
        )

    start_background_task(ping_containers(), task_name="wake_provider_containers")
    
    return {"status": "success", "message": f"Wake signal sent to {len(active_providers)} providers"}


@router.get("")
async def list_providers(session: Session = Depends(get_session)):
    """List all providers."""
    service = get_provider_service(session)
    providers = await service.list_providers()
    status_service = ProviderStatusService(session, provider_service=service)
    records = await status_service.build_provider_records(providers)
    return {"providers": records, "count": len(records)}


@router.post("")
async def create_provider(
    request: ProviderRequest,
    session: Session = Depends(get_session)
):
    """Create a new provider."""
    service = get_provider_service(session)
    provider = await service.create_provider(request.model_dump())
    status_service = ProviderStatusService(session, provider_service=service)
    return await status_service.build_provider_record(provider.id, provider=provider)


@router.get("/{provider_id}")
async def get_provider(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """Get a provider by ID."""
    service = get_provider_service(session)
    status_service = ProviderStatusService(session, provider_service=service)
    return await status_service.build_provider_record(provider_id)


@router.put("/{provider_id}")
async def update_provider(
    provider_id: str,
    request: ProviderUpdateRequest,
    session: Session = Depends(get_session)
):
    """Update a provider."""
    service = get_provider_service(session)
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    provider = await service.update_provider(provider_id, updates)
    status_service = ProviderStatusService(session, provider_service=service)
    return await status_service.build_provider_record(provider.id, provider=provider)


# PATCH alias for frontend compatibility
@router.patch("/{provider_id}")
async def patch_provider(
    provider_id: str,
    request: ProviderUpdateRequest,
    session: Session = Depends(get_session)
):
    """Update a provider (PATCH alias)."""
    return await update_provider(provider_id, request, session)


@router.delete("/{provider_id}")
async def delete_provider(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """Delete a provider."""
    service = get_provider_service(session)
    await service.delete_provider(provider_id)
    _container_status_cache.clear()
    invalidate_provider_status_caches(provider_id)
    return {"status": "success"}


# ============================================================================
# CONTAINER MANAGEMENT ENDPOINTS (provider-specific)
# ============================================================================

@router.post("/{provider_id}/container/start")
async def start_provider_container(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """Start a provider's container."""
    lifecycle = _get_provider_lifecycle_service(session)
    try:
        return await lifecycle.start_container(provider_id)
    except ProviderError as exc:
        detail = str(exc)
        status_code = 400 if "not configured for containerized mode" in detail else 500
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.post("/{provider_id}/container/stop")
async def stop_provider_container(provider_id: str, session: Session = Depends(get_session)):
    """Stop a provider's container."""
    lifecycle = _get_provider_lifecycle_service(session)
    try:
        return await lifecycle.stop_container(provider_id)
    except ProviderError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{provider_id}/container/restart")
async def restart_provider_container(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """Restart a provider's container."""
    lifecycle = _get_provider_lifecycle_service(session)
    try:
        return await lifecycle.restart_container(provider_id)
    except ProviderError as exc:
        detail = str(exc)
        status_code = 400 if "not configured for containerized mode" in detail else 500
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("/{provider_id}/container/logs")
async def get_provider_container_logs(provider_id: str, tail: int = 100, session: Session = Depends(get_session)):
    """Get logs from a provider's container."""
    lifecycle = _get_provider_lifecycle_service(session)
    try:
        return lifecycle.get_container_logs(provider_id, tail=tail)
    except ProviderError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{provider_id}/container/status")
async def get_provider_container_status(provider_id: str, session: Session = Depends(get_session)):
    """Get status of a provider's container."""
    lifecycle = _get_provider_lifecycle_service(session)
    try:
        return lifecycle.get_container_status(provider_id)
    except ProviderError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ============================================================================
# PROVIDER SETUP ENDPOINT
# ============================================================================

@router.post("/{provider_id}/setup")
async def setup_provider(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """Run Modal's setup_models function to initialize directories."""
    try:
        lifecycle = _get_provider_lifecycle_service(session)
        return await lifecycle.setup_provider(provider_id)
    except ProviderError as exc:
        detail = str(exc)
        status_code = 400 if "Setup requires" in detail else 500
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to run provider setup: {str(exc)}") from exc


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
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409:
            raise HTTPException(status_code=409, detail="Reconciliation already running in worker") from exc
        raise HTTPException(status_code=exc.response.status_code, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to reach worker: {str(exc)}") from exc

    if result.get("status") == "already_running":
        raise HTTPException(status_code=409, detail=result.get("message", "Reconciliation already in progress"))
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
        raise HTTPException(status_code=exc.response.status_code, detail="Failed to get reconciliation status") from exc


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
    from core.events import event_bus, Event, EventType
    
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
    
    # Build event data
    event_data = {
        "provider_id": provider_id,
        "status": ProviderService.normalize_reconciliation_status(request.status),
        "phase": request.phase,
        "stats": request.stats or {},
        "current_download": request.current_download,
        "active_downloads": request.active_downloads or [],
        "errors": request.errors or [],
        "message": request.message,
        "last_contact_at": ProviderService._utcnow_iso(),
    }

    service = get_provider_service(session)
    persisted_state = await service.upsert_reconciliation_state(provider_id, event_data)
    _invalidate_provider_runtime_caches(provider_id)
    
    # Emit event via EventBus (will be broadcast to WebSocket clients)
    await event_bus.publish(Event(type=event_type, data=event_data))
    
    return {"status": "ok", "event_type": event_type.value, "reconciliation_state": persisted_state}


# ============================================================================
# PROVIDER DEPLOYMENT ENDPOINT
# ============================================================================

@router.get("/{provider_id}/deploy-status")
async def get_provider_deploy_status(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """Get persisted backend deploy state for a provider."""
    service = get_provider_service(session)
    return await service.get_provider_deploy_state(provider_id)

@router.post("/{provider_id}/deploy")
async def deploy_provider_app(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """
    Deploy provider app (Modal or Beam) by running CLI commands in the worker container.
    
    For Modal: Runs `modal deploy /backend/modal_app.py`
    For Beam: Runs `beam deploy /backend/beam_app.py:comfy_gpu` and `comfy_storage`
    
    The CLI commands run in the worker container which has:
    - Provider credentials set as environment variables
    - Backend files mounted at /backend/ (via HOST_BACKEND_PATH volume)
    """
    container_manager = get_container_manager()
    service = get_provider_service(session)
    result = await service.deploy_provider_app(provider_id, container_manager)
    if result.get("status") == "already_running":
        raise HTTPException(status_code=409, detail=result.get("message", "Deployment already running"))
    _invalidate_provider_runtime_caches(provider_id)
    if "deploy_state" in result and "deploy" not in result:
        result["deploy"] = result["deploy_state"]
    return result


# ============================================================================
# PROVIDER STATUS CLEANUP
# ============================================================================

@router.post("/cleanup-orphaned-statuses")
async def cleanup_orphaned_provider_statuses(session: Session = Depends(get_session)):
    """
    Clean up ProviderVersionStatus records for providers that no longer exist.
    This fixes the desync between model status indicators and actual provider list.
    
    Should be run once after deleting providers to clean up orphaned status entries
    from before the cascade delete feature was added.
    """
    from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2
    
    # Get list of active provider IDs
    service = get_provider_service(session)
    providers = await service.list_providers()
    active_provider_ids = [p["id"] for p in providers]
    
    # Clean up orphaned statuses
    model_repo = ModelRepositoryV2(session)
    result = model_repo.cleanup_orphaned_provider_statuses(active_provider_ids)
    stale_reset_count = model_repo.reset_stale_downloading_statuses(
        stale_before=datetime.utcnow() - timedelta(minutes=120),
        provider_names=active_provider_ids,
    )
    _invalidate_provider_runtime_caches()

    return {
        "status": "success",
        "message": f"Cleaned up {result['deleted_count']} orphaned status entries and reset {stale_reset_count} stale downloads",
        "deleted_count": result["deleted_count"],
        "orphaned_providers": result["orphaned_providers"],
        "active_providers": active_provider_ids,
        "orphaned_statuses_removed": result["deleted_count"],
        "stale_downloading_reset": stale_reset_count,
        "affected_provider_ids": sorted(set(active_provider_ids + result["orphaned_providers"])),
    }


@router.post("/state/cleanup")
async def cleanup_provider_state(session: Session = Depends(get_session)):
    """Explicit maintenance action for provider state hygiene."""
    return await cleanup_orphaned_provider_statuses(session)
