from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.provider_status_service import ProviderStatusService


def test_build_provider_status_card_fallback_preserves_runtime_metadata():
    service = ProviderStatusService(session=MagicMock(), provider_service=MagicMock())

    card = service.build_provider_status_card_fallback({
        "id": "provider-1",
        "type": "modal",
        "enabled": True,
        "runtime_state": {
            "mode": "container_http",
            "connected": True,
        },
        "reconciliation_state": {"status": "started"},
    })

    assert card["provider_id"] == "provider-1"
    assert card["runtime"]["mode"] == "container_http"
    assert card["storage"]["error"] == "Failed to build provider status card"
    assert card["reconciliation"]["status"] == "queued"
    assert card["diagnostics"]["worker"]["mode"] == "container_http"


@pytest.mark.asyncio
async def test_build_provider_status_cards_uses_fallback_when_live_assembly_fails():
    service = ProviderStatusService(session=MagicMock(), provider_service=MagicMock())
    providers = [{
        "id": "provider-1",
        "type": "modal",
        "enabled": True,
        "runtime_state": {"mode": "container_http", "connected": True},
        "reconciliation_state": {"status": "idle"},
        "deploy_state": {"status": "idle"},
    }]

    with patch.object(
        service,
        "build_provider_status_card",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        cards = await service.build_provider_status_cards(providers)

    assert set(cards) == {"provider-1"}
    assert cards["provider-1"]["error"] == "Failed to build provider status card"
