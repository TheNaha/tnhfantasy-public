# HTTP Client with Connection Pooling
# Provides a singleton httpx AsyncClient for efficient connection reuse

from contextlib import asynccontextmanager
import os
import time
from urllib.parse import urlparse

import httpx

from infrastructure.logging import http_logger

logger = http_logger()

# Historical container-name prefix, kept locally (infrastructure.provider_naming
# is gone): legacy provider rows may still carry a `tnhfantasy-{id}` container
# name in config, and host recognition must keep matching them.
_PROVIDER_CONTAINER_PREFIX = "tnhfantasy-"

# Singleton HTTP client instance
_client: httpx.AsyncClient | None = None

# Paths that a provider container protects with X-Provider-Token. Used to decide
# when to warn about a token that will not be attached; it does not gate the
# request itself.
#
# `/info` and `/provider-stats` are here because the containers now require the
# token for them too.
_PROVIDER_MANAGEMENT_PATHS = (
    "/inference", "/download-model", "/delete-model", "/get-file", "/delete-file",
    "/upload-file", "/setup", "/list-models", "/validate-models", "/validate-all-models",
    "/reconcile", "/reconciliation-status", "/deploy", "/deploy-status", "/cancel-job",
    "/config", "/provider-stats", "/object-info", "/info",
)

# How long a resolved set of known provider hosts is trusted before it is
# re-read. Only bounds the RELOAD, never a read: the published set is read
# without touching the database, so this TTL costs nothing per request.
_PROVIDER_HOST_CACHE_SECONDS = 30.0

# `None` means "never resolved, or the last read failed" — i.e. "could not
# tell". It is deliberately distinct from an empty set, which means "resolved,
# and there are no providers".
_known_provider_hosts: frozenset[str] | None = None
_known_provider_hosts_at: float = 0.0


def publish_provider_host(host: str) -> None:
    """Add a host to the published set, at the moment we resolve it.

    The resolver knows for certain that the address it just produced is one of
    our providers. The database may not agree yet: a container id changes on every
    recreate and only reaches `discovery_url` when the worker's next discovery
    heartbeat writes it. Publishing here removes that window, which was a real
    401 on every job dispatched in the seconds after a provider was recreated.
    """
    global _known_provider_hosts
    host = (host or "").strip().lower()
    # `None` is the published "could not tell" state (see line 40), and
    # `host in None` raises. The only caller sits in a bare
    # `except Exception: pass`, so after any failed read every publish raised and
    # was silently discarded — the host was never learned and the token decision
    # fell back to "could not tell, attach anyway" on every request.
    known = _known_provider_hosts or frozenset()
    if not host or host in known:
        return
    _known_provider_hosts = frozenset({*known, host})


def _is_provider_management_path(url: str) -> bool:
    path = urlparse(url).path.rstrip("/")
    return any(path.endswith(suffix) for suffix in _PROVIDER_MANAGEMENT_PATHS)


def published_known_provider_hosts() -> frozenset[str] | None:
    """The host set, read without touching the database. Safe on the event loop.

    This is the ONLY function the request path is allowed to use. It used to call
    `_refresh_known_provider_hosts()`, which opened a fresh `get_session_sync()`
    and ran `ProviderRepository.get_all()` — a full provider-table read, inline,
    on the event loop, for every outbound provider call whose 30 s TTL was cold.
    `build_request()` is synchronous and cannot be made async, so the read could
    not be moved off the loop from where it was. The set is now published by
    `load_known_provider_hosts()` at startup and after any provider write, and
    this function is a plain read.
    """
    return _known_provider_hosts


def load_known_provider_hosts(*, force: bool = False) -> frozenset[str] | None:
    """Read the provider table and publish the result. BLOCKING — call via `to_thread`.

    Hostnames of every provider the backend knows about.

    The `tnhfantasy-` prefix convention only matches containers this project
    started under that name. A self-discovered provider registers
    `discovery_url` built from `socket.gethostname()`, which on a default Compose
    network is the 12-character container id — so *no* discovered provider matched
    the convention, and every management call to one silently omitted the token.
    With `/info` and `/provider-stats` now gated, that turned into the Diagnostics
    tab reporting every provider as offline.

    So: ask the database which hosts are providers, rather than guessing from the
    name. Both the container name and the discovery URL are registered, since
    either can be the address the backend actually dials.

    Args:
        force: re-read even if the published set is younger than the TTL.
            Startup and every provider write pass this; nothing else should.
    """
    global _known_provider_hosts, _known_provider_hosts_at

    now = time.monotonic()
    if not force and _known_provider_hosts is not None and (
        now - _known_provider_hosts_at < _PROVIDER_HOST_CACHE_SECONDS
    ):
        return _known_provider_hosts

    hosts: set[str] = set()
    try:
        from infrastructure.database import get_session_sync
        from infrastructure.repositories import ProviderRepository

        session = get_session_sync()
        try:
            for provider in ProviderRepository(session).get_all():
                config = provider.config or {}
                # A discovered provider keeps its container name under
                # `runtime_config`, and migration 089 folded the old
                # `container_config` column into `config` (config wins). Read
                # both so a provider is recognised whichever shape it stored.
                runtime_config = config.get("runtime_config") or {}
                for candidate in (
                    config.get("container_name"),
                    runtime_config.get("container_name") if isinstance(runtime_config, dict) else None,
                    f"{_PROVIDER_CONTAINER_PREFIX}{provider.id}",
                    config.get("discovery_url"),
                ):
                    if not candidate:
                        continue
                    host = (urlparse(str(candidate)).hostname or "").lower()
                    if host:
                        hosts.add(host)
        finally:
            session.close()
    except Exception as exc:
        # Previously this returned the last-known set, which on a cold process is
        # empty — and an empty set means "not a provider", so management calls
        # went out with no token and came back 401 "invalid provider worker
        # token". The inference path stayed up, so it was silent. `None` means
        # "could not tell", and the caller then fails closed.
        # Publishing the failure is what makes that work: a failed read must not
        # be indistinguishable from a resolved empty set.
        logger.warning("provider_host_refresh_failed", error=str(exc))
        _known_provider_hosts = None
        _known_provider_hosts_at = now
        return None

    _known_provider_hosts = frozenset(hosts)
    _known_provider_hosts_at = now
    return _known_provider_hosts


