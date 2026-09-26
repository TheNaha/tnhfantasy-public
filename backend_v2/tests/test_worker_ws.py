import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect

from api.routes.worker_ws import (
    dispatch_job_to_worker,
    is_worker_connected,
    request_worker_job_cancel,
    worker_websocket,
)
from core.entities import JobStatus
from core.exceptions import NotFoundError
from infrastructure.worker_registry import (
    ConnectedWorker,
    connected_workers,
    pending_job_futures,
)
from services.provider_client import ProviderCallError


class DummyWebSocket:
    def __init__(self, messages=None):
        self._messages = list(messages or [])
        self.accepted = False
        self.closed = None
        self.sent = []

    async def close(self, code: int, reason: str = ""):
        self.closed = (code, reason)

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        self.sent.append(payload)

    async def receive_json(self):
        if self._messages:
            return self._messages.pop(0)
        raise WebSocketDisconnect(code=1000)


@pytest.fixture(autouse=True)
def clear_connected_workers():
    connected_workers.clear()
    pending_job_futures.clear()
    yield
    connected_workers.clear()
    pending_job_futures.clear()


def _fake_session_context(session=None):
    @asynccontextmanager
    async def _ctx():
        yield session if session is not None else MagicMock()
    return _ctx()


def _owned_session(provider_id="provider-a"):
    """A session whose session.get(Job, ...) resolves to a job owned by `provider_id`.

    _worker_owns_job is called before every job_* message is processed, and it
    now requires an exact provider match.  Previously a bare MagicMock slipped
    through an unreachable `isinstance(job, Job)` fallthrough, so tests passed
    without ever declaring job ownership.
    """
    session = MagicMock()
    session.get.return_value = SimpleNamespace(provider_id=provider_id)
    return session


@pytest.mark.asyncio
async def test_worker_websocket_closes_when_provider_missing():
    websocket = DummyWebSocket()
    provider_service = AsyncMock()
    provider_service.get_provider.side_effect = NotFoundError("Provider", "missing")

    with patch("api.routes.worker_ws.get_session_context", side_effect=_fake_session_context), \
         patch("services.provider_service.ProviderService", return_value=provider_service):
        await worker_websocket(websocket, "missing", "token")

    assert websocket.accepted is False
    assert websocket.closed == (4001, "Provider not found")


@pytest.mark.asyncio
async def test_worker_websocket_closes_when_token_is_invalid():
    websocket = DummyWebSocket()
    provider = SimpleNamespace(config={"worker_token": "expected-token"})
    provider_service = AsyncMock()
    provider_service.get_provider.return_value = provider

    with patch("api.routes.worker_ws.get_session_context", side_effect=_fake_session_context), \
         patch("services.provider_service.ProviderService", return_value=provider_service):
        await worker_websocket(websocket, "provider-a", "bad-token")

    assert websocket.accepted is False
    assert websocket.closed == (4002, "Invalid token")


@pytest.mark.asyncio
async def _await_inline(coro, **kw):
    # Await the finalize coroutine inline so the test can assert completion
    # without racing the event loop teardown.
    await coro


async def test_worker_websocket_finalization_uses_output_filenames():
    outputs = [{"filename": "image-1.png", "relative_path": "2026/03/06/image-1.png", "subfolder": "2026/03/06"}]
    websocket = DummyWebSocket(
        messages=[
            {
                "type": "job_completed",
                "job_id": "job-1",
                "result": {"outputs": outputs},
            }
        ]
    )
    provider = SimpleNamespace(config={"worker_token": "token-1"})
    provider_service = AsyncMock()
    provider_service.get_provider.return_value = provider
    job_service = AsyncMock()

    finalize = AsyncMock()
    with patch("api.routes.worker_ws.get_session_context", side_effect=lambda *a, **k: _fake_session_context(_owned_session())), \
         patch("services.provider_service.ProviderService", return_value=provider_service), \
         patch("services.job_service.JobService", return_value=job_service), \
         patch("services.job_processing.finalize_successful_job", finalize), \
         patch("services.asset_reconciler.reconcile_asset", MagicMock()), \
         patch("services.job_processing.wait_for_gallery_outputs", AsyncMock()):
        await worker_websocket(websocket, "provider-a", "token-1")
        await asyncio.sleep(0.05)

    assert websocket.accepted is True
    finalize.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_websocket_rejects_unpersisted_outputs():
    websocket = DummyWebSocket(
        messages=[
            {
                "type": "job_completed",
                "job_id": "job-2",
                "result": {"outputs": ["image-1.png"]},
            }
        ]
    )
    provider = SimpleNamespace(config={"worker_token": "token-1"})
    provider_service = AsyncMock()
    provider_service.get_provider.return_value = provider
    job_service = AsyncMock()

    with patch("api.routes.worker_ws.get_session_context", side_effect=lambda *a, **k: _fake_session_context(_owned_session())), \
         patch("services.provider_service.ProviderService", return_value=provider_service), \
         patch("services.job_service.JobService", return_value=job_service):
        await worker_websocket(websocket, "provider-a", "token-1")

    job_service.update_job.assert_any_await(
        "job-2",
        status=JobStatus.FAILED,
        error="External worker outputs must be structured objects",
    )


@pytest.mark.asyncio
async def test_worker_websocket_normalizes_progress_updates():
    websocket = DummyWebSocket(
        messages=[
            {
                "type": "job_progress",
                "job_id": "job-3",
                "data": {
                    "progress": 42,
                    "message": "Rendering node 7",
                },
            }
        ]
    )
    provider = SimpleNamespace(config={"worker_token": "token-1"})
    provider_service = AsyncMock()
    provider_service.get_provider.return_value = provider
    job_service = AsyncMock()

    with patch("api.routes.worker_ws.get_session_context", side_effect=lambda *a, **k: _fake_session_context(_owned_session())), \
         patch("services.provider_service.ProviderService", return_value=provider_service), \
         patch("services.job_service.JobService", return_value=job_service):
        await worker_websocket(websocket, "provider-a", "token-1")

    job_service.update_job.assert_awaited_with(
        "job-3",
        progress=42,
        overall_progress=42,
        message="Rendering node 7",
    )


