# Model Service V2 - Version-aware business logic for normalized model schema
#
# Operates on the V2 schema (models_v2, model_versions, model_files,
# provider_version_status) which stores full CivitAI metadata with proper
# relational structure.
#
# KEY RESPONSIBILITIES:
#   - Facade class coordinating sub-services for download, reconciliation, and sync.
#   - Ensuring 100% backward compatibility with all existing callers.
from typing import Any

from sqlmodel import Session

from core.entities import ModelV2, ModelVersion
from core.exceptions import NotFoundError
from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2
from services.model_civitai_sync import ModelCivitaiSyncService
from services.model_downloader import ModelDownloader
from services.model_reconciliation import ModelReconciliationService


class ModelServiceV2:
    """
    Facade class delegating model management tasks to specialized sub-services:
    - ModelDownloader (downloading, status updates, custom models, dependencies)
    - ModelReconciliationService (auto-discovery, cache, pending status reconciliation)
    - ModelCivitaiSyncService (civitai model and version imports)
    """

    def __init__(self, session: Session):
        self.session = session
        self.repo = ModelRepositoryV2(session)
        self.downloader = ModelDownloader(session, self.repo)
        self.reconciliation = ModelReconciliationService(session, self.repo)
        self.civitai_sync = ModelCivitaiSyncService(session, self.repo, self.downloader)

    # =========================================================================
    # MODEL OPERATIONS
    # =========================================================================

    async def add_model_from_civitai(
        self,
        civitai_data: dict[str, Any],
        selected_version_ids: list[int]
    ) -> dict[str, Any]:
        """Add a model from CivitAI with selected versions."""
        return await self.civitai_sync.add_model_from_civitai(civitai_data, selected_version_ids)

    async def get_model(self, model_id: int) -> dict[str, Any]:
        """Get a model by ID."""
        model = self.repo.get_model(model_id)
        if not model:
            raise NotFoundError("Model", str(model_id))
        return self.repo.model_to_dict(model)

    async def list_models(self, include_versions: bool = False) -> list[dict[str, Any]]:
        """List all models (bulk-loaded, no N+1)."""
        models = self.repo.get_all_models()
        return self.repo.models_to_dict(models, include_versions=include_versions)

    async def list_models_by_directory(self, directory: str) -> list[dict[str, Any]]:
        """List models in a specific directory (bulk-loaded, no N+1)."""
        models = self.repo.get_models_by_directory(directory)
        return self.repo.models_to_dict(models, include_versions=True)

    def get_models_grouped(self) -> dict[str, list[dict[str, Any]]]:
        """Get all models grouped by directory.

        Synchronous on purpose. This was `async def` around one synchronous
        SQLModel query, so every caller awaited a function that never yielded —
        which read as "off the loop" and was not. Its only caller is
        `GET /api/v2/models/`, the 1.5 MB listing that measured flat at 778 ms
        per request from concurrency 1 to 16: fully serialised behind the event
        loop, because the query really did run there.
        """
        return self.repo.get_grouped_by_directory()

    async def delete_model(self, model_id: int) -> bool:
        """Delete a model and all related data, including from providers."""
        model = self.repo.get_model(model_id)
        if not model:
            raise NotFoundError("Model", str(model_id))
            
        for f in self.repo.get_files_for_model(model_id):
            storage_path = f"models/{model.directory}/{f.storage_filename}"
            self.repo.add_tombstone(storage_path)

        # Trigger deletion from all providers BEFORE removing from DB
        await self.downloader.trigger_delete_from_providers(model_id)

        return self.repo.delete_model(model_id)

    async def check_and_trigger_dependencies(
        self, 
        civitai_data: dict[str, Any] | None = None,
        base_model_name: str | None = None
    ) -> dict[str, Any]:
        """Check for and trigger auto-download of dependencies (CLIP/VAE) for UNET models."""
        return await self.downloader.check_and_trigger_dependencies(civitai_data, base_model_name)

    # =========================================================================
    # PROVIDER SYNC OPERATIONS (Immediate triggers)
    # =========================================================================

    async def trigger_download_to_providers(
        self, 
        model_id: int, 
        version_ids: list[int] = None,
        provider_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Trigger immediate download of model files to all enabled providers."""
        return await self.downloader.trigger_download_to_providers(model_id, version_ids, provider_ids)

    async def add_custom_model(
        self,
        *,
        name: str,
        directory: str,
        download_url: str,
        provider_ids: list[str] | None = None,
        model_type: str | None = None,
    ) -> dict[str, Any]:
        """Create a V2 model entry for a direct download URL and trigger sync."""
        return await self.downloader.add_custom_model(
            name=name,
            directory=directory,
            download_url=download_url,
            provider_ids=provider_ids,
            model_type=model_type,
        )

    async def register_discovered_files(
        self,
        provider_id: str,
        files: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Register files discovered on a provider's storage."""
        return await self.reconciliation.register_discovered_files(provider_id, files)

    async def trigger_delete_from_providers(self, model_id: int) -> dict[str, Any]:
        """Trigger immediate deletion of model files from all providers."""
        return await self.downloader.trigger_delete_from_providers(model_id)

    # =========================================================================
    # VERSION OPERATIONS
    # =========================================================================

    async def get_versions(self, model_id: int) -> list[dict[str, Any]]:
        """Get all versions for a model."""
        versions = self.repo.get_versions_for_model(model_id)
        return [self.repo._version_to_dict(v) for v in versions]

    async def set_default_version(self, model_id: int, version_id: int) -> bool:
        """Set a version as the default for generation."""
        return self.repo.set_default_version(model_id, version_id)

    async def toggle_version_enabled(self, version_id: int) -> dict[str, Any] | None:
        """Toggle whether a version is enabled."""
        version = self.repo.toggle_version_enabled(version_id)
        if version:
            return self.repo._version_to_dict(version)
        return None

    def get_version_for_generation(
        self,
        model_id: int,
        version_id: int | None = None
    ) -> dict[str, Any]:
        """Get version info for generation.

        If version_id is not specified, returns the default version.

        Synchronous on purpose: this was `async def` around four synchronous
        session/repo reads, so `GET /api/v2/models/{id}/generation-info` — which
        the generator calls before every submission — ran them on the event loop.
        """
        if version_id:
            version = self.session.get(ModelVersion, version_id)
        else:
            version = self.repo.get_default_version(model_id)
        
        if not version or str(version.model_id) != str(model_id):
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
        file_id: str,
        provider_id: str,
        status: str,
        storage_path: str | None = None,
        size_bytes: int | None = None,
        error_message: str | None = None
    ) -> dict[str, Any]:
        """Update provider status for a file."""
        return await self.downloader.update_provider_file_status(
            file_id=file_id,
            provider_id=provider_id,
            status=status,
            storage_path=storage_path,
            size_bytes=size_bytes,
            error_message=error_message,
        )

    async def get_model_provider_statuses(self, model_id: int) -> dict[str, dict[str, Any]]:
        """Get all provider statuses for a model."""
        return await self.downloader.get_model_provider_statuses(model_id)

    # =========================================================================
    # RECONCILIATION OPERATIONS
    # =========================================================================

    def get_pending_downloads(self, provider_id: str) -> list[dict[str, Any]]:
        """Get pending downloads for a specific provider."""
        return self.reconciliation.get_pending_downloads(provider_id)

    def get_full_cache(self) -> dict[str, list[dict[str, Any]]]:
        """Get all model metadata for reconciliation (sync method for worker)."""
        return self.reconciliation.get_full_cache()

    # =========================================================================
    # SEARCH OPERATIONS
    # =========================================================================

    async def search_by_tag(self, tag: str) -> list[dict[str, Any]]:
        """Search models by tag (bulk-loaded, no N+1)."""
        models = self.repo.search_by_tag(tag)
        return self.repo.models_to_dict(models, include_versions=False)

    async def search_models(
        self, 
        query: str = "",
        model_type: str | None = None,
        base_model: str | None = None
    ) -> list[dict[str, Any]]:
        """Search models by name, type, or base model."""
        from sqlmodel import or_, select
        
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
            model_ids = [m.id for m in models]
            if not model_ids:
                return []
            
            stmt = select(ModelVersion.model_id).where(
                ModelVersion.model_id.in_(model_ids),
                ModelVersion.base_model == base_model
            ).distinct()
            matching_model_ids = set(self.session.exec(stmt).all())
            
            models = [m for m in models if m.id in matching_model_ids]
        
        return self.repo.models_to_dict(models, include_versions=False)
