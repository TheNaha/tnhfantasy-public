"""Tests for services/provider_service.py"""
import asyncio
import time
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

    async def test_list_providers_does_not_persist_normalization_on_read(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)

        with patch.object(service.repo, "update", wraps=service.repo.update) as mock_update:
            providers = await service.list_providers()

        assert len(providers) == 1
        mock_update.assert_not_called()

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


class TestProviderServiceEnvironment:
    async def test_build_provider_environment_propagates_worker_reconciliation_settings(self, service, sample_provider_data):
        sample_provider_data = dict(sample_provider_data)
        sample_provider_data["runtime_config"] = {
            "worker": {
                "reconciliation_interval_hours": 2,
                "reconciliation_startup_delay_seconds": 45,
                "max_concurrent_downloads": 9,
            }
        }
        provider = await service.create_provider(sample_provider_data)

        env_vars = service.build_provider_environment(provider)

        assert env_vars["RECONCILIATION_INTERVAL_SECONDS"] == "7200"
        assert env_vars["RECONCILIATION_STARTUP_DELAY_SECONDS"] == "45"
        assert env_vars["MAX_CONCURRENT_DOWNLOADS"] == "9"


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
        assert "credential_summary" in d
        assert "runtime_config" in d
        assert "deploy_config" in d
        assert "credentials" not in d


class _DummyExecResult:
    def __init__(self, exit_code: int, stdout: str = "", stderr: str = ""):
        self.exit_code = exit_code
        self.output = (stdout.encode("utf-8"), stderr.encode("utf-8"))


class _DummyContainer:
    status = "running"
    name = "deploy-container"

    def __init__(self, results, delays=None):
        self._results = list(results)
        self._delays = list(delays or [])
        self.commands = []

    def exec_run(self, cmd, stream=False, demux=True):
        self.commands.append(cmd)
        if self._delays:
            delay = self._delays.pop(0)
            if delay > 0:
                time.sleep(delay)
        if not self._results:
            return _DummyExecResult(0, "no-op")
        return self._results.pop(0)

    def stop(self, timeout=2):
        return None

    def remove(self, force=False):
        return None


class _DummyContainersClient:
    def __init__(self, container, *, existing_names=None, listed_containers=None):
        self._container = container
        self._existing_names = set(existing_names or [])
        if container is not None and getattr(container, "name", None):
            self._existing_names.add(container.name)
        self._listed_containers = listed_containers

    def get(self, _name):
        if _name in self._existing_names:
            return self._container
        raise RuntimeError(f"container {_name} not found")

    def list(self, all=True, filters=None):
        if self._listed_containers is not None:
            return list(self._listed_containers)
        if self._container is None:
            return []
        return [self._container]

    def run(self, **_kwargs):
        return self._container


