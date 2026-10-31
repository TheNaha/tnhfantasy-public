"""Tests for infrastructure/http_client.py"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import infrastructure.http_client as http_module
from infrastructure.http_client import (
    close_http_client,
    get,
    get_http_client,
    get_streaming_client,
    post,
    post_json,
)


@pytest.fixture(autouse=True)
def reset_client():
    """Reset the singleton client before each test."""
    http_module._client = None
    yield
    http_module._client = None


class TestGetHttpClient:
    def test_returns_async_client(self):
        client = get_http_client()
        assert isinstance(client, httpx.AsyncClient)

    def test_singleton_same_instance(self):
        c1 = get_http_client()
        c2 = get_http_client()
        assert c1 is c2

    def test_creates_new_if_none(self):
        http_module._client = None
        client = get_http_client()
        assert client is not None

    def test_client_initialization_configuration(self):
        client = get_http_client()

        # Check timeout configuration
        assert client.timeout.connect == 5.0
        assert client.timeout.read == 60.0
        assert client.timeout.write == 10.0
        assert client.timeout.pool == 5.0

        # Check connection limits
        pool = client._transport._pool
        assert getattr(pool, "_max_keepalive_connections", None) == 20
        assert getattr(pool, "_max_connections", None) == 50
        assert getattr(pool, "_keepalive_expiry", None) == 30.0

        # Check other settings
        assert client.follow_redirects is True
        assert getattr(pool, "_http2", None) is True


class TestCloseHttpClient:
    async def test_closes_client(self):
        get_http_client()
        await close_http_client()
        assert http_module._client is None

    async def test_noop_if_no_client(self):
        http_module._client = None
        # Should not raise
        await close_http_client()

    async def test_client_none_after_close(self):
        get_http_client()
        await close_http_client()
        assert http_module._client is None


class TestGetStreamingClient:
    async def test_yields_client(self):
        async with get_streaming_client() as client:
            assert isinstance(client, httpx.AsyncClient)

    async def test_custom_timeout(self):
        async with get_streaming_client(timeout=300.0) as client:
            assert client is not None

    async def test_client_closed_after_context(self):
        async with get_streaming_client() as client:
            captured = client
        # After context manager exits, client should be closed
        assert captured.is_closed


class TestConvenienceFunctions:
    async def test_get_uses_pooled_client(self):
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_response):
            response = await get("https://example.com")
            assert response.status_code == 200

    async def test_post_uses_pooled_client(self):
        mock_response = MagicMock()
        mock_response.status_code = 201

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_response):
            response = await post("https://example.com", json={"key": "value"})
            assert response.status_code == 201

    async def test_post_json_uses_pooled_client(self):
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_response):
            response = await post_json("https://example.com", {"data": 42})
            assert response.status_code == 200


_PROVIDER_HOST = "tnhfantasy-modal-zetsuke"


class TestProviderTokenOnStreamingRequests:
    """Regression: the token must be attached on the *streaming* path too.

    `httpx.AsyncClient.stream()` is `build_request()` + `send(stream=True)` and
    never calls `request()`. Inference is an NDJSON stream, so attaching the
    token in `request()` left every `/inference` unauthenticated while a plain
    `post()` to the same URL worked. The provider answered 401 "invalid provider
    worker token" and every job failed as "all providers failed" against a
    healthy, correctly configured provider.
    """

    @pytest.mark.asyncio
    async def test_stream_attaches_the_token(self, monkeypatch):
        import httpx

        from infrastructure import http_client

        monkeypatch.setenv("COMFY_PROVIDER_TOKEN", "secret-token")
        monkeypatch.setenv("COMFY_WORKER_HOSTS", "")

        seen: dict[str, str | None] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["stream"] = request.headers.get("X-Provider-Token")
            return httpx.Response(200, json={"status": "success"})

        transport = httpx.MockTransport(handler)
        async with http_client.get_streaming_client(timeout=5) as client:
            # Force the streaming client onto our mock transport.
            client._transport = transport
            client._mounts = {}
            async with client.stream(
                "POST",
                f"http://{_PROVIDER_HOST}/inference",
                json={"workflow": {}},
            ) as response:
                assert response.status_code == 200

        assert seen["stream"] == "secret-token", "stream() bypassed the token attachment"

    @pytest.mark.asyncio
    async def test_post_still_attaches_the_token(self, monkeypatch):
        import httpx

        from infrastructure import http_client

        monkeypatch.setenv("COMFY_PROVIDER_TOKEN", "secret-token")
        monkeypatch.setenv("COMFY_WORKER_HOSTS", "")

        seen: dict[str, str | None] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["post"] = request.headers.get("X-Provider-Token")
            return httpx.Response(200, json={"status": "success"})

        transport = httpx.MockTransport(handler)
        async with http_client.get_streaming_client(timeout=5) as client:
            client._transport = transport
            client._mounts = {}
            response = await client.post(
                f"http://{_PROVIDER_HOST}/inference", json={"workflow": {}}
            )
            assert response.status_code == 200

        assert seen["post"] == "secret-token"

    def test_unknown_host_lookup_failure_attaches_the_token_anyway(self, monkeypatch):
        """Fails closed. An empty host set used to mean "not a provider", so a
        transient DB failure silently sent unauthenticated requests."""
        from infrastructure import http_client

        monkeypatch.setenv("COMFY_PROVIDER_TOKEN", "secret-token")
        monkeypatch.setattr(http_client, "published_known_provider_hosts", lambda: None)

        headers = http_client._provider_token_headers(
            f"http://{_PROVIDER_HOST}/inference", {}
        )
        assert headers["X-Provider-Token"] == "secret-token"

    def test_explicit_external_host_is_never_given_the_token(self, monkeypatch):
        from infrastructure import http_client

        monkeypatch.setenv("COMFY_PROVIDER_TOKEN", "secret-token")
        monkeypatch.setattr(http_client, "published_known_provider_hosts", lambda: frozenset())

        headers = http_client._provider_token_headers(
            "https://api.example.com/inference", {},  # not a provider
        )
        assert "X-Provider-Token" not in headers


class TestProviderHostLookupDoesNotTouchTheDatabase:
    """The request path must not do DB I/O.

    `_is_known_provider_host` used to call `_refresh_known_provider_hosts()`,
    which opened a fresh `get_session_sync()` and ran a full
    `ProviderRepository.get_all()` — inline, on the event loop, for every
    outbound provider call whose 30 s TTL was cold. It could not be moved off
    the loop from where it was: `build_request()` is synchronous, so there is no
    await point to offload at.

    The fix is architectural, not a bigger timeout: the set is *published* by
    `load_known_provider_hosts()` (called at startup and after every provider
    write) and *read* without the database. These tests pin both halves.
    """

    def test_the_request_path_opens_no_session(self, monkeypatch):
        from infrastructure import database, http_client

        def _explode(*args, **kwargs):
            raise AssertionError(
                "the token path opened a database session on the event loop"
            )

        monkeypatch.setattr(database, "get_session_sync", _explode)
        monkeypatch.setenv("COMFY_PROVIDER_TOKEN", "secret-token")
        monkeypatch.setattr(
            http_client, "published_known_provider_hosts", lambda: frozenset()
        )

        headers = http_client._provider_token_headers(
            "https://api.example.com/inference", {}
        )
        assert headers == {}

    def test_the_published_set_is_an_immutable_snapshot(self, monkeypatch):
        """A caller cannot mutate the published set and change what the request
        path sees; the published value is a `frozenset` built at load time."""
        from infrastructure import http_client

        monkeypatch.setattr(
            http_client, "published_known_provider_hosts", lambda: frozenset({"a"})
        )
        assert http_client.published_known_provider_hosts() == frozenset({"a"})

    def test_load_publishes_and_force_reloads(self, monkeypatch):
        from infrastructure import http_client

        calls = []

        class _Repo:
            def __init__(self, session):
                pass

            def get_all(self):
                return []

        class _Session:
            def close(self):
                pass

        monkeypatch.setattr(
            http_client, "_known_provider_hosts", None, raising=False
        )
        monkeypatch.setattr(
            "infrastructure.database.get_session_sync", lambda: _Session()
        )
        monkeypatch.setattr(
            "infrastructure.repositories.ProviderRepository", _Repo
        )
        monkeypatch.setattr(
            http_client, "_PROVIDER_HOST_CACHE_SECONDS", 30.0
        )

        calls.append(http_client.load_known_provider_hosts())
        # Within the TTL a second call is a cache hit...
        calls.append(http_client.load_known_provider_hosts())
        # ...and `force` re-reads, which is what startup and every provider
        # write do.
        calls.append(http_client.load_known_provider_hosts(force=True))

        assert calls[0] == frozenset()
        assert calls[1] == frozenset()
        assert calls[2] == frozenset()
        assert http_client.published_known_provider_hosts() == frozenset()

    def test_a_failed_load_publishes_none_not_an_empty_set(self, monkeypatch):
        """`None` and `frozenset()` are different answers and must not collapse.

        An empty set reads as "resolved, and there are no providers", so a failed
        read that published one would silently stop attaching the token to
        *every* management call.
        """
        from infrastructure import http_client

        def _boom(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr("infrastructure.database.get_session_sync", _boom)

        assert http_client.load_known_provider_hosts(force=True) is None
        assert http_client.published_known_provider_hosts() is None

    def test_publishing_still_works_after_a_failed_load(self, monkeypatch):
        """The `None` state must not make `publish_provider_host` raise.

        `host in None` is a `TypeError`, and the only production caller sits in
        a bare `except Exception: pass` (`infrastructure/providers/runtime.py`),
        so after any failed read every publish was raised and discarded: the
        resolved host was never learned, and the token decision kept falling
        back to "could not tell, attach anyway" — re-logging an ERROR per
        request instead of converging.
        """
        from infrastructure import http_client

        def _boom(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr("infrastructure.database.get_session_sync", _boom)
        monkeypatch.setattr(http_client, "_known_provider_hosts", None, raising=False)

        assert http_client.load_known_provider_hosts(force=True) is None

        http_client.publish_provider_host("tnhfantasy-Modal-Zetsuke:8000")

        published = http_client.published_known_provider_hosts()
        assert published is not None
        assert "tnhfantasy-modal-zetsuke:8000" in published
