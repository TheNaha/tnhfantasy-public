"""Tests for provider streaming response parsing in services.provider_client."""

from contextlib import asynccontextmanager
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx

from core.entities import JobStatus
from services.provider_client import JobCancelledError, ProviderCallError, call_provider


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
    def __init__(self, response, capture=None):
        self._response = response
        self._capture = capture

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, *args, **kwargs):
        if self._capture is not None:
            self._capture["args"] = args
            self._capture["kwargs"] = kwargs
        return self._response


def install_streaming_client(monkeypatch, response, capture=None):
    @asynccontextmanager
    async def fake_get_streaming_client(timeout=600.0):
        yield FakeClient(response, capture=capture)

    monkeypatch.setattr("services.provider_client.get_streaming_client", fake_get_streaming_client)


def build_provider_core_error_payload(message: str, *, retryable: bool = False):
    """Load provider_core error builder to ensure backend parser stays contract-compatible."""
    provider_containers_path = Path(__file__).resolve().parents[2] / "provider_containers"
    path_str = str(provider_containers_path)
    inserted = False
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
        inserted = True

    try:
        provider_models = importlib.import_module("provider_core.models")
        return provider_models.build_error_response(message, retryable=retryable)
    finally:
        if inserted:
            sys.path.remove(path_str)


@pytest.mark.asyncio
async def test_call_provider_uses_error_field_and_retryable(monkeypatch):
    response = FakeResponse(
        chunks=[
            b'{"status":"queued"}\n',
            b'{"status":"error","message":"beam upstream failed","retryable":true}\n',
        ]
    )
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())

    with pytest.raises(ProviderCallError) as exc_info:
        await call_provider(
            worker_url="http://worker",
            workflow={"nodes": {}},
            job_id="job-1",
            job_service=job_service,
            total_nodes=1,
            timeout=5.0,
            provider_id="provider-1",
        )

    assert str(exc_info.value) == "beam upstream failed"
    assert exc_info.value.provider_id == "provider-1"
    assert exc_info.value.is_retryable is True
    job_service.update_job.assert_any_call("job-1", status=JobStatus.PRE_GENERATION, message="Queued in ComfyUI...")


@pytest.mark.asyncio
async def test_call_provider_uses_details_message_field(monkeypatch):
    response = FakeResponse(
        chunks=[
            b'{"status":"queued"}\n',
            b'{"status":"error","message":"nested worker message","retryable":true}\n',
        ]
    )
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())

    with pytest.raises(ProviderCallError) as exc_info:
        await call_provider(
            worker_url="http://worker",
            workflow={"nodes": {}},
            job_id="job-details",
            job_service=job_service,
            total_nodes=1,
            timeout=5.0,
            provider_id="provider-details",
        )

    assert str(exc_info.value) == "nested worker message"
    assert exc_info.value.provider_id == "provider-details"
    assert exc_info.value.is_retryable is True
    job_service.update_job.assert_any_call("job-details", status=JobStatus.PRE_GENERATION, message="Queued in ComfyUI...")


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

    result = await call_provider(
        worker_url="http://worker",
        workflow={"nodes": {"1": {}}},
        job_id="job-2",
        job_service=job_service,
        total_nodes=4,
        timeout=5.0,
    )

    assert result["status"] == "success"
    assert result["images"][0]["filename"] == "a.png"
    assert job_service.update_job.await_count == 3


@pytest.mark.asyncio
async def test_call_provider_parses_success_without_trailing_newline(monkeypatch):
    response = FakeResponse(
        chunks=[
            b'{"status":"queued"}\n',
            b'{"status":"success","images":[{"filename":"tail.png"}]}'
        ]
    )
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())

    result = await call_provider(
        worker_url="http://worker",
        workflow={"nodes": {}},
        job_id="job-tail-success",
        job_service=job_service,
        total_nodes=0,
        timeout=5.0,
        provider_id="provider-tail",
    )

    assert result["status"] == "success"
    assert result["images"][0]["filename"] == "tail.png"
    job_service.update_job.assert_any_call("job-tail-success", status=JobStatus.PRE_GENERATION, message="Queued in ComfyUI...")


@pytest.mark.asyncio
async def test_call_provider_formats_http_error_payload(monkeypatch):
    response = FakeResponse(
        status_code=502,
        body=b'{"message":"upstream unavailable"}',
    )
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())

    with pytest.raises(ProviderCallError) as exc_info:
        await call_provider(
            worker_url="http://worker",
            workflow={"nodes": {}},
            job_id="job-3",
            job_service=job_service,
            total_nodes=0,
            timeout=5.0,
            provider_id="provider-3",
        )

    assert str(exc_info.value) == "Worker returned 502: upstream unavailable"
    assert exc_info.value.provider_id == "provider-3"
    assert exc_info.value.is_retryable is True
    job_service.update_job.assert_not_called()


