from unittest.mock import MagicMock
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from provider_core.router import attach_provider_routes

@pytest.fixture(autouse=True)
def _provider_token(monkeypatch):
    """Protected routes now fail closed without a token (503, not 422/401).

    Tests that exercise the payload-validation and exception handlers have to
    present a valid token to get past the auth gate and reach the code under
    test. See tests/test_provider_auth.py for the gate's own coverage.
    """
    monkeypatch.setenv("COMFY_PROVIDER_TOKEN", "router-test-token")
    return "router-test-token"

def test_router_exception_handlers(_provider_token):
    app = FastAPI()
    mock_client = MagicMock()
    
    # Setup endpoints to raise exceptions
    async def get_health_side_effect():
        raise HTTPException(status_code=503, detail="Unhealthy database connection")
        
    async def get_info_side_effect():
        raise ValueError("Something unexpected failed")
        
    mock_client.get_health = get_health_side_effect
    mock_client.get_info = get_info_side_effect
    
    attach_provider_routes(app, mock_client)
    
    # Use raise_server_exceptions=False so general exceptions return 500 response instead of raising in test
    client = TestClient(app, raise_server_exceptions=False)
    
    # Test HTTP Exception handler. A plain 503 detail (no `retryable` marker)
    # is a transient upstream fault, so it stays retryable.
    response = client.get("/health")
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "error"
    assert "Unhealthy database connection" in payload["message"]
    assert payload["retryable"] is True
    assert payload["code"] == 503

    # Test general Exception handler (should map to 500 retryable error).
    # /info is authenticated now, so present the token.
    response = client.get("/info", headers={"X-Provider-Token": _provider_token})
    assert response.status_code == 500
    payload = response.json()
    assert payload["status"] == "error"
    assert "Internal server error" in payload["message"]
    assert payload["retryable"] is True
    assert payload["code"] == 500

    # Test Validation error handler (e.g. sending invalid payload to inference)
    response = client.post(
        "/inference",
        json={"workflow": "not-a-dict"},
        headers={"X-Provider-Token": _provider_token},
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["status"] == "error"
    assert "Validation error" in payload["message"]
    assert payload["retryable"] is False


def test_delete_file_accepts_the_path_in_the_body(_provider_token):
    """The backend sends DELETE with a JSON body, not a query string.

    The route declared `path: str`, which FastAPI binds to the *query*
    parameter, so that request 422'd and the caller reported "not found" for a
    file it had just written.
    """
    app = FastAPI()
    mock_client = MagicMock()
    calls = []

    async def delete_file_side_effect(path):
        calls.append(path)
        return {"status": "success", "deleted": path}

    mock_client.delete_file = delete_file_side_effect
    attach_provider_routes(app, mock_client)
    client = TestClient(app)
    headers = {"X-Provider-Token": _provider_token}

    response = client.request(
        "DELETE", "/delete-file", json={"path": "models/checkpoints/x.safetensors"}, headers=headers
    )

    assert response.status_code == 200
    assert calls == ["models/checkpoints/x.safetensors"]


def test_delete_file_still_accepts_a_query_parameter(_provider_token):
    """The query form is the other documented shape; both must keep working."""
    app = FastAPI()
    mock_client = MagicMock()
    calls = []

    async def delete_file_side_effect(path):
        calls.append(path)
        return {"status": "success", "deleted": path}

    mock_client.delete_file = delete_file_side_effect
    attach_provider_routes(app, mock_client)
    client = TestClient(app)

    response = client.delete(
        "/delete-file", params={"path": "models/loras/y.safetensors"}, headers={"X-Provider-Token": _provider_token}
    )

    assert response.status_code == 200
    assert calls == ["models/loras/y.safetensors"]


def test_delete_file_without_a_path_is_a_400(_provider_token):
    app = FastAPI()
    mock_client = MagicMock()
    attach_provider_routes(app, mock_client)
    client = TestClient(app)

    response = client.request("DELETE", "/delete-file", headers={"X-Provider-Token": _provider_token})

    assert response.status_code == 400
