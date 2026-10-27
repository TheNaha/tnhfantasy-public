import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session
from unittest.mock import AsyncMock, MagicMock, patch

from core.entities import ModelFile, ModelV2, ModelVersion, Provider


@pytest.fixture
def test_model_data(session: Session):
    model = ModelV2(
        name="Targeted Test Model",
        directory="checkpoints",
        type="checkpoint",
        source="civitai",
        civitai_model_id=777001,
    )
    session.add(model)
    session.commit()
    session.refresh(model)

    version = ModelVersion(
        model_id=model.id,
        name="v1.0",
        civitai_version_id=777002,
        is_enabled=True,
    )
    session.add(version)
    session.commit()
    session.refresh(version)

    file_record = ModelFile(
        version_id=version.id,
        original_filename="targeted.safetensors",
        storage_filename="targeted_v1.safetensors",
        download_url="https://civitai.com/api/download/models/777002",
        size_kb=1024.0,
    )
    session.add(file_record)
    session.commit()
    session.refresh(file_record)

    provider = Provider(
        id="modal-test-worker",
        name="Modal Test Worker",
        type="modal",
        enabled=True,
    )
    session.add(provider)
    session.commit()
    session.refresh(provider)

    return {
        "model": model,
        "version": version,
        "file": file_record,
        "provider": provider,
    }


def test_download_provider_models_requires_ids(client: TestClient):
    resp = client.post("/api/v2/providers/modal-test-worker/models/download", json={})
    assert resp.status_code == 400 or resp.status_code == 422


def test_download_provider_models_by_file_id(client: TestClient, test_model_data: dict):
    file_id = test_model_data["file"].id
    provider_id = test_model_data["provider"].id

    mock_engine = AsyncMock()
    mock_engine.manages_model_files = True
    mock_engine.download_file = AsyncMock(return_value={"status": "downloaded"})

    mock_runtime = MagicMock()
    mock_runtime.mode = "in_process"

    with patch("services.provider_lifecycle_service.resolve_provider_runtime_async", return_value=mock_runtime), \
         patch("services.engines.engine_factory.get_engine", return_value=mock_engine):
        resp = client.post(
            f"/api/v2/providers/{provider_id}/models/download",
            json={"file_ids": [file_id]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"
        assert data["queued_count"] == 1
        assert data["files"][0]["file_id"] == file_id


def test_download_provider_models_by_model_id(client: TestClient, test_model_data: dict):
    model_id = test_model_data["model"].id
    file_id = test_model_data["file"].id
    provider_id = test_model_data["provider"].id

    mock_engine = AsyncMock()
    mock_engine.manages_model_files = True
    mock_engine.download_file = AsyncMock(return_value={"status": "downloaded"})

    mock_runtime = MagicMock()
    mock_runtime.mode = "in_process"

    with patch("services.provider_lifecycle_service.resolve_provider_runtime_async", return_value=mock_runtime), \
         patch("services.engines.engine_factory.get_engine", return_value=mock_engine):
        resp = client.post(
            f"/api/v2/providers/{provider_id}/models/download",
            json={"model_ids": [model_id]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"
        assert data["queued_count"] == 1
        assert data["files"][0]["file_id"] == file_id
