from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.provider_status_service import (
    ProviderStatusService,
    invalidate_provider_status_caches,
)


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


@pytest.mark.asyncio
async def test_get_provider_storage_stats_prefers_reconciliation_stats_without_worker_poll():
    invalidate_provider_status_caches()
    service = ProviderStatusService(session=MagicMock(), provider_service=MagicMock())

    state = {
        "status": "reconciling",
        "stats": {
            "total_models_in_storage": 7,
        },
    }

    with patch("services.provider_status_service.get_http_client") as get_http_client:
        result = await service.get_provider_storage_stats(
            "provider-a",
            reconciliation_state=state,
        )

    assert result == {
        "provider_id": "provider-a",
        "total": 7,
        "by_directory": {},
    }
    get_http_client.assert_not_called()


@pytest.mark.asyncio
async def test_get_provider_storage_stats_reconciliation_state_overrides_stale_cache():
    invalidate_provider_status_caches()
    service = ProviderStatusService(session=MagicMock(), provider_service=MagicMock())

    # Prime cache with stale totals.
    stale_state = {
        "status": "reconciling",
        "stats": {
            "total_models_in_storage": 2,
            "by_directory": {"checkpoints": 2},
        },
    }
    _ = await service.get_provider_storage_stats("provider-cache", reconciliation_state=stale_state)

    fresh_state = {
        "status": "reconciling",
        "stats": {
            "total_models_in_storage": 9,
            "by_directory": {"checkpoints": 4, "loras": 5},
        },
    }

    with patch("services.provider_status_service.get_http_client") as get_http_client:
        result = await service.get_provider_storage_stats(
            "provider-cache",
            reconciliation_state=fresh_state,
        )

    assert result == {
        "provider_id": "provider-cache",
        "total": 9,
        "by_directory": {"checkpoints": 4, "loras": 5},
    }
    get_http_client.assert_not_called()


@pytest.mark.asyncio
async def test_get_provider_storage_stats_uses_cache_when_reconciliation_stats_missing():
    invalidate_provider_status_caches()
    service = ProviderStatusService(session=MagicMock(), provider_service=MagicMock())

    cached = await service.get_provider_storage_stats(
        "provider-cache-fallback",
        reconciliation_state={
            "status": "reconciling",
            "stats": {"total_models_in_storage": 3},
        },
    )

    with patch("services.provider_status_service.get_http_client") as get_http_client:
        result = await service.get_provider_storage_stats(
            "provider-cache-fallback",
            reconciliation_state={"status": "reconciling", "stats": {}},
        )

    assert result == cached
    get_http_client.assert_not_called()


def test_storage_payload_from_reconciliation_state_uses_by_directory_sum_when_total_missing():
    payload = ProviderStatusService._storage_payload_from_reconciliation_state(
        "provider-b",
        {
            "stats": {
                "by_directory": {
                    "checkpoints": 2,
                    "loras": 3,
                }
            }
        },
    )

    assert payload == {
        "provider_id": "provider-b",
        "total": 5,
        "by_directory": {
            "checkpoints": 2,
            "loras": 3,
        },
    }


def test_storage_payload_from_reconciliation_state_preserves_explicit_zero_total():
    payload = ProviderStatusService._storage_payload_from_reconciliation_state(
        "provider-zero",
        {
            "stats": {
                "total_models_in_storage": 0,
            }
        },
    )

    assert payload == {
        "provider_id": "provider-zero",
        "total": 0,
        "by_directory": {},
    }
