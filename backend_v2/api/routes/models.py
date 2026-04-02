# Model routes
#
# ⚠️ DEPRECATED: This file uses the V1 Model schema (entities.Model)
# Please use models_v2.py routes which use the normalized V2 schema instead.
# V1 routes are maintained for backward compatibility only.
#
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException
from infrastructure.http_client import get_http_client

from sqlmodel import Session
from pydantic import BaseModel

from api.deps import get_session, get_model_service
from services.model_service import ModelService
from infrastructure.logging import get_logger

logger = get_logger("models_route")
from core.entities import ModelStatus
from core.exceptions import NotFoundError

router = APIRouter(prefix="/api/models", tags=["models (V1 - Deprecated)"])


class AddModelRequest(BaseModel):
    name: str
    directory: str
    url: Optional[str] = None
    source: str = "custom"
    metadata: Dict[str, Any] = {}


class UpdateStatusRequest(BaseModel):
    status: str


@router.get("")
async def list_models(session: Session = Depends(get_session)):
    """List all models grouped by directory."""
    service = get_model_service(session)
    return {"models": await service.get_models_grouped()}


@router.get("/all")
async def list_all_models(session: Session = Depends(get_session)):
    """List all models as flat list."""
    service = get_model_service(session)
    return await service.list_models()


@router.post("")
async def add_model(
    request: AddModelRequest,
    session: Session = Depends(get_session)
):
    """Add or update a model."""
    service = get_model_service(session)
    model = await service.add_model(
        name=request.name,
        directory=request.directory,
        url=request.url,
        source=request.source,
        metadata=request.metadata
    )
    return service._model_to_dict(model)


@router.get("/directory/{directory}")
async def list_models_by_directory(
    directory: str,
    session: Session = Depends(get_session)
):
    """List models in a specific directory."""
    service = get_model_service(session)
    return await service.list_models_by_directory(directory)


@router.get("/cache")
async def get_model_cache(session: Session = Depends(get_session)):
    """Get full model cache (for reconciliation)."""
    service = get_model_service(session)
    return {"models": service.get_full_cache()}


