from sqlmodel import Session
from fastapi.testclient import TestClient

from core.entities import ModelV2, ModelVersion, ModelFile, ProviderVersionStatus


def test_sync_manifest_empty(client: TestClient):
    resp = client.get("/api/v2/models/sync-manifest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "models" in data
    assert "llm_models" in data
    assert "total_models" in data
    assert "pending_downloads" in data


def test_sync_manifest_with_models_and_provider_status(client: TestClient, session: Session):
    # Setup model, version, file
    model = ModelV2(
        name="Test Diffusion Model",
        directory="checkpoints",
        type="checkpoint",
        source="civitai",
        civitai_model_id=999901,
    )
    session.add(model)
    session.commit()
    session.refresh(model)

    version = ModelVersion(
        model_id=model.id,
        name="v1.0",
        civitai_version_id=888801,
        is_enabled=True,
    )
    session.add(version)
    session.commit()
    session.refresh(version)

    file_item = ModelFile(
        version_id=version.id,
        original_filename="model.safetensors",
        storage_filename="test_model_v1.safetensors",
        download_url="https://civitai.com/api/download/models/888801",
        size_kb=2048.0,
        hash_sha256="abcdef123456",
    )
    session.add(file_item)
    session.commit()
    session.refresh(file_item)

    # 1. Query without provider_id
    resp = client.get("/api/v2/models/sync-manifest")
    assert resp.status_code == 200
    data = resp.json()
    matched = [m for m in data["models"] if m["file_id"] == file_item.id]
    assert len(matched) == 1
    item = matched[0]
    assert item["storage_path"] == "models/checkpoints/test_model_v1.safetensors"
    assert item["download_url"] == "https://civitai.com/api/download/models/888801"
    assert item["needs_download"] is True

    # 2. Query with provider_id (no status row -> missing/needs_download)
    resp = client.get("/api/v2/models/sync-manifest?provider_id=test_prov")
    assert resp.status_code == 200
    data = resp.json()
    matched = [m for m in data["models"] if m["file_id"] == file_item.id]
    assert len(matched) == 1
    assert matched[0]["status"] == "missing"
    assert matched[0]["needs_download"] is True

    # 3. Add ProviderVersionStatus marked "ready"
    prov_status = ProviderVersionStatus(
        file_id=file_item.id,
        provider_id="test_prov",
        status="ready",
        storage_path="models/checkpoints/test_model_v1.safetensors",
    )
    session.add(prov_status)
    session.commit()

    # Query with provider_id -> status is "ready", needs_download is False
    resp = client.get("/api/v2/models/sync-manifest?provider_id=test_prov")
    assert resp.status_code == 200
    data = resp.json()
    matched = [m for m in data["models"] if m["file_id"] == file_item.id]
    assert len(matched) == 1
    assert matched[0]["status"] == "ready"
    assert matched[0]["needs_download"] is False
