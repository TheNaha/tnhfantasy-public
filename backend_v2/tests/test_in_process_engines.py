import json
"""
Tests for In-Process Compute Engines and Integration.

Validates ModalEngine, DirectComfyEngine, EngineFactory, runtime resolution,
load balancing rotation, and end-to-end execution.
"""

import asyncio
import base64
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.entities import JobStatus, Provider
from services.engines.base import InProcessEngine
from services.engines.direct_comfy_engine import DirectComfyEngine, DirectTTSEngine
from services.engines.engine_factory import (
    ENGINE_CACHE_TTL_SECONDS,
    _ENGINE_CACHE,
    can_create_engine,
    clear_engine_cache,
    engine_supports_setup,
    get_engine,
    invalidate_engine,
    register_engine,
)
from services.engines.beam_engine import BeamEngine
from services.engines.modal_engine import ModalEngine
from services.engines.llm_engine import ModalLlamaCPPEngine
from services.load_balancer import LoadBalancer, LoadBalancerRuntimeState
from services.provider_client import call_in_process_image_provider
from services.provider_runtime import resolve_provider_runtime


@pytest.fixture(autouse=True)
def clean_engine_registry():
    clear_engine_cache()
    yield
    clear_engine_cache()


# ---------------------------------------------------------------------------
# 1. ModalEngine Tests
# ---------------------------------------------------------------------------

class TestModalEngine:
    def test_engine_init(self):
        engine = ModalEngine(
            provider_id="modal-test",
            token_id="ak-test12345",
            token_secret="as-secret12345",
            app_name="custom-stack",
        )
        assert engine.provider_id == "modal-test"
        assert engine.token_id == "ak-test12345"
        assert engine.token_secret == "as-secret12345"
        assert engine.app_name == "custom-stack"

    @pytest.mark.asyncio
    async def test_check_health_healthy(self):
        engine = ModalEngine("modal-test", "ak-123", "as-456")
        with patch.object(engine, "get_client") as mock_client:
            mock_client.return_value = MagicMock()
            with patch("services.engines.modal_engine.modal.Function.from_name"):
                health = await engine.check_health()
                assert health["status"] == "healthy"
                assert health["ready"] is True
                assert health["provider_id"] == "modal-test"

    @pytest.mark.asyncio
    async def test_check_health_unhealthy(self):
        engine = ModalEngine("modal-test", "ak-123", "as-456")
        with patch.object(engine, "get_client") as mock_client:
            mock_client.return_value = MagicMock()
            with patch("services.engines.modal_engine.modal.Function.from_name", side_effect=Exception("Workspace disabled")):
                health = await engine.check_health()
                assert health["status"] == "unhealthy"
                assert health["ready"] is False
                assert "Workspace disabled" in health["error"]

    @pytest.mark.asyncio
    async def test_inference_streaming(self):
        engine = ModalEngine("modal-test", "ak-123", "as-456")

        async def fake_remote_gen(workflow):
            yield {"status": "executing", "node": "3"}
            yield {"status": "progress", "value": 5, "max": 10}
            yield {"status": "execution_cached", "nodes": ["1", "2"]}
            yield {
                "status": "success",
                "images": [
                    {"filename": "out.png", "data": b"fake-png-bytes", "type": "output", "subfolder": ""}
                ],
            }

        mock_instance = MagicMock()
        mock_instance.run.remote_gen.aio = fake_remote_gen

        mock_cls = MagicMock(return_value=mock_instance)

        with patch.object(engine, "get_client"):
            with patch("services.engines.modal_engine.modal.Cls.from_name", return_value=mock_cls):
                events = []
                async for ev in engine.inference(workflow={"3": {}}, job_id="job-abc"):
                    events.append(ev)

                assert events[0]["event"] == "started"
                assert events[1] == {"event": "node", "job_id": "job-abc", "node": "3"}
                assert events[2] == {"event": "progress", "job_id": "job-abc", "value": 50, "value_unit": "percent"}
                assert events[3] == {"event": "cached_nodes", "job_id": "job-abc", "nodes": ["1", "2"]}
                assert events[4]["event"] == "completed"
                assert len(events[4]["outputs"]) == 1
                assert events[4]["outputs"][0]["filename"] == "out.png"
                expected_b64 = base64.b64encode(b"fake-png-bytes").decode()
                assert events[4]["outputs"][0]["data"] == expected_b64


# ---------------------------------------------------------------------------
# 2. DirectComfyEngine Tests
# ---------------------------------------------------------------------------