@router.put("/{directory}/{name}/providers/{provider_id}/status")
async def update_provider_status(
    directory: str,
    name: str,
    provider_id: str,
    request: UpdateStatusRequest,
    session: Session = Depends(get_session)
):
    """Update model status for a specific provider."""
    service = get_model_service(session)
    
    try:
        status = ModelStatus(request.status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {request.status}")
    
    model = await service.update_provider_status(
        name=name,
        directory=directory,
        provider_id=provider_id,
        status=status
    )
    
    return service._model_to_dict(model)


@router.delete("/{directory}/{name}")
async def delete_model(
    directory: str,
    name: str,
    session: Session = Depends(get_session)
):
    """Delete a model."""
    service = get_model_service(session)
    success = await service.delete_model(name=name, directory=directory)
    if not success:
        raise HTTPException(status_code=404, detail=f"Model {name} not found in {directory}")
    return {"status": "success"}


@router.get("/sync-status")
async def get_model_sync_status(
    provider: Optional[str] = None,
    session: Session = Depends(get_session)
):
    """
    Get model sync status for a provider.
    Shows which models are synced, pending, or missing.
    """
    service = get_model_service(session)
    
    # Get all models
    models = await service.list_models()
    
    # Build sync status
    sync_status = {
        "provider": provider,
        "total_models": len(models),
        "synced": 0,
        "pending": 0,
        "missing": 0,
        "models": []
    }
    
    for model in models:
        model_info = {
            "name": model.name if hasattr(model, 'name') else model.get('name'),
            "directory": model.directory if hasattr(model, 'directory') else model.get('directory'),
            "status": "synced"  # Default
        }
        
        # Check provider status if specified
        if provider and hasattr(model, 'provider_status'):
            provider_status = model.provider_status.get(provider, {})
            model_info["status"] = provider_status.get("status", "missing")
        
        sync_status["models"].append(model_info)
        
        if model_info["status"] == "synced":
            sync_status["synced"] += 1
        elif model_info["status"] == "pending":
            sync_status["pending"] += 1
        else:
            sync_status["missing"] += 1
    
    return sync_status


@router.post("/backfill-statuses")
async def backfill_provider_statuses(
    session: Session = Depends(get_session)
):
    """
    Backfill provider_statuses for all models by querying each provider.
    Useful for migrating existing models or after worker issues.
    """
    from api.deps import get_provider_service
    
    model_service = get_model_service(session)
    provider_service = get_provider_service(session)
    
    # Get all providers
    providers = await provider_service.list_providers()
    
    # Get all models
    models = await model_service.list_models()
    
    results = {
        "providers_checked": 0,
        "models_updated": 0,
        "errors": []
    }
    
    http_client = get_http_client()

    for provider in providers:
        container_config = (
            provider.get("runtime_config")
            if isinstance(provider, dict)
            else getattr(provider, "container_config", None)
        ) or {}
        if not container_config:
            continue
            
        # Use internal port (workers always run on 8000)
        internal_port = 8000
        provider_id = provider.get("id") if isinstance(provider, dict) else provider.id
        container_name = container_config.get("container_name", f"comfy-provider-{provider_id}")
        worker_url = f"http://{container_name}:{internal_port}"
        
        results["providers_checked"] += 1
        
        # Query each directory from the worker
        directories = ["checkpoints", "loras", "controlnet", "embeddings", "vae", "upscale_models"]
        
        for directory in directories:
            try:
                response = await http_client.post(
                    f"{worker_url}/list-models",
                    json={"directory": f"models/{directory}"},
                    timeout=10.0,
                )
                if response.status_code != 200:
                    continue
                
                data = response.json()
                provider_models = {m.get("name"): m for m in data.get("models", [])}
                
                for model in models:
                    model_name = model.name if hasattr(model, 'name') else model.get('name')
                    model_dir = model.directory if hasattr(model, 'directory') else model.get('directory')
                    
                    if model_dir != directory:
                        continue
                    
                    if model_name in provider_models:
                        try:
                            await model_service.update_provider_status(
                                name=model_name,
                                directory=model_dir,
                                provider_id=provider_id,
                                status=ModelStatus.INSTALLED,
                                extra_data={"size_bytes": provider_models[model_name].get("size")}
                            )
                            results["models_updated"] += 1
                        except Exception as e:
                            results["errors"].append(f"{model_name}: {str(e)}")
                            
            except Exception as e:
                results["errors"].append(f"{provider_id}/{directory}: {str(e)}")
    
    return results


class SyncProgressRequest(BaseModel):
    """Progress report from worker during model sync."""
    provider_id: str
    model_name: str
    directory: str
    progress: float  # 0-100
    status: str  # downloading, completed, failed
    message: Optional[str] = None
    size_bytes: Optional[int] = None


@router.post("/sync-progress")
async def receive_sync_progress(
    request: SyncProgressRequest,
    session: Session = Depends(get_session)
):
    """
    Receive sync progress from worker.
    Worker calls this endpoint to report download progress.
    Backend emits SSE event to frontend.
    """
    from core.events import event_bus, Event, EventType
    from api.deps import get_model_service
    
    # Determine event type based on status
    if request.status == "downloading":
        event_type = EventType.MODEL_SYNC_PROGRESS
    elif request.status == "completed":
        event_type = EventType.MODEL_SYNC_COMPLETED
    elif request.status == "failed":
        event_type = EventType.MODEL_SYNC_FAILED
    else:
        event_type = EventType.MODEL_SYNC_STARTED
    
    # Emit event for SSE subscribers
    event = Event(
        type=event_type,
        data={
            "provider_id": request.provider_id,
            "model_name": request.model_name,
            "directory": request.directory,
            "progress": request.progress,
            "status": request.status,
            "message": request.message,
            "size_bytes": request.size_bytes
        }
    )
    await event_bus.publish(event)
    
    # Update provider status in database if completed
    if request.status == "completed":
        service = get_model_service(session)
        try:
            await service.update_provider_status(
                name=request.model_name,
                directory=request.directory,
                provider_id=request.provider_id,
                status=ModelStatus.INSTALLED,
                extra_data={"size_bytes": request.size_bytes}
            )
        except Exception as e:
            logger.warning("provider_status_update_failed", error=str(e))
    elif request.status == "failed":
        service = get_model_service(session)
        try:
            await service.update_provider_status(
                name=request.model_name,
                directory=request.directory,
                provider_id=request.provider_id,
                status=ModelStatus.FAILED,
                extra_data={"error": request.message}
            )
        except Exception as e:
            logger.warning("provider_status_update_failed", error=str(e))
    
    return {"status": "ok"}


class BatchSyncItem(BaseModel):
    """Single item in batch sync request."""
    model_name: str
    directory: str
    status: str  # completed, pending, failed
    size_bytes: Optional[int] = None


class BatchSyncProgressRequest(BaseModel):
    """Batch sync progress from worker - updates multiple models at once."""
    provider_id: str
    models: List[BatchSyncItem]


@router.post("/sync-progress/batch")
async def receive_batch_sync_progress(
    request: BatchSyncProgressRequest,
    session: Session = Depends(get_session)
):
    """
    Receive batch sync progress from worker.
    Updates multiple model statuses in a single request.
    """
    service = get_model_service(session)
    
    updated = 0
    failed = 0
    
    for item in request.models:
        try:
            if item.status == "completed":
                await service.update_provider_status(
                    name=item.model_name,
                    directory=item.directory,
                    provider_id=request.provider_id,
                    status=ModelStatus.INSTALLED,
                    extra_data={"size_bytes": item.size_bytes}
                )
                updated += 1
            elif item.status == "failed":
                await service.update_provider_status(
                    name=item.model_name,
                    directory=item.directory,
                    provider_id=request.provider_id,
                    status=ModelStatus.FAILED
                )
                updated += 1
        except Exception as e:
            failed += 1
    
    return {
        "status": "ok",
        "updated": updated,
        "failed": failed
    }






class ParseUrlRequest(BaseModel):
    url: str


@router.post("/parse")
async def parse_model_url(request: ParseUrlRequest):
    """
    Parse a model URL to extract full metadata from CivitAI or HuggingFace.
    This fetches the actual model data from the source API.
    """
    import re
    
    url = request.url.strip()
    
    # CivitAI URL parsing
    if "civitai.com" in url:
        # Extract model ID from URL patterns like:
        # https://civitai.com/models/123456/model-name
        # https://civitai.com/models/123456?modelVersionId=789
        match = re.search(r'models/(\d+)', url)
        if not match:
            raise HTTPException(status_code=400, detail="Could not parse CivitAI model ID from URL")
        
        model_id = match.group(1)
        
        # Check for specific version in URL
        version_match = re.search(r'modelVersionId=(\d+)', url)
        version_id = version_match.group(1) if version_match else None
        
        try:
            api_url = f"https://civitai.com/api/v1/models/{model_id}"
            response = await get_http_client().get(api_url, timeout=15)
            response.raise_for_status()
            model_data = response.json()
            
            # Return in the same format as search results for consistency
            return model_data
            
        except requests.RequestException as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch from CivitAI: {str(e)}")
    
    # HuggingFace URL parsing
    elif "huggingface.co" in url:
        # Extract model path from URL patterns like:
        # https://huggingface.co/username/model-name
        # https://huggingface.co/username/model-name/tree/main
        match = re.search(r'huggingface\.co/([^/]+/[^/]+)', url)
        if not match:
            raise HTTPException(status_code=400, detail="Could not parse HuggingFace model path from URL")
        
        model_path = match.group(1)
        
        try:
            api_url = f"https://huggingface.co/api/models/{model_path}"
            response = await get_http_client().get(api_url, timeout=15)
            response.raise_for_status()
            hf_data = response.json()
            
            # Normalize to CivitAI-like format for consistent frontend handling
            return {
                "id": hf_data.get("id", model_path),
                "name": model_path.split("/")[-1],
                "type": "Checkpoint",
                "nsfw": False,
                "description": hf_data.get("description", ""),
                "creator": {"username": hf_data.get("author", model_path.split("/")[0])},
                "stats": {
                    "downloadCount": hf_data.get("downloads", 0),
                    "thumbsUpCount": hf_data.get("likes", 0)
                },
                "modelVersions": [{
                    "id": hf_data.get("sha", "main"),
                    "name": "main",
                    "baseModel": "Unknown",
                    "downloadUrl": f"https://huggingface.co/{model_path}/resolve/main/model.safetensors",
                    "files": [{
                        "name": "model.safetensors",
                        "sizeKB": 0,
                        "downloadUrl": f"https://huggingface.co/{model_path}/resolve/main/model.safetensors",
                        "primary": True
                    }],
                    "images": []
                }],
                "source": "huggingface"
            }
            
        except requests.RequestException as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch from HuggingFace: {str(e)}")
    
    else:
        raise HTTPException(
            status_code=400, 
            detail="URL must be from CivitAI (civitai.com) or HuggingFace (huggingface.co)"
        )


# ============================================================================
# PREVIEW IMAGES - Fetch from CivitAI/HuggingFace and cache
# ============================================================================

import os
from infrastructure.http_client import get_http_client
from fastapi import Response


# Cache directory for preview images
PREVIEW_CACHE_DIR = os.path.join(os.path.dirname(__file__), "../../cache/previews")


def get_cache_path(model_id: int, version_id: int = None) -> str:
    """Get cache path for a model preview image."""
    os.makedirs(PREVIEW_CACHE_DIR, exist_ok=True)
    if version_id:
        return os.path.join(PREVIEW_CACHE_DIR, f"{model_id}_{version_id}.jpg")
    return os.path.join(PREVIEW_CACHE_DIR, f"{model_id}.jpg")


async def fetch_civitai_preview(model_id: int, version_id: int = None) -> tuple:
    """Fetch preview image from CivitAI API and cache it."""
    cache_path = get_cache_path(model_id, version_id)
    
    # Check cache first
    if os.path.exists(cache_path):
        with open(cache_path, 'rb') as f:
            return f.read(), "image/jpeg"
    
    # Fetch from CivitAI API
    try:
        api_url = f"https://civitai.com/api/v1/models/{model_id}"
        response = await get_http_client().get(api_url, timeout=10)
        response.raise_for_status()
        model_data = response.json()
        
        # Get model versions
        model_versions = model_data.get('modelVersions', [])
        if not model_versions:
            return None, None
        
        # Find target version
        target_version = None
        if version_id:
            target_version = next((v for v in model_versions if v.get('id') == version_id), None)
        if not target_version:
            target_version = model_versions[0]
        
        # Find first image (skip videos)
        images = target_version.get('images', [])
        image_url = None
        for img in images:
            if img.get('type', 'image').lower() == 'image':
                image_url = img.get('url')
                break
        
        # Fallback to first image
        if not image_url and images:
            image_url = images[0].get('url')
        
        if not image_url:
            return None, None
        
        # Fetch the image
        img_response = await get_http_client().get(image_url, timeout=30)
        img_response.raise_for_status()
        image_data = img_response.content
        content_type = img_response.headers.get('Content-Type', 'image/jpeg')
        
        # Cache it
        with open(cache_path, 'wb') as f:
            f.write(image_data)
        
        return image_data, content_type
        
    except Exception as e:
        logger.warning("civitai_preview_fetch_failed", model_id=model_id, error=str(e))
        return None, None


@router.get("/preview-image")
async def get_model_preview_image(model_id: int, version_id: int = None):
    """
    Fetch and cache model preview image from CivitAI.
    Automatically filters out videos and returns the first image.
    """
    image_data, content_type = await fetch_civitai_preview(model_id, version_id)
    
    if not image_data:
        raise HTTPException(status_code=404, detail="Preview image not found")
    
    return Response(
        content=image_data,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Cache-Source": "civitai-proxy"
        }
    )


