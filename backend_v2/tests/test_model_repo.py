"""Tests for infrastructure/repositories/model_repo.py"""
import pytest
from datetime import datetime
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool
from infrastructure.repositories.model_repo import ModelRepository
from core.entities import Model, ModelStatus


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


@pytest.fixture(name="repo")
def repo_fixture(session):
    return ModelRepository(session)


@pytest.fixture(name="sample_model_data")
def sample_model_data_fixture():
    return {
        "name": "test-model.safetensors",
        "directory": "checkpoints",
        "url": "https://example.com/model.safetensors",
        "source": "civitai",
    }


class TestModelRepositoryCreate:
    def test_create_model(self, repo, sample_model_data):
        model = repo.create(sample_model_data)
        assert model.id is not None
        assert model.name == "test-model.safetensors"
        assert model.directory == "checkpoints"

    def test_create_model_with_url(self, repo, sample_model_data):
        model = repo.create(sample_model_data)
        assert model.url == "https://example.com/model.safetensors"

    def test_create_model_source(self, repo, sample_model_data):
        model = repo.create(sample_model_data)
        assert model.source == "civitai"

    def test_create_model_default_metadata(self, repo, sample_model_data):
        model = repo.create(sample_model_data)
        assert model.metadata_ == {}

    def test_create_model_default_provider_statuses(self, repo, sample_model_data):
        model = repo.create(sample_model_data)
        assert model.provider_statuses == {}


class TestModelRepositoryGet:
    def test_get_by_id(self, repo, sample_model_data):
        created = repo.create(sample_model_data)
        fetched = repo.get(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    def test_get_nonexistent_returns_none(self, repo):
        assert repo.get(99999) is None

    def test_get_by_name_and_directory(self, repo, sample_model_data):
        repo.create(sample_model_data)
        model = repo.get_by_name_and_directory("test-model.safetensors", "checkpoints")
        assert model is not None
        assert model.name == "test-model.safetensors"

    def test_get_by_name_and_directory_not_found(self, repo):
        result = repo.get_by_name_and_directory("nonexistent.safetensors", "checkpoints")
        assert result is None

    def test_get_all_returns_list(self, repo, sample_model_data):
        repo.create(sample_model_data)
        models = repo.get_all()
        assert isinstance(models, list)
        assert len(models) >= 1

    def test_get_all_empty(self, repo):
        assert repo.get_all() == []

    def test_get_by_directory(self, repo, sample_model_data):
        repo.create(sample_model_data)
        models = repo.get_by_directory("checkpoints")
        assert len(models) >= 1
        assert all(m.directory == "checkpoints" for m in models)

    def test_get_by_directory_not_found(self, repo):
        assert repo.get_by_directory("loras") == []

    def test_get_by_source(self, repo, sample_model_data):
        repo.create(sample_model_data)
        models = repo.get_by_source("civitai")
        assert len(models) >= 1

    def test_get_by_source_not_found(self, repo):
        assert repo.get_by_source("nonexistent") == []


class TestModelRepositoryUpdate:
    def test_update_field(self, repo, sample_model_data):
        created = repo.create(sample_model_data)
        updated = repo.update(created.id, url="https://new-url.com/model.safetensors")
        assert updated.url == "https://new-url.com/model.safetensors"

    def test_update_nonexistent_returns_none(self, repo):
        result = repo.update(99999, url="https://url.com")
        assert result is None

    def test_update_updates_updated_at(self, repo, sample_model_data):
        created = repo.create(sample_model_data)
        original_time = created.updated_at
        updated = repo.update(created.id, url="https://new.com")
        assert updated.updated_at >= original_time


class TestModelRepositoryProviderStatus:
    def test_update_provider_status(self, repo, sample_model_data):
        model = repo.create(sample_model_data)
        updated = repo.update_provider_status(
            model.id, "modal-primary", ModelStatus.INSTALLED
        )
        assert updated is not None
        assert updated.provider_statuses["modal-primary"]["status"] == "installed"

    def test_update_provider_status_nonexistent(self, repo):
        result = repo.update_provider_status(99999, "modal", ModelStatus.INSTALLED)
        assert result is None

    def test_update_provider_status_with_extra_data(self, repo, sample_model_data):
        model = repo.create(sample_model_data)
        updated = repo.update_provider_status(
            model.id,
            "modal-primary",
            ModelStatus.FAILED,
            extra_data={"error": "timeout"},
        )
        assert updated.provider_statuses["modal-primary"]["error"] == "timeout"

    def test_update_provider_status_multiple_providers(self, repo, sample_model_data):
        model = repo.create(sample_model_data)
        repo.update_provider_status(model.id, "modal-1", ModelStatus.INSTALLED)
        updated = repo.update_provider_status(model.id, "modal-2", ModelStatus.DOWNLOADING)
        assert "modal-1" in updated.provider_statuses
        assert "modal-2" in updated.provider_statuses


class TestModelRepositoryDelete:
    def test_delete_model(self, repo, sample_model_data):
        model = repo.create(sample_model_data)
        result = repo.delete(model.id)
        assert result is True
        assert repo.get(model.id) is None

    def test_delete_nonexistent(self, repo):
        result = repo.delete(99999)
        assert result is False

    def test_delete_by_name_and_directory(self, repo, sample_model_data):
        repo.create(sample_model_data)
        result = repo.delete_by_name_and_directory("test-model.safetensors", "checkpoints")
        assert result is True
        assert repo.get_by_name_and_directory("test-model.safetensors", "checkpoints") is None

    def test_delete_by_name_not_found(self, repo):
        result = repo.delete_by_name_and_directory("nonexistent.safetensors", "checkpoints")
        assert result is False


class TestModelRepositoryUpsert:
    def test_upsert_creates_new(self, repo):
        model = repo.upsert("new-model.safetensors", "checkpoints", source="custom")
        assert model.id is not None
        assert model.name == "new-model.safetensors"

    def test_upsert_updates_existing(self, repo, sample_model_data):
        repo.create(sample_model_data)
        updated = repo.upsert(
            "test-model.safetensors", "checkpoints", url="https://updated.com"
        )
        assert updated.url == "https://updated.com"
        # Should still be same record
        assert len(repo.get_all()) == 1

    def test_upsert_only_one_record(self, repo):
        repo.upsert("model.safetensors", "checkpoints")
        repo.upsert("model.safetensors", "checkpoints")
        models = repo.get_all()
        assert len(models) == 1


class TestModelRepositoryGrouped:
    def test_get_grouped_by_directory(self, repo):
        repo.create({"name": "a.safetensors", "directory": "checkpoints", "source": "custom"})
        repo.create({"name": "b.safetensors", "directory": "loras", "source": "custom"})
        grouped = repo.get_grouped_by_directory()
        assert "checkpoints" in grouped
        assert "loras" in grouped

    def test_grouped_empty(self, repo):
        grouped = repo.get_grouped_by_directory()
        assert grouped == {}

    def test_grouped_multiple_in_directory(self, repo):
        repo.create({"name": "a.safetensors", "directory": "checkpoints", "source": "custom"})
        repo.create({"name": "b.safetensors", "directory": "checkpoints", "source": "civitai"})
        grouped = repo.get_grouped_by_directory()
        assert len(grouped["checkpoints"]) == 2
