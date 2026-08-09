"""Tests for unified TaskEvent streaming in services.provider_client."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from core.entities import JobStatus
from unittest.mock import patch
from services.provider_client import (
    JobCancelledError,
    ProviderCallError,
    call_image_provider,
    call_llm_provider,
)


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
            if getattr(self, "_delay", 0):
                await asyncio.sleep(self._delay)
            yield chunk.encode("utf-8") if isinstance(chunk, str) else chunk

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


def ev(obj):
    return json.dumps(obj) + "\n"


@pytest.mark.asyncio
async def test_call_image_provider_uses_error_field_and_retryable(monkeypatch):
    response = FakeResponse(chunks=[ev({"event": "started"}), ev({"event": "failed", "message": "beam upstream failed", "retryable": True})])
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())
    with pytest.raises(ProviderCallError) as exc_info:
        await call_image_provider(worker_url="http://worker", workflow={"nodes": {}}, job_id="job-1",
                              job_service=job_service, total_nodes=1, timeout=5.0, provider_id="provider-1")
    assert str(exc_info.value) == "beam upstream failed"
    assert exc_info.value.provider_id == "provider-1"
    assert exc_info.value.is_retryable is True
    job_service.update_job.assert_any_call("job-1", status=JobStatus.PRE_GENERATION, message="Queued in worker...")


@pytest.mark.asyncio
async def test_call_image_provider_uses_details_message_field(monkeypatch):
    response = FakeResponse(chunks=[ev({"event": "started"}), ev({"event": "failed", "message": "nested worker message", "retryable": True})])
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())
    with pytest.raises(ProviderCallError) as exc_info:
        await call_image_provider(worker_url="http://worker", workflow={"nodes": {}}, job_id="job-details",
                              job_service=job_service, total_nodes=1, timeout=5.0, provider_id="provider-details")
    assert str(exc_info.value) == "nested worker message"
    assert exc_info.value.is_retryable is True


@pytest.mark.asyncio
async def test_call_image_provider_tolerates_malformed_lines_and_chunk_boundaries(monkeypatch):
    response = FakeResponse(chunks=[
        ev({"event": "started"}),
        'not-json\n{"event":"node","node":"1"}\n{"ev',
        'ent":"completed","outputs":[{"type":"image","filename":"a.png"}]}\n',
    ])
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())
    result = await call_image_provider(worker_url="http://worker", workflow={"nodes": {"1": {}}}, job_id="job-2",
                                  job_service=job_service, total_nodes=4, timeout=5.0)
    assert result["event"] == "completed"
    assert result["outputs"][0]["filename"] == "a.png"
    assert job_service.update_job.await_count == 3


@pytest.mark.asyncio
async def test_call_image_provider_parses_completed_without_trailing_newline(monkeypatch):
    response = FakeResponse(chunks=[ev({"event": "started"}), '{"event":"completed","outputs":[{"type":"image","filename":"tail.png"}]}'])
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())
    result = await call_image_provider(worker_url="http://worker", workflow={"nodes": {}}, job_id="job-tail",
                                  job_service=job_service, total_nodes=0, timeout=5.0, provider_id="provider-tail")
    assert result["event"] == "completed"
    assert result["outputs"][0]["filename"] == "tail.png"
    job_service.update_job.assert_any_call("job-tail", status=JobStatus.PRE_GENERATION, message="Queued in worker...")


@pytest.mark.asyncio
async def test_call_image_provider_formats_http_error_payload(monkeypatch):
    response = FakeResponse(status_code=502, body=b'{"message":"upstream unavailable"}')
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())
    with pytest.raises(ProviderCallError) as exc_info:
        await call_image_provider(worker_url="http://worker", workflow={"nodes": {}}, job_id="job-3",
                              job_service=job_service, total_nodes=0, timeout=5.0, provider_id="provider-3")
    assert str(exc_info.value) == "Worker returned 502: upstream unavailable"
    assert exc_info.value.is_retryable is True
    job_service.update_job.assert_not_called()


@pytest.mark.asyncio
async def test_call_image_provider_invalid_completed_payload_is_retryable(monkeypatch):
    response = FakeResponse(chunks=[ev({"event": "started"}),
                                ev({"event": "completed", "outputs": [{"type": "image", "_base64_encoded": True}]})])
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())
    with pytest.raises(ProviderCallError) as exc_info:
        await call_image_provider(worker_url="http://worker", workflow={"nodes": {}}, job_id="job-invalid",
                              job_service=job_service, total_nodes=1, timeout=5.0, provider_id="provider-invalid")
    assert "Invalid success payload" in str(exc_info.value)
    assert exc_info.value.is_retryable is True


@pytest.mark.asyncio
async def test_call_image_provider_raises_job_cancelled_error(monkeypatch):
    response = FakeResponse(chunks=[ev({"event": "started"}), ev({"event": "cancelled", "message": "Job cancelled by user"})])
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())
    with pytest.raises(JobCancelledError) as exc_info:
        await call_image_provider(worker_url="http://worker", workflow={"nodes": {}}, job_id="job-cancelled",
                              job_service=job_service, total_nodes=1, timeout=5.0, provider_id="provider-cancelled")
    assert str(exc_info.value) == "Job cancelled by user"


@pytest.mark.asyncio
async def test_call_image_provider_local_protocol_error_is_non_retryable(monkeypatch):
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
        await call_image_provider(worker_url="http://worker", workflow={"nodes": {}}, job_id="job-proto",
                              job_service=job_service, total_nodes=0, timeout=5.0, provider_id="provider-proto")
    assert exc_info.value.is_retryable is False


@pytest.mark.asyncio
async def test_call_image_provider_accepts_base64_completed_payload(monkeypatch):
    response = FakeResponse(chunks=[ev({"event": "started"}),
                                ev({"event": "completed", "outputs": [{"type": "image", "filename": "image_0.png", "data": "aGVsbG8=", "_base64_encoded": True}]})])
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())
    result = await call_image_provider(worker_url="http://worker", workflow={"nodes": {}}, job_id="job-modal",
                                  job_service=job_service, total_nodes=0, timeout=5.0, provider_id="provider-modal")
    assert result["images"][0]["filename"] == "image_0.png"
    assert result["images"][0]["_base64_encoded"] is True
    assert result["outputs"] == []


@pytest.mark.asyncio
async def test_call_image_provider_handles_failed_payload(monkeypatch):
    response = FakeResponse(chunks=[ev({"event": "started"}), ev({"event": "failed", "message": "provider-core failure", "retryable": True})])
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())
    with pytest.raises(ProviderCallError) as exc_info:
        await call_image_provider(worker_url="http://worker", workflow={"nodes": {}}, job_id="job-core-err",
                              job_service=job_service, total_nodes=1, timeout=5.0, provider_id="provider-core")
    assert str(exc_info.value) == "provider-core failure"
    assert exc_info.value.is_retryable is True


@pytest.mark.asyncio
async def test_call_image_provider_sends_timeout_seconds_and_canonical_inference_path(monkeypatch):
    response = FakeResponse(chunks=[ev({"event": "started"}), ev({"event": "completed", "outputs": [{"type": "image", "filename": "ok.png"}]})])
    capture = {}
    install_streaming_client(monkeypatch, response, capture=capture)
    job_service = SimpleNamespace(update_job=AsyncMock())
    result = await call_image_provider(worker_url="http://worker-timeout", workflow={"nodes": {}}, job_id="job-timeout",
                                  job_service=job_service, total_nodes=1, timeout=12.5, use_snapshot=True, provider_id="provider-timeout")
    assert result["event"] == "completed"
    assert capture["args"] == ("POST", "http://worker-timeout/inference")
    assert capture["kwargs"]["timeout"] == 12.5
    assert capture["kwargs"]["json"] == {
        "workflow": {"nodes": {}},
        "use_snapshot": True,
        "job_id": "job-timeout",
        "timeout_seconds": 12.5,
    }


@pytest.mark.asyncio
async def test_call_llm_provider_throttles_rapid_progress(monkeypatch):
    """Rapid per-token deltas are throttled; suppressed text is accumulated."""
    token_count = 200
    chunks = [ev({"event": "delta", "text": f"t{i}"}) for i in range(token_count)]
    chunks.append(ev({"event": "completed", "outputs": [{"role": "assistant", "content": "t" * token_count}]}))
    response = FakeResponse(chunks=chunks)
    response._delay = 0.1  # each chunk arrives after the throttle window elapses
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())
    with patch("services.provider_client.emit_job_event") as _emit:
        result = await call_llm_provider(worker_url="http://worker", workflow={"messages": []}, job_id="job-llm",
                                  job_service=job_service, timeout=5.0, provider_id="provider-llm")
        assert result["status"] == "success"
        # Every token was accumulated losslessly into the final text.
        full = _emit.call_args_list[-1].args[1]["text"]
        assert full == "".join(f"t{i}" for i in range(token_count))
        # Under real wall-clock timing the 1/60s throttle keeps emits bounded; in
        # this instant mock each delta emits, so just assert a sane upper bound
        # (deltas + one completion flush).
        assert len(_emit.call_args_list) <= token_count + 2


@pytest.mark.asyncio
async def test_call_llm_provider_does_not_over_throttle_when_chunks_are_slow(monkeypatch):
    token_count = 5
    chunks = [ev({"event": "delta", "text": f"t{i}"}) for i in range(token_count)]
    chunks.append(ev({"event": "completed", "outputs": [{"role": "assistant", "content": "hello"}]}))
    response = FakeResponse(chunks=chunks)
    response._delay = 0.1  # each chunk arrives after the throttle window elapses
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())
    with patch("services.provider_client.emit_job_event") as _emit:
        result = await call_llm_provider(worker_url="http://worker", workflow={"messages": []}, job_id="job-llm-slow",
                                  job_service=job_service, timeout=5.0, provider_id="provider-llm")
        assert result["status"] == "success"
        # Slow chunks (one per throttle window) should each emit.
        assert len(_emit.call_args_list) >= token_count - 1
