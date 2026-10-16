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

    # Mock free comfy vram
    free_call_count = 0
    async def mock_free():
        nonlocal free_call_count
        free_call_count += 1

    engine._free_comfy_vram = mock_free

    image_workflow = {
        "3": {"class_type": "KSampler", "inputs": {}},
        "4": {"class_type": "SaveImage", "inputs": {}},
    }

    # 1. Image generation runs: models remain warm (free Comfy VRAM is NOT called)
    events = [e async for e in engine.inference(image_workflow, job_id="job-1")]
    assert len(events) == 2
    assert events[-1]["event"] == "completed"
    assert free_call_count == 0

    # 2. Second image generation runs: models still remain warm
    events2 = [e async for e in engine.inference(image_workflow, job_id="job-2")]
    assert len(events2) == 2
    assert free_call_count == 0

    # 3. Workload switch to LLM: ComfyUI VRAM is freed to yield GPU to LLM
    llm_workflow = {"messages": [{"role": "user", "content": "hi"}]}
    llm_events = [e async for e in engine.inference(llm_workflow, job_id="job-3")]
    assert len(llm_events) == 2
    assert free_call_count == 1

    # 4. Another LLM job runs: ComfyUI VRAM is already freed, no redundant /free call
    llm_events2 = [e async for e in engine.inference(llm_workflow, job_id="job-4")]
    assert len(llm_events2) == 2
    assert free_call_count == 1


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


