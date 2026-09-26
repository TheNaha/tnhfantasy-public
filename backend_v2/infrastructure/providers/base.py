# Base provider interface for serverless platforms
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

# A file larger than this is not returned inline. 64 MiB is comfortably above any
# sidecar or thumbnail and comfortably below anything that would hurt.
MAX_INLINE_FILE_BYTES = 64 * 1024 * 1024


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
        """Retrieve file contents from provider storage.

        Bytes, so it cannot be used for anything large: a 7 GB SDXL checkpoint
        becomes 7 GB in the worker, 7 GB in the response, and on the JSON path a
        base64 copy on top. `stream_file` is what a caller serving a model should
        use. This one is kept for small payloads — a `.json` sidecar, a preview
        thumbnail — and `get_file` refuses anything past
        `MAX_INLINE_FILE_BYTES` rather than trying.
        """

    @abstractmethod
    def stream_file(self, path: str) -> AsyncIterator[bytes]:
        """Yield a provider's file in chunks. Never materialises it in memory.

        Synchronous, returning an async iterator, because httpx's streaming API
        opens the request eagerly and the response body must be iterated inside the
        session's lifetime — the caller is responsible for that, and an async
        generator cannot be iterated correctly from a different task.
        """

    @abstractmethod
    async def delete_file(self, path: str) -> bool:
        """Delete a file from provider storage."""
    
    @abstractmethod
    def get_proxy_url(self) -> str:
        """Get the base proxy URL for this provider."""
