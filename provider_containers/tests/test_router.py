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
    monkeypatch.setenv("PROVIDER_WORKER_TOKEN", "router-test-token")
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
    
    # Test HTTP Exception handler
    response = client.get("/health")
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "error"
    assert "Unhealthy database connection" in payload["message"]
    assert payload["retryable"] is True
    assert payload["code"] == 503

    # Test general Exception handler (should map to 500 retryable error)
    response = client.get("/info")
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