@pytest.mark.asyncio
async def test_dispatch_job_to_worker_sends_job_and_waits_for_result():
    websocket = DummyWebSocket()
    connected_workers["provider-a"] = ConnectedWorker(websocket, "provider-a")

    dispatch_task = asyncio.create_task(
        dispatch_job_to_worker(
            "provider-a",
            {"id": "job-4", "workflow": {"1": {}}, "metadata": {}},
            timeout=1.0,
        )
    )
    await asyncio.sleep(0)

    future = pending_job_futures["job-4"]
    future.set_result({"__handled_by_external_worker": True, "outputs": []})

    result = await dispatch_task

    assert result["__handled_by_external_worker"] is True
    assert websocket.sent == [{
        "type": "job",
        "data": {"id": "job-4", "workflow": {"1": {}}, "metadata": {}},
    }]


@pytest.mark.asyncio
async def test_request_worker_job_cancel_sends_cancel_message():
    websocket = DummyWebSocket()
    connected_workers["provider-a"] = ConnectedWorker(websocket, "provider-a")

    cancelled = await request_worker_job_cancel("provider-a", "job-5")

    assert cancelled is True
    assert websocket.sent == [{
        "type": "cancel_job",
        "job_id": "job-5",
    }]


@pytest.mark.asyncio
async def test_dispatch_rejects_stale_worker_connection():
    websocket = DummyWebSocket()
    worker = ConnectedWorker(websocket, "provider-a")
    worker.last_heartbeat = worker.last_heartbeat - timedelta(seconds=120)
    connected_workers["provider-a"] = worker

    assert is_worker_connected("provider-a") is False

    with pytest.raises(ProviderCallError, match="No external worker connected"):
        await dispatch_job_to_worker(
            "provider-a",
            {"id": "job-6", "workflow": {"1": {}}, "metadata": {}},
            timeout=1.0,
        )


class TestCoercePercent:
    """jobs.progress is percent 0..100 with a CHECK constraint (migration 047).

    An out-of-range write raised IntegrityError inside the session context,
    which propagated to the socket-level handler and closed the whole worker
    socket, leaving the job non-terminal. _coerce_percent makes that
    impossible for both the canonical and the legacy payload shapes.
    """

    def test_clamps_legacy_fraction(self):
        from api.routes.worker_ws import _coerce_percent
        assert _coerce_percent(0.5) == 50
        assert _coerce_percent(0) == 0

    def test_passes_through_percent(self):
        from api.routes.worker_ws import _coerce_percent
        assert _coerce_percent(42) == 42
        assert _coerce_percent(42.9) == 42
        assert _coerce_percent(100) == 100

    def test_clamps_out_of_range(self):
        from api.routes.worker_ws import _coerce_percent
        assert _coerce_percent(150) == 100
        assert _coerce_percent(-5) == 0
        assert _coerce_percent(1e9) == 100

    def test_garbage_becomes_zero(self):
        from api.routes.worker_ws import _coerce_percent
        assert _coerce_percent("nonsense") == 0
        assert _coerce_percent(None) == 0
        assert _coerce_percent(float("nan")) == 0


@pytest.mark.asyncio
async def test_worker_cannot_claim_job_owned_by_another_provider():
    """A job must only accept events from the provider it was assigned to."""
    websocket = DummyWebSocket(
        messages=[
            {
                "type": "job_progress",
                "job_id": "job-owned-elsewhere",
                "data": {"progress": 50, "message": "nope"},
            }
        ]
    )
    provider = SimpleNamespace(config={"worker_token": "token-1"})
    provider_service = AsyncMock()
    provider_service.get_provider.return_value = provider
    job_service = AsyncMock()

    with patch(
        "api.routes.worker_ws.get_session_context",
        side_effect=lambda *a, **k: _fake_session_context(
            _owned_session(provider_id="provider-b")
        ),
    ), patch("services.provider_service.ProviderService", return_value=provider_service), \
         patch("services.job_service.JobService", return_value=job_service):
        await worker_websocket(websocket, "provider-a", "token-1")

    job_service.update_job.assert_not_awaited()
    assert any(
        isinstance(sent, dict) and "not assigned" in str(sent.get("message", ""))
        for sent in websocket.sent
    )


@pytest.mark.asyncio
async def test_worker_cannot_claim_unassigned_job():
    """provider_id IS NULL must not make a job claimable by any worker."""
    websocket = DummyWebSocket(
        messages=[
            {
                "type": "job_completed",
                "job_id": "job-unassigned",
                "result": {"outputs": []},
            }
        ]
    )
    provider = SimpleNamespace(config={"worker_token": "token-1"})
    provider_service = AsyncMock()
    provider_service.get_provider.return_value = provider
    job_service = AsyncMock()

    finalize = AsyncMock()
    session = MagicMock()
    session.get.return_value = SimpleNamespace(provider_id=None)
    with patch(
        "api.routes.worker_ws.get_session_context",
        side_effect=lambda *a, **k: _fake_session_context(session),
    ), patch("services.provider_service.ProviderService", return_value=provider_service), \
         patch("services.job_service.JobService", return_value=job_service), \
         patch("services.job_processing.finalize_successful_job", finalize):
        await worker_websocket(websocket, "provider-a", "token-1")

    finalize.assert_not_awaited()
