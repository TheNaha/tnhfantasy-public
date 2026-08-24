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
