# Base provider interface for serverless platforms
from abc import ABC, abstractmethod
from typing import Dict, List, AsyncIterator, Any


class ServerlessProvider(ABC):
    """Abstract base class for serverless compute providers."""
    
    def __init__(self, provider_id: str, config: Dict[str, Any]):
        self.provider_id = provider_id
        self.config = config
        self.provider_type = config.get("type", "unknown")
    
    @abstractmethod
    async def run_inference(self, workflow: Dict[str, Any]) -> AsyncIterator[Dict[str, Any]]:
        """
        Execute a ComfyUI workflow and yield progress updates.
        
        Yields:
            Progress updates: {status, progress, message, etc.}
        """
        pass
    
    @abstractmethod
    async def download_model(
        self, 
        url: str, 
        path: str, 
        token: str = None, 
        preview_url: str = None, 
        metadata: Dict = None
    ) -> Dict[str, Any]:
        """Download a model to provider storage."""
        pass
    
    @abstractmethod
    async def list_models(self, directory: str) -> List[Dict[str, Any]]:
        """List models in a directory with metadata."""
        pass
    
    @abstractmethod
    async def delete_model(self, path: str) -> bool:
        """Delete a model from provider storage."""
        pass
    
    @abstractmethod
    def get_file_proxy(self) -> 'FileProxyProvider':
        """Get the file proxy instance for this provider."""
        pass
    
    def get_provider_info(self) -> Dict[str, Any]:
        """Get provider information."""
        return {
            "id": self.provider_id,
            "type": self.provider_type,
            "config": self.config
        }


class FileProxyProvider(ABC):
    """Abstract base class for file serving/proxy functionality."""
    
    def __init__(self, provider_id: str, config: Dict[str, Any]):
        self.provider_id = provider_id
        self.config = config
    
    @abstractmethod
    async def get_file(self, path: str) -> bytes:
        """Retrieve file contents from provider storage."""
        pass
    
    @abstractmethod
    async def delete_file(self, path: str) -> bool:
        """Delete a file from provider storage."""
        pass
    
    @abstractmethod
    def get_proxy_url(self) -> str:
        """Get the base proxy URL for this provider."""
        pass
