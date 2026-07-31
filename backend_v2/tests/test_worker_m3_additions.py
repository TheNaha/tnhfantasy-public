import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../provider_containers")))

from core.entities import Provider
from services.load_balancer import LoadBalancer, LoadBalancerRuntimeState
from services.provider_client import call_provider, ProviderCallError
from provider_core.router import attach_provider_routes
from provider_core.models import InferenceRequest

# -----------------------------------------------------------------------------
# 1. Test Provider Call Error retryable flag extraction
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_call_provider_extracts_retryable_from_non_200():
    # Mock httpx response and client
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.aread = AsyncMock(return_value=b'{"message": "OutOfMemory", "retryable": true}')
    
    mock_client = MagicMock()
    
    # Mock async context manager for stream
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)
    
    # Mock async context manager for get_streaming_client itself
    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_ctx.__aexit__ = AsyncMock(return_value=None)
    
    with patch("services.provider_client.get_streaming_client", return_value=mock_client_ctx):
        with pytest.raises(ProviderCallError) as exc_info:
            await call_provider(
                worker_url="http://mock-worker",
                workflow={},
                job_id="job-123",
                job_service=AsyncMock(),
                total_nodes=10,
                timeout=30.0,
                provider_id="provider-1"
            )
        assert exc_info.value.is_retryable is True

    # Test retryable is False
    mock_response.aread = AsyncMock(return_value=b'{"message": "InvalidWorkflow", "retryable": false}')
    with patch("services.provider_client.get_streaming_client", return_value=mock_client_ctx):
        with pytest.raises(ProviderCallError) as exc_info:
            await call_provider(
                worker_url="http://mock-worker",
                workflow={},
                job_id="job-123",
                job_service=AsyncMock(),
                total_nodes=10,
                timeout=30.0,
                provider_id="provider-1"
            )
        assert exc_info.value.is_retryable is False


# -----------------------------------------------------------------------------
# 2. Test global exception handlers in provider_core/router.py
# -----------------------------------------------------------------------------
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


# -----------------------------------------------------------------------------
# 3. Test Load Balancer Health check routing and autostart
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_load_balancer_health_checks(session: Session, monkeypatch):
    # Setup two mock providers
    p1 = Provider(
        id="warm-provider",
        type="modal",
        enabled=True,
        priority=1,
        credentials={},
        config={},
        container_config={"port": 8000}
    )
    p2 = Provider(
        id="cold-provider",
        type="modal",
        enabled=True,
        priority=1,
        credentials={},
        config={},
        container_config={"port": 8000}
    )
    session.add(p1)
    session.add(p2)
    session.commit()

    # Create LoadBalancer and force health checks enabled
    lb = LoadBalancer(session, strategy="round-robin")
    lb.health_check_enabled = True

    # Mock health check function
    async def mock_check_health(self_lb, provider):
        # p1 is warm, p2 is cold
        return provider.id == "warm-provider"

    monkeypatch.setattr(LoadBalancer, "_check_provider_health", mock_check_health)

    # When both exist, we route only to the warm provider
    selected = await lb.get_next_provider()
    assert selected is not None
    assert selected.id == "warm-provider"

    # Now test what happens when only cold providers exist
    session.delete(p1)
    session.commit()

    # Mock ContainerManager and ProviderLifecycleService.start_container
    mock_cm = MagicMock()
    mock_cm.client = MagicMock()
    
    # Mock httpx get call during health check polling
    mock_httpx_response = MagicMock()
    mock_httpx_response.status_code = 200
    
    # Mock lifecycle start_container
    mock_start_container = AsyncMock(return_value={"status": "success"})
    
    with patch("api.deps.get_container_manager", return_value=mock_cm), \
         patch("services.provider_lifecycle_service.ProviderLifecycleService.start_container", mock_start_container), \
         patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_httpx_response)):
         
        # Polling sleep is mocked to speed up tests
        with patch("asyncio.sleep", AsyncMock()):
            selected = await lb.get_next_provider()
            assert selected is not None
            assert selected.id == "cold-provider"
            mock_start_container.assert_awaited_once_with("cold-provider")
