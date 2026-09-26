# HTTP Client with Connection Pooling
# Provides a singleton httpx AsyncClient for efficient connection reuse

from contextlib import asynccontextmanager
import os
from urllib.parse import urlparse

import httpx

from infrastructure.logging import http_logger
from infrastructure.providers.runtime import PROVIDER_CONTAINER_PREFIX

logger = http_logger()

# Singleton HTTP client instance
_client: httpx.AsyncClient | None = None

# Paths that a provider container protects with X-Provider-Token. Used only to
# decide when to warn about a token that will not be attached; it does not
# gate the request itself.
_PROVIDER_MANAGEMENT_PATHS = (
    "/inference", "/download-model", "/delete-model", "/get-file", "/delete-file",
    "/upload-file", "/setup", "/list-models", "/validate-models", "/validate-all-models",
    "/reconcile", "/reconciliation-status", "/deploy", "/deploy-status", "/cancel-job",
    "/config", "/provider-stats", "/object-info",
)


def _is_provider_management_path(url: str) -> bool:
    path = urlparse(url).path.rstrip("/")
    return any(path.endswith(suffix) for suffix in _PROVIDER_MANAGEMENT_PATHS)


class _ProviderTokenClient(httpx.AsyncClient):
    """Attaches the provider auth header to provider management calls.

    Provider containers fail CLOSED when PROVIDER_WORKER_TOKEN is unset, so a
    missing header surfaces as a 401 that looks identical to an outage. This
    client attaches the token to Docker-network providers (matched by the
    `tnhcomfy-<provider_id>` container-name convention) and to any host listed
    in COMFY_WORKER_HOSTS, and logs loudly when it is about to omit it so the
    cause is diagnosable instead of mysterious.
    """

    async def request(self, method, url, **kwargs):
        token = os.getenv("PROVIDER_WORKER_TOKEN", "").strip()
        if token:
            hostname = (urlparse(str(url)).hostname or "").lower()
            allowed_hosts = {
                host.strip().lower()
                for host in os.getenv("COMFY_WORKER_HOSTS", "").split(",")
                if host.strip()
            }
            if hostname.startswith(PROVIDER_CONTAINER_PREFIX) or hostname in allowed_hosts:
                headers = dict(kwargs.pop("headers", {}) or {})
                headers.setdefault("X-Provider-Token", token)
                kwargs["headers"] = headers
            elif _is_provider_management_path(str(url)):
                logger.warning(
                    "provider_token_not_attached",
                    url=str(url),
                    hostname=hostname,
                    hint=(
                        f"host does not match the {PROVIDER_CONTAINER_PREFIX!r} prefix and is "
                        "not listed in COMFY_WORKER_HOSTS; the provider will answer 401"
                    ),
                )
        elif _is_provider_management_path(str(url)):
            logger.error(
                "provider_token_unset",
                url=str(url),
                hint="PROVIDER_WORKER_TOKEN is empty; provider containers fail closed with 503",
            )
        return await super().request(method, url, **kwargs)


def get_http_client() -> httpx.AsyncClient:
    """
    Get or create the singleton HTTP client with connection pooling.
    
    Returns:
        Configured httpx.AsyncClient with connection pooling
    """
    global _client
    if _client is None:
        _client = _ProviderTokenClient(
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
    async with _ProviderTokenClient(
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
