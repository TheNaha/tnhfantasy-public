"""Tests for services/provider_service.py"""
import asyncio
import pytest
from unittest.mock import MagicMock, patch
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool
from services.provider_service import ProviderService
from services.load_balancer import LoadBalancer
from core.exceptions import NotFoundError, ProviderError
from core.entities import LoadBalancerState


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

    async def test_delete_provider_cleans_load_balancer_runtime_state(self, service, session, sample_provider_data):
        runtime_state = LoadBalancer.default_runtime_state()

        with runtime_state.lock:
            runtime_state.provider_failures["test-provider"] = 4
            runtime_state.provider_job_counts["test-provider"] = 2

        await service.create_provider(sample_provider_data)
        await service.delete_provider("test-provider")

        with runtime_state.lock:
            assert "test-provider" not in runtime_state.provider_failures
            assert "test-provider" not in runtime_state.provider_job_counts

        state_row = session.get(LoadBalancerState, 1)
        assert state_row is not None
        assert "test-provider" not in (state_row.provider_failures or {})
        assert "test-provider" not in (state_row.provider_job_counts or {})


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


class _DummyExecResult:
    def __init__(self, exit_code: int, stdout: str = "", stderr: str = ""):
        self.exit_code = exit_code
        self.output = (stdout.encode("utf-8"), stderr.encode("utf-8"))


class _DummyContainer:
    status = "running"

    def __init__(self, results):
        self._results = list(results)

    def exec_run(self, cmd, stream=False, demux=True):
        if not self._results:
            return _DummyExecResult(0, "no-op")
        return self._results.pop(0)


class _DummyContainersClient:
    def __init__(self, container):
        self._container = container

    def get(self, _name):
        return self._container


class _DummyContainerManager:
    def __init__(self, provider_id: str, container):
        self.running_containers = {provider_id: container}
        self.client = MagicMock()
        self.client.containers = _DummyContainersClient(container)


class TestProviderServiceDeploy:
    async def test_modal_deploy_updates_state(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)

        container = _DummyContainer([_DummyExecResult(0, "modal deploy ok")])
        container_manager = _DummyContainerManager("test-provider", container)

        result = await service.deploy_provider_app("test-provider", container_manager)
        assert result["status"] == "success"
        assert result["provider_type"] == "modal"

        provider = await service.get_provider("test-provider")
        deploy_state = (provider.config or {}).get("deploy_state", {})
        assert deploy_state.get("status") == "succeeded"

    async def test_beam_deploy_resume_uses_completed_steps_checkpoint(self, service):
        provider_data = {
            "id": "beam-provider",
            "type": "beam",
            "enabled": True,
            "priority": 1,
            "credentials": {},
            "config": {},
        }
        await service.create_provider(provider_data)

        failing_container = _DummyContainer([
            _DummyExecResult(0, "gpu deployed"),
            _DummyExecResult(1, "storage deploy failed"),
        ])
        failing_manager = _DummyContainerManager("beam-provider", failing_container)

        with pytest.raises(ProviderError):
            await service.deploy_provider_app("beam-provider", failing_manager)

        provider = await service.get_provider("beam-provider")
        failed_state = (provider.config or {}).get("deploy_state", {})
        assert failed_state.get("status") == "failed"
        assert failed_state.get("completed_steps") == ["comfy_gpu"]

        resumed_container = _DummyContainer([_DummyExecResult(0, "storage deployed")])
        resumed_manager = _DummyContainerManager("beam-provider", resumed_container)

        result = await service.deploy_provider_app("beam-provider", resumed_manager)
        assert result["status"] == "success"
        deployments = result.get("deployments", [])
        skipped = [step for step in deployments if step.get("name") == "comfy_gpu" and step.get("skipped")]
        assert skipped

    async def test_deploy_returns_already_running_when_in_flight(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)
        container = _DummyContainer([_DummyExecResult(0, "modal deploy ok")])
        container_manager = _DummyContainerManager("test-provider", container)

        with patch("services.provider_service.is_in_flight", return_value=True):
            result = await service.deploy_provider_app("test-provider", container_manager)

        assert result["status"] == "already_running"


class TestProviderServiceReconciliationState:
    async def test_start_reconciliation_session_sets_started_state(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)

        result = await service.start_reconciliation_session("test-provider")
        assert result["accepted"] is True
        assert result["state"]["status"] == "started"

    async def test_start_reconciliation_session_rejects_if_in_progress(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)
        first = await service.start_reconciliation_session("test-provider")
        assert first["accepted"] is True

        second = await service.start_reconciliation_session("test-provider")
        assert second["accepted"] is False
        assert second["state"]["status"] == "started"

    async def test_upsert_reconciliation_state_sets_finished_at_for_terminal_status(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)
        await service.start_reconciliation_session("test-provider")

        state = await service.upsert_reconciliation_state(
            "test-provider",
            {"status": "completed", "phase": "done", "message": "Sync complete"},
        )

        assert state["status"] == "completed"
        assert state.get("finished_at") is not None
