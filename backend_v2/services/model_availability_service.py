# Model Availability Service - Check model availability across providers
"""
Service to check if required models are available on providers.
Used for pre-flight job validation and model-aware load balancing.
"""
from dataclasses import dataclass, field

from sqlalchemy import and_, or_
from sqlmodel import Session, select

from core.entities import ModelFile, ModelV2, ModelVersion, Provider, ProviderVersionStatus
from infrastructure.logging import model_logger
from infrastructure.repositories import ProviderRepository

logger = model_logger()


@dataclass
class AvailabilityResult:
    """Result of model availability check."""
    # Whether any provider has all required models
    valid: bool = False
    
    # Provider IDs that have ALL required models ready
    eligible_providers: list[str] = field(default_factory=list)
    
    # Missing models per provider: {provider_id: {directory: [filenames]}}
    missing_models: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    
    # Models that are missing on ALL providers (globally unavailable)
    global_missing: dict[str, list[str]] = field(default_factory=dict)
    
    # Whether downloads can be triggered (models exist in DB but not downloaded)
    can_trigger_download: bool = False
    
    # All required models for reference
    required_models: dict[str, list[str]] = field(default_factory=dict)


class ModelAvailabilityService:
    """
    Checks model availability across providers.
    
    Uses the ProviderVersionStatus table to determine which files
    are ready (downloaded) on which providers.
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.provider_repo = ProviderRepository(session)
    
    def check_availability(
        self,
        required_models: dict[str, list[str]]
    ) -> AvailabilityResult:
        """
        Check if required models are available on any provider.
        
        Args:
            required_models: Dict mapping directory to list of filenames
                            e.g., {"checkpoints": ["model.safetensors"], "loras": ["lora.safetensors"]}
        
        Returns:
            AvailabilityResult with eligible providers and missing models
        """
        result = AvailabilityResult(required_models=required_models)
        
        if not required_models:
            # No models required - all providers are eligible
            enabled_providers = self.provider_repo.get_enabled()
            result.valid = len(enabled_providers) > 0
            result.eligible_providers = [p.id for p in enabled_providers]
            return result
        
        # Get all enabled providers
        enabled_providers = self.provider_repo.get_enabled()
        if not enabled_providers:
            result.valid = False
            return result
        
        provider_ids = [p.id for p in enabled_providers]
        
        # Build a lookup: (directory, filename) -> {provider_id: status}
        file_provider_status = self._get_file_provider_status(required_models)
        
        # Check each provider for all required models
        for provider_id in provider_ids:
            missing_for_provider: dict[str, list[str]] = {}
            
            for directory, filenames in required_models.items():
                missing_files = []
                for filename in filenames:
                    # Check if this file is ready on this provider
                    file_status = file_provider_status.get((directory, filename), {})
                    provider_status = file_status.get(provider_id)
                    
                    if provider_status != "ready":
                        missing_files.append(filename)
                
                if missing_files:
                    missing_for_provider[directory] = missing_files
            
            if missing_for_provider:
                result.missing_models[provider_id] = missing_for_provider
            else:
                # This provider has all required models!
                result.eligible_providers.append(provider_id)
        
        # Find globally missing models (not ready on ANY provider)
        all_files_needed: set[str] = set()
        for filenames in required_models.values():
            all_files_needed.update(filenames)
        
        for directory, filenames in required_models.items():
            global_missing_files = []
            for filename in filenames:
                file_status = file_provider_status.get((directory, filename), {})
                # Check if ready on any provider
                ready_on_any = any(
                    status == "ready" 
                    for status in file_status.values()
                )
                if not ready_on_any:
                    global_missing_files.append(filename)
            
            if global_missing_files:
                result.global_missing[directory] = global_missing_files
        
        # Check if downloads can be triggered (models exist in DB)
        if result.global_missing:
            result.can_trigger_download = self._can_trigger_downloads(result.global_missing)
        
        result.valid = len(result.eligible_providers) > 0
        return result
    
    def _get_file_provider_status(
        self,
        required_models: dict[str, list[str]]
    ) -> dict[tuple[str, str], dict[str, str]]:
        """
        Get provider status for each required file.
        
        Returns: {(directory, filename): {provider_id: status}}
        """
        requested_pairs = {
            (directory, filename)
            for directory, filenames in required_models.items()
            for filename in filenames
        }
        
        if not requested_pairs:
            return {}

        result: dict[tuple[str, str], dict[str, str]] = {}

        file_filters = [
            and_(
                ModelV2.directory == directory,
                ModelFile.storage_filename == filename,
            )
            for directory, filename in requested_pairs
        ]

        stmt = select(ModelFile, ModelVersion, ModelV2).join(
            ModelVersion, ModelFile.version_id == ModelVersion.id
        ).join(
            ModelV2, ModelVersion.model_id == ModelV2.id
        ).where(
            ModelVersion.is_enabled == True,
            or_(*file_filters),
        )
        files = self.session.exec(stmt).all()

        matching_file_ids: list[int] = []
        file_id_to_key: dict[int, tuple[str, str]] = {}

        for file, _version, model in files:
            key = (model.directory, file.storage_filename)
            if key in requested_pairs:
                matching_file_ids.append(file.id)
                file_id_to_key[file.id] = key

        if not matching_file_ids:
            return result

        status_stmt = select(ProviderVersionStatus).where(
            ProviderVersionStatus.file_id.in_(matching_file_ids)
        )
        statuses = self.session.exec(status_stmt).all()

        for status in statuses:
            file_key = file_id_to_key.get(status.file_id)
            if file_key:
                result.setdefault(file_key, {})
                provider_key = status.provider_id
                if provider_key:
                    result[file_key][provider_key] = status.status
        
        return result
    
    def _can_trigger_downloads(
        self,
        global_missing: dict[str, list[str]]
    ) -> bool:
        """
        Check if missing models exist in DB (can be downloaded).
        
        Returns True if at least one missing model exists in the model library
        and just needs to be downloaded to providers.
        """
        file_filters = [
            and_(
                ModelV2.directory == directory,
                ModelFile.storage_filename == filename,
            )
            for directory, filenames in global_missing.items()
            for filename in filenames
        ]
        
        if not file_filters:
            return False
        
        stmt = select(ModelFile.id).join(
            ModelVersion, ModelFile.version_id == ModelVersion.id
        ).join(
            ModelV2, ModelVersion.model_id == ModelV2.id
        ).where(
            or_(*file_filters)
        ).limit(1)
        
        return self.session.exec(stmt).first() is not None
    
    def get_providers_with_models(
        self,
        required_models: dict[str, list[str]]
    ) -> list[str]:
        """
        Get list of provider IDs that have all required models.
        
        Convenience method for load balancer integration.
        
        Args:
            required_models: Dict mapping directory to list of filenames
            
        Returns:
            List of eligible provider IDs
        """
        result = self.check_availability(required_models)
        return result.eligible_providers
    
    def get_available_models(self, directory: str) -> list[str]:
        """
        List filenames of ready (downloaded) model files in *directory*
        across all enabled providers.

        Example:
            >>> service.get_available_models("checkpoints")
            ['animagine_xl_v31_v31_403131.safetensors', ...]

        Returns an empty list when no models are ready or the query fails.
        """
        try:
            rows = self.session.exec(
                select(ModelFile.storage_filename)
                .join(ModelVersion, ModelVersion.id == ModelFile.version_id)
                .join(ModelV2, ModelV2.id == ModelVersion.model_id)
                .join(
                    ProviderVersionStatus,
                    ProviderVersionStatus.file_id == ModelFile.id,
                )
                .join(Provider, Provider.id == ProviderVersionStatus.provider_id)
                .where(
                    ModelV2.directory == directory,
                    ModelVersion.is_enabled == True,  # noqa: E712
                    Provider.enabled == True,  # noqa: E712
                    ProviderVersionStatus.status == "ready",
                )
                .distinct()
            ).all()
            return [r for r in rows if r]
        except Exception as e:
            logger.warning("available_models_query_failed", directory=directory, error=str(e))
            return []

    def get_available_checkpoint(self, preferred: str | None = None) -> str | None:
        """Pick a checkpoint that is actually installed on an enabled provider.

        Returns *preferred* if it is present, otherwise the first ready
        checkpoint.  Returns ``None`` when no checkpoints are installed.
        """
        ready = self.get_available_models("checkpoints")
        if not ready:
            return None
        if preferred and preferred in ready:
            return preferred
        return ready[0]

    def get_available_lora(self, preferred: str | None = None) -> str | None:
        """Pick a LoRA that is actually installed on an enabled provider.

        Returns *preferred* if present, otherwise ``None`` (LoRAs are
        optional — we never silently swap one for another).
        """
        if not preferred:
            return None
        ready = self.get_available_models("loras")
        return preferred if preferred in ready else None

    def get_missing_models_for_provider(
        self,
        provider_id: str,
        required_models: dict[str, list[str]]
    ) -> dict[str, list[str]]:
        """
        Get missing models for a specific provider.
        
        Args:
            provider_id: Provider ID to check
            required_models: Dict mapping directory to list of filenames
            
        Returns:
            Dict of {directory: [missing_filenames]} for this provider
        """
        result = self.check_availability(required_models)
        return result.missing_models.get(provider_id, {})
