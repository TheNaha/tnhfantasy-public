"""Tests for services/model_service.py"""
import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from services.model_service import ModelService
from infrastructure.repositories.model_repo import ModelRepository
from core.entities import Model, ModelStatus
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
    return ModelService(session)


@pytest.fixture
def sample_model(session, service):
    """Create a sample model and return it."""
    async def _create():
        return await service.add_model(
            name="test-model.safetensors",
            directory="checkpoints",
            url="https://example.com/model.safetensors",
            source="civitai"
        )
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(_create())


class TestModelServiceAddModel:
    async def test_add_model(self, service):
        model = await service.add_model(
            name="new-model.safetensors",
            directory="checkpoints"
        )
        assert model is not None
        assert model.name == "new-model.safetensors"

    async def test_add_model_with_url(self, service):
        model = await service.add_model(
            name="url-model.safetensors",
            directory="checkpoints",
            url="https://example.com/model.safetensors"
        )
        assert model.url == "https://example.com/model.safetensors"

    async def test_add_model_with_metadata(self, service):
        model = await service.add_model(
            name="meta-model.safetensors",
            directory="loras",
            metadata={"author": "testuser"}
        )
        assert model.metadata_["author"] == "testuser"

    async def test_add_model_default_source(self, service):
        model = await service.add_model(
            name="default-source.safetensors",
            directory="checkpoints"
        )
        assert model.source == "custom"

    async def test_add_model_upserts_on_duplicate(self, service):
        await service.add_model(name="dup.safetensors", directory="checkpoints")
        await service.add_model(
            name="dup.safetensors",
            directory="checkpoints",
            url="https://new.com"
        )
        models = await service.list_models()
        assert len(models) == 1


class TestModelServiceGetModel:
    async def test_get_model_by_id(self, service):
        created = await service.add_model(
            name="get-test.safetensors", directory="checkpoints"
        )
        model = await service.get_model(created.id)
        assert model.id == created.id

    async def test_get_nonexistent_model_raises(self, service):
        with pytest.raises(NotFoundError):
            await service.get_model(99999)

    async def test_get_model_by_name(self, service):
        await service.add_model(name="by-name.safetensors", directory="checkpoints")
        model = await service.get_model_by_name("by-name.safetensors", "checkpoints")
        assert model is not None
        assert model.name == "by-name.safetensors"

    async def test_get_model_by_name_not_found(self, service):
        result = await service.get_model_by_name("nonexistent.safetensors", "loras")
        assert result is None


class TestModelServiceListModels:
    async def test_list_models_empty(self, service):
        models = await service.list_models()
        assert models == []

    async def test_list_models_returns_all(self, service):
        await service.add_model(name="model1.safetensors", directory="checkpoints")
        await service.add_model(name="model2.safetensors", directory="loras")
        models = await service.list_models()
        assert len(models) == 2

    async def test_list_models_by_directory(self, service):
        await service.add_model(name="ckpt.safetensors", directory="checkpoints")
        await service.add_model(name="lora.safetensors", directory="loras")
        models = await service.list_models_by_directory("checkpoints")
        assert len(models) == 1
        assert models[0]["directory"] == "checkpoints"

    async def test_list_models_by_directory_empty(self, service):
        models = await service.list_models_by_directory("vae")
        assert models == []

    async def test_get_models_grouped(self, service):
        await service.add_model(name="a.safetensors", directory="checkpoints")
        await service.add_model(name="b.safetensors", directory="loras")
        grouped = await service.get_models_grouped()
        assert "checkpoints" in grouped
        assert "loras" in grouped

    async def test_get_full_cache(self, service):
        await service.add_model(name="cache.safetensors", directory="checkpoints")
        cache = service.get_full_cache()
        assert "checkpoints" in cache


class TestModelServiceUpdateProviderStatus:
    async def test_update_provider_status(self, service):
        await service.add_model(name="status-test.safetensors", directory="checkpoints")
        with patch("asyncio.create_task"):
            model = await service.update_provider_status(
                name="status-test.safetensors",
                directory="checkpoints",
                provider_id="modal-primary",
                status=ModelStatus.INSTALLED
            )
        assert model.provider_statuses["modal-primary"]["status"] == "installed"

    async def test_update_provider_status_auto_creates_model(self, service):
        """Test that update_provider_status creates a model if it doesn't exist."""
        with patch("asyncio.create_task"):
            model = await service.update_provider_status(
                name="auto-created.safetensors",
                directory="checkpoints",
                provider_id="modal-primary",
                status=ModelStatus.DOWNLOADING
            )
        assert model is not None

    async def test_update_provider_status_failed_event(self, service):
        await service.add_model(name="failed-model.safetensors", directory="loras")
        with patch("asyncio.create_task"):
            model = await service.update_provider_status(
                name="failed-model.safetensors",
                directory="loras",
                provider_id="modal-primary",
                status=ModelStatus.FAILED,
                extra_data={"error": "disk full"}
            )
        assert model.provider_statuses["modal-primary"]["error"] == "disk full"


class TestModelServiceDeleteModel:
    async def test_delete_model(self, service):
        await service.add_model(name="to-delete.safetensors", directory="checkpoints")
        result = await service.delete_model("to-delete.safetensors", "checkpoints")
        assert result is True

    async def test_delete_nonexistent(self, service):
        result = await service.delete_model("nonexistent.safetensors", "loras")
        assert result is False


class TestModelServiceModelToDict:
    async def test_model_to_dict_format(self, service):
        model = await service.add_model(
            name="dict-test.safetensors",
            directory="checkpoints",
            url="https://example.com"
        )
        d = service._model_to_dict(model)
        assert "id" in d
        assert "name" in d
        assert "directory" in d
        assert "url" in d
        assert "source" in d
        assert "metadata" in d
        assert "provider_statuses" in d
        assert "created_at" in d
        assert "updated_at" in d

    async def test_model_to_dict_timestamps(self, service):
        model = await service.add_model(
            name="ts-test.safetensors",
            directory="checkpoints"
        )
        d = service._model_to_dict(model)
        assert d["created_at"] is not None
        assert d["updated_at"] is not None
