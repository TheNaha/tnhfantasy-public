from typing import Any

from infrastructure.http_client import get_http_client

from .direct_url_config import DirectUrlProvider
from .provider_registry import ProviderRegistry, ProviderTypeConfig


class RemoteComfyProvider(DirectUrlProvider):
    def __init__(self, provider_id: str, config: dict[str, Any]):
        super().__init__(provider_id, config)
        self.comfy_url = self.config.get("comfy_url", "")
        self.remote_agent_url = self.config.get("remote_agent_url", "")

    def get_provider_info(self) -> dict[str, Any]:
        return {
            "id": self.provider_id,
            "type": self.provider_type,
            "mode": "remote_agent",
            "worker_url": self.worker_url,
            "comfy_url": self.comfy_url,
            "remote_agent_url": self.remote_agent_url,
        }


def build_remote_comfy_env_vars(credentials: dict[str, Any], config: dict[str, Any]) -> dict[str, str]:
    from config import get_worker_backend_url

    env_vars = {
        "ENGINE": "remote_comfy",
        "BACKEND_URL": get_worker_backend_url(),
    }
    if config.get("id"):
        env_vars["PROVIDER_ID"] = config["id"]
    if config.get("comfy_url"):
        env_vars["COMFYUI_URL"] = config["comfy_url"]
    comfy_api_key = credentials.get("comfyui_api_key") or config.get("comfyui_api_key")
    if comfy_api_key:
        env_vars["COMFYUI_API_KEY"] = comfy_api_key
    if config.get("remote_agent_url"):
        env_vars["REMOTE_AGENT_URL"] = config["remote_agent_url"]
    token = credentials.get("remote_agent_token") or config.get("remote_agent_token")
    if token:
        env_vars["REMOTE_AGENT_TOKEN"] = token
    for key in ("hf_token", "civitai_token"):
        value = credentials.get(key)
        if value:
            env_vars[key.upper()] = value
    return env_vars


REMOTE_COMFY_PROVIDER_CONFIG = ProviderTypeConfig(
    type_name="remote_comfy",
    required_credentials=[],
    optional_credentials=["remote_agent_token", "hf_token", "civitai_token"],
    required_config=["comfy_url", "remote_agent_url"],
    optional_config=[],
    env_builder=build_remote_comfy_env_vars,
    worker_image="comfy-provider-image-worker",
    default_port=8000,
    client_class=RemoteComfyProvider,
)

ProviderRegistry.register(REMOTE_COMFY_PROVIDER_CONFIG)
