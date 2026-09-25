"""Tests for the beam image engine client."""

import asyncio
import json

import pytest
import websockets

from provider_core.models import InferenceRequest


class FakeWebSocket:
    def __init__(self, messages=(), block_after=False):
        self._messages = list(messages)
        self._block_after = block_after
        self.sent = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._messages:
            return self._messages.pop(0)
        if self._block_after:
            await asyncio.sleep(300)
        raise StopAsyncIteration

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


class TestBeamClientInference:
    def _client(self):
        from image_worker.engines.beam.client import BeamProviderClient
        return BeamProviderClient(runtime_config={})

    def _patch_connect(self, monkeypatch, ws):
        import websockets as ws_mod
        monkeypatch.setattr(ws_mod, "connect", lambda *a, **k: FakeConnect(ws))

    @pytest.mark.asyncio
    async def test_inference_streams_task_events(self, monkeypatch):
        ws = FakeWebSocket(messages=[
            json.dumps({"status": "executing", "node": "KSampler"}),
            json.dumps({"status": "success", "images": [{"data": "aGk=", "_base64_encoded": True}]}),
        ])
        self._patch_connect(monkeypatch, ws)

        client = self._client()
        req = InferenceRequest(workflow={"nodes": []}, job_id="job-beam-1")
        response = await client.inference(req)
        body = "".join([c async for c in response.body_iterator])

        events = [json.loads(l) for l in body.strip().split("\n") if l.strip()]
        assert [e["event"] for e in events] == ["node", "completed"]
        assert events[0]["node"] == "KSampler"
        assert events[1]["outputs"][0]["_base64_encoded"] is True
        assert ws.sent == [{"workflow": {"nodes": []}}]

    @pytest.mark.asyncio
    async def test_sends_only_workflow_ignoring_use_snapshot(self, monkeypatch):
        ws = FakeWebSocket(messages=[])
        self._patch_connect(monkeypatch, ws)

        client = self._client()
        req = InferenceRequest(
            workflow={"nodes": []}, job_id="job-beam-2", use_snapshot=True
        )
        response = await client.inference(req)
        body = "".join([c async for c in response.body_iterator])

        events = [json.loads(l) for l in body.strip().split("\n") if l.strip()]
        assert events == []
        assert ws.sent == [{"workflow": {"nodes": []}}]

    @pytest.mark.asyncio
    async def test_cancellation_emits_cancelled_event(self, monkeypatch):
        ws = FakeWebSocket(messages=[json.dumps({"status": "progress", "value": 0.5})])
        self._patch_connect(monkeypatch, ws)

        client = self._client()
        await client.job_tracker.start_job("job-beam-cancel")
        await client.job_tracker.cancel_job("job-beam-cancel")

        req = InferenceRequest(workflow={"nodes": []}, job_id="job-beam-cancel")
        response = await client.inference(req)
        body = "".join([c async for c in response.body_iterator])

        events = [json.loads(l) for l in body.strip().split("\n") if l.strip()]
        assert events[0]["event"] == "cancelled"
        assert events[0]["job_id"] == "job-beam-cancel"
        assert not await client.job_tracker.is_active("job-beam-cancel")

    @pytest.mark.asyncio
    async def test_timeout_emits_retryable_failure(self, monkeypatch):
        ws = FakeWebSocket(block_after=True)
        self._patch_connect(monkeypatch, ws)

        client = self._client()
        req = InferenceRequest(
            workflow={"nodes": []}, job_id="job-beam-timeout", timeout_seconds=0.01
        )
        response = await client.inference(req)
        body = "".join([c async for c in response.body_iterator])

        events = [json.loads(l) for l in body.strip().split("\n") if l.strip()]
        assert events[0]["event"] == "failed"
        assert events[0]["retryable"] is True
        assert "timed out" in events[0]["message"]
        assert not await client.job_tracker.is_active("job-beam-timeout")

    @pytest.mark.asyncio
    async def test_connection_error_emits_retryable_failure(self, monkeypatch):
        import websockets as ws_mod

        def bad_connect(*a, **k):
            raise websockets.exceptions.ConnectionClosedError(1006, "boom")

        monkeypatch.setattr(ws_mod, "connect", bad_connect)

        client = self._client()
        req = InferenceRequest(workflow={"nodes": []}, job_id="job-beam-conn")
        response = await client.inference(req)
        body = "".join([c async for c in response.body_iterator])

        events = [json.loads(l) for l in body.strip().split("\n") if l.strip()]
        assert events[0]["event"] == "failed"
        assert events[0]["retryable"] is True
