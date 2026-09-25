import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel import Session


from core.entities import Provider
from services.load_balancer import LoadBalancer
from services.provider_client import ProviderCallError, call_image_provider


# -----------------------------------------------------------------------------
# 1. Test Provider Call Error retryable flag extraction
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_call_image_provider_extracts_retryable_from_non_200():
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
            await call_image_provider(
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
            await call_image_provider(
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
    monkeypatch.setenv("COMFY_PROVIDER_AUTOSTART_ENABLED", "1")

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

    with patch("infrastructure.deps.get_container_manager", return_value=mock_cm), \
         patch("services.provider_lifecycle_service.ProviderLifecycleService.start_container", mock_start_container), \
         patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_httpx_response)):
        selected = await lb.get_next_provider()
        assert selected is not None
        assert selected.id == "cold-provider"

        # Cold-start warmup now runs fire-and-forget in a background task:
        # selection returns immediately, so pump the loop (real sleeps so the
        # event loop processes the pending background task) until the task
        # triggers container startup.
        for _ in range(50):
            if mock_start_container.await_count >= 1:
                break
            await asyncio.sleep(0.01)
        mock_start_container.assert_awaited_once_with("cold-provider")

        # Health polling (httpx 200) fills the cache keyed by id:url
        from services import load_balancer as lb_module
        for _ in range(50):
            if any(k.startswith("cold-provider:") for k in lb_module._provider_health_cache):
                break
            await asyncio.sleep(0.01)
        assert any(k.startswith("cold-provider:") for k in lb_module._provider_health_cache)
