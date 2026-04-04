import json
from types import SimpleNamespace

import pytest

from beam_worker import worker as beam_worker
from modal_worker import worker as modal_worker
from provider_core.models import InferenceRequest


class _ImmediateTimeout:
    async def __aenter__(self):
        raise TimeoutError()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _NoopRemoteGenerator:
    async def aio(self, workflow):
        if False:
            yield workflow


class _NoopComfyInstance:
    def __init__(self):
        self.run = SimpleNamespace(remote_gen=_NoopRemoteGenerator())


class _NoopComfyClass:
    def __call__(self):
        return _NoopComfyInstance()


async def _read_stream_payload(response):
    line = await anext(response.body_iterator)
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    return json.loads(line.strip())


@pytest.mark.asyncio
async def test_modal_worker_inference_timeout_stream_payload(monkeypatch):
    fake_modal = SimpleNamespace(
        Cls=SimpleNamespace(from_name=lambda _app, _class_name: _NoopComfyClass()),
        exception=SimpleNamespace(ConnectionError=RuntimeError),
    )
    monkeypatch.setattr(modal_worker, "modal", fake_modal)
    monkeypatch.setattr(
        modal_worker.asyncio,
        "timeout",
        lambda _seconds: _ImmediateTimeout(),
    )

    response = await modal_worker.run_inference(
        InferenceRequest(workflow={"nodes": {}}, timeout_seconds=5.0)
    )
    payload = await _read_stream_payload(response)

    assert payload["status"] == "error"
    assert payload["retryable"] is True
    assert payload["code"] == 408
    assert "timed out" in payload["message"].lower()
    assert payload["error"] == payload["message"]


@pytest.mark.asyncio
async def test_beam_worker_inference_timeout_stream_payload(monkeypatch):
    monkeypatch.setattr(beam_worker, "BEAM_GPU_URL", "http://beam-gpu")
    monkeypatch.setattr(
        beam_worker.asyncio,
        "timeout",
        lambda _seconds: _ImmediateTimeout(),
    )

    response = await beam_worker.run_inference(
        InferenceRequest(workflow={"nodes": {}}, timeout_seconds=7.0)
    )
    payload = await _read_stream_payload(response)

    assert payload["status"] == "error"
    assert payload["retryable"] is True
    assert payload["code"] == 408
    assert "timed out" in payload["message"].lower()
    assert payload["error"] == payload["message"]