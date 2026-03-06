"""Tests for provider streaming response parsing in api.main."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.main import ProviderCallError, _call_provider


class FakeResponse:
    def __init__(self, status_code=200, chunks=None, body=b""):
        self.status_code = status_code
        self._chunks = chunks or []
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk

    async def aread(self):
        return self._body


class FakeClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, *args, **kwargs):
        return self._response


def install_streaming_client(monkeypatch, response):
    @asynccontextmanager
    async def fake_get_streaming_client(timeout=600.0):
        yield FakeClient(response)

    monkeypatch.setattr("api.main.get_streaming_client", fake_get_streaming_client)


@pytest.mark.asyncio
async def test_call_provider_uses_error_field_and_retryable(monkeypatch):
    response = FakeResponse(
        chunks=[
            b'{"status":"queued"}\n',
            b'{"status":"error","error":"beam upstream failed","retryable":true}\n',
        ]
    )
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())

    with pytest.raises(ProviderCallError) as exc_info:
        await _call_provider(
            worker_url="http://worker",
            workflow={"nodes": {}},
            job_id="job-1",
            job_service=job_service,
            total_nodes=1,
            timeout=5.0,
        )

    assert str(exc_info.value) == "beam upstream failed"
    assert exc_info.value.is_retryable is True
    job_service.update_job.assert_awaited_once_with("job-1", message="Queued in ComfyUI...")


@pytest.mark.asyncio
async def test_call_provider_tolerates_malformed_lines_and_chunk_boundaries(monkeypatch):
    response = FakeResponse(
        chunks=[
            b'{"status":"queued"}\nnot-json\n{"status":"executing","node":"1"}\n{"st',
            b'atus":"success","images":[{"filename":"a.png"}]}\n',
        ]
    )
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())

    result = await _call_provider(
        worker_url="http://worker",
        workflow={"nodes": {"1": {}}},
        job_id="job-2",
        job_service=job_service,
        total_nodes=4,
        timeout=5.0,
    )

    assert result["status"] == "success"
    assert result["images"][0]["filename"] == "a.png"
    assert job_service.update_job.await_count == 2


@pytest.mark.asyncio
async def test_call_provider_formats_http_error_payload(monkeypatch):
    response = FakeResponse(
        status_code=502,
        body=b'{"message":"upstream unavailable"}',
    )
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())

    with pytest.raises(ProviderCallError) as exc_info:
        await _call_provider(
            worker_url="http://worker",
            workflow={"nodes": {}},
            job_id="job-3",
            job_service=job_service,
            total_nodes=0,
            timeout=5.0,
        )

    assert str(exc_info.value) == "Worker returned 502: upstream unavailable"
    assert exc_info.value.is_retryable is True
    job_service.update_job.assert_not_called()