"""Tests for services/model_availability_service.py"""

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from core.entities import Provider
from services.model_availability_service import (
    AvailabilityResult,
    ModelAvailabilityService,
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


@pytest.fixture(name="service")
def service_fixture(session):
    return ModelAvailabilityService(session)


@pytest.fixture(name="provider_in_db")
def provider_in_db_fixture(session):
    """Create a provider in the test database."""
    provider = Provider(
        id="test-provider",
        type="modal",
        enabled=True,
        priority=1,
        credentials={},
        config={}
    )
    session.add(provider)
    session.commit()
    return provider


class TestAvailabilityResult:
    def test_default_values(self):
        result = AvailabilityResult()
        assert result.valid is False
        assert result.eligible_providers == []
        assert result.missing_models == {}
        assert result.global_missing == {}
        assert result.can_trigger_download is False
        assert result.required_models == {}


class TestCheckAvailabilityNoProviders:
    def test_no_providers_returns_invalid(self, service):
        result = service.check_availability({"checkpoints": ["model.safetensors"]})
        assert result.valid is False
        assert result.eligible_providers == []

    def test_no_models_required_no_providers_returns_invalid(self, service):
        result = service.check_availability({})
        assert result.valid is False


class TestCheckAvailabilityWithProviders:
    def test_no_models_required_with_provider(self, service, provider_in_db):
        result = service.check_availability({})
        assert result.valid is True
        assert "test-provider" in result.eligible_providers

    def test_model_required_not_installed(self, service, provider_in_db):
        result = service.check_availability({"checkpoints": ["missing.safetensors"]})
        assert result.valid is False
        assert result.eligible_providers == []


class TestGetEligibleProviders:
    def test_no_providers_returns_empty(self, service):
        providers = service.get_providers_with_models({"checkpoints": ["model.safetensors"]})
        assert providers == []

    def test_with_provider_no_models_required(self, service, provider_in_db):
        providers = service.get_providers_with_models({})
        assert "test-provider" in providers

    def test_with_provider_model_missing(self, service, provider_in_db):
        providers = service.get_providers_with_models({"checkpoints": ["missing.safetensors"]})
        assert providers == []


class TestGetMissingModelsForProvider:
    def test_no_models_required_returns_empty(self, service, provider_in_db):
        missing = service.get_missing_models_for_provider("test-provider", {})
        assert missing == {}

    def test_model_missing(self, service, provider_in_db):
        missing = service.get_missing_models_for_provider(
            "test-provider", {"checkpoints": ["missing.safetensors"]}
        )
        assert isinstance(missing, dict)


class TestCJKAndOriginalFilenameAvailability:
    def test_cjk_nfc_nfd_and_original_filename_matching(self, service, provider_in_db, session):
        import unicodedata
        from core.entities import ModelV2, ModelVersion, ModelFile, ProviderVersionStatus

        # Create a model with NFD storage_filename and an original_filename
        nfd_name = unicodedata.normalize("NFD", "한국어_체크포인트.safetensors")
        nfc_name = unicodedata.normalize("NFC", "한국어_체크포인트.safetensors")

        model = ModelV2(id="cjk-model", name="Korean Model", type="checkpoint", directory="checkpoints")
        session.add(model)
        session.flush()

        version = ModelVersion(id="cjk-ver", model_id=model.id, name="v1.0", is_enabled=True)
        session.add(version)
        session.flush()

        file = ModelFile(
            id=9999,
            version_id=version.id,
            storage_filename=nfd_name,
            original_filename="Original_Korean_Name.safetensors",
            size_bytes=1024,
        )
        session.add(file)
        session.flush()

        status = ProviderVersionStatus(
            provider_id="test-provider",
            file_id=file.id,
            status="ready",
        )
        session.add(status)
        session.commit()

        # 1. Lookup with NFC name should find NFD file and mark provider eligible
        avail_nfc = service.check_availability({"checkpoints": [nfc_name]})
        assert avail_nfc.valid is True
        assert "test-provider" in avail_nfc.eligible_providers

        # 2. Lookup with original_filename should find file and mark provider eligible
        avail_orig = service.check_availability({"checkpoints": ["Original_Korean_Name.safetensors"]})
        assert avail_orig.valid is True
        assert "test-provider" in avail_orig.eligible_providers

        # 3. get_available_checkpoint with NFC name should return matching installed name
        matched = service.get_available_checkpoint(preferred=nfc_name)
        assert matched == nfd_name