@pytest.mark.asyncio
async def test_call_provider_invalid_success_payload_is_retryable(monkeypatch):
    response = FakeResponse(
        chunks=[
            b'{"status":"queued"}\n',
            b'{"status":"success","images":[{"data":"YWJj","_base64_encoded":true}]}\n',
        ]
    )
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())

    with pytest.raises(ProviderCallError) as exc_info:
        await call_provider(
            worker_url="http://worker",
            workflow={"nodes": {}},
            job_id="job-invalid-success",
            job_service=job_service,
            total_nodes=1,
            timeout=5.0,
            provider_id="provider-invalid-success",
        )

    assert "Invalid success payload" in str(exc_info.value)
    assert exc_info.value.provider_id == "provider-invalid-success"
    assert exc_info.value.is_retryable is True
    job_service.update_job.assert_any_call("job-invalid-success", status=JobStatus.PRE_GENERATION, message="Queued in ComfyUI...")


@pytest.mark.asyncio
async def test_call_provider_raises_job_cancelled_error(monkeypatch):
    response = FakeResponse(
        chunks=[
            b'{"status":"queued"}\n',
            b'{"status":"cancelled","message":"Job cancelled by user"}\n',
        ]
    )
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())

    with pytest.raises(JobCancelledError) as exc_info:
        await call_provider(
            worker_url="http://worker",
            workflow={"nodes": {}},
            job_id="job-cancelled",
            job_service=job_service,
            total_nodes=1,
            timeout=5.0,
            provider_id="provider-cancelled",
        )

    assert str(exc_info.value) == "Job cancelled by user"
    assert exc_info.value.provider_id == "provider-cancelled"
    job_service.update_job.assert_any_call("job-cancelled", status=JobStatus.PRE_GENERATION, message="Queued in ComfyUI...")


@pytest.mark.asyncio
async def test_call_provider_local_protocol_error_is_non_retryable(monkeypatch):
    class RaisingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, *args, **kwargs):
            raise httpx.LocalProtocolError("invalid request framing")

    @asynccontextmanager
    async def fake_get_streaming_client(timeout=600.0):
        yield RaisingClient()

    monkeypatch.setattr("services.provider_client.get_streaming_client", fake_get_streaming_client)
    job_service = SimpleNamespace(update_job=AsyncMock())

    with pytest.raises(ProviderCallError) as exc_info:
        await call_provider(
            worker_url="http://worker",
            workflow={"nodes": {}},
            job_id="job-proto",
            job_service=job_service,
            total_nodes=0,
            timeout=5.0,
            provider_id="provider-proto",
        )

    assert exc_info.value.provider_id == "provider-proto"
    assert exc_info.value.is_retryable is False
    job_service.update_job.assert_not_called()


@pytest.mark.asyncio
async def test_call_provider_accepts_modal_base64_success_payload(monkeypatch):
    response = FakeResponse(
        chunks=[
            b'{"status":"queued"}\n',
            b'{"status":"success","images":[{"filename":"image_0.png","data":"aGVsbG8=","_base64_encoded":true}]}\n',
        ]
    )
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())

    result = await call_provider(
        worker_url="http://worker",
        workflow={"nodes": {}},
        job_id="job-modal-success",
        job_service=job_service,
        total_nodes=0,
        timeout=5.0,
        provider_id="provider-modal",
    )

    assert result["status"] == "success"
    assert result["images"][0]["filename"] == "image_0.png"
    assert result["images"][0]["_base64_encoded"] is True
    job_service.update_job.assert_any_call("job-modal-success", status=JobStatus.PRE_GENERATION, message="Queued in ComfyUI...")


@pytest.mark.asyncio
async def test_call_provider_handles_provider_core_error_payload(monkeypatch):
    payload = build_provider_core_error_payload("provider-core failure", retryable=True)
    response = FakeResponse(
        chunks=[
            b'{"status":"queued"}\n',
            json.dumps(payload).encode("utf-8") + b"\n",
        ]
    )
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())

    with pytest.raises(ProviderCallError) as exc_info:
        await call_provider(
            worker_url="http://worker",
            workflow={"nodes": {}},
            job_id="job-provider-core-error",
            job_service=job_service,
            total_nodes=1,
            timeout=5.0,
            provider_id="provider-core",
        )

    assert str(exc_info.value) == "provider-core failure"
    assert exc_info.value.provider_id == "provider-core"
    assert exc_info.value.is_retryable is True
    job_service.update_job.assert_any_call("job-provider-core-error", status=JobStatus.PRE_GENERATION, message="Queued in ComfyUI...")


@pytest.mark.asyncio
async def test_call_provider_sends_timeout_seconds_and_canonical_inference_path(monkeypatch):
    response = FakeResponse(
        chunks=[
            b'{"status":"queued"}\n',
            b'{"status":"success","images":[{"filename":"ok.png"}]}\n',
        ]
    )
    capture = {}
    install_streaming_client(monkeypatch, response, capture=capture)
    job_service = SimpleNamespace(update_job=AsyncMock())

    result = await call_provider(
        worker_url="http://worker-timeout-test",
        workflow={"nodes": {}},
        job_id="job-timeout-payload",
        job_service=job_service,
        total_nodes=1,
        timeout=12.5,
        use_snapshot=True,
        provider_id="provider-timeout",
    )

    assert result["status"] == "success"
    assert capture["args"] == ("POST", "http://worker-timeout-test/inference")
    assert capture["kwargs"]["timeout"] == 12.5
    assert capture["kwargs"]["json"] == {
        "workflow": {"nodes": {}},
        "use_snapshot": True,
        "job_id": "job-timeout-payload",
        "timeout_seconds": 12.5,
    }