# Provider implementations
from .base import ServerlessProvider, FileProxyProvider
from .modal_provider import ModalProvider, ModalFileProxy
from .beam_provider import BeamProvider, BeamFileProxy
from .provider_registry import ProviderRegistry, ProviderTypeConfig

# Import provider configs to trigger auto-registration
from . import modal_config  # noqa: F401 - Registers Modal provider type
from . import beam_config   # noqa: F401 - Registers Beam provider type


def create_provider_client(provider_id: str, config: dict):
    provider_type = (config or {}).get("type")
    if provider_type == "modal":
        return ModalProvider(provider_id, config)
    if provider_type == "beam":
        return BeamProvider(provider_id, config)
    raise ValueError(f"Unsupported provider type: {provider_type}")

__all__ = [
    "ServerlessProvider",
    "FileProxyProvider",
    "ModalProvider",
    "ModalFileProxy",
    "BeamProvider",
    "BeamFileProxy",
    "create_provider_client",
    "ProviderRegistry",
    "ProviderTypeConfig",
]
