# Model Repository V2 - Version-aware data access layer
from sqlmodel import Session, select, col, and_, or_
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from typing import Optional, List, Dict, Any, Tuple, Union
from datetime import datetime, timezone
import json

from core.entities import (
    ModelV2, ModelVersion, ModelFile, ModelImage, 
    ProviderVersionStatus, ModelTag, compute_storage_filename, get_directory_from_type,
    is_unet_only_model, FLUX_DEFAULT_COMPONENTS, DeletedFileTombstone
)
from infrastructure.logging import get_logger

logger = get_logger("model_repo_v2")


def parse_civitai_datetime(value: Any) -> Optional[datetime]:
    """Parse CivitAI datetime string to Python datetime object."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            # CivitAI uses ISO format: 2024-01-15T12:00:00.000Z
            # Try multiple formats
            for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"]:
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
            # Fallback: try fromisoformat after replacing Z
            return datetime.fromisoformat(value.replace("Z", "+00:00").replace("+00:00", ""))
        except (ValueError, AttributeError):
            return None
    return None


class ModelRepositoryV2:
    """
    Version-aware data access layer for models.
    Replaces the flat ModelRepository with normalized operations.
    """
    
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _get_provider_key(status: ProviderVersionStatus) -> str:
        """Return provider ID."""
        return status.provider_id

    def _provider_match_clause(self, provider_key: str):
        """Build a provider filter."""
        return ProviderVersionStatus.provider_id == provider_key

    def _provider_match_clause_many(self, provider_keys: List[str]):
        """Build a provider filter for multiple providers."""
        return ProviderVersionStatus.provider_id.in_(provider_keys)
    
    # =========================================================================
    # MODEL CRUD
    # =========================================================================
    
    def create_model_with_versions(
        self,
        civitai_data: Dict[str, Any],
        selected_version_ids: List[int]
    ) -> ModelV2:
        """
        Create a model with only the selected versions.
        
        Args:
            civitai_data: Full CivitAI API response
            selected_version_ids: List of version IDs to include
            
        Returns:
            Created ModelV2 instance
        """
        # Extract base model info
        stats = civitai_data.get("stats", {})
        creator = civitai_data.get("creator", {})
        model_type = civitai_data.get("type", "Checkpoint")
        
        # Get base_model from first selected version for directory routing
        # (Flux "Checkpoints" need to go to unet/ directory)
        first_version_base_model = None
        for version_data in civitai_data.get("modelVersions", []):
            if version_data.get("id") in selected_version_ids:
                first_version_base_model = version_data.get("baseModel")
                break
        
        # Create model
        model = ModelV2(
            civitai_model_id=civitai_data.get("id"),
            name=civitai_data.get("name", "Unknown"),
            type=model_type,
            directory=get_directory_from_type(model_type, first_version_base_model),

            description=civitai_data.get("description"),
            nsfw=civitai_data.get("nsfw", False),
            nsfw_level=civitai_data.get("nsfwLevel", 1),
            creator_username=creator.get("username"),
            creator_image=creator.get("image"),
            stats_downloads=stats.get("downloadCount", 0),
            stats_thumbs_up=stats.get("thumbsUpCount", 0),
            stats_thumbs_down=stats.get("thumbsDownCount", 0),
            stats_comments=stats.get("commentCount", 0),
            source="civitai",
            source_url=f"https://civitai.com/models/{civitai_data.get('id')}"
        )
        self.session.add(model)
        self.session.flush()  # Get model ID
        
        # Create tags
        for tag in civitai_data.get("tags", []):
            tag_obj = ModelTag(model_id=model.id, tag=tag)
            self.session.add(tag_obj)
        
        # Create selected versions
        is_first = True
        for version_data in civitai_data.get("modelVersions", []):
            if version_data.get("id") not in selected_version_ids:
                continue
            
            trained_words = version_data.get("trainedWords", [])
            
            version = ModelVersion(
                model_id=model.id,
                civitai_version_id=version_data.get("id"),
                name=version_data.get("name", "v1.0"),
                base_model=version_data.get("baseModel"),
                base_model_type=version_data.get("baseModelType"),
                description=version_data.get("description"),
                is_enabled=True,
                is_default=is_first,  # First selected version is default
                trained_words=json.dumps(trained_words) if trained_words else None,
                civitai_created_at=parse_civitai_datetime(version_data.get("createdAt")),
                civitai_published_at=parse_civitai_datetime(version_data.get("publishedAt"))
            )
            self.session.add(version)
            self.session.flush()
            is_first = False
            
            # Create files - prefer safetensors format
            files_list = version_data.get("files", [])
            
            # Find the best file to use (prefer safetensors)
            def get_file_priority(f):
                """Lower is better. Prefer safetensors, avoid GGUF."""
                name = f.get("name", "").lower()
                score = 0
                
                # Extension priority
                if name.endswith(".safetensors"):
                    score -= 100
                elif name.endswith(".gguf"):
                    score -= 75  # Prefer GGUF over ckpt
                elif name.endswith((".ckpt", ".pt", ".pth", ".bin")):
                    score -= 50
                    
                # Primary flag priority
                if f.get("primary", False):
                    score -= 10
                    
                return score
            
            # Sort files by priority and take the best one
            sorted_files = sorted(files_list, key=get_file_priority)
            
            # Only store the primary (best) file - no need for multiple formats
            for i, file_data in enumerate(sorted_files[:1]):  # Take only the first (best) file
                hashes = file_data.get("hashes", {})
                
                # Force safetensors extension if the selected file is safetensors
                original_name = file_data.get("name", "model.safetensors")
                storage_filename = compute_storage_filename(
                    model.name,
                    version.name,
                    version_data.get("id"),
                    original_name
                )
                
                file = ModelFile(
                    version_id=version.id,
                    civitai_file_id=file_data.get("id"),
                    original_filename=original_name,
                    storage_filename=storage_filename,
                    size_kb=file_data.get("sizeKB", 0),
                    format=file_data.get("metadata", {}).get("format") if file_data.get("metadata") else None,
                    hash_sha256=hashes.get("SHA256"),
                    hash_autov2=hashes.get("AutoV2"),
                    hash_blake3=hashes.get("BLAKE3"),
                    hash_crc32=hashes.get("CRC32"),
                    download_url=file_data.get("downloadUrl"),
                    is_primary=True,  # Always primary since we only store one file
                    file_type=file_data.get("type", "Model")
                )
                self.session.add(file)
            
            # Create images
            for i, img_data in enumerate(version_data.get("images", [])):
                image = ModelImage(
                    version_id=version.id,
                    url=img_data.get("url"),
                    width=img_data.get("width"),
                    height=img_data.get("height"),
                    blurhash=img_data.get("hash"),
                    type=img_data.get("type", "image"),
                    nsfw_level=img_data.get("nsfwLevel", 1),
                    has_meta=img_data.get("hasMeta", False),
                    has_positive_prompt=img_data.get("hasPositivePrompt", False),
                    sort_order=i
                )
                self.session.add(image)
        
        self.session.commit()
        self.session.refresh(model)
        return model
    
    def add_versions_to_model(
        self,
        model: ModelV2,
        civitai_data: Dict[str, Any],
        selected_version_ids: List[int]
    ) -> List[ModelVersion]:
        """
        Add new versions to an existing model.
        
        Args:
            model: Existing ModelV2 instance
            civitai_data: Full CivitAI API response
            selected_version_ids: List of version IDs to add
            
        Returns:
            List of created ModelVersion instances
        """
        created_versions = []
        
        for version_data in civitai_data.get("modelVersions", []):
            if version_data.get("id") not in selected_version_ids:
                continue
            
            trained_words = version_data.get("trainedWords", [])
            
            version = ModelVersion(
                model_id=model.id,
                civitai_version_id=version_data.get("id"),
                name=version_data.get("name", "v1.0"),
                base_model=version_data.get("baseModel"),
                base_model_type=version_data.get("baseModelType"),
                description=version_data.get("description"),
                is_enabled=True,
                is_default=False,  # Don't change default for added versions
                trained_words=json.dumps(trained_words) if trained_words else None,
                civitai_created_at=parse_civitai_datetime(version_data.get("createdAt")),
                civitai_published_at=parse_civitai_datetime(version_data.get("publishedAt"))
            )
            self.session.add(version)
            self.session.flush()
            
            # Create files - prefer safetensors format
            files_list = version_data.get("files", [])
            
            def get_file_priority(f):
                name = f.get("name", "").lower()
                score = 0
                
                # Extension priority
                if name.endswith(".safetensors"):
                    score -= 100
                elif name.endswith(".gguf"):
                    score -= 75  # Prefer GGUF over ckpt
                elif name.endswith((".ckpt", ".pt", ".pth", ".bin")):
                    score -= 50
                    
                # Primary flag priority
                if f.get("primary", False):
                    score -= 10
                    
                return score
            
            sorted_files = sorted(files_list, key=get_file_priority)
            
            for file_data in sorted_files[:1]:
                hashes = file_data.get("hashes", {})
                original_name = file_data.get("name", "model.safetensors")
                storage_filename = compute_storage_filename(
                    model.name,
                    version.name,
                    version_data.get("id"),
                    original_name
                )
                
                file = ModelFile(
                    version_id=version.id,
                    civitai_file_id=file_data.get("id"),
                    original_filename=original_name,
                    storage_filename=storage_filename,
                    size_kb=file_data.get("sizeKB", 0),
                    format=file_data.get("metadata", {}).get("format") if file_data.get("metadata") else None,
                    hash_sha256=hashes.get("SHA256"),
                    hash_autov2=hashes.get("AutoV2"),
                    hash_blake3=hashes.get("BLAKE3"),
                    hash_crc32=hashes.get("CRC32"),
                    download_url=file_data.get("downloadUrl"),
                    is_primary=True,
                    file_type=file_data.get("type", "Model")
                )
                self.session.add(file)
            
            # Create images
            for i, img_data in enumerate(version_data.get("images", [])[:10]):
                image = ModelImage(
                    version_id=version.id,
                    url=img_data.get("url"),
                    width=img_data.get("width"),
                    height=img_data.get("height"),
                    blurhash=img_data.get("hash"),
                    type=img_data.get("type", "image"),
                    nsfw_level=img_data.get("nsfwLevel", 1),
                    has_meta=img_data.get("hasMeta", False),
                    has_positive_prompt=img_data.get("hasPositivePrompt", False),
                    sort_order=i
                )
                self.session.add(image)
            
            created_versions.append(version)
        
        self.session.commit()
        return created_versions
    
    def get_model(self, model_id: int) -> Optional[ModelV2]:
        """Get a model by ID."""
        return self.session.get(ModelV2, model_id)
    
    def get_model_by_civitai_id(self, civitai_id: int) -> Optional[ModelV2]:
        """Get a model by CivitAI model ID."""
        stmt = select(ModelV2).where(ModelV2.civitai_model_id == civitai_id)
        return self.session.exec(stmt).first()
    
    def get_all_models(self) -> List[ModelV2]:
        """Get all models."""
        stmt = select(ModelV2).order_by(col(ModelV2.updated_at).desc())
        return list(self.session.exec(stmt).all())
    
    def get_models_by_directory(self, directory: str) -> List[ModelV2]:
        """Get models in a specific directory."""
        stmt = select(ModelV2).where(ModelV2.directory == directory)
        return list(self.session.exec(stmt).all())
    
    def get_models_by_type(self, model_type: str) -> List[ModelV2]:
        """Get models of a specific type."""
        stmt = select(ModelV2).where(ModelV2.type == model_type)
        return list(self.session.exec(stmt).all())
    
    def delete_model(self, model_id: int) -> bool:
        """Delete a model and all related data (cascades)."""
        model = self.get_model(model_id)
        if not model:
            return False
        
        # Manual cascade since SQLite doesn't always respect FK cascades
        # Get versions
        versions = self.get_versions_for_model(model_id)
        for version in versions:
            # First, get all file IDs for this version
            files = self.get_files_for_version(version.id)
            file_ids = [f.id for f in files]
            
            # Delete provider statuses FIRST (they reference files)
            for file_id in file_ids:
                stmt = select(ProviderVersionStatus).where(
                    ProviderVersionStatus.file_id == file_id
                )
                for status in self.session.exec(stmt).all():
                    self.session.delete(status)
            
            # Flush to ensure provider statuses are deleted before files
            self.session.flush()
            
            # Now delete the files
            for file in files:
                self.session.delete(file)
            
            # Flush to ensure files are deleted before querying images
            self.session.flush()
            
            # Delete images
            stmt = select(ModelImage).where(ModelImage.version_id == version.id)
            for image in self.session.exec(stmt).all():
                self.session.delete(image)
            
            self.session.delete(version)
        
        # Flush before querying tags
        self.session.flush()
        
        # Delete tags
        stmt = select(ModelTag).where(ModelTag.model_id == model_id)
        for tag in self.session.exec(stmt).all():
            self.session.delete(tag)
        
        self.session.delete(model)
        self.session.commit()
        return True
    
    # =========================================================================
    # VERSION OPERATIONS
    # =========================================================================
    
    def get_versions_for_model(self, model_id: int) -> List[ModelVersion]:
        """Get all versions for a model."""
        stmt = select(ModelVersion).where(ModelVersion.model_id == model_id)
        return list(self.session.exec(stmt).all())
    
    def get_default_version(self, model_id: int) -> Optional[ModelVersion]:
        """Get the default version for a model."""
        stmt = select(ModelVersion).where(
            and_(ModelVersion.model_id == model_id, ModelVersion.is_default == True)
        )
        return self.session.exec(stmt).first()
    
    def get_version_by_civitai_id(self, civitai_version_id: int) -> Optional[ModelVersion]:
        """Get a version by CivitAI version ID."""
        stmt = select(ModelVersion).where(
            ModelVersion.civitai_version_id == civitai_version_id
        )
        return self.session.exec(stmt).first()
    
    def set_default_version(self, model_id: int, version_id: int) -> bool:
        """Set a version as the default for a model."""
        # Unset current default
        versions = self.get_versions_for_model(model_id)
        for v in versions:
            v.is_default = (v.id == version_id)
        self.session.commit()
        return True
    
    def toggle_version_enabled(self, version_id: int) -> Optional[ModelVersion]:
        """Toggle whether a version is enabled."""
        version = self.session.get(ModelVersion, version_id)
        if version:
            version.is_enabled = not version.is_enabled
            self.session.commit()
            self.session.refresh(version)
        return version
    
    # =========================================================================
    # FILE OPERATIONS
    # =========================================================================
    
    def get_files_for_version(self, version_id: int) -> List[ModelFile]:
        """Get all files for a version."""
        stmt = select(ModelFile).where(ModelFile.version_id == version_id)
        return list(self.session.exec(stmt).all())
    
    def get_primary_file_for_version(self, version_id: int) -> Optional[ModelFile]:
        """Get the primary file for a version."""
        stmt = select(ModelFile).where(
            and_(ModelFile.version_id == version_id, ModelFile.is_primary == True)
        )
        return self.session.exec(stmt).first()
    
    def get_file_by_storage_path(self, directory: str, filename: str) -> Optional[ModelFile]:
        """Get a file by its storage path components."""
        stmt = select(ModelFile).join(
            ModelVersion, ModelFile.version_id == ModelVersion.id
        ).join(
            ModelV2, ModelVersion.model_id == ModelV2.id
        ).where(
            ModelFile.storage_filename == filename,
            ModelV2.directory == directory
        )
        return self.session.exec(stmt).first()
    
    def add_tombstone(self, storage_path: str):
        existing = self.session.exec(select(DeletedFileTombstone).where(DeletedFileTombstone.storage_path == storage_path)).first()
        if not existing:
            self.session.add(DeletedFileTombstone(storage_path=storage_path))
            self.session.commit()
            
    def is_tombstoned(self, storage_path: str) -> bool:
        return self.session.exec(select(DeletedFileTombstone).where(DeletedFileTombstone.storage_path == storage_path)).first() is not None
    
    def create_system_dependency(
        self,
        name: str,
        model_type: str,
        directory: str,
        filename: str,
        download_url: str,
        size_mb: float = 0,
        description: str = "",
        base_model: str = ""
    ) -> Optional[ModelV2]:
        """
        Create a system dependency model (CLIP, VAE for Flux/AuraFlow).
        
        These are auto-downloaded dependencies with source='system' to 
        distinguish them from user-added models.
        
        Args:
            name: Display name (e.g., "T5-XXL Text Encoder")
            model_type: Type (e.g., "CLIP", "VAE")
            directory: Storage directory (e.g., "clip", "vae")
            filename: Storage filename
            download_url: URL to download from
            size_mb: Size in MB
            description: Description text
            base_model: Base model compatibility (e.g., "Flux.1 D")
            
        Returns:
            Created ModelV2 or None if already exists
        """
        # Check if this dependency already exists by looking for the file
        existing_file = self.get_file_by_storage_path(directory, filename)
        if existing_file:
            # Check if URL needs update (e.g. converting from gated to public mirror)
            if existing_file.download_url != download_url:
                logger.info("dependency_url_updated", filename=filename, old_url=existing_file.download_url, new_url=download_url)
                existing_file.download_url = download_url
                self.session.add(existing_file)
                self.session.commit()
                self.session.refresh(existing_file)
            
            # Already exists
            return None
        
        # Create the model
        model = ModelV2(
            name=name,
            type=model_type,
            directory=directory,
            description=description,
            source="system",  # Mark as system dependency
            source_url=download_url,
            nsfw=False,
            nsfw_level=1,
        )
        self.session.add(model)
        self.session.flush()  # Get the ID
        
        # Create a single version
        version = ModelVersion(
            model_id=model.id,
            name="v1.0",
            base_model=base_model,
            base_model_type="Standard",
            description=description,
            is_enabled=True,
            is_default=True,
        )
        self.session.add(version)
        self.session.flush()
        
        # Create the file entry
        file = ModelFile(
            version_id=version.id,
            original_filename=filename,
            storage_filename=filename,  # Use same name for system files
            size_kb=size_mb * 1024,
            format="SafeTensor",
            download_url=download_url,
            is_primary=True,
            file_type="Model",
        )
        self.session.add(file)
        
        self.session.commit()
        logger.info("system_dependency_created", name=name, directory=directory, filename=filename)
        
        return model

    
    # =========================================================================
    # PROVIDER STATUS OPERATIONS
    # =========================================================================
    
    def get_pending_downloads(self, provider_id: str) -> List[Dict[str, Any]]:
        """
        Get files pending download for a provider.
        Returns file info with version and model context.
        """
        stmt = select(ModelFile, ModelVersion, ModelV2).join(
            ModelVersion, ModelFile.version_id == ModelVersion.id
        ).join(
            ModelV2, ModelVersion.model_id == ModelV2.id
        ).outerjoin(
            ProviderVersionStatus,
            and_(
                ProviderVersionStatus.file_id == ModelFile.id,
                self._provider_match_clause(provider_id)
            )
        ).where(
            ModelVersion.is_enabled == True,
            ModelFile.download_url != None,
            ModelFile.download_url != "",
            or_(
                ProviderVersionStatus.id == None,
                ProviderVersionStatus.status != "ready"
            )
        )
        
        results = []
        for file, version, model in self.session.exec(stmt).all():
            results.append({
                "file_id": file.id,
                "version_id": version.id,
                "model_id": model.id,
                "model_name": model.name,
                "version_name": version.name,
                "storage_filename": file.storage_filename,
                "storage_path": f"models/{model.directory}/{file.storage_filename}",
                "download_url": file.download_url,
                "size_kb": file.size_kb,
                "hash_sha256": file.hash_sha256
            })
        return results
    
    def get_provider_status(
        self, 
        file_id: int, 
        provider_id: str
    ) -> Optional[ProviderVersionStatus]:
        """Get provider status for a specific file."""
        stmt = select(ProviderVersionStatus).where(
            and_(
                ProviderVersionStatus.file_id == file_id,
                self._provider_match_clause(provider_id)
            )
        )
        return self.session.exec(stmt).first()

    def get_provider_statuses_for_files(
        self,
        file_ids: List[int],
        provider_id: str,
    ) -> Dict[int, ProviderVersionStatus]:
        """Get provider statuses for many files in one query."""
        if not file_ids:
            return {}

        stmt = select(ProviderVersionStatus).where(
            and_(
                ProviderVersionStatus.file_id.in_(file_ids),
                self._provider_match_clause(provider_id),
            )
        )
        statuses = self.session.exec(stmt).all()
        return {status.file_id: status for status in statuses}
    
    def update_provider_status(
        self,
        file_id: int,
        provider_id: str,
        status: str,
        storage_path: Optional[str] = None,
        size_bytes: Optional[int] = None,
        error_message: Optional[str] = None
    ) -> ProviderVersionStatus:
        """Update or create provider status for a file."""
        existing = self.get_provider_status(file_id, provider_id)
        
        if existing:
            if not existing.provider_id:
                existing.provider_id = provider_id
            
            existing.status = status
            if status == "downloading":
                existing.queued_at = datetime.now(timezone.utc)
            if storage_path:
                existing.storage_path = storage_path
            if size_bytes:
                existing.size_bytes = size_bytes
            if error_message is not None:
                existing.error_message = error_message
            elif status != "failed":
                existing.error_message = None
            if status == "ready":
                existing.downloaded_at = datetime.now(timezone.utc)
            elif status == "failed":
                existing.retry_count += 1
            self.session.commit()
            self.session.refresh(existing)
            return existing
        else:
            new_status = ProviderVersionStatus(
                file_id=file_id,
                provider_id=provider_id,
                status=status,
                storage_path=storage_path,
                size_bytes=size_bytes,
                error_message=error_message,
                queued_at=datetime.now(timezone.utc),
                downloaded_at=datetime.now(timezone.utc) if status == "ready" else None,
                retry_count=0
            )
            self.session.add(new_status)
            self.session.commit()
            self.session.refresh(new_status)
            return new_status
    
    def get_provider_statuses_for_model(
        self, 
        model_id: int
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get all provider statuses for a model's files.
        Returns dict keyed by provider_id.
        """
        # Get all files for this model's versions
        stmt = select(ProviderVersionStatus, ModelFile, ModelVersion).join(
            ModelFile, ProviderVersionStatus.file_id == ModelFile.id
        ).join(
            ModelVersion, ModelFile.version_id == ModelVersion.id
        ).where(ModelVersion.model_id == model_id)
        
        result: Dict[str, Dict[str, Any]] = {}
        for status, file, version in self.session.exec(stmt).all():
            provider_key = self._get_provider_key(status)
            if not provider_key:
                continue

            if provider_key not in result:
                result[provider_key] = {
                    "status": status.status,
                    "files": [],
                    "total_size": 0
                }
            result[provider_key]["files"].append({
                "file_id": file.id,
                "filename": file.storage_filename,
                "status": status.status,
                "size_bytes": status.size_bytes
            })
            if status.size_bytes:
                result[provider_key]["total_size"] += status.size_bytes
        
        return result
    
    def delete_all_statuses_for_provider(self, provider_id: str) -> int:
        """
        Delete all ProviderVersionStatus records for a given provider.
        Used when deleting a provider to cascade cleanup.
        
        Returns:
            Number of records deleted
        """
        stmt = select(ProviderVersionStatus).where(
            self._provider_match_clause(provider_id)
        )
        statuses = list(self.session.exec(stmt).all())
        count = len(statuses)
        
        for status in statuses:
            self.session.delete(status)
        
        if count > 0:
            self.session.commit()
        
        return count
    
    def cleanup_orphaned_provider_statuses(self, active_provider_names: List[str]) -> Dict[str, int]:
        """
        Delete ProviderVersionStatus records for providers that no longer exist.
        
        Args:
            active_provider_names: List of provider names/IDs that currently exist
            
        Returns:
            Dict with 'deleted_count' and 'orphaned_providers' list
        """
        from sqlalchemy import distinct
        
        # Get all unique provider identifiers in ProviderVersionStatus.
        stmt = select(distinct(ProviderVersionStatus.provider_id))
        all_provider_names = {
            provider_key
            for provider_key in self.session.exec(stmt).all()
            if provider_key
        }
        
        # Find orphaned provider names (in status table but not in active providers)
        active_set = set(active_provider_names)
        orphaned_providers = list(all_provider_names - active_set)
        
        total_deleted = 0
        for provider_id in orphaned_providers:
            count = self.delete_all_statuses_for_provider(provider_id)
            total_deleted += count
        
        return {
            "deleted_count": total_deleted,
            "orphaned_providers": orphaned_providers
        }

    def reset_stale_downloading_statuses(
        self,
        *,
        stale_before: datetime,
        provider_names: Optional[List[str]] = None,
    ) -> int:
        """
        Reset stale downloading statuses back to pending.

        A status is considered stale when it is still marked as downloading
        and its queued_at timestamp is older than ``stale_before``.
        """
        if provider_names is not None and len(provider_names) == 0:
            return 0

        stmt = select(ProviderVersionStatus).where(
            ProviderVersionStatus.status == "downloading",
            ProviderVersionStatus.queued_at < stale_before,
        )

        if provider_names is not None:
            stmt = stmt.where(self._provider_match_clause_many(provider_names))

        stale_statuses = list(self.session.exec(stmt).all())
        if not stale_statuses:
            return 0

        reset_at = datetime.now(timezone.utc)
        for status in stale_statuses:
            status.status = "pending"
            status.queued_at = reset_at
            status.error_message = "Reset stale downloading status during startup cleanup"
            self.session.add(status)

        self.session.commit()
        return len(stale_statuses)
    
    # =========================================================================
    # IMAGE OPERATIONS
    # =========================================================================
    
    def get_images_for_version(self, version_id: int) -> List[ModelImage]:
        """Get all images for a version."""
        stmt = select(ModelImage).where(
            ModelImage.version_id == version_id
        ).order_by(ModelImage.sort_order)
        return list(self.session.exec(stmt).all())
    
    def get_primary_image_for_model(self, model_id: int) -> Optional[ModelImage]:
        """Get the first image from the default version."""
        default_version = self.get_default_version(model_id)
        if not default_version:
            return None
        
        stmt = select(ModelImage).where(
            ModelImage.version_id == default_version.id
        ).order_by(ModelImage.sort_order).limit(1)
        return self.session.exec(stmt).first()
    
    # =========================================================================
    # TAG OPERATIONS
    # =========================================================================
    
    def get_tags_for_model(self, model_id: int) -> List[str]:
        """Get all tags for a model."""
        stmt = select(ModelTag.tag).where(ModelTag.model_id == model_id)
        return list(self.session.exec(stmt).all())
    
    def search_by_tag(self, tag: str) -> List[ModelV2]:
        """Search models by tag."""
        stmt = select(ModelV2).join(
            ModelTag, ModelV2.id == ModelTag.model_id
        ).where(ModelTag.tag.ilike(f"%{tag}%"))
        return list(self.session.exec(stmt).all())
    
    # =========================================================================
    # SERIALIZATION
    # =========================================================================
    
    # =========================================================================
    # BULK LOADING (eliminates N+1 queries)
    # =========================================================================

    def _bulk_load_tags(self, model_ids: List[int]) -> Dict[int, List[str]]:
        """Load all tags for multiple models in one query."""
        if not model_ids:
            return {}
        stmt = select(ModelTag).where(ModelTag.model_id.in_(model_ids))
        result: Dict[int, List[str]] = {mid: [] for mid in model_ids}
        for tag in self.session.exec(stmt).all():
            result.setdefault(tag.model_id, []).append(tag.tag)
        return result

    def _bulk_load_versions(self, model_ids: List[int]) -> Dict[int, List[ModelVersion]]:
        """Load all versions for multiple models in one query."""
        if not model_ids:
            return {}
        stmt = select(ModelVersion).where(ModelVersion.model_id.in_(model_ids))
        result: Dict[int, List[ModelVersion]] = {mid: [] for mid in model_ids}
        for version in self.session.exec(stmt).all():
            result.setdefault(version.model_id, []).append(version)
        return result

    def _bulk_load_files(self, version_ids: List[int]) -> Dict[int, List[ModelFile]]:
        """Load all files for multiple versions in one query."""
        if not version_ids:
            return {}
        stmt = select(ModelFile).where(ModelFile.version_id.in_(version_ids))
        from collections import defaultdict
        result: Dict[int, List[ModelFile]] = defaultdict(list)
        for file in self.session.exec(stmt).all():
            result[file.version_id].append(file)
        return dict(result)

    def _bulk_load_images(self, version_ids: List[int]) -> Dict[int, List[ModelImage]]:
        """Load all images for multiple versions in one query, ordered by sort_order."""
        if not version_ids:
            return {}
        stmt = select(ModelImage).where(ModelImage.version_id.in_(version_ids)).order_by(ModelImage.sort_order)
        from collections import defaultdict
        result: Dict[int, List[ModelImage]] = defaultdict(list)
        for image in self.session.exec(stmt).all():
            result[image.version_id].append(image)
        return dict(result)

    def _bulk_load_provider_statuses_by_model(
        self, model_ids: List[int]
    ) -> Dict[int, Dict[str, Dict[str, Any]]]:
        """Load all provider statuses for multiple models in one query."""
        if not model_ids:
            return {}
        stmt = select(ProviderVersionStatus, ModelFile, ModelVersion).join(
            ModelFile, ProviderVersionStatus.file_id == ModelFile.id
        ).join(
            ModelVersion, ModelFile.version_id == ModelVersion.id
        ).where(ModelVersion.model_id.in_(model_ids))

        from collections import defaultdict
        result: Dict[int, Dict[str, Dict[str, Any]]] = {}
        for status, file, version in self.session.exec(stmt).all():
            model_id = version.model_id
            if model_id not in result:
                result[model_id] = {}
            provider_key = self._get_provider_key(status)
            if not provider_key:
                continue
            if provider_key not in result[model_id]:
                result[model_id][provider_key] = {
                    "status": status.status,
                    "files": [],
                    "total_size": 0,
                }
            result[model_id][provider_key]["files"].append({
                "file_id": file.id,
                "filename": file.storage_filename,
                "status": status.status,
                "size_bytes": status.size_bytes,
            })
            if status.size_bytes:
                result[model_id][provider_key]["total_size"] += status.size_bytes
        return result

    def model_to_dict(
        self,
        model: ModelV2,
        include_versions: bool = True,
        *,
        _tags_map: Optional[Dict[int, List[str]]] = None,
        _versions_map: Optional[Dict[int, List[ModelVersion]]] = None,
        _files_map: Optional[Dict[int, List[ModelFile]]] = None,
        _images_map: Optional[Dict[int, List[ModelImage]]] = None,
        _statuses_map: Optional[Dict[int, Dict[str, Dict[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        """Convert model to dictionary for API response.
        
        Accepts optional pre-loaded bulk data to avoid N+1 queries.
        """
        mid = model.id
        tags = _tags_map.get(mid, []) if _tags_map is not None else self.get_tags_for_model(mid)
        versions = _versions_map.get(mid, []) if _versions_map is not None else self.get_versions_for_model(mid)

        result = {
            "id": mid,
            "civitai_model_id": model.civitai_model_id,
            "name": model.name,
            "type": model.type,
            "directory": model.directory,
            "description": model.description,
            "nsfw": model.nsfw,
            "nsfw_level": model.nsfw_level,
            "creator": {
                "username": model.creator_username,
                "image": model.creator_image
            },
            "stats": {
                "downloads": model.stats_downloads,
                "thumbsUp": model.stats_thumbs_up,
                "thumbsDown": model.stats_thumbs_down,
                "comments": model.stats_comments
            },
            "source": model.source,
            "source_url": model.source_url,
            "tags": tags,
            "created_at": model.created_at.isoformat() if model.created_at else None,
            "updated_at": model.updated_at.isoformat() if model.updated_at else None
        }

        if include_versions:
            result["versions"] = [
                self._version_to_dict(v, _files_map=_files_map, _images_map=_images_map)
                for v in versions
            ]

        # Primary image: first image of the default version
        primary_image = None
        default_version = next((v for v in versions if v.is_default), versions[0] if versions else None)
        if default_version:
            version_images = (
                _images_map.get(default_version.id, [])
                if _images_map is not None
                else self.get_images_for_version(default_version.id)
            )
            if version_images:
                primary_image = version_images[0]
        if primary_image:
            result["preview_image"] = {
                "url": primary_image.url,
                "width": primary_image.width,
                "height": primary_image.height,
                "blurhash": primary_image.blurhash
            }

        # Provider statuses
        if _statuses_map is not None:
            result["provider_statuses"] = _statuses_map.get(mid, {})
        else:
            result["provider_statuses"] = self.get_provider_statuses_for_model(mid)

        return result

    def models_to_dict(
        self,
        models: List[ModelV2],
        include_versions: bool = True,
    ) -> List[Dict[str, Any]]:
        """Convert multiple models to dicts with bulk-loaded related data.
        
        Eliminates the N+1 query problem by loading all tags, versions,
        files, images, and provider statuses in 5 total queries regardless
        of how many models are passed in.
        """
        if not models:
            return []

        model_ids = [m.id for m in models]
        tags_map = self._bulk_load_tags(model_ids)
        versions_map = self._bulk_load_versions(model_ids)

        all_version_ids = [v.id for versions in versions_map.values() for v in versions]
        files_map = self._bulk_load_files(all_version_ids)
        images_map = self._bulk_load_images(all_version_ids)
        statuses_map = self._bulk_load_provider_statuses_by_model(model_ids)

        return [
            self.model_to_dict(
                m,
                include_versions=include_versions,
                _tags_map=tags_map,
                _versions_map=versions_map,
                _files_map=files_map,
                _images_map=images_map,
                _statuses_map=statuses_map,
            )
            for m in models
        ]

    def _version_to_dict(
        self,
        version: ModelVersion,
        *,
        _files_map: Optional[Dict[int, List[ModelFile]]] = None,
        _images_map: Optional[Dict[int, List[ModelImage]]] = None,
    ) -> Dict[str, Any]:
        """Convert version to dictionary, accepting optional pre-loaded data."""
        vid = version.id
        files = _files_map.get(vid, []) if _files_map is not None else self.get_files_for_version(vid)
        images = _images_map.get(vid, []) if _images_map is not None else self.get_images_for_version(vid)

        primary_file = next((f for f in files if f.is_primary), files[0] if files else None)

        return {
            "id": vid,
            "civitai_version_id": version.civitai_version_id,
            "name": version.name,
            "base_model": version.base_model,
            "base_model_type": version.base_model_type,
            "is_unet_only": is_unet_only_model(version.base_model),
            "description": version.description,
            "is_enabled": version.is_enabled,
            "is_default": version.is_default,
            "trained_words": json.loads(version.trained_words) if version.trained_words else [],
            "file": {
                "id": primary_file.id,
                "filename": primary_file.storage_filename,
                "size_kb": primary_file.size_kb,
                "hash": primary_file.hash_sha256
            } if primary_file else None,
            "images": [
                {
                    "url": img.url,
                    "width": img.width,
                    "height": img.height,
                    "blurhash": img.blurhash,
                    "type": img.type,
                    "nsfw_level": img.nsfw_level
                }
                for img in images
            ],
            "created_at": version.created_at.isoformat() if version.created_at else None
        }
    
    def get_grouped_by_directory(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get all models grouped by directory (bulk-loaded, no N+1)."""
        models = self.get_all_models()
        dicts = self.models_to_dict(models, include_versions=False)
        result: Dict[str, List[Dict[str, Any]]] = {}
        for d in dicts:
            directory = d.get("directory", "other")
            if directory not in result:
                result[directory] = []
            result[directory].append(d)
        return result
    
    def migrate_unet_only_models(self) -> Dict[str, Any]:
        """
        Migration function: Find UNET-only models incorrectly stored in 'checkpoints'
        and move them to 'unet' directory.
        
        This fixes models added before the UNET routing was implemented.
        
        Returns:
            Dict with migration results: {'migrated': [...], 'count': N}
        """
        from core.entities import is_unet_only_model
        
        # Find all Checkpoint type models in checkpoints directory
        stmt = select(ModelV2).where(
            and_(
                ModelV2.type == "Checkpoint",
                ModelV2.directory == "checkpoints"
            )
        )
        models = list(self.session.exec(stmt).all())
        
        migrated = []
        
        for model in models:
            # Get the default version to check base_model
            versions = self.get_versions_for_model(model.id)
            if not versions:
                continue
            
            # Check if any version is UNET-only
            for version in versions:
                if is_unet_only_model(version.base_model):
                    # This model should be in 'unet' directory
                    old_dir = model.directory
                    model.directory = "unet"
                    self.session.add(model)
                    
                    migrated.append({
                        "id": model.id,
                        "name": model.name,
                        "base_model": version.base_model,
                        "old_directory": old_dir,
                        "new_directory": "unet"
                    })
                    logger.info("migration_model_moved", model_name=model.name, old_directory=old_dir, new_directory="unet", base_model=version.base_model)
                    break  # Only need to find one UNET-only version
        
        if migrated:
            self.session.commit()
        
        logger.info("migration_complete", migrated_count=len(migrated))
        return {"migrated": migrated, "count": len(migrated)}

    def garbage_collect_auto_discovered(self) -> int:
        stmt = select(ModelV2).where(ModelV2.description.like("%Auto-discovered%"))
        models = self.session.exec(stmt).all()
        if not models:
            return 0
            
        model_ids = [m.id for m in models]
        statuses_map = self._bulk_load_provider_statuses_by_model(model_ids)
        
        deleted = 0
        for m in models:
            has_active = False
            provider_data = statuses_map.get(m.id, {})
            for p_key, p_info in provider_data.items():
                for f in p_info.get("files", []):
                    if f.get("status") in ["ready", "downloading", "pending"]:
                        has_active = True
                        break
                if has_active:
                    break
            
            if not has_active:
                self.delete_model(m.id)
                deleted += 1
        return deleted

    def cleanup_orphaned_models(self) -> int:
        """Remove models whose files have NO provider status records at all.
        
        This is a conservative cleanup: only delete models where every file has
        literally zero ProviderVersionStatus records. Models with any status
        (including failed) are preserved — they may be in progress or retriable.
        
        Models created in the last 24 hours are always skipped to avoid race
        conditions with download initialization.
        """
        stmt = select(ModelV2)
        models = self.session.exec(stmt).all()
        if not models:
            return 0
            
        model_ids = [m.id for m in models]
        statuses_map = self._bulk_load_provider_statuses_by_model(model_ids)
        
        deleted = 0
        from datetime import datetime, timezone, timedelta
        recent_threshold = datetime.now(timezone.utc) - timedelta(hours=24)
        for m in models:
            # Skip models created recently to avoid race conditions with initial download.
            # SQLite may store datetimes as naive, so normalize before comparing.
            if m.created_at:
                created = m.created_at
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created > recent_threshold:
                    continue
                
            has_viable = False
            if m.id in statuses_map and statuses_map[m.id]:
                has_viable = True
                
            if not has_viable:
                self.delete_model(m.id)
                deleted += 1
        return deleted

