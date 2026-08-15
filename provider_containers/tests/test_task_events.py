"""Tests for the unified TaskEvent protocol layer.

Covers the translation shims (provider_core.utils) and the per-engine
TaskEvent emission that the backend single reader consumes.
"""

import json

import pytest

from provider_core.models import TaskEvent, InferenceRequest
from provider_core.utils import (
    comfy_status_to_task_event,
    translate_task_events,
)


class TestComfyStatusToTaskEvent:
    def test_success_with_base64_images(self):
        update = {
            "status": "success",
            "images": [
                {"data": "aGVsbG8=", "filename": "x.png", "type": "output", "_base64_encoded": True},
                {"filename": "y.png", "subfolder": "2026/08/10", "type": "output"},
            ],
        }
        te = comfy_status_to_task_event(update, job_id="job-1")
        assert te is not None
        assert te.event == "completed"
        assert te.job_id == "job-1"
        assert len(te.outputs) == 2
        assert te.outputs[0]["type"] == "image"
        assert te.outputs[0]["_base64_encoded"] is True
        assert te.outputs[1]["filename"] == "y.png"
        assert te.outputs[1]["subfolder"] == "2026/08/10"

    def test_success_via_data_key(self):
        update = {"status": "success", "data": {"images": [{"data": "abc"}]}}
        te = comfy_status_to_task_event(update, job_id="job-2")
        assert te.event == "completed"
        assert te.outputs[0]["_base64_encoded"] is True

    def test_error_maps_to_failed(self):
        te = comfy_status_to_task_event(
            {"status": "error", "message": "boom", "retryable": True}, job_id="job-3"
        )
        assert te.event == "failed"
        assert te.message == "boom"
        assert te.retryable is True

    def test_error_default_message(self):
        te = comfy_status_to_task_event({"status": "error"}, job_id="job-3")
        assert te.event == "failed"
        assert te.message == "Image generation failed"

    def test_cancelled(self):
        te = comfy_status_to_task_event({"status": "cancelled"}, job_id="job-4")
        assert te.event == "cancelled"

    def test_executing_maps_to_node(self):
        te = comfy_status_to_task_event({"status": "executing", "node": "KSampler"}, job_id="job-5")
        assert te.event == "node"
        assert te.node == "KSampler"

    def test_cached_and_interrupted_are_skipped(self):
        for status in ("execution_interrupted", "execution_start"):
            assert comfy_status_to_task_event({"status": status}, job_id="j") is None

    def test_execution_cached_maps_to_cached_nodes(self):
        te = comfy_status_to_task_event({"status": "execution_cached", "nodes": ["A"]}, job_id="job-7")
        assert te.event == "cached_nodes"
        assert te.nodes == ["A"]

    def test_progress_with_plain_value(self):
        te = comfy_status_to_task_event({"status": "progress", "value": 0.5}, job_id="job-6")
        assert te.event == "progress"
        assert te.value == 0.5

    def test_progress_with_nested_dict(self):
        te = comfy_status_to_task_event(
            {"status": "progress", "progress": {"value": 7, "max": 10}}, job_id="job-6"
        )
        assert te.event == "progress"
        assert te.value == 0.7

    def test_non_dict_input_returns_none(self):
        assert comfy_status_to_task_event("garbage", job_id="j") is None
        assert comfy_status_to_task_event(None, job_id="j") is None


