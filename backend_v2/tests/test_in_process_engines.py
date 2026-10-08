"""
Tests for In-Process Compute Engines and Integration.

Validates ModalEngine, DirectComfyEngine, EngineFactory, runtime resolution,
load balancing rotation, and end-to-end execution.
"""

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.entities import JobStatus, Provider
from services.engines.base import InProcessEngine
from services.engines.direct_comfy_engine import DirectComfyEngine
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
from services.engines.modal_engine import ModalEngine
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
            assert models[0]["path"] == "checkpoints/model1.safetensors"

            loras = await engine.list_models("loras")
            assert len(loras) == 1
            assert loras[0]["name"] == "style.safetensors"


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
            container_config={"port": 8000},
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
            container_config={"port": 8000},
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
    async def test_modal_vllm_engine_streaming(self):
        from services.engines.llm_engine import ModalVLLMEngine

        engine = ModalVLLMEngine("modal-vllm", "ak-123", "as-456")

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
    async def test_modal_vllm_legacy_dialect_translation(self):
        from services.engines.llm_engine import ModalVLLMEngine

        engine = ModalVLLMEngine("modal-vllm", "ak-123", "as-456")

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
    async def test_modal_vllm_legacy_error_retryable_defaults_false(self):
        from services.engines.llm_engine import ModalVLLMEngine

        async def run_with(remote_payload):
            engine = ModalVLLMEngine("modal-vllm", "ak-123", "as-456")

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
    async def test_modal_vllm_legacy_cancelled_completed(self):
        from services.engines.llm_engine import ModalVLLMEngine

        engine = ModalVLLMEngine("modal-vllm", "ak-123", "as-456")

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
    async def test_modal_vllm_connection_error_retryable(self):
        from services.engines.llm_engine import ModalVLLMEngine

        try:
            import modal as modal_pkg
            conn_err_cls = modal_pkg.exception.ConnectionError
        except Exception:
            conn_err_cls = type(
                "ConnectionError", (Exception,), {"__module__": "modal.exception"}
            )

        for exc in (conn_err_cls("lost"), TimeoutError("slow")):
            engine = ModalVLLMEngine("modal-vllm", "ak-123", "as-456")
            with patch.object(
                engine, "get_client_async", side_effect=exc
            ):
                events = [ev async for ev in engine.inference(
                    {"model": "m1", "messages": []}, job_id="job-vllm-conn")]
                assert events[0]["event"] == "started"
                assert events[-1]["event"] == "failed"
                assert events[-1]["retryable"] is True

    @pytest.mark.asyncio
    async def test_modal_vllm_cancel_carries_partial_content(self):
        from services.engines.llm_engine import ModalVLLMEngine

        engine = ModalVLLMEngine("modal-vllm", "ak-123", "as-456")

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
    async def test_modal_vllm_list_models(self):
        from services.engines.llm_engine import ModalVLLMEngine

        engine = ModalVLLMEngine("modal-vllm", "ak-123", "as-456")
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
    async def test_modal_vllm_default_model_fallback(self):
        from services.engines.llm_engine import ModalVLLMEngine

        engine = ModalVLLMEngine("modal-vllm", "ak-123", "as-456")
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
    async def test_modal_vllm_unpacks_remote_signature(self):
        from services.engines.llm_engine import ModalVLLMEngine

        engine = ModalVLLMEngine("modal-vllm", "ak-123", "as-456")
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
        import services.engines.modal_tts_engine as tts_module

        engine = _make_tts_engine()
        storage = MagicMock()
        storage.file_size.remote.aio = AsyncMock(return_value=11)
        storage.read_file.remote.aio = AsyncMock(return_value=b"x" * 11)
        with (
            patch("services.engines.modal_tts_engine.modal") as mock_modal,
            patch.object(tts_module, "_MAX_AUDIO_BYTES", 10),
        ):
            mock_modal.Cls.from_name.return_value = MagicMock(return_value=storage)
            with pytest.raises(ValueError, match="limit is 10"):
                [chunk async for chunk in engine.get_file_stream("a.mp3")]
            # Refused on size alone: the bytes are never fetched.
            storage.read_file.remote.aio.assert_not_called()

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
            ("llm-vllm-1", "modal_vllm", True),  # full model lifecycle in-process
            ("llm-modal-1", "modal_llm", True),  # same ModalVLLMEngine class, same models/ tree
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
        # modal_llm resolves to the same ModalVLLMEngine class as modal_vllm
        # (registry ENGINE_SPECS), which implements setup_models
        # (llm_engine.py) for its models/ volume tree — True matches engine
        # reality. An earlier revision asserted False when the factory only
        # built the vLLM engine for the modal_vllm type / vllm-in-id.
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
            # vllm-in-id wins over a generic llm type.
            ({"provider_id": "llm-vllm-1", "provider_type": "openai_compat"}, "modal_vllm"),
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


class TestModalVLLMTruncation:
    @pytest.mark.asyncio
    async def test_stream_without_terminal_event_is_retryable_failure(self):
        from services.engines.llm_engine import ModalVLLMEngine

        engine = ModalVLLMEngine("modal-vllm", "ak-123", "as-456")

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
    async def test_modal_vllm_upload_encoded_precheck_skips_client(self):
        from services.engines.llm_engine import ModalVLLMEngine

        engine = ModalVLLMEngine("vllm-test", "ak-123", "as-456")
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
