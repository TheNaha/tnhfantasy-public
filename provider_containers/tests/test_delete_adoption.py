"""A `success: false` upstream must not be reported as a successful delete.

Reconciliation's delete callback contract is a boolean, and
`run_reconciliation_v2` increments `deletions_completed` on True
(provider_core/reconciliation.py:621-625). Both remote backends returned an
unconditional `True`:

    image_worker/engines/beam/client.py     -> `response.raise_for_status(); return True`
    image_worker/engines/remote_comfy/client.py -> the same

but neither remote answers a refusal with a status code. Beam's storage app
returns `outcome(False, ...)` — HTTP 200 with `success: false` — and the remote
agent returns `{"success": false, "message": "File not found"}` with HTTP 200
(remote_agent/server.py:262-263). So with `RECONCILIATION_DELETE_ORPHANS=true`
the worker reported a clean sweep for every orphan it "removed" while the bytes
stayed on the volume, and the volume filled with un-reclaimable multi-GB
checkpoints. Beam's PUBLIC `delete_model` already adopted the flag
(beam/client.py:261-265); the reconciliation closure deliberately did not.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from provider_core.reconciliation import run_reconciliation_v2
from provider_core.state import ReconciliationState


def _upstream_response(status_code: int, payload: dict) -> MagicMock:
    response = MagicMock(status_code=status_code)
    response.json.return_value = payload
    response.text = json.dumps(payload)
    # A real httpx response raises; the point of the fix is that the client must
    # not be relying on that to learn the answer.
    response.raise_for_status.side_effect = AssertionError(
        "raise_for_status() discards the upstream's own success flag"
    )
    return response


async def _run_delete_phase(delete_file, monkeypatch, storage_paths: set[str], expected_paths: set[str]):
    """Drive run_reconciliation_v2 to its delete phase and return the state.

    `expected_paths` must be non-empty: reconciliation refuses to delete anything
    when the backend has no expected paths at all, treating it as "the database is
    empty, so everything is an orphan" (calculate_safe_deletion_limit's guard). The
    callers pass one path that is expected-but-absent, which is exactly the shape
    of a real orphan sweep.
    """
    monkeypatch.setenv("RECONCILIATION_DELETE_ORPHANS", "true")
    state = ReconciliationState("test-provider")

    monkeypatch.setattr(
        "provider_core.reconciliation.get_pending_downloads", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        "provider_core.reconciliation.get_all_expected_paths",
        AsyncMock(return_value=expected_paths),
    )
    monkeypatch.setattr("provider_core.reconciliation.batch_update_file_status_v2", AsyncMock())
    monkeypatch.setattr("provider_core.reconciliation.report_file_status_v2", AsyncMock())
    monkeypatch.setattr(
        "provider_core.reconciliation.push_reconciliation_event", AsyncMock(return_value=True)
    )
    # Nothing registers, so the orphans are genuine deletion candidates.
    monkeypatch.setattr(
        "provider_core.reconciliation.register_discovered_files",
        AsyncMock(return_value={"imported": 0, "failed": 1}),
    )

    await run_reconciliation_v2(
        provider_id="test-provider",
        backend_url="http://backend",
        reconciliation_state=state,
        max_concurrent_downloads=2,
        hf_token="",
        civitai_token="",
        storage_label="Test",
        validate_existing=AsyncMock(return_value={"total_invalid": 0, "total_partial": 0}),
        list_existing_files=AsyncMock(
            return_value={path: {"size": 4096} for path in storage_paths}
        ),
        download_file=AsyncMock(),
        delete_file=delete_file,
    )
    return state


# Present in the database but NOT on provider storage. Every deletion test keeps
# this as its only expected path, so the orphan under test is a real orphan and
# the "no expected paths -> delete nothing" safety guard stays satisfied.
_KEPT_PATH = "models/loras/kept.safetensors"


# ── the callbacks themselves ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_beam_delete_callback_adopts_success_false(monkeypatch):
    """HTTP 200 + `success: false` is a refusal, not a deletion."""
    import image_worker.engines.beam.client as beam_client

    client = beam_client.BeamProviderClient(runtime_config={})
    # _start_reconciliation_task spawns the flow; capture the callback it is given.
    captured = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return {"status": "started"}

    monkeypatch.setattr(client, "_start_reconciliation_task", _capture)
    await client.run_reconciliation()

    http = MagicMock()
    http.post = AsyncMock(
        return_value=_upstream_response(200, {"status": "error", "success": False, "message": "Not found: x"})
    )
    monkeypatch.setattr(beam_client, "get_http_client", lambda: http)

    assert await captured["delete_file_fn"]("models/checkpoints/x.safetensors") is False


@pytest.mark.asyncio
async def test_beam_delete_callback_adopts_success_true(monkeypatch):
    import image_worker.engines.beam.client as beam_client

    client = beam_client.BeamProviderClient(runtime_config={})
    captured = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return {"status": "started"}

    monkeypatch.setattr(client, "_start_reconciliation_task", _capture)
    await client.run_reconciliation()

    http = MagicMock()
    http.post = AsyncMock(return_value=_upstream_response(200, {"status": "success", "success": True}))
    monkeypatch.setattr(beam_client, "get_http_client", lambda: http)

    assert await captured["delete_file_fn"]("models/checkpoints/x.safetensors") is True


@pytest.mark.asyncio
async def test_remote_comfy_delete_callback_adopts_success_false(monkeypatch):
    import image_worker.engines.remote_comfy.client as rc_client

    monkeypatch.setenv("REMOTE_AGENT_TOKEN", "test-token")
    client = rc_client.RemoteComfyProviderClient(runtime_config={})
    captured = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return {"status": "started"}

    monkeypatch.setattr(client, "_start_reconciliation_task", _capture)
    await client.run_reconciliation()

    http = MagicMock()
    http.post = AsyncMock(
        # Exactly the agent's /delete-model body for a missing file (server.py:262-263).
        return_value=_upstream_response(200, {"success": False, "message": "File not found"})
    )
    monkeypatch.setattr(rc_client, "get_http_client", lambda: http)

    assert await captured["delete_file_fn"]("models/checkpoints/x.safetensors") is False


@pytest.mark.asyncio
async def test_remote_comfy_delete_callback_adopts_success_true(monkeypatch):
    import image_worker.engines.remote_comfy.client as rc_client

    client = rc_client.RemoteComfyProviderClient(runtime_config={})
    captured = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return {"status": "started"}

    monkeypatch.setattr(client, "_start_reconciliation_task", _capture)
    await client.run_reconciliation()

    http = MagicMock()
    http.post = AsyncMock(return_value=_upstream_response(200, {"success": True}))
    monkeypatch.setattr(rc_client, "get_http_client", lambda: http)

    assert await captured["delete_file_fn"]("models/checkpoints/x.safetensors") is True


# ── and the consequence for the reconciliation counters ─────────────────────


@pytest.mark.asyncio
async def test_a_refused_delete_is_not_counted_as_a_deletion(monkeypatch):
    """`success: false` must not increment `deletions_completed`."""
    orphan = "models/checkpoints/orphan.safetensors"
    state = await _run_delete_phase(
        AsyncMock(return_value=False), monkeypatch, {orphan}, expected_paths={_KEPT_PATH}
    )
    assert state.get_stats()["deletions_completed"] == 0
    assert state.status == "completed"


@pytest.mark.asyncio
async def test_a_successful_delete_is_counted(monkeypatch):
    orphan = "models/checkpoints/orphan.safetensors"
    delete_file = AsyncMock(return_value=True)
    state = await _run_delete_phase(delete_file, monkeypatch, {orphan}, expected_paths={_KEPT_PATH})
    assert state.get_stats()["deletions_completed"] == 1
    delete_file.assert_awaited_once_with(orphan)


@pytest.mark.asyncio
async def test_a_refused_delete_does_not_abort_the_sweep(monkeypatch):
    """`deleted is False` is a `continue`, not a raise: the rest still run."""
    refused = "models/checkpoints/refused.safetensors"
    removed = "models/checkpoints/removed.safetensors"
    outcomes = {refused: False, removed: True}

    state = await _run_delete_phase(
        AsyncMock(side_effect=lambda path: outcomes[path]),
        monkeypatch,
        storage_paths={refused, removed},
        expected_paths={_KEPT_PATH},
    )
    # Both paths were on storage; the refused one is skipped, the other deleted.
    assert state.get_stats()["deletions_completed"] == 1


# ── and the PUBLIC delete_model routes ───────────────────────────────────────


@pytest.mark.asyncio
async def test_remote_comfy_delete_model_reports_the_agents_refusal(monkeypatch):
    """Finding: `outcome(True, ...)` invented success for a delete the agent refused.

    The agent answers `{"success": false, "message": "File not found"}` with HTTP
    200. The old code returned `outcome(True, "Deleted ...")`, so the backend
    dropped the provider-file row while the file stayed on the rig.
    """
    from provider_core.models import DeleteModelRequest
    import image_worker.engines.remote_comfy.client as rc_client

    client = rc_client.RemoteComfyProviderClient(runtime_config={})
    http = MagicMock()
    http.post = AsyncMock(return_value=_upstream_response(200, {"success": False, "message": "File not found"}))
    monkeypatch.setattr(rc_client, "get_http_client", lambda: http)

    payload = await client.delete_model(DeleteModelRequest(path="models/checkpoints/gone.safetensors"))
    assert payload["success"] is False
    assert payload["status"] == "error"
    assert "not found" in payload["message"].lower()


@pytest.mark.asyncio
async def test_remote_comfy_delete_model_reports_success(monkeypatch):
    from provider_core.models import DeleteModelRequest
    import image_worker.engines.remote_comfy.client as rc_client

    client = rc_client.RemoteComfyProviderClient(runtime_config={})
    http = MagicMock()
    http.post = AsyncMock(return_value=_upstream_response(200, {"success": True}))
    monkeypatch.setattr(rc_client, "get_http_client", lambda: http)

    payload = await client.delete_model(DeleteModelRequest(path="models/checkpoints/gone.safetensors"))
    assert payload["success"] is True


@pytest.mark.asyncio
async def test_beam_delete_model_already_adopted_this_and_still_does(monkeypatch):
    """The sibling that had the fix must keep it."""
    from provider_core.models import DeleteModelRequest
    import image_worker.engines.beam.client as beam_client

    client = beam_client.BeamProviderClient(runtime_config={})
    http = MagicMock()
    http.post = AsyncMock(return_value=_upstream_response(200, {"status": "error", "success": False, "message": "Not found"}))
    monkeypatch.setattr(beam_client, "get_http_client", lambda: http)

    payload = await client.delete_model(DeleteModelRequest(path="models/checkpoints/gone.safetensors"))
    assert payload["success"] is False


@pytest.mark.asyncio
async def test_delete_file_never_raises_on_a_refusal(monkeypatch):
    """`delete_file` delegates to `delete_model`, so it must inherit the adoption."""
    import image_worker.engines.remote_comfy.client as rc_client

    client = rc_client.RemoteComfyProviderClient(runtime_config={})
    http = MagicMock()
    http.post = AsyncMock(return_value=_upstream_response(200, {"success": False, "message": "File not found"}))
    monkeypatch.setattr(rc_client, "get_http_client", lambda: http)

    payload = await client.delete_file("models/checkpoints/gone.safetensors")
    assert payload["success"] is False
