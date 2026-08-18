# Google (Gemini) Provider Type Configuration

from typing import Any

from .base import ServerlessProvider
from .llm_client_stubs import LLMClientGracefulStubMixin
from .provider_registry import ProviderRegistry, ProviderTypeConfig
from .runtime import get_provider_worker_base_url, provider_container_name


class GoogleProvider(LLMClientGracefulStubMixin, ServerlessProvider):
    """
    Google Gemini LLM provider implementation.
    Routes text requests to the LLM worker container.
    """

    def __init__(self, provider_id: str, config: dict[str, Any]):
        super().__init__(provider_id, config)

        self.container_port = 8000
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

def build_google_env_vars(credentials: dict[str, Any], config: dict[str, Any]) -> dict[str, str]:
    """
    Build environment variables for LLM worker container.
    """
    env_vars: dict[str, str] = {}

    env_vars["ENGINE"] = "google"
    if config.get("id"):
        env_vars["PROVIDER_ID"] = config["id"]
    from config import settings
    env_vars["BACKEND_URL"] = settings.worker_backend_url

    if credentials.get("api_key"):
        env_vars["GOOGLE_API_KEY"] = credentials["api_key"]

    return env_vars


GOOGLE_PROVIDER_CONFIG = ProviderTypeConfig(
    type_name="google",

    required_credentials=[],
    optional_credentials=["api_key"],

    required_config=[],
    optional_config=[],

    env_builder=build_google_env_vars,

    worker_image="comfy-provider-llm-worker",
    default_port=8000,
    client_class=GoogleProvider
)

ProviderRegistry.register(GOOGLE_PROVIDER_CONFIG)

# 'gemini' is a legacy/UI-facing alias for the Google provider.
GEMINI_ALIAS_CONFIG = ProviderTypeConfig(
    type_name="gemini",

    required_credentials=[],
    optional_credentials=["api_key"],

    required_config=[],
    optional_config=[],

    env_builder=build_google_env_vars,

    worker_image="comfy-provider-llm-worker",
    default_port=8000,
    client_class=GoogleProvider
)

ProviderRegistry.register(GEMINI_ALIAS_CONFIG)
