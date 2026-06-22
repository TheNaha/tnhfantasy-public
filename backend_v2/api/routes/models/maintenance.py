from .schemas import *
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from api.deps import get_session, get_model_service_v2
from core.exceptions import NotFoundError, ValidationError, ComfyError
from api.routes.websocket import broadcast_to_all
from infrastructure.database import get_session_context
from infrastructure.logging import model_logger

logger = model_logger()

router = APIRouter()


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
    from core.entities import ModelV2, ModelVersion, ModelTag
    
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
    from core.entities import ModelVersion
    from sqlmodel import select
    
    service = get_model_service_v2(session)
    
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
    from core.entities import ModelV2, ModelTag
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
    stats = civitai_data.get("stats") or {}
    creator = civitai_data.get("creator") or {}
    
    model.name = civitai_data.get("name") or model.name
    model.description = civitai_data.get("description")
    model.nsfw = civitai_data.get("nsfw", model.nsfw)
    
    # nsfwLevel might be absent or None
    new_nsfw_level = civitai_data.get("nsfwLevel")
    if new_nsfw_level is not None:
        model.nsfw_level = new_nsfw_level
        
    model.creator_username = creator.get("username")
    model.creator_image = creator.get("image")
    model.stats_downloads = stats.get("downloadCount") or 0
    model.stats_thumbs_up = stats.get("thumbsUpCount") or 0
    model.stats_thumbs_down = stats.get("thumbsDownCount") or 0
    model.stats_comments = stats.get("commentCount") or 0
    
    # Update tags - delete old and add new
    session.exec(delete(ModelTag).where(ModelTag.model_id == model.id))
    for tag in civitai_data.get("tags", []):
        session.add(ModelTag(model_id=model.id, tag=tag))
    
    session.add(model)
    session.commit()
    
    # Get service for dict conversion
    service = get_model_service_v2(session)
    
    return {
        "status": "success",
        "message": f"Resynced model '{model.name}' from CivitAI",
        "model": service.repo.model_to_dict(model)
    }

@router.post("/resync-all")
async def resync_all_models_from_civitai(session: Session = Depends(get_session)):
    """
    Re-sync all non-autodiscovered models from CivitAI.
    """
    from core.entities import ModelV2, ModelTag
    from sqlmodel import select, delete
    import asyncio
    from infrastructure.http_client import get_http_client
    
    # Get all models that are NOT auto-discovered and HAVE a civitai ID
    models = session.exec(
        select(ModelV2)
        .where(ModelV2.civitai_model_id != None)
        .where(ModelV2.description.not_like("%Auto-discovered%"))
    ).all()
    
    if not models:
        return {"status": "no_models", "count": 0}
        
    async def _background_resync():
        async with get_session_context() as bg_session:
            results = {"success": 0, "failed": 0, "errors": []}
            total = len(models)
            
            await broadcast_to_all("RESYNC_PROGRESS", {
                "status": "started",
                "processed": 0,
                "total": total,
                "results": results,
                "current_model": "Starting..."
            })
            
            http_client = get_http_client()
            
            for i, model in enumerate(models):
                await broadcast_to_all("RESYNC_PROGRESS", {
                    "status": "processing",
                    "processed": i,
                    "total": total,
                    "results": results,
                    "current_model": model.name
                })
                
                # Fetch fresh data from CivitAI
                url = f"https://civitai.com/api/v1/models/{model.civitai_model_id}"
                try:
                    # we must re-fetch model within the background session!
                    bg_model = bg_session.get(ModelV2, model.id)
                    if not bg_model:
                        continue
                        
                    response = await http_client.get(url, timeout=30.0)
                    if response.status_code != 200:
                        raise ComfyError(f"CivitAI API error: {response.status_code}")
                    civitai_data = response.json()
                    
                    stats = civitai_data.get("stats") or {}
                    creator = civitai_data.get("creator") or {}
                    
                    bg_model.name = civitai_data.get("name") or bg_model.name
                    bg_model.description = civitai_data.get("description", bg_model.description)
                    bg_model.nsfw = civitai_data.get("nsfw", bg_model.nsfw)
                    
                    new_nsfw_level = civitai_data.get("nsfwLevel")
                    if new_nsfw_level is not None:
                        bg_model.nsfw_level = new_nsfw_level
                        
                    bg_model.creator_username = creator.get("username")
                    bg_model.creator_image = creator.get("image")
                    bg_model.stats_downloads = stats.get("downloadCount") or 0
                    bg_model.stats_thumbs_up = stats.get("thumbsUpCount") or 0
                    bg_model.stats_thumbs_down = stats.get("thumbsDownCount") or 0
                    bg_model.stats_comments = stats.get("commentCount") or 0
                    
                    # Update tags
                    bg_session.exec(delete(ModelTag).where(ModelTag.model_id == bg_model.id))
                    for tag in civitai_data.get("tags", []):
                        bg_session.add(ModelTag(model_id=bg_model.id, tag=tag))
                        
                    bg_session.add(bg_model)
                    bg_session.commit()
                    results["success"] += 1
                except Exception as exc:
                    results["failed"] += 1
                    results["errors"].append({"model_id": str(model.id), "error": str(exc)})
            
            await broadcast_to_all("RESYNC_PROGRESS", {
                "status": "completed",
                "processed": total,
                "total": total,
                "results": results,
                "current_model": "Done"
            })
            
    asyncio.create_task(_background_resync())
    return {"status": "processing", "count": len(models)}


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
    from services.provider_runtime import resolve_provider_runtime
    from infrastructure.http_client import get_http_client
    from services.model_reconciliation import _DIRECTORY_TO_MODEL_TYPE

    service = get_model_service_v2(session)

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
