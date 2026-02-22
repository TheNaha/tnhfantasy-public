# Model routes V2 - Version-aware model management
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from pydantic import BaseModel

from api.deps import get_session
from services.model_service_v2 import ModelServiceV2
from core.exceptions import NotFoundError

router = APIRouter(prefix="/api/v2/models", tags=["models-v2"])


# ============================================================================
# REQUEST MODELS
# ============================================================================

class AddModelRequest(BaseModel):
    """Request to add a model with selected versions."""
    civitai_data: Dict[str, Any]  # Full CivitAI API response
    selected_versions: List[Dict[str, Any]]  # [{version_id: int, is_default: bool}]


class UpdateProviderStatusRequest(BaseModel):
    """Request to update file status on a provider."""
    status: str  # pending, downloading, ready, failed
    storage_path: Optional[str] = None
    size_bytes: Optional[int] = None
    error_message: Optional[str] = None


class SetDefaultVersionRequest(BaseModel):
    """Request to set default version."""
    version_id: int


# ============================================================================
# HELPERS
# ============================================================================

def get_model_service(session: Session) -> ModelServiceV2:
    """Get model service instance."""
    return ModelServiceV2(session)


# ============================================================================
# MODEL ENDPOINTS
# ============================================================================

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


@router.get("/all-storage-paths")
async def get_all_storage_paths(session: Session = Depends(get_session)):
    """
    Get all expected storage paths from the V2 database.
    Used by worker to determine what files should exist vs what to delete.
    Returns paths like: models/checkpoints/model_v1_12345.safetensors
    """
    from sqlmodel import select
    from core.entities_v2 import ModelFile, ModelVersion, ModelV2
    
    # Query all files with their model directory
    stmt = select(ModelFile, ModelVersion, ModelV2).join(
        ModelVersion, ModelFile.version_id == ModelVersion.id
    ).join(
        ModelV2, ModelVersion.model_id == ModelV2.id
    )
    
    paths = []
    for file, version, model in session.exec(stmt).all():
        storage_path = f"models/{model.directory}/{file.storage_filename}"
        paths.append(storage_path)
    
    return {"paths": paths, "count": len(paths)}


@router.get("/check-installed/{civitai_model_id}")
async def check_installed_versions(
    civitai_model_id: int,
    session: Session = Depends(get_session)
):
    """
    Check if a CivitAI model and its versions are already installed.
    
    Returns:
    - model_installed: bool - whether any version of this model is installed
    - installed_versions: list of installed civitai_version_ids
    - model_id: local model ID if installed
    
    Use this before showing the import dialog to mark installed versions.
    """
    from sqlmodel import select
    from core.entities_v2 import ModelV2, ModelVersion
    
    # Check if model exists
    model = session.exec(
        select(ModelV2).where(ModelV2.civitai_model_id == civitai_model_id)
    ).first()
    
    if not model:
        return {
            "model_installed": False,
            "installed_versions": [],
            "model_id": None
        }
    
    # Get installed versions for this model
    versions = session.exec(
        select(ModelVersion).where(ModelVersion.model_id == model.id)
    ).all()
    
    installed_version_ids = [v.civitai_version_id for v in versions if v.civitai_version_id]
    
    return {
        "model_installed": True,
        "installed_versions": installed_version_ids,
        "model_id": model.id,
        "model_name": model.name
    }

@router.post("")
async def add_model(
    request: AddModelRequest,
    session: Session = Depends(get_session)
):
    """
    Add a model with selected versions.
    
    The civitai_data should be the full CivitAI API response.
    selected_versions should be: [{"version_id": 12345, "is_default": true}, ...]
    
    Prevents duplicate imports:
    - If model+version already exists, that version is skipped
    - New versions of existing models CAN be added
    """
    from core.entities_v2 import ModelVersion
    from sqlmodel import select
    
    service = get_model_service(session)
    
    # Extract version IDs from request
    selected_version_ids = [v["version_id"] for v in request.selected_versions]
    
    if not selected_version_ids:
        raise HTTPException(status_code=400, detail="At least one version must be selected")
    
    # Check for already installed versions
    already_installed = []
    new_version_ids = []
    
    for version_id in selected_version_ids:
        existing = session.exec(
            select(ModelVersion).where(ModelVersion.civitai_version_id == version_id)
        ).first()
        if existing:
            already_installed.append(version_id)
        else:
            new_version_ids.append(version_id)
    
    if not new_version_ids:
        # All versions already installed
        raise HTTPException(
            status_code=409, 
            detail=f"All selected versions are already installed: {already_installed}"
        )
    
    if already_installed:
        print(f"[Model Import] Skipping already installed versions: {already_installed}")
    
    model = await service.add_model_from_civitai(
        civitai_data=request.civitai_data,
        selected_version_ids=new_version_ids  # Only add new versions
    )
    
    result = model
    if already_installed:
        result["skipped_versions"] = already_installed
        result["message"] = f"Imported {len(new_version_ids)} new versions, skipped {len(already_installed)} already installed"
    
    return result


