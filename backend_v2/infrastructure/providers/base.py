# Base provider interface for serverless platforms
from abc import ABC, abstractmethod
from typing import Any


class ServerlessProvider(ABC):
    """Abstract base class for serverless compute providers."""
    
    def __init__(self, provider_id: str, config: dict[str, Any]):
        self.provider_id = provider_id
        self.config = config
        self.provider_type = config.get("type", "unknown")
    
    @abstractmethod
    async def download_model(
        self, 
        url: str, 
        path: str, 
        token: str = None, 
        preview_url: str = None, 
        metadata: dict = None
    ) -> dict[str, Any]:
        """Download a model to provider storage."""
    
    @abstractmethod
    async def list_models(self, directory: str) -> list[dict[str, Any]]:
        """List models in a directory with metadata."""
    
    @abstractmethod
    async def delete_model(self, path: str) -> bool:
        """Delete a model from provider storage."""
    
    @abstractmethod
    def get_file_proxy(self) -> 'FileProxyProvider':
        """Get the file proxy instance for this provider."""
    
    def get_provider_info(self) -> dict[str, Any]:
        """Get provider information."""
        return {
            "id": self.provider_id,
            "type": self.provider_type,
            "config": self.config
        }


class FileProxyProvider(ABC):
    """Abstract base class for file serving/proxy functionality."""
    
    def __init__(self, provider_id: str, config: dict[str, Any]):
        self.provider_id = provider_id
        self.config = config
    
    @abstractmethod
    async def get_file(self, path: str) -> bytes:
        """Retrieve file contents from provider storage."""
    
    @abstractmethod
    async def delete_file(self, path: str) -> bool:
        """Delete a file from provider storage."""
    
    @abstractmethod
    def get_proxy_url(self) -> str:
        """Get the base proxy URL for this provider."""
