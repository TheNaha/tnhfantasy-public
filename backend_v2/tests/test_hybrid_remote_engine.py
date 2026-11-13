"""Tests for the HybridRemoteEngine (unified Image + LLM + TTS on a single node).

Verifies:
1. Hardware capability marker and concurrency policy resolution:
   - Explicit policies ("exclusive", "semi_concurrent", "concurrent")
   - "auto" probing via /info with VRAM thresholds (>=70GB -> concurrent, >=35GB -> semi_concurrent, else exclusive)
   - Fallback to exclusive on agent query error
2. Dual-modality dispatch:
   - Image prompt graphs route to DirectComfyEngine
   - Chat payloads route to RemoteLLMEngine
   - In exclusive mode: ComfyUI /free is invoked after image generation
3. Mutual exclusion lock:
   - Verifies sequential execution under exclusive policy
4. Unified health aggregation
5. Model storage delegation to sidecar agent
"""

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from services.engines.hybrid_engine import HybridRemoteEngine


class _MockTransport(httpx.AsyncBaseTransport):
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


@pytest.mark.asyncio
async def test_explicit_concurrency_policies():
    engine_ex = HybridRemoteEngine("hyb-1", base_url="http://node:8001", concurrency_policy="exclusive")
    assert await engine_ex._resolve_policy() == "exclusive"

    engine_sc = HybridRemoteEngine("hyb-2", base_url="http://node:8001", concurrency_policy="semi_concurrent")
    assert await engine_sc._resolve_policy() == "semi_concurrent"

    engine_cc = HybridRemoteEngine("hyb-3", base_url="http://node:8001", concurrency_policy="concurrent")
    assert await engine_cc._resolve_policy() == "concurrent"


@pytest.mark.asyncio
async def test_auto_policy_resolution_a100_80gb():
    """VRAM >= 70GB auto-resolves to concurrent."""
    transport = _MockTransport([
        (200, {"worker_mode": "hybrid", "gpu": {"name": "NVIDIA A100-SXM4-80GB", "vram_total_mb": 81920}}, {}),
    ])
    engine = HybridRemoteEngine("hyb-auto", base_url="http://node:8001", concurrency_policy="auto")
    engine.image_engine._agent_http = httpx.AsyncClient(base_url="http://node:8001", transport=transport)

    policy = await engine._resolve_policy()
    assert policy == "concurrent"
    assert engine._detected_gpu["name"] == "NVIDIA A100-SXM4-80GB"


@pytest.mark.asyncio
async def test_auto_policy_resolution_a100_40gb():
    """VRAM 35GB-70GB auto-resolves to semi_concurrent."""
    transport = _MockTransport([
        (200, {"worker_mode": "hybrid", "gpu": {"name": "NVIDIA A100-PCIE-40GB", "vram_total_mb": 40960}}, {}),
    ])
    engine = HybridRemoteEngine("hyb-auto", base_url="http://node:8001", concurrency_policy="auto")
    engine.image_engine._agent_http = httpx.AsyncClient(base_url="http://node:8001", transport=transport)

    policy = await engine._resolve_policy()
    assert policy == "semi_concurrent"


@pytest.mark.asyncio
async def test_auto_policy_resolution_budget_l4():
    """VRAM < 35GB auto-resolves to exclusive."""
    transport = _MockTransport([
        (200, {"worker_mode": "hybrid", "gpu": {"name": "NVIDIA L4", "vram_total_mb": 23040}}, {}),
    ])
    engine = HybridRemoteEngine("hyb-auto", base_url="http://node:8001", concurrency_policy="auto")
    engine.image_engine._agent_http = httpx.AsyncClient(base_url="http://node:8001", transport=transport)

    policy = await engine._resolve_policy()
    assert policy == "exclusive"


@pytest.mark.asyncio
async def test_auto_policy_fallback_on_agent_unreachable():
    """When /info fails, fall back to conservative 'exclusive' to protect budget GPUs."""
    transport = _MockTransport([
        (500, {"error": "internal error"}, {}),
    ])
    engine = HybridRemoteEngine("hyb-auto", base_url="http://node:8001", concurrency_policy="auto")
    engine.image_engine._agent_http = httpx.AsyncClient(base_url="http://node:8001", transport=transport)

    policy = await engine._resolve_policy()
    assert policy == "exclusive"