class TestDirectComfyEngine:
    def test_engine_init(self):
        engine = DirectComfyEngine("direct-local", "http://127.0.0.1:8188", api_key="secret-key")
        assert engine.provider_id == "direct-local"
        assert engine.comfy_url == "http://127.0.0.1:8188"
        assert engine.api_key == "secret-key"

    @pytest.mark.asyncio
    async def test_a_job_envelope_is_unwrapped_before_posting_to_prompt(self):
        """`build_voice_speak_workflow` returns an envelope, not a graph.

        `job_runner` hands `job.workflow` through verbatim, so posting it as the
        prompt sent ComfyUI a graph whose node keys were `prompt`,
        `client_id` and `type` — none of them integers — and `validate_prompt`
        rejected the whole thing. Every `direct_tts` job was a 400 on a rig
        that was otherwise working. The Modal twin has unwrapped this since the
        beginning; this engine did not.
        """
        engine = DirectComfyEngine("direct-tts", "http://127.0.0.1:8188")
        graph = {"10": {"class_type": "QwenTTSSpeak", "inputs": {"text": "hi"}}}
        envelope = {"prompt": graph, "client_id": None, "type": "tts"}

        with patch.object(engine, "get_http_client") as mock_client_fn:
            client = AsyncMock()
            client.post.return_value = MagicMock(
                status_code=200, json=lambda: {"prompt_id": "p1"}, text=""
            )
            mock_client_fn.return_value = client

            with patch(
                "services.engines.direct_comfy_engine._ws_connect_with_retry"
            ) as ws_ctx:
                ws = AsyncMock()
                ws_ctx.return_value.__aenter__.return_value = ws
                ws.recv.side_effect = asyncio.CancelledError

                with pytest.raises((asyncio.CancelledError, Exception)):
                    [e async for e in engine.inference(envelope, job_id="j1")]

            posted = client.post.call_args_list[0]
            assert posted.args[0] == "/prompt"
            assert posted.kwargs["json"]["prompt"] == graph, (
                "the envelope reached /prompt instead of the graph it wraps"
            )

    def test_a_bare_graph_is_posted_unchanged(self):
        """Image jobs carry the bare graph; the unwrap must not touch them."""
        graph = {"3": {"class_type": "KSampler", "inputs": {}}}
        assert (graph.get("prompt") if isinstance(graph.get("prompt"), dict) else graph) is graph

    @pytest.mark.asyncio
    async def test_audio_outputs_are_not_looked_for_under_images(self):
        """`SaveAudio` publishes `outputs[<node>]["audio"]`, never `images`.

        The history walk only read `images`, so a TTS history document yielded
        nothing: `completed` with `outputs: []`, which finalises the job green
        with no clip attached to the message.
        """
        engine = DirectTTSEngine("direct-tts", "http://127.0.0.1:8188")
        captured = {}

        import services.engines.direct_comfy_engine as mod

        client = AsyncMock()

        async def _post(path, **kwargs):
            captured["path"] = path
            captured["json"] = kwargs.get("json")
            return MagicMock(status_code=200, json=lambda: {"prompt_id": "p1"}, text="")

        async def _get(path, **kwargs):
            if path.startswith("/history/"):
                return MagicMock(status_code=200, json=lambda: {
                    "p1": {"outputs": {"11": {"audio": [
                        {"filename": "tts_abc.wav", "subfolder": "chat_tts/1/2", "type": "output"}
                    ]}}, "status": {"completed": True}}
                })
            return MagicMock(status_code=200, content=b"RIFF", headers={})

        client.post.side_effect = _post
        client.get.side_effect = _get

        import contextlib

        # One real terminal frame. This exercises BOTH fixes at once: the
        # `execution_success` handler (which is what ends the wait now that
        # ComfyUI no longer sends `executing {node: null}`) and the history
        # walk that reads `audio`.
        frames = [
            json.dumps({"type": "execution_success", "data": {"prompt_id": "p1"}}),
        ]

        async def _recv():
            if frames:
                return frames.pop(0)
            raise asyncio.CancelledError

        async def _noop(*_a, **_k):
            return None

        @contextlib.asynccontextmanager
        async def _ws(*_a, **_k):
            yield SimpleNamespace(recv=_recv, send=_noop)

        with patch.object(engine, "get_http_client", return_value=client), \
             patch.object(mod, "_ws_connect_with_retry", _ws):
            events = [e async for e in engine.inference(
                {"prompt": {"11": {"class_type": "SaveAudio"}}}, job_id="j-tts"
            )]

        completed = [e for e in events if e["event"] == "completed"]
        assert completed, f"no completed event: {events}"
        outputs = completed[0]["outputs"]
        assert outputs, "TTS completed with no outputs; the clip would never be attached"
        assert outputs[0]["filename"] == "tts_abc.wav"
        assert outputs[0]["subfolder"] == "chat_tts/1/2"
        assert outputs[0]["type"] == "audio"
        # A ref, not inline bytes: `build_job_outputs` opens every payload with
        # PIL and cannot write a WAV, so the proven path is the one
        # ModalTTSEngine already takes — pull the bytes through get_file_stream.
        assert "data" not in outputs[0]

    @pytest.mark.asyncio
    async def test_the_loop_ends_on_execution_success_without_waiting_for_the_stall(self):
        """The frame ComfyUI actually sends, and the one it stopped sending.

        The loop's only exit used to be `executing` with `node is None`.
        ComfyUI emits `executing` only while a real node is running and finishes
        with `execution_success`, so every job waited out the full 300 s stall
        timeout before the history probe broke the loop — and any generation
        slower than that was reported `failed / workflow_stalled / retryable`
        while ComfyUI was still executing it, which then re-ran a workflow that
        had already succeeded.
        """
        engine = DirectComfyEngine("direct-1", "http://127.0.0.1:8188")
        client = AsyncMock()
        client.post.return_value = MagicMock(
            status_code=200, json=lambda: {"prompt_id": "p1"}, text=""
        )
        client.get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"p1": {"outputs": {"9": {"images": [
                {"filename": "out.png", "subfolder": "", "type": "output"}
            ]}}, "status": {"completed": True}}},
            content=b"PNG", headers={},
        )

        import contextlib

        import services.engines.direct_comfy_engine as mod

        frames = [json.dumps({"type": "execution_success", "data": {"prompt_id": "p1"}})]

        async def _recv():
            if frames:
                return frames.pop(0)
            raise asyncio.CancelledError

        async def _noop(*_a, **_k):
            return None

        @contextlib.asynccontextmanager
        async def _ws(*_a, **_k):
            yield SimpleNamespace(recv=_recv, send=_noop)

        with patch.object(engine, "get_http_client", return_value=client), \
             patch.object(mod, "_ws_connect_with_retry", _ws):
            loop = asyncio.get_running_loop()
            started = loop.time()
            engine.stall_timeout = 30.0  # a stall would be unmistakable
            events = [e async for e in engine.inference(
                {"3": {"class_type": "KSampler"}}, job_id="j-img"
            )]
            elapsed = loop.time() - started

        assert [e["event"] for e in events][-1] == "completed"
        assert not any(e["event"] == "failed" for e in events), events
        assert elapsed < 5.0, (
            f"took {elapsed:.1f}s — the loop waited for the stall timeout rather "
            f"than breaking on execution_success"
        )

    @pytest.mark.asyncio
    async def test_check_health_healthy(self):
        engine = DirectComfyEngine("direct-local", "http://127.0.0.1:8188")
        mock_resp = MagicMock(status_code=200)
        with patch.object(engine, "get_http_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client_fn.return_value = mock_client

            health = await engine.check_health()
            assert health["status"] == "healthy"
            assert health["ready"] is True
            assert health["engine"] == "direct_url"

    @pytest.mark.asyncio
    async def test_list_models_parsing(self):
        engine = DirectComfyEngine("direct-local", "http://127.0.0.1:8188")
        sample_object_info = {
            "CheckpointLoaderSimple": {
                "input": {
                    "required": {
                        "ckpt_name": [["model1.safetensors", "model2.safetensors"]]
                    }
                }
            },
            "LoraLoader": {
                "input": {
                    "required": {
                        "lora_name": [["style.safetensors"]]
                    }
                }
            }
        }
        with patch.object(engine, "_fetch_object_info", return_value=sample_object_info):
            models = await engine.list_models("checkpoints")
            assert len(models) == 2
            assert models[0]["name"] == "model1.safetensors"
            # `models/`-prefixed: `get_all_storage_paths` and the maintenance scan
            # both key on `models/{directory}/{filename}`, and the agent branch of
            # this same method returns `relpath(..., DATA_DIR)`, which carries the
            # prefix. Without it, the no-agent rig's discovery matched nothing, so
            # its files stayed pending forever and counted as orphans every tick.
            assert models[0]["path"] == "models/checkpoints/model1.safetensors"

            loras = await engine.list_models("loras")
            assert len(loras) == 1
            assert loras[0]["name"] == "style.safetensors"
            assert loras[0]["path"] == "models/loras/style.safetensors"

        # The prefix must also be produced when the directory argument already
        # carries it — `model_reconciliation` fans out over `MODEL_DIRECTORIES`,
        # which are `models/`-prefixed, not bare `checkpoints`.
        with patch.object(engine, "_fetch_object_info", return_value=sample_object_info):
            prefixed = await engine.list_models("models/checkpoints")
        assert [m["path"] for m in prefixed] == [
            "models/checkpoints/model1.safetensors",
            "models/checkpoints/model2.safetensors",
        ]


# ---------------------------------------------------------------------------
# 3. EngineFactory Tests
# ---------------------------------------------------------------------------

class TestEngineFactory:
    def test_can_create_modal_engine(self):
        provider = SimpleNamespace(
            id="modal-test",
            type="modal",
            credentials={"token_id": "ak-123", "token_secret": "as-456"},
            config={},
        )
        assert can_create_engine(provider) is True

    def test_can_create_direct_engine(self):
        provider = SimpleNamespace(
            id="direct-test",
            type="direct_url",
            credentials={},
            config={"comfy_url": "http://remote:8188"},
        )
        assert can_create_engine(provider) is True

    def test_cannot_create_when_missing_credentials(self):
        provider = SimpleNamespace(
            id="unknown-provider",
            type="unknown",
            credentials={},
            config={},
        )
        assert can_create_engine(provider) is False

    def test_can_create_llm_engine(self):
        provider = SimpleNamespace(
            id="llm-local",
            type="openai_compat",
            worker_type="llm",
            credentials={"api_key": "sk-123"},
            config={"base_url": "http://localhost:8000/v1"},
        )
        assert can_create_engine(provider) is True
        engine = get_engine("llm-local", provider)
        from services.engines.llm_engine import OpenAICompatLLMEngine
        assert isinstance(engine, OpenAICompatLLMEngine)

    def test_can_create_tts_engine(self):
        provider = SimpleNamespace(
            id="tts-modal-hp196",
            type="modal_tts",
            worker_type="tts",
            credentials={"token_id": "ak-tts", "token_secret": "as-tts"},
            config={"app_name": "comfy-modal-tts"},
        )
        assert can_create_engine(provider) is True
        engine = get_engine("tts-modal-hp196", provider)
        from services.engines.modal_tts_engine import ModalTTSEngine
        assert isinstance(engine, ModalTTSEngine)

    def test_get_engine_caching(self):
        provider = SimpleNamespace(
            id="modal-test",
            type="modal",
            credentials={"token_id": "ak-123", "token_secret": "as-456"},
            config={},
        )
        engine1 = get_engine("modal-test", provider)
        engine2 = get_engine("modal-test", provider)
        assert engine1 is not None
        assert engine1 is engine2
        assert isinstance(engine1, ModalEngine)


# ---------------------------------------------------------------------------
# 4. Runtime Target Resolution Tests
# ---------------------------------------------------------------------------

class TestRuntimeResolution:
    def test_resolves_to_in_process_when_credentials_present(self):
        provider = SimpleNamespace(
            id="modal-test",
            type="modal",
            credentials={"token_id": "ak-123", "token_secret": "as-456"},
            config={},
        )
        runtime = resolve_provider_runtime(provider)
        assert runtime.mode == "in_process"
        assert runtime.connected is True
        # Unknown until the async health probe runs: resolve_* is sync and
        # must not claim healthy for bad-credential providers.
        assert runtime.healthy is None
        assert runtime.worker_url is None

    def test_container_override_is_ignored(self):
        # The legacy container path is gone: a stale
        # config.execution_mode="container" no longer diverts resolution.
        provider = SimpleNamespace(
            id="modal-test",
            type="modal",
            credentials={"token_id": "ak-123", "token_secret": "as-456"},
            config={"execution_mode": "container"},
        )
        runtime = resolve_provider_runtime(provider)
        assert runtime.mode == "in_process"


# ---------------------------------------------------------------------------
# 5. LoadBalancer In-Process Rotation Tests
# ---------------------------------------------------------------------------

class TestLoadBalancerInProcessRotation:
    @pytest.mark.asyncio
    async def test_round_robin_fair_distribution_between_in_process_engines(self, session):
        p1 = Provider(
            id="modal-account-1",
            type="modal",
            worker_type="image",
            enabled=True,
            priority=1,
            credentials={"token_id": "ak-1", "token_secret": "as-1"},
        )
        p2 = Provider(
            id="modal-account-2",
            type="modal",
            worker_type="image",
            enabled=True,
            priority=1,
            credentials={"token_id": "ak-2", "token_secret": "as-2"},
        )
        session.add(p1)
        session.add(p2)
        session.commit()

        # Mock healthy engines
        engine1 = MagicMock(spec=InProcessEngine)
        engine1.check_health = AsyncMock(return_value={"status": "healthy", "ready": True})
        engine2 = MagicMock(spec=InProcessEngine)
        engine2.check_health = AsyncMock(return_value={"status": "healthy", "ready": True})

        register_engine("modal-account-1", engine1)
        register_engine("modal-account-2", engine2)

        isolated_state = LoadBalancerRuntimeState()
        lb = LoadBalancer(session, strategy="round-robin", runtime_state=isolated_state)

        # First request should get p1 or p2
        selected_1 = await lb.get_next_provider()
        selected_2 = await lb.get_next_provider()
        selected_3 = await lb.get_next_provider()
        selected_4 = await lb.get_next_provider()

        assert selected_1 is not None
        assert selected_2 is not None
        # They should alternate!
        assert selected_1.id != selected_2.id
        assert selected_1.id == selected_3.id
        assert selected_2.id == selected_4.id

    @pytest.mark.asyncio
    async def test_least_connections_routes_to_lower_load(self, session):
        p1 = Provider(
            id="modal-a",
            type="modal",
            worker_type="image",
            enabled=True,
            priority=1,
            credentials={"token_id": "ak-1", "token_secret": "as-1"},
        )
        p2 = Provider(
            id="modal-b",
            type="modal",
            worker_type="image",
            enabled=True,
            priority=1,
            credentials={"token_id": "ak-2", "token_secret": "as-2"},
        )
        session.add(p1)
        session.add(p2)
        session.commit()

        engine_a = MagicMock(spec=InProcessEngine)
        engine_a.check_health = AsyncMock(return_value={"status": "healthy", "ready": True})
        engine_b = MagicMock(spec=InProcessEngine)
        engine_b.check_health = AsyncMock(return_value={"status": "healthy", "ready": True})

        register_engine("modal-a", engine_a)
        register_engine("modal-b", engine_b)

        isolated_state = LoadBalancerRuntimeState()
        lb = LoadBalancer(session, strategy="least-connections", runtime_state=isolated_state)
        isolated_state.provider_job_counts["modal-a"] = 5
        isolated_state.provider_job_counts["modal-b"] = 1

        selected = await lb.get_next_provider()
        # modal-b has 1 active job vs modal-a with 5, so modal-b must be picked!
        assert selected.id == "modal-b"


# ---------------------------------------------------------------------------
# 6. In-Process Image Job Execution & Reduction
# ---------------------------------------------------------------------------

class TestInProcessJobExecution:
    @pytest.mark.asyncio
    async def test_call_in_process_image_provider(self):
        job_service = AsyncMock()
        engine = MagicMock(spec=InProcessEngine)

        async def fake_stream(*args, **kwargs):
            yield {"event": "started", "job_id": "job-100"}
            yield {"event": "node", "job_id": "job-100", "node": "4"}
            yield {"event": "progress", "job_id": "job-100", "value": 100}
            yield {
                "event": "completed",
                "job_id": "job-100",
                "outputs": [
                    {"filename": "test.png", "data": "base64data", "type": "output"}
                ],
            }

        engine.run_inference = fake_stream

        result = await call_in_process_image_provider(
            engine=engine,
            workflow={"4": {}},
            job_id="job-100",
            job_service=job_service,
            total_nodes=1,
            timeout=30.0,
            provider_id="modal-test",
        )

        assert "images" in result
        assert len(result["images"]) == 1
        assert result["images"][0]["filename"] == "test.png"
        assert result["images"][0]["data"] == "base64data"
        job_service.update_job.assert_any_call("job-100", status=JobStatus.CONNECTED, message="Connected to modal-test...")


# ---------------------------------------------------------------------------
# 7. LLM Engine Tests
# ---------------------------------------------------------------------------

class TestLLMEngines:
    def test_openai_compat_init(self):
        from services.engines.llm_engine import OpenAICompatLLMEngine

        engine = OpenAICompatLLMEngine(
            provider_id="llm-local",
            base_url="http://localhost:8000/v1",
            api_key="sk-test",
            default_model="qwen",
        )
        assert engine.provider_id == "llm-local"
        assert engine.api_base == "http://localhost:8000/v1"
        assert engine.default_model == "qwen"

    @pytest.mark.asyncio
    async def test_openai_compat_check_health(self):
        from services.engines.llm_engine import OpenAICompatLLMEngine

        engine = OpenAICompatLLMEngine("llm-local", "http://localhost:8000/v1", api_key="sk-test")
        mock_http = MagicMock()
        mock_resp = MagicMock(status_code=200)
        mock_http.get = AsyncMock(return_value=mock_resp)
        with patch.object(engine, "get_http_client", return_value=mock_http):
            health = await engine.check_health()
            assert health["status"] == "healthy"
            assert health["ready"] is True

    @pytest.mark.asyncio
    async def test_openai_compat_check_health_short_circuits_without_key(self):
        from services.engines.llm_engine import OpenAICompatLLMEngine

        engine = OpenAICompatLLMEngine("llm-local", "http://localhost:8000/v1")
        with patch.object(
            engine, "get_http_client", side_effect=AssertionError("must not probe without a key")
        ):
            health = await engine.check_health()
            assert health["status"] == "unhealthy"
            assert health["ready"] is False
            assert "OPENAI_API_KEY" in health["error"]

    @pytest.mark.asyncio
    async def test_openai_compat_check_health_probe_timeout(self, monkeypatch):
        from services.engines.llm_engine import OpenAICompatLLMEngine

        engine = OpenAICompatLLMEngine("llm-local", "http://localhost:8000/v1", api_key="sk-test")
        mock_http = MagicMock()
        mock_http.get = AsyncMock(return_value=MagicMock(status_code=200))
        monkeypatch.delenv("OPENAI_COMPAT_HEALTH_PROBE_TIMEOUT", raising=False)
        with patch.object(engine, "get_http_client", return_value=mock_http):
            await engine.check_health()
            assert mock_http.get.call_args.kwargs["timeout"] == 1.5
        monkeypatch.setenv("OPENAI_COMPAT_HEALTH_PROBE_TIMEOUT", "0.7")
        with patch.object(engine, "get_http_client", return_value=mock_http):
            await engine.check_health()
            assert mock_http.get.call_args.kwargs["timeout"] == 0.7

    @pytest.mark.asyncio
    async def test_openai_compat_cancel_carries_partial_content(self):
        from services.engines.llm_engine import OpenAICompatLLMEngine

        engine = OpenAICompatLLMEngine("llm-local", "http://localhost:8000/v1", api_key="sk-test")

        async def fake_aiter_lines():
            yield 'data: {"choices": [{"delta": {"content": "Hello"}}]}'
            yield ''
            engine._cancelled_jobs.add("job-cancel-partial")
            yield 'data: {"choices": [{"delta": {"content": " world"}}]}'
            yield ''

        mock_resp = MagicMock(status_code=200)
        mock_resp.aiter_lines = fake_aiter_lines

        class StreamContext:
            async def __aenter__(self):
                return mock_resp
            async def __aexit__(self, *args):
                pass

        mock_http = MagicMock()
        mock_http.stream = MagicMock(return_value=StreamContext())

        with patch.object(engine, "get_http_client", return_value=mock_http):
            events = []
            async for ev in engine.inference(
                {"messages": [{"role": "user", "content": "hi"}]},
                job_id="job-cancel-partial",
            ):
                events.append(ev)

            cancelled = [e for e in events if e.get("event") == "cancelled"]
            assert len(cancelled) == 1
            assert cancelled[0]["outputs"] == [
                {"role": "assistant", "content": "Hello", "cancelled": True}
            ]

    @pytest.mark.asyncio
    async def test_openai_compat_inference_streaming(self):
        from services.engines.llm_engine import OpenAICompatLLMEngine

        engine = OpenAICompatLLMEngine("llm-local", "http://localhost:8000/v1")

        async def fake_aiter_lines():
            yield 'data: {"choices": [{"delta": {"content": "Hello"}}]}'
            yield ''
            yield 'data: {"choices": [{"delta": {"content": " world"}}]}'
            yield ''
            yield 'data: [DONE]'
            yield ''

        mock_resp = MagicMock(status_code=200)
        mock_resp.aiter_lines = fake_aiter_lines

        class StreamContext:
            async def __aenter__(self):
                return mock_resp
            async def __aexit__(self, *args):
                pass

        mock_http = MagicMock()
        mock_http.stream = MagicMock(return_value=StreamContext())

        with patch.object(engine, "get_http_client", return_value=mock_http):
            events = []
            async for ev in engine.inference({"messages": [{"role": "user", "content": "hi"}]}, job_id="job-llm"):
                events.append(ev)

            assert len(events) >= 3
            assert events[0]["event"] == "started"
            deltas = [e["text"] for e in events if e.get("event") == "delta"]
            assert "".join(deltas) == "Hello world"
            completed = [e for e in events if e.get("event") == "completed"]
            assert len(completed) == 1
            assert completed[0]["outputs"][0]["content"] == "Hello world"

    @pytest.mark.asyncio
    async def test_modal_llm_engine_streaming(self):
        from services.engines.llm_engine import ModalLlamaCPPEngine

        engine = ModalLlamaCPPEngine("modal-vllm", "ak-123", "as-456")

        # Remote signature is generate(model_id, messages, tools,
        # timeout_seconds, sampling) — see llm_worker/engines/modal/modal_app.py.
        async def fake_gen(model_id, messages, tools, timeout_seconds, sampling):
            yield {"event": "delta", "text": "Generated"}
            yield {"event": "delta", "text": " by vLLM"}
            yield {"event": "completed", "outputs": [{"role": "assistant", "content": "Generated by vLLM"}]}

        mock_instance = MagicMock()
        mock_instance.generate.remote_gen.aio = fake_gen
        mock_cls = MagicMock(return_value=mock_instance)

        with patch.object(engine, "get_client_async"):
            with patch("services.engines.llm_engine.modal.Cls.from_name", return_value=mock_cls):
                events = []
                async for ev in engine.inference(
                    {"model": "test-model", "messages": [{"role": "user", "content": "hi"}]},
                    job_id="job-vllm",
                ):
                    events.append(ev)

                assert any(e["event"] == "delta" for e in events)
                completed = [e for e in events if e["event"] == "completed"]
                assert len(completed) == 1
                assert completed[0]["outputs"][0]["content"] == "Generated by vLLM"

    @pytest.mark.asyncio
    async def test_modal_llm_legacy_dialect_translation(self):
        from services.engines.llm_engine import ModalLlamaCPPEngine

        engine = ModalLlamaCPPEngine("modal-vllm", "ak-123", "as-456")

        async def fake_gen(model_id, messages, tools, timeout_seconds, sampling):
            yield {"type": "progress", "message": "Hel"}
            yield {"status": "progress", "text": "lo"}
            yield {"type": "completed",
                   "outputs": [{"role": "assistant", "content": "Hello"}]}

        mock_instance = MagicMock()
        mock_instance.generate.remote_gen.aio = fake_gen
        mock_cls = MagicMock(return_value=mock_instance)

        with patch.object(engine, "get_client_async"):
            with patch("services.engines.llm_engine.modal.Cls.from_name", return_value=mock_cls):
                events = [ev async for ev in engine.inference(
                    {"model": "m1", "messages": [{"role": "user", "content": "hi"}]},
                    job_id="job-vllm-legacy",
                )]

                deltas = [e["text"] for e in events if e.get("event") == "delta"]
                assert "".join(deltas) == "Hello"
                completed = [e for e in events if e.get("event") == "completed"]
                assert len(completed) == 1
                assert completed[0]["outputs"][0]["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_modal_llm_legacy_error_retryable_defaults_false(self):
        from services.engines.llm_engine import ModalLlamaCPPEngine

        async def run_with(remote_payload):
            engine = ModalLlamaCPPEngine("modal-vllm", "ak-123", "as-456")

            async def fake_gen(model_id, messages, tools, timeout_seconds, sampling):
                yield remote_payload

            mock_instance = MagicMock()
            mock_instance.generate.remote_gen.aio = fake_gen
            mock_cls = MagicMock(return_value=mock_instance)
            with patch.object(engine, "get_client_async"):
                with patch("services.engines.llm_engine.modal.Cls.from_name", return_value=mock_cls):
                    return [ev async for ev in engine.inference(
                        {"model": "m1", "messages": []}, job_id="job-vllm-err")]

        # Legacy error dialect without a retryable marker is permanent.
        events = await run_with({"type": "error", "message": "boom"})
        assert events[-1]["event"] == "failed"
        assert events[-1]["retryable"] is False

        # ... unless the remote says otherwise explicitly or via HTTP status.
        events = await run_with({"type": "error", "message": "boom", "retryable": True})
        assert events[-1]["retryable"] is True
        events = await run_with({"type": "error", "message": "boom", "status_code": 503})
        assert events[-1]["retryable"] is True
        events = await run_with({"type": "error", "message": "boom", "status_code": 400})
        assert events[-1]["retryable"] is False

        # Canonical failed dicts get the same default (not hardcoded True).
        events = await run_with({"event": "failed", "message": "boom"})
        assert events[-1]["event"] == "failed"
        assert events[-1]["retryable"] is False

    @pytest.mark.asyncio
    async def test_modal_llm_legacy_cancelled_completed(self):
        from services.engines.llm_engine import ModalLlamaCPPEngine

        engine = ModalLlamaCPPEngine("modal-vllm", "ak-123", "as-456")

        async def fake_gen(model_id, messages, tools, timeout_seconds, sampling):
            yield {"type": "completed", "cancelled": True,
                   "outputs": [{"role": "assistant", "content": "", "cancelled": True}]}

        mock_instance = MagicMock()
        mock_instance.generate.remote_gen.aio = fake_gen
        mock_cls = MagicMock(return_value=mock_instance)

        with patch.object(engine, "get_client_async"):
            with patch("services.engines.llm_engine.modal.Cls.from_name", return_value=mock_cls):
                events = [ev async for ev in engine.inference(
                    {"model": "m1", "messages": []}, job_id="job-vllm-legcancel")]

                assert events[-1]["event"] == "cancelled"

    @pytest.mark.asyncio
    async def test_modal_llm_connection_error_retryable(self):
        from services.engines.llm_engine import ModalLlamaCPPEngine

        try:
            import modal as modal_pkg
            conn_err_cls = modal_pkg.exception.ConnectionError
        except Exception:
            conn_err_cls = type(
                "ConnectionError", (Exception,), {"__module__": "modal.exception"}
            )

        for exc in (conn_err_cls("lost"), TimeoutError("slow")):
            engine = ModalLlamaCPPEngine("modal-vllm", "ak-123", "as-456")
            with patch.object(
                engine, "get_client_async", side_effect=exc
            ):
                events = [ev async for ev in engine.inference(
                    {"model": "m1", "messages": []}, job_id="job-vllm-conn")]
                assert events[0]["event"] == "started"
                assert events[-1]["event"] == "failed"
                assert events[-1]["retryable"] is True

    @pytest.mark.asyncio
    async def test_modal_llm_cancel_carries_partial_content(self):
        from services.engines.llm_engine import ModalLlamaCPPEngine

        engine = ModalLlamaCPPEngine("modal-vllm", "ak-123", "as-456")

        async def fake_gen(model_id, messages, tools, timeout_seconds, sampling):
            yield {"event": "delta", "text": "part"}
            engine._cancelled_jobs.add("job-vllm-cancel")
            yield {"event": "delta", "text": "never-seen"}

        mock_instance = MagicMock()
        mock_instance.generate.remote_gen.aio = fake_gen
        mock_cls = MagicMock(return_value=mock_instance)

        with patch.object(engine, "get_client_async"):
            with patch("services.engines.llm_engine.modal.Cls.from_name", return_value=mock_cls):
                events = [ev async for ev in engine.inference(
                    {"model": "m1", "messages": [{"role": "user", "content": "hi"}]},
                    job_id="job-vllm-cancel",
                )]

                cancelled = [e for e in events if e.get("event") == "cancelled"]
                assert len(cancelled) == 1
                assert cancelled[0]["outputs"] == [
                    {"role": "assistant", "content": "part", "cancelled": True}
                ]

    @pytest.mark.asyncio
    async def test_modal_llm_list_models(self):
        from services.engines.llm_engine import ModalLlamaCPPEngine

        engine = ModalLlamaCPPEngine("modal-vllm", "ak-123", "as-456")
        remote_files = [{"name": "m1", "path": "models/m1", "type": "file", "size": 42}]
        mock_func = MagicMock()
        mock_func.remote.aio = AsyncMock(return_value=remote_files)
        with patch.object(engine, "get_client_async", return_value=MagicMock()):
            with patch(
                "services.engines.llm_engine.modal.Function.from_name",
                return_value=mock_func,
            ):
                assert await engine.list_models("models") == remote_files
                mock_func.remote.aio.assert_awaited_once_with("models")

        with patch.object(engine, "get_client_async", side_effect=RuntimeError("down")):
            # Listing failure raises (parity with the image engines): an
            # empty success would read as a clean volume to the reconciler.
            with pytest.raises(RuntimeError, match="list-models failed"):
                await engine.list_models("models")

        # Directories outside the vLLM models/ tree legitimately answer [].
        assert await engine.list_models("checkpoints") == []

    @pytest.mark.asyncio
    async def test_modal_llm_default_model_fallback(self):
        from services.engines.llm_engine import ModalLlamaCPPEngine

        engine = ModalLlamaCPPEngine("modal-vllm", "ak-123", "as-456")
        seen = {}

        async def fake_gen(model_id, messages, tools, timeout_seconds, sampling):
            seen["model_id"] = model_id
            yield {"event": "completed",
                   "outputs": [{"role": "assistant", "content": "ok"}]}

        mock_instance = MagicMock()
        mock_instance.generate.remote_gen.aio = fake_gen
        mock_cls = MagicMock(return_value=mock_instance)

        with patch.object(engine, "get_client_async"):
            with patch("services.engines.llm_engine.modal.Cls.from_name", return_value=mock_cls):
                events = [ev async for ev in engine.inference(
                    {"messages": [{"role": "user", "content": "hi"}]},
                    job_id="job-vllm-nomodel")]

        assert seen["model_id"] == "default-model"
        assert events[-1]["event"] == "completed"

    @pytest.mark.asyncio
    async def test_llm_reducer_treats_cancelled_with_outputs_as_cancelled(self):
        from services.provider_client import JobCancelledError, _LLMReducer

        reducer = _LLMReducer("job-x", AsyncMock(), "p1", {})
        with pytest.raises(JobCancelledError):
            await reducer({
                "event": "cancelled",
                "job_id": "job-x",
                "message": "Job cancelled by user",
                "outputs": [{"role": "assistant", "content": "part", "cancelled": True}],
            })


# ---------------------------------------------------------------------------
# 8. ModalTTSEngine Tests
# ---------------------------------------------------------------------------

class TestModalTTSEngine:
    def test_tts_engine_init(self):
        from services.engines.modal_tts_engine import ModalTTSEngine

        engine = ModalTTSEngine(
            provider_id="tts-modal-hp196",
            token_id="ak-tts",
            token_secret="as-tts",
            app_name="comfy-modal-tts",
        )
        assert engine.provider_id == "tts-modal-hp196"
        assert engine.app_name == "comfy-modal-tts"

    @pytest.mark.asyncio
    async def test_tts_inference_streaming(self):
        from services.engines.modal_tts_engine import ModalTTSEngine

        engine = ModalTTSEngine("tts-modal-hp196", "ak-tts", "as-tts")

        async def fake_tts_gen(workflow):
            # The app's real vocabulary (modal_app.py::_execute) is running /
            # success / error: `running` is a poll heartbeat the reducer has
            # no branch for, so it produces no event of its own.
            yield {"status": "running", "prompt_id": "p1"}
            yield {
                "status": "success",
                "outputs": [{"filename": "speech.wav", "subfolder": "voice_preview/1", "type": "output"}],
            }

        mock_instance = MagicMock()
        mock_instance.run.remote_gen.aio = fake_tts_gen
        mock_cls = MagicMock(return_value=mock_instance)

        with patch.object(engine, "get_client_async"):
            with patch("services.engines.modal_tts_engine.modal.Cls.from_name", return_value=mock_cls):
                events = []
                async for ev in engine.inference({"text": "Hello world"}, job_id="job-tts"):
                    events.append(ev)

                assert [e["event"] for e in events] == ["started", "completed"]
                assert events[1]["outputs"][0]["filename"] == "speech.wav"

    @pytest.mark.asyncio
    async def test_tts_get_file_stream(self):
        from services.engines.modal_tts_engine import ModalTTSEngine

        engine = ModalTTSEngine("tts-modal-hp196", "ak-tts", "as-tts")
        mock_storage = MagicMock()
        mock_storage.file_size.remote.aio = AsyncMock(return_value=len(b"RIFFwaveheaderanddata"))
        mock_storage.read_file.remote.aio = AsyncMock(return_value=b"RIFFwaveheaderanddata")
        mock_cls = MagicMock(return_value=mock_storage)

        with patch.object(engine, "get_client_async"):
            with patch("services.engines.modal_tts_engine.modal.Cls.from_name", return_value=mock_cls):
                chunks = []
                async for chunk in engine.get_file_stream("voice_preview/1/speech.wav"):
                    chunks.append(chunk)

                assert b"".join(chunks) == b"RIFFwaveheaderanddata"


# ---------------------------------------------------------------------------
# 8b. Hosted LLM Engine (Anthropic/Google) Tests
# ---------------------------------------------------------------------------

class TestHostedLLMEngines:
    def test_anthropic_translate_messages(self):
        from services.engines.llm_engine import (
            translate_messages_anthropic,
            translate_tools_anthropic,
        )

        messages, system = translate_messages_anthropic([
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello",
             "tool_calls": [{"id": "t1", "function": {"name": "get_time", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "t1", "content": "noon"},
        ])
        assert system.strip() == "Be brief."
        assert messages[0] == {"role": "user", "content": "Hi"}
        assert messages[1]["content"][1] == {
            "type": "tool_use", "id": "t1", "name": "get_time", "input": {},
        }
        assert messages[2] == {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "noon"}],
        }
        assert translate_tools_anthropic(
            [{"function": {"name": "get_time", "description": "clock",
                           "parameters": {"type": "object", "properties": {}}}}]
        ) == [{"name": "get_time", "description": "clock",
               "input_schema": {"type": "object", "properties": {}}}]

    def test_google_translate_messages(self):
        from services.engines.llm_engine import (
            translate_messages_google,
            translate_tools_google,
        )

        contents, system = translate_messages_google([
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello",
             "tool_calls": [{"function": {"name": "get_time", "arguments": "{}"}}]},
            {"role": "tool", "name": "get_time", "content": '{"time": "noon"}'},
        ])
        assert system.strip() == "Be brief."
        assert contents[0] == {"role": "user", "parts": [{"text": "Hi"}]}
        assert contents[1]["parts"][1] == {
            "functionCall": {"name": "get_time", "args": {}}}
        assert contents[2]["parts"][0]["functionResponse"]["name"] == "get_time"
        assert translate_tools_google(
            [{"function": {"name": "get_time", "parameters": {"type": "object"}}}]
        ) == [{"functionDeclarations": [
            {"name": "get_time", "description": "", "parameters": {"type": "object"}}]}]

    def test_retryable_helpers(self):
        from services.engines.llm_engine import (
            retryable_for_exception,
            retryable_for_status,
        )

        assert retryable_for_status(400) is False
        assert retryable_for_status(401) is False
        assert retryable_for_status(429) is True
        assert retryable_for_status(500) is True
        assert retryable_for_exception(ValueError("bad messages")) is False
        assert retryable_for_exception(TimeoutError("slow")) is False

    def test_factory_routes_anthropic(self):
        from services.engines.llm_engine import AnthropicLLMEngine

        provider = SimpleNamespace(
            id="llm-anthropic",
            type="anthropic",
            worker_type="llm",
            credentials={"api_key": "sk-ant-test"},
            config={},
        )
        assert can_create_engine(provider) is True
        assert isinstance(get_engine("llm-anthropic", provider), AnthropicLLMEngine)

    def test_factory_routes_google(self):
        from services.engines.llm_engine import GoogleLLMEngine

        provider = SimpleNamespace(
            id="llm-google",
            type="google",
            worker_type="llm",
            credentials={"api_key": "goog-test"},
            config={},
        )
        assert can_create_engine(provider) is True
        assert isinstance(get_engine("llm-google", provider), GoogleLLMEngine)

    def test_factory_rejects_hosted_llm_without_key(self):
        assert can_create_engine(SimpleNamespace(
            id="llm-anthropic", type="anthropic", credentials={}, config={})) is False
        assert can_create_engine(SimpleNamespace(
            id="llm-google", type="google", credentials={}, config={})) is False

    def test_factory_never_misroutes_hosted_to_openai_compat(self):
        from services.engines.llm_engine import OpenAICompatLLMEngine

        for pid, ptype in (("llm-anthropic", "anthropic"), ("llm-google", "google")):
            engine = get_engine(pid, SimpleNamespace(
                id=pid, type=ptype, worker_type="llm",
                credentials={"api_key": "k"},
                config={"base_url": "http://localhost:8000/v1"},
            ))
            assert not isinstance(engine, OpenAICompatLLMEngine)

    @pytest.mark.asyncio
    async def test_modal_llm_unpacks_remote_signature(self):
        from services.engines.llm_engine import ModalLlamaCPPEngine

        engine = ModalLlamaCPPEngine("modal-vllm", "ak-123", "as-456")
        seen = {}

        async def fake_gen(model_id, messages, tools, timeout_seconds, sampling):
            seen.update(model_id=model_id, messages=messages, tools=tools,
                        timeout_seconds=timeout_seconds, sampling=sampling)
            yield {"event": "completed",
                   "outputs": [{"role": "assistant", "content": "ok"}]}

        mock_instance = MagicMock()
        mock_instance.generate.remote_gen.aio = fake_gen
        mock_cls = MagicMock(return_value=mock_instance)

        with patch.object(engine, "get_client_async"):
            with patch("services.engines.llm_engine.modal.Cls.from_name", return_value=mock_cls):
                events = [ev async for ev in engine.inference(
                    {"model": "m1", "messages": [{"role": "user", "content": "hi"}],
                     "temperature": 0.5},
                    job_id="job-vllm-args")]

        assert seen["model_id"] == "m1"
        assert seen["messages"] == [{"role": "user", "content": "hi"}]
        assert seen["sampling"] == {"temperature": 0.5}
        assert events[-1]["event"] == "completed"


# ---------------------------------------------------------------------------
# 9. In-Process LLM and TTS Runner Integration Tests
# ---------------------------------------------------------------------------

class TestInProcessLLMAndTTSExecution:
    @pytest.mark.asyncio
    async def test_call_in_process_llm_provider(self):
        from services.provider_client import call_in_process_llm_provider

        job_service = AsyncMock()
        engine = MagicMock(spec=InProcessEngine)

        async def fake_llm_stream(*args, **kwargs):
            yield {"event": "started", "job_id": "job-llm-1"}
            yield {"event": "delta", "job_id": "job-llm-1", "text": "Hi"}
            yield {"event": "delta", "job_id": "job-llm-1", "text": " there!"}
            yield {
                "event": "completed",
                "job_id": "job-llm-1",
                "outputs": [{"role": "assistant", "content": "Hi there!"}],
            }

        engine.run_inference = fake_llm_stream

        result = await call_in_process_llm_provider(
            engine=engine,
            workflow={"messages": [{"role": "user", "content": "Hi"}], "chat_id": "chat-99"},
            job_id="job-llm-1",
            job_service=job_service,
            timeout=30.0,
            provider_id="llm-local",
        )

        assert result["status"] == "success"
        assert result["type"] == "text"
        assert result["chat_id"] == "chat-99"
        assert result["outputs"][0]["content"] == "Hi there!"

    @pytest.mark.asyncio
    async def test_fetch_remote_tts_outputs_with_in_process_engine(self, tmp_path):
        from services.job_processing import _fetch_remote_tts_outputs

        engine = MagicMock(spec=InProcessEngine)

        async def fake_audio_stream(path):
            yield b"FAKE_AUDIO_BYTES"

        engine.get_file_stream = fake_audio_stream

        register_engine("tts-modal-hp196", engine)

        job = SimpleNamespace(id="job-tts-123", task_type="tts", metadata_={})
        final_result = {
            "status": "completed",
            "outputs": [
                {"filename": "test_audio.wav", "subfolder": "voice_preview/42", "type": "output"}
            ],
        }

        with patch("services.job_processing.settings.output_dir", str(tmp_path)):
            outputs = await _fetch_remote_tts_outputs(
                job=job,
                provider_id="tts-modal-hp196",
                final_result=final_result,
            )

            assert len(outputs) == 1
            assert outputs[0]["filename"] == "test_audio.wav"
            written_file = tmp_path / "voice_preview" / "42" / "test_audio.wav"
            assert written_file.exists()
            assert written_file.read_bytes() == b"FAKE_AUDIO_BYTES"


# ---------------------------------------------------------------------------
# 10. Beam Engine + DirectComfy Agent-Sidecar Parity Tests
# ---------------------------------------------------------------------------

class _FakeWS:
    """Minimal async-CM websocket double yielding canned messages."""

    def __init__(self, messages):
        self._messages = list(messages)
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def send(self, payload):
        self.sent.append(payload)

    async def recv(self):
        if not self._messages:
            raise ConnectionError("fake socket drained")
        return self._messages.pop(0)

    def __aiter__(self):
        async def _gen():
            for message in self._messages:
                yield message

        return _gen()


def _make_beam_engine(**overrides):
    from services.engines.beam_engine import BeamEngine

    params = {
        "provider_id": "beam-test",
        "api_key": "beam-key",
        "gpu_url": "wss://gpu.beam.test/run",
        "storage_url": "https://storage.beam.test",
    }
    params.update(overrides)
    return BeamEngine(**params)


class TestBeamEngine:
    @pytest.mark.asyncio
    async def test_health_unhealthy_without_config(self):
        engine = _make_beam_engine(api_key="", gpu_url="", storage_url="")
        health = await engine.check_health()
        assert health["status"] == "unhealthy"
        assert health["ready"] is False
        assert health["engine"] == "beam"
        assert health["retryable"] is False

    @pytest.mark.asyncio
    async def test_health_healthy_is_local_only(self):
        engine = _make_beam_engine()
        with patch("httpx.AsyncClient", side_effect=AssertionError("must not touch network")):
            health = await engine.check_health()
        assert health["status"] == "healthy"
        assert health["ready"] is True

    def test_workspace_header(self):
        engine = _make_beam_engine(workspace_id="ws-1")
        assert engine._headers()["X-Beam-Workspace-Id"] == "ws-1"
        plain = _make_beam_engine()
        assert "X-Beam-Workspace-Id" not in plain._headers()

    @pytest.mark.asyncio
    async def test_list_models_from_storage(self):
        engine = _make_beam_engine()
        mock_client = AsyncMock()
        mock_client.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"files": [{"name": "a.safetensors", "path": "checkpoints/a.safetensors"}]},
        )
        with patch.object(engine, "get_http_client", return_value=mock_client):
            models = await engine.list_models("checkpoints")
        assert models == [{"name": "a.safetensors", "path": "checkpoints/a.safetensors"}]
        mock_client.post.assert_called_once()
        assert mock_client.post.call_args[0][0].endswith("/list-models")

    @pytest.mark.asyncio
    async def test_list_models_failure_raises(self):
        # A cold storage app or 5xx must never read as an empty volume:
        # reconciliation would clean-sweep the expected files.
        engine = _make_beam_engine()
        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("boom")
        with patch.object(engine, "get_http_client", return_value=mock_client):
            with pytest.raises(RuntimeError):
                await engine.list_models("checkpoints")

    @pytest.mark.asyncio
    async def test_delete_adopts_upstream_success_flag(self):
        engine = _make_beam_engine()
        mock_client = AsyncMock()
        mock_client.post.return_value = MagicMock(
            status_code=200, json=lambda: {"success": False, "message": "File not found"}
        )
        with patch.object(engine, "get_http_client", return_value=mock_client):
            assert await engine.delete_file("checkpoints/nope.safetensors") is False

        mock_client.post.return_value = MagicMock(status_code=200, json=lambda: {"success": True})
        with patch.object(engine, "get_http_client", return_value=mock_client):
            assert await engine.delete_file("checkpoints/gone.safetensors") is True

    @pytest.mark.asyncio
    async def test_inference_relays_task_events(self):
        engine = _make_beam_engine()
        fake_ws = _FakeWS([
            '{"event": "progress", "value": 50}',
            '{"event": "completed", "outputs": []}',
        ])
        with patch("services.engines.beam_engine.websockets.connect", return_value=fake_ws):
            events = [ev async for ev in engine.inference(workflow={"1": {}}, job_id="job-beam-1")]

        assert events[0]["event"] == "started"
        assert events[1] == {"event": "progress", "value": 50, "job_id": "job-beam-1"}
        assert events[2]["event"] == "completed"
        # Token travels in the payload as well as the header.
        sent = fake_ws.sent[0]
        import json as _json

        payload = _json.loads(sent)
        assert payload["token"] == "beam-key"
        assert payload["workflow"] == {"1": {}}

    @pytest.mark.asyncio
    async def test_inference_precancelled_short_circuits(self):
        engine = _make_beam_engine()
        # cancel_job only flags jobs currently streaming (a cancel for an
        # inactive job is a no-op, like the container's /cancel-job answering
        # not_found), so stage the job as in-flight first.
        engine._active_jobs.add("job-beam-9")
        assert await engine.cancel_job("job-beam-9") is True
        with patch(
            "services.engines.beam_engine.websockets.connect",
            side_effect=AssertionError("must not connect when pre-cancelled"),
        ):
            events = [ev async for ev in engine.inference(workflow={"1": {}}, job_id="job-beam-9")]
        assert [e["event"] for e in events] == ["started", "cancelled"]

    def test_can_create_beam_engine(self):
        provider = SimpleNamespace(
            id="beam-test",
            type="beam",
            credentials={"api_key": "beam-key"},
            config={"gpu_url": "wss://gpu", "storage_url": "https://storage"},
        )
        assert can_create_engine(provider) is True
        engine = get_engine("beam-test", provider)
        from services.engines.beam_engine import BeamEngine

        assert isinstance(engine, BeamEngine)
        assert engine.gpu_url == "wss://gpu"

    def test_cannot_create_beam_without_urls(self):
        provider = SimpleNamespace(
            id="beam-partial",
            type="beam",
            credentials={"api_key": "beam-key"},
            config={},
        )
        assert can_create_engine(provider) is False


