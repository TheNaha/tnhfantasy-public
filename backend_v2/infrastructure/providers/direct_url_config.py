# Direct URL Provider Type Configuration
# This module contains all Direct URL-specific logic for bypassing serverless platforms.

from typing import Dict, Any

from .provider_registry import ProviderTypeConfig, ProviderRegistry, clean_registry_dict as clean_dict
from .base import ServerlessProvider, FileProxyProvider
from .ndjson import iter_ndjson_payloads
from .runtime import get_provider_worker_base_url
from infrastructure.http_client import get_http_client
from .provider_registry import HttpFileProxy
from typing import AsyncIterator, Optional, List

class DirectUrlProvider(ServerlessProvider):
    """
    Direct URL provider implementation.
    
    Uses CONTAINERIZED mode - calls HTTP endpoints on direct_url_worker container.
    """
    
    def __init__(self, provider_id: str, config: Dict[str, Any]):
        super().__init__(provider_id, config)
        
        # Container mode settings
        self.container_port = 8000
        self.container_name = f"comfy-provider-{provider_id}"
        
        # Worker URL (inside podman network)
        self.worker_url = get_provider_worker_base_url(provider_id, self.container_port)
        
        # File proxy
        self._file_proxy = HttpFileProxy(provider_id, config, self.worker_url)
        
        self.comfy_url = self.config.get("comfy_url", "http://localhost:8188")
    
    async def run_inference(self, workflow: Dict[str, Any]) -> AsyncIterator[Dict[str, Any]]:
        """
        Run ComfyUI inference via worker container.
        """
        from infrastructure.http_client import get_streaming_client
        
        url = f"{self.worker_url}/inference"
        
        async with get_streaming_client(timeout=600.0) as client:
            async with client.stream("POST", url, json={"workflow": workflow}) as response:
                if response.status_code != 200:
                    yield {"status": "error", "error": f"Worker returned {response.status_code}"}
                    return

                async for payload in iter_ndjson_payloads(
                    response.aiter_bytes(),
                    source=f"direct_url_provider:{self.provider_id}",
                ):
                    yield payload
    
    async def download_model(
        self,
        url: str,
        path: str,
        token: str = None,
        preview_url: str = None,
        metadata: Dict = None,
        info: Optional[Dict] = None
    ) -> Dict[str, Any]:
        client = get_http_client()
        endpoint = f"{self.worker_url}/download-model"
        payload = {
            "url": url,
            "path": path,
            "token": token,
            "preview_url": preview_url,
            "metadata": metadata,
            "info": info
        }
        
        response = await client.post(endpoint, json=payload)
        if response.status_code == 200:
            return response.json()
        return {"status": "error", "error": f"Download failed: {response.status_code}"}
    
    async def list_models(self, directory: str) -> List[Dict[str, Any]]:
        client = get_http_client()
        response = await client.post(f"{self.worker_url}/list-models", json={"directory": directory})
        if response.status_code == 200:
            data = response.json()
            return data.get("files", [])
        return []
    
    async def delete_model(self, path: str) -> bool:
        client = get_http_client()
        url = f"{self.worker_url}/delete-model"
        try:
            delete_response = await client.request("DELETE", url, json={"path": path})
        except Exception:
            delete_response = None

        if delete_response is not None and delete_response.status_code == 200:
            return True

        if delete_response is None or delete_response.status_code in {404, 405, 422}:
            fallback_response = await client.post(url, json={"path": path})
            return fallback_response.status_code == 200

        return False
    
    def get_file_proxy(self) -> FileProxyProvider:
        return self._file_proxy
    
    def get_provider_info(self) -> Dict[str, Any]:
        return {
            "id": self.provider_id,
            "type": self.provider_type,
            "mode": "containerized",
            "worker_url": self.worker_url,
            "comfy_url": self.comfy_url,
        }


def build_direct_url_env_vars(credentials: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, str]:
    """
    Build environment variables for Direct URL worker container.
    """
    env_vars: Dict[str, str] = {}

    # Core config
    env_vars["ENGINE"] = "direct_url"
    if config.get("id"):
        env_vars["PROVIDER_ID"] = config["id"]
    from config import settings
    env_vars["BACKEND_URL"] = settings.worker_backend_url

    if config.get("comfy_url"):
        env_vars["COMFYUI_URL"] = config["comfy_url"]

    return env_vars


# Direct URL provider type configuration
DIRECT_URL_PROVIDER_CONFIG = ProviderTypeConfig(
    type_name="direct_url",
    
    # Required credentials
    required_credentials=[],
    optional_credentials=[],
    
    # Required config
    required_config=["comfy_url"],
    optional_config=[],
    
    # Environment variable builder
    env_builder=build_direct_url_env_vars,
    
    # Worker image name
    worker_image="comfy-provider-image-worker",
    
    # Default port
    default_port=8000,
    client_class=DirectUrlProvider
)


# Auto-register Direct URL provider type on import
ProviderRegistry.register(DIRECT_URL_PROVIDER_CONFIG)