@router.get("/{model_id}")
async def get_model(
    model_id: int,
    session: Session = Depends(get_session)
):
    """Get model with versions, files, and images."""
    service = get_model_service(session)
    try:
        return await service.get_model(model_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Model {model_id} not found")


@router.delete("/{model_id}")
async def delete_model(
    model_id: int,
    session: Session = Depends(get_session)
):
    """Delete a model and all related data."""
    service = get_model_service(session)
    try:
        await service.delete_model(model_id)
        return {"status": "success"}
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Model {model_id} not found")


@router.post("/{model_id}/set-default-version/{version_id}")
async def set_default_version(
    model_id: int,
    version_id: int,
    session: Session = Depends(get_session)
):
    """
    Set the default version for a model.
    The default version is what gets selected when the model is chosen in the generator.
    """
    from core.entities_v2 import ModelVersion
    from sqlmodel import select
    
    # Verify model exists
    service = get_model_service(session)
    model = service.repo.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model {model_id} not found")
    
    # Verify version belongs to this model
    version = session.exec(
        select(ModelVersion).where(
            ModelVersion.id == version_id,
            ModelVersion.model_id == model_id
        )
    ).first()
    
    if not version:
        raise HTTPException(
            status_code=404, 
            detail=f"Version {version_id} not found for model {model_id}"
        )
    
    # Clear existing defaults
    all_versions = session.exec(
        select(ModelVersion).where(ModelVersion.model_id == model_id)
    ).all()
    
    for v in all_versions:
        v.is_default = (v.id == version_id)
        session.add(v)
    
    session.commit()
    
    return {
        "status": "success",
        "model_id": model_id,
        "new_default_version_id": version_id,
        "new_default_version_name": version.name
    }


@router.get("/directory/{directory}")
async def list_models_by_directory(
    directory: str,
    session: Session = Depends(get_session)
):
    """List models in a specific directory."""
    service = get_model_service(session)
    return await service.list_models_by_directory(directory)


@router.get("/search")
async def search_models(
    q: str = "",
    type: Optional[str] = None,
    base_model: Optional[str] = None,
    session: Session = Depends(get_session)
):
    """Search models by name, type, or base model."""
    service = get_model_service(session)
    return await service.search_models(query=q, model_type=type, base_model=base_model)


@router.get("/search/tag/{tag}")
async def search_by_tag(
    tag: str,
    session: Session = Depends(get_session)
):
    """Search models by tag."""
    service = get_model_service(session)
    return await service.search_by_tag(tag)


# ============================================================================
# VERSION ENDPOINTS
# ============================================================================

@router.get("/{model_id}/versions")
async def get_versions(
    model_id: int,
    session: Session = Depends(get_session)
):
    """Get all versions for a model."""
    service = get_model_service(session)
    return await service.get_versions(model_id)


@router.put("/{model_id}/default-version")
async def set_default_version(
    model_id: int,
    request: SetDefaultVersionRequest,
    session: Session = Depends(get_session)
):
    """Set the default version for a model."""
    service = get_model_service(session)
    success = await service.set_default_version(model_id, request.version_id)
    if success:
        return {"status": "success"}
    raise HTTPException(status_code=400, detail="Failed to set default version")


@router.put("/versions/{version_id}/toggle")
async def toggle_version_enabled(
    version_id: int,
    session: Session = Depends(get_session)
):
    """Toggle whether a version is enabled."""
    service = get_model_service(session)
    result = await service.toggle_version_enabled(version_id)
    if result:
        return result
    raise HTTPException(status_code=404, detail=f"Version {version_id} not found")


@router.get("/{model_id}/generation-info")
async def get_generation_info(
    model_id: int,
    version_id: Optional[int] = None,
    session: Session = Depends(get_session)
):
    """
    Get model/version info needed for generation.
    Returns storage path and other generation params.
    """
    service = get_model_service(session)
    try:
        return await service.get_version_for_generation(model_id, version_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ============================================================================
# PROVIDER STATUS ENDPOINTS
# ============================================================================

@router.get("/{model_id}/provider-status")
async def get_provider_statuses(
    model_id: int,
    session: Session = Depends(get_session)
):
    """Get provider download statuses for a model."""
    service = get_model_service(session)
    return await service.get_model_provider_statuses(model_id)


@router.put("/files/{file_id}/providers/{provider_name}/status")
async def update_file_provider_status(
    file_id: int,
    provider_name: str,
    request: UpdateProviderStatusRequest,
    session: Session = Depends(get_session)
):
    """Update provider status for a specific file."""
    service = get_model_service(session)
    result = await service.update_provider_file_status(
        file_id=file_id,
        provider_name=provider_name,
        status=request.status,
        storage_path=request.storage_path,
        size_bytes=request.size_bytes,
        error_message=request.error_message
    )
    
    # Emit WebSocket event to replace polling
    from core.events import emit_model_status_update
    await emit_model_status_update(
        provider_id=provider_name,
        file_id=file_id,
        status=request.status,
        extra={"storage_path": request.storage_path, "size_bytes": request.size_bytes}
    )
    
    return result


# ============================================================================
# RECONCILIATION ENDPOINTS
# ============================================================================

@router.get("/providers/{provider_name}/pending-downloads")
async def get_pending_downloads(
    provider_name: str,
    session: Session = Depends(get_session)
):
    """
    Get files pending download for a provider.
    Used by worker for reconciliation.
    """
    service = get_model_service(session)
    pending = service.get_pending_downloads(provider_name)
    return {"files": pending}


@router.get("/cache")
async def get_model_cache(session: Session = Depends(get_session)):
    """Get full model cache for reconciliation."""
    service = get_model_service(session)
    return {"models": service.get_full_cache()}





# ============================================================================
# BATCH UPDATES (for worker efficiency)
# ============================================================================

class BatchStatusUpdate(BaseModel):
    """Single item in batch status update."""
    file_id: Optional[int] = None  # Optional if storage_path provided
    status: str
    storage_path: Optional[str] = None  # Can be used to lookup file_id
    size_bytes: Optional[int] = None


class BatchUpdateRequest(BaseModel):
    """Batch status update from worker."""
    provider_name: str
    updates: List[BatchStatusUpdate]


@router.post("/providers/batch-status-update")
async def batch_update_status(
    request: BatchUpdateRequest,
    session: Session = Depends(get_session)
):
    """
    Batch update provider statuses.
    More efficient than individual calls during reconciliation.
    
    Supports two lookup modes:
    - By file_id (preferred, faster)
    - By storage_path (used when file_id unknown, e.g., reporting missing files)
    """
    from sqlmodel import select
    from core.entities_v2 import ModelFile, ModelVersion, ModelV2
    
    service = get_model_service(session)
    
    # Build storage_path -> file_id lookup if needed
    path_to_file_id = None
    needs_path_lookup = any(u.file_id is None and u.storage_path for u in request.updates)
    
    if needs_path_lookup:
        stmt = select(ModelFile, ModelVersion, ModelV2).join(
            ModelVersion, ModelFile.version_id == ModelVersion.id
        ).join(
            ModelV2, ModelVersion.model_id == ModelV2.id
        )
        path_to_file_id = {}
        for file, version, model in session.exec(stmt).all():
            storage_path = f"models/{model.directory}/{file.storage_filename}"
            path_to_file_id[storage_path] = file.id
    
    updated = 0
    failed = 0
    
    for update in request.updates:
        try:
            # Resolve file_id from storage_path if needed
            file_id = update.file_id
            if file_id is None and update.storage_path and path_to_file_id:
                file_id = path_to_file_id.get(update.storage_path)
            
            if file_id is None:
                failed += 1
                continue
            
            await service.update_provider_file_status(
                file_id=file_id,
                provider_name=request.provider_name,
                status=update.status,
                storage_path=update.storage_path,
                size_bytes=update.size_bytes
            )
            updated += 1
        except Exception:
            failed += 1
    
    return {"updated": updated, "failed": failed}


@router.delete("/providers/{provider_name}/reset-status")
async def reset_provider_status(
    provider_name: str,
    session: Session = Depends(get_session)
):
    """
    Reset all provider statuses for a provider.
    This will force re-download of ALL files on next reconciliation.
    Use with caution!
    """
    from sqlmodel import select, delete
    from core.entities_v2 import ProviderVersionStatus
    
    # Count before deleting
    count_stmt = select(ProviderVersionStatus).where(
        ProviderVersionStatus.provider_name == provider_name
    )
    count = len(list(session.exec(count_stmt).all()))
    
    # Delete all statuses for this provider
    stmt = delete(ProviderVersionStatus).where(
        ProviderVersionStatus.provider_name == provider_name
    )
    session.exec(stmt)
    session.commit()
    
    return {
        "status": "success",
        "message": f"Reset {count} status entries for provider '{provider_name}'",
        "deleted_count": count
    }


# ============================================================================
# MAINTENANCE ENDPOINTS
# ============================================================================

@router.post("/cleanup-orphans")
async def cleanup_orphan_models(session: Session = Depends(get_session)):
    """
    Remove models that have no versions (orphaned during failed imports or migration).
    These models cannot be used and should be cleaned up.
    """
    from sqlmodel import select, delete
    from core.entities_v2 import ModelV2, ModelVersion, ModelTag
    
    # Find all models with no versions
    all_models = session.exec(select(ModelV2)).all()
    orphans = []
    
    for model in all_models:
        version_count = len(list(session.exec(
            select(ModelVersion).where(ModelVersion.model_id == model.id)
        ).all()))
        if version_count == 0:
            orphans.append({"id": model.id, "name": model.name, "civitai_id": model.civitai_model_id})
    
    # Delete orphans
    deleted = []
    for orphan in orphans:
        # Delete tags first
        session.exec(delete(ModelTag).where(ModelTag.model_id == orphan["id"]))
        # Delete model
        model_to_delete = session.get(ModelV2, orphan["id"])
        if model_to_delete:
            session.delete(model_to_delete)
            deleted.append(orphan["name"])
    
    session.commit()
    
    return {
        "status": "success",
        "message": f"Cleaned up {len(deleted)} orphan models",
        "deleted_models": deleted
    }


@router.post("/migrate-unet")
async def migrate_unet_models(session: Session = Depends(get_session)):
    """
    Migrate UNET-only models (Flux, AuraFlow, Pony V7) from 'checkpoints' to 'unet' directory.
    
    Run this once after upgrading to fix models that were added before the UNET routing was implemented.
    Safe to run multiple times - only migrates models that need it.
    """
    service = get_model_service(session)
    result = service.repo.migrate_unet_only_models()
    
    return {
        "status": "success",
        "message": f"Migrated {result['count']} models to unet directory",
        "migrated": result["migrated"]
    }



@router.post("/{model_id}/check-dependencies")
async def check_dependencies(
    model_id: int,
    session: Session = Depends(get_session)
):
    """
    Check for and auto-download dependencies (CLIP, VAE) for a model.
    Useful for Flux/AuraFlow models if dependencies failed to download initially.
    """
    from core.entities_v2 import ModelVersion
    from sqlmodel import select
    
    service = get_model_service(session)
    
    # Get model to check existence
    model = await service.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
        
    # Get base model from default version
    versions = model.get("versions", [])
    if not versions:
        raise HTTPException(status_code=400, detail="Model has no versions")
        
    default_v = next((v for v in versions if v.get("is_default")), versions[0])
    base_model = default_v.get("base_model")
    
    if not base_model:
        raise HTTPException(status_code=400, detail="Model has no base model information")
    
    # Trigger check
    result = await service.check_and_trigger_dependencies(base_model_name=base_model)
    
    return {
        "status": "success",
        "result": result
    }


@router.post("/{model_id}/resync")
async def resync_model_from_civitai(
    model_id: int,
    session: Session = Depends(get_session)
):
    """
    Re-sync a model's metadata from CivitAI.
    This can fix models that were imported with incomplete data.
    
    Note: This only updates model-level metadata (name, description, stats).
    Version/file data cannot be updated without re-downloading.
    """
    import aiohttp
    from core.entities_v2 import ModelV2, ModelTag
    from sqlmodel import select, delete
    
    # Get the model
    model = session.get(ModelV2, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    
    if not model.civitai_model_id:
        raise HTTPException(status_code=400, detail="Model has no CivitAI ID - cannot resync")
    
    # Fetch fresh data from CivitAI
    url = f"https://civitai.com/api/v1/models/{model.civitai_model_id}"
    try:
        async with aiohttp.ClientSession() as http_session:
            async with http_session.get(url) as response:
                if response.status != 200:
                    raise HTTPException(status_code=502, detail=f"CivitAI API error: {response.status}")
                civitai_data = await response.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch from CivitAI: {str(e)}")
    
    # Update model metadata
    stats = civitai_data.get("stats", {})
    creator = civitai_data.get("creator", {})
    
    model.name = civitai_data.get("name", model.name)
    model.description = civitai_data.get("description")
    model.nsfw = civitai_data.get("nsfw", model.nsfw)
    model.nsfw_level = civitai_data.get("nsfwLevel", model.nsfw_level)
    model.creator_username = creator.get("username")
    model.creator_image = creator.get("image")
    model.stats_downloads = stats.get("downloadCount", 0)
    model.stats_thumbs_up = stats.get("thumbsUpCount", 0)
    model.stats_thumbs_down = stats.get("thumbsDownCount", 0)
    model.stats_comments = stats.get("commentCount", 0)
    
    # Update tags - delete old and add new
    session.exec(delete(ModelTag).where(ModelTag.model_id == model.id))
    for tag in civitai_data.get("tags", []):
        session.add(ModelTag(model_id=model.id, tag=tag))
    
    session.add(model)
    session.commit()
    
    # Get service for dict conversion
    service = get_model_service(session)
    
    return {
        "status": "success",
        "message": f"Resynced model '{model.name}' from CivitAI",
        "model": service.repo.model_to_dict(model)
    }


# ============================================================================
# EXTERNAL API INTEGRATION (CivitAI / HuggingFace)
# ============================================================================

import os
import re
import requests
from fastapi import Response


class ParseUrlRequest(BaseModel):
    url: str


@router.post("/external/parse")
async def parse_model_url(request: ParseUrlRequest):
    """
    Parse a model URL to extract full metadata from CivitAI or HuggingFace.
    This fetches the actual model data from the source API.
    """
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
            response = requests.get(api_url, timeout=15)
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
            response = requests.get(api_url, timeout=15)
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


@router.get("/external/civitai")
async def search_civitai(query: str, limit: int = 20):
    """Search models on CivitAI."""
    try:
        url = f"https://civitai.com/api/v1/models?query={query}&limit={limit}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            raise HTTPException(status_code=response.status_code, detail="CivitAI search failed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/external/huggingface")
async def search_huggingface(query: str, limit: int = 20):
    """Search models on HuggingFace."""
    try:
        url = f"https://huggingface.co/api/models?search={query}&limit={limit}&filter=diffusers"
        response = requests.get(url, timeout=10)
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


# ============================================================================
# PREVIEW IMAGES - Fetch from CivitAI and cache
# ============================================================================

# Cache directory for preview images
PREVIEW_CACHE_DIR = os.path.join(os.path.dirname(__file__), "../../cache/previews")


def get_cache_path(model_id: int, version_id: int = None) -> str:
    """Get cache path for a model preview image."""
    os.makedirs(PREVIEW_CACHE_DIR, exist_ok=True)
    if version_id:
        return os.path.join(PREVIEW_CACHE_DIR, f"{model_id}_{version_id}.jpg")
    return os.path.join(PREVIEW_CACHE_DIR, f"{model_id}.jpg")


def fetch_civitai_preview(model_id: int, version_id: int = None) -> tuple:
    """Fetch preview image from CivitAI API and cache it."""
    cache_path = get_cache_path(model_id, version_id)
    
    # Check cache first
    if os.path.exists(cache_path):
        with open(cache_path, 'rb') as f:
            return f.read(), "image/jpeg"
    
    # Fetch from CivitAI API
    try:
        api_url = f"https://civitai.com/api/v1/models/{model_id}"
        response = requests.get(api_url, timeout=10)
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
        img_response = requests.get(image_url, timeout=30)
        img_response.raise_for_status()
        image_data = img_response.content
        content_type = img_response.headers.get('Content-Type', 'image/jpeg')
        
        # Cache it
        with open(cache_path, 'wb') as f:
            f.write(image_data)
        
        return image_data, content_type
        
    except Exception as e:
        print(f"Failed to fetch CivitAI preview for {model_id}: {e}")
        return None, None


@router.get("/preview/{model_id}")
async def get_model_preview_image(model_id: int, version_id: int = None):
    """
    Fetch and cache model preview image from CivitAI.
    Automatically filters out videos and returns the first image.
    """
    image_data, content_type = fetch_civitai_preview(model_id, version_id)
    
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
# SYNC PROGRESS - Worker reports download progress
# ============================================================================

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
    Backend emits WebSocket event to frontend.
    """
    from core.events import event_bus, Event, EventType
    from core.entities import ModelStatus
    
    # Determine event type based on status
    if request.status == "downloading":
        event_type = EventType.MODEL_SYNC_PROGRESS
    elif request.status == "completed":
        event_type = EventType.MODEL_SYNC_COMPLETED
    elif request.status == "failed":
        event_type = EventType.MODEL_SYNC_FAILED
    else:
        event_type = EventType.MODEL_SYNC_STARTED
    
    # Emit event for WebSocket subscribers
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
    from core.entities import ModelStatus
    from api.deps import get_model_service as get_v1_model_service
    
    service = get_v1_model_service(session)
    
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


# ============================================================================
# BACKFILL UTILITY
# ============================================================================

@router.post("/backfill-statuses")
async def backfill_provider_statuses(
    session: Session = Depends(get_session)
):
    """
    Backfill provider_statuses for all models by querying each provider.
    Useful for migrating existing models or after worker issues.
    """
    import aiohttp
    from api.deps import get_provider_service, get_model_service as get_v1_model_service
    from core.entities import ModelStatus
    
    model_service = get_v1_model_service(session)
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
    
    for provider in providers:
        container_config = provider.container_config or {}
        if not container_config:
            continue
            
        # Use internal port (workers always run on 8000)
        internal_port = 8000
        container_name = container_config.get("container_name", f"comfy-provider-{provider.id}")
        worker_url = f"http://{container_name}:{internal_port}"
        
        results["providers_checked"] += 1
        
        # Query each directory from the worker
        directories = ["checkpoints", "loras", "controlnet", "embeddings", "vae", "upscale_models"]
        
        async with aiohttp.ClientSession() as http_session:
            for directory in directories:
                try:
                    async with http_session.get(
                        f"{worker_url}/list-models?directory=models/{directory}",
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
                        if response.status != 200:
                            continue
                        
                        data = await response.json()
                        provider_models = {m.get("name"): m for m in data.get("models", [])}
                        
                        # Update status for matching models in DB
                        for model in models:
                            model_name = model.name if hasattr(model, 'name') else model.get('name')
                            model_dir = model.directory if hasattr(model, 'directory') else model.get('directory')
                            
                            if model_dir != directory:
                                continue
                            
                            if model_name in provider_models:
                                # Model exists on this provider - mark as installed
                                try:
                                    await model_service.update_provider_status(
                                        name=model_name,
                                        directory=model_dir,
                                        provider_id=provider.id,
                                        status=ModelStatus.INSTALLED,
                                        extra_data={"size_bytes": provider_models[model_name].get("size")}
                                    )
                                    results["models_updated"] += 1
                                except Exception as e:
                                    results["errors"].append(f"{model_name}: {str(e)}")
                                    
                except Exception as e:
                    results["errors"].append(f"{provider.id}/{directory}: {str(e)}")
    
    return results