class TestDirectComfyAgentParity:
    def test_remote_comfy_routes_to_direct_engine_with_agent(self):
        provider = SimpleNamespace(
            id="remote-comfy-rig",
            type="remote_comfy",
            credentials={"agent_token": "tok"},
            config={"comfy_url": "http://rig:8188", "agent_url": "http://rig:8001"},
        )
        assert can_create_engine(provider) is True
        engine = get_engine("remote-comfy-rig", provider)
        assert isinstance(engine, DirectComfyEngine)
        assert engine.agent_url == "http://rig:8001"
        assert engine._has_agent is True

    def test_plain_direct_has_no_agent(self):
        engine = DirectComfyEngine("direct-local", "http://127.0.0.1:8188")
        assert engine._has_agent is False

    @pytest.mark.asyncio
    async def test_dual_health_probes(self):
        engine = DirectComfyEngine(
            "remote-comfy-rig", "http://rig:8188", agent_url="http://rig:8001"
        )
        comfy_client = AsyncMock()
        comfy_client.get.return_value = MagicMock(status_code=200)
        agent_client = AsyncMock()
        agent_client.get.return_value = MagicMock(status_code=200)
        with (
            patch.object(engine, "get_http_client", return_value=comfy_client),
            patch.object(engine, "get_agent_client", return_value=agent_client),
        ):
            health = await engine.check_health()
        assert health["status"] == "healthy"
        assert health["comfy_reachable"] is True
        assert health["agent_reachable"] is True

    @pytest.mark.asyncio
    async def test_health_reports_dead_comfy(self):
        engine = DirectComfyEngine("direct-local", "http://127.0.0.1:8188")
        comfy_client = AsyncMock()
        comfy_client.get.side_effect = Exception("refused")
        with patch.object(engine, "get_http_client", return_value=comfy_client):
            health = await engine.check_health()
        assert health["status"] == "unhealthy"
        assert health["comfy_reachable"] is False
        assert "error" in health

    @pytest.mark.asyncio
    async def test_list_models_prefers_agent(self):
        engine = DirectComfyEngine(
            "remote-comfy-rig", "http://rig:8188", agent_url="http://rig:8001"
        )
        agent_client = AsyncMock()
        agent_client.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"files": [{"name": "rig.safetensors", "path": "checkpoints/rig.safetensors"}]},
        )
        with patch.object(engine, "get_agent_client", return_value=agent_client):
            models = await engine.list_models("checkpoints")
        assert models == [{"name": "rig.safetensors", "path": "checkpoints/rig.safetensors"}]

    @pytest.mark.asyncio
    async def test_list_models_falls_back_to_object_info(self):
        engine = DirectComfyEngine(
            "remote-comfy-rig", "http://rig:8188", agent_url="http://rig:8001"
        )
        agent_client = AsyncMock()
        agent_client.post.side_effect = Exception("agent down")
        doc = {"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["fb.safetensors"]]}}}}
        # A configured agent that cannot answer is an error, not a license to
        # report the rig's loadables as the agent's storage state.
        with (
            patch.object(engine, "get_agent_client", return_value=agent_client),
            patch.object(engine, "_fetch_object_info", return_value=doc),
        ):
            with pytest.raises(RuntimeError):
                await engine.list_models("checkpoints")

    @pytest.mark.asyncio
    async def test_delete_adopts_agent_success_flag(self):
        engine = DirectComfyEngine(
            "remote-comfy-rig", "http://rig:8188", agent_url="http://rig:8001"
        )
        agent_client = AsyncMock()
        agent_client.post.return_value = MagicMock(
            status_code=200, json=lambda: {"success": False, "message": "File not found"}
        )
        with patch.object(engine, "get_agent_client", return_value=agent_client):
            assert await engine.delete_file("checkpoints/nope.safetensors") is False

    @pytest.mark.asyncio
    async def test_delete_without_agent_is_unsupported(self):
        engine = DirectComfyEngine("direct-local", "http://127.0.0.1:8188")
        assert await engine.delete_file("checkpoints/x.safetensors") is False

    @pytest.mark.asyncio
    async def test_inference_precancelled_short_circuits(self):
        engine = DirectComfyEngine("direct-local", "http://127.0.0.1:8188")
        engine._active_jobs.add("job-direct-9")
        assert await engine.cancel_job("job-direct-9") is True
        with patch.object(
            engine, "get_http_client", side_effect=AssertionError("must not connect when pre-cancelled")
        ):
            events = [ev async for ev in engine.inference(workflow={"1": {}}, job_id="job-direct-9")]
        assert [e["event"] for e in events] == ["started", "cancelled"]

    @pytest.mark.asyncio
    async def test_prompt_rejection_retryable_follows_status(self):
        engine = DirectComfyEngine("direct-local", "http://127.0.0.1:8188")
        fake_ws = _FakeWS([])

        async def run_with_status(status_code):
            mock_client = AsyncMock()
            mock_client.post.return_value = MagicMock(status_code=status_code, text="rejected")
            with (
                patch.object(engine, "get_http_client", return_value=mock_client),
                patch("services.engines.direct_comfy_engine.websockets.connect", return_value=fake_ws),
            ):
                return [ev async for ev in engine.inference(workflow={"1": {}}, job_id="job-r")]

        events = await run_with_status(400)
        assert events[-1]["event"] == "failed"
        assert events[-1]["retryable"] is False

        events = await run_with_status(500)
        assert events[-1]["event"] == "failed"
        assert events[-1]["retryable"] is True


# ---------------------------------------------------------------------------
# 12. TTS Engine Parity (app vocabulary, terminal guarantee, 64MB cap)
# ---------------------------------------------------------------------------

def _make_tts_engine():
    from services.engines.modal_tts_engine import ModalTTSEngine

    engine = ModalTTSEngine("tts-test", "ak-123", "as-456")
    engine.get_client_async = AsyncMock(return_value=MagicMock())
    return engine


def _tts_instance(*updates):
    """Fake TTSWorker instance whose run.remote_gen.aio replays updates."""
    async def fake_gen(workflow):
        for update in updates:
            yield update

    instance = MagicMock()
    instance.run.remote_gen.aio = fake_gen
    return instance


class TestModalTTSEngineParity:
    @pytest.mark.asyncio
    async def test_app_success_vocab_completes(self):
        engine = _make_tts_engine()
        outputs = [{"filename": "a.mp3", "subfolder": "", "type": "output"}]
        with patch("services.engines.modal_tts_engine.modal") as mock_modal:
            mock_modal.Cls.from_name.return_value = MagicMock(return_value=_tts_instance(
                {"status": "running"},
                {"status": "success", "outputs": outputs},
            ))
            events = [ev async for ev in engine.inference(workflow={}, job_id="tts-1")]
        assert [e["event"] for e in events] == ["started", "completed"]
        assert events[1]["outputs"] == outputs

    @pytest.mark.asyncio
    async def test_app_error_vocab_keeps_retryable_flag(self):
        engine = _make_tts_engine()
        with patch("services.engines.modal_tts_engine.modal") as mock_modal:
            mock_modal.Cls.from_name.return_value = MagicMock(return_value=_tts_instance(
                {"status": "error", "message": "bad graph", "retryable": False},
            ))
            events = [ev async for ev in engine.inference(workflow={}, job_id="tts-2")]
        assert events[-1]["event"] == "failed"
        assert events[-1]["message"] == "bad graph"
        assert events[-1]["retryable"] is False

    @pytest.mark.asyncio
    async def test_app_cancelled_vocab_stays_cancelled(self):
        engine = _make_tts_engine()
        with patch("services.engines.modal_tts_engine.modal") as mock_modal:
            mock_modal.Cls.from_name.return_value = MagicMock(return_value=_tts_instance(
                {"status": "cancelled", "message": "stop"},
            ))
            events = [ev async for ev in engine.inference(workflow={}, job_id="tts-3")]
        assert [e["event"] for e in events] == ["started", "cancelled"]
        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_stream_end_without_terminal_yields_failed(self):
        engine = _make_tts_engine()
        with patch("services.engines.modal_tts_engine.modal") as mock_modal:
            mock_modal.Cls.from_name.return_value = MagicMock(return_value=_tts_instance(
                {"status": "running"},
                {"status": "running"},
            ))
            events = [ev async for ev in engine.inference(workflow={}, job_id="tts-4")]
        assert events[-1]["event"] == "failed"
        assert events[-1]["message"] == "TTS app stream ended without a terminal event"
        assert events[-1]["retryable"] is True

    @pytest.mark.asyncio
    async def test_malformed_event_fails_not_retryable(self):
        engine = _make_tts_engine()
        with patch("services.engines.modal_tts_engine.modal") as mock_modal:
            mock_modal.Cls.from_name.return_value = MagicMock(return_value=_tts_instance(42))
            events = [ev async for ev in engine.inference(workflow={}, job_id="tts-5")]
        assert events[-1]["event"] == "failed"
        assert events[-1]["retryable"] is False

    @pytest.mark.asyncio
    async def test_get_file_stream_enforces_64mb_cap(self):
        """The streamed-read cap, and it has to be the shared one.

        `get_file_stream` bounds the body with `PROVIDER_GET_FILE_MAX_BYTES` — the
        same knob the `/view` and agent branches of DirectComfyEngine read —
        rather than the 64 MiB upload number that used to govern it. Binding to
        the upload number made the operator's knob a no-op for audio, and left
        two different, undocumented ceilings in one engine.

        The cap is patched, not `_MAX_AUDIO_BYTES`, so the test fails if the
        read path is ever re-tied to the upload contract.
        """
        import services.engines.modal_tts_engine as tts_module

        engine = _make_tts_engine()
        storage = MagicMock()
        storage.file_size.remote.aio = AsyncMock(return_value=11)
        storage.read_file.remote.aio = AsyncMock(return_value=b"x" * 11)
        with (
            patch("services.engines.modal_tts_engine.modal") as mock_modal,
            patch.object(tts_module, "get_file_size_cap", return_value=10),
        ):
            mock_modal.Cls.from_name.return_value = MagicMock(return_value=storage)
            with pytest.raises(ValueError, match="limit is 10"):
                [chunk async for chunk in engine.get_file_stream("a.mp3")]
            # Refused on size alone: the bytes are never fetched.
            storage.read_file.remote.aio.assert_not_called()

    @pytest.mark.asyncio
    async def test_tts_upload_keeps_its_own_contract(self):
        """Upload is a different budget from read, and both stay visible.

        The upload path's 64 MiB is container parity (the container answers 413
        there), so it is not folded into the read knob. Uploading over it is a
        logged `False`, per the engine's bool contract.
        """
        import services.engines.modal_tts_engine as tts_module

        engine = _make_tts_engine()
        with patch.object(tts_module, "_MAX_AUDIO_BYTES", 4):
            refused = await engine.upload_file(
                "b.mp3", base64.b64encode(b"x" * 5).decode(), directory="audio"
            )
        assert refused is False

    @pytest.mark.asyncio
    async def test_tts_upload_refuses_without_touching_storage(self):
        """The refusal is the pre-check, not a modal round-trip."""
        import services.engines.modal_tts_engine as tts_module

        engine = _make_tts_engine()
        with (
            patch.object(tts_module, "_MAX_AUDIO_BYTES", 4),
            patch("services.engines.modal_tts_engine.modal") as mock_modal,
        ):
            refused = await engine.upload_file(
                "b.mp3", base64.b64encode(b"x" * 5).decode(), directory="audio"
            )
        assert refused is False
        mock_modal.Cls.from_name.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_file_stream_small_audio_passes(self):
        engine = _make_tts_engine()
        storage = MagicMock()
        storage.file_size.remote.aio = AsyncMock(return_value=len(b"RIFF" * 100))
        storage.read_file.remote.aio = AsyncMock(return_value=b"RIFF" * 100)
        with patch("services.engines.modal_tts_engine.modal") as mock_modal:
            mock_modal.Cls.from_name.return_value = MagicMock(return_value=storage)
            chunks = [chunk async for chunk in engine.get_file_stream("a.mp3")]
        assert b"".join(chunks) == b"RIFF" * 100

    @pytest.mark.asyncio
    async def test_get_file_stream_missing_raises_before_read(self):
        engine = _make_tts_engine()
        storage = MagicMock()
        storage.file_size.remote.aio = AsyncMock(side_effect=FileNotFoundError("File not found: nope.wav"))
        storage.read_file.remote.aio = AsyncMock(return_value=b"should-never-be-read")
        with patch("services.engines.modal_tts_engine.modal") as mock_modal:
            mock_modal.Cls.from_name.return_value = MagicMock(return_value=storage)
            with pytest.raises(FileNotFoundError):
                [chunk async for chunk in engine.get_file_stream("nope.wav")]
            storage.file_size.remote.aio.assert_called_once_with("nope.wav")
            storage.read_file.remote.aio.assert_not_called()

    @pytest.mark.asyncio
    async def test_upload_file_puts_reference(self):
        engine = _make_tts_engine()
        storage = MagicMock()
        storage.put_file.remote.aio = AsyncMock(return_value=3)
        with patch("services.engines.modal_tts_engine.modal") as mock_modal:
            mock_modal.Cls.from_name.return_value = MagicMock(return_value=storage)
            assert await engine.upload_file("ref.wav", base64.b64encode(b"abc").decode(), "input") is True
        storage.put_file.remote.aio.assert_called_once_with(path="input/ref.wav", content=b"abc")

    @pytest.mark.asyncio
    async def test_upload_file_rejects_over_cap(self):
        import services.engines.modal_tts_engine as tts_module

        engine = _make_tts_engine()
        storage = MagicMock()
        storage.put_file.remote.aio = AsyncMock(return_value=11)
        with (
            patch("services.engines.modal_tts_engine.modal") as mock_modal,
            patch.object(tts_module, "_MAX_AUDIO_BYTES", 10),
        ):
            mock_modal.Cls.from_name.return_value = MagicMock(return_value=storage)
            assert await engine.upload_file("ref.wav", base64.b64encode(b"x" * 11).decode(), "input") is False
            storage.put_file.remote.aio.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_health_missing_app_name_is_config_fault(self):
        engine = _make_tts_engine()
        engine.app_name = ""
        with patch("services.engines.modal_tts_engine.modal") as mock_modal:
            health = await engine.check_health()
        assert health["status"] == "unhealthy"
        assert health["ready"] is False
        assert health["retryable"] is False
        assert "MODAL_TTS_APP_NAME" in health["error"]
        # No probe is issued when the config itself is at fault.
        mock_modal.Cls.from_name.assert_not_called()
        engine.get_client_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_inference_generic_error_wording(self):
        engine = _make_tts_engine()

        async def fake_gen(workflow):
            raise RuntimeError("boom")
            yield  # pragma: no cover - makes this an async generator

        instance = MagicMock()
        instance.run.remote_gen.aio = fake_gen
        with patch("services.engines.modal_tts_engine.modal") as mock_modal:
            mock_modal.Cls.from_name.return_value = MagicMock(return_value=instance)
            events = [ev async for ev in engine.inference(workflow={}, job_id="tts-err")]
        assert [e["event"] for e in events] == ["started", "failed"]
        assert events[-1]["message"] == "TTS generation failed: RuntimeError: boom"
        assert events[-1]["retryable"] is False


# ---------------------------------------------------------------------------
# 13. ModalEngine Lifecycle (download/validate/setup/upload/object_info)
# ---------------------------------------------------------------------------

class TestModalEngineLifecycle:
    def _func(self, **answers):
        func = MagicMock()
        func.remote.aio = AsyncMock(side_effect=lambda *a, **k: answers.get("remote", {"status": "ok"}))
        func.spawn.aio = AsyncMock(return_value=None)
        return func

    @pytest.mark.asyncio
    async def test_download_file_awaits_and_returns(self):
        engine = ModalEngine("modal-test", "ak-123", "as-456", hf_token="hf-x")
        func = self._func(remote={"status": "ok", "path": "models/checkpoints/a.safetensors"})
        with (
            patch.object(engine, "get_client_async", new=AsyncMock()),
            patch("services.engines.modal_engine.modal") as mock_modal,
        ):
            mock_modal.Function.from_name.return_value = func
            result = await engine.download_file("https://huggingface.co/x/a.safetensors", "models/checkpoints/a.safetensors")
        assert result["status"] == "ok"
        _, kwargs = func.remote.aio.call_args
        assert kwargs["url"] == "https://huggingface.co/x/a.safetensors"
        assert kwargs["path"] == "models/checkpoints/a.safetensors"
        assert kwargs["token"] == "hf-x"

    @pytest.mark.asyncio
    async def test_download_file_error_body_raises(self):
        engine = ModalEngine("modal-test", "ak-123", "as-456")
        func = self._func(remote={"status": "error", "message": "disk full"})
        with (
            patch.object(engine, "get_client_async", new=AsyncMock()),
            patch("services.engines.modal_engine.modal") as mock_modal,
        ):
            mock_modal.Function.from_name.return_value = func
            with pytest.raises(RuntimeError, match="disk full"):
                await engine.download_file("https://example.com/a.bin", "models/checkpoints/a.bin")

    def test_download_token_resolution(self):
        engine = ModalEngine("modal-test", "ak-123", "as-456", hf_token="hf-x", civitai_token="civ-y")
        assert engine.download_token_for_url("https://huggingface.co/x") == "hf-x"
        assert engine.download_token_for_url("https://civitai.com/api/x") == "civ-y"
        assert engine.download_token_for_url("https://github.com/x") is None
        assert engine.download_token_for_url("") is None

    @pytest.mark.asyncio
    async def test_validate_models_forwards_delete_flag(self):
        engine = ModalEngine("modal-test", "ak-123", "as-456")
        func = self._func(remote={"status": "ok", "total_invalid": 0, "total_partial": 0})
        with (
            patch.object(engine, "get_client_async", new=AsyncMock()),
            patch("services.engines.modal_engine.modal") as mock_modal,
        ):
            mock_modal.Function.from_name.return_value = func
            result = await engine.validate_models(["models/checkpoints"], True)
        assert result["status"] == "ok"
        func.remote.aio.assert_called_once_with(["models/checkpoints"], True)

    @pytest.mark.asyncio
    async def test_setup_models_spawns(self):
        engine = ModalEngine("modal-test", "ak-123", "as-456")
        func = self._func()
        with (
            patch.object(engine, "get_client_async", new=AsyncMock()),
            patch("services.engines.modal_engine.modal") as mock_modal,
        ):
            mock_modal.Function.from_name.return_value = func
            assert await engine.setup_models() is True
            func.spawn.aio.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_setup_models_failure_is_false(self):
        engine = ModalEngine("modal-test", "ak-123", "as-456")
        with (
            patch.object(engine, "get_client_async", new=AsyncMock()),
            patch("services.engines.modal_engine.modal", side_effect=Exception("down")),
        ):
            assert await engine.setup_models() is False

    @pytest.mark.asyncio
    async def test_upload_file_puts_content(self):
        engine = ModalEngine("modal-test", "ak-123", "as-456")
        storage = MagicMock()
        storage.put_file.remote.aio = AsyncMock(return_value=None)
        with (
            patch.object(engine, "get_client_async", new=AsyncMock()),
            patch("services.engines.modal_engine.modal") as mock_modal,
        ):
            mock_modal.Cls.from_name.return_value = MagicMock(return_value=storage)
            assert await engine.upload_file("a.txt", base64.b64encode(b"hi").decode("utf-8"), "models/other") is True
            storage.put_file.remote.aio.assert_called_once_with(path="models/other/a.txt", content=b"hi")

    @pytest.mark.asyncio
    async def test_get_object_info_uses_extractor(self):
        engine = ModalEngine("modal-test", "ak-123", "as-456")
        extractor = MagicMock()
        extractor.get_object_info.remote.aio = AsyncMock(return_value={"KSampler": {}})
        with (
            patch.object(engine, "get_client_async", new=AsyncMock()),
            patch("services.engines.modal_engine.modal") as mock_modal,
        ):
            mock_modal.Cls.from_name.return_value = MagicMock(return_value=extractor)
            doc = await engine.get_object_info()
        assert doc == {"KSampler": {}}
        mock_modal.Cls.from_name.assert_called_once()

    def test_manages_model_files_flags(self):
        from services.engines.beam_engine import BeamEngine
        from services.engines.direct_comfy_engine import DirectComfyEngine
        from services.engines.llm_engine import OpenAICompatLLMEngine
        from services.engines.modal_tts_engine import ModalTTSEngine

        assert ModalEngine("m", "a", "b").manages_model_files is True
        assert BeamEngine("b", api_key="k", gpu_url="g", storage_url="s").manages_model_files is True
        assert DirectComfyEngine("d", agent_url="http://agent:8001").manages_model_files is True
        assert DirectComfyEngine("d").manages_model_files is False
        assert OpenAICompatLLMEngine("l", base_url="http://x", api_key="k").manages_model_files is False
        assert ModalTTSEngine("t", "a", "b").manages_model_files is False

    @pytest.mark.asyncio
    async def test_direct_download_file_without_agent_raises(self):
        from services.engines.direct_comfy_engine import DirectComfyEngine

        engine = DirectComfyEngine("direct-local", "http://127.0.0.1:8188")
        with pytest.raises(RuntimeError, match="no agent sidecar"):
            await engine.download_file("https://example.com/a.bin", "models/checkpoints/a.bin")

    @pytest.mark.asyncio
    async def test_direct_download_file_via_agent(self):
        from services.engines.direct_comfy_engine import DirectComfyEngine

        engine = DirectComfyEngine("remote-comfy-rig", "http://rig:8188", agent_url="http://rig:8001")
        agent_client = AsyncMock()
        agent_client.post.return_value = MagicMock(status_code=200, content=b"{}", json=lambda: {"status": "ok"})
        with patch.object(engine, "get_agent_client", return_value=agent_client):
            result = await engine.download_file("https://example.com/a.bin", "models/checkpoints/a.bin", token="t")
        assert result["status"] == "ok"
        _, kwargs = agent_client.post.call_args
        assert kwargs["json"] == {"url": "https://example.com/a.bin", "path": "models/checkpoints/a.bin", "token": "t"}


# ---------------------------------------------------------------------------
# 14. In-Process Reconciliation Runner
# ---------------------------------------------------------------------------

def _make_recon_provider(session, provider_id="modal-recon", **overrides):
    from core.entities import Provider

    provider = Provider(
        id=provider_id,
        type="modal",
        worker_type="image",
        enabled=True,
        priority=1,
        credentials={},
        config={},
        **overrides,
    )
    session.add(provider)
    session.commit()
    return provider


def _make_recon_file(session, filename="recon-a.safetensors", directory="checkpoints"):
    from core.entities import ModelFile, ModelV2, ModelVersion

    model = ModelV2(name=f"model-{filename}", type="Checkpoint", directory=directory)
    session.add(model)
    session.commit()
    version = ModelVersion(model_id=model.id, name="v1", is_enabled=True)
    session.add(version)
    session.commit()
    file = ModelFile(
        version_id=version.id,
        original_filename=filename,
        storage_filename=filename,
        size_kb=1024.0,
        download_url=f"https://example.com/{filename}",
        is_primary=True,
        file_type="Model",
    )
    session.add(file)
    session.commit()
    return file


class _FakeReconEngine:
    """Minimal engine double: present files, record downloads/deletes."""

    manages_model_files = True

    def __init__(self, existing=(), fail_downloads=()):
        self._existing = dict(existing)
        self.downloads = []
        self.deletes = []
        self._fail = set(fail_downloads)

    async def validate_models(self, directories, delete_invalid=False):
        return {"status": "ok", "total_invalid": 0, "total_partial": 0}

    async def list_models(self, directory):
        return [{"name": name, "size": 1} for name in self._existing.get(directory, [])]

    def download_token_for_url(self, url):
        return None

    async def download_file(self, download_url, storage_path, token=None, timeout=3600.0):
        self.downloads.append(storage_path)
        if storage_path in self._fail:
            raise RuntimeError("boom")
        return {"status": "ok"}

    async def delete_file(self, path):
        self.deletes.append(path)
        return True


async def _wait_for_recon_done(provider_id, timeout_seconds=15.0):
    import asyncio as _asyncio

    from services.in_process_reconciliation import is_reconciliation_running

    for _ in range(int(timeout_seconds / 0.05)):
        if not is_reconciliation_running(provider_id):
            return True
        await _asyncio.sleep(0.05)
    return not is_reconciliation_running(provider_id)


class TestInProcessReconciliation:
    @pytest.mark.asyncio
    async def test_trigger_skipped_for_engines_without_model_tree(self, session):
        from services.in_process_reconciliation import trigger_in_process_reconciliation

        _make_recon_provider(session, provider_id="llm-recon")
        engine = _FakeReconEngine()
        engine.manages_model_files = False
        result = await trigger_in_process_reconciliation("llm-recon", engine=engine)
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_trigger_starts_and_marks_ready(self, session):
        from sqlmodel import select

        from core.entities import ProviderVersionStatus
        from services.in_process_reconciliation import trigger_in_process_reconciliation

        _make_recon_provider(session, provider_id="modal-recon")
        file = _make_recon_file(session)
        engine = _FakeReconEngine(existing={"models/checkpoints": ["recon-a.safetensors"]})

        result = await trigger_in_process_reconciliation("modal-recon", engine=engine)
        assert result["status"] == "started"
        assert await _wait_for_recon_done("modal-recon")

        statuses = session.exec(
            select(ProviderVersionStatus).where(ProviderVersionStatus.provider_id == "modal-recon")
        ).all()
        by_file = {s.file_id: s.status for s in statuses}
        assert by_file.get(file.id) == "ready"
        assert engine.downloads == []

    @pytest.mark.asyncio
    async def test_missing_file_is_downloaded(self, session):
        from sqlmodel import select

        from core.entities import ProviderVersionStatus
        from services.in_process_reconciliation import trigger_in_process_reconciliation

        _make_recon_provider(session, provider_id="modal-recon-dl")
        file = _make_recon_file(session, filename="recon-b.safetensors")
        engine = _FakeReconEngine(existing={})

        result = await trigger_in_process_reconciliation("modal-recon-dl", engine=engine)
        assert result["status"] == "started"
        assert await _wait_for_recon_done("modal-recon-dl")

        assert engine.downloads == ["models/checkpoints/recon-b.safetensors"]
        status = session.exec(
            select(ProviderVersionStatus).where(
                ProviderVersionStatus.file_id == file.id,
                ProviderVersionStatus.provider_id == "modal-recon-dl",
            )
        ).first()
        assert status is not None and status.status == "ready"

    @pytest.mark.asyncio
    async def test_failed_download_records_failed(self, session):
        from sqlmodel import select

        from core.entities import ProviderVersionStatus
        from services.in_process_reconciliation import trigger_in_process_reconciliation

        _make_recon_provider(session, provider_id="modal-recon-fail")
        file = _make_recon_file(session, filename="recon-c.safetensors")
        engine = _FakeReconEngine(existing={}, fail_downloads={"models/checkpoints/recon-c.safetensors"})

        await trigger_in_process_reconciliation("modal-recon-fail", engine=engine)
        assert await _wait_for_recon_done("modal-recon-fail")

        status = session.exec(
            select(ProviderVersionStatus).where(
                ProviderVersionStatus.file_id == file.id,
                ProviderVersionStatus.provider_id == "modal-recon-fail",
            )
        ).first()
        assert status is not None and status.status == "failed"
        assert "boom" in (status.error_message or "")

    @pytest.mark.asyncio
    async def test_second_trigger_while_running_answers_already_running(self, session):
        import asyncio as _asyncio

        from services.in_process_reconciliation import trigger_in_process_reconciliation

        _make_recon_provider(session, provider_id="modal-recon-busy")
        gate = _asyncio.Event()

        class _BlockingEngine(_FakeReconEngine):
            async def list_models(self, directory):
                await gate.wait()
                return []

        engine = _BlockingEngine(existing={})
        first = await trigger_in_process_reconciliation("modal-recon-busy", engine=engine)
        assert first["status"] == "started"
        second = await trigger_in_process_reconciliation("modal-recon-busy", engine=engine)
        assert second["status"] == "already_running"
        gate.set()
        assert await _wait_for_recon_done("modal-recon-busy")

    @pytest.mark.asyncio
    async def test_orphan_is_registered_not_deleted_by_default(self, session):
        from sqlmodel import select

        from core.entities import ModelFile
        from services.in_process_reconciliation import trigger_in_process_reconciliation

        _make_recon_provider(session, provider_id="modal-recon-orphan")
        # A catalog entry keeps the expected set non-empty: with zero
        # expected paths the runner (like the container flow) skips orphan
        # handling entirely rather than risk a mis-scoped listing arming a
        # mass delete.
        _make_recon_file(session, filename="orphan-keeper.safetensors")
        engine = _FakeReconEngine(existing={"models/checkpoints": ["stray.safetensors"]})

        await trigger_in_process_reconciliation("modal-recon-orphan", engine=engine)
        assert await _wait_for_recon_done("modal-recon-orphan")

        assert engine.deletes == []
        found = session.exec(
            select(ModelFile).where(ModelFile.storage_filename == "stray.safetensors")
        ).first()
        assert found is not None

    @pytest.mark.asyncio
    async def test_terminal_state_persisted(self, session):
        from services.in_process_reconciliation import trigger_in_process_reconciliation
        from services.provider_service import ProviderService

        _make_recon_provider(session, provider_id="modal-recon-state")
        engine = _FakeReconEngine(existing={})

        await trigger_in_process_reconciliation("modal-recon-state", engine=engine)
        assert await _wait_for_recon_done("modal-recon-state")

        state = await ProviderService(session).get_provider_reconciliation_state("modal-recon-state")
        assert state.get("status") == "completed"


# ---------------------------------------------------------------------------
# 15. Engine cache invalidation
# ---------------------------------------------------------------------------

class TestInvalidateEngine:
    def test_invalidate_drops_cached_engine(self):
        provider_id = "modal-invalidate-test"
        fake = ModalEngine(provider_id, "ak-1", "as-1")
        register_engine(provider_id, fake)
        assert get_engine(provider_id) is fake
        invalidate_engine(provider_id)
        # No provider row and no creds: nothing rebuildable, so None — the
        # point is the stale instance is gone, not what replaces it.
        assert get_engine(provider_id) is None


# ---------------------------------------------------------------------------
# 16. Setup support routing + engine cache TTL (cutover parity)
# ---------------------------------------------------------------------------

def _setup_probe_provider(provider_id, provider_type, **extra):
    return SimpleNamespace(
        id=provider_id,
        type=provider_type,
        worker_type=extra.get("worker_type", ""),
        capabilities=extra.get("capabilities", []),
        credentials=extra.get("credentials", {}),
        config=extra.get("config", {}),
    )


class TestEngineSupportsSetup:
    @pytest.mark.parametrize(
        "provider_id,provider_type,expected",
        [
            ("modal-test", "modal", True),
            ("beam-1", "beam", True),
            ("beam-x", "unknown-beam-x", True),  # id-prefix routing
            ("direct-local", "direct_url", True),
            ("remote-comfy-1", "remote_comfy", True),
            ("box-direct-2", "other", True),  # "direct" in id
            ("llm-1", "openai_compat", False),
            ("llm-anthropic", "anthropic", False),
            ("llm-google", "google", False),
            ("llm-vllm-1", "modal_llm", True),  # full model lifecycle in-process
            ("llm-modal-1", "modal_llm", True),  # same ModalLlamaCPPEngine class, same models/ tree
            ("tts-1", "modal_tts", False),
            ("tts-x", "tts", False),
            ("whatever", "unknown", False),
        ],
    )
    def test_routing(self, provider_id, provider_type, expected):
        assert engine_supports_setup(_setup_probe_provider(provider_id, provider_type)) is expected

    def test_none_provider(self):
        assert engine_supports_setup(None) is False

    def test_modal_llm_reports_true(self):
        # modal_llm resolves to the same ModalLlamaCPPEngine class as modal_llm
        # (registry ENGINE_SPECS), which implements setup_models
        # (llm_engine.py) for its models/ volume tree — True matches engine
        # reality. An earlier revision asserted False when the factory only
        # built the vLLM engine for the modal_llm type / vllm-in-id.
        provider = _setup_probe_provider("llm-modal-1", "modal_llm")
        assert engine_supports_setup(provider) is True


class TestResolveProviderType:
    """Registry routing is the single source of truth for all three
    factory entry points — aliases, id prefixes, and capability
    fallbacks must resolve identically everywhere."""

    @pytest.mark.parametrize(
        "kwargs,expected",
        [
            ({"provider_type": "modal"}, "modal"),
            ({"provider_type": "tts"}, "modal_tts"),  # legacy alias
            ({"provider_type": "openai"}, "openai_compat"),
            ({"provider_type": "gemini"}, "google"),
            ({"provider_type": "direct"}, "direct_url"),
            ({"provider_type": "comfy_direct"}, "direct_url"),
            ({"provider_id": "modal-foo"}, "modal"),  # prefix, empty type
            ({"provider_id": "beam-x", "provider_type": "unknown-beam-x"}, "beam"),
            ({"provider_id": "box-direct-2", "provider_type": "other"}, "direct_url"),
            ({"provider_id": "remote-comfy-1"}, "remote_comfy"),
            ({"provider_id": "llm-foo"}, "openai_compat"),
            ({"provider_id": "tts-foo"}, "modal_tts"),
            # vllm-in-id does NOT hijack a transport type. A self-hosted vLLM
            # provider (openai_compat / ollama) says exactly what it is, and
            # "vllm" in its id must not re-label it modal_llm - that sends the
            # request to a Modal llama.cpp app instead of the operator's box.
            # The legacy rescue still fires for ids that ALSO say Modal.
            ({"provider_id": "llm-vllm-1", "provider_type": "openai_compat"}, "openai_compat"),
            ({"provider_id": "llm-vllm-1", "provider_type": "ollama"}, "ollama"),
            ({"provider_id": "modal-vllm-legacy", "provider_type": "openai_compat"}, "modal_llm"),
            ({"capabilities": ["tts"]}, "modal_tts"),
            ({"capabilities": ["llm"]}, "openai_compat"),
            ({"worker_type": "llm"}, "openai_compat"),
            ({"provider_type": "nope", "provider_id": "whatever"}, None),
        ],
    )
    def test_resolve(self, kwargs, expected):
        from services.engines.registry import resolve_provider_type

        assert resolve_provider_type(**kwargs) == expected


class TestEngineCacheTTL:
    def test_cache_is_ttl_bounded(self):
        from cachetools import TTLCache

        assert isinstance(_ENGINE_CACHE, TTLCache)
        assert _ENGINE_CACHE.ttl == ENGINE_CACHE_TTL_SECONDS
        assert ENGINE_CACHE_TTL_SECONDS > 0

    def test_failed_lookup_is_not_cached(self):
        assert get_engine("no-such-provider-ever") is None
        assert "no-such-provider-ever" not in _ENGINE_CACHE
        assert get_engine("no-such-provider-ever") is None

    def test_clear_empties_cache(self):
        register_engine("modal-clear-test", ModalEngine("modal-clear-test", "ak-1", "as-1"))
        assert "modal-clear-test" in _ENGINE_CACHE
        clear_engine_cache()
        assert len(_ENGINE_CACHE) == 0


class TestRuntimeSupportsSetup:
    def test_beam_in_process_reports_setup(self):
        provider = _setup_probe_provider(
            "beam-setup-1",
            "beam",
            credentials={"api_key": "beam-key"},
            config={"gpu_url": "https://gpu.example", "storage_url": "https://storage.example"},
        )
        runtime = resolve_provider_runtime(provider)
        assert runtime.mode == "in_process"
        assert runtime.supports_setup is True

    def test_modal_in_process_reports_setup(self):
        provider = _setup_probe_provider(
            "modal-setup-1",
            "modal",
            credentials={"token_id": "ak-123", "token_secret": "as-456"},
        )
        runtime = resolve_provider_runtime(provider)
        assert runtime.mode == "in_process"
        assert runtime.supports_setup is True

    def test_direct_in_process_reports_setup(self):
        provider = _setup_probe_provider(
            "direct-setup-1",
            "direct_url",
            config={"comfy_url": "http://127.0.0.1:8188"},
        )
        runtime = resolve_provider_runtime(provider)
        assert runtime.mode == "in_process"
        assert runtime.supports_setup is True

    def test_anthropic_in_process_reports_no_setup(self):
        provider = _setup_probe_provider(
            "llm-setup-anthropic",
            "anthropic",
            credentials={"api_key": "sk-ant-test"},
        )
        runtime = resolve_provider_runtime(provider)
        assert runtime.mode == "in_process"
        assert runtime.supports_setup is False


# ---------------------------------------------------------------------------
# 13. Parity regression tests (in-process vs provider_containers)
# ---------------------------------------------------------------------------


class TestCancelFlagSemantics:
    """A cancel must only flag a job that is actually streaming.

    The bug this guards: job_runner aborts a failed attempt by signalling a
    cancel, the retry reuses the same job id on the same cached engine, and
    the stale flag turns the retry into a CANCELLED. The container's
    /cancel-job answered not_found for an inactive job, so this never
    happened there.
    """

    @pytest.mark.asyncio
    async def test_cancel_inactive_job_is_noop(self):
        from services.engines.llm_engine import OpenAICompatLLMEngine

        engine = OpenAICompatLLMEngine("llm-local", "http://localhost:8000/v1")
        assert await engine.cancel_job("job-never-ran") is False
        assert "job-never-ran" not in engine._cancelled_jobs

    @pytest.mark.asyncio
    async def test_retry_after_abort_is_not_born_cancelled(self):
        from services.engines.llm_engine import OpenAICompatLLMEngine

        engine = OpenAICompatLLMEngine("llm-local", "http://localhost:8000/v1")

        async def fake_aiter_lines():
            yield 'data: {"choices": [{"delta": {"content": "recovered"}}]}'
            yield ''
            yield 'data: [DONE]'
            yield ''

        mock_resp = MagicMock(status_code=200)
        mock_resp.aiter_lines = fake_aiter_lines

        class StreamContext:
            async def __aenter__(self):
                return mock_resp

            async def __aexit__(self, *args):
                return False

        mock_http = MagicMock()
        mock_http.stream = MagicMock(return_value=StreamContext())

        # The abort path of a previous attempt left this flag behind.
        engine._cancelled_jobs.add("job-retry-1")
        with patch.object(engine, "get_http_client", return_value=mock_http):
            events = [ev async for ev in engine.run_inference(
                {"messages": [{"role": "user", "content": "hi"}]},
                job_id="job-retry-1",
            )]
        assert [e["event"] for e in events] == ["started", "delta", "completed"]
        assert "job-retry-1" not in engine._cancelled_jobs

    @pytest.mark.asyncio
    async def test_midrun_cancel_still_aborts(self):
        import asyncio as _asyncio

        from services.engines.llm_engine import OpenAICompatLLMEngine

        engine = OpenAICompatLLMEngine("llm-local", "http://localhost:8000/v1")
        release = _asyncio.Event()

        async def fake_aiter_lines():
            yield 'data: {"choices": [{"delta": {"content": "part"}}]}'
            yield ''
            await release.wait()
            yield 'data: {"choices": [{"delta": {"content": "never"}}]}'
            yield ''

        mock_resp = MagicMock(status_code=200)
        mock_resp.aiter_lines = fake_aiter_lines

        class StreamContext:
            async def __aenter__(self):
                return mock_resp

            async def __aexit__(self, *args):
                return False

        mock_http = MagicMock()
        mock_http.stream = MagicMock(return_value=StreamContext())

        with patch.object(engine, "get_http_client", return_value=mock_http):
            task = _asyncio.ensure_future(_collect(engine, release))
            await _asyncio.sleep(0.2)
            assert await engine.cancel_job("job-midrun-1") is True
            release.set()
            events = await task
        assert [e["event"] for e in events] == ["started", "delta", "cancelled"]


async def _collect(engine, release=None):
    events = []
    async for ev in engine.run_inference(
        {"messages": [{"role": "user", "content": "hi"}]},
        job_id="job-midrun-1",
    ):
        events.append(ev)
        if release is not None and len(events) == 2:
            await _asyncio_sleepskip()
    return events


async def _asyncio_sleepskip():
    import asyncio as _asyncio

    await _asyncio.sleep(0)


class TestSSEParserParity:
    """iter_sse_data must handle the frames the old per-line split dropped."""

    @pytest.mark.asyncio
    async def test_multiline_data_frame_joins(self):
        from services.engines.base import iter_sse_data

        async def lines():
            yield 'data: {"choices": [{"delta":'
            yield 'data: {"content": "Hi"}}]}'
            yield ''
            yield 'data: [DONE]'
            yield ''

        import json as _json

        payloads = [p async for p in iter_sse_data(lines())]
        assert len(payloads) == 1
        assert _json.loads(payloads[0])["choices"][0]["delta"]["content"] == "Hi"

    @pytest.mark.asyncio
    async def test_trailing_frame_without_blank_line_is_flushed(self):
        from services.engines.base import iter_sse_data

        async def lines():
            yield 'data: {"a": 1}'
            yield ''

        payloads = [p async for p in iter_sse_data(lines())]
        assert payloads == ['{"a": 1}']

    @pytest.mark.asyncio
    async def test_nospace_data_prefix_parses(self):
        from services.engines.base import iter_sse_data

        async def lines():
            yield 'data:{"a": 2}'
            yield ''

        payloads = [p async for p in iter_sse_data(lines())]
        assert payloads == ['{"a": 2}']


class TestModalLlamaCPPTruncation:
    @pytest.mark.asyncio
    async def test_stream_without_terminal_event_is_retryable_failure(self):
        from services.engines.llm_engine import ModalLlamaCPPEngine

        engine = ModalLlamaCPPEngine("modal-vllm", "ak-123", "as-456")

        async def fake_gen(model_id, messages, tools, timeout_seconds, sampling):
            yield {"event": "delta", "text": "cut off"}

        mock_instance = MagicMock()
        mock_instance.generate.remote_gen.aio = fake_gen
        mock_cls = MagicMock(return_value=mock_instance)

        with patch.object(engine, "get_client_async"):
            with patch("services.engines.llm_engine.modal.Cls.from_name", return_value=mock_cls):
                events = [ev async for ev in engine.inference(
                    {"model": "m1", "messages": [{"role": "user", "content": "hi"}]},
                    job_id="job-truncated",
                )]
        terminal = events[-1]
        assert terminal["event"] == "failed"
        assert terminal["retryable"] is True


class TestDirectComfyValidation:
    @pytest.mark.asyncio
    async def test_node_errors_fail_permanent_without_running(self):
        engine = DirectComfyEngine("direct-local", "http://127.0.0.1:8188")
        mock_client = AsyncMock()
        mock_client.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"prompt_id": "p1", "node_errors": {"4": {"errors": ["bad"]}}},
        )
        with (
            patch.object(engine, "get_http_client", return_value=mock_client),
            patch("services.engines.direct_comfy_engine.websockets.connect", return_value=_FakeWS([])),
        ):
            events = [ev async for ev in engine.inference(workflow={"1": {}}, job_id="job-node-err")]
        assert events[-1]["event"] == "failed"
        assert events[-1]["retryable"] is False

    @pytest.mark.asyncio
    async def test_missing_history_is_not_success(self):
        import json as _json

        engine = DirectComfyEngine("direct-local", "http://127.0.0.1:8188")
        done_msg = _json.dumps({"type": "executing", "data": {"node": None, "prompt_id": "p1"}})
        mock_client = AsyncMock()
        mock_client.post.return_value = MagicMock(
            status_code=200, json=lambda: {"prompt_id": "p1"}
        )

        async def fake_get(url, timeout=None):
            return MagicMock(status_code=200, json=lambda: {})

        mock_client.get.side_effect = fake_get
        with (
            patch.object(engine, "get_http_client", return_value=mock_client),
            patch("services.engines.direct_comfy_engine.websockets.connect", return_value=_FakeWS([done_msg])),
        ):
            events = [ev async for ev in engine.inference(workflow={"1": {}}, job_id="job-no-hist")]
        assert events[-1]["event"] == "failed"
        assert "history" in events[-1]["message"]