class _DummyContainerManager:
    def __init__(self, provider_id: str, container, *, containers_client=None):
        self.running_containers = {provider_id: container}
        self.client = MagicMock()
        self.client.containers = containers_client or _DummyContainersClient(container)
        self.build_worker_image = MagicMock(return_value=f"comfy-provider-{provider_id}:latest")


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

        resumed_container = _DummyContainer([
            _DummyExecResult(0, "storage deployed"),
            _DummyExecResult(0, "download deployed"),
        ])
        resumed_manager = _DummyContainerManager("beam-provider", resumed_container)

        result = await service.deploy_provider_app("beam-provider", resumed_manager)
        assert result["status"] == "success"
        deployments = result.get("deployments", [])
        skipped = [step for step in deployments if step.get("name") == "comfy_gpu" and step.get("skipped")]
        assert skipped
        assert {step["name"] for step in deployments} == {"comfy_gpu", "comfy_storage", "comfy_download"}

    async def test_beam_deploy_rewrites_legacy_beam_cli(self, service):
        provider_data = {
            "id": "beam-legacy-cli",
            "type": "beam",
            "enabled": True,
            "priority": 1,
            "credentials": {},
            "config": {
                "deploy_config": {
                    "deploy_mode": "managed",
                    "targets": [
                        {
                            "name": "comfy_gpu",
                            "entrypoint": "/app/beam_app.py:comfy_gpu",
                            "command": ["beam", "deploy", "/app/beam_app.py:comfy_gpu"],
                        }
                    ],
                }
            },
        }
        await service.create_provider(provider_data)

        container = _DummyContainer([_DummyExecResult(0, "beam deploy ok")])
        container_manager = _DummyContainerManager("beam-legacy-cli", container)

        result = await service.deploy_provider_app("beam-legacy-cli", container_manager)

        assert result["status"] == "success"
        assert container.commands
        assert container.commands[0][0] == "beta9"

    async def test_deploy_returns_already_running_when_in_flight(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)
        container = _DummyContainer([_DummyExecResult(0, "modal deploy ok")])
        container_manager = _DummyContainerManager("test-provider", container)

        with patch("services.provider_service.is_in_flight", return_value=True):
            result = await service.deploy_provider_app("test-provider", container_manager)

        assert result["status"] == "already_running"

    async def test_deploy_retries_when_attempt_container_is_missing(self, service, sample_provider_data):
        stuck_provider_data = dict(sample_provider_data)
        stuck_provider_data["id"] = "stuck-provider"
        await service.create_provider(stuck_provider_data)
        provider = await service.get_provider("stuck-provider")

        stuck_state = service._build_deploy_state(
            provider_id=provider.id,
            provider_type=provider.type,
            status="deploying",
            attempt_id="179eec65-3a78-4f7f-8c96-4a12572efa5e",
            started_at=service._utcnow_iso(),
            message="Deployment started",
            steps=[],
        )
        service._persist_deploy_state(provider, stuck_state)

        deploy_container = _DummyContainer([_DummyExecResult(0, "modal deploy ok")])
        missing_attempt_client = _DummyContainersClient(
            deploy_container,
            existing_names=set(),
            listed_containers=[],
        )
        container_manager = _DummyContainerManager(
            "stuck-provider",
            deploy_container,
            containers_client=missing_attempt_client,
        )

        result = await service.deploy_provider_app("stuck-provider", container_manager)

        assert result["status"] == "success"
        provider = await service.get_provider("stuck-provider")
        deploy_state = (provider.config or {}).get("deploy_state", {})
        assert deploy_state.get("status") == "succeeded"

    async def test_get_deploy_state_marks_failed_when_attempt_container_is_missing(self, service, sample_provider_data):
        stuck_provider_data = dict(sample_provider_data)
        stuck_provider_data["id"] = "stuck-provider-state"
        await service.create_provider(stuck_provider_data)
        provider = await service.get_provider("stuck-provider-state")

        stuck_state = service._build_deploy_state(
            provider_id=provider.id,
            provider_type=provider.type,
            status="deploying",
            attempt_id="179eec65-3a78-4f7f-8c96-4a12572efa5e",
            started_at=service._utcnow_iso(),
            message="Deployment started",
            steps=[],
        )
        service._persist_deploy_state(provider, stuck_state)

        missing_attempt_client = _DummyContainersClient(
            None,
            existing_names=set(),
            listed_containers=[],
        )
        container_manager = _DummyContainerManager(
            "stuck-provider-state",
            None,
            containers_client=missing_attempt_client,
        )

        with patch("services.container_manager.get_container_manager", return_value=container_manager):
            state = await service.get_provider_deploy_state("stuck-provider-state")

        assert state["status"] == "failed"
        assert "disappeared" in state.get("message", "")

    async def test_deploy_timeout_marks_failed_step(self, service, sample_provider_data):
        timeout_provider_data = dict(sample_provider_data)
        timeout_provider_data["id"] = "timeout-provider"
        await service.create_provider(timeout_provider_data)

        # Keep execution comfortably beyond the configured timeout.
        container = _DummyContainer(
            [_DummyExecResult(0, "modal deploy ok")],
            delays=[1.5],
        )
        container_manager = _DummyContainerManager("timeout-provider", container)

        with patch.dict("os.environ", {"COMFY_PROVIDER_DEPLOY_STEP_TIMEOUT_SECONDS": "1"}, clear=False):
            with pytest.raises(ProviderError, match="deploy failed"):
                await service.deploy_provider_app("timeout-provider", container_manager)

        provider = await service.get_provider("timeout-provider")
        deploy_state = (provider.config or {}).get("deploy_state", {})

        assert deploy_state.get("status") == "failed"
        steps = deploy_state.get("steps") or []
        assert steps
        assert steps[0]["name"] == "modal_app"
        assert steps[0]["success"] is False
        assert steps[0]["exit_code"] == -1
        assert "timed out" in (steps[0].get("output") or "")


class TestProviderServiceReconciliationState:
    async def test_start_reconciliation_session_sets_started_state(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)

        result = await service.start_reconciliation_session("test-provider")
        assert result["accepted"] is True
        assert result["state"]["status"] == "queued"

    async def test_start_reconciliation_session_rejects_if_in_progress(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)
        first = await service.start_reconciliation_session("test-provider")
        assert first["accepted"] is True

        second = await service.start_reconciliation_session("test-provider")
        assert second["accepted"] is False
        assert second["state"]["status"] == "queued"

    async def test_upsert_reconciliation_state_sets_finished_at_for_terminal_status(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)
        await service.start_reconciliation_session("test-provider")

        state = await service.upsert_reconciliation_state(
            "test-provider",
            {"status": "completed", "phase": "done", "message": "Sync complete"},
        )

        assert state["status"] == "completed"
        assert state.get("finished_at") is not None
