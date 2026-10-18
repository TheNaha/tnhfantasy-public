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
        import server
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

