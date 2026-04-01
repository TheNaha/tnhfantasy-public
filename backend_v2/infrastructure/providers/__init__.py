# Provider implementations
from .base import ServerlessProvider, FileProxyProvider
from .modal_provider import ModalProvider, ModalFileProxy
from .beam_provider import BeamProvider, BeamFileProxy
from .provider_registry import ProviderRegistry, ProviderTypeConfig
from .runtime import get_provider_worker_base_url

# Import provider configs to trigger auto-registration
from . import modal_config  # noqa: F401 - Registers Modal provider type
from . import beam_config   # noqa: F401 - Registers Beam provider type

_PROVIDER_CLIENTS = {
    "modal": ModalProvider,
    "beam": BeamProvider,
}


def create_provider_client(provider_id: str, config: dict):
    provider_type = (config or {}).get("type")
    provider_class = _PROVIDER_CLIENTS.get(provider_type)
    if provider_class:
        return provider_class(provider_id, config)
    raise ValueError(f"Unsupported provider type: {provider_type}")

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