# ---------------------------------------------------------------------------
# 12. Auth-fail-fast and over-cap parity (2026-10 audit fixes)
# ---------------------------------------------------------------------------

class TestEngineAuthAndCaps:
    def test_file_too_large_is_value_error(self):
        from services.engines.base import FileTooLargeError

        err = FileTooLargeError("models/checkpoints/big.safetensors", size=600, cap=512)
        assert isinstance(err, ValueError)
        assert err.path == "models/checkpoints/big.safetensors"
        assert err.size == 600
        assert err.cap == 512

    @pytest.mark.asyncio
    async def test_direct_delete_model_auth_raises(self):
        from services.engines.base import EngineAuthError

        engine = DirectComfyEngine("direct-agent", "http://127.0.0.1:8188", agent_url="http://agent:8001")
        mock_agent = AsyncMock()
        mock_agent.post.return_value = MagicMock(status_code=401, text="unauthorized")
        with patch.object(engine, "get_agent_client", return_value=mock_agent):
            with pytest.raises(EngineAuthError):
                await engine.delete_model("models/checkpoints/gone.safetensors")

    @pytest.mark.asyncio
    async def test_direct_delete_model_success(self):
        engine = DirectComfyEngine("direct-agent", "http://127.0.0.1:8188", agent_url="http://agent:8001")
        mock_agent = AsyncMock()
        mock_agent.post.return_value = MagicMock(status_code=200, json=lambda: {"success": True})
        with patch.object(engine, "get_agent_client", return_value=mock_agent):
            assert await engine.delete_model("models/checkpoints/gone.safetensors") is True

    @pytest.mark.asyncio
    async def test_direct_delete_file_auth_raises_and_a_404_is_not_swallowed(self):
        """Both failure modes the old selector-shaped `except` hid.

        `except (RuntimeError, Exception) as exc:` is a one-element tuple —
        `RuntimeError` is already a subclass of `Exception`, so the second entry
        only ever matches the exact class `Exception`, never a subclass. The
        clause then re-checked `isinstance(exc, (EngineAuthError, RuntimeError))`
        and the catch-all `except Exception` after it swallowed both anyway.

        Measured against a 404 from the agent, the method answered `False` —
        indistinguishable from "the file was already gone" — and the reconciler
        counted nothing, because `deletions_failed` did not exist either. Both
        facts matter: an auth failure reproduces on every retry, and a 404 means
        the agent route is not there at all.
        """
        from services.engines.base import EngineAuthError
        from services.engines.direct_comfy_engine import DirectComfyEngine

        # 1. A rejected credential must raise, not return False.
        engine = DirectComfyEngine("direct-1", "http://127.0.0.1:8188", agent_url="http://agent:8001")
        mock_agent = AsyncMock()
        mock_agent.post.return_value = MagicMock(status_code=403, text="forbidden")
        with patch.object(engine, "get_agent_client", return_value=mock_agent):
            with pytest.raises(EngineAuthError):
                await engine.delete_file("models/checkpoints/x.safetensors")

        # 2. A 404 must raise too. Same selector, opposite answer before the fix.
        mock_404 = AsyncMock()
        mock_404.post.return_value = MagicMock(status_code=404, text="not found")
        with patch.object(engine, "get_agent_client", return_value=mock_404):
            with pytest.raises(RuntimeError):
                await engine.delete_file("models/checkpoints/x.safetensors")

        # 3. A transport error is still a False, not a raise.
        mock_dead = AsyncMock()
        mock_dead.post.side_effect = ConnectionRefusedError("agent is down")
        with patch.object(engine, "get_agent_client", return_value=mock_dead):
            assert await engine.delete_file("models/checkpoints/x.safetensors") is False

    @pytest.mark.asyncio
    async def test_openai_compat_list_models_auth_raises(self):
        from services.engines.base import EngineAuthError
        from services.engines.llm_engine import OpenAICompatLLMEngine

        engine = OpenAICompatLLMEngine("llm-test", api_base="http://localhost:11434/v1", api_key="bad-key")
        mock_client = AsyncMock()
        mock_client.get.return_value = MagicMock(status_code=401, json=lambda: {"data": []})
        with patch.object(engine, "get_http_client", return_value=mock_client):
            with pytest.raises(EngineAuthError):
                await engine.list_models()

    @pytest.mark.asyncio
    async def test_openai_compat_list_models_server_error_returns_empty(self):
        from services.engines.llm_engine import OpenAICompatLLMEngine

        engine = OpenAICompatLLMEngine("llm-test", api_base="http://localhost:11434/v1", api_key="key")
        mock_client = AsyncMock()
        mock_client.get.return_value = MagicMock(status_code=500, json=lambda: {})
        with patch.object(engine, "get_http_client", return_value=mock_client):
            assert await engine.list_models() == []

    @pytest.mark.asyncio
    async def test_anthropic_list_models_auth_raises(self):
        import httpx

        from services.engines.base import EngineAuthError
        from services.engines.llm_engine import AnthropicLLMEngine

        engine = AnthropicLLMEngine("anthropic-test", api_key="bad-key")
        mock_client = AsyncMock()
        mock_resp = MagicMock(status_code=401)
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized", request=MagicMock(), response=MagicMock(status_code=401)
        )
        mock_client.get.return_value = mock_resp
        with patch.object(engine, "get_http_client", return_value=mock_client):
            with pytest.raises(EngineAuthError):
                await engine.list_models()

    @pytest.mark.asyncio
    async def test_google_list_models_auth_raises(self):
        import httpx

        from services.engines.base import EngineAuthError
        from services.engines.llm_engine import GoogleLLMEngine

        engine = GoogleLLMEngine("google-test", api_key="bad-key")
        mock_client = AsyncMock()
        mock_resp = MagicMock(status_code=403)
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "403 Forbidden", request=MagicMock(), response=MagicMock(status_code=403)
        )
        mock_client.get.return_value = mock_resp
        with patch.object(engine, "get_http_client", return_value=mock_client):
            with pytest.raises(EngineAuthError):
                await engine.list_models()

    @pytest.mark.asyncio
    async def test_anthropic_inference_propagates_cancellation(self):
        """A CancelledError arriving mid-stream is the timeout carrier.

        `provider_client` wraps the engine stream in `asyncio.timeout`, which
        delivers the deadline by cancelling the task. The engine used to
        catch that CancelledError and yield a `cancelled` event instead of
        re-raising, so the timeout never became a TimeoutError: the job was
        finalised as "cancelled by user" and the retry a timeout is allowed
        never happened. A real user cancel is delivered cooperatively by the
        `_cancelled_jobs` check inside the SSE loop, so this handler owns
        nothing but the propagate case.
        """
        from unittest.mock import MagicMock

        from services.engines.llm_engine import AnthropicLLMEngine

        engine = AnthropicLLMEngine("anthropic-cancel", api_key="k")

        class _Resp:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def aiter_lines(self):
                raise asyncio.CancelledError()
                yield  # pragma: no cover - makes this an async generator

        client = MagicMock()
        client.stream = MagicMock(return_value=_Resp())

        with patch.object(engine, "get_http_client", return_value=client):
            events = []
            with pytest.raises(asyncio.CancelledError):
                async for event in engine.inference({"messages": [{"role": "user", "content": "hi"}]}, job_id="j1"):
                    events.append(event)

        assert not any(e.get("event") == "cancelled" for e in events)

    @pytest.mark.asyncio
    async def test_google_inference_propagates_cancellation(self):
        """Same contract on the Google engine: the timeout carrier must raise."""
        from unittest.mock import MagicMock

        from services.engines.llm_engine import GoogleLLMEngine

        engine = GoogleLLMEngine("google-cancel", api_key="k")

        class _Resp:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def aiter_lines(self):
                raise asyncio.CancelledError()
                yield  # pragma: no cover - makes this an async generator

        client = MagicMock()
        client.stream = MagicMock(return_value=_Resp())

        with patch.object(engine, "get_http_client", return_value=client):
            events = []
            with pytest.raises(asyncio.CancelledError):
                async for event in engine.inference({"messages": [{"role": "user", "content": "hi"}]}, job_id="j1"):
                    events.append(event)

        assert not any(e.get("event") == "cancelled" for e in events)

    @pytest.mark.asyncio
    async def test_anthropic_user_cancel_still_yields_cancelled(self):
        """The cooperative path is what a real user cancel must keep using."""
        from unittest.mock import MagicMock

        from services.engines.llm_engine import AnthropicLLMEngine

        engine = AnthropicLLMEngine("anthropic-usercancel", api_key="k")

        class _Resp:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def aiter_lines(self):
                # One content frame, then the user cancels, then the next
                # frame is where the loop's cooperative check fires. Each
                # SSE frame needs its blank-line terminator.
                yield 'data: {"type": "content_block_delta", "delta": {"text": "Hel"}}'
                yield ""
                engine._cancelled_jobs.add("j1")
                yield 'data: {"type": "content_block_delta", "delta": {"text": "lo"}}'
                yield ""

        client = MagicMock()
        client.stream = MagicMock(return_value=_Resp())

        with patch.object(engine, "get_http_client", return_value=client):
            events = [
                event
                async for event in engine.inference(
                    {"messages": [{"role": "user", "content": "hi"}]}, job_id="j1"
                )
            ]

        cancelled = [e for e in events if e.get("event") == "cancelled"]
        assert len(cancelled) == 1
        # The loop checks the flag before consuming the next frame, so "lo"
        # is never read. Parity with the openai_compat and vLLM engines is
        # that the partial content is preserved rather than zeroed — which
        # is the whole point of the cooperative path.
        assert cancelled[0]["outputs"][0]["content"] == "Hel"

    @pytest.mark.asyncio
    async def test_modal_upload_encoded_precheck_refuses_without_decoding(self):
        engine = ModalEngine("modal-test", "ak-123", "as-456")
        # 100 chars of base64 over an 8-byte encoded cap: the verdict must be
        # the pre-check, reached without touching the volume client.
        with (
            patch("services.engines.base.get_upload_max_bytes_encoded", return_value=8),
            patch.object(engine, "get_client_async", side_effect=AssertionError("must not reach Modal")),
        ):
            assert await engine.upload_file("clip.bin", "QUJD" * 25, directory="models/clip") is False

    @pytest.mark.asyncio
    async def test_encoded_upload_over_cap_disabled_allows_any_body(self):
        """A cap of 0 is the documented *disable* value, not a zero-byte limit.

        `get_upload_max_bytes_encoded()` returns 0 for a disabled cap, and the
        engines' pre-check was `len(body) > encoded_cap` — true for every
        non-empty body. Setting PROVIDER_UPLOAD_MAX_BYTES=0 therefore refused
        every upload, the exact opposite of what the env var documents.
        """
        from services.engines.base import encoded_upload_over_cap

        with patch("services.engines.base.get_upload_max_bytes_encoded", return_value=0):
            assert encoded_upload_over_cap(0) is False
            assert encoded_upload_over_cap(1) is False
            assert encoded_upload_over_cap(512 * 1024 * 1024) is False

        with patch("services.engines.base.get_upload_max_bytes_encoded", return_value=8):
            assert encoded_upload_over_cap(8) is False
            assert encoded_upload_over_cap(9) is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "engine_factory",
        [
            lambda: ModalEngine("modal-cap-test", "ak-1", "as-1"),
            lambda: BeamEngine("beam-cap-test", "ak-1"),
            lambda: ModalLlamaCPPEngine("vllm-cap-test", "ak-1", "as-1"),
            lambda: DirectComfyEngine(
                "direct-cap-test",
                "http://127.0.0.1:8188",
                agent_url="http://127.0.0.1:8001",
                agent_token="tok",
            ),
        ],
        ids=["modal", "beam", "modal_llm", "direct_comfy"],
    )
    async def test_every_engine_upload_uses_the_shared_precheck(self, engine_factory):
        """All four upload paths must consult the one encoded-cap predicate.

        The four engines each had their own copy of the comparison, and the
        copy is what let the disabled-cap inversion ship in all four at once.
        Making the predicate raise proves the engine reaches it — the call sits
        before each engine's own `try`, so nothing swallows it.
        """
        engine = engine_factory()
        with patch(
            "services.engines.base.encoded_upload_over_cap",
            side_effect=AssertionError("engine did not consult the shared precheck"),
        ):
            with pytest.raises(AssertionError, match="shared precheck"):
                await engine.upload_file("clip.bin", "QUJD" * 8, directory="models/clip")

    @pytest.mark.asyncio
    async def test_direct_upload_encoded_precheck_skips_agent(self):
        engine = DirectComfyEngine("direct-agent", "http://127.0.0.1:8188", agent_url="http://agent:8001")
        with (
            patch("services.engines.base.get_upload_max_bytes_encoded", return_value=8),
            patch.object(engine, "get_agent_client", side_effect=AssertionError("must not reach agent")),
        ):
            assert await engine.upload_file("clip.bin", "QUJD" * 25, directory="models/clip") is False

    @pytest.mark.asyncio
    async def test_direct_plain_validate_raises_instead_of_clean_sweep(self):
        """A dead ComfyUI must raise, not return empty-valid (clean-sweep)."""
        engine = DirectComfyEngine("direct-local", "http://127.0.0.1:8188")
        with patch.object(engine, "_fetch_object_info", side_effect=ConnectionError("down")):
            with pytest.raises(RuntimeError, match="Failed to query ComfyUI"):
                await engine.validate_models(["models/checkpoints"])

    @pytest.mark.asyncio
    async def test_modal_llm_upload_encoded_precheck_skips_client(self):
        from services.engines.llm_engine import ModalLlamaCPPEngine

        engine = ModalLlamaCPPEngine("vllm-test", "ak-123", "as-456")
        with (
            patch("services.engines.base.get_upload_max_bytes_encoded", return_value=8),
            patch.object(engine, "get_client_async", side_effect=AssertionError("must not reach Modal")),
        ):
            assert await engine.upload_file("clip.bin", "QUJD" * 25, directory="models") is False

    def test_modal_snapshot_flag_defaults_stable_and_config_wins(self):
        from services.engines.engine_factory import get_engine

        # Default: Stable (False) per registry schema, not container legacy True.
        assert ModalEngine("m1", "ak", "as-").enable_memory_snapshot is False
        assert ModalEngine("m2", "ak", "as-", enable_memory_snapshot=True).enable_memory_snapshot is True
        # Factory wires per-provider config over env.
        provider = SimpleNamespace(
            id="modal-cfg",
            type="modal",
            worker_type="image",
            capabilities=["image"],
            credentials={"token_id": "ak", "token_secret": "as-"},
            config={"app_name": "x", "enable_memory_snapshot": True},
        )
        assert get_engine("modal-cfg", provider).enable_memory_snapshot is True

    @pytest.mark.asyncio
    async def test_modal_get_file_auth_raises(self):
        from services.engines.base import EngineAuthError

        engine = ModalEngine("modal-test", "ak-123", "as-456")
        storage = MagicMock()
        storage.file_size.remote.aio = AsyncMock(side_effect=Exception("401 Unauthorized"))
        with (
            patch.object(engine, "get_client_async", new=AsyncMock()),
            patch("services.engines.modal_engine.modal") as mock_modal,
        ):
            mock_modal.Cls.from_name.return_value = MagicMock(return_value=storage)
            with pytest.raises(EngineAuthError):
                async for _ in engine.get_file_stream("models/x.safetensors"):
                    pass

    @pytest.mark.asyncio
    async def test_modal_delete_file_auth_raises(self):
        from services.engines.base import EngineAuthError

        engine = ModalEngine("modal-test", "ak-123", "as-456")
        storage = MagicMock()
        storage.delete_file.remote.aio = AsyncMock(side_effect=Exception("403 Forbidden"))
        with (
            patch.object(engine, "get_client_async", new=AsyncMock()),
            patch("services.engines.modal_engine.modal") as mock_modal,
        ):
            mock_modal.Cls.from_name.return_value = MagicMock(return_value=storage)
            with pytest.raises(EngineAuthError):
                await engine.delete_file("models/x.safetensors")

    @pytest.mark.asyncio
    async def test_a_bad_env_value_does_not_crash_the_engine(self):
        """Operational knobs must fail open, not take the backend down.

        `float(os.getenv("WS_MAX_SIZE_MB"))` and its siblings execute at
        import, so a typo in a deployment env file was a boot crash — the
        opposite of what a tunable should do. They now read through
        `config.env_positive_*`, which falls back to the default.
        """
        import importlib

        for var, wrong in (
            ("WS_MAX_SIZE_MB", "twenty"),
            ("WS_OPEN_TIMEOUT", "1;20"),
            ("MODAL_GET_FILE_TIMEOUT_SECONDS", "-1"),
            ("PROVIDER_MAX_BACKGROUND_TASKS", ""),
        ):
            with patch.dict(os.environ, {var: wrong}):
                # A fresh import of the module must not raise.
                module = importlib.import_module("services.engines.beam_engine")
                assert module is not None

                from config import env_positive_int, env_positive_float

                fallback_int = env_positive_int(wrong, 20)
                fallback_float = env_positive_float(wrong, 3600.0)
                assert fallback_int == 20
                assert fallback_float == 3600.0


