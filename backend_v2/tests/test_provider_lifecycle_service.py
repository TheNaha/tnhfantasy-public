from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.events import EventType
from core.exceptions import ProviderError
from services.provider_lifecycle_service import ProviderLifecycleService


@pytest.mark.asyncio
async def test_start_container_emits_event_and_invalidates_cache():
    provider_service = MagicMock()
    provider_service.get_provider = AsyncMock(
        return_value=SimpleNamespace(
            id="provider-1",
            type="modal",
            container_config={"port": 8000},
        )
    )
    provider_service.build_provider_environment.return_value = {"MODAL_TOKEN_ID": "abc"}

    container = MagicMock(short_id="container-123")
    container_manager = MagicMock()
    container_manager.start_container.return_value = container

    invalidate = MagicMock()

    service = ProviderLifecycleService(
        session=MagicMock(),
        provider_service=provider_service,
        container_manager=container_manager,
        invalidate_caches=invalidate,
    )

    with patch("services.provider_lifecycle_service.emit_provider_event", new=AsyncMock()) as mock_emit:
        result = await service.start_container("provider-1")

    assert result["container_id"] == "container-123"
    provider_service.build_provider_environment.assert_called_once_with(
        provider_service.get_provider.return_value
    )
    container_manager.start_container.assert_called_once()
    invalidate.assert_called_once_with("provider-1")
    mock_emit.assert_awaited_once_with(
        EventType.PROVIDER_CONTAINER_STATUS,
        "provider-1",
        {"status": "running"},
    )


@pytest.mark.asyncio
async def test_trigger_reconciliation_short_circuits_when_already_running():
    provider_service = MagicMock()
    provider_service.get_provider = AsyncMock(
        return_value=SimpleNamespace(id="provider-1", type="modal", container_config={"port": 8000})
    )
    provider_service.start_reconciliation_session = AsyncMock(
        return_value={
            "accepted": False,
            "state": {"status": "queued"},
            "message": "Reconciliation already in progress for this provider",
        }
    )

    service = ProviderLifecycleService(
        session=MagicMock(),
        provider_service=provider_service,
        container_manager=MagicMock(),
    )

    with patch(
        "services.provider_lifecycle_service.resolve_provider_runtime",
        return_value=SimpleNamespace(supports_reconciliation=True, mode="container_http", worker_url="http://worker"),
    ):
        result = await service.trigger_reconciliation("provider-1")

    assert result["status"] == "already_running"
    assert result["message"] == "Reconciliation already in progress for this provider"


@pytest.mark.asyncio
async def test_get_reconciliation_status_returns_warning_when_worker_unreachable():
    provider_service = MagicMock()
    provider_service.get_provider = AsyncMock(
        return_value=SimpleNamespace(id="provider-1", type="modal", container_config={"port": 8000})
    )
    provider_service.get_provider_reconciliation_state = AsyncMock(return_value={"status": "idle"})

    http_client = MagicMock()
    http_client.get = AsyncMock(side_effect=httpx.ConnectError("boom"))

    service = ProviderLifecycleService(
        session=MagicMock(),
        provider_service=provider_service,
        container_manager=MagicMock(),
    )

    with patch(
        "services.provider_lifecycle_service.resolve_provider_runtime",
        return_value=SimpleNamespace(mode="container_http", worker_url="http://worker"),
    ), patch("services.provider_lifecycle_service.get_http_client", return_value=http_client):
        result = await service.get_reconciliation_status("provider-1")

    assert result["status"] == "idle"
    assert "Cannot reach worker" in result["warning"]


@pytest.mark.asyncio
async def test_setup_provider_returns_accepted_for_queued_worker_response():
    provider_service = MagicMock()
    provider_service.get_provider = AsyncMock(
        return_value=SimpleNamespace(id="provider-1", type="modal", container_config={"port": 8000})
    )

    http_client = MagicMock()
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "status": "queued",
        "message": "Setup queued",
        "provider": "provider-1",
    }
    http_client.post = AsyncMock(return_value=response)

    service = ProviderLifecycleService(
        session=MagicMock(),
        provider_service=provider_service,
        container_manager=MagicMock(),
    )

    with patch(
        "services.provider_lifecycle_service.resolve_provider_runtime",
        return_value=SimpleNamespace(supports_setup=True, mode="container_http", worker_url="http://worker"),
    ), patch("services.provider_lifecycle_service.get_http_client", return_value=http_client):
        result = await service.setup_provider("provider-1")

    assert result["status"] == "accepted"
    assert result["message"] == "Setup queued"
    assert result["result"]["status"] == "queued"
    http_client.post.assert_awaited_once_with("http://worker/setup", timeout=30.0)


@pytest.mark.asyncio
async def test_setup_provider_wraps_timeout_with_provider_error():
    provider_service = MagicMock()
    provider_service.get_provider = AsyncMock(
        return_value=SimpleNamespace(id="provider-1", type="modal", container_config={"port": 8000})
    )

    http_client = MagicMock()
    http_client.post = AsyncMock(side_effect=httpx.ReadTimeout("", request=MagicMock()))

    service = ProviderLifecycleService(
        session=MagicMock(),
        provider_service=provider_service,
        container_manager=MagicMock(),
    )

    with patch(
        "services.provider_lifecycle_service.resolve_provider_runtime",
        return_value=SimpleNamespace(supports_setup=True, mode="container_http", worker_url="http://worker"),
    ), patch("services.provider_lifecycle_service.get_http_client", return_value=http_client):
        with pytest.raises(ProviderError, match="Setup request to worker timed out"):
            await service.setup_provider("provider-1")


@pytest.mark.asyncio
async def test_get_container_status_uses_async_health_probe_when_container_is_running():
    provider_service = MagicMock()
    provider_service.get_provider = AsyncMock(
        return_value=SimpleNamespace(id="provider-1", type="modal", container_config={"port": 8000})
    )

    container = MagicMock()
    container.status = "running"
    container.short_id = "container-123"
    container.ports = {"8000/tcp": [{"HostPort": "18000"}]}
    container.attrs = {"State": {"Health": {}}}
    container.reload.return_value = None

    container_manager = MagicMock()
    container_manager.client.containers.get.return_value = container
    container_manager.running_containers = {}

    response = MagicMock()
    response.status_code = 200

    async_client = MagicMock()
    async_client.get = AsyncMock(return_value=response)

    async_context = MagicMock()
    async_context.__aenter__ = AsyncMock(return_value=async_client)
    async_context.__aexit__ = AsyncMock(return_value=None)

    service = ProviderLifecycleService(
        session=MagicMock(),
        provider_service=provider_service,
        container_manager=container_manager,
    )

    with patch("services.provider_lifecycle_service.httpx.AsyncClient", return_value=async_context):
        result = await service.get_container_status("provider-1")

    assert result["status"] == "running"
    assert result["running"] is True
    assert result["healthy"] is True
    async_client.get.assert_awaited_once_with("http://localhost:18000/health")
