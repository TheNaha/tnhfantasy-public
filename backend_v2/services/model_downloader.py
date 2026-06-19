from typing import Dict, Any, List, Optional
import os

from sqlmodel import Session

from core.entities import Provider
from core.entities_v2 import (
    ModelV2, ModelVersion, ModelFile, ProviderVersionStatus,
    FLUX_DEFAULT_COMPONENTS, AURAFLOW_DEFAULT_COMPONENTS, is_unet_only_model
)
from core.exceptions import NotFoundError
from infrastructure.http_client import get_http_client
from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2
from infrastructure.logging import model_logger

logger = model_logger()


class ModelDownloader:
    """
    Handles model downloads, status updates, custom model registration,
    and dependency tracking for the model service.
    """

    def __init__(self, session: Session, repo: Optional[ModelRepositoryV2] = None):
        self.session = session
        self.repo = repo or ModelRepositoryV2(session)

    async def trigger_download_to_providers(
        self, 
        model_id: int, 
        version_ids: List[int] = None,
        provider_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Trigger immediate download of model files to all enabled providers.
        Called after adding a model to the database.
        """
        model = self.repo.get_model(model_id)
        if not model:
            return {"status": "error", "message": f"Model {model_id} not found"}
        
        # Get enabled providers
        from sqlmodel import select
        provider_stmt = select(Provider).where(Provider.enabled == True)
        if provider_ids:
            provider_stmt = provider_stmt.where(Provider.id.in_(provider_ids))
        providers = list(self.session.exec(provider_stmt).all())
        
        if not providers:
            return {"status": "skipped", "message": "No enabled providers"}
        
        results = {"triggered": 0, "providers": []}
        
        # Get versions to download
        versions = self.repo.get_versions_for_model(model_id)
        http_client = get_http_client()
        for version in versions:
            if version_ids is not None and version.id not in version_ids:
                continue
            if not version.is_enabled:
                continue
                
            file = self.repo.get_primary_file_for_version(version.id)
            if not file or not file.download_url:
                continue
            
            storage_path = f"models/{model.directory}/{file.storage_filename}"
            
            token = None
            if file.download_url:
                if "huggingface.co" in file.download_url:
                    token = os.getenv("HF_TOKEN", "")
                elif "civitai.com" in file.download_url:
                    token = os.getenv("CIVITAI_TOKEN", "")
            
            for provider in providers:
                container_name = f"comfy-provider-{provider.id}"
                worker_url = f"http://{container_name}:8000"
                
                try:
                    payload = {
                        "url": file.download_url,
                        "path": storage_path,
                        "token": token
                    }
                    response = await http_client.post(
                        f"{worker_url}/download-model",
                        json=payload,
                        timeout=10.0,
                    )
                    if response.status_code == 200:
                        results["triggered"] += 1
                        results["providers"].append({
                            "provider_id": provider.id,
                            "file_id": file.id,
                            "status": "queued"
                        })
                        self.repo.update_provider_status(
                            file_id=file.id,
                            provider_name=provider.id,
                            status="downloading",
                            storage_path=storage_path
                        )
                except Exception as e:
                    logger.warning("provider_download_trigger_failed", provider_id=provider.id, error=str(e))
                    results["providers"].append({
                        "provider_id": provider.id,
                        "file_id": file.id,
                        "status": "error",
                        "error": str(e)
                    })
        
        return results

    async def trigger_delete_from_providers(self, model_id: int) -> Dict[str, Any]:
        """
        Trigger immediate deletion of model files from all providers.
        Called BEFORE deleting model from database.
        """
        model = self.repo.get_model(model_id)
        if not model:
            return {"status": "error", "message": f"Model {model_id} not found"}
        
        # Get all providers (even disabled - clean up everywhere)
        from core.entities import Provider
        from sqlmodel import select
        providers = list(self.session.exec(select(Provider)).all())
        
        results = {"deleted": 0, "providers": []}
        
        # Get all files for this model's versions
        versions = self.repo.get_versions_for_model(model_id)
        http_client = get_http_client()
        for version in versions:
            file = self.repo.get_primary_file_for_version(version.id)
            if not file:
                continue
            
            storage_path = f"models/{model.directory}/{file.storage_filename}"
            
            for provider in providers:
                from api.provider_runtime import resolve_provider_runtime
                runtime = resolve_provider_runtime(provider)
                
                if not runtime.worker_url:
                    continue
                
                worker_url = runtime.worker_url
                
                try:
                    import urllib.parse
                    encoded_path = urllib.parse.quote(storage_path, safe='')
                    response = await http_client.delete(
                        f"{worker_url}/delete-file/{encoded_path}",
                        timeout=10.0,
                    )
                    if response.status_code == 200:
                        results["deleted"] += 1
                        results["providers"].append({
                            "provider_id": provider.id,
                            "file_id": file.id,
                            "path": storage_path,
                            "status": "deleted"
                        })
                    else:
                        results["providers"].append({
                            "provider_id": provider.id,
                            "file_id": file.id,
                            "path": storage_path,
                            "status": "not_found"
                        })
                except Exception as e:
                    logger.warning("provider_delete_failed", provider_id=provider.id, error=str(e))
                    results["providers"].append({
                        "provider_id": provider.id,
                        "file_id": file.id,
                        "status": "error",
                        "error": str(e)
                    })
        
        return results

    async def add_custom_model(
        self,
        *,
        name: str,
        directory: str,
        download_url: str,
        provider_ids: Optional[List[str]] = None,
        model_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a V2 model entry for a direct download URL and trigger sync."""
        filename = name.split("/")[-1].strip()
        if not filename:
            raise ValueError("Model filename is required")

        existing_file = self.repo.get_file_by_storage_path(directory, filename)
        if existing_file:
            version = self.session.get(ModelVersion, existing_file.version_id)
            existing_model = self.repo.get_model(version.model_id) if version else None
            if not existing_model:
                raise NotFoundError("Model", filename)

            await self.trigger_download_to_providers(existing_model.id, provider_ids=provider_ids)
            return self.repo.model_to_dict(existing_model)

        resolved_type = model_type or directory.replace("models/", "").replace("_", " ").title()

        model = ModelV2(
            name=filename,
            type=resolved_type,
            directory=directory.replace("models/", ""),
            description=f"Direct import for {filename}",
            source="custom",
            source_url=download_url,
            nsfw=False,
            nsfw_level=1,
        )
        self.session.add(model)
        self.session.flush()

        version = ModelVersion(
            model_id=model.id,
            name="v1.0",
            base_model="Custom",
            base_model_type="Standard",
            description=f"Direct import for {filename}",
            is_enabled=True,
            is_default=True,
        )
        self.session.add(version)
        self.session.flush()

        file = ModelFile(
            version_id=version.id,
            original_filename=filename,
            storage_filename=filename,
            size_kb=0,
            format=filename.split(".")[-1] if "." in filename else "Unknown",
            download_url=download_url,
            is_primary=True,
            file_type="Model",
        )
        self.session.add(file)
        self.session.commit()
        self.session.refresh(model)

        await self.trigger_download_to_providers(model.id, provider_ids=provider_ids)
        return self.repo.model_to_dict(model)

    async def check_and_trigger_dependencies(
        self, 
        civitai_data: Optional[Dict[str, Any]] = None,
        base_model_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Check for and trigger auto-download of dependencies (CLIP/VAE) for UNET models.
        """
        is_flux = False
        is_auraflow = False
        
        # Determine model type
        if base_model_name:
            if not is_unet_only_model(base_model_name):
                return {"triggered": False, "reason": "Not a UNET model"}
                
            base_lower = base_model_name.lower()
            if base_lower.startswith("flux"):
                is_flux = True
            elif base_lower.startswith("aura"):
                is_auraflow = True
        
        elif civitai_data:
            # Check if any version is a UNET-only model
            versions = civitai_data.get("modelVersions", [])
            for v in versions:
                base_model = v.get("baseModel", "").lower()
                if is_unet_only_model(base_model):
                    if base_model.startswith("flux"):
                        is_flux = True
                    elif base_model.startswith("aura"):
                        is_auraflow = True
                    break
                    
        if not (is_flux or is_auraflow):
            return {"triggered": False, "reason": "Not a supported UNET model"}
        
        # Select appropriate components
        model_type = "Unknown"
        components = {}
        
        if is_flux:
            components = FLUX_DEFAULT_COMPONENTS
            model_type = "Flux"
        elif is_auraflow:
            components = AURAFLOW_DEFAULT_COMPONENTS
            model_type = "AuraFlow"
        
        logger.info("dependency_model_detected", model_type=model_type)
        
        # Create database entries for each dependency and trigger downloads
        models_to_download = []
        
        for category, files in components.items():
            for file_info in files:
                filename = file_info["name"]
                url = file_info["url"]
                directory = file_info["directory"]
                size_mb = file_info.get("size_mb", 0)
                description = file_info.get("description", "")
                
                # Determine model type for database
                if category == "clip":
                    db_type = "CLIP"
                    display_name = description or f"CLIP Encoder - {filename}"
                elif category == "vae":
                    db_type = "VAE"
                    display_name = description or f"VAE - {filename}"
                else:
                    db_type = "Other"
                    display_name = filename
                
                # Create the database entry for this dependency
                model = self.repo.create_system_dependency(
                    name=display_name,
                    model_type=db_type,
                    directory=directory,
                    filename=filename,
                    download_url=url,
                    size_mb=size_mb,
                    description=description,
                    base_model=model_type
                )
                
                if model:
                    # Newly created
                    models_to_download.append(model)
                else:
                    # Already exists - check if we should re-sync
                    # Look up the existing model by filename
                    existing_file = self.repo.get_file_by_storage_path(directory, filename)
                    if existing_file:
                        # Get the model from the file's version
                        from sqlmodel import select
                        version = self.session.exec(
                            select(ModelVersion).where(ModelVersion.id == existing_file.version_id)
                        ).first()
                        if version:
                            existing_model = self.repo.get_model(version.model_id)
                            if existing_model:
                                models_to_download.append(existing_model)
                                logger.debug("dependency_resync", filename=filename)
        
        # Now trigger downloads for all models (new and existing that need re-sync)
        for model in models_to_download:
            logger.info("dependency_download_triggered", model_name=model.name)
            await self.trigger_download_to_providers(model.id)
        
        logger.info("dependency_downloads_complete", count=len(models_to_download), model_type=model_type)
        
        return {
            "triggered": True,
            "model_type": model_type,
            "count": len(models_to_download),
            "downloads": [m.name for m in models_to_download]
        }

    async def update_provider_file_status(
        self,
        file_id: int,
        provider_name: str,
        status: str,
        storage_path: Optional[str] = None,
        size_bytes: Optional[int] = None,
        error_message: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update provider status for a file."""
        status_obj = self.repo.update_provider_status(
            file_id=file_id,
            provider_name=provider_name,
            status=status,
            storage_path=storage_path,
            size_bytes=size_bytes,
            error_message=error_message
        )
        provider_key = status_obj.provider_id or status_obj.provider_name or provider_name

        # Provider readiness changed; clear model-aware routing memoization.
        from services.load_balancer import LoadBalancer
        LoadBalancer.invalidate_model_availability_cache(provider_id=provider_key)

        return {
            "file_id": status_obj.file_id,
            "provider_id": provider_key,
            "provider_name": provider_key,
            "status": status_obj.status,
            "storage_path": status_obj.storage_path,
            "size_bytes": status_obj.size_bytes,
            "downloaded_at": status_obj.downloaded_at.isoformat() if status_obj.downloaded_at else None
        }

    async def get_model_provider_statuses(self, model_id: int) -> Dict[str, Dict[str, Any]]:
        """Get all provider statuses for a model."""
        return self.repo.get_provider_statuses_for_model(model_id)
