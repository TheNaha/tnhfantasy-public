"""Tests for provider streaming response parsing in services.provider_client."""

import asyncio
import importlib
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from core.entities import JobStatus
from services.provider_client import JobCancelledError, ProviderCallError, call_image_provider


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

    async def aiter_lines(self):
        # Each chunk is already a single NDJSON line from the fake worker.
        for chunk in self._chunks:
            if isinstance(chunk, bytes):
                chunk = chunk.decode("utf-8")
            yield chunk
            delay = getattr(self, "_lines_delay", 0.0)
            if delay:
                await asyncio.sleep(delay)

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
    """Hardcoded error payload to decouple backend tests from provider_containers."""
    return {"status": "error", "message": message, "retryable": retryable}


@pytest.mark.asyncio
async def test_call_image_provider_uses_error_field_and_retryable(monkeypatch):
    response = FakeResponse(
        chunks=[
            b'{"status":"queued"}\n',
            b'{"status":"error","message":"beam upstream failed","retryable":true}\n',
        ]
    )
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())

    with pytest.raises(ProviderCallError) as exc_info:
        await call_image_provider(
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
async def test_call_image_provider_uses_details_message_field(monkeypatch):
    response = FakeResponse(
        chunks=[
            b'{"status":"queued"}\n',
            b'{"status":"error","message":"nested worker message","retryable":true}\n',
        ]
    )
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())

    with pytest.raises(ProviderCallError) as exc_info:
        await call_image_provider(
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
async def test_call_image_provider_tolerates_malformed_lines_and_chunk_boundaries(monkeypatch):
    response = FakeResponse(
        chunks=[
            b'{"status":"queued"}\nnot-json\n{"status":"executing","node":"1"}\n{"st',
            b'atus":"success","images":[{"filename":"a.png"}]}\n',
        ]
    )
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())

    result = await call_image_provider(
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
async def test_call_image_provider_parses_success_without_trailing_newline(monkeypatch):
    response = FakeResponse(
        chunks=[
            b'{"status":"queued"}\n',
            b'{"status":"success","images":[{"filename":"tail.png"}]}'
        ]
    )
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())

    result = await call_image_provider(
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
async def test_call_image_provider_formats_http_error_payload(monkeypatch):
    response = FakeResponse(
        status_code=502,
        body=b'{"message":"upstream unavailable"}',
    )
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())

    with pytest.raises(ProviderCallError) as exc_info:
        await call_image_provider(
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
async def test_call_image_provider_invalid_success_payload_is_retryable(monkeypatch):
    response = FakeResponse(
        chunks=[
            b'{"status":"queued"}\n',
            b'{"status":"success","images":[{"data":"YWJj","_base64_encoded":true}]}\n',
        ]
    )
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())

    with pytest.raises(ProviderCallError) as exc_info:
        await call_image_provider(
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
async def test_call_image_provider_raises_job_cancelled_error(monkeypatch):
    response = FakeResponse(
        chunks=[
            b'{"status":"queued"}\n',
            b'{"status":"cancelled","message":"Job cancelled by user"}\n',
        ]
    )
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())

    with pytest.raises(JobCancelledError) as exc_info:
        await call_image_provider(
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
        await call_image_provider(
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
async def test_call_image_provider_accepts_modal_base64_success_payload(monkeypatch):
    response = FakeResponse(
        chunks=[
            b'{"status":"queued"}\n',
            b'{"status":"success","images":[{"filename":"image_0.png","data":"aGVsbG8=","_base64_encoded":true}]}\n',
        ]
    )
    install_streaming_client(monkeypatch, response)
    job_service = SimpleNamespace(update_job=AsyncMock())

    result = await call_image_provider(
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
async def test_call_image_provider_handles_provider_core_error_payload(monkeypatch):
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
        await call_image_provider(
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
async def test_call_image_provider_sends_timeout_seconds_and_canonical_inference_path(monkeypatch):
    response = FakeResponse(
        chunks=[
            b'{"status":"queued"}\n',
            b'{"status":"success","images":[{"filename":"ok.png"}]}\n',
        ]
    )
    capture = {}
    install_streaming_client(monkeypatch, response, capture=capture)
    job_service = SimpleNamespace(update_job=AsyncMock())

    result = await call_image_provider(
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


@pytest.mark.asyncio
async def test_call_llm_provider_throttles_rapid_progress(monkeypatch):
    """Rapid per-token progress chunks are throttled; suppressed deltas are
    accumulated into `full_content` and flushed once on completion (lossless)."""
    from services.provider_client import call_llm_provider

    token_count = 200
    chunks = [json.dumps({"type": "progress", "message": f"t{i}"}) for i in range(token_count)]
    chunks.append(json.dumps({"type": "completed", "outputs": [{"role": "assistant", "content": "done"}]}))

    emitted = []

    async def fake_emit(event_type, data=None, **_kw):
        emitted.append(data)

    monkeypatch.setattr("core.events.emit_job_event", fake_emit)

    response = FakeResponse(status_code=200, chunks=chunks)
    response._lines_delay = 0.0  # tight loop: tokens arrive far faster than 60fps
    install_streaming_client(monkeypatch, response)

    job_service = SimpleNamespace(update_job=AsyncMock())
    result = await call_llm_provider(
        worker_url="http://llm-worker",
        workflow={"chat_id": "c1", "type": "chat_reply"},
        job_id="job-llm-throttle",
        job_service=job_service,
        timeout=60,
        provider_id="provider-1",
    )

    progress = [e for e in emitted if e and e.get("status") == "generating"]
    # Throttling must kick in: < 200 emits for 200 rapid tokens.
    assert len(progress) < token_count, f"expected throttling, got {len(progress)} emits"
    # At least the first progress emit + the mandatory final flush.
    assert len(progress) >= 2
    # Lossless: the final flush carries the complete accumulated text.
    assert progress[-1]["text"] == "".join(f"t{i}" for i in range(token_count))
    assert result["outputs"] == [{"role": "assistant", "content": "done"}]
    assert result["type"] == "text"
    assert result["status"] == "success"
    # update_job was called to set GENERATING status.
    job_service.update_job.assert_awaited()


@pytest.mark.asyncio
async def test_call_llm_provider_does_not_over_throttle_when_chunks_are_slow(monkeypatch):
    """When tokens arrive slower than the 60fps ceiling, every chunk is emitted
    (throttle only ever drops sub-interval tokens)."""
    from services.provider_client import call_llm_provider, LLM_PROGRESS_THROTTLE_SECONDS

    token_count = 10
    # Delay (20ms) exceeds the 16.67ms throttle ceiling -> each token emits.
    delay = LLM_PROGRESS_THROTTLE_SECONDS + 0.005
    chunks = [json.dumps({"type": "progress", "message": f"x{i}"}) for i in range(token_count)]
    chunks.append(json.dumps({"type": "completed", "outputs": [{"role": "assistant", "content": "done"}]}))

    emitted = []

    async def fake_emit(event_type, data=None, **_kw):
        emitted.append(data)

    monkeypatch.setattr("core.events.emit_job_event", fake_emit)

    response = FakeResponse(status_code=200, chunks=chunks)
    response._lines_delay = delay
    install_streaming_client(monkeypatch, response)

    job_service = SimpleNamespace(update_job=AsyncMock())
    await call_llm_provider(
        worker_url="http://llm-worker",
        workflow={"type": "story_continue"},
        job_id="job-llm-slow",
        job_service=job_service,
        timeout=60,
        provider_id="provider-1",
    )

    progress = [e for e in emitted if e and e.get("status") == "generating"]
    # 10 progress emits (one per token, none throttled) + 1 final flush = 11.
    assert len(progress) == token_count + 1
    assert progress[-1]["text"] == "".join(f"x{i}" for i in range(token_count))