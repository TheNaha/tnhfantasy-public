import os
import time
from fastapi.testclient import TestClient

from api.routes.files import _cleanup_expired_inputs_sync
import api.routes.files as files_module


def test_cleanup_expired_inputs_sync(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True)
    monkeypatch.setattr(files_module, "INPUT_DIR", str(input_dir))

    # Create an old mask file (mtime 10 days ago)
    old_file = input_dir / "old_mask.png"
    old_file.write_bytes(b"test1234")
    old_mtime = time.time() - (10 * 86400)
    os.utime(str(old_file), (old_mtime, old_mtime))

    # Create a fresh mask file (mtime now)
    fresh_file = input_dir / "fresh_mask.png"
    fresh_file.write_bytes(b"freshcontent")

    # Run cleanup with 7-day cutoff
    result = _cleanup_expired_inputs_sync(max_age_days=7)

    assert result["removed"] == 1
    assert result["freed_bytes"] == 8
    assert not old_file.exists()
    assert fresh_file.exists()


def test_prompts_import_rejects_oversized_batch(client: TestClient):
    # Payload with more than MAX_BATCH_ITEMS (1000)
    oversized = [{"name": f"P{i}", "text": f"text {i}"} for i in range(1005)]

    resp = client.post("/api/prompts/import", json={"prompts": oversized})
    assert resp.status_code == 400
    data = resp.json()
    assert data.get("code") == "BATCH_TOO_LARGE"
    assert data.get("field") == "prompts"
