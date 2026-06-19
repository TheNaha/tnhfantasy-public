# Modal provider implementation
import os
from typing import Dict, List, AsyncIterator, Any, Optional

from .base import ServerlessProvider, FileProxyProvider
from .ndjson import iter_ndjson_payloads
from .runtime import get_provider_worker_base_url
from .provider_registry import HttpFileProxy
from infrastructure.http_client import get_http_client


class ModalProvider(ServerlessProvider):
    """
    Modal.com serverless provider implementation.
    
    Uses CONTAINERIZED mode - calls HTTP endpoints on modal_worker container.
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
        
        # Credentials
        self.credentials = config.get("credentials", {})
        self.username = self.credentials.get("username", "")
    
    async def run_inference(self, workflow: Dict[str, Any]) -> AsyncIterator[Dict[str, Any]]:
        """
        Run ComfyUI inference via worker container.
        Streams progress updates.
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
                    source=f"modal_provider:{self.provider_id}",
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
    
    async def list_models(self, directory: str) -> List[Dict[str, Any]]:
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
        response = await client.delete(url, json={"path": path})
        return response.status_code == 200
    
    def get_file_proxy(self) -> FileProxyProvider:
        return self._file_proxy
    
    def get_provider_info(self) -> Dict[str, Any]:
        return {
            "id": self.provider_id,
            "type": self.provider_type,
            "mode": "containerized",
            "worker_url": self.worker_url,
            "username": self.username,
        }
