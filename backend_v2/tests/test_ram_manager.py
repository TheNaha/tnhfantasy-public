import os
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure remote_agent is on sys.path
REMOTE_AGENT_DIR = Path(__file__).resolve().parent.parent.parent / "remote_agent"
if str(REMOTE_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(REMOTE_AGENT_DIR))

from ram_manager import RamModelManager


@pytest.fixture
def temp_env(tmp_path):
    ram_dir = tmp_path / "shm"
    ram_dir.mkdir()
    source_dir = tmp_path / "models"
    source_dir.mkdir()
    return ram_dir, source_dir


def test_ram_manager_init_and_cache(temp_env):
    ram_dir, source_dir = temp_env
    # 10 MB budget
    mgr = RamModelManager(ram_dir=str(ram_dir), budget_gb=0.01, min_system_reserve_gb=0.0)
    assert mgr.budget_bytes == int(0.01 * 1024 * 1024 * 1024)

    # Create dummy model file (1MB)
    m1 = source_dir / "artemis.gguf"
    m1.write_bytes(b"A" * (1024 * 1024))

    # Pre-warm into RAM
    ram_path = mgr.ensure_in_ram(str(m1), model_id="artemis", role="rp", is_anchor=True)
    assert ram_path.exists()
    assert ram_path.stat().st_size == 1024 * 1024
    assert mgr.is_cached("artemis")
    assert "artemis" in mgr.entries
    entry = mgr.entries["artemis"]
    assert entry.is_anchor is True
    assert entry.role == "rp"

    # Cache hit returns immediately
    mtime_before = entry.last_used
    time.sleep(0.01)
    ram_path2 = mgr.ensure_in_ram(str(m1), model_id="artemis")
    assert ram_path2 == ram_path
    assert mgr.entries["artemis"].last_used >= mtime_before


def test_ram_manager_anchor_protection_and_lru_eviction(temp_env):
    ram_dir, source_dir = temp_env
    # Small budget: 3 MB
    mgr = RamModelManager(ram_dir=str(ram_dir), budget_gb=3 / 1024, min_system_reserve_gb=0.0)

    # 1. Anchor model (1MB)
    m_anchor = source_dir / "anchor_rp.gguf"
    m_anchor.write_bytes(b"R" * (1024 * 1024))
    mgr.set_anchors(["anchor_rp"])
    mgr.ensure_in_ram(str(m_anchor), model_id="anchor_rp", role="rp", is_anchor=True)

    # 2. Secondary model 1 (1MB)
    m_sec1 = source_dir / "illustrious.safetensors"
    m_sec1.write_bytes(b"I" * (1024 * 1024))
    mgr.ensure_in_ram(str(m_sec1), model_id="illustrious", role="image", is_anchor=False)

    # 3. Secondary model 2 (1MB)
    time.sleep(0.01)
    m_sec2 = source_dir / "lora_detail.safetensors"
    m_sec2.write_bytes(b"L" * (1024 * 1024))
    mgr.ensure_in_ram(str(m_sec2), model_id="lora_detail", role="lora", is_anchor=False)

    # Currently 3MB used (anchor_rp, illustrious, lora_detail)
    assert mgr.current_usage_bytes == 3 * 1024 * 1024
    assert mgr.is_cached("anchor_rp")
    assert mgr.is_cached("illustrious")
    assert mgr.is_cached("lora_detail")

    # 4. Add Secondary model 3 (1MB) -> exceeds 3MB budget!
    # LRU should evict illustrious (oldest secondary), but NOT anchor_rp!
    time.sleep(0.01)
    m_sec3 = source_dir / "lora_style.safetensors"
    m_sec3.write_bytes(b"S" * (1024 * 1024))
    mgr.ensure_in_ram(str(m_sec3), model_id="lora_style", role="lora", is_anchor=False)

    # Anchor must still be cached!
    assert mgr.is_cached("anchor_rp")
    # Oldest secondary (illustrious) should have been evicted
    assert not mgr.is_cached("illustrious")
    # Newest models remain
    assert mgr.is_cached("lora_detail")
    assert mgr.is_cached("lora_style")


