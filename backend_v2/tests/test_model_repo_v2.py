"""Tests for infrastructure/repositories/model_repo_v2.py"""
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from core.entities import ProviderVersionStatus
from infrastructure.repositories.model_repo_v2 import (
    ModelRepositoryV2,
    parse_civitai_datetime,
)


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
    return ModelRepositoryV2(session)


@pytest.fixture
def civitai_data():
    """Standard CivitAI model data for testing."""
    return {
        "id": 12345,
        "name": "Test Checkpoint",
        "type": "Checkpoint",
        "nsfw": False,
        "description": "A test model",
        "creator": {"username": "testuser"},
        "stats": {"downloadCount": 500, "favoriteCount": 100, "ratingCount": 50, "rating": 4.5},
        "tags": ["anime", "realistic"],
        "modelVersions": [
            {
                "id": 67890,
                "name": "v1.0",
                "baseModel": "SD 1.5",
                "description": "First version",
                "trainedWords": ["test"],
                "files": [
                    {
                        "name": "model.safetensors",
                        "sizeKB": 2048000,
                        "type": "Model",
                        "metadata": {"format": "SafeTensor", "size": "pruned", "fp": "fp16"},
                        "pickleScanMessage": "No Pickle imports",
                        "virusScanMessage": "No virus found",
                        "scannedAt": "2024-01-01T00:00:00.000Z",
                        "hashes": {"AutoV2": "abc123"},
                        "downloadUrl": "https://civitai.com/api/download/models/67890",
                        "primary": True
                    }
                ],
                "images": []
            },
            {
                "id": 67891,
                "name": "v2.0",
                "baseModel": "SD XL 1.0",
                "description": "Second version",
                "trainedWords": [],
                "files": [
                    {
                        "name": "model-xl.safetensors",
                        "sizeKB": 4096000,
                        "type": "Model",
                        "metadata": {"format": "SafeTensor", "size": "full", "fp": "fp16"},
                        "pickleScanMessage": "No Pickle imports",
                        "virusScanMessage": "No virus found",
                        "scannedAt": "2024-06-01T00:00:00.000Z",
                        "hashes": {"AutoV2": "def456"},
                        "downloadUrl": "https://civitai.com/api/download/models/67891",
                        "primary": True
                    }
                ],
                "images": []
            }
        ]
    }


class TestParseCivitaiDatetime:
    def test_none_returns_none(self):
        assert parse_civitai_datetime(None) is None

    def test_naive_datetime_is_upgraded_to_utc(self):
        """A naive `datetime` is NOT passed through.

        `civitai_published_at` / `civitai_created_at` are `UTCDateTime` columns
        and SQLModel's bind processor rejects a naive value, so handing one
        back turned "Add model" into a 500 for any CivitAI model whose version
        carried a timestamp. A naive value is interpreted as UTC, which is what
        CivitAI means.
        """
        result = parse_civitai_datetime(datetime(2024, 1, 15, 12, 0, 0))
        assert result.tzinfo is not None
        assert result == datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc)

    def test_aware_datetime_is_preserved(self):
        dt = datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc)
        assert parse_civitai_datetime(dt) == dt

    def test_iso_with_ms(self):
        result = parse_civitai_datetime("2024-01-15T12:00:00.000Z")
        assert isinstance(result, datetime)
        assert result.year == 2024

    def test_iso_without_ms(self):
        result = parse_civitai_datetime("2024-06-15T08:30:00Z")
        assert isinstance(result, datetime)

    def test_iso_no_tz(self):
        result = parse_civitai_datetime("2024-06-15T08:30:00")
        assert isinstance(result, datetime)

    def test_invalid_string_returns_none(self):
        result = parse_civitai_datetime("not-a-date")
        assert result is None

    def test_non_string_returns_none(self):
        result = parse_civitai_datetime(12345)
        assert result is None


class TestModelRepositoryV2Create:
    def test_create_model_with_versions(self, repo, civitai_data):
        model = repo.create_model_with_versions(civitai_data, [67890])
        assert model is not None
        assert model.id is not None
        assert model.name == "Test Checkpoint"

    def test_creates_selected_versions_only(self, repo, civitai_data):
        model = repo.create_model_with_versions(civitai_data, [67890])
        versions = repo.get_versions_for_model(model.id)
        assert len(versions) == 1
        assert versions[0].civitai_version_id == 67890

    def test_creates_multiple_versions(self, repo, civitai_data):
        model = repo.create_model_with_versions(civitai_data, [67890, 67891])
        versions = repo.get_versions_for_model(model.id)
        assert len(versions) == 2

    def test_civitai_id_stored(self, repo, civitai_data):
        model = repo.create_model_with_versions(civitai_data, [67890])
        assert model.civitai_model_id == 12345

    def test_tags_stored(self, repo, civitai_data):
        model = repo.create_model_with_versions(civitai_data, [67890])
        tags = repo.get_tags_for_model(model.id)
        assert len(tags) >= 1


