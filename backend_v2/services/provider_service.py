# Provider Service - Business logic for provider management
from typing import Dict, Any, List, Optional

from sqlmodel import Session

from core.entities import Provider, LoadBalancingConfig
from core.events import event_bus, Event, EventType, emit_provider_event
from core.exceptions import NotFoundError, ProviderError, ValidationError
from infrastructure.repositories import ProviderRepository, LoadBalancingRepository
from infrastructure.logging import provider_logger

logger = provider_logger()


class ProviderService:
    """
    Handles provider lifecycle and configuration.
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.repo = ProviderRepository(session)
        self.lb_repo = LoadBalancingRepository(session)
    
    async def create_provider(self, provider_data: Dict[str, Any]) -> Provider:
        """
        Create a new provider.
        
        Args:
            provider_data: Provider configuration
            
        Returns:
            Created provider
        """
        # Validate required fields
        if "id" not in provider_data:
            raise ValidationError("Provider ID is required", field="id")
        if "type" not in provider_data:
            raise ValidationError("Provider type is required", field="type")
        
        # Check if already exists
        if self.repo.exists(provider_data["id"]):
            raise ValidationError(f"Provider '{provider_data['id']}' already exists", field="id")
        
        provider = self.repo.create(provider_data)
        
        logger.info("provider_created", provider_id=provider.id, type=provider.type)
        await emit_provider_event(
            EventType.PROVIDER_STATUS, 
            provider.id, 
            {"status": "created", "enabled": provider.enabled}
        )
        
        return provider
    
    async def get_provider(self, provider_id: str) -> Provider:
        """Get a provider by ID."""
        provider = self.repo.get(provider_id)
        if not provider:
            logger.warning("provider_not_found", provider_id=provider_id)
            raise NotFoundError("Provider", provider_id)
        return provider
    
    async def list_providers(self) -> List[Dict[str, Any]]:
        """List all providers with their info."""
        providers = self.repo.get_all()
        return [self._provider_to_dict(p) for p in providers]
    
    def get_enabled_providers(self) -> List[Provider]:
        """Get all enabled providers."""
        return self.repo.get_enabled()
    
    async def update_provider(self, provider_id: str, updates: Dict[str, Any]) -> Provider:
        """
        Update a provider.
        
        Args:
            provider_id: Provider ID
            updates: Fields to update
            
        Returns:
            Updated provider
        """
        provider = self.repo.update(provider_id, updates)
        if not provider:
            logger.warning("provider_update_not_found", provider_id=provider_id)
            raise NotFoundError("Provider", provider_id)
        
        logger.info("provider_updated", provider_id=provider_id)
        
        await emit_provider_event(
            EventType.PROVIDER_STATUS,
            provider_id,
            {"status": "updated", "enabled": provider.enabled}
        )
        
        return provider
    
    async def delete_provider(self, provider_id: str) -> bool:
        """Delete a provider and cascade delete its status entries."""
        from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2
        
        # First, cascade delete all ProviderVersionStatus entries for this provider
        model_repo = ModelRepositoryV2(self.session)
        deleted_count = model_repo.delete_all_statuses_for_provider(provider_id)
        if deleted_count > 0:
            logger.info("provider_cascade_delete", provider_id=provider_id, statuses_deleted=deleted_count)
        
        # Then delete the provider itself
        success = self.repo.delete(provider_id)
        if not success:
            logger.warning("provider_delete_not_found", provider_id=provider_id)
            raise NotFoundError("Provider", provider_id)
        
        logger.info("provider_deleted", provider_id=provider_id, statuses_cleaned=deleted_count)
        
        await emit_provider_event(
            EventType.PROVIDER_STATUS,
            provider_id,
            {"status": "deleted", "statuses_cleaned": deleted_count}
        )
        
        return True
    
    def get_load_balancing_config(self) -> LoadBalancingConfig:
        """Get load balancing configuration."""
        return self.lb_repo.get()
    
    async def update_load_balancing_config(self, **updates) -> LoadBalancingConfig:
        """Update load balancing configuration."""
        return self.lb_repo.update(**updates)
    
    def _provider_to_dict(self, provider: Provider) -> Dict[str, Any]:
        """Convert provider to dictionary for API responses."""
        return {
            "id": provider.id,
            "type": provider.type,
            "enabled": provider.enabled,
            "priority": provider.priority,
            "credentials": provider.credentials,
            "config": provider.config,
            "container_config": provider.container_config,
        }
    
    def get_model_cache(self) -> Dict[str, Any]:
        """Get all model metadata cache for reconciliation."""
        from services.model_service import ModelService
        model_service = ModelService(self.session)
        return model_service.get_full_cache()
    
    def get_model_cache_for_directory(self, directory: str) -> List[Dict[str, Any]]:
        """Get model cache for a specific directory."""
        from services.model_service import ModelService
        model_service = ModelService(self.session)
        # get_full_cache returns {directory: [models]}
        cache = model_service.get_full_cache()
        return cache.get(directory, [])
    
    def get_load_balancer_stats(self) -> Dict[str, Any]:
        """Get load balancer statistics."""
        from services.load_balancer import LoadBalancer
        load_balancer = LoadBalancer(self.session, strategy="round-robin")
        return load_balancer.get_stats()

