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
from infrastructure.providers.runtime import get_provider_worker_base_url
from core.events import Event, EventType, emit_provider_stats, event_bus
from services.provider_service import ProviderService
from services.provider_lifecycle_service import ProviderLifecycleService
from services.provider_status_service import ProviderStatusService, invalidate_provider_status_caches
from core.exceptions import NotFoundError, ProviderError, ValidationError
from api.deps import start_background_task
from api.deps import get_http_client
from api.deps import api_logger
from config import get_worker_backend_url

logger = api_logger()




router = APIRouter()


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


class AddCustomProviderModelRequest(BaseModel):
    directory: str
    model_data: Dict[str, Any]
    provider_ids: List[str]



# ============================================================================
# LOAD BALANCER CONFIG
# ============================================================================


@router.get("/config/load-balancing")
async def get_load_balancing_config(session: Session = Depends(get_session)):
    """Get load balancing configuration with stats."""
    service = get_provider_service(session)
    config = service.get_load_balancing_config()
    stats = await service.get_load_balancer_stats()
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
    stats = await service.get_load_balancer_stats()
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
                    f"{get_provider_worker_base_url(provider_id)}/health",
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


@router.get("/")
async def list_providers(session: Session = Depends(get_session)):
    """List all providers."""
    service = get_provider_service(session)
    providers = await service.list_providers()
    status_service = ProviderStatusService(session, provider_service=service)
    records = await status_service.build_provider_records(providers)
    return {"providers": records, "count": len(records)}


@router.post("/")
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
    invalidate_provider_status_caches(provider_id)
    return {"status": "success"}


