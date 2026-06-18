# Provider implementations
from .base import ServerlessProvider, FileProxyProvider
from .modal_provider import ModalProvider, ModalFileProxy
from .beam_provider import BeamProvider, BeamFileProxy
from .provider_registry import ProviderRegistry, ProviderTypeConfig
from .runtime import get_provider_worker_base_url

# Import provider configs to trigger auto-registration
from . import modal_config  # noqa: F401 - Registers Modal provider type
from . import beam_config   # noqa: F401 - Registers Beam provider type

def create_provider_client(provider_id: str, config: dict):
    provider_type = (config or {}).get("type")
    
    # Lookup via ProviderRegistry
    type_config = ProviderRegistry.get_type_config(provider_type)
    if type_config and type_config.client_class:
        return type_config.client_class(provider_id, config)
        
    raise ValueError(f"Unsupported provider type or missing client_class: {provider_type}")

__all__ = [
    "ServerlessProvider",
    "FileProxyProvider",
    "ModalProvider",
    "ModalFileProxy",
    "BeamProvider",
    "BeamFileProxy",
    "create_provider_client",
    "get_provider_worker_base_url",
    "ProviderRegistry",
    "ProviderTypeConfig",
]