def test_ram_manager_explicit_eviction(temp_env):
    ram_dir, source_dir = temp_env
    mgr = RamModelManager(ram_dir=str(ram_dir), budget_gb=0.05, min_system_reserve_gb=0.0)

    m = source_dir / "temp_model.safetensors"
    m.write_bytes(b"T" * (512 * 1024))
    mgr.ensure_in_ram(str(m), model_id="temp_model", role="image", is_anchor=True)

    # Attempt evicting anchor without force -> False
    assert mgr.evict_model("temp_model", force=False) is False
    assert mgr.is_cached("temp_model")

    # Evict with force -> True
    assert mgr.evict_model("temp_model", force=True) is True
    assert not mgr.is_cached("temp_model")


def test_ram_manager_opportunistic_prewarming(temp_env):
    ram_dir, source_dir = temp_env
    # 5 MB budget
    mgr = RamModelManager(ram_dir=str(ram_dir), budget_gb=5 / 1024, min_system_reserve_gb=0.0)

    m1 = source_dir / "rp.gguf"
    m1.write_bytes(b"1" * (1024 * 1024))
    m2 = source_dir / "util.gguf"
    m2.write_bytes(b"2" * (1024 * 1024))
    m3 = source_dir / "image.safetensors"
    m3.write_bytes(b"3" * (1024 * 1024))
    m4 = source_dir / "lora1.safetensors"
    m4.write_bytes(b"4" * (1024 * 1024))
    m5 = source_dir / "lora2.safetensors"
    m5.write_bytes(b"5" * (2 * 1024 * 1024))  # 2MB -> would exceed remaining budget

    specs = [
        {"id": "rp", "source_path": str(m1), "role": "rp", "is_anchor": True},
        {"id": "util", "source_path": str(m2), "role": "util", "is_anchor": True},
        {"id": "image", "source_path": str(m3), "role": "image", "is_anchor": True},
        {"id": "lora1", "source_path": str(m4), "role": "lora", "is_anchor": False},
        {"id": "lora2", "source_path": str(m5), "role": "lora", "is_anchor": False},
    ]

    prewarmed = mgr.prewarm_models(specs)
    # All 3 anchors should be prewarmed (total 3MB)
    assert "rp" in prewarmed
    assert "util" in prewarmed
    assert "image" in prewarmed
    # lora1 (1MB) fits within remaining 2MB spare limit
    assert "lora1" in prewarmed
    # lora2 (2MB) does not fit (only 1MB left)
    assert "lora2" not in prewarmed

    status = mgr.get_status()
    assert status["models_count"] == 4
    assert len(status["anchor_models"]) == 3
    assert len(status["spare_cached_models"]) == 1
    assert status["used_bytes"] == 4 * 1024 * 1024


def test_server_ram_cache_api(monkeypatch, tmp_path):
    os.environ["REMOTE_AGENT_TOKEN"] = "test-token"
    os.environ["DATA_DIR"] = str(tmp_path)
    os.environ["RAM_CACHE_DIR"] = str(tmp_path / "shm")

    # Import server
    import server

    client = TestClient(server.app)
    headers = {"Authorization": "Bearer test-token"}

    # 1. GET /ram-cache/status
    res = client.get("/ram-cache/status", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "budget_gb" in data
    assert "percent_used" in data

    # 2. POST /ram-cache/prewarm
    m_file = tmp_path / "test_model.gguf"
    m_file.write_bytes(b"X" * (1024 * 1024))

    prewarm_payload = {
        "anchors": ["test_anchor"],
        "models": [
            {
                "id": "test_anchor",
                "source_path": str(m_file),
                "role": "rp",
                "is_anchor": True,
            }
        ],
    }
    res_pw = client.post("/ram-cache/prewarm", json=prewarm_payload, headers=headers)
    assert res_pw.status_code == 200
    pw_data = res_pw.json()
    assert pw_data["ok"] is True
    assert "test_anchor" in pw_data["prewarmed"]
    assert pw_data["status"]["models_count"] >= 1

    # 3. POST /ram-cache/evict (force=True)
    res_ev = client.post("/ram-cache/evict", json={"model_id": "test_anchor", "force": True}, headers=headers)
    assert res_ev.status_code == 200
    assert res_ev.json()["ok"] is True
