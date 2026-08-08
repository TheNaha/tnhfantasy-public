# OpenAI Compat Provider Type Configuration

from collections.abc import AsyncIterator
from typing import Any

from .base import ServerlessProvider
from .ndjson import iter_ndjson_payloads
from .provider_registry import ProviderRegistry, ProviderTypeConfig
from .runtime import get_provider_worker_base_url, provider_container_name


class OpenAICompatProvider(ServerlessProvider):
    """
    OpenAI-compatible LLM provider implementation.
    Routes text requests to the LLM worker container.
    """
    
    def __init__(self, provider_id: str, config: dict[str, Any]):
        super().__init__(provider_id, config)
        
        self.container_port = 8000
        self.container_name = provider_container_name(provider_id)
        self.worker_url = get_provider_worker_base_url(provider_id, self.container_port)
        
        self.api_base = self.config.get("api_base", "http://localhost:11434/v1")
        self.api_key = self.config.get("api_key", "")
    
    async def run_inference(self, workflow: dict[str, Any], job_id: str = "", timeout_seconds: int = 180) -> AsyncIterator[dict[str, Any]]:
        """
        Run LLM generation via worker container.
        """
        from infrastructure.http_client import get_streaming_client
        
        url = f"{self.worker_url}/inference"
        
        async with get_streaming_client(timeout=timeout_seconds) as client:
            async with client.stream(
                "POST",
                url,
                json={
                    "workflow": workflow,
                    "job_id": job_id,
                    "timeout_seconds": timeout_seconds,
                },
            ) as response:
                if response.status_code != 200:
                    yield {"status": "error", "error": f"Worker returned {response.status_code}"}
                    return

                async for payload in iter_ndjson_payloads(
                    response.aiter_bytes(),
                    source=f"openai_compat_provider:{self.provider_id}",
                ):
                    yield payload
    
    def get_provider_info(self) -> dict[str, Any]:
        return {
            "id": self.provider_id,
            "type": self.provider_type,
            "mode": "containerized",
            "worker_url": self.worker_url,
            "api_base": self.api_base,
        }

def build_openai_compat_env_vars(credentials: dict[str, Any], config: dict[str, Any]) -> dict[str, str]:
    """
    Build environment variables for LLM worker container.
    """
    env_vars: dict[str, str] = {}

    env_vars["ENGINE"] = "openai_compat"
    if config.get("id"):
        env_vars["PROVIDER_ID"] = config["id"]
    from config import settings
    env_vars["BACKEND_URL"] = settings.worker_backend_url

    if config.get("api_base"):
        env_vars["OPENAI_API_BASE"] = config["api_base"]
    if credentials.get("api_key"):
        env_vars["OPENAI_API_KEY"] = credentials["api_key"]

    return env_vars


OPENAI_COMPAT_PROVIDER_CONFIG = ProviderTypeConfig(
    type_name="openai_compat",
    
    required_credentials=[],
    optional_credentials=["api_key"],
    
    required_config=["api_base"],
    optional_config=[],
    
    env_builder=build_openai_compat_env_vars,
    
    worker_image="comfy-provider-llm-worker",
    default_port=8000,
    client_class=OpenAICompatProvider
)

ProviderRegistry.register(OPENAI_COMPAT_PROVIDER_CONFIG)
