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
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from pydantic import BaseModel
import aiohttp

from api.deps import get_session, get_provider_service, get_container_manager
from services.provider_service import ProviderService
from core.exceptions import NotFoundError, ValidationError
from infrastructure.logging import api_logger

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
    config: Dict[str, Any] = {}
    container_config: Optional[Dict[str, Any]] = None


class ProviderUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    priority: Optional[int] = None
    credentials: Optional[Dict[str, Any]] = None
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
        image_data = base64.b64decode(request.image_base64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 image data: {e}")
    
    from services.job_service import JobService
    from core.entities import JobStatus
    from infrastructure.database import get_session_context
    from infrastructure.logging import get_logger

    logger = get_logger("providers_route")

    if request.job_id:
        try:
            async with get_session_context() as session:
                job_service = JobService(session)
                job = await job_service.get_job(request.job_id)
                if job.status in [JobStatus.RUNNING, JobStatus.PROCESSING]:
                    await job_service.update_job(request.job_id, status=JobStatus.POST_PROCESSING)
        except Exception as e:
            logger.error(f"Error updating job status to POST_PROCESSING: {e}")

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
        gallery_indexer.add_file(result['path'])
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
        raise HTTPException(status_code=500, detail="Container manager not initialized")
    
    containers = container_manager.list_containers()
    return {"containers": containers}


# Cache for batch container status (10 second TTL)
from cachetools import TTLCache
_container_status_cache = TTLCache(maxsize=1, ttl=10)


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
        raise HTTPException(status_code=500, detail="Container manager not initialized")
    
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
    
    result = {"statuses": statuses, "cached": False}
    _container_status_cache['all_statuses'] = {**result, "cached": True}
    return result


# Cache for modal stats (30 second TTL to reduce Modal load)
_modal_stats_cache = TTLCache(maxsize=10, ttl=30)


@router.get("/{provider_id}/modal-stats")
async def get_provider_modal_stats(provider_id: str, session: Session = Depends(get_session)):
    """
    Get model counts directly from provider storage via worker container.
    Cached for 30 seconds to reduce load.
    Works with both Modal and Beam providers.
    """
    # Check cache first
    cache_key = f"modal_stats_{provider_id}"
    if cache_key in _modal_stats_cache:
        return _modal_stats_cache[cache_key]
    
    # Get provider to verify it exists  
    service = get_provider_service(session)
    provider = await service.get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    # Check if container is running
    container_manager = get_container_manager()
    if not container_manager:
        raise HTTPException(status_code=500, detail="Container manager not initialized")
    
    container_name = f"comfy-provider-{provider_id}"
    
    try:
        container = container_manager.client.containers.get(container_name)
        if container.status != "running":
            return {"provider_id": provider_id, "error": "Container not running", "total": 0}
    except Exception:
        return {"provider_id": provider_id, "error": "Container not found", "total": 0}
    
    # Get port from container config (provider is a Pydantic model)
    # Workers always run on internal port 8000
    internal_port = 8000
    
    # Use correct endpoint based on provider type
    provider_type = provider.type if hasattr(provider, 'type') else "modal"
    if provider_type == "beam":
        stats_endpoint = "/beam-stats"
    elif provider_type == "modal":
        stats_endpoint = "/modal-stats"
    else:
        stats_endpoint = "/provider-stats"  # Generic fallback
    
    worker_url = f"http://{container_name}:{internal_port}{stats_endpoint}"
    
    try:
        async with aiohttp.ClientSession() as http_session:
            async with http_session.get(
                worker_url,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    # Cache the result
                    _modal_stats_cache[cache_key] = result
                    return result
                else:
                    return {"provider_id": provider_id, "error": f"HTTP {response.status}", "total": 0}
            
    except Exception as e:
        print(f"[ModalStats] Error fetching from {provider_id}: {e}")
        return {"provider_id": provider_id, "error": str(e), "total": 0}


# ============================================================================
# PROVIDER CRUD ENDPOINTS
# ============================================================================

@router.post("/wake")
async def wake_providers(session: Session = Depends(get_session)):
    """Ping enabled provider containers to wake them up from cold start."""
    service = get_provider_service(session)
    providers = await service.list_providers()
    
    active_providers = [p for p in providers if p.get("enabled", True) and p.get("container_config")]
    
    if not active_providers:
        return {"status": "success", "message": "No active containerized providers to wake"}

    async def ping_containers():
        import asyncio
        import aiohttp
        async with aiohttp.ClientSession() as http:
            tasks = []
            for p in active_providers:
                p_id = p.get("id")
                # ping the root or health endpoint
                worker_url = f"http://comfy-provider-{p_id}:8000/health"
                tasks.append(
                    http.get(worker_url, timeout=aiohttp.ClientTimeout(total=5))
                )
            # Fire and forget; we don't care if they timeout during cold start
            await asyncio.gather(*tasks, return_exceptions=True)

    import asyncio
    asyncio.create_task(ping_containers())
    
    return {"status": "success", "message": f"Wake signal sent to {len(active_providers)} providers"}


@router.get("")
async def list_providers(session: Session = Depends(get_session)):
    """List all providers."""
    service = get_provider_service(session)
    return await service.list_providers()


@router.post("")
async def create_provider(
    request: ProviderRequest,
    session: Session = Depends(get_session)
):
    """Create a new provider."""
    service = get_provider_service(session)
    provider = await service.create_provider(request.model_dump())
    return service._provider_to_dict(provider)


@router.get("/{provider_id}")
async def get_provider(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """Get a provider by ID."""
    service = get_provider_service(session)
    provider = await service.get_provider(provider_id)
    return service._provider_to_dict(provider)


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
    return service._provider_to_dict(provider)


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
    container_manager = get_container_manager()
    if not container_manager:
        raise HTTPException(status_code=500, detail="Container manager not initialized")
    
    service = get_provider_service(session)
    providers = await service.list_providers()
    provider_config = next((p for p in providers if p["id"] == provider_id), None)
    
    if not provider_config:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
    
    container_config = provider_config.get("container_config")
    if not container_config:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider_id}' is not configured for containerized mode"
        )
    
    # Prepare environment variables from credentials
    credentials = provider_config.get("credentials", {})
    config = provider_config.get("config", {})
    provider_type = provider_config.get("type", "modal")
    
    env_vars = {}
    
    # =========================================================
    # Worker Settings (applies to both Modal and Beam)
    # =========================================================
    worker_cfg = config.get("worker", {})
    if "max_concurrent_downloads" in worker_cfg:
        env_vars["MAX_CONCURRENT_DOWNLOADS"] = str(worker_cfg["max_concurrent_downloads"])
    if "reconciliation_interval_hours" in worker_cfg:
        env_vars["RECONCILIATION_INTERVAL_SECONDS"] = str(int(worker_cfg["reconciliation_interval_hours"]) * 3600)
    if "validation_timeout_seconds" in worker_cfg:
        env_vars["VALIDATION_TIMEOUT_SECONDS"] = str(worker_cfg["validation_timeout_seconds"])
    
    # API tokens for model downloads
    if "hf_token" in credentials:
        env_vars["HF_TOKEN"] = credentials["hf_token"]
    if "civitai_token" in credentials:
        env_vars["CIVITAI_TOKEN"] = credentials["civitai_token"]
    
    # Per-function settings
    funcs = config.get("functions", {})
    
    if provider_type == "modal":
        # Modal credentials
        if "token_id" in credentials:
            env_vars["MODAL_TOKEN_ID"] = credentials["token_id"]
        if "token_secret" in credentials:
            env_vars["MODAL_TOKEN_SECRET"] = credentials["token_secret"]
        if "username" in credentials:
            env_vars["MODAL_USERNAME"] = credentials["username"]
        if "app_name" in config:
            env_vars["MODAL_APP_NAME"] = config["app_name"]
        # Note: enable_memory_snapshot is passed per-request via job payload,
        # so no env var needed - setting takes effect immediately
        
        # ComfyUI GPU function settings (for modal deploy)
        comfyui = funcs.get("comfyui", {})
        if "gpu_type" in comfyui:
            env_vars["MODAL_GPU_TYPE"] = comfyui["gpu_type"]
        if "cpu" in comfyui:
            env_vars["MODAL_GPU_CPU"] = str(comfyui["cpu"])
        if "timeout_seconds" in comfyui:
            env_vars["MODAL_GPU_TIMEOUT"] = str(comfyui["timeout_seconds"])
        if "max_containers" in comfyui:
            env_vars["MODAL_GPU_MAX_CONTAINERS"] = str(comfyui["max_containers"])
        if "scaledown_window_seconds" in comfyui:
            env_vars["MODAL_GPU_SCALEDOWN"] = str(comfyui["scaledown_window_seconds"])
        
        # Download function settings
        download = funcs.get("download", {})
        if "timeout_seconds" in download:
            env_vars["MODAL_DOWNLOAD_TIMEOUT"] = str(download["timeout_seconds"])
        if "max_containers" in download:
            env_vars["MODAL_DOWNLOAD_MAX_CONTAINERS"] = str(download["max_containers"])
        
        # Storage function settings
        storage = funcs.get("storage", {})
        if "timeout_seconds" in storage:
            env_vars["MODAL_STORAGE_TIMEOUT"] = str(storage["timeout_seconds"])
        if "max_containers" in storage:
            env_vars["MODAL_STORAGE_MAX_CONTAINERS"] = str(storage["max_containers"])
        
    elif provider_type == "beam":
        # Beam credentials
        if "api_key" in credentials:
            env_vars["BEAM_API_KEY"] = credentials["api_key"]
        if "workspace_id" in credentials:
            env_vars["BEAM_WORKSPACE_ID"] = credentials["workspace_id"]
        # Beam endpoint URLs from config
        if "gpu_url" in config:
            env_vars["BEAM_GPU_URL"] = config["gpu_url"]
        if "storage_url" in config:
            env_vars["BEAM_STORAGE_URL"] = config["storage_url"]
        if "download_url" in config:
            env_vars["BEAM_DOWNLOAD_URL"] = config["download_url"]
        if "gpu_type" in config:
            env_vars["BEAM_GPU_TYPE"] = config["gpu_type"]
        
        # GPU function settings (for beam deploy)
        gpu_func = funcs.get("comfyui", {})
        if "gpu_type" in gpu_func:
            env_vars["BEAM_GPU_TYPE"] = gpu_func["gpu_type"]
        if "cpu" in gpu_func:
            env_vars["BEAM_GPU_CPU"] = str(gpu_func["cpu"])
        if "memory" in gpu_func:
            env_vars["BEAM_GPU_MEMORY"] = gpu_func["memory"]
        if "timeout_seconds" in gpu_func:
            env_vars["BEAM_GPU_TIMEOUT"] = str(gpu_func["timeout_seconds"])
        if "keep_warm_seconds" in gpu_func:
            env_vars["BEAM_GPU_KEEP_WARM"] = str(gpu_func["keep_warm_seconds"])
        if "concurrent_requests" in gpu_func:
            env_vars["BEAM_GPU_CONCURRENT"] = str(gpu_func["concurrent_requests"])
        
        # Download function settings (separate deployment)
        download = funcs.get("download", {})
        if "cpu" in download:
            env_vars["BEAM_DOWNLOAD_CPU"] = str(download["cpu"])
        if "memory" in download:
            env_vars["BEAM_DOWNLOAD_MEMORY"] = download["memory"]
        if "timeout_seconds" in download:
            env_vars["BEAM_DOWNLOAD_TIMEOUT"] = str(download["timeout_seconds"])
        if "max_containers" in download:
            env_vars["BEAM_DOWNLOAD_MAX_CONTAINERS"] = str(download["max_containers"])
        
        # Storage function settings
        storage = funcs.get("storage", {})
        if "cpu" in storage:
            env_vars["BEAM_STORAGE_CPU"] = str(storage["cpu"])
        if "memory" in storage:
            env_vars["BEAM_STORAGE_MEMORY"] = storage["memory"]
        if "timeout_seconds" in storage:
            env_vars["BEAM_STORAGE_TIMEOUT"] = str(storage["timeout_seconds"])
        if "concurrent_requests" in storage:
            env_vars["BEAM_STORAGE_CONCURRENT"] = str(storage["concurrent_requests"])

    
    # Start container
    container = container_manager.start_container(
        provider_id=provider_id,
        provider_type=provider_type,
        port=container_config["port"],
        env_vars=env_vars
    )

    # Emit status event
    from core.events import event_bus, Event, EventType
    await event_bus.publish(Event(
        type=EventType.PROVIDER_CONTAINER_STATUS,
        data={
            "provider_id": provider_id,
            "status": "running"
        }
    ))
    
    return {
        "status": "success",
        "message": f"Container for provider '{provider_id}' started",
        "container_id": container.short_id
    }


@router.post("/{provider_id}/container/stop")
async def stop_provider_container(provider_id: str):
    """Stop a provider's container."""
    container_manager = get_container_manager()
    if not container_manager:
        raise HTTPException(status_code=500, detail="Container manager not initialized")
    
    container_manager.stop_container(provider_id)

    # Emit status event
    from core.events import event_bus, Event, EventType
    await event_bus.publish(Event(
        type=EventType.PROVIDER_CONTAINER_STATUS,
        data={
            "provider_id": provider_id,
            "status": "stopped"
        }
    ))

    return {
        "status": "success",
        "message": f"Container for provider '{provider_id}' stopped"
    }


@router.post("/{provider_id}/container/restart")
async def restart_provider_container(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """Restart a provider's container."""
    await stop_provider_container(provider_id)
    result = await start_provider_container(provider_id, session)

    # Emit status event (already emitted by start, but good to be explicit if needed)
    # The start call above will emit 'running'.
    
    return {
        "status": "success",
        "message": f"Container for provider '{provider_id}' restarted"
    }


@router.get("/{provider_id}/container/logs")
async def get_provider_container_logs(provider_id: str, tail: int = 100):
    """Get logs from a provider's container."""
    container_manager = get_container_manager()
    if not container_manager:
        raise HTTPException(status_code=500, detail="Container manager not initialized")
    
    logs = container_manager.get_container_logs(provider_id, tail=tail)
    return {
        "provider_id": provider_id,
        "logs": logs
    }


@router.get("/{provider_id}/container/status")
async def get_provider_container_status(provider_id: str):
    """Get status of a provider's container."""
    container_manager = get_container_manager()
    if not container_manager:
        raise HTTPException(status_code=500, detail="Container manager not initialized")
    
    container_name = f"comfy-provider-{provider_id}"
    
    # Query Docker/Podman directly instead of relying on in-memory dict
    try:
        container = container_manager.client.containers.get(container_name)
    except Exception:
        # Container doesn't exist
        return {
            "provider_id": provider_id,
            "status": "stopped",
            "running": False
        }
    
    # Reload container info
    container.reload()
    
    # Check health via container's health status or HTTP probe
    healthy = False
    try:
        # First check container's own health status if available
        health_status = container.attrs.get('State', {}).get('Health', {}).get('Status')
        if health_status:
            healthy = health_status == 'healthy'
        else:
            # Fallback to HTTP health check
            import requests
            port = container.ports.get('8000/tcp')
            if port:
                host_port = port[0]['HostPort']
                response = requests.get(f"http://localhost:{host_port}/health", timeout=2)
                healthy = response.status_code == 200
    except:
        pass
    
    # Also update the in-memory dict so future calls are faster
    if container.status == "running":
        container_manager.running_containers[provider_id] = container
    elif provider_id in container_manager.running_containers:
        del container_manager.running_containers[provider_id]
    
    return {
        "provider_id": provider_id,
        "status": container.status,
        "running": container.status == "running",
        "healthy": healthy,
        "container_id": container.short_id,
        "ports": container.ports
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
    service = get_provider_service(session)
    provider = await service.get_provider(provider_id)
    
    if provider.type != "modal":
        raise HTTPException(status_code=400, detail="Setup is only available for Modal providers")
    
    # Check container config for worker URL
    container_config = provider.container_config or {}
    if container_config:
        # Use internal port (workers always run on 8000)
        internal_port = 8000
        container_name = container_config.get("container_name", f"comfy-provider-{provider_id}")
        worker_url = f"http://{container_name}:{internal_port}"
        
        async with aiohttp.ClientSession() as http_session:
            async with http_session.post(f"{worker_url}/setup") as response:
                response.raise_for_status()
                result = await response.json()
        
        return {
            "status": "success",
            "message": f"Provider '{provider_id}' setup complete (via worker)",
            "result": result
        }
    else:
        raise HTTPException(
            status_code=400,
            detail="Setup requires containerized mode with worker"
        )


# ============================================================================
# MODEL RECONCILIATION ENDPOINTS
# ============================================================================

@router.post("/{provider_id}/reconcile")
async def reconcile_provider(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """Trigger model reconciliation for a provider."""
    service = get_provider_service(session)
    provider = await service.get_provider(provider_id)
    
    container_config = provider.container_config or {}
    if not container_config:
        raise HTTPException(
            status_code=400,
            detail="Reconciliation only supported for containerized providers"
        )
    
    # Note: container_config['port'] is the HOST port (external mapping)
    # Workers always run on port 8000 internally
    internal_port = 8000
    container_name = container_config.get("container_name", f"comfy-provider-{provider_id}")
    worker_url = f"http://{container_name}:{internal_port}"
    
    try:
        async with aiohttp.ClientSession() as http_session:
            async with http_session.post(
                f"{worker_url}/reconcile",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    return {
                        "status": "triggered",
                        "provider_id": provider_id,
                        "message": "Reconciliation started in worker"
                    }
                else:
                    body = await response.text()
                    raise HTTPException(
                        status_code=response.status,
                        detail=f"Failed to trigger reconciliation: {body}"
                    )
    except aiohttp.ClientError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reach worker: {str(e)}"
        )


@router.get("/{provider_id}/reconciliation-status")
async def get_reconciliation_status(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """Get current reconciliation status for a provider."""
    service = get_provider_service(session)
    provider = await service.get_provider(provider_id)
    
    container_config = provider.container_config or {}
    if not container_config:
        return {
            "provider_id": provider_id,
            "status": "idle",
            "message": "Status tracking only available for containerized providers"
        }
    
    # Use internal port (workers always run on 8000)
    internal_port = 8000
    container_name = container_config.get("container_name", f"comfy-provider-{provider_id}")
    worker_url = f"http://{container_name}:{internal_port}"
    
    try:
        async with aiohttp.ClientSession() as http_session:
            async with http_session.get(
                f"{worker_url}/reconciliation-status",
                timeout=aiohttp.ClientTimeout(total=30)  # Increased for slow Modal SDK calls
            ) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 404:
                    return {
                        "provider_id": provider_id,
                        "status": "idle",
                        "message": "Status tracking not available"
                    }
                else:
                    raise HTTPException(
                        status_code=response.status,
                        detail="Failed to get reconciliation status"
                    )
    except aiohttp.ClientError as e:
        return {
            "provider_id": provider_id,
            "status": "error",
            "error": f"Cannot reach worker: {str(e)}"
        }


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
        "reconciling": EventType.RECONCILIATION_PROGRESS,
        "progress": EventType.RECONCILIATION_PROGRESS,
        "completed": EventType.RECONCILIATION_COMPLETED,
        "failed": EventType.RECONCILIATION_COMPLETED,  # Use completed for failure too
    }
    
    event_type = status_to_event.get(request.status, EventType.RECONCILIATION_PROGRESS)
    
    # Build event data
    event_data = {
        "provider_id": provider_id,
        "status": request.status,
        "phase": request.phase,
        "stats": request.stats or {},
        "current_download": request.current_download,
        "active_downloads": request.active_downloads or [],
        "errors": request.errors or [],
        "message": request.message
    }
    
    # Emit event via EventBus (will be broadcast to WebSocket clients)
    await event_bus.publish(Event(type=event_type, data=event_data))
    
    return {"status": "ok", "event_type": event_type.value}


# ============================================================================
# PROVIDER DEPLOYMENT ENDPOINT
# ============================================================================

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
    if not container_manager:
        raise HTTPException(status_code=500, detail="Container manager not initialized")
    
    service = get_provider_service(session)
    provider = await service.get_provider(provider_id)
    
    # Get running container
    container = container_manager.running_containers.get(provider_id)
    if not container:
        # Try to get from Docker/Podman directly
        container_name = f"comfy-provider-{provider_id}"
        try:
            container = container_manager.client.containers.get(container_name)
            if container.status != "running":
                raise HTTPException(
                    status_code=400,
                    detail=f"Container for provider '{provider_id}' is not running. Start the container first."
                )
        except Exception:
            raise HTTPException(
                status_code=400,
                detail=f"Container for provider '{provider_id}' not found. Start the container first."
            )
    
    provider_type = provider.type
    
    if provider_type == "modal":
        print(f"[Deploy] Deploying Modal app for {provider_id} via container exec...")
        
        try:
            # Run modal deploy in worker container
            exec_result = container.exec_run(
                cmd=["modal", "deploy", "/app/modal_app.py"],
                stream=False,
                demux=True
            )
            
            stdout = exec_result.output[0].decode('utf-8') if exec_result.output[0] else ""
            stderr = exec_result.output[1].decode('utf-8') if exec_result.output[1] else ""
            output = stdout + stderr
            
            print(f"[Deploy] Output: {output}")
            
            if exec_result.exit_code != 0:
                raise HTTPException(
                    status_code=500,
                    detail=f"Modal deploy failed (exit code {exec_result.exit_code}): {output}"
                )
            
            return {
                "status": "success",
                "provider_type": "modal",
                "message": f"Modal app deployed for {provider_id}",
                "output": output
            }
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Deployment error: {str(e)}")
    
    elif provider_type == "beam":
        print(f"[Deploy] Deploying Beam apps for {provider_id} via container exec...")
        
        # Beam has two endpoints to deploy
        deployments = [
            ("comfy_gpu", ["beam", "deploy", "/app/beam_app.py:comfy_gpu"]),
            ("comfy_storage", ["beam", "deploy", "/app/beam_app.py:comfy_storage"]),
        ]
        
        results = []
        for name, cmd in deployments:
            print(f"[Deploy] Running: {' '.join(cmd)}")
            
            try:
                exec_result = container.exec_run(
                    cmd=cmd,
                    stream=False,
                    demux=True
                )
                
                stdout = exec_result.output[0].decode('utf-8') if exec_result.output[0] else ""
                stderr = exec_result.output[1].decode('utf-8') if exec_result.output[1] else ""
                output = stdout + stderr
                
                print(f"[Deploy] {name} output: {output}")
                
                results.append({
                    "name": name,
                    "success": exec_result.exit_code == 0,
                    "exit_code": exec_result.exit_code,
                    "output": output
                })
                
            except Exception as e:
                results.append({
                    "name": name,
                    "success": False,
                    "exit_code": -1,
                    "output": str(e)
                })
        
        # Check if all deployments succeeded
        all_success = all(r["success"] for r in results)
        
        if not all_success:
            failed = [r for r in results if not r["success"]]
            raise HTTPException(
                status_code=500,
                detail=f"Beam deploy failed for: {', '.join(r['name'] for r in failed)}. Check logs for details."
            )
        
        return {
            "status": "success",
            "provider_type": "beam",
            "message": f"Beam apps deployed for {provider_id}",
            "deployments": results
        }
    
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Deployment not supported for provider type: {provider_type}"
        )


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
    
    return {
        "status": "success",
        "message": f"Cleaned up {result['deleted_count']} orphaned status entries",
        "deleted_count": result["deleted_count"],
        "orphaned_providers": result["orphaned_providers"],
        "active_providers": active_provider_ids
    }
