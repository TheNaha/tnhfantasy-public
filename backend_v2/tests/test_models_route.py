"""Tests for api/routes/models.py (V1 - deprecated but still needs coverage)"""
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from api.routes.models import router as models_v1_router
from api.deps import get_session
import infrastructure.database as _db_module


@pytest.fixture(name="models_v1_engine")
def models_v1_engine_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="models_v1_session")
def models_v1_session_fixture(models_v1_engine):
    with Session(models_v1_engine) as session:
        yield session


@pytest.fixture(name="models_v1_client")
def models_v1_client_fixture(models_v1_session):
    app = FastAPI()
    app.include_router(models_v1_router)

    def get_session_override():
        return models_v1_session

    app.dependency_overrides[get_session] = get_session_override
    app.dependency_overrides[_db_module.get_session] = get_session_override
    return TestClient(app)


class TestModelsV1List:
    def test_list_models_empty(self, models_v1_client):
        response = models_v1_client.get("/api/models")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data

    def test_list_all_models_empty(self, models_v1_client):
        response = models_v1_client.get("/api/models/all")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestModelsV1Add:
    def test_add_model(self, models_v1_client):
        payload = {
            "name": "my-model.safetensors",
            "directory": "checkpoints",
            "url": "https://example.com/model.safetensors",
            "source": "custom",
            "metadata": {}
        }
        response = models_v1_client.post("/api/models", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "my-model.safetensors"

    def test_add_model_minimal(self, models_v1_client):
        payload = {
            "name": "minimal.safetensors",
            "directory": "loras"
        }
        response = models_v1_client.post("/api/models", json=payload)
        assert response.status_code == 200

    def test_add_model_with_metadata(self, models_v1_client):
        payload = {
            "name": "meta-model.safetensors",
            "directory": "checkpoints",
            "metadata": {"author": "test", "version": "1.0"}
        }
        response = models_v1_client.post("/api/models", json=payload)
        assert response.status_code == 200

    def test_list_after_add(self, models_v1_client):
        payload = {
            "name": "added.safetensors",
            "directory": "checkpoints",
            "source": "custom"
        }
        models_v1_client.post("/api/models", json=payload)
        response = models_v1_client.get("/api/models/all")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1


class TestModelsV1ByDirectory:
    def test_list_by_directory(self, models_v1_client):
        # Add a model first
        models_v1_client.post("/api/models", json={
            "name": "dir-test.safetensors",
            "directory": "checkpoints"
        })
        response = models_v1_client.get("/api/models/directory/checkpoints")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_list_by_directory_empty(self, models_v1_client):
        response = models_v1_client.get("/api/models/directory/nonexistent")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0


class TestModelsV1Cache:
    def test_get_model_cache(self, models_v1_client):
        response = models_v1_client.get("/api/models/cache")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data


class TestModelsV1ProviderStatus:
    def test_update_provider_status(self, models_v1_client):
        # Add model first
        models_v1_client.post("/api/models", json={
            "name": "status-test.safetensors",
            "directory": "checkpoints"
        })
        response = models_v1_client.put(
            "/api/models/checkpoints/status-test.safetensors/providers/modal-1/status",
            json={"status": "installed"}
        )
        assert response.status_code == 200

    def test_update_provider_status_invalid(self, models_v1_client):
        # Add model first
        models_v1_client.post("/api/models", json={
            "name": "invalid-status.safetensors",
            "directory": "checkpoints"
        })
        response = models_v1_client.put(
            "/api/models/checkpoints/invalid-status.safetensors/providers/modal-1/status",
            json={"status": "not-a-valid-status"}
        )
        assert response.status_code == 400

    def test_update_downloading_status(self, models_v1_client):
        models_v1_client.post("/api/models", json={
            "name": "dl-model.safetensors",
            "directory": "loras"
        })
        response = models_v1_client.put(
            "/api/models/loras/dl-model.safetensors/providers/modal-1/status",
            json={"status": "downloading"}
        )
        assert response.status_code == 200


class TestModelsV1Delete:
    def test_delete_model(self, models_v1_client):
        models_v1_client.post("/api/models", json={
            "name": "to-delete.safetensors",
            "directory": "checkpoints"
        })
        response = models_v1_client.delete("/api/models/checkpoints/to-delete.safetensors")
        assert response.status_code == 200

    def test_delete_nonexistent(self, models_v1_client):
        response = models_v1_client.delete("/api/models/checkpoints/nonexistent.safetensors")
        assert response.status_code == 404

    def test_list_grouped_models(self, models_v1_client):
        models_v1_client.post("/api/models", json={
            "name": "grouped.safetensors",
            "directory": "vae"
        })
        response = models_v1_client.get("/api/models")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data
        assert "vae" in data["models"]
