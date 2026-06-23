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

from .crud import AddCustomProviderModelRequest

from api.deps import get_session, get_provider_service, get_container_manager
from core.events import Event, EventType, emit_provider_stats, event_bus
from services.provider_service import ProviderService
from services.provider_lifecycle_service import ProviderLifecycleService
from services.provider_status_service import ProviderStatusService, invalidate_provider_status_caches
from core.exceptions import NotFoundError, ProviderError, ValidationError, ComfyError
from api.deps import start_background_task
from api.deps import get_http_client
from api.deps import api_logger
from config import get_worker_backend_url

logger = api_logger()




router = APIRouter()


# ============================================================================
# CONTAINER MANAGEMENT ENDPOINTS
# ============================================================================


@router.get("/containers/list")
def list_all_containers():
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


@router.get("/{provider_id}/live-metrics")
async def get_provider_live_metrics(provider_id: str, session: Session = Depends(get_session)):
    """Fetch live metrics directly from the remote provider container."""
    from services.provider_runtime import resolve_provider_runtime
    from api.deps import get_http_client
    import time
    
    service = get_provider_service(session)
    provider = await service.get_provider(provider_id)
    runtime = resolve_provider_runtime(provider)
    
    if not runtime.worker_url:
        return {"status": "offline", "latency_ms": 0, "error": "No worker URL configured"}
        
    try:
        http_client = get_http_client()
        start_t = time.time()
        res = await http_client.get(f"{runtime.worker_url}/info", timeout=5.0)
        res.raise_for_status()
        latency = int((time.time() - start_t) * 1000)
        info_data = res.json()
        
        return {
            "status": "online",
            "latency_ms": latency,
            "info": info_data,
        }
    except Exception as exc:
        return {
            "status": "offline",
            "latency_ms": 0,
            "error": str(exc),
        }


@router.get("/{provider_id}/logs")
async def get_provider_logs(provider_id: str, tail: int = 500, session: Session = Depends(get_session)):
    """Fetch recent container logs for a provider."""
    lifecycle = _get_provider_lifecycle_service(session)
    result = lifecycle.get_container_logs(provider_id, tail=tail)
    if "error" in result:
        return {"logs": [], "error": result["error"]}
    # Split the string of logs into an array of lines
    lines = result.get("logs", "").split("\n")
    return {"logs": lines}


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
    from services.model_service import ModelServiceV2
    from api.deps import create_provider_client

    normalized_directory = directory.replace("models/", "", 1)
    service = ModelServiceV2(session)
    file = service.repo.get_file_by_storage_path(normalized_directory, filename)
    if not file:
        raise NotFoundError("Resource", "Model file not found")

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
    from services.model_service import ModelServiceV2

    model_name = request.model_data.get("name", "").strip()
    model_url = request.model_data.get("url", "").strip()
    model_type = request.model_data.get("type")

    if not model_name or not model_url:
        raise ValidationError("Model name and URL are required")

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
        raise ComfyError(detail) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise ComfyError(f"Failed to run provider setup: {str(exc)}") from exc



# ============================================================================
# PROVIDER DEPLOYMENT ENDPOINT
# ============================================================================


@router.get("/{provider_id}/deploy-status")
async def get_provider_deploy_status(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """Get persisted backend deploy state for a provider or proxy from worker."""
    service = get_provider_service(session)
    provider = await service.get_provider(provider_id)
    from services.provider_runtime import resolve_provider_runtime
    runtime = resolve_provider_runtime(provider)
    
    if runtime.mode == "discovery":
        http_client = get_http_client()
        try:
            response = await http_client.get(f"{runtime.worker_url}/deploy-status", timeout=5.0)
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
            
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
        raise ValidationError(result.get("message", "Deployment already running"))
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
    from api.deps import get_model_repo_v2
    
    # Get list of active provider IDs
    service = get_provider_service(session)
    providers = await service.list_providers()
    active_provider_ids = [p["id"] for p in providers]
    
    # Clean up orphaned statuses
    model_repo = get_model_repo_v2(session)
    result = model_repo.cleanup_orphaned_provider_statuses(active_provider_ids)
    stale_reset_count = model_repo.reset_stale_downloading_statuses(
        stale_before=datetime.now(timezone.utc) - timedelta(minutes=120),
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
