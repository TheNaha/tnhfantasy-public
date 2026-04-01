import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect

from api.routes.worker_ws import (
    ConnectedWorker,
    connected_workers,
    dispatch_job_to_worker,
    pending_job_futures,
    request_worker_job_cancel,
    worker_websocket,
)
from core.entities import JobStatus
from core.exceptions import NotFoundError


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


def _fake_session_context():
    @asynccontextmanager
    async def _ctx():
        yield MagicMock()
    return _ctx()


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
    gallery_indexer = MagicMock()
    gallery_indexer.get_path.return_value = "/app/output/2026/03/06/image-1.png"

    with patch("api.routes.worker_ws.get_session_context", side_effect=_fake_session_context), \
         patch("services.provider_service.ProviderService", return_value=provider_service), \
         patch("services.job_service.JobService", return_value=job_service), \
         patch("services.gallery_indexer.gallery_indexer", gallery_indexer):
        await worker_websocket(websocket, "provider-a", "token-1")
        await asyncio.sleep(0.05)

    assert websocket.accepted is True
    gallery_indexer.get_path.assert_called_with("2026/03/06/image-1.png")
    job_service.update_job.assert_any_await(
        "job-1",
        status=JobStatus.POST_PROCESSING,
        outputs=[{
            "type": "image",
            "filename": "image-1.png",
            "relative_path": "2026/03/06/image-1.png",
            "subfolder": "2026/03/06",
            "path": None,
            "thumbnail": None,
            "blurhash": None,
            "width": None,
            "height": None,
        }],
        progress=100,
        overall_progress=100,
        provider_id="provider-a",
    )
    job_service.update_job.assert_any_await(
        "job-1",
        status=JobStatus.COMPLETED,
        outputs=[{
            "type": "image",
            "filename": "image-1.png",
            "relative_path": "2026/03/06/image-1.png",
            "subfolder": "2026/03/06",
            "path": None,
            "thumbnail": None,
            "blurhash": None,
            "width": None,
            "height": None,
        }],
        progress=100,
        overall_progress=100,
        provider_id="provider-a",
    )


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

    with patch("api.routes.worker_ws.get_session_context", side_effect=_fake_session_context), \
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

    with patch("api.routes.worker_ws.get_session_context", side_effect=_fake_session_context), \
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
