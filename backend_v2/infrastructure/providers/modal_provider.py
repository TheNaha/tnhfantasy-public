# Modal provider implementation
from typing import Any

from infrastructure.http_client import get_http_client

from .base import FileProxyProvider, ServerlessProvider
from .provider_registry import HttpFileProxy
from .runtime import get_provider_worker_base_url, provider_container_name


class ModalProvider(ServerlessProvider):
    """
    Modal.com serverless provider implementation.
    
    Uses CONTAINERIZED mode - calls HTTP endpoints on image_worker container.
    """
    
    def __init__(self, provider_id: str, config: dict[str, Any]):
        super().__init__(provider_id, config)
        
        # Container mode settings
        runtime = config.get("runtime_config") or {}
        self.container_port = int(runtime.get("port") or config.get("port") or 8000)
        self.container_name = provider_container_name(provider_id)
        
        # Worker URL (inside podman network)
        self.worker_url = get_provider_worker_base_url(provider_id, self.container_port)
        
        # File proxy
        self._file_proxy = HttpFileProxy(provider_id, config, self.worker_url)
        
        # Credentials
        self.credentials = config.get("credentials", {})
        self.username = self.credentials.get("username", "")
    
    async def download_model(
        self,
        url: str,
        path: str,
        token: str = None,
        preview_url: str = None,
        metadata: dict = None,
        info: dict | None = None
    ) -> dict[str, Any]:
        """Download model via worker container."""
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
    
    async def list_models(self, directory: str) -> list[dict[str, Any]]:
        """List models via worker container."""
        client = get_http_client()
        response = await client.post(f"{self.worker_url}/list-models", json={"directory": directory})
        if response.status_code == 200:
            data = response.json()
            return data.get("files", [])
        return []
    
    async def delete_model(self, path: str) -> bool:
        """Delete model via worker container."""
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
    
    def get_provider_info(self) -> dict[str, Any]:
        return {
            "id": self.provider_id,
            "type": self.provider_type,
            "mode": "containerized",
            "worker_url": self.worker_url,
            "username": self.username,
        }
