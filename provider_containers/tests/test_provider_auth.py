"""Auth tests for the provider management API.

This path had ZERO coverage while being the only thing standing between the
Docker bridge network and a management API that includes `/deploy` (which shells
out to `modal deploy` / `beam deploy`), `/delete-model`, and `/delete-file`.

The original gate was `if expected and header != expected`, so an unset
COMFY_PROVIDER_TOKEN disabled authentication entirely — and empty is what
.env.example shipped. Every protected route was therefore open by default.
"""
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from provider_core.router import attach_provider_routes

TOKEN = "test-provider-token-secret"


def _async_return(value):
    async def _inner():
        return value

    return _inner


def _app() -> TestClient:
    app = FastAPI()
    client = MagicMock()
    client.get_health = _async_return({"status": "healthy", "ready": True})
    client.get_info = _async_return({"engine": "test"})
    client.get_storage_stats = _async_return({"total_models": 0})
    client.get_reconciliation_status = lambda: {"status": "idle"}
    client.get_config = lambda: {}
    client.get_deploy_status = _async_return({"status": "idle"})
    attach_provider_routes(app, client)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def token_env(monkeypatch):
    monkeypatch.setenv("COMFY_PROVIDER_TOKEN", TOKEN)
    return TOKEN


class TestProviderAuthFailsClosed:
    def test_unset_token_refuses_protected_routes(self, monkeypatch):
        """An unset token must NOT mean "no authentication required"."""
        monkeypatch.delenv("COMFY_PROVIDER_TOKEN", raising=False)
        client = _app()

        for path, method in (
            ("/list-models", "get"),
            ("/setup", "post"),
            ("/reconcile", "post"),
        ):
            response = getattr(client, method)(path)
            assert response.status_code == 503, (
                f"{method.upper()} {path} was reachable with no token configured"
            )
            assert "COMFY_PROVIDER_TOKEN" in response.text

    def test_unset_token_still_allows_healthcheck(self, monkeypatch):
        """The compose healthcheck sends no token, so /health must stay open."""
        monkeypatch.delenv("COMFY_PROVIDER_TOKEN", raising=False)
        client = _app()
        assert client.get("/health").status_code == 200

    def test_blank_token_is_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("COMFY_PROVIDER_TOKEN", "   ")
        client = _app()
        assert client.get("/list-models").status_code == 503


class TestProviderAuthRejectsBadTokens:
    def test_missing_header_is_401(self, token_env):
        client = _app()
        assert client.get("/list-models").status_code == 401

    def test_wrong_token_is_401(self, token_env):
        client = _app()
        response = client.get("/list-models", headers={"X-Provider-Token": "not-the-token"})
        assert response.status_code == 401

    def test_empty_header_is_401(self, token_env):
        client = _app()
        response = client.get("/list-models", headers={"X-Provider-Token": ""})
        assert response.status_code == 401

    def test_token_prefix_is_not_accepted(self, token_env):
        """Guards against a compare that only checked a leading substring."""
        client = _app()
        response = client.get("/list-models", headers={"X-Provider-Token": TOKEN[:-1]})
        assert response.status_code == 401

    def test_correct_token_passes(self, token_env):
        client = _app()
        response = client.get("/list-models", headers={"X-Provider-Token": TOKEN})
        assert response.status_code not in (401, 503)


class TestStateReadingRoutesAreGated:
    """`/info` and `/provider-stats` were the last two state-reading routes
    left without `dependencies=protected`.

    `/info` returns the upstream endpoint (direct_url's `comfy_url` is a LAN IP,
    modal's is a *.modal.run URL). `/provider-stats` is amplification: nothing
    overrides `BaseProviderClient.get_storage_stats` on a remote_comfy provider,
    so one unauthenticated GET fanned out to MODEL_DIRECTORIES x list_models —
    16 authenticated round trips to the remote agent.

    `/health` must stay open: the compose and Dockerfile healthchecks call it
    with no headers.
    """

    def test_info_requires_the_token(self, token_env):
        client = _app()
        assert client.get("/info").status_code == 401
        assert client.get(
            "/info", headers={"X-Provider-Token": TOKEN}
        ).json() == {"engine": "test"}

    def test_provider_stats_requires_the_token(self, token_env):
        client = _app()
        assert client.get("/provider-stats").status_code == 401
        assert client.get(
            "/provider-stats", headers={"X-Provider-Token": TOKEN}
        ).json() == {"total_models": 0}

    def test_state_routes_fail_closed_without_a_configured_token(self, monkeypatch):
        monkeypatch.delenv("COMFY_PROVIDER_TOKEN", raising=False)
        client = _app()
        assert client.get("/info").status_code == 503
        assert client.get("/provider-stats").status_code == 503

    def test_health_stays_open(self, token_env):
        client = _app()
        assert client.get("/health").status_code == 200
