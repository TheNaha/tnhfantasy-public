"""
Shared HTTP client with connection pooling and retry logic.
Uses httpx with optional tenacity for retries.
"""

import asyncio
import os
from typing import AsyncIterator, Optional
from dataclasses import dataclass
import httpx

# Bytes per chunk when relaying a streamed response body.
FILE_TRANSFER_CHUNK_BYTES = 1 << 20

# Default ceiling on a single /get-file transfer. Files served by the storage
# apps are model sidecars, previews and output images; a checkpoint weights file
# is not fetched through this path.
DEFAULT_GET_FILE_SIZE_CAP = 512 * 1024 * 1024

# Default ceiling on one uploaded file body (decoded bytes) — the same default
# backend_v2/services/engines/base.py documents for PROVIDER_UPLOAD_MAX_BYTES.
DEFAULT_UPLOAD_MAX_BYTES = 512 * 1024 * 1024


def get_upload_size_cap() -> int:
    """Ceiling on one uploaded file body, in decoded bytes.

    Override with ``PROVIDER_UPLOAD_MAX_BYTES`` — the name the backend's
    pre-check (`services/engines/base.get_upload_size_cap`) reads, so the
    container and the route in front of it agree on one knob. Zero or
    negative disables the cap, exactly like ``get_file_size_cap``.

    Mirrored in ``remote_agent/provider_core/http_client.py`` (deliberate
    fork); `tests/test_provider_core_parity.py` pins the two together.
    """
    raw = os.getenv("PROVIDER_UPLOAD_MAX_BYTES", "").strip()
    if not raw:
        return DEFAULT_UPLOAD_MAX_BYTES
    try:
        cap = int(raw)
    except ValueError:
        return DEFAULT_UPLOAD_MAX_BYTES
    return cap if cap > 0 else 0


def get_file_size_cap() -> int:
    """Max bytes a provider will relay for one /get-file call.

    Override with ``PROVIDER_GET_FILE_MAX_BYTES``. Zero or negative disables the
    cap (only for a deployment that genuinely streams model weights).

    The negative clamp is not decoration — it is a fork fix. This copy returns
    the raw `int(raw)`, while `backend_v2/services/engines/base.py`'s
    `get_file_size_cap()` clamps with `cap if cap > 0 else 0`. The two then
    disagreed about what the DOCUMENTED disable value meant: the caller reads 0
    as "no limit", `beam_app.py`'s guard reads it as `if max_bytes >= 0 and
    size > max_bytes` — true for every non-empty file — so setting
    `PROVIDER_GET_FILE_MAX_BYTES=0` to disable the cap returned HTTP 413 on
    EVERY `/get-file`, making the storage app unreadable rather than unlimited.

    Both sides must agree that 0 means unlimited. `tests/test_provider_core_parity.py`
    asserts this rather than trusting the two copies to stay in step.
    """
    raw = os.getenv("PROVIDER_GET_FILE_MAX_BYTES", "").strip()
    if not raw:
        return DEFAULT_GET_FILE_SIZE_CAP
    try:
        cap = int(raw)
    except ValueError:
        return DEFAULT_GET_FILE_SIZE_CAP
    return cap if cap > 0 else 0


