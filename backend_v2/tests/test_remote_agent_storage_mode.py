import os
import sys
import pytest
from fastapi.testclient import TestClient

from repo_paths import require_repo_root

REPO_ROOT = require_repo_root("remote_agent/server.py")
AGENT_DIR = REPO_ROOT / "remote_agent"


def _import_server_fresh(monkeypatch):
    """Import remote_agent/server.py fresh with AGENT_DIR on sys.path."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    if str(AGENT_DIR) not in sys.path:
        sys.path.insert(0, str(AGENT_DIR))
    sys.modules.pop("server", None)
    import server as srv  # noqa: PLC0415
    return srv


@pytest.fixture
def storage_agent_client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMOTE_AGENT_TOKEN", "test-token")
    monkeypatch.setenv("WORKER_MODE", "storage")
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("BACKEND_URL", "http://127.0.0.1:8002")
    monkeypatch.setenv("PROVIDER_ID", "test_colab_worker")

    # Force a fresh import so WORKER_MODE is read from the env we just set,
    # even if a prior test cached the module under a different mode.
    srv = _import_server_fresh(monkeypatch)
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


def test_storage_mode_info_authenticated(storage_agent_client):
    client, data_dir = storage_agent_client
    headers = {"Authorization": "Bearer test-token"}
    resp = client.get("/info", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "storage"
    assert data["inference_enabled"] is False
    assert os.path.realpath(data["storage_root"]) == os.path.realpath(str(data_dir))


def test_storage_mode_inference_endpoints_return_503(storage_agent_client):
    client, _ = storage_agent_client
    headers = {"Authorization": "Bearer test-token"}
    resp = client.post("/chat/completions", json={"model": "x"}, headers=headers)
    assert resp.status_code == 503
    assert "storage-only" in resp.text.lower()


def test_storage_mode_download_endpoint_return_503(storage_agent_client):
    client, _ = storage_agent_client
    headers = {"Authorization": "Bearer test-token"}
    resp = client.post(
        "/download-model",
        json={"model_id": "x", "url": "http://x"},
        headers=headers,
    )
    assert resp.status_code == 503


def test_storage_mode_setup_returns_503(storage_agent_client):
    client, _ = storage_agent_client
    headers = {"Authorization": "Bearer test-token"}
    resp = client.post("/setup", headers=headers)
    assert resp.status_code == 503


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


def test_resolve_bind_host_insecure_nonloopback_returns_loopback(monkeypatch):
    """ALLOW_INSECURE=1 with HOST=0.0.0.0 clamps to loopback."""
    monkeypatch.setenv("REMOTE_AGENT_ALLOW_INSECURE", "1")
    monkeypatch.delenv("REMOTE_AGENT_TOKEN", raising=False)
    monkeypatch.setenv("HOST", "0.0.0.0")
    srv = _import_server_fresh(monkeypatch)
    assert srv._resolve_bind_host() == "127.0.0.1"


def test_resolve_bind_host_insecure_loopback_returns_loopback(monkeypatch):
    """ALLOW_INSECURE=1 with HOST=127.0.0.1 returns 127.0.0.1 (unchanged)."""
    monkeypatch.setenv("REMOTE_AGENT_ALLOW_INSECURE", "1")
    monkeypatch.delenv("REMOTE_AGENT_TOKEN", raising=False)
    monkeypatch.setenv("HOST", "127.0.0.1")
    srv = _import_server_fresh(monkeypatch)
    assert srv._resolve_bind_host() == "127.0.0.1"


def test_resolve_bind_host_secure_returns_requested(monkeypatch):
    """With a token (secure) and HOST=0.0.0.0, bind host is returned unchanged."""
    monkeypatch.setenv("REMOTE_AGENT_TOKEN", "test-token")
    monkeypatch.delenv("REMOTE_AGENT_ALLOW_INSECURE", raising=False)
    monkeypatch.setenv("HOST", "0.0.0.0")
    srv = _import_server_fresh(monkeypatch)
    assert srv._resolve_bind_host() == "0.0.0.0"


def test_resolve_bind_host_empty_host_insecure_returns_loopback(monkeypatch):
    """Empty HOST treated as wildcard; insecure clamps to loopback."""
    monkeypatch.setenv("REMOTE_AGENT_ALLOW_INSECURE", "1")
    monkeypatch.delenv("REMOTE_AGENT_TOKEN", raising=False)
    monkeypatch.setenv("HOST", "")
    srv = _import_server_fresh(monkeypatch)
    assert srv._resolve_bind_host() == "127.0.0.1"


def test_warn_insecure_bind_logs_warning(monkeypatch, caplog):
    """When ALLOW_INSECURE=1 and HOST=0.0.0.0, _warn_insecure_bind logs a
    warning mentioning NO authentication and the resolved bind host."""
    monkeypatch.setenv("REMOTE_AGENT_ALLOW_INSECURE", "1")
    monkeypatch.delenv("REMOTE_AGENT_TOKEN", raising=False)
    monkeypatch.setenv("HOST", "0.0.0.0")
    srv = _import_server_fresh(monkeypatch)

    with caplog.at_level("WARNING", logger="server"):
        srv._warn_insecure_bind()

    joined = caplog.text
    assert "NO authentication" in joined, (
        f"insecure-bind warning does not say NO authentication: {joined!r}"
    )
    assert "binding '127.0.0.1'" in joined, (
        f"insecure-bind warning does not report loopback binding: {joined!r}"
    )