@pytest.mark.asyncio
async def test_image_workflow_detection_and_free_vram_in_exclusive_mode():
    """Image generation keeps models warm, and switching to LLM frees ComfyUI VRAM."""
    engine = HybridRemoteEngine("hyb-test", base_url="http://node", concurrency_policy="exclusive")

    # Mock image_engine.inference
    async def mock_image_inference(wf, **kwargs):
        yield {"event": "started", "job_id": "job-1"}
        yield {"event": "completed", "outputs": ["out.png"]}

    engine.image_engine.inference = mock_image_inference

    # Mock llm_engine.inference
    async def mock_llm_inference(wf, **kwargs):
        yield {"event": "delta", "text": "hello"}
        yield {"event": "completed", "outputs": [{"text": "hello"}]}

    engine.llm_engine.inference = mock_llm_inference

    # Mock free comfy vram and prepare agent vram
    free_call_count = 0
    prepare_calls = []

    async def mock_free():
        nonlocal free_call_count
        free_call_count += 1

    async def mock_prepare(workload, model=None):
        prepare_calls.append((workload, model))

    engine._free_comfy_vram = mock_free
    engine._prepare_agent_vram = mock_prepare

    image_workflow = {
        "3": {"class_type": "KSampler", "inputs": {}},
        "4": {"class_type": "SaveImage", "inputs": {}},
    }

    # 1. Image generation runs: models remain warm (free Comfy VRAM is NOT called, image workload prepared)
    events = [e async for e in engine.inference(image_workflow, job_id="job-1")]
    assert len(events) == 2
    assert events[-1]["event"] == "completed"
    assert free_call_count == 0
    assert ("image", None) in prepare_calls

    # 2. Second image generation runs: models still remain warm
    prepare_calls.clear()
    events2 = [e async for e in engine.inference(image_workflow, job_id="job-2")]
    assert len(events2) == 2
    assert free_call_count == 0
    assert len(prepare_calls) == 0

    # 3. Workload switch to LLM: ComfyUI VRAM is freed to yield GPU to LLM, agent vram arbiter notified
    llm_workflow = {"messages": [{"role": "user", "content": "hi"}]}
    llm_events = [e async for e in engine.inference(llm_workflow, job_id="job-3")]
    assert len(llm_events) == 2
    assert free_call_count == 1
    assert ("llm", None) in prepare_calls

    # 4. Another LLM job runs: ComfyUI VRAM is already freed, no redundant /free call
    prepare_calls.clear()
    llm_events2 = [e async for e in engine.inference(llm_workflow, job_id="job-4")]
    assert len(llm_events2) == 2
    assert free_call_count == 1
    assert len(prepare_calls) == 0


@pytest.mark.asyncio
async def test_llm_workflow_routing():
    """Chat payloads route to llm_engine."""
    engine = HybridRemoteEngine("hyb-test", base_url="http://node", concurrency_policy="exclusive")

    async def mock_llm_inference(wf, **kwargs):
        yield {"event": "started", "job_id": "job-llm"}
        yield {"event": "chunk", "text": "Hello world"}
        yield {"event": "completed", "response": "Hello world"}

    engine.llm_engine.inference = mock_llm_inference

    workflow = {
        "messages": [{"role": "user", "content": "Hi"}],
        "model": "rp",
    }

    events = [e async for e in engine.inference(workflow, job_id="job-llm")]
    assert len(events) == 3
    assert events[-1]["event"] == "completed"


