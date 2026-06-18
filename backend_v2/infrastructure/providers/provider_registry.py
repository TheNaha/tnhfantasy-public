# Provider Registry - Type-agnostic provider configuration system
# This module abstracts provider-specific logic from the core backend

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Type, Callable

from infrastructure.logging import provider_logger

logger = provider_logger()


@dataclass
class ProviderTypeConfig:
    """
    Configuration schema for a provider type.
    Each provider type (modal, beam, runpod, etc.) registers one of these.
    """
    type_name: str
    
    # Credential fields
    required_credentials: List[str] = field(default_factory=list)
    optional_credentials: List[str] = field(default_factory=list)
    
    # Config fields
    required_config: List[str] = field(default_factory=list)
    optional_config: List[str] = field(default_factory=list)
    
    # Environment variable builder function
    # Signature: (credentials: Dict, config: Dict) -> Dict[str, str]
    env_builder: Optional[Callable[[Dict, Dict], Dict[str, str]]] = None
    
    # Worker image name for this provider type
    worker_image: str = "comfy-provider"
    
    # Default port for worker container
    default_port: int = 8000
    
    # The ServerlessProvider class for API interactions
    client_class: Optional[Type['ServerlessProvider']] = None
    
    def build_env_vars(self, credentials: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, str]:
        """
        Build container environment variables from credentials and config.
        
        Args:
            credentials: Provider credentials dict
            config: Provider config dict
            
        Returns:
            Environment variables dict for container
        """
        if self.env_builder:
            return self.env_builder(credentials, config)
        return {}
    
    def validate_credentials(self, credentials: Dict[str, Any]) -> List[str]:
        """
        Validate that required credentials are present.
        
        Returns:
            List of missing required credential fields
        """
        missing = []
        for field_name in self.required_credentials:
            if not credentials.get(field_name):
                missing.append(field_name)
        return missing
    
    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        """
        Validate that required config fields are present.
        
        Returns:
            List of missing required config fields
        """
        missing = []
        for field_name in self.required_config:
            if not config.get(field_name):
                missing.append(field_name)
        return missing


class ProviderRegistry:
    """
    Registry of available provider types.
    
    Provider types register themselves on import, making the system extensible.
    The backend uses this registry to handle provider-specific logic without
    knowing about specific providers.
    
    Usage:
        # Registration (in modal_config.py or beam_config.py)
        ProviderRegistry.register(MODAL_PROVIDER_CONFIG)
        
        # Usage (in main.py or container_manager.py)
        env_vars = ProviderRegistry.build_container_env(provider)
    """
    _types: Dict[str, ProviderTypeConfig] = {}
    
    @classmethod
    def register(cls, config: ProviderTypeConfig) -> None:
        """Register a provider type configuration."""
        cls._types[config.type_name] = config
        logger.info("provider_type_registered", type_name=config.type_name)
    
    @classmethod
    def get(cls, type_name: str) -> Optional[ProviderTypeConfig]:
        """Get configuration for a provider type."""
        return cls._types.get(type_name)
    
    @classmethod
    def get_all(cls) -> Dict[str, ProviderTypeConfig]:
        """Get all registered provider types."""
        return cls._types.copy()
    
    @classmethod
    def is_registered(cls, type_name: str) -> bool:
        """Check if a provider type is registered."""
        return type_name in cls._types
    
    @classmethod
    def build_container_env(cls, provider: Any) -> Dict[str, str]:
        """
        Build container environment variables for a provider.
        
        This is the main abstraction point - the backend calls this method
        without knowing what type of provider it is.
        
        Args:
            provider: Provider entity (with type, credentials, config attributes)
            
        Returns:
            Environment variables dict for the provider's container
        """
        type_config = cls.get(provider.type)
        if not type_config:
            logger.warning("unknown_provider_type", provider_type=provider.type)
            return {}
        
        credentials = provider.credentials or {}
        config = provider.config or {}
        
        return type_config.build_env_vars(credentials, config)
    
    @classmethod
    def validate_provider(cls, provider_type: str, credentials: Dict, config: Dict) -> Dict[str, List[str]]:
        """
        Validate a provider's credentials and config.
        
        Returns:
            Dict with 'credentials' and 'config' keys, each containing list of missing fields
        """
        type_config = cls.get(provider_type)
        if not type_config:
            return {"error": [f"Unknown provider type: {provider_type}"]}
        
        return {
            "credentials": type_config.validate_credentials(credentials),
            "config": type_config.validate_config(config)
        }
    
    @classmethod
    def get_worker_image(cls, provider_type: str) -> str:
        """Get the worker image name for a provider type."""
        type_config = cls.get(provider_type)
        if type_config:
            worker_image = type_config.worker_image
            if worker_image.endswith(":latest"):
                return worker_image
            return f"{worker_image}:latest"
        return f"comfy-provider-{provider_type}:latest"
    
    @classmethod
    def get_default_port(cls, provider_type: str) -> int:
        """Get the default worker port for a provider type."""
        type_config = cls.get(provider_type)
        return type_config.default_port if type_config else 8000
