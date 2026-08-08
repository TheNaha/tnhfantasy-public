"""
Shared HTTP client with connection pooling and retry logic.
Uses httpx with optional tenacity for retries.
"""

import asyncio
from typing import Optional, Dict, Any
from dataclasses import dataclass
import httpx

try:
    from tenacity import (
        retry,
        stop_after_attempt,
        wait_exponential,
        retry_if_exception_type,
        retry_if_result,
    )
    TENACITY_AVAILABLE = True
except ImportError:
    TENACITY_AVAILABLE = False


@dataclass
class HttpClientConfig:
    """Configuration for the HTTP client."""
    timeout: float = 30.0
    max_connections: int = 10
    max_keepalive_connections: int = 5
    retry_attempts: int = 3
    retry_min_wait: float = 1.0
    retry_max_wait: float = 10.0


class SharedHttpClient:
    """
    Shared HTTP client with connection pooling.
    
    Maintains a persistent connection pool for efficient request handling.
    Supports optional retry logic via tenacity.
    """
    
    def __init__(self, config: HttpClientConfig = None):
        self.config = config or HttpClientConfig()
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()
    
    async def get_client(self) -> httpx.AsyncClient:
        """Get or create the shared HTTP client."""
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    limits = httpx.Limits(
                        max_connections=self.config.max_connections,
                        max_keepalive_connections=self.config.max_keepalive_connections,
                    )
                    self._client = httpx.AsyncClient(
                        timeout=httpx.Timeout(self.config.timeout),
                        limits=limits,
                    )
        return self._client
    
    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def get(self, url: str, **kwargs) -> httpx.Response:
        """Perform GET request with optional retry."""
        client = await self.get_client()
        return await self._request_with_retry(client.get, url, **kwargs)
    
    async def post(self, url: str, **kwargs) -> httpx.Response:
        """Perform POST request with optional retry."""
        client = await self.get_client()
        return await self._request_with_retry(client.post, url, **kwargs)
    
    async def put(self, url: str, **kwargs) -> httpx.Response:
        """Perform PUT request with optional retry."""
        client = await self.get_client()
        return await self._request_with_retry(client.put, url, **kwargs)
    
    async def delete(self, url: str, **kwargs) -> httpx.Response:
        """Perform DELETE request with optional retry."""
        client = await self.get_client()
        return await self._request_with_retry(client.delete, url, **kwargs)
    
    async def _request_with_retry(self, method, url: str, **kwargs) -> httpx.Response:
        """Execute request with retry logic if tenacity is available."""
        if TENACITY_AVAILABLE and self.config.retry_attempts > 1:
            return await self._retry_request(method, url, **kwargs)
        else:
            return await method(url, **kwargs)
    
    async def _retry_request(self, method, url: str, **kwargs) -> httpx.Response:
        """Execute request with tenacity retry."""
        if not TENACITY_AVAILABLE:
            return await method(url, **kwargs)
        
        @retry(
            stop=stop_after_attempt(self.config.retry_attempts),
            wait=wait_exponential(
                min=self.config.retry_min_wait,
                max=self.config.retry_max_wait,
            ),
            retry=(
                retry_if_exception_type((
                    httpx.TimeoutException,
                    httpx.ConnectError,
                    httpx.ReadError,
                ))
                | retry_if_result(lambda r: isinstance(r, httpx.Response) and r.status_code >= 500)
            ),
            reraise=True,
        )
        async def do_request():
            return await method(url, **kwargs)
        
        return await do_request()


# Global client instance
_http_client: Optional[SharedHttpClient] = None


def get_http_client(config: HttpClientConfig = None) -> SharedHttpClient:
    """Get or create the global HTTP client."""
    global _http_client
    if _http_client is None:
        _http_client = SharedHttpClient(config)
    return _http_client


async def close_http_client():
    """Close the global HTTP client."""
    global _http_client
    if _http_client:
        await _http_client.close()
        _http_client = None