@pytest.mark.asyncio
async def test_aggregated_health_check():
    """check_health combines image and llm statuses."""
    engine = HybridRemoteEngine("hyb-test", base_url="http://node", concurrency_policy="exclusive")

    engine.image_engine.check_health = AsyncMock(return_value={"status": "healthy", "comfyui": "connected"})
    engine.llm_engine.check_health = AsyncMock(return_value={"status": "healthy", "llama": "connected"})

    health = await engine.check_health()
    assert health["status"] == "healthy"
    assert health["engine"] == "remote_hybrid"
    assert health["concurrency_policy"] == "exclusive"
    assert "components" in health
    assert health["components"]["comfyui"]["status"] == "healthy"
    assert health["components"]["llm"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_model_storage_delegation():
    """Model listing and setup delegate to image_engine (agent client)."""
    engine = HybridRemoteEngine("hyb-test", base_url="http://node")
    engine.image_engine.list_models = AsyncMock(return_value=[{"name": "test.safetensors", "size": 1024}])
    engine.image_engine.setup_models = AsyncMock(return_value=True)

    models = await engine.list_models("checkpoints")
    assert len(models) == 1
    assert models[0]["name"] == "test.safetensors"

    setup_ok = await engine.setup_models()
    assert setup_ok is True


@pytest.mark.asyncio
async def test_free_vram_resets_warm_workload():
    """free_vram unloads models from ComfyUI and clears warm workload tracking."""
    engine = HybridRemoteEngine("hyb-test", base_url="http://node")
    engine._last_workload = "flux_sdxl"
    engine._free_comfy_vram = AsyncMock()

    success = await engine.free_vram()
    assert success is True
    assert engine.warm_workload is None
    engine._free_comfy_vram.assert_awaited_once()


def test_llm_engine_targets_agent_url_gateway():
    """Verify RemoteLLMEngine uses authenticated agent_url rather than raw loopback llm_port."""
    # 1. Default configuration: no explicit llm_url
    engine = HybridRemoteEngine("hyb-test", base_url="http://100.150.0.26")
    assert engine.agent_url == "http://100.150.0.26:8001"
    assert engine.llm_engine.agent_url == "http://100.150.0.26:8001"

    # 2. When llm_url matches default host:llm_port (port 8003), it redirects to agent_url
    engine_with_port = HybridRemoteEngine(
        "hyb-test",
        base_url="http://100.150.0.26",
        llm_url="http://100.150.0.26:8003",
    )
    assert engine_with_port.llm_engine.agent_url == "http://100.150.0.26:8001"

    # 3. Explicit custom agent url is preserved
    engine_custom = HybridRemoteEngine(
        "hyb-test",
        base_url="http://100.150.0.26",
        llm_url="http://100.150.0.99:9000",
    )
    assert engine_custom.llm_engine.agent_url == "http://100.150.0.99:9000"


def test_hybrid_engine_is_util_workload_detection():
    engine = HybridRemoteEngine(
        "hyb-test",
        base_url="http://node",
        default_rp_model="artemis_31b_q4",
        default_util_model="gemma3_12b_heretic_util",
    )
    # Direct model string matches
    assert engine._is_util_workload({"model": "util"}) is True
    assert engine._is_util_workload({"model": "gemma3_12b_heretic_util"}) is True
    assert engine._is_util_workload({"model": "my_util_model"}) is True
    assert engine._is_util_workload({"model": "artemis_31b_q4"}) is False
    assert engine._is_util_workload({"model": "rp"}) is False

    # Workflow role matches
    assert engine._is_util_workload({"role": "util"}) is True
    assert engine._is_util_workload({"role": "rp"}) is False

    # Workflow kind/type matches
    assert engine._is_util_workload({"type": "memory_extraction"}) is True
    assert engine._is_util_workload({"type": "story_parse"}) is True
    assert engine._is_util_workload({"type": "state_updater"}) is True
    assert engine._is_util_workload({"kind": "tool_call"}) is True
    assert engine._is_util_workload({"type": "chat_reply"}) is False
    assert engine._is_util_workload({"type": "narrator"}) is False


@pytest.mark.asyncio
async def test_semi_concurrent_util_locking_and_vram_preparation():
    engine = HybridRemoteEngine(
        "hyb-test",
        base_url="http://node",
        concurrency_policy="semi_concurrent",
        default_util_model="gemma3_12b_heretic_util",
    )

    prepare_calls = []
    release_calls = []

    async def mock_prepare(workload, model=None):
        prepare_calls.append((workload, model))

    async def mock_release(workload):
        release_calls.append(workload)

    async def mock_llm_inference(wf, **kwargs):
        yield {"event": "completed", "text": "done"}

    engine._prepare_agent_vram = mock_prepare
    engine._release_agent_vram = mock_release
    engine.llm_engine.inference = mock_llm_inference

    # 1. Util job runs: triggers GPU lock, prepare_agent_vram, and release_agent_vram
    util_wf = {"messages": [{"role": "user", "content": "extract"}], "type": "memory_extraction", "model": "gemma3_12b_heretic_util"}
    events = [e async for e in engine.inference(util_wf, job_id="job-util-1")]
    assert len(events) == 1
    assert ("llm", "gemma3_12b_heretic_util") in prepare_calls
    assert "llm" in release_calls

    # 2. RP job runs: bypasses heavy swap lock & prepare call
    prepare_calls.clear()
    release_calls.clear()
    rp_wf = {"messages": [{"role": "user", "content": "hello"}], "type": "chat_reply", "model": "artemis_31b_q4"}
    events2 = [e async for e in engine.inference(rp_wf, job_id="job-rp-1")]
    assert len(events2) == 1
    assert len(prepare_calls) == 0
    assert len(release_calls) == 0


@pytest.mark.asyncio
async def test_degraded_health_check_returns_ready_and_ready_for():
    """When LLM is in standby (unhealthy/idle), status is degraded but ready is True and ready_for lists image/tts."""
    engine = HybridRemoteEngine("hyb-test", base_url="http://node:8001")
    engine.image_engine.check_health = AsyncMock(return_value={"status": "healthy", "comfy_reachable": True, "agent_reachable": True})
    engine.llm_engine.check_health = AsyncMock(return_value={"status": "unhealthy", "ready": False})

    health = await engine.check_health()
    assert health["status"] == "degraded"
    assert health["ready"] is True
    assert "image" in health["ready_for"]
    assert "tts" in health["ready_for"]
    assert health["components"]["comfyui"]["status"] == "healthy"
    assert health["components"]["llm"]["status"] == "unhealthy"
    assert health["components"]["tts"]["status"] == "healthy"
    assert health["components"]["tts"]["port"] == 8001
    assert health["components"]["tts"]["workflow_port"] == 8188


@pytest.mark.asyncio
async def test_hybrid_model_listing_directory_routing():
    """Verify that models, llm, models/llm route to llm_engine with 'models', and '' merges both."""
    engine = HybridRemoteEngine("hyb-test", base_url="http://node:8001")
    engine.image_engine.list_models = AsyncMock(return_value=[{"name": "sdxl.safetensors", "size": 1000}])
    engine.llm_engine.list_models = AsyncMock(return_value=[{"name": "llama.gguf", "size": 2000}])

    # 1. Query "models" -> routes to llm_engine with "models"
    models_res = await engine.list_models("models")
    assert models_res == [{"name": "llama.gguf", "size": 2000}]
    engine.llm_engine.list_models.assert_awaited_with("models")

    # 2. Query "llm" -> routes to llm_engine with "models"
    engine.llm_engine.list_models.reset_mock()
    llm_res = await engine.list_models("llm")
    assert llm_res == [{"name": "llama.gguf", "size": 2000}]
    engine.llm_engine.list_models.assert_awaited_with("models")

    # 3. Query "" -> merges image models and llm models
    engine.llm_engine.list_models.reset_mock()
    engine.image_engine.list_models.reset_mock()
    all_res = await engine.list_models("")
    assert len(all_res) == 2
    assert {"name": "sdxl.safetensors", "size": 1000} in all_res
    assert {"name": "llama.gguf", "size": 2000} in all_res
    engine.image_engine.list_models.assert_awaited_with("")
    engine.llm_engine.list_models.assert_awaited_with("models")

    # 4. Query image directory "checkpoints" -> delegates to image_engine
    engine.image_engine.list_models.reset_mock()
    ckpt_res = await engine.list_models("checkpoints")
    assert ckpt_res == [{"name": "sdxl.safetensors", "size": 1000}]
    engine.image_engine.list_models.assert_awaited_with("checkpoints")


@pytest.mark.asyncio
async def test_hybrid_list_voices():
    """Verify list_voices queries /v1/voices on sidecar agent."""
    transport = _MockTransport([
        (200, {"voices": [{"id": "friendly", "name": "Friendly"}], "total": 1}, {}),
    ])
    engine = HybridRemoteEngine("hyb-test", base_url="http://node:8001")
    engine.image_engine._agent_http = httpx.AsyncClient(base_url="http://node:8001", transport=transport)

    voices = await engine.list_voices()
    assert len(voices) == 1
    assert voices[0]["id"] == "friendly"



@pytest.mark.asyncio
async def test_hybrid_cancel_job_propagates_to_active_child_engine():
    import asyncio

    engine = HybridRemoteEngine("hyb-cancel", base_url="http://node", concurrency_policy="concurrent")
    started = asyncio.Event()
    aborted = False

    async def slow_llm_inference(wf, job_id=None, **kwargs):
        def _abort():
            nonlocal aborted
            aborted = True

        engine.llm_engine.register_abort(job_id, _abort)
        started.set()
        yield {"event": "delta", "text": "part"}
        while not engine.llm_engine.is_cancelled(job_id):
            await asyncio.sleep(0.01)
        yield {"event": "cancelled", "job_id": job_id}

    engine.llm_engine.inference = slow_llm_inference

    events = []

    async def _consume():
        async for ev in engine.run_inference({"messages": [{"role": "user", "content": "hi"}]}, job_id="job-hyb-1"):
            events.append(ev)

    consumer = asyncio.create_task(_consume())
    await started.wait()
    cancelled = await engine.cancel_job("job-hyb-1")
    await consumer

    assert cancelled is True
    assert aborted is True
    assert any(ev.get("event") == "cancelled" for ev in events)



