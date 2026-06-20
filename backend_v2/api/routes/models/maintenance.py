from .schemas import *
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends

from sqlmodel import Session
from pydantic import BaseModel

from api.deps import get_session, get_session_sync
from services.model_service import ModelServiceV2
from core.exceptions import NotFoundError, ValidationError, ComfyError
from infrastructure.logging import model_logger

logger = model_logger()

router = APIRouter()

def get_model_service(session: Session) -> ModelServiceV2:
    return ModelServiceV2(session)


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

    # Get base model from default version
    versions = model.get("versions", [])
    if not versions:
        raise ValidationError("Model has no versions")
        
    default_v = next((v for v in versions if v.get("is_default")), versions[0])
    base_model = default_v.get("base_model")
    
    if not base_model:
        raise ValidationError("Model has no base model information")
    
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
    from core.entities_v2 import ModelV2, ModelTag
    from sqlmodel import select, delete
    from infrastructure.http_client import get_http_client
    
    # Get the model
    model = session.get(ModelV2, model_id)
    if not model:
        raise NotFoundError("Resource", "Model not found")
    
    if not model.civitai_model_id:
        raise ValidationError("Model has no CivitAI ID - cannot resync")
    
    # Fetch fresh data from CivitAI
    url = f"https://civitai.com/api/v1/models/{model.civitai_model_id}"
    try:
        http_client = get_http_client()
        response = await http_client.get(url, timeout=30.0)
        if response.status_code != 200:
            raise ComfyError(f"CivitAI API error: {response.status_code}")
        civitai_data = response.json()
    except Exception as e:
        raise ComfyError(f"Failed to fetch from CivitAI: {str(e)}")
    
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
    from core.entities import Provider
    from sqlmodel import select
    from api.provider_runtime import resolve_provider_runtime
    from infrastructure.http_client import get_http_client
    from services.model_reconciliation import _DIRECTORY_TO_MODEL_TYPE

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
    
    http_client = get_http_client()
    
    MODEL_DIRECTORIES = [
        f"models/{d}" for d in _DIRECTORY_TO_MODEL_TYPE
    ]
    
    import asyncio
    
    tasks = []

    async def check_directory(provider_id, directory, worker_url):
        try:
            response = await http_client.post(
                f"{worker_url}/list-models",
                json={"directory": directory},
                timeout=60.0
            )
            if response.status_code != 200:
                return []
            
            data = response.json()
            updates = []
            for provider_file in data.get("files", []):
                storage_path = provider_file.get("path") or provider_file.get("storage_path")
                if not storage_path:
                    name = provider_file.get("name")
                    if not name:
                        continue
                    storage_path = f"{directory}/{name}"

                file_id = all_files_by_path.get(storage_path)
                if file_id:
                    updates.append((provider_id, file_id))
            return updates
        except Exception as e:
            results["errors"].append(f"Failed to query {provider_id} at {directory}: {str(e)}")
            return []
    
    for provider in providers:
        runtime = resolve_provider_runtime(provider)
        if runtime.mode not in ("container_http", "discovery"):
            continue

        worker_url = runtime.worker_url
        
        results["providers_checked"] += 1
        
        for directory in MODEL_DIRECTORIES:
            tasks.append(check_directory(provider.id, directory, worker_url))
            
    all_updates = await asyncio.gather(*tasks)
    
    for directory_updates in all_updates:
        for provider_id, file_id in directory_updates:
            try:
                await service.update_provider_file_status(
                    provider_id=provider_id,
                    file_id=file_id,
                    status="downloaded"
                )
                results["models_updated"] += 1
            except Exception as e:
                results["errors"].append(str(e))
    
    return results