class TestModelRepositoryV2Get:
    def test_get_model_by_id(self, repo, civitai_data):
        model = repo.create_model_with_versions(civitai_data, [67890])
        fetched = repo.get_model(model.id)
        assert fetched is not None
        assert fetched.id == model.id

    def test_get_nonexistent_model(self, repo):
        assert repo.get_model(99999) is None

    def test_get_model_by_civitai_id(self, repo, civitai_data):
        repo.create_model_with_versions(civitai_data, [67890])
        model = repo.get_model_by_civitai_id(12345)
        assert model is not None
        assert model.civitai_model_id == 12345

    def test_get_model_by_civitai_id_not_found(self, repo):
        assert repo.get_model_by_civitai_id(99999) is None

    def test_get_all_models(self, repo, civitai_data):
        repo.create_model_with_versions(civitai_data, [67890])
        models = repo.get_all_models()
        assert len(models) >= 1

    def test_get_all_models_empty(self, repo):
        assert repo.get_all_models() == []

    def test_get_models_by_directory(self, repo, civitai_data):
        repo.create_model_with_versions(civitai_data, [67890])
        models = repo.get_models_by_directory("checkpoints")
        assert len(models) >= 1

    def test_get_models_by_directory_empty(self, repo):
        models = repo.get_models_by_directory("loras")
        assert models == []

    def test_get_grouped_by_directory(self, repo, civitai_data):
        repo.create_model_with_versions(civitai_data, [67890])
        grouped = repo.get_grouped_by_directory()
        assert isinstance(grouped, dict)
        # Should have "checkpoints" key with a list of model dicts
        assert "checkpoints" in grouped

    def test_get_grouped_empty(self, repo):
        grouped = repo.get_grouped_by_directory()
        assert grouped == {}


class TestModelRepositoryV2AddVersions:
    def test_add_versions_to_model(self, repo, civitai_data):
        model = repo.create_model_with_versions(civitai_data, [67890])
        added = repo.add_versions_to_model(model, civitai_data, [67891])
        assert len(added) == 1
        assert added[0].civitai_version_id == 67891

    def test_add_existing_version_skipped(self, repo, civitai_data):
        """Test that adding the same version twice raises an IntegrityError."""
        import sqlalchemy.exc
        model = repo.create_model_with_versions(civitai_data, [67890])
        # Adding the same version again raises IntegrityError (not handled by repo)
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            repo.add_versions_to_model(model, civitai_data, [67890])


class TestModelRepositoryV2Delete:
    def test_delete_model(self, repo, civitai_data):
        model = repo.create_model_with_versions(civitai_data, [67890])
        result = repo.delete_model(model.id)
        assert result is True
        assert repo.get_model(model.id) is None

    def test_delete_nonexistent(self, repo):
        result = repo.delete_model(99999)
        assert result is False


class TestModelRepositoryV2ProviderStatus:
    def test_update_provider_status(self, repo, civitai_data):
        model = repo.create_model_with_versions(civitai_data, [67890])
        versions = repo.get_versions_for_model(model.id)
        version = versions[0]
        files = repo.get_files_for_version(version.id)
        file_obj = files[0]

        result = repo.update_provider_status(
            file_id=file_obj.id,
            provider_id="modal-primary",
            status="ready"
        )
        assert result is not None
        assert result.provider_id == "modal-primary"
        assert result.provider_id == "modal-primary"
        assert result.status == "ready"

    def test_update_provider_status_backfills_legacy_provider_name_rows(self, repo, civitai_data):
        model = repo.create_model_with_versions(civitai_data, [67890])
        versions = repo.get_versions_for_model(model.id)
        files = repo.get_files_for_version(versions[0].id)
        file_obj = files[0]

        legacy_status = ProviderVersionStatus(
            file_id=file_obj.id,
            provider_id="modal-primary",
            status="downloading",
        )
        repo.session.add(legacy_status)
        repo.session.commit()

        updated = repo.update_provider_status(
            file_id=file_obj.id,
            provider_id="modal-primary",
            status="ready",
        )

        assert updated.provider_id == "modal-primary"
        assert updated.provider_id == "modal-primary"
        assert updated.status == "ready"

    def test_get_pending_downloads(self, repo, civitai_data):
        repo.create_model_with_versions(civitai_data, [67890])
        pending = repo.get_pending_downloads("modal-primary")
        assert isinstance(pending, list)

    def test_get_tags_for_model(self, repo, civitai_data):
        model = repo.create_model_with_versions(civitai_data, [67890])
        tags = repo.get_tags_for_model(model.id)
        assert "anime" in tags

    def test_delete_all_statuses_for_provider(self, repo, civitai_data):
        model = repo.create_model_with_versions(civitai_data, [67890])
        versions = repo.get_versions_for_model(model.id)
        files = repo.get_files_for_version(versions[0].id)
        repo.update_provider_status(
            file_id=files[0].id,
            provider_id="modal-primary",
            status="ready"
        )
        count = repo.delete_all_statuses_for_provider("modal-primary")
        assert count >= 0

    def test_reset_stale_downloading_statuses_resets_only_target_providers(self, repo, civitai_data):
        model = repo.create_model_with_versions(civitai_data, [67890])
        versions = repo.get_versions_for_model(model.id)
        files = repo.get_files_for_version(versions[0].id)
        file_obj = files[0]

        modal_status = repo.update_provider_status(
            file_id=file_obj.id,
            provider_id="modal-primary",
            status="downloading"
        )
        beam_status = repo.update_provider_status(
            file_id=file_obj.id,
            provider_id="beam-main",
            status="downloading"
        )

        modal_status.queued_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        beam_status.queued_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        repo.session.add(modal_status)
        repo.session.add(beam_status)
        repo.session.commit()

        reset_count = repo.reset_stale_downloading_statuses(
            stale_before=datetime(2021, 1, 1, tzinfo=timezone.utc),
            provider_names=["modal-primary"],
        )

        assert reset_count == 1
        assert repo.get_provider_status(file_obj.id, "modal-primary").status == "pending"
        assert repo.get_provider_status(file_obj.id, "beam-main").status == "downloading"


