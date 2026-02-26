"""Tests for services/model_service_v2.py"""
import pytest
from unittest.mock import patch, AsyncMock
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from services.model_service_v2 import ModelServiceV2
from core.exceptions import NotFoundError


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture(name="service")
def service_fixture(session):
    return ModelServiceV2(session)


@pytest.fixture
def civitai_data():
    return {
        "id": 12345,
        "name": "Test Checkpoint",
        "type": "Checkpoint",
        "nsfw": False,
        "description": "Test model",
        "creator": {"username": "testuser"},
        "stats": {"downloadCount": 100},
        "tags": ["anime"],
        "modelVersions": [
            {
                "id": 67890,
                "name": "v1.0",
                "baseModel": "SD 1.5",
                "files": [
                    {
                        "name": "model.safetensors",
                        "sizeKB": 2048000,
                        "type": "Model",
                        "metadata": {"format": "SafeTensor", "size": "pruned", "fp": "fp16"},
                        "pickleScanMessage": "",
                        "virusScanMessage": "",
                        "scannedAt": None,
                        "hashes": {},
                        "downloadUrl": "https://civitai.com/api/download/models/67890",
                        "primary": True
                    }
                ],
                "images": []
            }
        ]
    }


class TestModelServiceV2AddModel:
    async def test_add_model_from_civitai(self, service, civitai_data):
        with patch.object(service, "trigger_download_to_providers", new=AsyncMock()):
            with patch.object(service, "check_and_trigger_dependencies", new=AsyncMock()):
                result = await service.add_model_from_civitai(civitai_data, [67890])
        assert result is not None
        assert result["name"] == "Test Checkpoint"

    async def test_add_existing_model_adds_versions(self, service, civitai_data):
        """Adding a model that already exists should add new versions."""
        with patch.object(service, "trigger_download_to_providers", new=AsyncMock()):
            with patch.object(service, "check_and_trigger_dependencies", new=AsyncMock()):
                # First add
                first_result = await service.add_model_from_civitai(civitai_data, [67890])
        
        # Now add with a different version (just to test the existing model path)
        civitai_data_v2 = dict(civitai_data)
        civitai_data_v2["modelVersions"] = civitai_data["modelVersions"] + [
            {
                "id": 67891,
                "name": "v2.0",
                "baseModel": "SD 1.5",
                "files": [
                    {
                        "name": "model_v2.safetensors",
                        "sizeKB": 3000000,
                        "type": "Model",
                        "metadata": {},
                        "pickleScanMessage": "",
                        "virusScanMessage": "",
                        "scannedAt": None,
                        "hashes": {},
                        "downloadUrl": "https://civitai.com/api/download/models/67891",
                        "primary": True
                    }
                ],
                "images": []
            }
        ]
        
        with patch.object(service, "trigger_download_to_providers", new=AsyncMock()):
            with patch.object(service, "check_and_trigger_dependencies", new=AsyncMock()):
                second_result = await service.add_model_from_civitai(civitai_data_v2, [67891])
        
        assert "added_versions" in second_result


class TestModelServiceV2GetModel:
    async def test_get_model(self, service, civitai_data):
        with patch.object(service, "trigger_download_to_providers", new=AsyncMock()):
            with patch.object(service, "check_and_trigger_dependencies", new=AsyncMock()):
                created = await service.add_model_from_civitai(civitai_data, [67890])
        result = await service.get_model(created["id"])
        assert result["id"] == created["id"]

    async def test_get_nonexistent_model_raises(self, service):
        with pytest.raises(NotFoundError):
            await service.get_model(99999)

    async def test_list_models_empty(self, service):
        result = await service.list_models()
        assert result == []

    async def test_list_models(self, service, civitai_data):
        with patch.object(service, "trigger_download_to_providers", new=AsyncMock()):
            with patch.object(service, "check_and_trigger_dependencies", new=AsyncMock()):
                await service.add_model_from_civitai(civitai_data, [67890])
        result = await service.list_models()
        assert len(result) == 1

    async def test_list_models_by_directory(self, service, civitai_data):
        with patch.object(service, "trigger_download_to_providers", new=AsyncMock()):
            with patch.object(service, "check_and_trigger_dependencies", new=AsyncMock()):
                await service.add_model_from_civitai(civitai_data, [67890])
        result = await service.list_models_by_directory("checkpoints")
        assert len(result) >= 1

    async def test_get_models_grouped(self, service, civitai_data):
        with patch.object(service, "trigger_download_to_providers", new=AsyncMock()):
            with patch.object(service, "check_and_trigger_dependencies", new=AsyncMock()):
                await service.add_model_from_civitai(civitai_data, [67890])
        result = await service.get_models_grouped()
        assert "checkpoints" in result


class TestModelServiceV2DeleteModel:
    async def test_delete_model(self, service, civitai_data):
        with patch.object(service, "trigger_download_to_providers", new=AsyncMock()):
            with patch.object(service, "check_and_trigger_dependencies", new=AsyncMock()):
                created = await service.add_model_from_civitai(civitai_data, [67890])
        with patch.object(service, "trigger_delete_from_providers", new=AsyncMock(return_value={})):
            result = await service.delete_model(created["id"])
        assert result is True

    async def test_delete_nonexistent_raises(self, service):
        with pytest.raises(NotFoundError):
            await service.delete_model(99999)


class TestModelServiceV2Versions:
    async def test_get_versions(self, service, civitai_data):
        with patch.object(service, "trigger_download_to_providers", new=AsyncMock()):
            with patch.object(service, "check_and_trigger_dependencies", new=AsyncMock()):
                created = await service.add_model_from_civitai(civitai_data, [67890])
        versions = await service.get_versions(created["id"])
        assert len(versions) == 1

    async def test_set_default_version(self, service, civitai_data):
        with patch.object(service, "trigger_download_to_providers", new=AsyncMock()):
            with patch.object(service, "check_and_trigger_dependencies", new=AsyncMock()):
                created = await service.add_model_from_civitai(civitai_data, [67890])
        version_id = created["versions"][0]["id"]
        result = await service.set_default_version(created["id"], version_id)
        assert result is True


class TestModelServiceV2Cache:
    async def test_get_full_cache(self, service, civitai_data):
        with patch.object(service, "trigger_download_to_providers", new=AsyncMock()):
            with patch.object(service, "check_and_trigger_dependencies", new=AsyncMock()):
                await service.add_model_from_civitai(civitai_data, [67890])
        cache = service.get_full_cache()
        assert isinstance(cache, dict)

    async def test_get_pending_downloads(self, service):
        result = service.get_pending_downloads("modal-primary")
        assert isinstance(result, list)


class TestModelServiceV2Search:
    async def test_search_by_tag(self, service, civitai_data):
        with patch.object(service, "trigger_download_to_providers", new=AsyncMock()):
            with patch.object(service, "check_and_trigger_dependencies", new=AsyncMock()):
                await service.add_model_from_civitai(civitai_data, [67890])
        results = await service.search_by_tag("anime")
        assert len(results) >= 1

    async def test_search_by_tag_not_found(self, service):
        results = await service.search_by_tag("nonexistent_tag_xyz")
        assert results == []
