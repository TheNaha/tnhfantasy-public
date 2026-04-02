from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.events import EventType
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
