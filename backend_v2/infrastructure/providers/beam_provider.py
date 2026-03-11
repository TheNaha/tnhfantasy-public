# Beam.cloud provider implementation
import os
import json
import urllib.parse
from typing import Dict, List, AsyncIterator, Any, Optional

from .base import ServerlessProvider, FileProxyProvider
from infrastructure.http_client import get_http_client


class BeamFileProxy(FileProxyProvider):
    """File proxy for Beam - uses HTTP calls to worker container."""
    
    def __init__(self, provider_id: str, config: Dict[str, Any], base_url: str):
        super().__init__(provider_id, config)
        self.base_url = base_url.rstrip("/")
    
    async def get_file(self, path: str) -> bytes:
        """Get file from Beam via worker container."""
        client = get_http_client()
        encoded_path = urllib.parse.quote(path, safe='')
        url = f"{self.base_url}/file-proxy?path={encoded_path}"
        response = await client.get(url)
        if response.status_code == 200:
            return response.content
        raise Exception(f"Failed to get file: {response.status_code}")
    
    async def delete_file(self, path: str) -> bool:
        """Delete file from Beam volume."""
        client = get_http_client()
        encoded_path = urllib.parse.quote(path, safe='')
        url = f"{self.base_url}/file-proxy?path={encoded_path}"
        response = await client.delete(url)
        return response.status_code == 200
    
    def get_proxy_url(self) -> str:
        return self.base_url


class BeamProvider(ServerlessProvider):
    """
    Beam.cloud serverless provider implementation.
    
    Uses CONTAINERIZED mode - calls HTTP endpoints on beam_worker container.
    """
    
    def __init__(self, provider_id: str, config: Dict[str, Any]):
        super().__init__(provider_id, config)
        
        # Container mode settings
        container_config = config.get("container_config", {})
        self.container_port = container_config.get("port", 8004)  # Default 8004 to avoid Modal conflicts
        self.container_name = f"beam-worker-{provider_id}"
        
        # Worker URL (inside podman network)
        self.worker_url = f"http://{self.container_name}:{self.container_port}"
        
        # File proxy
        self._file_proxy = BeamFileProxy(provider_id, config, self.worker_url)
        
        # Credentials
        self.credentials = config.get("credentials", {})
        self.api_key = self.credentials.get("api_key", "")
        
        # App config
        self.app_config = config.get("config", {})
        self.gpu_type = self.app_config.get("gpu_type", "RTX4090")
    
    async def run_inference(self, workflow: Dict[str, Any]) -> AsyncIterator[Dict[str, Any]]:
        """
        Run ComfyUI inference via worker container.
        Streams progress updates.
        """
        from infrastructure.http_client import get_streaming_client
        
        url = f"{self.worker_url}/run"
        
        async with get_streaming_client(timeout=600.0) as client:
            async with client.stream("POST", url, json={"workflow": workflow}) as response:
                if response.status_code != 200:
                    yield {"status": "error", "error": f"Worker returned {response.status_code}"}
                    return
                
                # Read streaming NDJSON response
                buffer = ""
                async for chunk in response.aiter_bytes():
                    buffer += chunk.decode()
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        if line.strip():
                            try:
                                data = json.loads(line)
                                yield data
                            except json.JSONDecodeError:
                                pass
    
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
        encoded_dir = urllib.parse.quote(directory, safe='')
        url = f"{self.worker_url}/list-models?directory={encoded_dir}"
        response = await client.get(url)
        if response.status_code == 200:
            data = response.json()
            return data.get("files", [])
        return []
    
    async def delete_model(self, path: str) -> bool:
        """Delete model via worker container."""
        client = get_http_client()
        url = f"{self.worker_url}/delete-model"
        response = await client.post(url, json={"path": path})
        return response.status_code == 200
    
    def get_file_proxy(self) -> FileProxyProvider:
        return self._file_proxy
    
    def get_provider_info(self) -> Dict[str, Any]:
        return {
            "id": self.provider_id,
            "type": self.provider_type,
            "mode": "containerized",
            "worker_url": self.worker_url,
            "gpu_type": self.gpu_type,
        }