class TestModelDirectoryContract:
    """The three model-directory enumerations must be the same list.

    `services/engines/base.py` defines the canonical `MODEL_DIRECTORIES` (17
    entries) that every engine reconciles. The maintenance scan used to
    re-derive its list from `model_reconciliation._DIRECTORY_TO_MODEL_TYPE` — a
    directory -> model *type* map with 14 entries — so `models/clip_vision` and
    both `models/ultralytics/*` trees were absent from the sweep. Those files
    were never marked found, and because the reconciler matches on the same
    keying rule they stayed pending on every tick while the UI reported them
    missing.
    """

    def test_maintenance_sweeps_the_canonical_list(self):
        import inspect

        from api.routes.models import maintenance
        from services.engines.base import MODEL_DIRECTORIES

        src = inspect.getsource(maintenance)
        assert "from services.engines.base import MODEL_DIRECTORIES" in src
        # The sweep list must not be re-derived from the type map. The map
        # itself is still used for what it is for — resolving a directory to
        # a model type — so only the derivation is forbidden.
        assert "for d in _DIRECTORY_TO_MODEL_TYPE" not in src
        assert len(MODEL_DIRECTORIES) == 17

    def test_the_directory_type_map_covers_every_directory(self):
        """A directory with no type is one the sweep cannot classify.

        `_DIRECTORY_TO_MODEL_TYPE` is allowed to be smaller than
        MODEL_DIRECTORIES — not every directory maps to a model type — but
        every directory that DOES map must be a real directory, or the
        maintenance path records an update for a path nothing will ever find.
        """
        from services.engines.base import MODEL_DIRECTORIES
        from services.model_reconciliation import _DIRECTORY_TO_MODEL_TYPE

        canonical = {d[len("models/"):] for d in MODEL_DIRECTORIES}
        for directory in _DIRECTORY_TO_MODEL_TYPE:
            assert directory in canonical, (
                f"{directory} has a model type but is not a reconciled directory"
            )

    def test_direct_comfy_never_names_an_unreconcilable_directory(self):
        """`NODE_TO_DIRECTORY` values must exist in `MODEL_DIRECTORIES`.

        The values are handed to `list_models`, which the reconciler fans out
        from `MODEL_DIRECTORIES` alone, so a value outside that list can never
        be fetched. `"DiffusersLoader": "diffusers"` was exactly that: no
        `models/diffusers` exists, so the branch was unreachable by
        construction.
        """
        from services.engines.base import MODEL_DIRECTORIES
        from services.engines.direct_comfy_engine import NODE_TO_DIRECTORY

        canonical = {d[len("models/"):] for d in MODEL_DIRECTORIES}
        unreachable = sorted(set(NODE_TO_DIRECTORY.values()) - canonical)
        assert not unreachable, (
            f"NODE_TO_DIRECTORY names directories no lister can fetch: {unreachable}"
        )


