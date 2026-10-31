"""Unit and Integration Tests for Dynamic VRAM Arbiter and Remote Agent VRAM Routes.

Verifies:
1. GPU VRAM inspection and telemetry.
2. Eviction priority hierarchy:
   - ComfyUI diffusion models unloaded first via /free.
   - llama-server stopped second when image generation needs GPU VRAM.
   - Laya System 1 preserved on CUDA (highest priority) unless clearance is still insufficient.
3. JIT llama-server management (start, stop, health polling).
4. Remote Agent FastAPI endpoints: /vram/prepare, /vram/status, /vram/stop-llm, /v1/decisions.
5. HybridRemoteEngine coordination with the remote VRAM Arbiter.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

# Ensure remote_agent directory is in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REMOTE_AGENT_DIR = REPO_ROOT / "remote_agent"
if str(REMOTE_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(REMOTE_AGENT_DIR))

from vram_manager import VRAMManager


class TestVRAMManagerHierarchy:
    """Test the priority retention/eviction hierarchy in VRAMManager."""

    def test_telemetry_defaults_without_cuda(self):
        mgr = VRAMManager()
        info = mgr.get_vram_info()
        assert "available" in info
        assert "vram_total_mb" in info
        assert "vram_free_mb" in info
        assert info["active_workload"] == "idle"
        assert info["laya_device"] == "cpu"

    def test_image_workload_preserves_laya_on_cuda_when_stopping_llama_is_sufficient(self):
        """When llama-server is stopped and free VRAM exceeds target, Laya MUST stay on CUDA."""
        mgr = VRAMManager()
        mgr.current_laya_device = "cuda:0"
        mgr.laya_cache[("convaiinnovations/laya-multilingual", "cuda:0")] = MagicMock()

        # Mock GPU memory: 16GB total (T4), initially 2GB free with llama running
        mock_info_initial = {
            "available": True,
            "device_name": "NVIDIA T4",
            "vram_total_mb": 15360,
            "vram_used_mb": 13360,
            "vram_free_mb": 2000,
        }
        # After stopping llama, free VRAM jumps to 13GB (well above 10GB target)
        mock_info_after_llama_stopped = {
            "available": True,
            "device_name": "NVIDIA T4",
            "vram_total_mb": 15360,
            "vram_used_mb": 2360,
            "vram_free_mb": 13000,
        }

        call_count = 0
        def fake_vram_info():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return dict(mock_info_initial, active_workload="image", laya_device="cuda:0")
            return dict(mock_info_after_llama_stopped, active_workload="image", laya_device="cuda:0")

        mgr.get_vram_info = fake_vram_info
        mgr.is_llama_running = MagicMock(return_value=True)
        mgr.stop_llama = MagicMock(return_value=True)

        res = mgr.prepare_for_workload("image", min_free_vram_mb=10000)

        # 1. llama-server was stopped
        mgr.stop_llama.assert_called_once()
        # 2. Laya was PRESERVED on CUDA!
        assert "stopped_llama_server" in res["actions_taken"]
        assert "preserved_laya_cuda" in res["actions_taken"]
        assert ("convaiinnovations/laya-multilingual", "cuda:0") in mgr.laya_cache

    def test_image_workload_unloads_laya_only_as_last_resort(self):
        """If stopping llama still leaves free VRAM below target, touch Laya as last resort."""
        mgr = VRAMManager()
        mgr.current_laya_device = "cuda:0"
        mgr.laya_cache[("convaiinnovations/laya-multilingual", "cuda:0")] = MagicMock()

        # Constrained GPU where even after stopping llama, free VRAM is only 8GB (< 12GB needed for Flux)
        mock_info = {
            "available": True,
            "device_name": "NVIDIA T4",
            "vram_total_mb": 15360,
            "vram_used_mb": 7360,
            "vram_free_mb": 8000,
        }
        mgr.get_vram_info = MagicMock(return_value=dict(mock_info, active_workload="image", laya_device="cuda:0"))
        mgr.is_llama_running = MagicMock(return_value=False)

        res = mgr.prepare_for_workload("image", min_free_vram_mb=12000)

        assert "unloaded_laya_cuda" in res["actions_taken"]
        assert ("convaiinnovations/laya-multilingual", "cuda:0") not in mgr.laya_cache
        assert mgr.current_laya_device == "cpu"

    def test_llm_workload_yields_comfy_vram_and_preserves_laya(self):
        """Preparing for LLM yields ComfyUI models and keeps Laya untouched on CUDA."""
        mgr = VRAMManager()
        mgr.current_laya_device = "cuda:0"
        mgr.laya_cache[("convaiinnovations/laya-multilingual", "cuda:0")] = MagicMock()
        mgr.free_comfy_vram = MagicMock(return_value=True)
        mgr.is_llama_running = MagicMock(return_value=True)

        res = mgr.prepare_for_workload("llm", model_id="sompoa_26b")

        mgr.free_comfy_vram.assert_called_once()
        assert "freed_comfy_vram" in res["actions_taken"]
        assert "preserved_laya_cuda" in res["actions_taken"]
        assert ("convaiinnovations/laya-multilingual", "cuda:0") in mgr.laya_cache

    def test_decisions_workload_selects_cuda_when_headroom_available(self):
        """Laya selects CUDA when free VRAM >= 1.2 GB."""
        mgr = VRAMManager()
        mgr.get_vram_info = MagicMock(return_value={
            "available": True,
            "device_name": "NVIDIA L4",
            "vram_total_mb": 22490,
            "vram_free_mb": 5000,
            "vram_used_mb": 17490,
            "active_workload": "decisions",
            "laya_device": "cuda:0",
        })

        dev = mgr.get_laya_device(required_headroom_mb=1200)
        assert dev == "cuda:0"


class TestRemoteAgentVRAMEndpoints:
    """Test remote agent FastAPI endpoints for VRAM coordination."""

    @pytest.fixture
    def client(self, monkeypatch):
        monkeypatch.setenv("REMOTE_AGENT_TOKEN", "test-secret-token")
        monkeypatch.setenv("WORKER_MODE", "hybrid")
        import importlib
        import server
        importlib.reload(server)
        monkeypatch.setattr(server, "TOKEN", "test-secret-token")
        return TestClient(server.app)

    def test_vram_status_endpoint(self, client):
        resp = client.get("/vram/status", headers={"Authorization": "Bearer test-secret-token"})
        assert resp.status_code == 200
        data = resp.json()
        assert "available" in data
        assert "vram_total_mb" in data
        assert "active_workload" in data

    def test_vram_prepare_endpoint_image(self, client):
        resp = client.post(
            "/vram/prepare",
            json={"workload": "image"},
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["workload"] == "image"

    def test_vram_stop_llm_endpoint(self, client):
        resp = client.post(
            "/vram/stop-llm",
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("success", "noop")
        assert "vram" in data

    def test_vram_endpoints_require_token(self, client):
        resp = client.get("/vram/status")
        assert resp.status_code == 401

    def test_list_upstream_models_returns_ready_when_idle(self, client):
        resp = client.get("/v1/models", headers={"Authorization": "Bearer test-secret-token"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("object") == "list"
        assert isinstance(data.get("data"), list)
        assert any(m.get("id") == "default" for m in data.get("data", []))

    def test_resolve_model_path_generic_and_fallback(self, tmp_path, monkeypatch):
        ram_dir = tmp_path / "ram_cache"
        ram_dir.mkdir()
        fake_gguf = ram_dir / "sompoa_26b_q5.gguf"
        fake_gguf.write_bytes(b"dummy gguf content")

        monkeypatch.setenv("RAM_CACHE_DIR", str(ram_dir))
        mgr = VRAMManager()

        # 1. Generic alias "default" should find the gguf
        path, mid = mgr._resolve_model_path("default")
        assert path == str(fake_gguf)
        assert "sompoa" in mid or mid == "default"

        # 2. None or empty should find the gguf
        path, mid = mgr._resolve_model_path(None)
        assert path == str(fake_gguf)

        # 3. Non-matching model ID should gracefully fallback to the available GGUF
        path, mid = mgr._resolve_model_path("unknown_requested_model")
        assert path == str(fake_gguf)

    def test_resolve_model_path_dual_rp_and_util(self, tmp_path, monkeypatch):
        ram_dir = tmp_path / "shm_dual"
        ram_dir.mkdir(parents=True)
        artemis = ram_dir / "TheDrummer_Artemis-31B-v1.2-Q4_K_M.gguf"
        artemis.write_bytes(b"artemis content")
        gemma = ram_dir / "gemma-3-12b-it-heretic-Q5_K_M.gguf"
        gemma.write_bytes(b"gemma content")

        monkeypatch.setenv("RAM_CACHE_DIR", str(ram_dir))
        monkeypatch.setenv("ACTIVE_RP_MODEL", "artemis_31b_q4")
        monkeypatch.setenv("ACTIVE_UTIL_MODEL", "gemma3_12b_heretic_util")

        mgr = VRAMManager()

        # "default" or "rp" must resolve to Artemis
        path_rp, _ = mgr._resolve_model_path("default")
        assert path_rp == str(artemis)

        path_rp2, _ = mgr._resolve_model_path("rp")
        assert path_rp2 == str(artemis)

        # "util" must resolve to Gemma
        path_u, _ = mgr._resolve_model_path("util")
        assert path_u == str(gemma)

        # Explicit model IDs
        path_art, _ = mgr._resolve_model_path("artemis_31b_q4")
        assert path_art == str(artemis)

        path_gem, _ = mgr._resolve_model_path("gemma3_12b_heretic_util")
        assert path_gem == str(gemma)


class TestVRAMManagerDynamicNGL:
    """Test dynamic layer offload calculation and GGUF header parsing."""

    def test_gguf_layer_count_parser(self, tmp_path):
        import struct

        mgr = VRAMManager()

        # Simulate GGUF binary header with gemma2.block_count = 46
        arch_key = b"gemma2.block_count"
        fake_header = (
            b"GGUF\x03\x00\x00\x00"  # Magic + Version 3
            + b"\x00" * 16  # Tensor count + KV count placeholders
            + struct.pack("<Q", len(arch_key))
            + arch_key
            + struct.pack("<I", 4)  # Type 4: UINT32
            + struct.pack("<I", 46)  # 46 layers
        )
        fake_gguf = tmp_path / "model.gguf"
        fake_gguf.write_bytes(fake_header)

        layers = mgr._get_gguf_layer_count(str(fake_gguf))
        assert layers == 46

    def test_calculate_safe_ngl_full_fit(self, tmp_path):
        mgr = VRAMManager()
        fake_gguf = tmp_path / "small_model.gguf"
        # 4 GB model file
        fake_gguf.write_bytes(b"\x00" * (4 * 1024 * 1024))

        # Mock GPU: 24GB total, 17GB free
        mgr.get_vram_info = MagicMock(return_value={
            "available": True,
            "device_name": "NVIDIA L4",
            "vram_total_mb": 22563,
            "vram_free_mb": 17000,
            "vram_used_mb": 5563,
        })

        # 4 MB model easily fits in 17000 MB free (weight + 2500 reserve <= 17000)
        ngl, meta = mgr.calculate_safe_ngl(str(fake_gguf))
        assert ngl == 99
        assert meta["mode"] == "full_gpu"

    def test_calculate_safe_ngl_partial_offload_prevents_oom(self, tmp_path, monkeypatch):
        mgr = VRAMManager()
        fake_gguf = tmp_path / "sompoa_26b.gguf"
        fake_gguf.write_bytes(b"dummy")

        # Mock model file size as 18,231 MB (~17.8 GB)
        monkeypatch.setattr("os.path.getsize", lambda p: 18231 * 1024 * 1024)

        # Mock GPU: NVIDIA L4 (22.5GB total, 17,000 MB free due to ComfyUI & Laya baseline)
        mgr.get_vram_info = MagicMock(return_value={
            "available": True,
            "device_name": "NVIDIA L4",
            "vram_total_mb": 22563,
            "vram_free_mb": 17000,
            "vram_used_mb": 5563,
        })
        mgr._get_gguf_layer_count = MagicMock(return_value=46)

        ngl, meta = mgr.calculate_safe_ngl(str(fake_gguf))

        # Model is 18.2 GB, free is 17.0 GB. Reserve is 2.5 GB.
        # Available weight budget = 17,000 - 2,500 = 14,500 MB
        # Fraction = 14,500 / 18,231 = 0.795
        # Target layers = int(46 * 0.795) = 36
        # Safe ngl = 35 (clamped to prevent full offload and leave headroom for KV cache)
        assert meta["mode"] == "partial_offload"
        assert ngl < 46  # Must NEVER be 99 or total_layers
        assert 30 <= ngl <= 38
        assert ngl <= 46 - 2  # At least 2 layers on CPU

    def test_calculate_safe_ngl_low_vram_falls_back_to_cpu(self, tmp_path, monkeypatch):
        mgr = VRAMManager()
        fake_gguf = tmp_path / "model.gguf"
        fake_gguf.write_bytes(b"dummy")
        monkeypatch.setattr("os.path.getsize", lambda p: 10000 * 1024 * 1024)

        # Critical low free VRAM (< 3000 MB)
        mgr.get_vram_info = MagicMock(return_value={
            "available": True,
            "device_name": "NVIDIA L4",
            "vram_total_mb": 22563,
            "vram_free_mb": 2000,
            "vram_used_mb": 20563,
        })

        ngl, meta = mgr.calculate_safe_ngl(str(fake_gguf))
        assert ngl == 0
        assert meta["mode"] == "cpu_only"

    def test_llm_workload_unloads_laya_if_it_enables_full_gpu_fit(self, tmp_path, monkeypatch):
        mgr = VRAMManager()
        mgr.current_laya_device = "cuda:0"
        mgr.laya_cache[("convaiinnovations/laya-multilingual", "cuda:0")] = MagicMock()
        mgr.free_comfy_vram = MagicMock(return_value=True)
        mgr.is_llama_running = MagicMock(return_value=False)
        mgr.ensure_llama_running = MagicMock(return_value=True)

        fake_gguf = tmp_path / "model_15gb.gguf"
        fake_gguf.write_bytes(b"dummy")
        mgr._resolve_model_path = MagicMock(return_value=(str(fake_gguf), "model_15gb"))

        # Model is 15,000 MB, reserve 2,500 MB -> needs 17,500 MB for 100% GPU fit
        monkeypatch.setattr("os.path.getsize", lambda p: 15000 * 1024 * 1024)

        # Free VRAM is currently 16,500 MB (< 17,500 MB needed).
        # But unloading Laya gives +1,500 MB = 18,000 MB >= 17,500 MB!
        mgr.get_vram_info = MagicMock(return_value={
            "available": True,
            "device_name": "NVIDIA L4",
            "vram_total_mb": 22563,
            "vram_free_mb": 16500,
            "vram_used_mb": 6063,
        })

        res = mgr.prepare_for_workload("llm", model_id="model_15gb")

        # Laya is demoted to CPU to enable 100% GPU fit!
        assert "unloaded_laya_to_allow_full_llm_gpu_fit" in res["actions_taken"]
        assert ("convaiinnovations/laya-multilingual", "cuda:0") not in mgr.laya_cache


class TestMultiGPUAndStorageStrategies:
    """Verify multi-GPU device routing, cross-workload eviction bypass, and low-RAM volume streaming."""

    def test_multi_gpu_image_workload_bypasses_llama_eviction(self, monkeypatch):
        monkeypatch.setenv("COMFY_GPU_DEVICE", "0")
        monkeypatch.setenv("LLM_GPU_DEVICE", "1")
        mgr = VRAMManager()
        assert mgr.is_multi_gpu is True
        assert mgr.comfy_gpu_device == 0
        assert mgr.llm_gpu_device == 1

        mgr.is_llama_running = MagicMock(return_value=True)
        mgr.stop_llama = MagicMock()

        res = mgr.prepare_for_workload("image")
        assert res["policy"] == "multi_gpu_concurrent"
        assert "bypassed_llama_eviction_multi_gpu" in res["actions_taken"]
        mgr.stop_llama.assert_not_called()

    def test_multi_gpu_llm_workload_bypasses_comfy_eviction(self, monkeypatch):
        monkeypatch.setenv("COMFY_GPU_DEVICE", "0")
        monkeypatch.setenv("LLM_GPU_DEVICE", "1")
        mgr = VRAMManager()
        assert mgr.is_multi_gpu is True

        mgr.free_comfy_vram = MagicMock()
        mgr.is_llama_running = MagicMock(return_value=True)

        res = mgr.prepare_for_workload("llm", model_id="default")
        assert "bypassed_comfy_eviction_multi_gpu" in res["actions_taken"]
        mgr.free_comfy_vram.assert_not_called()

    def test_multi_gpu_telemetry_reports_devices(self, monkeypatch):
        monkeypatch.setenv("COMFY_GPU_DEVICE", "0")
        monkeypatch.setenv("LLM_GPU_DEVICE", "1")
        mgr = VRAMManager()
        info = mgr.get_vram_info()
        assert "is_multi_gpu" in info
        assert info["is_multi_gpu"] is True
        assert info["comfy_gpu_device"] == 0
        assert info["llm_gpu_device"] == 1
        assert "devices" in info

    def test_low_ram_mode_resolves_disk_candidate_directly(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CACHE_IN_RAM", "0")
        mgr = VRAMManager()
        assert mgr.cache_in_ram is False

        # Create a mock modal volume path
        modal_dir = tmp_path / "mnt_data" / "tnhfantasy" / "llm_models" / "artemis"
        modal_dir.mkdir(parents=True)
        gguf_file = modal_dir / "artemis_31b_q4.gguf"
        gguf_file.write_bytes(b"dummy_weights")

        monkeypatch.setenv("PERSISTENT_STORAGE_PATH", str(tmp_path / "mnt_data" / "tnhfantasy" / "llm_models"))

        p, mid = mgr._resolve_model_path("artemis_31b_q4")
        assert p == str(gguf_file)
        assert "artemis" in mid.lower()


class TestVRAMConcurrencyAndWorkloadQueue:
    """Test cooperative workload leasing, non-destructive transitions, and queue arbiter."""

    def test_telemetry_reports_queue_and_lease_state(self):
        mgr = VRAMManager()
        mgr.active_lease = "llm"
        mgr.in_flight_count = 2
        mgr.waiting_queue = ["image"]

        info = mgr.get_vram_info()
        assert info["active_lease"] == "llm"
        assert info["in_flight_count"] == 2
        assert info["queue_depth"] == 1
        assert info["waiting_workloads"] == ["image"]
        assert "comfy_generating" in info

    def test_image_workload_cooperatively_waits_for_active_llm_lease(self):
        """When an LLM stream is actively in-flight, an image request MUST NOT kill llama-server; it waits for drain."""
        import threading
        import time

        mgr = VRAMManager()
        mgr.active_lease = "llm"
        mgr.in_flight_count = 1
        mgr.is_llama_running = MagicMock(return_value=True)
        mgr.stop_llama = MagicMock(return_value=True)

        # Mock low free VRAM so image generation requires stopping llama
        mock_info = {
            "available": True,
            "device_name": "NVIDIA L4",
            "vram_total_mb": 24000,
            "vram_used_mb": 22000,
            "vram_free_mb": 2000,
        }
        mgr.get_vram_info = MagicMock(return_value=mock_info)

        def _delayed_llm_finish():
            time.sleep(0.15)
            mgr.release_lease("llm")

        thread = threading.Thread(target=_delayed_llm_finish, daemon=True)
        thread.start()

        # Prepare for image: should wait for LLM to finish, then safely stop llama
        res = mgr.prepare_for_workload("image", min_free_vram_mb=10000, timeout=5.0)

        thread.join(timeout=2.0)
        assert "waited_for_llm_drain" in res["actions_taken"]
        assert "stopped_llama_server" in res["actions_taken"]
        mgr.stop_llama.assert_called_once()
        assert mgr.active_lease == "image"

    def test_llm_workload_cooperatively_waits_for_active_comfy_generation(self):
        """When ComfyUI is generating, an LLM request MUST NOT free ComfyUI models; it waits for sampling to finish."""
        import threading
        import time

        mgr = VRAMManager()
        comfy_active = [True]
        mgr.is_comfy_generating = MagicMock(side_effect=lambda: comfy_active[0])
        mgr.free_comfy_vram = MagicMock(return_value=True)
        mgr.is_llama_running = MagicMock(return_value=True)
        mgr.get_vram_info = MagicMock(return_value={"available": True, "vram_total_mb": 24000, "vram_free_mb": 15000})

        def _delayed_comfy_finish():
            time.sleep(0.15)
            comfy_active[0] = False

        thread = threading.Thread(target=_delayed_comfy_finish, daemon=True)
        thread.start()

        res = mgr.prepare_for_workload("llm", timeout=5.0)

        thread.join(timeout=2.0)
        assert "waited_for_comfy_drain" in res["actions_taken"]
        assert "freed_comfy_vram" in res["actions_taken"]
        mgr.free_comfy_vram.assert_called_once()
        assert mgr.active_lease == "llm"

    def test_vram_release_endpoint(self, monkeypatch):
        import server
        from server import app
        from vram_manager import get_vram_manager

        monkeypatch.setattr(server, "TOKEN", "test-token")
        client = TestClient(app)
        mgr = get_vram_manager()
        mgr.active_lease = "image"
        mgr.in_flight_count = 1

        resp = client.post("/vram/release", json={"workload": "image"}, headers={"Authorization": "Bearer test-token"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "released"
        assert data["workload"] == "image"
        assert data["in_flight"] == 0
        assert data["active_lease"] is None