class TestTranslateTaskEvents:
    @pytest.mark.asyncio
    async def test_task_event_passthrough(self):
        te = TaskEvent(event="delta", job_id="job-1", text="hello")
        source = _async_iter([te])
        out = [line async for line in translate_task_events(source, job_id="job-1")]
        assert len(out) == 1
        parsed = json.loads(out[0])
        assert parsed["event"] == "delta"
        assert parsed["text"] == "hello"

    @pytest.mark.asyncio
    async def test_legacy_dict_translation(self):
        source = _async_iter([{"status": "executing", "node": "KSampler"}])
        out = [line async for line in translate_task_events(source, job_id="job-2")]
        assert len(out) == 1
        parsed = json.loads(out[0])
        assert parsed["event"] == "node"

    @pytest.mark.asyncio
    async def test_legacy_json_string_translation(self):
        source = _async_iter([json.dumps({"status": "success", "images": []})])
        out = [line async for line in translate_task_events(source, job_id="job-3")]
        assert len(out) == 1
        parsed = json.loads(out[0])
        assert parsed["event"] == "completed"
        assert parsed["outputs"] == []

    @pytest.mark.asyncio
    async def test_unparseable_lines_skipped(self):
        source = _async_iter(["not-json", "", "42"])
        out = [line async for line in translate_task_events(source, job_id="job-4")]
        assert out == []

    @pytest.mark.asyncio
    async def test_keepalive_status_skipped(self):
        source = _async_iter([{"status": "execution_start"}])
        out = [line async for line in translate_task_events(source, job_id="job-5")]
        assert out == []

    @pytest.mark.asyncio
    async def test_task_event_json_string_passthrough(self):
        # Engines (e.g. beam) emit TaskEvent JSON strings inside their raw
        # stream; these must round-trip unchanged, not be misread as legacy
        # {"status": ...} updates (which would degrade cancelled -> progress).
        for te in (
            TaskEvent(event="cancelled", job_id="job-6", message="Job cancelled"),
            TaskEvent(event="failed", job_id="job-6", message="boom", retryable=True),
            TaskEvent(event="completed", job_id="job-6", outputs=[]),
        ):
            source = _async_iter([te.to_ndjson()])
            out = [line async for line in translate_task_events(source, job_id="job-6")]
            assert len(out) == 1
            parsed = json.loads(out[0])
            assert parsed["event"] == te.event
            assert parsed["job_id"] == "job-6"


class TestVLLMModalRemoteEventTranslation:
    """Covers llm_worker.engines.modal.client._translate_remote_event."""

    def _client(self):
        from llm_worker.engines.modal.client import VLLMModalProviderClient
        return VLLMModalProviderClient(provider_id="test", runtime_config={})

    def test_task_event_shaped_dict_passthrough(self):
        client = self._client()
        line = client._translate_remote_event({"event": "delta", "text": "hi"}, "job-1")
        parsed = json.loads(line)
        assert parsed["event"] == "delta"
        assert parsed["text"] == "hi"

    def test_legacy_progress_becomes_delta(self):
        client = self._client()
        line = client._translate_remote_event({"type": "progress", "message": "tok"}, "job-1")
        parsed = json.loads(line)
        assert parsed["event"] == "delta"
        assert parsed["text"] == "tok"

    def test_legacy_completed(self):
        client = self._client()
        line = client._translate_remote_event(
            {"type": "completed", "outputs": [{"role": "assistant", "content": "done"}]}, "job-1"
        )
        parsed = json.loads(line)
        assert parsed["event"] == "completed"
        assert parsed["outputs"][0]["content"] == "done"

    def test_legacy_completed_cancelled(self):
        client = self._client()
        line = client._translate_remote_event(
            {"type": "completed", "outputs": [{"role": "assistant", "content": "", "cancelled": True}]},
            "job-1",
        )
        parsed = json.loads(line)
        assert parsed["event"] == "cancelled"

    def test_legacy_error(self):
        client = self._client()
        line = client._translate_remote_event({"type": "error", "message": "vllm exploded"}, "job-1")
        parsed = json.loads(line)
        assert parsed["event"] == "failed"
        assert parsed["retryable"] is True

    def test_malformed_input(self):
        client = self._client()
        for raw in ("{{{", 42, None):
            line = client._translate_remote_event(raw, "job-1")
            parsed = json.loads(line)
            assert parsed["event"] == "failed"


