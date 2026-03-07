"""Tests for services/provider_service.py"""
import asyncio
import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool
from services.provider_service import ProviderService
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
    return ProviderService(session)


@pytest.fixture
def sample_provider_data():
    return {
        "id": "test-provider",
        "type": "modal",
        "enabled": True,
        "priority": 1,
        "credentials": {"api_key": "test-key"},
        "config": {"app_name": "test-app"}
    }


class TestProviderServiceCreate:
    async def test_create_provider(self, service, sample_provider_data):
        provider = await service.create_provider(sample_provider_data)
        assert provider is not None
        assert provider.id == "test-provider"

    async def test_create_provider_enabled(self, service, sample_provider_data):
        provider = await service.create_provider(sample_provider_data)
        assert provider.enabled is True

    async def test_create_provider_type(self, service, sample_provider_data):
        provider = await service.create_provider(sample_provider_data)
        assert provider.type == "modal"

    async def test_create_provider_with_beam_type(self, service):
        data = {
            "id": "beam-provider",
            "type": "beam",
            "enabled": True,
            "priority": 2,
            "credentials": {},
            "config": {}
        }
        provider = await service.create_provider(data)
        assert provider.type == "beam"


class TestProviderServiceGet:
    async def test_get_provider(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)
        provider = await service.get_provider("test-provider")
        assert provider is not None
        assert provider.id == "test-provider"

    async def test_get_nonexistent_raises(self, service):
        with pytest.raises(NotFoundError):
            await service.get_provider("nonexistent")

    async def test_list_providers_empty(self, service):
        providers = await service.list_providers()
        assert providers == []

    async def test_list_providers_returns_all(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)
        providers = await service.list_providers()
        assert len(providers) == 1

    async def test_get_enabled_providers(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)
        enabled = service.get_enabled_providers()
        assert len(enabled) == 1

    async def test_get_enabled_providers_excludes_disabled(self, service):
        data = {
            "id": "disabled-provider",
            "type": "modal",
            "enabled": False,
            "priority": 1,
            "credentials": {},
            "config": {}
        }
        await service.create_provider(data)
        enabled = service.get_enabled_providers()
        assert len(enabled) == 0


class TestProviderServiceUpdate:
    async def test_update_provider_enabled(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)
        updated = await service.update_provider("test-provider", {"enabled": False})
        assert updated.enabled is False

    async def test_update_provider_priority(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)
        updated = await service.update_provider("test-provider", {"priority": 5})
        assert updated.priority == 5

    async def test_update_nonexistent_raises(self, service):
        with pytest.raises(NotFoundError):
            await service.update_provider("nonexistent", {"enabled": False})


class TestProviderServiceDelete:
    async def test_delete_provider(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)
        result = await service.delete_provider("test-provider")
        assert result is True

    async def test_delete_nonexistent_raises(self, service):
        with pytest.raises(NotFoundError):
            await service.delete_provider("nonexistent")

    async def test_provider_not_in_list_after_delete(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)
        await service.delete_provider("test-provider")
        providers = await service.list_providers()
        assert len(providers) == 0


class TestProviderServiceLoadBalancing:
    def test_get_load_balancing_config(self, service):
        config = service.get_load_balancing_config()
        assert config is not None

    async def test_update_load_balancing_config(self, service):
        config = await service.update_load_balancing_config(strategy="round-robin")
        assert config is not None

    def test_get_load_balancer_stats(self, service):
        stats = service.get_load_balancer_stats()
        assert isinstance(stats, dict)

    async def test_get_load_balancer_stats_reflects_created_provider(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)

        stats = service.get_load_balancer_stats()
        provider_ids = {item["id"] for item in stats["provider_stats"]}

        assert "test-provider" in provider_ids


class TestProviderServiceModelCache:
    def test_get_model_cache_empty(self, service):
        cache = service.get_model_cache()
        assert isinstance(cache, dict)

    def test_get_model_cache_for_directory_empty(self, service):
        result = service.get_model_cache_for_directory("checkpoints")
        assert isinstance(result, list)


class TestProviderToDict:
    async def test_provider_to_dict(self, service, sample_provider_data):
        provider = await service.create_provider(sample_provider_data)
        d = service._provider_to_dict(provider)
        assert "id" in d
        assert "type" in d
        assert "enabled" in d
        assert "priority" in d
        assert "credentials" in d
        assert "config" in d
