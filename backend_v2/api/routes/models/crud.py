
from fastapi import APIRouter, Depends

from api.deps import (
    get_model_repo_v2,
    get_model_service_v2,
)
from core.exceptions import NotFoundError, ValidationError
from infrastructure.logging import model_logger
from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2
from services.model_service import ModelServiceV2

from .schemas import *  # noqa: F401, F403, F405

logger = model_logger()

router = APIRouter()


# ============================================================================
# MODEL ENDPOINTS
# ============================================================================

@router.get("/")
async def list_models(service: ModelServiceV2 = Depends(get_model_service_v2)):
    """List all models grouped by directory."""
    return {"models": await service.get_models_grouped()}


@router.get("/all")
async def list_all_models(service: ModelServiceV2 = Depends(get_model_service_v2)):
    """List all models as flat list."""
    return await service.list_models()


@router.get("/all-storage-paths")
def get_all_storage_paths(repo: ModelRepositoryV2 = Depends(get_model_repo_v2)):
    """
    Get all expected storage paths from the V2 database.
    Used by worker to determine what files should exist vs what to delete.
    Returns paths like: models/checkpoints/model_v1_12345.safetensors
    """
    paths = repo.get_all_storage_paths()
    
    return {"paths": paths, "count": len(paths)}


@router.get("/check-installed/{civitai_model_id}")
def check_installed_versions(
    civitai_model_id: int,
    repo: ModelRepositoryV2 = Depends(get_model_repo_v2)
):
    """
    Check if a CivitAI model and its versions are already installed.

    Returns:
    - model_installed: bool - whether any version of this model is installed
    - installed_versions: list of installed civitai_version_ids
    - model_id: local model ID if installed

    Use this before showing the import dialog to mark installed versions.

    `civitai_model_id` is declared `int`, not `str`, so pydantic rejects a
    non-numeric path segment with a 422 instead of letting a bare string reach
    `ModelV2.civitai_model_id == <str>`, which is a comparison against an
    integer column and therefore an unmapped `InvalidTextRepresentation` 500.
    """
    # Check if model exists
    model = repo.get_model_by_civitai_id(civitai_model_id)
    
    if not model:
        return {
            "model_installed": False,
            "installed_versions": [],
            "model_id": None
        }
    
    # Get installed versions for this model
    versions = repo.get_versions_for_model(model.id)
    
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
    repo: ModelRepositoryV2 = Depends(get_model_repo_v2),
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
    requested_ids = [mid for mid in request.civitai_model_ids if isinstance(mid, int)]
    if not requested_ids:
        return {"models": {}}

    unique_ids = sorted(set(requested_ids))
    models = repo.get_models_by_civitai_ids(unique_ids)

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
    versions = repo.get_versions_for_models(model_ids)

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
    repo: ModelRepositoryV2 = Depends(get_model_repo_v2),
    service: ModelServiceV2 = Depends(get_model_service_v2)
):
    """
    Add a model with selected versions.
    
    The civitai_data should be the full CivitAI API response.
    selected_versions should be: [{"version_id": 12345, "is_default": true}, ...]
    
    Prevents duplicate imports:
    - If model+version already exists, that version is skipped
    - New versions of existing models CAN be added
    """
    # Extract version IDs from request
    selected_version_ids = [v["version_id"] for v in request.selected_versions]
    
    if not selected_version_ids:
        raise ValidationError("At least one version must be selected")
    
    available_version_ids = {
        version.get("id")
        for version in (request.civitai_data.get("modelVersions") or [])
        if version.get("id") is not None
    }
    unknown_version_ids = [
        version_id for version_id in selected_version_ids
        if version_id not in available_version_ids
    ]
    if unknown_version_ids:
        raise ValidationError(
            f"Selected versions are not present in the model response: {unknown_version_ids}"
        )

    # Check for already installed versions
    already_installed = []
    new_version_ids = []
    
    for version_id in selected_version_ids:
        existing = repo.get_version_by_civitai_id(version_id)
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
    service: ModelServiceV2 = Depends(get_model_service_v2)
):
    """List models in a specific directory."""
    return await service.list_models_by_directory(directory)


@router.get("/search")
async def search_models(
    q: str = "",
    type: str | None = None,
    base_model: str | None = None,
    service: ModelServiceV2 = Depends(get_model_service_v2)
):
    """Search models by name, type, or base model."""
    return await service.search_models(query=q, model_type=type, base_model=base_model)


@router.get("/search/tag/{tag}")
async def search_by_tag(
    tag: str,
    service: ModelServiceV2 = Depends(get_model_service_v2)
):
    """Search models by tag."""
    return await service.search_by_tag(tag)


@router.get("/{model_id}")
async def get_model(
    model_id: str,
    service: ModelServiceV2 = Depends(get_model_service_v2)
):
    """Get model with versions, files, and images."""
    return await service.get_model(model_id)


@router.delete("/{model_id}")
async def delete_model(
    model_id: str,
    service: ModelServiceV2 = Depends(get_model_service_v2)
):
    """Delete a model and all related data."""
    await service.delete_model(model_id)
    return {"status": "success"}


# ============================================================================
# VERSION ENDPOINTS
# ============================================================================

@router.get("/{model_id}/versions")
async def get_versions(
    model_id: str,
    service: ModelServiceV2 = Depends(get_model_service_v2)
):
    """Get all versions for a model."""
    return await service.get_versions(model_id)


@router.put("/{model_id}/default-version")
async def set_default_version_modern(
    model_id: str,
    request: SetDefaultVersionRequest,
    service: ModelServiceV2 = Depends(get_model_service_v2)
):
    """Set the default version for a model."""
    success = await service.set_default_version(model_id, request.version_id)
    if success:
        return {"status": "success"}
    raise ValidationError("Failed to set default version")


@router.put("/versions/{version_id}/toggle")
async def toggle_version_enabled(
    version_id: str,
    service: ModelServiceV2 = Depends(get_model_service_v2)
):
    """Toggle whether a version is enabled."""
    result = await service.toggle_version_enabled(version_id)
    if result:
        return result
    raise NotFoundError("Resource", f"Version {version_id} not found")


@router.get("/{model_id}/generation-info")
async def get_generation_info(
    model_id: str,
    version_id: int | None = None,
    service: ModelServiceV2 = Depends(get_model_service_v2)
):
    """
    Get model/version info needed for generation.
    Returns storage path and other generation params.
    """
    return await service.get_version_for_generation(model_id, version_id)