class TestAnthropicMessageHandling:
    """The anthropic engine must read request.messages (top-level) and emit TaskEvents."""

    def _client(self):
        from llm_worker.engines.anthropic.client import AnthropicProviderClient
        return AnthropicProviderClient(provider_id="test", runtime_config={})

    @pytest.mark.asyncio
    async def test_inference_respects_top_level_messages(self, monkeypatch):
        client = self._client()

        captured = {}

        class FakeResponse:
            def __init__(self):
                self.lines = []
                self.raise_for_status_called = False

            def raise_for_status(self):
                self.raise_for_status_called = True

            async def aiter_lines(self):
                for line in self.lines:
                    yield line

        class FakeStreamCtx:
            def __init__(self, resp):
                self.resp = resp
                self._captured = None

            async def __aenter__(self):
                return self.resp

            async def __aexit__(self, *args):
                return False

        class FakeClient:
            def stream(self, *args, **kwargs):
                captured["json"] = kwargs.get("json", args[2] if len(args) > 2 else None)
                resp = FakeResponse()
                resp.lines = [
                    'event: content_block_delta',
                    'data: {"type":"content_block_delta","delta":{"text":"Hel"}}',
                    'data: {"type":"content_block_delta","delta":{"text":"lo"}}',
                ]
                return FakeStreamCtx(resp)

        class FakeHttp:
            async def get_client(self):
                return FakeClient()

        import llm_worker.engines.anthropic.client as anthropic_mod
        monkeypatch.setattr(anthropic_mod, "get_http_client", lambda: FakeHttp())

        req = InferenceRequest(
            messages=[
                {"role": "system", "content": "You are a pirate."},
                {"role": "user", "content": "Ahoy"},
            ],
            model="claude-3-5-sonnet-20241022",
            job_id="job-anthropic-1",
        )
        response = await client.inference(req)
        chunks = [c async for c in response.body_iterator]
        body = "".join(chunks)

        assert captured["json"]["messages"] == [{"role": "user", "content": "Ahoy"}]
        assert captured["json"]["system"] == "You are a pirate."

        events = [json.loads(l) for l in body.strip().split("\n") if l.strip()]
        assert [e["event"] for e in events] == ["delta", "delta", "completed"]
        assert "".join(e["text"] for e in events if e["event"] == "delta") == "Hello"
        assert events[-1]["outputs"][0]["content"] == "Hello"


class TestGoogleMessageHandling:
    """The google engine must read request.messages (top-level) and emit TaskEvents."""

    def _client(self):
        from llm_worker.engines.google.client import GoogleProviderClient
        return GoogleProviderClient(provider_id="test", runtime_config={})

    @pytest.mark.asyncio
    async def test_inference_respects_top_level_messages(self, monkeypatch):
        client = self._client()

        captured = {}

        class FakeResponse:
            def __init__(self):
                self.raise_for_status_called = False

            def raise_for_status(self):
                self.raise_for_status_called = True

            async def aiter_lines(self):
                # Minimal Gemini SSE shape: one candidate, two text chunks.
                yield 'data: {"candidates":[{"content":{"parts":[{"text":"Hel"}]}}]}'
                yield 'data: {"candidates":[{"content":{"parts":[{"text":"lo"}]}}]}'

        class FakeStreamCtx:
            async def __aenter__(self):
                return FakeResponse()

            async def __aexit__(self, *args):
                return False

        class FakeClient:
            def stream(self, *args, **kwargs):
                captured["url"] = args[1] if len(args) > 1 else kwargs.get("url")
                captured["json"] = kwargs.get("json")
                return FakeStreamCtx()

        class FakeHttp:
            async def get_client(self):
                return FakeClient()

        import llm_worker.engines.google.client as google_mod
        monkeypatch.setattr(google_mod, "get_http_client", lambda: FakeHttp())

        req = InferenceRequest(
            messages=[
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "Hi"},
            ],
            model="gemini-2.0-flash",
            job_id="job-google-1",
        )
        response = await client.inference(req)
        chunks = [c async for c in response.body_iterator]
        body = "".join(chunks)

        assert "gemini" in captured["url"]
        # System prompt must not be smuggled into contents
        assert captured["json"]["systemInstruction"]["parts"][0]["text"] == "Be concise."
        assert captured["json"]["contents"] == [
            {"role": "user", "parts": [{"text": "Hi"}]}
        ]

        events = [json.loads(l) for l in body.strip().split("\n") if l.strip()]
        assert [e["event"] for e in events] == ["delta", "delta", "completed"]
        assert "".join(e["text"] for e in events if e["event"] == "delta") == "Hello"


