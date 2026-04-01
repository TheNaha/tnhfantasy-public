import pytest
from unittest.mock import AsyncMock, MagicMock

from provider_core.reconciliation import batch_update_file_status_v2
from provider_core.state import ReconciliationState


def test_reconciliation_state_schema_is_stable():
    state = ReconciliationState("beam-primary")
    state.start_reconciliation()
    state.set_phase("downloading")
    state.set_message("Downloading models")
    state.set_active_downloads([{"file_id": 1, "name": "model-a"}])

    payload = state.to_dict()
    stats = payload["stats"]

    assert payload["provider_id"] == "beam-primary"
    assert payload["status"] == "reconciling"
    assert payload["phase"] == "downloading"
    assert payload["message"] == "Downloading models"
    assert payload["active_downloads"] == [{"file_id": 1, "name": "model-a"}]
    assert "total_models_in_storage" in stats
    assert "total_models_in_modal" not in stats
    assert "invalid_cleaned" in stats
    assert "missing_reported" in stats


@pytest.mark.asyncio
async def test_batch_update_file_status_v2_chunks_large_payloads():
    updates = [{"storage_path": f"models/checkpoints/file-{i}.safetensors", "status": "pending"} for i in range(501)]

    response_one = MagicMock()
    response_one.status_code = 200
    response_one.json.return_value = {"updated": 500, "failed": 0}

    response_two = MagicMock()
    response_two.status_code = 200
    response_two.json.return_value = {"updated": 1, "failed": 0}

    http_client = AsyncMock()
    http_client.post = AsyncMock(side_effect=[response_one, response_two])

    await batch_update_file_status_v2(
        "http://backend",
        "beam-primary",
        updates,
        http_client=http_client,
    )

    assert http_client.post.await_count == 2
    first_payload = http_client.post.await_args_list[0].kwargs["json"]
    second_payload = http_client.post.await_args_list[1].kwargs["json"]
    assert len(first_payload["updates"]) == 500
    assert len(second_payload["updates"]) == 1
