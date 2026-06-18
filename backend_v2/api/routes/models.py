# Model routes V2 - Version-aware model management using the normalized schema
#
# These routes operate on the V2 model schema (models_v2, model_versions,
# model_files, provider_version_status) which stores full CivitAI metadata
# with per-version and per-file granularity.
#
# KEY ENDPOINTS:
#   POST   /api/v2/models                        – Import a CivitAI model
#   GET    /api/v2/models                        – List models with per-provider status
#   GET    /api/v2/models/{id}                   – Get single model details
#   DELETE /api/v2/models/{id}                   – Delete model + all provider statuses
#   GET    /api/v2/models/external/civitai       – Search CivitAI for new models
#   PATCH  /api/v2/models/{id}/versions/{vid}/status/{pid} – Update provider file status
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException

from sqlmodel import Session
from pydantic import BaseModel

from api.deps import get_session, get_session_sync
from services.model_service import ModelServiceV2
from core.exceptions import NotFoundError
from infrastructure.logging import model_logger

logger = model_logger()

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


class CheckInstalledBatchRequest(BaseModel):
    """Batch request for checking installed CivitAI models."""
    civitai_model_ids: List[int]


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
def get_all_storage_paths(session: Session = Depends(get_session)):
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
def check_installed_versions(
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


@router.post("/check-installed/batch")
def check_installed_versions_batch(
    request: CheckInstalledBatchRequest,
    session: Session = Depends(get_session),
):
    """
    Batch variant of check-installed to avoid one request per model card.

    Returns:
    {
      "models": {
        "<civitai_model_id>": {
          "model_installed": bool,
          "installed_versions": [int],
          "model_id": int | null,
          "model_name": str | null
        }
      }
    }
    """
    from sqlmodel import select
    from core.entities_v2 import ModelV2, ModelVersion

    requested_ids = [mid for mid in request.civitai_model_ids if isinstance(mid, int)]
    if not requested_ids:
        return {"models": {}}

    unique_ids = sorted(set(requested_ids))
    models = session.exec(
        select(ModelV2).where(ModelV2.civitai_model_id.in_(unique_ids))
    ).all()

    if not models:
        return {
            "models": {
                str(model_id): {
                    "model_installed": False,
                    "installed_versions": [],
                    "model_id": None,
                    "model_name": None,
                }
                for model_id in unique_ids
            }
        }

    model_ids = [model.id for model in models if model.id is not None]
    versions = session.exec(
        select(ModelVersion).where(ModelVersion.model_id.in_(model_ids))
    ).all()

    versions_by_model_id = {}
    for version in versions:
        versions_by_model_id.setdefault(version.model_id, []).append(version)

    response = {}
    models_by_civitai_id = {
        model.civitai_model_id: model
        for model in models
        if model.civitai_model_id is not None
    }

    for civitai_model_id in unique_ids:
        model = models_by_civitai_id.get(civitai_model_id)
        if not model:
            response[str(civitai_model_id)] = {
                "model_installed": False,
                "installed_versions": [],
                "model_id": None,
                "model_name": None,
            }
            continue

        installed_version_ids = [
            version.civitai_version_id
            for version in versions_by_model_id.get(model.id, [])
            if version.civitai_version_id is not None
        ]

        response[str(civitai_model_id)] = {
            "model_installed": True,
            "installed_versions": installed_version_ids,
            "model_id": model.id,
            "model_name": model.name,
        }

    return {"models": response}

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
        logger.info("model_import_skip_installed", versions=already_installed)
    
    model = await service.add_model_from_civitai(
        civitai_data=request.civitai_data,
        selected_version_ids=new_version_ids  # Only add new versions
    )
    
    result = model
    if already_installed:
        result["skipped_versions"] = already_installed
        result["message"] = f"Imported {len(new_version_ids)} new versions, skipped {len(already_installed)} already installed"
    
    return result


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
async def set_default_version_modern(
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
def get_pending_downloads(
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
def get_model_cache(session: Session = Depends(get_session)):
    """Get full model cache for reconciliation."""
    service = get_model_service(session)
    return {"models": service.get_full_cache()}


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
    provider_name: Optional[str] = None
    provider_id: Optional[str] = None
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
    provider_key = request.provider_id or request.provider_name
    if not provider_key:
        raise HTTPException(status_code=422, detail="provider_id or provider_name is required")
    
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
                provider_name=provider_key,
                status=update.status,
                storage_path=update.storage_path,
                size_bytes=update.size_bytes
            )
            updated += 1
        except Exception:
            failed += 1
    
    return {"updated": updated, "failed": failed}


@router.delete("/providers/{provider_name}/reset-status")
def reset_provider_status(
    provider_name: str,
    session: Session = Depends(get_session)
):
    """
    Reset all provider statuses for a provider.
    This will force re-download of ALL files on next reconciliation.
    Use with caution!
    """
    from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2

    model_repo = ModelRepositoryV2(session)
    count = model_repo.delete_all_statuses_for_provider(provider_name)
    
    return {
        "status": "success",
        "message": f"Reset {count} status entries for provider '{provider_name}'",
        "deleted_count": count
    }


# ============================================================================
# MAINTENANCE ENDPOINTS
# ============================================================================

@router.post("/cleanup-orphans")
def cleanup_orphan_models(session: Session = Depends(get_session)):
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
# PREVIEW IMAGES - Fetch from CivitAI and cache
# ============================================================================

import os
import asyncio
import time
import random
import httpx
from fastapi import Response
from infrastructure.http_client import get_http_client
from infrastructure.request_dedup import deduplicated, make_key

def _resolve_preview_cache_dir() -> str:
    configured_dir = os.getenv("COMFY_PREVIEW_CACHE_DIR")
    if configured_dir:
        return configured_dir

    output_dir = os.getenv("OUTPUT_DIR")
    if output_dir:
        return os.path.join(output_dir, "cache", "previews")

    return os.path.join(os.path.dirname(__file__), "../../cache/previews")


def _resolve_preview_timeout_seconds(env_name: str, default_value: float) -> float:
    raw_value = os.getenv(env_name)
    if raw_value is None:
        return default_value

    try:
        parsed = float(raw_value)
    except (TypeError, ValueError):
        logger.warning(
            "preview_timeout_invalid",
            env_name=env_name,
            raw_value=raw_value,
            default_value=default_value,
        )
        return default_value

    if parsed <= 0:
        logger.warning(
            "preview_timeout_non_positive",
            env_name=env_name,
            raw_value=raw_value,
            default_value=default_value,
        )
        return default_value

    return parsed


def _resolve_preview_failure_ttl_seconds() -> int:
    default_ttl_seconds = 600
    raw_value = os.getenv("COMFY_PREVIEW_FAILURE_TTL_SECONDS")
    if raw_value is None:
        return default_ttl_seconds

    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        logger.warning(
            "preview_failure_ttl_invalid",
            raw_value=raw_value,
            default_value=default_ttl_seconds,
        )
        return default_ttl_seconds

    if parsed < 0:
        logger.warning(
            "preview_failure_ttl_negative",
            raw_value=raw_value,
            default_value=default_ttl_seconds,
        )
        return default_ttl_seconds

    return parsed


def _resolve_preview_not_found_ttl_seconds() -> int:
    """Cooldown for CivitAI model IDs that return 404 (deleted/invalid)."""
    default_ttl_seconds = 6 * 60 * 60
    raw_value = os.getenv("COMFY_PREVIEW_NOT_FOUND_TTL_SECONDS")
    if raw_value is None:
        return default_ttl_seconds

    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        logger.warning(
            "preview_not_found_ttl_invalid",
            raw_value=raw_value,
            default_value=default_ttl_seconds,
        )
        return default_ttl_seconds

    if parsed < 0:
        logger.warning(
            "preview_not_found_ttl_negative",
            raw_value=raw_value,
            default_value=default_ttl_seconds,
        )
        return default_ttl_seconds

    return parsed


# Cache directory for preview images (prefer persistent output volume when available)
PREVIEW_CACHE_DIR = _resolve_preview_cache_dir()
PREVIEW_METADATA_TIMEOUT_SECONDS = _resolve_preview_timeout_seconds(
    "COMFY_PREVIEW_METADATA_TIMEOUT_SECONDS",
    6.0,
)
PREVIEW_IMAGE_TIMEOUT_SECONDS = _resolve_preview_timeout_seconds(
    "COMFY_PREVIEW_IMAGE_TIMEOUT_SECONDS",
    8.0,
)
PREVIEW_FAILURE_TTL_SECONDS = _resolve_preview_failure_ttl_seconds()
PREVIEW_NOT_FOUND_TTL_SECONDS = _resolve_preview_not_found_ttl_seconds()


def _resolve_preview_prefetch_enabled() -> bool:
    raw_value = os.getenv("COMFY_PREVIEW_PREFETCH_ENABLED")
    if raw_value is None:
        return True
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_preview_prefetch_interval_seconds() -> int:
    default_interval = 900
    raw_value = os.getenv("COMFY_PREVIEW_PREFETCH_INTERVAL_SECONDS")
    if raw_value is None:
        return default_interval

    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        logger.warning(
            "preview_prefetch_interval_invalid",
            raw_value=raw_value,
            default_value=default_interval,
        )
        return default_interval

    if parsed <= 0:
        logger.warning(
            "preview_prefetch_interval_non_positive",
            raw_value=raw_value,
            default_value=default_interval,
        )
        return default_interval

    return parsed


def _resolve_preview_prefetch_batch_size() -> int:
    default_batch_size = 12
    raw_value = os.getenv("COMFY_PREVIEW_PREFETCH_BATCH_SIZE")
    if raw_value is None:
        return default_batch_size

    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        logger.warning(
            "preview_prefetch_batch_invalid",
            raw_value=raw_value,
            default_value=default_batch_size,
        )
        return default_batch_size

    if parsed <= 0:
        logger.warning(
            "preview_prefetch_batch_non_positive",
            raw_value=raw_value,
            default_value=default_batch_size,
        )
        return default_batch_size

    return parsed


def _resolve_preview_prefetch_max_candidates() -> int:
    default_candidates = 200
    raw_value = os.getenv("COMFY_PREVIEW_PREFETCH_MAX_CANDIDATES")
    if raw_value is None:
        return default_candidates

    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        logger.warning(
            "preview_prefetch_candidates_invalid",
            raw_value=raw_value,
            default_value=default_candidates,
        )
        return default_candidates

    if parsed <= 0:
        logger.warning(
            "preview_prefetch_candidates_non_positive",
            raw_value=raw_value,
            default_value=default_candidates,
        )
        return default_candidates

    return parsed


def _resolve_preview_prefetch_stale_after_seconds() -> int:
    default_stale_seconds = 604800  # 7 days
    raw_value = os.getenv("COMFY_PREVIEW_PREFETCH_STALE_AFTER_SECONDS")
    if raw_value is None:
        return default_stale_seconds

    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        logger.warning(
            "preview_prefetch_stale_after_invalid",
            raw_value=raw_value,
            default_value=default_stale_seconds,
        )
        return default_stale_seconds

    if parsed < 0:
        logger.warning(
            "preview_prefetch_stale_after_negative",
            raw_value=raw_value,
            default_value=default_stale_seconds,
        )
        return default_stale_seconds

    return parsed


def _resolve_preview_prefetch_jitter_seconds() -> float:
    default_jitter_seconds = 45.0
    raw_value = os.getenv("COMFY_PREVIEW_PREFETCH_JITTER_SECONDS")
    if raw_value is None:
        return default_jitter_seconds

    try:
        parsed = float(raw_value)
    except (TypeError, ValueError):
        logger.warning(
            "preview_prefetch_jitter_invalid",
            raw_value=raw_value,
            default_value=default_jitter_seconds,
        )
        return default_jitter_seconds

    if parsed < 0:
        logger.warning(
            "preview_prefetch_jitter_negative",
            raw_value=raw_value,
            default_value=default_jitter_seconds,
        )
        return default_jitter_seconds

    return parsed


def _resolve_preview_prefetch_item_delay_seconds() -> float:
    default_delay_seconds = 0.35
    raw_value = os.getenv("COMFY_PREVIEW_PREFETCH_ITEM_DELAY_SECONDS")
    if raw_value is None:
        return default_delay_seconds

    try:
        parsed = float(raw_value)
    except (TypeError, ValueError):
        logger.warning(
            "preview_prefetch_item_delay_invalid",
            raw_value=raw_value,
            default_value=default_delay_seconds,
        )
        return default_delay_seconds

    if parsed < 0:
        logger.warning(
            "preview_prefetch_item_delay_negative",
            raw_value=raw_value,
            default_value=default_delay_seconds,
        )
        return default_delay_seconds

    return parsed


PREVIEW_PREFETCH_ENABLED = _resolve_preview_prefetch_enabled()
PREVIEW_PREFETCH_INTERVAL_SECONDS = _resolve_preview_prefetch_interval_seconds()
PREVIEW_PREFETCH_BATCH_SIZE = _resolve_preview_prefetch_batch_size()
PREVIEW_PREFETCH_MAX_CANDIDATES = _resolve_preview_prefetch_max_candidates()
PREVIEW_PREFETCH_STALE_AFTER_SECONDS = _resolve_preview_prefetch_stale_after_seconds()
PREVIEW_PREFETCH_JITTER_SECONDS = _resolve_preview_prefetch_jitter_seconds()
PREVIEW_PREFETCH_ITEM_DELAY_SECONDS = _resolve_preview_prefetch_item_delay_seconds()


def get_cache_path(model_id: int, version_id: int = None, image_index: int = 0) -> str:
    """Get cache path for a model preview image."""
    os.makedirs(PREVIEW_CACHE_DIR, exist_ok=True)
    if version_id is not None:
        return os.path.join(PREVIEW_CACHE_DIR, f"{model_id}_{version_id}_{image_index}.img")
    return os.path.join(PREVIEW_CACHE_DIR, f"{model_id}_{image_index}.img")


def _get_cache_meta_path(cache_path: str) -> str:
    return f"{cache_path}.meta"


def _get_failure_marker_path(cache_path: str) -> str:
    return f"{cache_path}.fail"


def _get_not_found_marker_path(cache_path: str) -> str:
    return f"{cache_path}.404"


def _has_recent_failure(failure_marker_path: str, ttl_seconds: int) -> bool:
    if ttl_seconds <= 0 or not os.path.exists(failure_marker_path):
        return False

    try:
        with open(failure_marker_path, 'r', encoding='utf-8') as marker_file:
            failed_at = float(marker_file.read().strip())
    except Exception:
        return False

    return (time.time() - failed_at) < ttl_seconds


def _mark_failure(failure_marker_path: str) -> None:
    with open(failure_marker_path, 'w', encoding='utf-8') as marker_file:
        marker_file.write(str(time.time()))


def _clear_failure_marker(failure_marker_path: str) -> None:
    if os.path.exists(failure_marker_path):
        os.remove(failure_marker_path)


def _load_preview_from_cache(cache_path: str, cache_meta_path: str) -> tuple:
    if not os.path.exists(cache_path):
        return None, None

    with open(cache_path, 'rb') as image_file:
        cached_content = image_file.read()

    cached_content_type = "image/jpeg"
    if os.path.exists(cache_meta_path):
        try:
            with open(cache_meta_path, 'r', encoding='utf-8') as meta_file:
                cached_content_type = meta_file.read().strip() or cached_content_type
        except Exception:
            pass

    return cached_content, cached_content_type


def _save_preview_to_cache(cache_path: str, cache_meta_path: str, image_data: bytes, content_type: str) -> None:
    with open(cache_path, 'wb') as image_file:
        image_file.write(image_data)
    with open(cache_meta_path, 'w', encoding='utf-8') as meta_file:
        meta_file.write(content_type)


def _select_preview_url(model_data: Dict[str, Any], version_id: Optional[int], image_index: int) -> Optional[str]:
    model_versions = model_data.get('modelVersions', [])
    if not model_versions:
        return None

    target_version = None
    if version_id is not None:
        target_version = next((v for v in model_versions if v.get('id') == version_id), None)
    if not target_version:
        target_version = model_versions[0]

    raw_images = target_version.get('images', [])
    image_candidates = [
        img for img in raw_images
        if isinstance(img, dict)
        and img.get('url')
        and img.get('type', 'image').lower() != 'video'
    ]

    if not image_candidates:
        image_candidates = [
            img for img in raw_images
            if isinstance(img, dict) and img.get('url')
        ]

    if not image_candidates:
        return None

    safe_image_index = min(max(image_index, 0), len(image_candidates) - 1)
    return image_candidates[safe_image_index].get('url')


def _is_preview_cache_stale(
    model_id: int,
    version_id: Optional[int],
    image_index: int,
    stale_after_seconds: int,
) -> bool:
    cache_path = get_cache_path(model_id, version_id, image_index)
    if not os.path.exists(cache_path):
        return True

    if stale_after_seconds <= 0:
        return True

    try:
        return (time.time() - os.path.getmtime(cache_path)) >= stale_after_seconds
    except OSError:
        return True


def _list_civitai_model_ids_for_prefetch() -> List[int]:
    from sqlmodel import select
    from core.entities_v2 import ModelV2

    session = get_session_sync()
    try:
        rows = session.exec(
            select(ModelV2.civitai_model_id).where(
                ModelV2.civitai_model_id.is_not(None),
                ModelV2.source == "civitai",
            )
        ).all()
        unique_ids = {
            model_id
            for model_id in rows
            if isinstance(model_id, int) and model_id > 0
        }
        return list(unique_ids)
    finally:
        session.close()


def _select_stale_prefetch_candidates(
    model_ids: List[int],
    max_candidates: int,
    batch_size: int,
    stale_after_seconds: int,
) -> List[int]:
    if not model_ids or batch_size <= 0:
        return []

    shuffled_ids = model_ids[:]
    random.shuffle(shuffled_ids)

    if max_candidates > 0 and len(shuffled_ids) > max_candidates:
        shuffled_ids = shuffled_ids[:max_candidates]

    stale_candidates: List[int] = []
    for model_id in shuffled_ids:
        if _is_preview_cache_stale(
            model_id,
            version_id=None,
            image_index=0,
            stale_after_seconds=stale_after_seconds,
        ):
            stale_candidates.append(model_id)
        if len(stale_candidates) >= batch_size:
            break

    return stale_candidates


async def fetch_civitai_preview(
    model_id: int,
    version_id: int = None,
    image_index: int = 0,
    force_refresh: bool = False,
) -> tuple:
    """Fetch preview image from CivitAI API and cache it using non-blocking I/O."""
    cache_path = get_cache_path(model_id, version_id, image_index)
    cache_meta_path = _get_cache_meta_path(cache_path)
    failure_marker_path = _get_failure_marker_path(cache_path)
    not_found_marker_path = _get_not_found_marker_path(cache_path)

    has_recent_not_found = await asyncio.to_thread(
        _has_recent_failure,
        not_found_marker_path,
        PREVIEW_NOT_FOUND_TTL_SECONDS,
    )
    if has_recent_not_found:
        logger.debug(
            "civitai_preview_recent_not_found_skip",
            model_id=model_id,
            version_id=version_id,
            image_index=image_index,
            ttl_seconds=PREVIEW_NOT_FOUND_TTL_SECONDS,
        )
        return None, None, False

    has_recent_failure = await asyncio.to_thread(
        _has_recent_failure,
        failure_marker_path,
        PREVIEW_FAILURE_TTL_SECONDS,
    )
    if has_recent_failure:
        logger.debug(
            "civitai_preview_recent_failure_skip",
            model_id=model_id,
            version_id=version_id,
            image_index=image_index,
            ttl_seconds=PREVIEW_FAILURE_TTL_SECONDS,
        )
        return None, None, False

    if not force_refresh:
        cached_content, cached_content_type = await asyncio.to_thread(
            _load_preview_from_cache,
            cache_path,
            cache_meta_path,
        )
        if cached_content is not None:
            return cached_content, cached_content_type, True

    try:
        client = get_http_client()
        api_url = f"https://civitai.com/api/v1/models/{model_id}"
        response = await client.get(api_url, timeout=PREVIEW_METADATA_TIMEOUT_SECONDS)
        response.raise_for_status()
        model_data = response.json()

        image_url = _select_preview_url(model_data, version_id, image_index)
        if not image_url:
            return None, None, False

        img_response = await client.get(image_url, timeout=PREVIEW_IMAGE_TIMEOUT_SECONDS)
        img_response.raise_for_status()
        image_data = img_response.content
        content_type = img_response.headers.get('Content-Type', 'image/jpeg')

        await asyncio.to_thread(
            _save_preview_to_cache,
            cache_path,
            cache_meta_path,
            image_data,
            content_type,
        )
        await asyncio.to_thread(_clear_failure_marker, failure_marker_path)
        await asyncio.to_thread(_clear_failure_marker, not_found_marker_path)
        return image_data, content_type, False

    except httpx.HTTPStatusError as e:
        status_code = getattr(getattr(e, "response", None), "status_code", None)
        if status_code == 404:
            await asyncio.to_thread(_mark_failure, not_found_marker_path)
            await asyncio.to_thread(_clear_failure_marker, failure_marker_path)
            logger.info(
                "civitai_preview_model_not_found",
                model_id=model_id,
                version_id=version_id,
                image_index=image_index,
                error=str(e),
            )
            return None, None, False

        await asyncio.to_thread(_mark_failure, failure_marker_path)
        logger.warning(
            "civitai_preview_fetch_failed",
            model_id=model_id,
            version_id=version_id,
            image_index=image_index,
            error=str(e),
        )
        return None, None, False
    except Exception as e:
        await asyncio.to_thread(_mark_failure, failure_marker_path)
        logger.warning(
            "civitai_preview_fetch_failed",
            model_id=model_id,
            version_id=version_id,
            image_index=image_index,
            error=str(e),
        )
        return None, None, False


async def prefetch_stale_model_previews() -> Dict[str, Any]:
    """Warm stale model preview cache entries with jittered, sampled background fetches."""
    if not PREVIEW_PREFETCH_ENABLED:
        logger.debug("preview_prefetch_disabled")
        return {"status": "disabled"}

    jitter_seconds = 0.0
    if PREVIEW_PREFETCH_JITTER_SECONDS > 0:
        jitter_seconds = random.uniform(0.0, PREVIEW_PREFETCH_JITTER_SECONDS)
        if jitter_seconds > 0:
            await asyncio.sleep(jitter_seconds)

    model_ids = await asyncio.to_thread(_list_civitai_model_ids_for_prefetch)
    total_models = len(model_ids)
    if total_models == 0:
        logger.debug("preview_prefetch_no_models")
        return {"status": "no_models"}

    stale_candidates = await asyncio.to_thread(
        _select_stale_prefetch_candidates,
        model_ids,
        PREVIEW_PREFETCH_MAX_CANDIDATES,
        PREVIEW_PREFETCH_BATCH_SIZE,
        PREVIEW_PREFETCH_STALE_AFTER_SECONDS,
    )

    if not stale_candidates:
        logger.debug("preview_prefetch_no_stale", total_models=total_models)
        return {
            "status": "no_stale",
            "total_models": total_models,
        }

    warmed = 0
    misses = 0
    for index, model_id in enumerate(stale_candidates):
        image_data, _content_type, _cache_hit = await fetch_civitai_preview(
            model_id,
            version_id=None,
            image_index=0,
            force_refresh=True,
        )
        if image_data:
            warmed += 1
        else:
            misses += 1

        if PREVIEW_PREFETCH_ITEM_DELAY_SECONDS > 0 and index < len(stale_candidates) - 1:
            await asyncio.sleep(random.uniform(0.0, PREVIEW_PREFETCH_ITEM_DELAY_SECONDS))

    logger.info(
        "preview_prefetch_cycle_complete",
        total_models=total_models,
        selected=len(stale_candidates),
        warmed=warmed,
        misses=misses,
        jitter_seconds=round(jitter_seconds, 3),
    )
    return {
        "status": "ok",
        "total_models": total_models,
        "selected": len(stale_candidates),
        "warmed": warmed,
        "misses": misses,
    }


@router.get("/preview/{model_id}")
async def get_model_preview_image(model_id: int, version_id: int = None, image_index: int = 0):
    """
    Fetch and cache model preview image from CivitAI.
    Automatically filters out videos and returns the first image.
    """
    if image_index < 0:
        raise HTTPException(status_code=400, detail="image_index must be >= 0")

    dedup_key = make_key(
        "civitai_preview",
        model_id,
        version_id if version_id is not None else "default",
        image_index,
    )
    image_data, content_type, cache_hit = await deduplicated(
        dedup_key,
        lambda: fetch_civitai_preview(model_id, version_id, image_index),
    )
    
    if not image_data:
        raise HTTPException(status_code=404, detail="Preview image not found")
    
    return Response(
        content=image_data,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=604800, stale-while-revalidate=86400",
            "X-Cache-Source": "civitai-proxy",
            "X-Cache-Status": "hit" if cache_hit else "miss",
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
    from sqlmodel import select
    from core.entities_v2 import ModelFile, ModelVersion, ModelV2

    service = get_model_service(session)
    file_id_by_key = {}
    stmt = select(ModelFile, ModelVersion, ModelV2).join(
        ModelVersion, ModelFile.version_id == ModelVersion.id
    ).join(
        ModelV2, ModelVersion.model_id == ModelV2.id
    )
    for file, _version, model in session.exec(stmt).all():
        file_id_by_key[(model.directory, file.storage_filename)] = file.id
    
    updated = 0
    failed = 0
    
    for item in request.models:
        try:
            file_id = file_id_by_key.get((item.directory, item.model_name))
            if file_id is None:
                failed += 1
                continue

            if item.status == "completed":
                await service.update_provider_file_status(
                    file_id=file_id,
                    provider_name=request.provider_id,
                    status="ready",
                    storage_path=f"models/{item.directory}/{item.model_name}",
                    size_bytes=item.size_bytes,
                )
                updated += 1
            elif item.status == "failed":
                await service.update_provider_file_status(
                    file_id=file_id,
                    provider_name=request.provider_id,
                    status="failed",
                    storage_path=f"models/{item.directory}/{item.model_name}",
                )
                updated += 1
            elif item.status == "pending":
                await service.update_provider_file_status(
                    file_id=file_id,
                    provider_name=request.provider_id,
                    status="pending",
                    storage_path=f"models/{item.directory}/{item.model_name}",
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
    from core.entities import Provider
    from sqlmodel import select
    from api.provider_runtime import resolve_provider_runtime

    service = get_model_service(session)

    providers = session.exec(
        select(Provider).where(Provider.enabled == True)
    ).all()

    all_models = await service.list_models(include_versions=True)
    all_files_by_path = {}
    for model in all_models:
        for version in model.get("versions", []):
            file = version.get("file")
            if not file:
                continue
            storage_path = f"models/{model['directory']}/{file['filename']}"
            all_files_by_path[storage_path] = file["id"]
    
    results = {
        "providers_checked": 0,
        "models_updated": 0,
        "errors": []
    }
    
    for provider in providers:
        runtime = resolve_provider_runtime(provider)
        if runtime.mode != "container_http":
            continue

        worker_url = runtime.worker_url
        
        results["providers_checked"] += 1
        
        # Query each directory from the worker
        directories = ["checkpoints", "loras", "controlnet", "embeddings", "vae", "upscale_models", "clip", "unet"]
        
        async with aiohttp.ClientSession() as http_session:
            for directory in directories:
                try:
                    async with http_session.post(
                        f"{worker_url}/list-models",
                        json={"directory": f"models/{directory}"},
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
                        if response.status != 200:
                            continue
                        
                        data = await response.json()
                        for provider_file in data.get("files", []):
                            storage_path = provider_file.get("path") or provider_file.get("storage_path")
                            if not storage_path:
                                name = provider_file.get("name")
                                if not name:
                                    continue
                                storage_path = f"models/{directory}/{name}"

                            file_id = all_files_by_path.get(storage_path)
                            if not file_id:
                                continue

                            try:
                                await service.update_provider_file_status(
                                    file_id=file_id,
                                    provider_name=provider.id,
                                    status="ready",
                                    storage_path=storage_path,
                                    size_bytes=provider_file.get("size"),
                                )
                                results["models_updated"] += 1
                            except Exception as e:
                                results["errors"].append(f"{storage_path}: {str(e)}")
                                    
                except Exception as e:
                    results["errors"].append(f"{provider.id}/{directory}: {str(e)}")
    
    return results
