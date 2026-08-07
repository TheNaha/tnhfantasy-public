from unittest.mock import MagicMock
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from provider_core.router import attach_provider_routes

def test_router_exception_handlers():
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
    response = client.post("/inference", json={"workflow": "not-a-dict"})
    assert response.status_code == 422
    payload = response.json()
    assert payload["status"] == "error"
    assert "Validation error" in payload["message"]
    assert payload["retryable"] is False