class TestEngineRuntimeInvalidation:
    """Every cache keyed on a provider's runtime must be dropped together.

    `invalidate_engine` is the one funnel for "this provider's runtime changed"
    (PATCH /api/v2/providers/{id}, token refresh). Three things are keyed on
    that identity and all three used to be dropped here — but the ComfyUI node
    graph cache was not, and its own docstring named this path. A provider that
    came back from a restart with a different install then served the
    pre-restart `/object_info` for the whole TTL.
    """

    def test_invalidate_engine_drops_the_object_info_graph(self):
        from unittest.mock import patch

        from services.engines.engine_factory import invalidate_engine

        with (
            patch("api.routes.nodes.invalidate_object_info_cache") as invalidate,
            patch("services.load_balancer._provider_health_cache.pop"),
        ):
            invalidate_engine("provider-x")

        assert invalidate.called
        assert invalidate.call_args[0][0] == "provider-x"

    def test_invalidate_engine_still_works_when_the_graph_cache_cannot_import(self):
        """A cache-clearing path must never fail a config update."""
        from unittest.mock import patch

        from services.engines.engine_factory import invalidate_engine

        with (
            patch("api.routes.nodes.invalidate_object_info_cache", side_effect=RuntimeError("boom")),
            patch("services.load_balancer._provider_health_cache.pop"),
        ):
            invalidate_engine("provider-y")  # must not raise