# Kept as the historical name for anything that imported it. Now a pure cache
# read, so calling it from a request handler is safe; use
# `load_known_provider_hosts(force=True)` to actually re-read.
_refresh_known_provider_hosts = published_known_provider_hosts


def _is_known_provider_host(
    hostname: str, allowed_hosts: "frozenset[str] | set[str]" = frozenset()
) -> bool:
    """Is this host one of our provider workers?

    Fails *closed* when the host list cannot be resolved and the host is not in
    the explicit external allow-list. The token is a shared internal secret, the
    backend constructs every provider URL itself, and guessing wrong costs a 401
    that surfaces on a job the user is paying for. Over-attaching stays bounded
    by COMFY_WORKER_HOSTS for genuinely external hosts.
    """
    host = hostname.lower()
    if host.startswith(_PROVIDER_CONTAINER_PREFIX):
        return True
    if host in allowed_hosts:
        return False

    hosts = published_known_provider_hosts()
    if hosts is None:
        logger.error("provider_host_lookup_unavailable_attaching_token_anyway", host=host)
        return True
    return host in hosts


def _provider_token_headers(url: str, headers: dict[str, str] | None) -> dict[str, str]:
    """`headers` plus `X-Provider-Token` when `url` points at one of our providers.

    Provider containers fail CLOSED when the token is unset, so a missing header
    surfaces as a 401 that looks exactly like an outage. Hosts are resolved from
    the database rather than the `tnhfantasy-` naming convention, because a
    self-discovered provider registers its container id as its hostname.

    Shared by the pooled and streaming paths — see the note on the class for why
    this cannot live in `request()`.
    """
    token = os.getenv("COMFY_PROVIDER_TOKEN", "").strip()
    merged = dict(headers or {})
    is_management = _is_provider_management_path(str(url))

    if not token:
        if is_management:
            logger.error(
                "provider_token_unset",
                url=str(url),
                hint="COMFY_PROVIDER_TOKEN is empty; the provider will answer 401",
            )
        return merged

    hostname = (urlparse(str(url)).hostname or "").lower()
    allowed_hosts = {
        host.strip().lower()
        for host in os.getenv("COMFY_WORKER_HOSTS", "").split(",")
        if host.strip()
    }
    if _is_known_provider_host(hostname, allowed_hosts):
        merged.setdefault("X-Provider-Token", token)
    elif is_management:
        logger.warning(
            "provider_token_not_attached",
            url=str(url),
            hostname=hostname,
            hint=(
                f"host does not match the {_PROVIDER_CONTAINER_PREFIX!r} prefix and is "
                "not listed in COMFY_WORKER_HOSTS; the provider will answer 401"
            ),
        )
    return merged


class _ProviderTokenClient(httpx.AsyncClient):
    """Attaches the provider auth header to provider management calls.

    The header is added in `build_request()`, NOT in `request()`.

    `httpx.AsyncClient.stream()` is implemented as `build_request()` followed by
    `send(request, stream=True)` and never calls `request()`. Inference is an
    NDJSON stream, so *every* generation call goes through `stream()` — attaching
    the token in `request()` left every `/inference` unauthenticated. A plain
    `post()` to the same URL authenticated fine and returned 422 for an invalid
    body while `stream()` returned 401 "invalid provider worker token", so the
    provider looked misconfigured and every job failed as "all providers failed"
    against a provider that was healthy and correctly set up.
    """

    def build_request(self, method, url, **kwargs) -> httpx.Request:
        headers = kwargs.pop("headers", None)
        request = super().build_request(method, url, headers=headers, **kwargs)
        resolved = _provider_token_headers(str(request.url), dict(request.headers))
        if "X-Provider-Token" in resolved:
            request.headers["X-Provider-Token"] = resolved["X-Provider-Token"]
        return request


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
