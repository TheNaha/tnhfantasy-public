"""Parity tests for the Beam image engine client's TaskEvent emission.

The Unified Protocol (VISION #5) requires every engine to emit the same
`provider_core.models.TaskEvent` NDJSON stream. These tests verify the Beam
client translates its native WebSocket payloads correctly and that the
standardized failure/retryable semantics are preserved.
"""

import json

import pytest
import websockets

from image_worker.engines.beam.client import BeamProviderClient
from provider_core.models import InferenceRequest


class FakeWebSocket:
    def __init__(self, messages=(), block_after=False):
        self._messages = list(messages)
        self._block_after = block_after
        self.sent = []

    async def send(self, payload):
        self.sent.append(json.loads(payload))

    async def recv(self):
        if self._messages:
            return self._messages.pop(0)
        if self._block_after:
            await asyncio.sleep(300)
        raise websockets.exceptions.ConnectionClosedOK(None, None)


class FakeConnect:
    def __init__(self, ws):
        self._ws = ws

    async def __aenter__(self):
        return self._ws

    async def __aexit__(self, *args):
        return False


class TestBeamTaskEventParity:
    def _client(self):
        return BeamProviderClient(runtime_config={})

    def _patch_connect(self, monkeypatch, ws):
        import websockets as ws_mod
        monkeypatch.setattr(ws_mod, "connect", lambda *a, **k: FakeConnect(ws))

    @pytest.mark.asyncio
    async def test_inference_streams_translated_task_events(self, monkeypatch):
        ws = FakeWebSocket(messages=[
            json.dumps({"status": "executing", "node": "KSampler"}),
            json.dumps({"status": "progress", "value": 50, "max": 100}),
            json.dumps({"status": "success", "images": [{"data": "aGk=", "_base64_encoded": True}]}),
        ])
        self._patch_connect(monkeypatch, ws)

        client = self._client()
        req = InferenceRequest(workflow={"nodes": []}, job_id="job-beam-parity-1")
        response = await client.inference(req)
        body = "".join([c async for c in response.body_iterator])

        events = [json.loads(l) for l in body.strip().split("\n") if l.strip()]
        assert [e["event"] for e in events] == ["node", "progress", "completed"]
        assert events[0]["node"] == "KSampler"
        assert events[1]["value"] == 50
        assert events[2]["outputs"][0]["_base64_encoded"] is True
        assert ws.sent == [{"workflow": {"nodes": []}}]

    @pytest.mark.asyncio
    async def test_already_formed_task_event_passthrough(self, monkeypatch):
        ws = FakeWebSocket(messages=[
            json.dumps({"event": "completed", "job_id": "job-x", "outputs": [{"type": "image"}]}),
        ])
        self._patch_connect(monkeypatch, ws)

        client = self._client()
        req = InferenceRequest(workflow={"nodes": []}, job_id="job-beam-parity-2")
        response = await client.inference(req)
        body = "".join([c async for c in response.body_iterator])

        events = [json.loads(l) for l in body.strip().split("\n") if l.strip()]
        assert len(events) == 1
        assert events[0]["event"] == "completed"
        assert events[0]["job_id"] == "job-x"

    @pytest.mark.asyncio
    async def test_cancellation_emits_cancelled_task_event(self, monkeypatch):
        ws = FakeWebSocket(messages=[json.dumps({"status": "progress", "value": 0.5})])
        self._patch_connect(monkeypatch, ws)

        client = self._client()
        await client.job_tracker.start_job("job-beam-parity-cancel")
        await client.job_tracker.cancel_job("job-beam-parity-cancel")

        req = InferenceRequest(workflow={"nodes": []}, job_id="job-beam-parity-cancel")
        response = await client.inference(req)
        body = "".join([c async for c in response.body_iterator])

        events = [json.loads(l) for l in body.strip().split("\n") if l.strip()]
        assert events[0]["event"] == "cancelled"
        assert events[0]["job_id"] == "job-beam-parity-cancel"

    @pytest.mark.asyncio
    async def test_timeout_emits_retryable_failure(self, monkeypatch):
        ws = FakeWebSocket(block_after=True)
        self._patch_connect(monkeypatch, ws)

        client = self._client()
        req = InferenceRequest(
            workflow={"nodes": []}, job_id="job-beam-parity-timeout", timeout_seconds=0.01
        )
        response = await client.inference(req)
        body = "".join([c async for c in response.body_iterator])

        events = [json.loads(l) for l in body.strip().split("\n") if l.strip()]
        assert events[0]["event"] == "failed"
        assert events[0]["retryable"] is True
        assert "timed out" in events[0]["message"]

    @pytest.mark.asyncio
    async def test_connection_error_emits_retryable_failure(self, monkeypatch):
        import websockets as ws_mod

        async def bad_connect(*a, **k):
            raise websockets.exceptions.ConnectionClosedError(1006, "boom")

        monkeypatch.setattr(ws_mod, "connect", bad_connect)

        client = self._client()
        req = InferenceRequest(workflow={"nodes": []}, job_id="job-beam-parity-conn")
        response = await client.inference(req)
        body = "".join([c async for c in response.body_iterator])

        events = [json.loads(l) for l in body.strip().split("\n") if l.strip()]
        assert events[0]["event"] == "failed"
        assert events[0]["retryable"] is True