class TestDirectUrlInferenceJobId:
    """The direct_url engine must not crash on undefined job_id (regression)."""

    @pytest.mark.asyncio
    async def test_inference_has_job_id(self, monkeypatch):
        import sys
        from image_worker.engines.direct_url import client as direct_client

        # Force PROVIDER_ID used by the module
        monkeypatch.setattr(direct_client, "PROVIDER_ID", "direct-test")

        client = direct_client.DirectUrlProviderClient(runtime_config={})
        req = InferenceRequest(workflow={"nodes": []}, job_id="job-direct-1")

        async def fake_execute(workflow_json, comfy_api_url, image_fetch_mode, logger):
            yield {"status": "executing", "node": "KSampler"}
            yield {"status": "success", "images": [{"data": "aGk=", "_base64_encoded": True}]}

        # The client lazily imports from image_worker.comfy.workflow_executor
        # inside inference(); stub that module in sys.modules. Use
        # SimpleNamespace so the function is not descriptor-bound.
        import types

        monkeypatch.setitem(
            sys.modules,
            "image_worker.comfy.workflow_executor",
            types.SimpleNamespace(
                execute_comfy_workflow=fake_execute,
                IMAGE_FETCH_VIEW_API="view_api",
            ),
        )

        response = await client.inference(req)
        chunks = [c async for c in response.body_iterator]
        body = "".join(chunks)

        events = [json.loads(l) for l in body.strip().split("\n") if l.strip()]
        assert events[0]["event"] == "node"
        assert events[1]["event"] == "completed"
        assert events[1]["job_id"] == "job-direct-1"

    @pytest.mark.asyncio
    async def test_cancellation_emits_task_event(self, monkeypatch):
        import sys
        import types
        from image_worker.engines.direct_url import client as direct_client

        monkeypatch.setattr(direct_client, "PROVIDER_ID", "direct-test")

        client = direct_client.DirectUrlProviderClient(runtime_config={})
        req = InferenceRequest(workflow={"nodes": []}, job_id="job-direct-cancel")

        async def fake_execute(workflow_json, comfy_api_url, image_fetch_mode, logger):
            yield {"status": "executing", "node": "KSampler"}

        monkeypatch.setitem(
            sys.modules,
            "image_worker.comfy.workflow_executor",
            types.SimpleNamespace(
                execute_comfy_workflow=fake_execute,
                IMAGE_FETCH_VIEW_API="view_api",
            ),
        )

        await client.job_tracker.start_job("job-direct-cancel")
        await client.job_tracker.cancel_job("job-direct-cancel")

        response = await client.inference(req)
        chunks = [c async for c in response.body_iterator]
        body = "".join(chunks)

        events = [json.loads(l) for l in body.strip().split("\n") if l.strip()]
        assert events[0]["event"] == "cancelled"
        assert events[0]["job_id"] == "job-direct-cancel"
        # Tracker must be cleaned up when the job ends.
        assert not await client.job_tracker.is_active("job-direct-cancel")

    @pytest.mark.asyncio
    async def test_timeout_emits_retryable_failure(self, monkeypatch):
        import sys
        import types
        import asyncio
        from image_worker.engines.direct_url import client as direct_client

        monkeypatch.setattr(direct_client, "PROVIDER_ID", "direct-test")

        client = direct_client.DirectUrlProviderClient(runtime_config={})

        async def fake_execute(workflow_json, comfy_api_url, image_fetch_mode, logger):
            await asyncio.sleep(300)
            yield {"status": "error", "message": "unreachable"}

        monkeypatch.setitem(
            sys.modules,
            "image_worker.comfy.workflow_executor",
            types.SimpleNamespace(
                execute_comfy_workflow=fake_execute,
                IMAGE_FETCH_VIEW_API="view_api",
            ),
        )

        req = InferenceRequest(
            workflow={"nodes": []}, job_id="job-direct-timeout", timeout_seconds=0.01
        )
        response = await client.inference(req)
        chunks = [c async for c in response.body_iterator]
        body = "".join(chunks)

        events = [json.loads(l) for l in body.strip().split("\n") if l.strip()]
        assert events[0]["event"] == "failed"
        assert events[0]["retryable"] is True
        assert "timed out" in events[0]["message"]


def _async_iter(items):
    async def gen():
        for item in items:
            yield item
    return gen()
