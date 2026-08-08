# Provider implementations
from .base import FileProxyProvider, ServerlessProvider
from .beam_provider import BeamProvider
from .modal_provider import ModalProvider
from .provider_registry import (
    HttpFileProxy,
    ProviderRegistry,
    ProviderTypeConfig,
    clean_registry_dict,
)

clean_dict = clean_registry_dict  # backward compat alias
# Import provider configs to trigger auto-registration
from . import (
    beam_config,  # noqa: F401 - Registers Beam provider type
    direct_url_config,  # noqa: F401 - Registers Direct URL provider type
    modal_config,  # noqa: F401 - Registers Modal provider type
    modal_llm_config,  # noqa: F401 - Registers Modal LLM provider type
    openai_compat_config,  # noqa: F401 - Registers OpenAI Compat provider type
)
from .runtime import get_provider_worker_base_url


def create_provider_client(provider_id: str, config: dict):
    provider_type = (config or {}).get("type")
    
    # Lookup via ProviderRegistry
    type_config = ProviderRegistry.get(provider_type)
    if type_config and type_config.client_class:
        return type_config.client_class(provider_id, config)
        
    raise ValueError(f"Unsupported provider type or missing client_class: {provider_type}")

__all__ = [
    "BeamProvider",
    "FileProxyProvider",
    "HttpFileProxy",
    "ModalProvider",
    "ProviderRegistry",
    "ProviderTypeConfig",
    "ServerlessProvider",
    "clean_dict",
    "clean_registry_dict",
    "create_provider_client",
    "get_provider_worker_base_url",
]
