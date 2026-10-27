import os
import pytest
from fastapi.testclient import TestClient

from repo_paths import require_repo_root

REPO_ROOT = require_repo_root("remote_agent/server.py")
AGENT_DIR = REPO_ROOT / "remote_agent"


@pytest.fixture
def storage_agent_client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMOTE_AGENT_TOKEN", "test-token")
    monkeypatch.setenv("WORKER_MODE", "storage")
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("BACKEND_URL", "http://127.0.0.1:8002")
    monkeypatch.setenv("PROVIDER_ID", "test_colab_worker")

    import sys
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    if str(AGENT_DIR) not in sys.path:
        sys.path.insert(0, str(AGENT_DIR))

    import server as srv
    monkeypatch.setattr(srv, "WORKER_MODE", "storage")
    monkeypatch.setattr(srv, "DATA_ROOT", str(data_dir))

    # In storage mode, register stubs if not registered
    client = TestClient(srv.app)
    return client, data_dir


def test_storage_mode_health_reports_ready_for_empty(storage_agent_client):
    client, _ = storage_agent_client
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["worker_mode"] == "storage"
    assert data["ready_for"] == []
    assert data["inference_enabled"] is False


def test_storage_mode_info_authenticated(storage_agent_client):
    client, data_dir = storage_agent_client
    # Unauthenticated info should 401
    unauth = client.get("/info")
    assert unauth.status_code == 401

    # Authenticated info should return topology
    resp = client.get("/info", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    info = resp.json()
    assert info["worker_mode"] == "storage"
    assert info["inference_enabled"] is False
    assert os.path.realpath(info["storage_root"]) == os.path.realpath(str(data_dir))


def test_storage_mode_inference_endpoints_return_503(storage_agent_client):
    client, _ = storage_agent_client
    headers = {"Authorization": "Bearer test-token"}
    resp = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}, headers=headers)
    assert resp.status_code == 503
    assert "storage-only" in resp.json()["detail"]

    resp = client.post("/synthesize", json={"text": "hello"}, headers=headers)
    assert resp.status_code == 503
    assert "storage-only" in resp.json()["detail"]


def test_storage_mode_list_and_manage_models(storage_agent_client):
    client, data_dir = storage_agent_client
    headers = {"Authorization": "Bearer test-token"}

    # Create dummy checkpoint
    ckpt_dir = data_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    fake_model = ckpt_dir / "test_model.safetensors"
    fake_model.write_bytes(b"dummy safetensors content " * 100)

    resp = client.post("/list-models", json={"directory": "checkpoints"}, headers=headers)
    assert resp.status_code == 200
    payload = resp.json()
    files = payload.get("files") or payload.get("models") or []
    names = [f["name"] for f in files]
    assert "test_model.safetensors" in names


def test_storage_mode_reconcile_backend_endpoint(storage_agent_client, monkeypatch):
    client, _ = storage_agent_client
    headers = {"Authorization": "Bearer test-token"}

    # Mock httpx in server
    import httpx

    class FakeResponse:
        status_code = 200
        def json(self):
            return {"status": "started", "message": "Reconciliation started"}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, url, params=None):
            assert "/api/v2/providers/test_colab_worker/reconcile" in url
            assert params == {"force": "true", "quick_sync": "false"}
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    resp = client.post("/reconcile-backend", json={}, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["success"] is True
    assert data["result"]["status"] == "started"
