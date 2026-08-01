# HTTP Client with Connection Pooling
# Provides a singleton httpx AsyncClient for efficient connection reuse

from contextlib import asynccontextmanager

import httpx

from infrastructure.logging import http_logger

logger = http_logger()

# Singleton HTTP client instance
_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """
    Get or create the singleton HTTP client with connection pooling.
    
    Returns:
        Configured httpx.AsyncClient with connection pooling
    """
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            # Connection pooling limits
            limits=httpx.Limits(
                max_keepalive_connections=20,  # Keep up to 20 connections alive
                max_connections=50,             # Maximum 50 total connections
                keepalive_expiry=30.0           # Keep connections alive for 30 seconds
            ),
            # Default timeout (can be overridden per-request)
            timeout=httpx.Timeout(
                connect=5.0,    # Connection timeout
                read=60.0,      # Read timeout (for streaming responses)
                write=10.0,     # Write timeout
                pool=5.0        # Pool timeout waiting for connection
            ),
            # Follow redirects
            follow_redirects=True,
            # HTTP/2 support
            http2=True
        )
        logger.info("http_client_created", max_connections=50, keepalive=20)
    return _client


async def close_http_client():
    """
    Close the HTTP client and release all connections.
    Should be called on application shutdown.
    """
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
        logger.info("http_client_closed")


@asynccontextmanager
async def get_streaming_client(timeout: float = 600.0):
    """
    Get a client configured for streaming responses (like NDJSON).
    
    This uses a separate client with longer timeouts for streaming use cases.
    
    Args:
        timeout: Total request timeout in seconds (default: 10 minutes)
        
    Yields:
        httpx.AsyncClient configured for streaming
    """
    async with httpx.AsyncClient(
        limits=httpx.Limits(
            max_keepalive_connections=5,
            max_connections=10,
            keepalive_expiry=60.0
        ),
        timeout=httpx.Timeout(
            connect=10.0,
            read=timeout,      # Long read timeout for streaming
            write=30.0,
            pool=10.0
        ),
        http2=True
    ) as client:
        yield client


# Convenience functions for common operations

async def get(url: str, **kwargs) -> httpx.Response:
    """Make a GET request using the pooled client."""
    client = get_http_client()
    return await client.get(url, **kwargs)


async def post(url: str, **kwargs) -> httpx.Response:
    """Make a POST request using the pooled client."""
    client = get_http_client()
    return await client.post(url, **kwargs)


async def post_json(url: str, data: dict, **kwargs) -> httpx.Response:
    """Make a POST request with JSON body using the pooled client."""
    client = get_http_client()
    return await client.post(url, json=data, **kwargs)
