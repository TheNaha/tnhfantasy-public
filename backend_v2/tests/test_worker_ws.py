import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect

from api.routes.worker_ws import connected_workers, worker_websocket
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
    yield
    connected_workers.clear()


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

    with patch("infrastructure.database.get_session_context", side_effect=_fake_session_context), \
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

    with patch("infrastructure.database.get_session_context", side_effect=_fake_session_context), \
         patch("services.provider_service.ProviderService", return_value=provider_service):
        await worker_websocket(websocket, "provider-a", "bad-token")

    assert websocket.accepted is False
    assert websocket.closed == (4002, "Invalid token")


@pytest.mark.asyncio
async def test_worker_websocket_finalization_uses_output_filenames():
    outputs = [{"filename": "image-1.png", "subfolder": "2026/03/06"}]
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
    gallery_indexer.get_path_by_filename.return_value = "/app/output/2026/03/06/image-1.png"

    with patch("infrastructure.database.get_session_context", side_effect=_fake_session_context), \
         patch("services.provider_service.ProviderService", return_value=provider_service), \
         patch("services.job_service.JobService", return_value=job_service), \
         patch("api.routes.statistics.gallery_indexer", gallery_indexer), \
         patch("api.routes.websocket.broadcast_to_room", new=AsyncMock()) as broadcast_mock:
        await worker_websocket(websocket, "provider-a", "token-1")
        await asyncio.sleep(0.01)

    assert websocket.accepted is True
    gallery_indexer.get_path_by_filename.assert_called_with("image-1.png")
    job_service.update_job.assert_any_await(
        "job-1",
        status=JobStatus.POST_PROCESSING,
        outputs=outputs,
    )
    job_service.update_job.assert_any_await(
        "job-1",
        status=JobStatus.COMPLETED,
    )
    broadcast_mock.assert_any_await(
        "job",
        "job.completed",
        {"job_id": "job-1", "provider_id": "provider-a", "outputs": outputs},
    )

