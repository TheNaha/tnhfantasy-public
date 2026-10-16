"""The Remote transport's engines, against the protocol they actually speak.

`remote_llm` / `remote_tts` / `beam_llm` / `beam_tts` / `direct_tts` were the
four-and-a-half empty cells in the provider matrix. This suite pins the protocol
of each against a stub, so the container and the engine cannot drift apart the
way the deleted container path did — and the one case that needs a real
container (the agent's response envelope) is asserted literally here rather than
left to be discovered on a GPU box.
"""

import json

import httpx
import pytest

from services.engines.worker_transport_engines import (
    BeamLLMEngine,
    BeamTTSEngine,
    RemoteLLMEngine,
    RemoteTTSEngine,
)


class _MockTransport(httpx.AsyncBaseTransport):
    """Records requests and answers from a scripted queue."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        if not self.responses:
            raise AssertionError(f"unscripted request: {request.url}")
        status, payload, headers = self.responses.pop(0)
        return httpx.Response(
            status_code=status,
            content=payload if isinstance(payload, bytes) else json.dumps(payload).encode(),
            headers=headers,
        )


def _tts_engine(url="http://gpu-box:8002", token="tok"):
    engine = RemoteTTSEngine("remote-tts", url, token)
    return engine


class TestRemoteTTSEngineProtocol:
    @pytest.mark.asyncio
    async def test_synthesize_reads_the_agent_envelope_not_the_top_level(self):
        """The container answers `{"status": "success", "result": {...}}`.

        Reading the top level alone finds nothing and turns a synthesised clip
        into "no file path" — which was the actual bug in the first working
        version, caught only by running against the real container.
        """
        engine = _tts_engine()
        transport = _MockTransport([
            (200, {"status": "success", "message": "Synthesised", "result": {
                "path": "audio/tts-abc.wav",
                "filename": "tts-abc.wav",
                "duration": 1.5,
                "voice": "af_bella",
            }}, {"content-type": "application/json"}),
        ])
        engine._agent_http = httpx.AsyncClient(
            base_url="http://gpu-box:8002",
            headers={"Authorization": "Bearer tok"},
            transport=transport,
        )

        events = [e async for e in engine.inference({"text": "hi", "voice": "af_bella"}, job_id="j1")]
        await engine.close()

        assert [e["event"] for e in events] == ["started", "completed"]
        assert events[-1]["outputs"][0]["path"] == "audio/tts-abc.wav"
        assert events[-1]["outputs"][0]["duration"] == 1.5
        assert transport.requests[0].url.path == "/synthesize"
        sent = json.loads(transport.requests[0].content)
        assert sent == {"text": "hi", "voice": "af_bella"}

    @pytest.mark.asyncio
    async def test_a_200_with_no_result_is_a_failure_not_a_success(self):
        """A green job with nothing to download is worse than a red one."""
        engine = _tts_engine()
        engine._agent_http = httpx.AsyncClient(
            base_url="http://gpu-box:8002",
            headers={"Authorization": "Bearer tok"},
            transport=_MockTransport([(200, {"status": "success", "result": {}}, {})]),
        )
        events = [e async for e in engine.inference({"text": "hi"}, job_id="j2")]
        await engine.close()

        assert events[-1]["event"] == "failed"
        assert events[-1]["retryable"] is True
        assert "no file path" in events[-1]["message"]

    @pytest.mark.asyncio
    async def test_an_auth_rejection_is_permanent(self):
        """A wrong service token is a config fault, not a transient failure."""
        engine = _tts_engine(token="wrong")
        engine._agent_http = httpx.AsyncClient(
            base_url="http://gpu-box:8002",
            headers={"Authorization": "Bearer wrong"},
            transport=_MockTransport([
                (401, {"status": "error", "message": "unauthorized"}, {}),
            ]),
        )
        events = [e async for e in engine.inference({"text": "hi"}, job_id="j3")]
        await engine.close()

        assert events[-1]["event"] == "failed"
        assert events[-1]["retryable"] is False

    @pytest.mark.asyncio
    async def test_an_empty_request_is_refused_before_any_network_call(self):
        engine = _tts_engine()
        engine._agent_http = httpx.AsyncClient(
            base_url="http://gpu-box:8002",
            transport=_MockTransport([]),
        )
        events = [e async for e in engine.inference({"text": "   "}, job_id="j4")]
        await engine.close()

        assert events[-1]["event"] == "failed"
        assert events[-1]["retryable"] is False

    @pytest.mark.asyncio
    async def test_a_missing_clip_is_file_not_found(self):
        engine = _tts_engine()
        engine._agent_http = httpx.AsyncClient(
            base_url="http://gpu-box:8002",
            transport=_MockTransport([(404, {"status": "error"}, {})]),
        )
        with pytest.raises(FileNotFoundError):
            [c async for c in engine.get_file_stream("audio/nope.wav")]
        await engine.close()

    @pytest.mark.asyncio
    async def test_delete_uses_the_agents_post_body_protocol(self):
        """`POST /delete-file {"path": ...}`, not a path-shaped URL."""
        engine = _tts_engine()
        transport = _MockTransport([(200, {"status": "success", "message": "Deleted"}, {})])
        engine._agent_http = httpx.AsyncClient(
            base_url="http://gpu-box:8002", transport=transport
        )
        assert await engine.delete_file("audio/x.wav") is True
        await engine.close()

        request = transport.requests[0]
        assert request.method == "POST"
        assert request.url.path == "/delete-file"
        assert json.loads(request.content) == {"path": "audio/x.wav"}

    @pytest.mark.asyncio
    async def test_a_404_on_delete_is_success(self):
        """The clip is gone, which is what a delete is for."""
        engine = _tts_engine()
        engine._agent_http = httpx.AsyncClient(
            base_url="http://gpu-box:8002",
            transport=_MockTransport([
                (404, {"status": "error", "message": "File not found"}, {}),
            ]),
        )
        assert await engine.delete_file("audio/x.wav") is True
        await engine.close()

    @pytest.mark.asyncio
    async def test_a_410_is_not_a_lie(self):
        """A real failure must not read as success.

        Returning True for any non-2xx is how a caller ends up believing a file
        it still has is gone.
        """
        engine = _tts_engine()
        engine._agent_http = httpx.AsyncClient(
            base_url="http://gpu-box:8002",
            transport=_MockTransport([(410, {"status": "error", "message": "gone"}, {})]),
        )
        assert await engine.delete_file("audio/x.wav") is False
        await engine.close()

    @pytest.mark.asyncio
    async def test_the_read_cap_governs_a_download_too(self):
        """The shared ceiling, not a bespoke audio number."""
        engine = _tts_engine()
        from unittest.mock import patch

        class _Resp:
            status_code = 200
            headers = {"content-length": "9999"}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def aiter_bytes(self, n):
                yield b"x" * (n + 1)

        engine._agent_http = httpx.AsyncClient(
            base_url="http://gpu-box:8002", transport=_MockTransport([])
        )
        engine._agent_http.stream = lambda *a, **kw: _Resp()

        with patch("services.engines.worker_transport_engines.get_file_size_cap", return_value=10):
            with pytest.raises(Exception) as excinfo:
                [c async for c in engine.get_file_stream("audio/big.wav")]
        await engine.close()
        assert "limit is 10" in str(excinfo.value) or "FileTooLarge" in type(excinfo.value).__name__


class TestBeamDialectEngines:
    """The Beam LLM/TTS cells: same websocket plumbing, different dialect."""

    @pytest.mark.asyncio
    async def test_the_payload_carries_only_the_dialects_fields(self):
        engine = BeamLLMEngine("beam-llm-1", api_key="k", gpu_url="http://beam.run")
        payload = engine._payload({"messages": [{"role": "user", "content": "hi"}],
                                   "text": "ignored by llm", "temperature": 0.7})
        assert payload["messages"] == [{"role": "user", "content": "hi"}]
        assert "text" not in payload, "llm payload must not carry the tts text key"
        assert payload["temperature"] == 0.7
        assert payload["token"] == "k"
        assert engine._ws_target() == "http://beam.run/llm"

    @pytest.mark.asyncio
    async def test_tts_targets_the_tts_endpoint(self):
        engine = BeamTTSEngine("beam-tts-1", api_key="k", gpu_url="http://beam.run")
        assert engine._ws_target() == "http://beam.run/tts"
        payload = engine._payload({"text": "read this"})
        assert payload["text"] == "read this"
        assert "messages" not in payload

    @pytest.mark.asyncio
    async def test_a_trailing_slash_in_gpu_url_does_not_double_the_path(self):
        engine = BeamLLMEngine("beam-llm-2", api_key="k", gpu_url="http://beam.run/")
        assert engine._ws_target() == "http://beam.run/llm"

    @pytest.mark.asyncio
    async def test_health_probes_the_deployment(self):
        """A healthy answer has to come from the deployment, not from config.

        This asserted `healthy is True` for an engine pointed at a URL nothing
        was serving — which is the whole defect. `beam_llm` and `beam_tts` had
        no server at all, `check_health` returned `healthy` off `bool(gpu_url)`,
        and the load balancer kept paying to dispatch jobs that 404'd. `/llm`
        and `/tts` are `@asgi` deployments with a plain `GET /health` on the
        same host, so "is it there" is one cheap round trip.
        """
        transport = _MockTransport([(200, {"status": "healthy", "models": ["rp"]}, {})])
        engine = BeamLLMEngine("beam-llm-3", api_key="k", gpu_url="http://beam.run")
        engine._http = httpx.AsyncClient(transport=transport)
        health = await engine.check_health()
        assert health["healthy"] is True
        assert health["probed"] is True
        assert health["check"] == "deployment_health"
        assert transport.requests[0].url == "http://beam.run/health"

    @pytest.mark.asyncio
    async def test_health_is_unhealthy_when_the_deployment_404s(self):
        """The case that used to read green: a URL that answers nothing."""
        transport = _MockTransport([(404, {"detail": "Not Found"}, {})])
        engine = BeamLLMEngine("beam-llm-5", api_key="k", gpu_url="http://beam.run")
        engine._http = httpx.AsyncClient(transport=transport)
        health = await engine.check_health()
        assert health["healthy"] is False
        assert health["probed"] is True
        # A 404 is not going to start answering on a retry.
        assert health["retryable"] is False

    @pytest.mark.asyncio
    async def test_health_is_unhealthy_when_the_deployment_is_unreachable(self):
        engine = BeamLLMEngine("beam-llm-6", api_key="k", gpu_url="http://beam.run")
        engine._http = httpx.AsyncClient(transport=_MockTransport([]))
        health = await engine.check_health()
        assert health["healthy"] is False
        assert health["probed"] is True

    @pytest.mark.asyncio
    async def test_health_without_a_url_is_rejected_without_probing(self):
        unconfigured = BeamLLMEngine("beam-llm-4", api_key="k", gpu_url="")
        health = await unconfigured.check_health()
        assert health["healthy"] is False
        assert health["gpu_url_configured"] is False

    @pytest.mark.asyncio
    async def test_no_model_tree(self):
        """Hosted endpoints do not own model files, so the lifecycle is honest."""
        for engine in (
            BeamLLMEngine("b1", api_key="k", gpu_url="http://x"),
            BeamTTSEngine("b2", api_key="k", gpu_url="http://x"),
        ):
            assert engine.manages_model_files is False
            assert await engine.list_models("models") == []
            assert await engine.delete_file("x") is False
            assert await engine.upload_file("x", "eA==") is False
            assert await engine.setup_models() is True


class TestRemoteLLMEngine:
    def test_the_service_token_replaces_the_hosted_api_key(self):
        engine = RemoteLLMEngine(
            "remote-llm-1",
            agent_url="http://gpu-box:8001",
            agent_token="service-token",
        )
        assert engine.api_base == "http://gpu-box:8001/v1"
        assert engine.api_key == "service-token"
        assert engine._headers()["Authorization"] == "Bearer service-token"

    def test_an_explicit_v1_is_not_doubled(self):
        engine = RemoteLLMEngine(
            "remote-llm-2", agent_url="http://gpu-box:8001/v1", agent_token="t"
        )
        assert engine.api_base == "http://gpu-box:8001/v1"

    def test_defaults_resolve_to_rp_and_util(self):
        """The two-model router's per-kind defaults, on the engine."""
        engine = RemoteLLMEngine(
            "remote-llm-3", agent_url="http://gpu-box:8001", agent_token="t"
        )
        assert engine.default_rp_model == "rp"
        assert engine.default_util_model == "util"

    def test_the_two_clients_do_not_share_one_attribute(self):
        """The mixin and the OpenAI base must not cache on the same name.

        Both used `_http`, with different base URLs: the mixin's is
        `agent_url`, the LLM's is `agent_url + "/v1"`. Whichever parent ran
        first won permanently, so a health check before the first completion
        left inference POSTing to `/chat/completions` — a route that does not
        exist; the agent serves `/v1/chat/completions`. It was order-dependent,
        which is why it survived: whichever path happened to run first in
        practice decided whether the provider appeared to work.
        """
        engine = RemoteLLMEngine(
            "remote-llm-4", agent_url="http://gpu-box:8001", agent_token="t"
        )
        assert engine.agent_url == "http://gpu-box:8001"
        assert engine.api_base == "http://gpu-box:8001/v1"

        agent_client = engine.get_agent_client()
        llm_client = engine.get_http_client()

        assert agent_client is not llm_client
        assert str(agent_client.base_url).rstrip("/") == "http://gpu-box:8001"
        assert str(llm_client.base_url).rstrip("/") == "http://gpu-box:8001/v1"

    @pytest.mark.asyncio
    async def test_the_file_client_survives_the_first_completion(self):
        """The inverse order must not corrupt the file routes either."""
        engine = RemoteLLMEngine(
            "remote-llm-5", agent_url="http://gpu-box:8001", agent_token="t"
        )
        engine.get_http_client()
        agent_client = engine.get_agent_client()
        assert str(agent_client.base_url).rstrip("/") == "http://gpu-box:8001"

    @pytest.mark.asyncio
    async def test_close_releases_both_clients(self):
        """Two clients means two pools; closing one is not enough."""
        engine = RemoteLLMEngine(
            "remote-llm-6", agent_url="http://gpu-box:8001", agent_token="t"
        )
        agent_client = engine.get_agent_client()
        llm_client = engine.get_http_client()
        await engine.close()
        assert agent_client.is_closed
        assert llm_client.is_closed

    @pytest.mark.asyncio
    async def test_upstream_unreachable_returns_rejected_failure(self):
        """When remote agent returns 503 upstream unreachable, engine yields failure."""
        import httpx

        engine = RemoteLLMEngine(
            "remote-llm-7", agent_url="http://gpu-box:8001", agent_token="t"
        )

        async def mock_handler(request: httpx.Request):
            return httpx.Response(
                503,
                json={
                    "status": "error",
                    "message": "Upstream LLM server unreachable on http://127.0.0.1:8003/v1: Connection refused",
                    "retryable": False,
                },
            )

        transport = httpx.MockTransport(mock_handler)
        engine._http = httpx.AsyncClient(base_url="http://gpu-box:8001/v1", transport=transport)

        events = []
        async for ev in engine.inference(
            workflow={"messages": [{"role": "user", "content": "hi"}]},
            job_id="job-1",
        ):
            events.append(ev)

        assert len(events) == 2
        assert events[0]["event"] == "started"
        assert events[1]["event"] == "failed"
        assert "503" in events[1]["message"]
        assert events[1]["retryable"] is True
        await engine.close()