async def relay_bytes(
    response: httpx.Response,
    max_bytes: Optional[int] = None,
    *,
    chunk_bytes: int = FILE_TRANSFER_CHUNK_BYTES,
) -> AsyncIterator[bytes]:
    """Stream a response body through in chunks, enforcing a byte ceiling.

    Replaces `return Response(content=response.content, ...)` on a large fetch,
    which held the whole body in memory and, on the base64 variant, then made a
    second copy while decoding. Raises ``httpx.RequestError`` if the body turns
    out to exceed ``max_bytes`` — a declared Content-Length is checked by the
    caller first, but it can lie or be absent.
    """
    sent = 0
    try:
        async for chunk in response.aiter_bytes(chunk_bytes):
            sent += len(chunk)
            # `> 0`, not `>= 0`, for the same reason `beam_app.py`'s guard and
            # `remote_agent/server.py`'s both say it: 0 is the documented
            # "no limit" value, and `>= 0` turned it into "a zero-byte limit"
            # that rejects the first chunk of every stream.
            if max_bytes is not None and max_bytes > 0 and sent > max_bytes:
                raise httpx.RequestError(
                    f"response body exceeded the {max_bytes} byte limit"
                )
            yield chunk
    finally:
        await response.aclose()

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
        """Perform POST request without automatic retries by default."""
        client = await self.get_client()
        retry = kwargs.pop("_retry", False)
        return await self._request_with_retry(client.post, url, **kwargs, retry=retry)

    async def put(self, url: str, **kwargs) -> httpx.Response:
        """Perform PUT request without automatic retries by default."""
        client = await self.get_client()
        retry = kwargs.pop("_retry", False)
        return await self._request_with_retry(client.put, url, **kwargs, retry=retry)

    async def delete(self, url: str, **kwargs) -> httpx.Response:
        """Perform DELETE request without automatic retries by default."""
        client = await self.get_client()
        retry = kwargs.pop("_retry", False)
        return await self._request_with_retry(client.delete, url, **kwargs, retry=retry)

    async def _request_with_retry(self, method, url: str, *, retry: bool = True, **kwargs) -> httpx.Response:
        """Execute request with retry logic if tenacity is available."""
        if retry and TENACITY_AVAILABLE and self.config.retry_attempts > 1:
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


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def http_client_config_from_env() -> HttpClientConfig:
    """The process-wide client config, read from the environment.

    Defaults are the `HttpClientConfig` field defaults, restated so the knobs and
    the numbers they change are visible in one place.
    """
    max_connections = _env_int("PROVIDER_HTTP_MAX_CONNECTIONS", 10)
    return HttpClientConfig(
        # 30s, shorter than the per-call timeouts the callers pass explicitly
        # (a download is 1800s); this is the default for a call that passes none.
        timeout=_env_float("PROVIDER_HTTP_TIMEOUT_SECONDS", 30.0),
        max_connections=max_connections,
        max_keepalive_connections=_env_int("PROVIDER_HTTP_MAX_KEEPALIVE", 5),
        retry_attempts=_env_int("PROVIDER_HTTP_RETRY_ATTEMPTS", 3),
        retry_min_wait=_env_float("PROVIDER_HTTP_RETRY_MIN_WAIT", 1.0),
        retry_max_wait=_env_float("PROVIDER_HTTP_RETRY_MAX_WAIT", 10.0),
    )


def configure_http_client(config: Optional[HttpClientConfig] = None) -> SharedHttpClient:
    """Install the process-wide client. Call once, at startup.

    This used to be `get_http_client(config)`, which built the singleton on the
    first call and then **silently ignored `config` on every later call** — so
    the first caller's timeout/pool/retry count won process-wide, and every
    subsequent caller was handed a client configured for somebody else's
    workload with no way to tell. `os.getenv`'s "absent means default" trap made
    it worse: a caller passing `HttpClientConfig()` looked like it was asking for
    the defaults and got whatever the first caller had asked for instead.

    So configuration is now explicit and separate from acquisition. `config`
    defaults to the environment-derived config; passing one is for tests and for a
    caller that has genuinely built its own.
    """
    global _http_client
    _http_client = SharedHttpClient(config or http_client_config_from_env())
    return _http_client


def get_http_client() -> SharedHttpClient:
    """Get the process-wide client, creating it with the env config if unset.

    Takes no arguments on purpose. A `config` parameter here is the bug: it reads
    as "this call decides the config" and would be ignored by every call after
    the first. Use `configure_http_client` at startup instead.
    """
    global _http_client
    if _http_client is None:
        configure_http_client()
    return _http_client


async def close_http_client():
    """Close the global HTTP client."""
    global _http_client
    if _http_client:
        await _http_client.close()
        _http_client = None