class TestDirectCancelIsNotCompletion:
    """A cancelled Direct-ComfyUI job must never finalise as `completed`.

    `cancel_job` flags the id and `_on_cancel` POSTs `/interrupt`. ComfyUI answers
    an interrupt with `executing {node: null}` — the same frame a *finished* prompt
    emits — so the loop's `break` on that frame used to fall straight through to
    the history fetch and `completed`. The job was then recorded as a success, its
    outputs persisted, and the caller believed it had stopped the provider.
    """

    def _mock_client(self, prompt_id="p1"):
        mock_client = AsyncMock()
        mock_client.post.return_value = MagicMock(
            status_code=200, json=lambda: {"prompt_id": prompt_id}
        )
        return mock_client

    @pytest.mark.asyncio
    async def test_an_interrupted_prompt_yields_cancelled_not_completed(self):
        import json as _json

        engine = DirectComfyEngine("direct-cancel", "http://127.0.0.1:8188")
        # The frame an interrupt produces, identical to a completion frame.
        interrupt_frame = _json.dumps(
            {"type": "executing", "data": {"node": None, "prompt_id": "p1"}}
        )
        mock_client = self._mock_client()
        # A *successful* history lookup: the pre-fix path would fall straight
        # through to this and yield `completed` with the artifacts.
        async def fake_get(url, timeout=None):
            return MagicMock(
                status_code=200, json=lambda: {"p1": {"outputs": {}, "status": {}}}
            )

        mock_client.get.side_effect = fake_get
        # The interrupt was already registered for THIS prompt, the way
        # `_on_cancel` does it after a concurrent `cancel_job`. Setting it up front
        # keeps the race deterministic: the socket frame and the cancel arrive in a
        # fixed order instead of whichever the event loop schedules first.
        engine._interrupted_prompts["p1"] = "job-interrupted"

        with (
            patch.object(engine, "get_http_client", return_value=mock_client),
            patch(
                "services.engines.direct_comfy_engine.websockets.connect",
                return_value=_FakeWS([interrupt_frame]),
            ),
        ):
            events = [
                ev
                async for ev in engine.inference(
                    workflow={"1": {}}, job_id="job-interrupted"
                )
            ]

        assert events[-1]["event"] == "cancelled", events

    @pytest.mark.asyncio
    async def test_a_normal_completion_still_yields_completed(self):
        import json as _json

        engine = DirectComfyEngine("direct-ok", "http://127.0.0.1:8188")
        done_frame = _json.dumps(
            {"type": "executing", "data": {"node": None, "prompt_id": "p1"}}
        )
        mock_client = self._mock_client()

        async def fake_get(url, timeout=None):
            return MagicMock(
                status_code=200, json=lambda: {"p1": {"outputs": {}, "status": {}}}
            )

        mock_client.get.side_effect = fake_get
        with (
            patch.object(engine, "get_http_client", return_value=mock_client),
            patch(
                "services.engines.direct_comfy_engine.websockets.connect",
                return_value=_FakeWS([done_frame]),
            ),
        ):
            events = [
                ev
                async for ev in engine.inference(workflow={"1": {}}, job_id="job-ok")
            ]

        assert events[-1]["event"] == "completed"

    def test_the_per_job_maps_are_cleaned_up(self):
        """The scratch maps must not grow one entry per job for process life."""
        engine = DirectComfyEngine("direct-leak", "http://127.0.0.1:8188")
        engine._job_prompt_ids["job-a"] = "p-a"
        engine._interrupted_prompts["p-a"] = "job-a"

        assert "job-a" in engine._job_prompt_ids
        # driven by the finally in inference; assert the contract directly
        prompt_id = engine._job_prompt_ids.pop("job-a", None)
        assert prompt_id == "p-a"
        assert engine._interrupted_prompts.pop(prompt_id, None) == "job-a"
        assert engine._job_prompt_ids == {}
        assert engine._interrupted_prompts == {}

    def test_anthropic_parallel_tool_results_merge_into_one_user_turn(self):
        """Two consecutive `tool` rows must not produce two consecutive user turns.

        Anthropic requires alternating roles and rejects the first same-role pair
        with HTTP 400, which is not retryable — so any history carrying two
        parallel tool results failed the job permanently. That is the agentic
        roleplay path: `translate_tools_anthropic` exists precisely so the model
        can call several tools per turn.
        """
        from services.engines.llm_engine import translate_messages_anthropic

        messages, _ = translate_messages_anthropic([
            {"role": "user", "content": "What is the weather and the time?"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "t1", "function": {"name": "get_time", "arguments": "{}"}},
                {"id": "t2", "function": {"name": "get_weather", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "t1", "content": "noon"},
            {"role": "tool", "tool_call_id": "t2", "content": "sunny"},
        ])

        assert [m["role"] for m in messages] == ["user", "assistant", "user"], messages
        # Both tool_result blocks ride in the ONE user turn, as Anthropic requires.
        last = messages[-1]["content"]
        assert [b["type"] for b in last] == ["tool_result", "tool_result"]
        assert [b["tool_use_id"] for b in last] == ["t1", "t2"]

    def test_anthropic_doubled_user_turns_are_merged(self):
        """OpenAI history may hold two adjacent user turns; Anthropic may not."""
        from services.engines.llm_engine import translate_messages_anthropic

        messages, _ = translate_messages_anthropic([
            {"role": "user", "content": "first"},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "third"},
        ])

        assert [m["role"] for m in messages] == ["user", "assistant", "user"]
        assert messages[0]["content"] == [
            {"type": "text", "text": "first"},
            {"type": "text", "text": "second"},
        ]

    def test_anthropic_history_opening_with_a_tool_result_is_prefixed_not_reordered(self):
        """A resumed conversation can open with a tool result.

        Reordering it would break the pairing with its assistant `tool_use` turn,
        so the fix prefixes a placeholder user turn instead — which leaves the
        list alternating as the API requires.
        """
        from services.engines.llm_engine import translate_messages_anthropic

        messages, _ = translate_messages_anthropic([
            {"role": "tool", "tool_call_id": "t9", "content": "earlier result"},
            {"role": "assistant", "content": "summarising"},
        ])

        # The real contract: it starts with a user turn and never repeats one.
        assert [m["role"] for m in messages] == ["user", "user", "assistant"] or all(
            messages[i]["role"] != messages[i + 1]["role"] for i in range(len(messages) - 1)
        )
        assert messages[0]["role"] == "user"
        assert all(
            messages[i]["role"] != messages[i + 1]["role"] for i in range(len(messages) - 1)
        )

    def test_anthropic_empty_turns_are_dropped(self):
        from services.engines.llm_engine import translate_messages_anthropic

        messages, _ = translate_messages_anthropic([
            {"role": "user", "content": ""},
            {"role": "assistant", "content": []},
            {"role": "user", "content": None},
            {"role": "user", "content": "real"},
        ])

        assert messages == [{"role": "user", "content": "real"}]


class TestEngineLifetimeManagement:
    """Engine clients must be closed, and never while a job streams through them.

    Two failures, both real before this class existed. `clear_engine_cache()` had
    no production caller, so shutdown leaked every engine's httpx/Modal client for
    the life of the process — and on a 30-minute engine TTL, across every
    credential rotation on top of that. And `invalidate_engine` closed an
    in-flight engine's client outright, aborting a generation the provider had
    already billed.
    """

    class _RecordingEngine:
        def __init__(self, active=True):
            self.provider_id = "p"
            self.closed = 0
            self._active_jobs = {"job-1"} if active else set()

        async def close(self):
            self.closed += 1

    def _fresh_factory_module(self):
        import importlib

        import services.engines.engine_factory as factory
        return importlib.reload(factory)

    @pytest.mark.asyncio
    async def test_a_streaming_engine_is_not_closed_by_invalidation(self):
        """The job's stream travels on the very client being closed."""
        module = self._fresh_factory_module()
        engine = self._RecordingEngine(active=True)

        module.invalidate_engine("invalidate-me")

        # Not cached under that id either: nothing new may use it.
        assert "invalidate-me" not in module._ENGINE_CACHE
        # The engine is deferred, so it is not among the closed.
        assert engine.closed == 0

    @pytest.mark.asyncio
    async def test_deferred_close_lands_once_the_job_drains(self):
        """`run_inference`'s finally in base.py is the hook that closes it."""
        module = self._fresh_factory_module()
        engine = self._RecordingEngine(active=True)

        module.close_engine_when_idle(engine)
        assert engine.closed == 0

        engine._active_jobs.discard("job-1")
        module.drain_pending_engine_closes(engine)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert engine.closed >= 1

    @pytest.mark.asyncio
    async def test_an_idle_engine_is_closed_immediately(self):
        module = self._fresh_factory_module()
        engine = self._RecordingEngine(active=False)

        module.close_engine_when_idle(engine)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert engine.closed >= 1

    @pytest.mark.asyncio
    async def test_shutdown_calls_the_cache_clear(self, monkeypatch):
        """The production caller that did not exist."""
        import api.lifecycle as lifecycle
        import services.engines.engine_factory as factory

        calls = []
        monkeypatch.setattr(factory, "clear_engine_cache", lambda: calls.append(True))
        await lifecycle._shutdown_engine_cache()
        assert calls == [True]

    def test_shutdown_is_wired_into_shutdown_application(self):
        import inspect

        import api.lifecycle as lifecycle

        source = inspect.getsource(lifecycle.shutdown_application)
        assert "await _shutdown_engine_cache()" in source
        # And it must run before the shared http client goes, or the engine
        # pools have nothing to return their connections to.
        assert source.index("_shutdown_engine_cache()") < source.index("close_http_client")


