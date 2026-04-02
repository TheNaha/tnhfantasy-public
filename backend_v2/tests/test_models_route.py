"""Tests for api/routes/models.py (V1 - deprecated but still needs coverage)"""
import pytest
import os
import json
from unittest.mock import patch, MagicMock, AsyncMock, mock_open
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


class TestModelsV1Extended:
    def test_get_model_sync_status(self, models_v1_client):
        models_v1_client.post("/api/models", json={
            "name": "sync.safetensors",
            "directory": "checkpoints"
        })
        response = models_v1_client.get("/api/models/sync-status")
        assert response.status_code == 200
        data = response.json()
        assert data["total_models"] >= 1
        assert "synced" in data

    @patch("api.deps.get_provider_service")
    def test_backfill_statuses(self, mock_get_provider_service, models_v1_client):
        # Mock provider service
        mock_service = AsyncMock()
        mock_provider = MagicMock()
        mock_provider.id = "p1"
        mock_provider.container_config = {"container_name": "c1"}
        mock_service.list_providers.return_value = [mock_provider]
        mock_get_provider_service.return_value = mock_service

        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "test.safetensors", "size": 1024}]},
        )
        with patch("api.routes.models.get_http_client", return_value=mock_http_client):

            # Add a model to match
            models_v1_client.post("/api/models", json={
                "name": "test.safetensors",
                "directory": "checkpoints"
            })

            response = models_v1_client.post("/api/models/backfill-statuses")
            assert response.status_code == 200
            data = response.json()
            assert data["providers_checked"] == 1

    @patch("core.events.event_bus")
    def test_receive_sync_progress(self, mock_event_bus, models_v1_client):
        mock_event_bus.publish = AsyncMock()
        payload = {
            "provider_id": "p1",
            "model_name": "m1",
            "directory": "checkpoints",
            "progress": 50.0,
            "status": "downloading",
            "message": "dl",
            "size_bytes": 100
        }
        response = models_v1_client.post("/api/models/sync-progress", json=payload)
        assert response.status_code == 200
        assert mock_event_bus.publish.call_count >= 1

    @patch("core.events.event_bus")
    def test_receive_sync_progress_completed(self, mock_event_bus, models_v1_client):
        mock_event_bus.publish = AsyncMock()
        # Add model first
        models_v1_client.post("/api/models", json={
            "name": "m1",
            "directory": "checkpoints"
        })

        payload = {
            "provider_id": "p1",
            "model_name": "m1",
            "directory": "checkpoints",
            "progress": 100.0,
            "status": "completed",
            "size_bytes": 100
        }
        response = models_v1_client.post("/api/models/sync-progress", json=payload)
        assert response.status_code == 200
        assert mock_event_bus.publish.call_count >= 1

    def test_receive_batch_sync_progress(self, models_v1_client):
        # Add model first
        models_v1_client.post("/api/models", json={
            "name": "m1",
            "directory": "checkpoints"
        })

        payload = {
            "provider_id": "p1",
            "models": [
                {
                    "model_name": "m1",
                    "directory": "checkpoints",
                    "status": "completed",
                    "size_bytes": 100
                }
            ]
        }
        response = models_v1_client.post("/api/models/sync-progress/batch", json=payload)
        assert response.status_code == 200
        assert response.json()["updated"] == 1

    @patch("api.routes.models.get_http_client")
    def test_parse_model_url_civitai(self, mock_get_client, models_v1_client):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"id": 123}
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_get_client.return_value = mock_client

        response = models_v1_client.post("/api/models/parse", json={"url": "https://civitai.com/models/123/name"})
        assert response.status_code == 200
        assert response.json()["id"] == 123

    @patch("api.routes.models.get_http_client")
    def test_parse_model_url_huggingface(self, mock_get_client, models_v1_client):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"id": "user/repo", "author": "user"}
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_get_client.return_value = mock_client

        response = models_v1_client.post("/api/models/parse", json={"url": "https://huggingface.co/user/repo"})
        assert response.status_code == 200
        assert response.json()["name"] == "repo"

    @patch("api.routes.models.get_http_client")
    def test_search_civitai(self, mock_get_client, models_v1_client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"items": []}
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_get_client.return_value = mock_client

        response = models_v1_client.get("/api/models/search/civitai?query=test")
        assert response.status_code == 200

    @patch("api.routes.models.get_http_client")
    def test_search_huggingface(self, mock_get_client, models_v1_client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"id": "user/repo"}]
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_get_client.return_value = mock_client

        response = models_v1_client.get("/api/models/search/huggingface?query=test")
        assert response.status_code == 200

    @patch("os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.exists")
    @patch("api.routes.models.get_http_client")
    def test_get_model_preview_image(self, mock_get_client, mock_exists, mock_open_file, mock_makedirs, models_v1_client):
        # Case 1: Cached
        mock_exists.return_value = True
        mock_open_file.return_value.__enter__.return_value.read.return_value = b"image"

        response = models_v1_client.get("/api/models/preview-image?model_id=123")
        assert response.status_code == 200
        assert response.content == b"image"

    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.exists")
    @patch("api.routes.models.get_http_client")
    def test_get_model_preview_image_fetch(self, mock_get_client, mock_exists, mock_open_file, models_v1_client):
        # Case 2: Fetch
        mock_exists.return_value = False

        # Mock CivitAI API response
        mock_api_resp = MagicMock()
        mock_api_resp.json.return_value = {
            "modelVersions": [{
                "id": 456,
                "images": [{"url": "http://img", "type": "image"}]
            }]
        }
        mock_api_resp.raise_for_status.return_value = None

        # Mock Image response
        mock_img_resp = MagicMock()
        mock_img_resp.content = b"fetched_image"
        mock_img_resp.headers = {"Content-Type": "image/jpeg"}
        mock_img_resp.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=[mock_api_resp, mock_img_resp])
        mock_get_client.return_value = mock_client

        with patch("os.makedirs"):
            response = models_v1_client.get("/api/models/preview-image?model_id=123")
            assert response.status_code == 200
            assert response.content == b"fetched_image"