class TestTTSEnginesReadTheRealWorkflow:
    """The engines must read the workflow the app actually builds.

    `build_voice_speak_workflow` produces ONE shape — a ComfyUI graph with the
    text buried at `prompt[<node>][inputs][text]` — because it is shared with the
    ComfyUI-based TTS engines. The plain-HTTP engines (`remote_tts`, `beam_tts`)
    read that document, not a hypothetical flat one.

    Reading `workflow["text"]` instead made those two transports refuse every
    real narration with "TTS request carried no text", *after* the job had been
    routed and paid for — and the two engines that do read the graph
    (`modal_tts`, `direct_tts`) worked, so it presented as "TTS works on Modal
    but not on my box".
    """

    @staticmethod
    def _workflow():
        from services.tts_workflow_builder import build_voice_speak_workflow

        workflow, _ = build_voice_speak_workflow(
            "The gate creaks open.", voice_profile="af_bella", language="en",
        )
        return workflow

    def test_the_extractor_reads_the_graph(self):
        from services.engines.worker_transport_engines import (
            _tts_request_from_workflow,
        )

        request = _tts_request_from_workflow(self._workflow())
        assert request["text"] == "The gate creaks open."
        assert request["voice"] == "af_bella"
        assert request["language"] == "en"

    def test_a_flat_workflow_still_works(self):
        """Both shapes accepted, so a direct caller is not broken."""
        from services.engines.worker_transport_engines import (
            _tts_request_from_workflow,
        )

        request = _tts_request_from_workflow(
            {"text": "hello", "voice": "bm_george", "language": "en"}
        )
        assert request["text"] == "hello"
        assert request["voice"] == "bm_george"

    @pytest.mark.asyncio
    async def test_remote_tts_sends_the_extracted_text(self):
        """The request that reaches the container, not the intent."""
        transport = _MockTransport([
            (200, {"status": "success", "result": {
                "path": "audio/clip.wav", "filename": "clip.wav", "duration": 1.0,
            }}, {}),
        ])
        engine = RemoteTTSEngine("remote-tts", "http://gpu-box:8002", "tok")
        engine._agent_http = httpx.AsyncClient(
            base_url="http://gpu-box:8002", transport=transport
        )

        events = [e async for e in engine.inference(self._workflow(), job_id="tts-1")]
        await engine.close()

        assert events[-1]["event"] == "completed", events
        sent = json.loads(transport.requests[0].content)
        assert sent["text"] == "The gate creaks open."
        assert sent["voice"] == "af_bella"
        assert sent["language"] == "en"

    def test_beam_tts_includes_the_text_in_its_payload(self):
        """The websocket payload is what the deployed handler answers."""
        from services.engines.worker_transport_engines import BeamTTSEngine

        engine = BeamTTSEngine("beam-tts", api_key="k", gpu_url="http://beam.run")
        payload = engine._payload(self._workflow())
        assert payload["text"] == "The gate creaks open."
        assert payload["voice"] == "af_bella"
        assert payload["language"] == "en"
        assert "token" in payload

    @pytest.mark.asyncio
    async def test_a_graph_with_no_text_fails_with_a_useful_message(self):
        transport = _MockTransport([])
        engine = RemoteTTSEngine("remote-tts", "http://gpu-box:8002", "tok")
        engine._agent_http = httpx.AsyncClient(
            base_url="http://gpu-box:8002", transport=transport
        )
        events = [e async for e in engine.inference({"prompt": {}}, job_id="tts-2")]
        await engine.close()
        assert events[-1]["event"] == "failed"
        assert "prompt" in events[-1]["message"]
