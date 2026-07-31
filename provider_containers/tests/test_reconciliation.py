import pytest
from unittest.mock import AsyncMock, MagicMock

from provider_core.reconciliation import batch_update_file_status_v2, push_reconciliation_event, run_reconciliation_v2
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


@pytest.mark.asyncio
async def test_push_reconciliation_event_retries_until_success(monkeypatch):
    response = MagicMock()
    response.status_code = 200

    http_client = AsyncMock()
    http_client.post = AsyncMock(side_effect=[RuntimeError("dns lookup failed"), response])

    sleep_mock = AsyncMock()
    monkeypatch.setattr("provider_core.reconciliation.asyncio.sleep", sleep_mock)

    delivered = await push_reconciliation_event(
        backend_url="http://backend",
        provider_id="modal-step",
        status="reconciling",
        phase="fetching",
        http_client=http_client,
        retry_attempts=2,
        retry_backoff_seconds=0.01,
    )

    assert delivered is True
    assert http_client.post.await_count == 2
    sleep_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_push_reconciliation_event_returns_false_after_exhausting_retries(monkeypatch):
    response = MagicMock()
    response.status_code = 503

    http_client = AsyncMock()
    http_client.post = AsyncMock(return_value=response)

    sleep_mock = AsyncMock()
    monkeypatch.setattr("provider_core.reconciliation.asyncio.sleep", sleep_mock)

    delivered = await push_reconciliation_event(
        backend_url="http://backend",
        provider_id="modal-step",
        status="reconciling",
        phase="fetching",
        http_client=http_client,
        retry_attempts=3,
        retry_backoff_seconds=0.01,
    )

    assert delivered is False
    assert http_client.post.await_count == 3
    assert sleep_mock.await_count == 2


@pytest.mark.asyncio
async def test_run_reconciliation_v2_marks_existing_pending_files_ready(monkeypatch):
    state = ReconciliationState("modal-primary")
    pending_file = {
        "file_id": 1,
        "model_name": "Model A",
        "version_name": "v1",
        "storage_path": "models/checkpoints/model-a.safetensors",
        "download_url": "https://huggingface.co/model-a",
        "size_kb": 2,
    }

    monkeypatch.setattr(
        "provider_core.reconciliation.get_pending_downloads",
        AsyncMock(return_value=[pending_file]),
    )
    monkeypatch.setattr(
        "provider_core.reconciliation.get_all_expected_paths",
        AsyncMock(return_value={pending_file["storage_path"]}),
    )
    batch_update = AsyncMock()
    monkeypatch.setattr("provider_core.reconciliation.batch_update_file_status_v2", batch_update)
    monkeypatch.setattr("provider_core.reconciliation.report_file_status_v2", AsyncMock())
    monkeypatch.setattr("provider_core.reconciliation.push_reconciliation_event", AsyncMock(return_value=True))

    validate_existing = AsyncMock(return_value={"total_invalid": 0, "total_partial": 0})
    list_existing_files = AsyncMock(return_value={pending_file["storage_path"]: {"size": pending_file["size_kb"] * 1024, "modified_at": 12345}})
    download_file = AsyncMock()
    delete_file = AsyncMock()

    await run_reconciliation_v2(
        provider_id="modal-primary",
        backend_url="http://backend",
        reconciliation_state=state,
        max_concurrent_downloads=2,
        hf_token="hf-token",
        civitai_token="",
        storage_label="Modal",
        validate_existing=validate_existing,
        list_existing_files=list_existing_files,
        download_file=download_file,
        delete_file=delete_file,
    )

    assert state.status == "completed"
    assert state.get_stats()["downloads_completed"] == 0
    assert batch_update.await_count == 1
    updates = batch_update.await_args.args[2]
    assert updates == [{"file_id": 1, "status": "ready", "storage_path": pending_file["storage_path"]}]
    download_file.assert_not_awaited()
    delete_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_reconciliation_v2_downloads_missing_files_and_deletes_orphans(monkeypatch):
    monkeypatch.setenv("RECONCILIATION_DELETE_ORPHANS", "true")
    state = ReconciliationState("beam-primary")
    pending_file = {
        "file_id": 7,
        "model_name": "Model B",
        "version_name": "v2",
        "storage_path": "models/loras/model-b.safetensors",
        "download_url": "https://civitai.com/model-b",
        "size_kb": 4,
    }
    orphan_path = "models/loras/orphan.safetensors"

    monkeypatch.setattr(
        "provider_core.reconciliation.get_pending_downloads",
        AsyncMock(side_effect=[[pending_file], [pending_file]]),
    )
    monkeypatch.setattr(
        "provider_core.reconciliation.get_all_expected_paths",
        AsyncMock(return_value={pending_file["storage_path"]}),
    )
    monkeypatch.setattr("provider_core.reconciliation.batch_update_file_status_v2", AsyncMock())
    report_status = AsyncMock()
    monkeypatch.setattr("provider_core.reconciliation.report_file_status_v2", report_status)
    monkeypatch.setattr("provider_core.reconciliation.push_reconciliation_event", AsyncMock(return_value=True))
    monkeypatch.setattr("provider_core.reconciliation.register_discovered_files", AsyncMock(return_value={"imported": 0, "failed": 1}))

    validate_existing = AsyncMock(return_value={"total_invalid": 1, "total_partial": 0})
    list_existing_files = AsyncMock(return_value={orphan_path: {"size": 4096, "modified_at": 12345}})
    download_file = AsyncMock()
    delete_file = AsyncMock(return_value=True)

    await run_reconciliation_v2(
        provider_id="beam-primary",
        backend_url="http://backend",
        reconciliation_state=state,
        max_concurrent_downloads=3,
        hf_token="",
        civitai_token="civitai-token",
        storage_label="Beam",
        validate_existing=validate_existing,
        list_existing_files=list_existing_files,
        download_file=download_file,
        delete_file=delete_file,
    )

    assert state.status == "completed"
    assert state.get_stats()["downloads_completed"] == 1
    assert state.get_stats()["deletions_completed"] == 1
    download_file.assert_awaited_once_with(
        pending_file["download_url"],
        pending_file["storage_path"],
        "civitai-token",
    )
    delete_file.assert_awaited_once_with(orphan_path)
    statuses = [call.args[3] for call in report_status.await_args_list]
    assert "downloading" in statuses
    assert "ready" in statuses
