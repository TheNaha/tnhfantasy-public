# Model Service V2 - Version-aware business logic for normalized model schema
#
# Operates on the V2 schema (models_v2, model_versions, model_files,
# provider_version_status) which stores full CivitAI metadata with proper
# relational structure.
#
# KEY RESPONSIBILITIES:
#   - Import models from CivitAI with selected versions and files
#   - Track per-provider, per-file download status
#   - Provide reconciliation data (what each provider needs to download/delete)
#   - Support version switching (set_default_version)
#   - External search (proxy CivitAI/HuggingFace API calls)
from typing import Dict, Any, List, Optional
from datetime import datetime

from sqlmodel import Session

from core.entities_v2 import (
    ModelV2, ModelVersion, ModelFile, ProviderVersionStatus,
    get_directory_from_type, is_unet_only_model, FLUX_DEFAULT_COMPONENTS
)
from core.exceptions import NotFoundError
from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2
from infrastructure.logging import model_logger

logger = model_logger()


class ModelServiceV2:
    """
    Version-aware model management service.
    Handles:
    - Adding models with selected versions
    - Version selection and default setting
    - Provider status tracking per-file
    - Reconciliation queries
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.repo = ModelRepositoryV2(session)
    
    # =========================================================================
    # MODEL OPERATIONS
    # =========================================================================
    
    async def add_model_from_civitai(
        self,
        civitai_data: Dict[str, Any],
        selected_version_ids: List[int]
    ) -> Dict[str, Any]:
        """
        Add a model from CivitAI with selected versions.
        
        Args:
            civitai_data: Full CivitAI API response
            selected_version_ids: List of CivitAI version IDs to include
            
        Returns:
            Created model as dict
        """
        # Check if model already exists
        civitai_id = civitai_data.get("id")
        existing = self.repo.get_model_by_civitai_id(civitai_id)
        if existing:
            # Add new versions to existing model
            added_versions = self.repo.add_versions_to_model(
                model=existing,
                civitai_data=civitai_data,
                selected_version_ids=selected_version_ids
            )
            
            if added_versions:
                # Trigger download for only the new versions (not all versions)
                new_version_ids = [v.id for v in added_versions]
                await self.trigger_download_to_providers(existing.id, version_ids=new_version_ids)
            
            result = self.repo.model_to_dict(existing)
            result["added_versions"] = len(added_versions)
            return result
        
        model = self.repo.create_model_with_versions(
            civitai_data=civitai_data,
            selected_version_ids=selected_version_ids
        )
        
        # Trigger immediate download to all enabled providers
        await self.trigger_download_to_providers(model.id)
        
        # Auto-download Flux dependencies if this is a Flux model
        await self.check_and_trigger_dependencies(civitai_data=civitai_data)
        
        return self.repo.model_to_dict(model)
    
    async def get_model(self, model_id: int) -> Dict[str, Any]:
        """Get a model by ID."""
        model = self.repo.get_model(model_id)
        if not model:
            raise NotFoundError("Model", str(model_id))
        return self.repo.model_to_dict(model)
    
    async def list_models(self) -> List[Dict[str, Any]]:
        """List all models."""
        models = self.repo.get_all_models()
        return [self.repo.model_to_dict(m, include_versions=False) for m in models]
    
    async def list_models_by_directory(self, directory: str) -> List[Dict[str, Any]]:
        """List models in a specific directory."""
        models = self.repo.get_models_by_directory(directory)
        return [self.repo.model_to_dict(m, include_versions=True) for m in models]
    
    async def get_models_grouped(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get all models grouped by directory."""
        return self.repo.get_grouped_by_directory()
    
    async def delete_model(self, model_id: int) -> bool:
        """Delete a model and all related data, including from providers."""
        if not self.repo.get_model(model_id):
            raise NotFoundError("Model", str(model_id))
        
        # Trigger deletion from all providers BEFORE removing from DB
        await self.trigger_delete_from_providers(model_id)
        
        return self.repo.delete_model(model_id)
    
    async def check_and_trigger_dependencies(
        self, 
        civitai_data: Optional[Dict[str, Any]] = None,
        base_model_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Check for and trigger auto-download of dependencies (CLIP/VAE) for UNET models.
        
        Args:
            civitai_data: Full CivitAI data (used during import)
            base_model_name: Explicit base model name (used during manual check)
            
        Returns:
            Dict identifying what was triggered
        """
        import aiohttp
        import os
        from core.entities_v2 import FLUX_DEFAULT_COMPONENTS, AURAFLOW_DEFAULT_COMPONENTS, is_unet_only_model
        
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
        
        print(f"[ModelService] {model_type} model detected - creating dependency entries")
        
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
                    base_model=model_type  # "Flux" or "AuraFlow/Pony V7"
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
                        from core.entities_v2 import ModelVersion, ModelV2
                        version = self.session.exec(
                            select(ModelVersion).where(ModelVersion.id == existing_file.version_id)
                        ).first()
                        if version:
                            existing_model = self.repo.get_model(version.model_id)
                            if existing_model:
                                models_to_download.append(existing_model)
                                print(f"[ModelService] Re-syncing existing dependency: {filename}")
        
        # Now trigger downloads for all models (new and existing that need re-sync)
        for model in models_to_download:
            print(f"[ModelService] Triggering download for dependency: {model.name}")
            await self.trigger_download_to_providers(model.id)
        
        print(f"[ModelService] ✓ Triggered downloads for {len(models_to_download)} dependencies for {model_type}")
        
        return {
            "triggered": True,
            "model_type": model_type,
            "count": len(models_to_download),
            "downloads": [m.name for m in models_to_download]
        }


    
    # =========================================================================
    # PROVIDER SYNC OPERATIONS (Immediate triggers)
    # =========================================================================
    
    async def trigger_download_to_providers(
        self, 
        model_id: int, 
        version_ids: List[int] = None
    ) -> Dict[str, Any]:
        """
        Trigger immediate download of model files to all enabled providers.
        Called after adding a model to the database.
        
        Args:
            model_id: The model ID
            version_ids: Optional list of specific version IDs to download.
                         If None, downloads all enabled versions.
        """
        import aiohttp
        import os
        
        model = self.repo.get_model(model_id)
        if not model:
            return {"status": "error", "message": f"Model {model_id} not found"}
        
        # Get enabled providers
        from core.entities import Provider
        from sqlmodel import select
        providers = list(self.session.exec(
            select(Provider).where(Provider.enabled == True)
        ).all())
        
        if not providers:
            return {"status": "skipped", "message": "No enabled providers"}
        
        results = {"triggered": 0, "providers": []}
        
        # Get versions to download
        versions = self.repo.get_versions_for_model(model_id)
        for version in versions:
            # Skip if version_ids specified and this version not in list
            if version_ids is not None and version.id not in version_ids:
                continue
            if not version.is_enabled:
                continue
                
            file = self.repo.get_primary_file_for_version(version.id)
            if not file or not file.download_url:
                continue
            
            storage_path = f"models/{model.directory}/{file.storage_filename}"
            
            # Determine token based on URL
            token = None
            if file.download_url:
                if "huggingface.co" in file.download_url:
                    token = os.getenv("HF_TOKEN", "")
                elif "civitai.com" in file.download_url:
                    token = os.getenv("CIVITAI_TOKEN", "")
            
            # Send download request to each enabled provider
            for provider in providers:
                # Container name is comfy-provider-{id}, internal port is always 8000
                container_name = f"comfy-provider-{provider.id}"
                worker_url = f"http://{container_name}:8000"
                
                try:
                    async with aiohttp.ClientSession() as session:
                        payload = {
                            "url": file.download_url,
                            "path": storage_path,
                            "token": token
                        }
                        async with session.post(
                            f"{worker_url}/download-model",
                            json=payload,
                            timeout=aiohttp.ClientTimeout(total=10)
                        ) as resp:
                            if resp.status == 200:
                                results["triggered"] += 1
                                results["providers"].append({
                                    "provider_id": provider.id,
                                    "file_id": file.id,
                                    "status": "queued"
                                })
                                
                                # Update provider status to downloading
                                self.repo.update_provider_status(
                                    file_id=file.id,
                                    provider_name=provider.id,
                                    status="downloading",
                                    storage_path=storage_path
                                )
                except Exception as e:
                    print(f"[ModelService] Failed to trigger download to {provider.id}: {e}")
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
        import aiohttp
        
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
        for version in versions:
            file = self.repo.get_primary_file_for_version(version.id)
            if not file:
                continue
            
            storage_path = f"models/{model.directory}/{file.storage_filename}"
            
            # Send delete request to each provider
            for provider in providers:
                # Container name is comfy-provider-{id}, internal port is always 8000
                container_name = f"comfy-provider-{provider.id}"
                worker_url = f"http://{container_name}:8000"
                
                try:
                    async with aiohttp.ClientSession() as session:
                        # URL-encode the path for the route param
                        import urllib.parse
                        encoded_path = urllib.parse.quote(storage_path, safe='')
                        async with session.delete(
                            f"{worker_url}/delete-file/{encoded_path}",
                            timeout=aiohttp.ClientTimeout(total=10)
                        ) as resp:
                            if resp.status == 200:
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
                    print(f"[ModelService] Failed to delete from {provider.id}: {e}")
                    # Don't fail the whole operation - provider might be offline
                    results["providers"].append({
                        "provider_id": provider.id,
                        "file_id": file.id,
                        "status": "error",
                        "error": str(e)
                    })
        
        return results
    
    # =========================================================================
    # VERSION OPERATIONS
    # =========================================================================
    
    async def get_versions(self, model_id: int) -> List[Dict[str, Any]]:
        """Get all versions for a model."""
        versions = self.repo.get_versions_for_model(model_id)
        return [self.repo.version_to_dict(v) for v in versions]
    
    async def set_default_version(self, model_id: int, version_id: int) -> bool:
        """Set a version as the default for generation."""
        return self.repo.set_default_version(model_id, version_id)
    
    async def toggle_version_enabled(self, version_id: int) -> Optional[Dict[str, Any]]:
        """Toggle whether a version is enabled."""
        version = self.repo.toggle_version_enabled(version_id)
        if version:
            return self.repo.version_to_dict(version)
        return None
    
    async def get_version_for_generation(
        self, 
        model_id: int, 
        version_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get version info for generation.
        If version_id is not specified, returns the default version.
        """
        if version_id:
            version = self.session.get(ModelVersion, version_id)
        else:
            version = self.repo.get_default_version(model_id)
        
        if not version:
            raise NotFoundError("Version", str(version_id or "default"))
        
        # Get the primary file
        file = self.repo.get_primary_file_for_version(version.id)
        if not file:
            raise NotFoundError("File", f"for version {version.id}")
        
        model = self.repo.get_model(model_id)
        
        return {
            "model_id": model_id,
            "version_id": version.id,
            "model_name": model.name,
            "version_name": version.name,
            "base_model": version.base_model,
            "directory": model.directory,
            "storage_path": f"models/{model.directory}/{file.storage_filename}",
            "trained_words": version.trained_words
        }
    
    # =========================================================================
    # PROVIDER STATUS OPERATIONS
    # =========================================================================
    
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
        return {
            "file_id": status_obj.file_id,
            "provider_name": status_obj.provider_name,
            "status": status_obj.status,
            "storage_path": status_obj.storage_path,
            "size_bytes": status_obj.size_bytes,
            "downloaded_at": status_obj.downloaded_at.isoformat() if status_obj.downloaded_at else None
        }
    
    async def get_model_provider_statuses(self, model_id: int) -> Dict[str, Dict[str, Any]]:
        """Get all provider statuses for a model."""
        return self.repo.get_provider_statuses_for_model(model_id)
    
    # =========================================================================
    # RECONCILIATION OPERATIONS
    # =========================================================================
    
    def get_pending_downloads(self, provider_name: str) -> List[Dict[str, Any]]:
        """Get files pending download for a provider (sync method for worker)."""
        return self.repo.get_pending_downloads(provider_name)
    
    def get_full_cache(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get all model metadata for reconciliation (sync method for worker)."""
        return self.repo.get_grouped_by_directory()
    
    # =========================================================================
    # SEARCH OPERATIONS
    # =========================================================================
    
    async def search_by_tag(self, tag: str) -> List[Dict[str, Any]]:
        """Search models by tag."""
        models = self.repo.search_by_tag(tag)
        return [self.repo.model_to_dict(m, include_versions=False) for m in models]
    
    async def search_models(
        self, 
        query: str = "",
        model_type: Optional[str] = None,
        base_model: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Search models by name, type, or base model.
        """
        from sqlmodel import select, or_
        
        stmt = select(ModelV2)
        
        if query:
            stmt = stmt.where(
                or_(
                    ModelV2.name.ilike(f"%{query}%"),
                    ModelV2.creator_username.ilike(f"%{query}%")
                )
            )
        
        if model_type:
            stmt = stmt.where(ModelV2.type == model_type)
        
        models = list(self.session.exec(stmt).all())
        
        # Filter by base_model if specified (need to check versions)
        if base_model:
            filtered = []
            for model in models:
                versions = self.repo.get_versions_for_model(model.id)
                if any(v.base_model == base_model for v in versions):
                    filtered.append(model)
            models = filtered
        
        return [self.repo.model_to_dict(m, include_versions=False) for m in models]