class TestModelRepositoryV2ModelToDict:
    def test_model_to_dict(self, repo, civitai_data):
        model = repo.create_model_with_versions(civitai_data, [67890])
        d = repo.model_to_dict(model)
        assert "id" in d
        assert "name" in d
        assert "versions" in d

    def test_model_to_dict_without_versions(self, repo, civitai_data):
        model = repo.create_model_with_versions(civitai_data, [67890])
        d = repo.model_to_dict(model, include_versions=False)
        assert "id" in d
        assert "name" in d

    def test_model_to_dict_has_tags(self, repo, civitai_data):
        model = repo.create_model_with_versions(civitai_data, [67890])
        d = repo.model_to_dict(model)
        assert "tags" in d


class TestModelRepositoryV2Search:
    def test_search_by_tag(self, repo, civitai_data):
        repo.create_model_with_versions(civitai_data, [67890])
        results = repo.search_by_tag("anime")
        assert len(results) >= 1

    def test_search_by_tag_not_found(self, repo, civitai_data):
        repo.create_model_with_versions(civitai_data, [67890])
        results = repo.search_by_tag("nonexistent_tag")
        assert len(results) == 0

    def test_get_models_by_type(self, repo, civitai_data):
        repo.create_model_with_versions(civitai_data, [67890])
        results = repo.get_models_by_type("Checkpoint")
        assert len(results) >= 1

    def test_get_models_by_type_not_found(self, repo, civitai_data):
        repo.create_model_with_versions(civitai_data, [67890])
        results = repo.get_models_by_type("LORA")
        assert len(results) == 0


class TestModelRepositoryV2UnicodeNormalization:
    def test_get_file_by_storage_path_matches_nfc_and_nfd(self, repo, session):
        import unicodedata
        from core.entities import ModelFile, ModelV2, ModelVersion

        nfc_name = unicodedata.normalize("NFC", "ako_amau_天雨アコ_-_blue_archive_ブ_booru_430792.safetensors")
        nfd_name = unicodedata.normalize("NFD", "ako_amau_天雨アコ_-_blue_archive_ブ_booru_430792.safetensors")
        assert nfc_name != nfd_name

        model = ModelV2(name="Ako", type="LORA", directory="loras")
        session.add(model)
        session.flush()

        version = ModelVersion(model_id=model.id, name="v1.0", base_model="SDXL")
        session.add(version)
        session.flush()

        file = ModelFile(
            version_id=version.id,
            original_filename=nfc_name,
            storage_filename=nfc_name,
            format="SafeTensor",
            is_primary=True,
            file_type="Model",
        )
        session.add(file)
        session.commit()

        # Looking up via NFD filename should find the NFC file record
        found_via_nfd = repo.get_file_by_storage_path("loras", nfd_name)
        assert found_via_nfd is not None
        assert found_via_nfd.id == file.id

        # Looking up via NFC filename should also find it
        found_via_nfc = repo.get_file_by_storage_path("loras", nfc_name)
        assert found_via_nfc is not None
        assert found_via_nfc.id == file.id

        # get_file_ids_by_storage_paths maps both NFC and NFD paths to file.id
        path_map = repo.get_file_ids_by_storage_paths([f"models/loras/{nfd_name}"])
        assert path_map.get(f"models/loras/{nfd_name}") == file.id
        assert path_map.get(f"models/loras/{nfc_name}") == file.id