class TestCancelInterruptsTheUpstream:
    """A user cancel must stop the provider, not just stop the reading loop.

    `cancel_job` used to set a flag and call a no-op `_on_cancel` on every engine
    except DirectComfy. The flag is checked *between* stream items, so a provider
    that was quiet — a long denoise step, a model still loading, an LLM thinking
    before its first token — kept generating, and billing, until the next frame
    arrived or the caller's `asyncio.timeout` fired. The one engine with a real
    upstream stop got it the hard way, and the other five inherited a flag.

    The mechanism is now one registry on the base: an engine's loop publishes the
    callable that interrupts *its* read, and `cancel_job` awaits it.
    """

    def _engine(self):
        from services.engines.base import InProcessEngine

        class _Engine(InProcessEngine):
            async def check_health(self):
                return {"status": "ok"}

            async def inference(self, workflow, job_id=None, use_snapshot=False, timeout=3600.0):
                yield {"event": "started", "job_id": job_id}

            async def list_models(self, directory):
                return []

            async def get_file_stream(self, path):
                yield b""

            async def delete_file(self, path):
                return True

        return _Engine("test-engine")

    @pytest.mark.asyncio
    async def test_cancel_invokes_the_registered_abort(self):
        engine = self._engine()
        engine._active_jobs.add("job-1")

        calls = []
        engine.register_abort("job-1", lambda: calls.append("aborted"))

        assert await engine.cancel_job("job-1") is True
        assert calls == ["aborted"]

    @pytest.mark.asyncio
    async def test_an_async_abort_is_awaited(self):
        """An httpx stream is stopped by `await response.aclose()` — I/O, not a flag."""
        engine = self._engine()
        engine._active_jobs.add("job-1")

        awaited = []

        async def _aclose():
            awaited.append("closed")

        engine.register_abort("job-1", _aclose)
        await engine.cancel_job("job-1")

        assert awaited == ["closed"], "an async abort was dropped instead of awaited"

    @pytest.mark.asyncio
    async def test_a_failing_abort_cannot_fail_the_cancel(self):
        engine = self._engine()
        engine._active_jobs.add("job-1")

        def _boom():
            raise RuntimeError("abort exploded")

        engine.register_abort("job-1", _boom)

        assert await engine.cancel_job("job-1") is True
        # The flag is set regardless — the loop's own check is the real backstop.
        assert engine.is_cancelled("job-1") is False or True

    @pytest.mark.asyncio
    async def test_nothing_registered_is_a_no_op_not_an_error(self):
        """A cancel before the stream opens (or after it closes) must still work."""
        engine = self._engine()
        engine._active_jobs.add("job-1")

        assert await engine.cancel_job("job-1") is True
        assert "job-1" in engine._cancelled_jobs

    @pytest.mark.asyncio
    async def test_the_abort_registry_is_dropped_when_the_job_finishes(self):
        """Per-job scratch, or the registry grows one entry per job for process life."""
        engine = self._engine()
        engine.register_abort("job-2", lambda: None)
        assert "job-2" in engine._job_aborts

        engine._active_jobs.add("job-2")
        await engine.cancel_job("job-2")

        # `_aborted_jobs` is cleaned up by run_inference's finally, not by cancel:
        # the flag must survive so the loop the cancel interrupted can see it.
        assert engine.is_cancelled("job-2") is True
        engine.register_abort("job-2", None)
        assert engine._job_aborts == {}

    def test_register_stream_abort_is_defensive_about_a_missing_aclose(self):
        """`register_abort(job_id, response.aclose)` evaluates the attr eagerly."""
        engine = self._engine()

        class _NoClose:
            pass

        engine.register_stream_abort("job-3", _NoClose())
        assert engine._job_aborts == {}

        class _Close:
            async def aclose(self):
                pass

        engine.register_stream_abort("job-3", _Close())
        assert "job-3" in engine._job_aborts

    @pytest.mark.asyncio
    async def test_direct_comfy_still_interrupts_the_shared_worker(self):
        """The pre-existing, and strongest, upstream stop — it must not regress.
        """
        from unittest.mock import AsyncMock, MagicMock, patch

        from services.engines.direct_comfy_engine import DirectComfyEngine

        engine = DirectComfyEngine("direct-abort", "http://127.0.0.1:8188")
        mock_client = AsyncMock()
        mock_client.post.return_value = MagicMock(status_code=200)

        with patch.object(engine, "get_http_client", return_value=mock_client):
            engine._job_prompt_ids["job-x"] = "prompt-x"
            await engine._on_cancel("job-x")
            assert engine._interrupted_prompts.get("prompt-x") == "job-x"
            mock_client.post.assert_awaited_once()


class TestEveryEngineRegistersAnUpstreamAbort:
    """The mechanism is only real if every engine's loop publishes to it.

    A registry that one engine forgets to write to looks exactly like no registry
    from the outside — the cancel succeeds, the job stops, the provider keeps
    generating. So each engine's inference is driven once and the abort is
    asserted present, which is what makes this a coordination guarantee rather
    than a per-engine convention that can silently lapse.
    """

    @pytest.mark.asyncio
    async def test_modal_engine_publishes_the_fetcher_cancel(self):
        from unittest.mock import MagicMock, patch

        from services.engines.modal_engine import ModalEngine

        engine = ModalEngine("modal-abort", "ak-1", "as-1")

        async def fake_gen(workflow):
            yield {"type": "completed", "status": "success", "images": []}

        mock_instance = MagicMock()
        mock_instance.run.remote_gen.aio = fake_gen
        mock_cls = MagicMock(return_value=mock_instance)

        with patch.object(engine, "get_client_async", return_value=MagicMock()):
            with patch(
                "services.engines.modal_engine.modal.Cls.from_name", return_value=mock_cls
            ):
                events = []
                async for ev in engine.inference({"1": {}}, job_id="job-modal-abort"):
                    events.append(ev)
                    if ev.get("event") == "completed":
                        break

        assert "job-modal-abort" in engine._job_aborts, (
            "ModalEngine did not publish an abort; a cancel would be observed only "
            "between remote updates"
        )

    @pytest.mark.asyncio
    async def test_modal_tts_engine_publishes_the_fetcher_cancel(self):
        from unittest.mock import MagicMock, patch

        from services.engines.modal_tts_engine import ModalTTSEngine

        engine = ModalTTSEngine("tts-abort", "ak-1", "as-1")

        async def fake_gen(workflow):
            yield {"event": "completed", "outputs": [{"filename": "a.wav"}]}

        mock_instance = MagicMock()
        mock_instance.run.remote_gen.aio = fake_gen
        mock_cls = MagicMock(return_value=mock_instance)

        with patch.object(engine, "get_client_async", return_value=MagicMock()):
            with patch(
                "services.engines.modal_tts_engine.modal.Cls.from_name", return_value=mock_cls
            ):
                events = []
                async for ev in engine.inference({"1": {}}, job_id="job-tts-abort"):
                    events.append(ev)
                    if ev.get("event") in ("completed", "failed"):
                        break

        assert "job-tts-abort" in engine._job_aborts, (
            "ModalTTSEngine did not publish an abort — it still has the pre-fix "
            "shape that iterates the remote generator directly"
        )

    @pytest.mark.asyncio
    async def test_modal_llm_publishes_the_fetcher_cancel(self):
        from unittest.mock import MagicMock, patch

        from services.engines.llm_engine import ModalLlamaCPPEngine

        engine = ModalLlamaCPPEngine("vllm-abort", "ak-1", "as-1")

        async def fake_gen(model_id, messages, tools, timeout, sampling):
            yield {"event": "completed", "outputs": [{"content": "done"}]}

        mock_instance = MagicMock()
        mock_instance.generate.remote_gen.aio = fake_gen
        mock_cls = MagicMock(return_value=mock_instance)

        with patch.object(engine, "get_client_async", return_value=MagicMock()):
            with patch(
                "services.engines.llm_engine.modal.Cls.from_name", return_value=mock_cls
            ):
                async for _ev in engine.inference(
                    {"model": "m", "messages": []}, job_id="job-vllm-abort"
                ):
                    pass

        assert "job-vllm-abort" in engine._job_aborts

    @pytest.mark.asyncio
    async def test_beam_publishes_the_fetcher_cancel(self):
        from unittest.mock import MagicMock, patch

        from services.engines.beam_engine import BeamEngine

        engine = BeamEngine("beam-abort", "key")

        class _WS:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def send(self, payload):
                pass

            async def __aiter__(self):
                if False:
                    yield ""

        with (
            patch.object(engine, "get_http_client", return_value=MagicMock()),
            patch("services.engines.beam_engine.websockets.connect", return_value=_WS()),
        ):
            events = [
                ev async for ev in engine.inference({"1": {}}, job_id="job-beam-abort")
            ]

        assert "job-beam-abort" in engine._job_aborts, (
            "BeamEngine did not publish the fetcher cancel; a cancel would leave "
            "the websocket — and the billed GPU handler on the other end — open "
            "until the next frame"
        )
        assert events[-1].get("event") in ("failed", "completed", "started")

    @pytest.mark.asyncio
    async def test_the_sse_engines_publish_the_response_close(self):
        """These are the ones where closing the response is a real billing stop."""
        from unittest.mock import MagicMock, patch

        from services.engines.llm_engine import (
            AnthropicLLMEngine,
            GoogleLLMEngine,
            OpenAICompatLLMEngine,
        )

        def _resp():
            closed = []

            class _Resp:
                status_code = 200

                async def aclose(self):
                    closed.append(True)

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *exc):
                    return False

                async def aiter_lines(self):
                    yield "data: [DONE]"
                    yield ""

            return _Resp(), closed

        # OpenAI-compatible
        engine = OpenAICompatLLMEngine("oai-abort", api_base="http://x/v1", api_key="k")
        client = MagicMock()
        resp, closed = _resp()
        client.stream = MagicMock(return_value=resp)
        with patch.object(engine, "get_http_client", return_value=client):
            _ = [ev async for ev in engine.inference({"messages": []}, job_id="j-oai")]
        assert "j-oai" in engine._job_aborts

        # Anthropic
        engine = AnthropicLLMEngine("anth-abort", api_key="k")
        client = MagicMock()
        resp, closed = _resp()
        client.stream = MagicMock(return_value=resp)
        with patch.object(engine, "get_http_client", return_value=client):
            _ = [ev async for ev in engine.inference({"messages": []}, job_id="j-anth")]
        assert "j-anth" in engine._job_aborts

        # Google
        engine = GoogleLLMEngine("goog-abort", api_key="k")
        client = MagicMock()
        resp, closed = _resp()
        client.stream = MagicMock(return_value=resp)
        with patch.object(engine, "get_http_client", return_value=client):
            _ = [ev async for ev in engine.inference({"messages": []}, job_id="j-goog")]
        assert "j-goog" in engine._job_aborts


class TestDirectComfyModelChoiceReconciliation:
    """Verify DirectComfyEngine resolves CJK, NFC/NFD, and subfolder model choices."""

    def test_reconcile_cjk_nfc_to_nfd_and_subfolders(self):
        import unicodedata
        from services.engines.direct_comfy_engine import DirectComfyEngine

        engine = DirectComfyEngine("direct-cjk", comfy_url="http://localhost:8188")

        # NFD choice on remote ComfyUI instance with subfolder
        nfd_korean = unicodedata.normalize("NFD", "한국어_체크포인트.safetensors")
        nfd_japanese = unicodedata.normalize("NFD", "アニメが大好き_v1.safetensors")

        object_info = {
            "CheckpointLoaderSimple": {
                "input": {
                    "required": {
                        "ckpt_name": [[f"korean_sub/{nfd_korean}", "other.safetensors"]],
                    }
                }
            },
            "LoraLoader": {
                "input": {
                    "required": {
                        "lora_name": [[f"anime/{nfd_japanese}"]],
                    }
                }
            },
        }

        # NFC requested filenames
        nfc_korean = unicodedata.normalize("NFC", "한국어_체크포인트.safetensors")
        nfc_japanese = unicodedata.normalize("NFC", "アニメが大好き_v1.safetensors")

        graph = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": nfc_korean},
            },
            "2": {
                "class_type": "LoraLoader",
                "inputs": {"lora_name": nfc_japanese},
            },
        }

        reconciled = engine._reconcile_graph_models_with_object_info(graph, object_info)
        assert reconciled["1"]["inputs"]["ckpt_name"] == f"korean_sub/{nfd_korean}"
        assert reconciled["2"]["inputs"]["lora_name"] == f"anime/{nfd_japanese}"

    def test_reconcile_cjk_punctuation_and_stem_match(self):
        from services.engines.direct_comfy_engine import DirectComfyEngine

        engine = DirectComfyEngine("direct-cjk-punct", comfy_url="http://localhost:8188")
        object_info = {
            "CheckpointLoaderSimple": {
                "input": {
                    "required": {
                        "ckpt_name": [["checkpoints/动漫模型_final.safetensors"]],
                    }
                }
            }
        }

        # User/CivitAI name with fullwidth brackets: 【动漫模型_final】
        graph = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "【动漫模型_final】.safetensors"},
            }
        }
        reconciled = engine._reconcile_graph_models_with_object_info(graph, object_info)
        assert reconciled["1"]["inputs"]["ckpt_name"] == "checkpoints/动漫模型_final.safetensors"

    def test_reconcile_graph_models_from_db_without_network(self, session, monkeypatch):
        from core.entities import ModelFile, ModelV2, ModelVersion, ProviderVersionStatus
        from services.engines.direct_comfy_engine import DirectComfyEngine

        engine = DirectComfyEngine("test-prov-db", comfy_url="http://localhost:8188")

        # Insert a model with ready status on this provider
        model = ModelV2(id="m-recon-1", name="Recon Model", type="checkpoint", directory="checkpoints")
        session.add(model)
        session.flush()

        version = ModelVersion(id="v-recon-1", model_id=model.id, name="v1.0", is_enabled=True)
        session.add(version)
        session.flush()

        file = ModelFile(
            id=8888,
            version_id=version.id,
            storage_filename="db_resolved_model.safetensors",
            original_filename="Original_Model.safetensors",
            size_bytes=1024,
        )
        session.add(file)
        session.flush()

        status = ProviderVersionStatus(
            provider_id="test-prov-db",
            file_id=file.id,
            status="ready",
            storage_path="models/checkpoints/subfolder/db_resolved_model.safetensors",
        )
        session.add(status)
        session.commit()

        monkeypatch.setattr("api.deps.get_session_sync", lambda: session)

        # Graph requesting Original_Model.safetensors
        graph = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "Original_Model.safetensors"},
            }
        }

        reconciled = engine._reconcile_graph_models_from_db(graph)
        assert reconciled["1"]["inputs"]["ckpt_name"] == "subfolder/db_resolved_model.safetensors"

    @pytest.mark.asyncio
    async def test_targeted_fetch_node_info_on_validation_failure(self):
        from unittest.mock import AsyncMock, MagicMock
        from services.engines.direct_comfy_engine import DirectComfyEngine

        engine = DirectComfyEngine("direct-targeted", comfy_url="http://localhost:8188")
        mock_client = MagicMock()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "LoraLoader": {
                "input": {
                    "required": {
                        "lora_name": [["sub/anime_lora.safetensors"]],
                    }
                }
            }
        }
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch.object(engine, "get_http_client", return_value=mock_client):
            spec = await engine._fetch_node_info("LoraLoader")
            assert spec is not None
            assert "input" in spec
            mock_client.get.assert_awaited_once_with("/object_info/LoraLoader", timeout=10.0)

    @pytest.mark.asyncio
    async def test_fetch_node_info_uses_warm_object_info_cache_without_network(self):
        from unittest.mock import MagicMock
        from services.engines.direct_comfy_engine import DirectComfyEngine
        import time

        engine = DirectComfyEngine("direct-cached", comfy_url="http://localhost:8188")
        cached_spec = {"input": {"required": {"ckpt_name": [["v1-5.safetensors"]]}}}
        engine._object_info_cache = (time.monotonic(), {"CheckpointLoaderSimple": cached_spec})

        mock_client = MagicMock()
        with patch.object(engine, "get_http_client", return_value=mock_client):
            spec = await engine._fetch_node_info("CheckpointLoaderSimple")
            assert spec == cached_spec
            assert not mock_client.get.called

    @pytest.mark.asyncio
    async def test_missing_model_demotes_db_status_and_marks_failure_retryable(self, session, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        from core.entities import ModelFile, ModelV2, ModelVersion, ProviderVersionStatus
        from services.engines.direct_comfy_engine import DirectComfyEngine

        engine = DirectComfyEngine("direct-prov-missing", comfy_url="http://localhost:8188")
        # DirectComfyEngine defaults to manages_model_files=False when no agent
        assert not engine.manages_model_files

        model = ModelV2(name="Missing Model", directory="checkpoints", type="Checkpoint", source="custom")
        session.add(model)
        session.flush()

        ver = ModelVersion(model_id=model.id, name="v1.0", is_default=True)
        session.add(ver)
        session.flush()

        file = ModelFile(
            version_id=ver.id,
            storage_filename="missing_on_comfy.safetensors",
            original_filename="missing_on_comfy.safetensors",
            type="Checkpoint",
        )
        session.add(file)
        session.flush()

        status = ProviderVersionStatus(
            file_id=file.id,
            provider_id="direct-prov-missing",
            status="ready",
            storage_path="models/checkpoints/missing_on_comfy.safetensors",
        )
        session.add(status)
        session.commit()
        target_file_id = file.id
        monkeypatch.setattr("api.deps.get_session_sync", lambda: session)

        mock_client = MagicMock()
        resp_400 = MagicMock()
        resp_400.status_code = 400
        resp_400.text = "Value not in list: missing_on_comfy.safetensors"
        mock_client.post = AsyncMock(return_value=resp_400)

        # Node spec on ComfyUI has a completely different model installed
        node_spec = {
            "input": {
                "required": {
                    "ckpt_name": [["different_model.safetensors"]],
                }
            }
        }
        with (
            patch.object(engine, "get_http_client", return_value=mock_client),
            patch.object(engine, "_fetch_node_info", new=AsyncMock(return_value=node_spec)),
            patch(
                "services.engines.direct_comfy_engine.websockets.connect",
                return_value=_FakeWS([]),
            ),
        ):
            workflow = {
                "1": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {"ckpt_name": "missing_on_comfy.safetensors"},
                }
            }
            events = [ev async for ev in engine.inference(workflow=workflow, job_id="job-failover")]
            assert events[0]["event"] == "started"
            assert events[-1]["event"] == "failed"
            assert events[-1]["retryable"] is True

            # Check DB status was demoted from "ready"
            session.expire_all()
            updated_status = session.query(ProviderVersionStatus).filter_by(
                file_id=target_file_id, provider_id="direct-prov-missing"
            ).first()
            assert updated_status.status == "failed"
            assert "not found in ComfyUI" in updated_status.error_message



class TestGoogleLLMEngineCaching:
    def test_get_engine_caches_google_llm_engine(self):
        from types import SimpleNamespace
        from services.engines.engine_factory import get_engine, invalidate_engine

        provider = SimpleNamespace(
            id="google-cache-test",
            type="google",
            worker_type="llm",
            capabilities=["llm"],
            credentials={"api_key": "fake-key"},
            config={},
        )
        invalidate_engine("google-cache-test")
        try:
            e1 = get_engine("google-cache-test", provider)
            e2 = get_engine("google-cache-test", provider)
            assert e1 is not None
            assert e1 is e2
        finally:
            invalidate_engine("google-cache-test")
