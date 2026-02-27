# Model Availability Service - Check model availability across providers
"""
Service to check if required models are available on providers.
Used for pre-flight job validation and model-aware load balancing.
"""
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field
from sqlmodel import Session, select

from core.entities_v2 import ModelFile, ModelVersion, ModelV2, ProviderVersionStatus
from core.entities import Provider
from infrastructure.repositories import ProviderRepository
from infrastructure.logging import model_logger

logger = model_logger()


@dataclass
class AvailabilityResult:
    """Result of model availability check."""
    # Whether any provider has all required models
    valid: bool = False
    
    # Provider IDs that have ALL required models ready
    eligible_providers: List[str] = field(default_factory=list)
    
    # Missing models per provider: {provider_id: {directory: [filenames]}}
    missing_models: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)
    
    # Models that are missing on ALL providers (globally unavailable)
    global_missing: Dict[str, List[str]] = field(default_factory=dict)
    
    # Whether downloads can be triggered (models exist in DB but not downloaded)
    can_trigger_download: bool = False
    
    # All required models for reference
    required_models: Dict[str, List[str]] = field(default_factory=dict)


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
        required_models: Dict[str, List[str]]
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
        
        # Build a lookup: filename -> {provider_id: status}
        file_provider_status = self._get_file_provider_status(required_models)
        
        # Check each provider for all required models
        for provider_id in provider_ids:
            missing_for_provider: Dict[str, List[str]] = {}
            
            for directory, filenames in required_models.items():
                missing_files = []
                for filename in filenames:
                    # Check if this file is ready on this provider
                    file_status = file_provider_status.get(filename, {})
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
        all_files_needed: Set[str] = set()
        for filenames in required_models.values():
            all_files_needed.update(filenames)
        
        for directory, filenames in required_models.items():
            global_missing_files = []
            for filename in filenames:
                file_status = file_provider_status.get(filename, {})
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
        required_models: Dict[str, List[str]]
    ) -> Dict[str, Dict[str, str]]:
        """
        Get provider status for each required file.
        
        Returns: {filename: {provider_id: status}}
        """
        # Collect all filenames to look up
        all_filenames: Set[str] = set()
        for filenames in required_models.values():
            all_filenames.update(filenames)
        
        if not all_filenames:
            return {}
        
        # Query to find files by storage_filename
        # Join through the chain: ModelFile -> ModelVersion -> ModelV2 for directory
        # Then join ProviderVersionStatus for status per provider
        result: Dict[str, Dict[str, str]] = {}
        
        # First, get file IDs for our filenames
        stmt = select(ModelFile).where(
            ModelFile.storage_filename.in_(all_filenames)
        )
        files = self.session.exec(stmt).all()
        
        if not files:
            return result
        
        file_id_to_name = {f.id: f.storage_filename for f in files}
        file_ids = list(file_id_to_name.keys())
        
        # Now get provider statuses for these files
        status_stmt = select(ProviderVersionStatus).where(
            ProviderVersionStatus.file_id.in_(file_ids)
        )
        statuses = self.session.exec(status_stmt).all()
        
        # Build the result dict
        for status in statuses:
            filename = file_id_to_name.get(status.file_id)
            if filename:
                if filename not in result:
                    result[filename] = {}
                result[filename][status.provider_name] = status.status
        
        return result
    
    def _can_trigger_downloads(
        self,
        global_missing: Dict[str, List[str]]
    ) -> bool:
        """
        Check if missing models exist in DB (can be downloaded).
        
        Returns True if at least one missing model exists in the model library
        and just needs to be downloaded to providers.
        """
        for directory, filenames in global_missing.items():
            for filename in filenames:
                # Check if file exists in ModelFile table
                stmt = select(ModelFile).where(
                    ModelFile.storage_filename == filename
                )
                file = self.session.exec(stmt).first()
                if file:
                    return True
        return False
    
    def get_providers_with_models(
        self,
        required_models: Dict[str, List[str]]
    ) -> List[str]:
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
    
    def get_missing_models_for_provider(
        self,
        provider_id: str,
        required_models: Dict[str, List[str]]
    ) -> Dict[str, List[str]]:
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