# ============================================================================
# SEARCH ENDPOINTS - CivitAI and HuggingFace
# ============================================================================

@router.get("/search/civitai")
async def search_civitai(query: str, limit: int = 20):
    """Search models on CivitAI."""
    import urllib.parse
    try:
        # Sentinel: URL-encode user-provided query to prevent SSRF and parameter injection
        encoded_query = urllib.parse.quote(query, safe='')
        url = f"https://civitai.com/api/v1/models?query={encoded_query}&limit={limit}"
        response = await get_http_client().get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            raise HTTPException(status_code=response.status_code, detail="CivitAI search failed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search/huggingface")
async def search_huggingface(query: str, limit: int = 20):
    """Search models on HuggingFace."""
    import urllib.parse
    try:
        # Sentinel: URL-encode user-provided query to prevent SSRF and parameter injection
        encoded_query = urllib.parse.quote(query, safe='')
        url = f"https://huggingface.co/api/models?search={encoded_query}&limit={limit}&filter=diffusers"
        response = await get_http_client().get(url, timeout=10)
        if response.status_code == 200:
            hf_models = response.json()
            
            # Normalize to CivitAI-like format
            items = []
            for model in hf_models[:limit]:
                items.append({
                    "id": model.get("id", ""),
                    "name": model.get("id", "").split("/")[-1],
                    "type": "Checkpoint",
                    "nsfw": False,
                    "creator": {"username": model.get("author", "")},
                    "modelVersions": [{
                        "id": model.get("sha", ""),
                        "name": "main",
                        "downloadUrl": f"https://huggingface.co/{model.get('id')}/resolve/main/model.safetensors",
                        "images": []
                    }],
                    "source": "huggingface"
                })
            
            return {"items": items}
        else:
            raise HTTPException(status_code=response.status_code, detail="HuggingFace search failed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

