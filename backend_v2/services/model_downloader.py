import asyncio
from typing import Any

from sqlmodel import Session

from core.entities import (
    AURAFLOW_DEFAULT_COMPONENTS,
    FLUX_DEFAULT_COMPONENTS,
    ModelFile,
    ModelV2,
    ModelVersion,
    Provider,
    is_unet_only_model,
)
from core.exceptions import NotFoundError
from infrastructure.http_client import get_http_client
from infrastructure.logging import model_logger
from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2

logger = model_logger()


class ModelDownloader:
    """
    Handles model downloads, status updates, custom model registration,
    and dependency tracking for the model service.
    """

    def __init__(self, session: Session, repo: ModelRepositoryV2 | None = None):
        self.session = session
        self.repo = repo or ModelRepositoryV2(session)

    async def trigger_download_to_providers(
        self, 
        model_id: int, 
        version_ids: list[int] = None,
        provider_ids: list[str] | None = None,
    ) -> dict[str, Any]:
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
            
        # Add pending statuses for all relevant files and providers BEFORE triggering
        all_versions = self.repo.get_versions_for_model(model_id)
        target_versions = [v for v in all_versions if v.id in version_ids] if version_ids else all_versions
        
        for provider in providers:
            for version in target_versions:
                file = self.repo.get_primary_file_for_version(version.id)
                if file:
                    status = "not_installed" if getattr(provider, "type", None) in {"direct_url", "remote_comfy"} else "pending"
                    self.repo.update_provider_status(
                        file_id=file.id,
                        provider_id=provider.id,
                        status=status,
                        force_create=True
                    )
        
        results = {"triggered": 0, "providers": []}
        
        http_client = get_http_client()
        for provider in providers:
            from services.provider_runtime import resolve_provider_runtime
            runtime = resolve_provider_runtime(provider)

            if runtime.mode not in ("container_http", "discovery"):
                results["providers"].append({
                    "provider_id": provider.id,
                    "status": "skipped",
                    "error": f"Runtime unavailable ({runtime.mode})",
                })
                continue

            if getattr(provider, "worker_type", "image") == "llm":
                results["providers"].append({
                    "provider_id": provider.id,
                    "status": "skipped",
                    "error": "LLM workers do not reconcile model files",
                })
                continue

            if getattr(provider, "type", None) in {"direct_url", "remote_comfy"}:
                results["providers"].append({
                    "provider_id": provider.id,
                    "status": "external",
                    "message": "Model files are managed by the external ComfyUI host",
                })
                continue

            worker_url = runtime.worker_url
            try:
                response = await http_client.post(
                    f"{worker_url}/reconcile",
                    timeout=5.0,
                )
                if response.status_code == 200:
                    results["triggered"] += 1
                    results["providers"].append({
                        "provider_id": provider.id,
                        "status": "reconciling"
                    })
                else:
                    logger.warning("provider_reconcile_trigger_failed", provider_id=provider.id, status=response.status_code)
                    results["providers"].append({
                        "provider_id": provider.id,
                        "status": "failed",
                        "error": f"Status {response.status_code}"
                    })
            except Exception as e:
                logger.warning("provider_reconcile_trigger_error", provider_id=provider.id, error=str(e))
                results["providers"].append({
                    "provider_id": provider.id,
                    "status": "error",
                    "error": str(e)
                })
        
        return results

    async def trigger_delete_from_providers(self, model_id: int) -> dict[str, Any]:
        """
        Trigger immediate deletion of model files from all providers.
        Called BEFORE deleting model from database.
        """
        model = self.repo.get_model(model_id)
        if not model:
            return {"status": "error", "message": f"Model {model_id} not found"}
        
        # Get all providers (even disabled - clean up everywhere)
        from sqlmodel import select

        from core.entities import Provider
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
                from services.provider_runtime import resolve_provider_runtime
                runtime = resolve_provider_runtime(provider)
                
                if not runtime.worker_url:
                    continue
                
                worker_url = runtime.worker_url
                
                try:
                    if hasattr(http_client, "request"):
                        response = await http_client.request(
                            "DELETE",
                            f"{worker_url}/delete-file",
                            json={"path": storage_path},
                            timeout=10.0,
                        )
                    else:
                        import urllib.parse
                        encoded_path = urllib.parse.quote(storage_path, safe="")
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
        provider_ids: list[str] | None = None,
        model_type: str | None = None,
    ) -> dict[str, Any]:
        """Create a V2 model entry for a direct download URL and trigger sync.

        The record creation is a `to_thread` because it is six synchronous
        session calls (`get` / `add` / `flush` x2 / `commit` / `refresh`) plus
        two repository reads, and it used to run inline on the event loop
        before the first real suspension — the `trigger_download_to_providers`
        HTTP call at the end. Splitting it out keeps the genuinely-async part
        genuinely async and moves the blocking part off the loop.
        """
        filename = name.split("/")[-1].strip()
        if not filename:
            raise ValueError("Model filename is required")

        existing_file = await asyncio.to_thread(
            self.repo.get_file_by_storage_path, directory, filename
        )
        if existing_file:
            version = await asyncio.to_thread(
                self.session.get, ModelVersion, existing_file.version_id
            )
            existing_model = self.repo.get_model(version.model_id) if version else None
            if not existing_model:
                raise NotFoundError("Model", filename)

            await self.trigger_download_to_providers(existing_model.id, provider_ids=provider_ids)
            return self.repo.model_to_dict(existing_model)

        resolved_type = model_type or directory.replace("models/", "").replace("_", " ").title()

        def _create_record() -> ModelV2:
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
            return model

        model = await asyncio.to_thread(_create_record)

        await self.trigger_download_to_providers(model.id, provider_ids=provider_ids)
        return self.repo.model_to_dict(model)

    async def check_and_trigger_dependencies(
        self, 
        civitai_data: dict[str, Any] | None = None,
        base_model_name: str | None = None
    ) -> dict[str, Any]:
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

    def update_provider_file_status(
        self,
        file_id: str,
        provider_id: str,
        status: str,
        storage_path: str | None = None,
        size_bytes: int | None = None,
        error_message: str | None = None
    ) -> dict[str, Any]:
        """Update provider status for a file.

        Synchronous on purpose: this is one repository upsert (with its commit)
        plus an in-memory routing-cache invalidation, and there is no suspension
        anywhere in it. The `async def` this replaces bought nothing and cost
        every caller a blocking write on the event loop. Callers that are
        themselves `async def` and have a session they cannot hand to a worker
        thread wrap this in `asyncio.to_thread`, which is the idiom
        `api/routes/world_vault/chats.py` already uses for `session.commit`.
        """
        status_obj = self.repo.update_provider_status(
            file_id=file_id,
            provider_id=provider_id,
            status=status,
            storage_path=storage_path,
            size_bytes=size_bytes,
            error_message=error_message
        )
        provider_key = status_obj.provider_id or provider_id

        # Provider readiness changed; clear model-aware routing memoization.
        from services.load_balancer import LoadBalancer
        LoadBalancer.invalidate_model_availability_cache(provider_id=provider_key)

        return {
            "file_id": status_obj.file_id,
            "provider_id": provider_key,
            "status": status_obj.status,
            "storage_path": status_obj.storage_path,
            "size_bytes": status_obj.size_bytes,
            "downloaded_at": status_obj.downloaded_at.isoformat() if status_obj.downloaded_at else None
        }

    async def get_model_provider_statuses(self, model_id: int) -> dict[str, dict[str, Any]]:
        """Get all provider statuses for a model."""
        return self.repo.get_provider_statuses_for_model(model_id)
