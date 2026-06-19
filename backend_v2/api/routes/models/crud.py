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
# MODEL ENDPOINTS
# ============================================================================

@router.get("/")
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

@router.post("/")
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
        raise ValidationError("At least one version must be selected")
    
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
        raise ValidationError(f"All selected versions are already installed: {already_installed}")
    
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
    raise ValidationError("Failed to set default version")


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
    raise NotFoundError("Resource", f"Version {version_id} not found")


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
    return await service.get_version_for_generation(model_id, version_id)


