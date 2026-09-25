# Anthropic Provider Type Configuration

from typing import Any

from .base import ServerlessProvider
from .llm_client_stubs import LLMClientGracefulStubMixin
from .provider_registry import ProviderRegistry, ProviderTypeConfig
from .runtime import get_provider_worker_base_url, provider_container_name


class AnthropicProvider(LLMClientGracefulStubMixin, ServerlessProvider):
    """
    Anthropic (Claude) LLM provider implementation.
    Routes text requests to the LLM worker container.
    """

    def __init__(self, provider_id: str, config: dict[str, Any]):
        super().__init__(provider_id, config)

        runtime = config.get("runtime_config") or {}
        self.container_port = int(runtime.get("port") or config.get("port") or 8000)
        self.container_name = provider_container_name(provider_id)
        self.worker_url = get_provider_worker_base_url(provider_id, self.container_port)

        self.api_key = self.config.get("api_key", "")

    def get_provider_info(self) -> dict[str, Any]:
        return {
            "id": self.provider_id,
            "type": self.provider_type,
            "mode": "containerized",
            "worker_url": self.worker_url,
        }

def build_anthropic_env_vars(credentials: dict[str, Any], config: dict[str, Any]) -> dict[str, str]:
    """
    Build environment variables for LLM worker container.
    """
    env_vars: dict[str, str] = {}

    env_vars["ENGINE"] = "anthropic"
    if config.get("id"):
        env_vars["PROVIDER_ID"] = config["id"]
    from config import get_worker_backend_url
    env_vars["BACKEND_URL"] = get_worker_backend_url()

    if credentials.get("api_key"):
        env_vars["ANTHROPIC_API_KEY"] = credentials["api_key"]

    return env_vars


ANTHROPIC_PROVIDER_CONFIG = ProviderTypeConfig(
    type_name="anthropic",

    required_credentials=[],
    optional_credentials=["api_key"],

    required_config=[],
    optional_config=[],

    env_builder=build_anthropic_env_vars,

    worker_image="comfy-provider-llm-worker",
    default_port=8000,
    client_class=AnthropicProvider
)

ProviderRegistry.register(ANTHROPIC_PROVIDER_CONFIG)
