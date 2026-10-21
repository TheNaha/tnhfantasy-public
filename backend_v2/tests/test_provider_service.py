"""Tests for services/provider_service.py"""
from unittest.mock import patch

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from core.entities import LoadBalancerState, Provider
from core.exceptions import NotFoundError
from services.provider_service import ProviderService


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
        from services.load_balancer import get_global_runtime_state

        runtime_state = get_global_runtime_state()

        runtime_state.provider_failures["test-provider"] = 4
        runtime_state.provider_job_counts["test-provider"] = 2

        await service.create_provider(sample_provider_data)
        await service.delete_provider("test-provider")

        assert "test-provider" not in runtime_state.provider_failures
        assert "test-provider" not in runtime_state.provider_job_counts

        state_row = session.get(LoadBalancerState, 1)
        assert state_row is not None
        assert "test-provider" not in (state_row.provider_failures or {})
        assert "test-provider" not in (state_row.provider_job_counts or {})

    async def test_delete_provider_keeps_job_history(self, service, session, sample_provider_data):
        """A provider that has run a job must still be deletable.

        `jobs.provider_id` is a plain column with a NO ACTION foreign key to
        providers, so deleting such a provider raised ForeignKeyViolationError and
        the route returned 500. Job history is worth keeping, so the reference is
        cleared instead of cascading the rows away.
        """
        from core.entities import Job, JobStatus

        await service.create_provider(sample_provider_data)
        job = Job(task_type="image", status=JobStatus.COMPLETED, provider_id="test-provider")
        session.add(job)
        session.commit()

        assert await service.delete_provider("test-provider") is True

        session.refresh(job)
        assert job.provider_id is None
        assert session.get(Job, job.id) is not None


class TestProviderServiceWorkerToken:
    """The external-worker token, and making the mode reachable at all.

    `/ws/worker/{provider_id}` authenticates against `config.worker_token`, and
    nothing in the repo produced that key, so no worker could ever register and
    the `external_worker` runtime mode was unreachable.
    """

    async def test_mint_returns_a_token_and_stores_it(self, service, session, sample_provider_data):
        await service.create_provider(sample_provider_data)
        token = await service.mint_worker_token("test-provider")

        assert len(token) >= 32
        assert session.get(Provider, "test-provider").config["worker_token"] == token

    async def test_mint_rotates_the_previous_token(self, service, session, sample_provider_data):
        await service.create_provider(sample_provider_data)
        first = await service.mint_worker_token("test-provider")
        second = await service.mint_worker_token("test-provider")

        assert first != second
        assert session.get(Provider, "test-provider").config["worker_token"] == second

    async def test_revoke_removes_the_token(self, service, session, sample_provider_data):
        """Revoking used to report success and leave the credential live.

        `_normalize_provider_for_storage` merges the payload *over* the existing
        config, so a payload without `worker_token` put the stored token straight
        back. The base config is now derived from the normalised existing config
        and written back verbatim.
        """
        await service.create_provider(sample_provider_data)
        await service.mint_worker_token("test-provider")

        assert await service.revoke_worker_token("test-provider") is True
        assert "worker_token" not in (session.get(Provider, "test-provider").config or {})

    async def test_revoke_is_idempotent(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)
        await service.mint_worker_token("test-provider")

        assert await service.revoke_worker_token("test-provider") is True
        assert await service.revoke_worker_token("test-provider") is False

    async def test_revoke_on_a_provider_with_no_token_is_false(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)
        assert await service.revoke_worker_token("test-provider") is False

    async def test_token_is_never_returned_in_the_provider_payload(self, service, session, sample_provider_data):
        await service.create_provider(sample_provider_data)
        token = await service.mint_worker_token("test-provider")

        payload = service._provider_to_dict(session.get(Provider, "test-provider"))
        assert payload["has_worker_token"] is True
        assert token not in str(payload)

    async def test_rotate_preserves_the_rest_of_the_config(self, service, session, sample_provider_data):
        """Writing the token must not clobber the composed runtime/deploy config."""
        await service.create_provider(sample_provider_data)
        before = dict(session.get(Provider, "test-provider").config or {})

        await service.mint_worker_token("test-provider")
        after = dict(session.get(Provider, "test-provider").config or {})

        assert "worker_token" not in before
        assert set(before) <= set(after)


class TestProviderServiceLoadBalancing:
    def test_get_load_balancing_config(self, service):
        config = service.get_load_balancing_config()
        assert config is not None

    async def test_update_load_balancing_config(self, service):
        config = await service.update_load_balancing_config(strategy="round-robin")
        assert config is not None

    async def test_get_load_balancer_stats(self, service):
        stats = await service.get_load_balancer_stats()
        assert isinstance(stats, dict)

    async def test_get_load_balancer_stats_reflects_created_provider(self, service, sample_provider_data):
        await service.create_provider(sample_provider_data)

        stats = await service.get_load_balancer_stats()
        provider_ids = {item["id"] for item in stats["provider_stats"]}

        assert "test-provider" in provider_ids


class TestProviderServiceModelCache:
    def test_the_model_cache_accessors_are_gone(self, service):
        """`get_model_cache` / `get_model_cache_for_directory` existed only to
        serve `GET /api/v2/providers/model-cache`, which was one of four
        implementations of the same 1.5 MB dump and had no caller."""
        assert not hasattr(service, "get_model_cache")
        assert not hasattr(service, "get_model_cache_for_directory")


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

    async def test_legacy_engine_fields_reach_the_frontend_through_deploy_config(
        self, service, sample_provider_data
    ):
        """Engine settings set on the provider row must survive onto the dict.

        `build_provider_record` emits `deploy_config`, never `config`, so a row
        written with `config={"comfy_url": ...}` reaches the browser under that
        key only because `LEGACY_DEPLOY_CONFIG_FIELDS` backfills it. The Providers
        page's Runtime tab read `provider.config?.comfy_url` — a key that is not
        emitted — so the row was blank for every direct_url / remote_comfy
        provider no matter what was configured.
        """
        payload = dict(sample_provider_data)
        payload["config"] = {"comfy_url": "http://gpu-box:8188", "app_name": "comfy-modal-stack"}
        provider = await service.create_provider(payload)

        d = service._provider_to_dict(provider)
        assert d["deploy_config"]["comfy_url"] == "http://gpu-box:8188"
        assert d["deploy_config"]["app_name"] == "comfy-modal-stack"
        # The alias is an alias, not a second field: the row's own config is not
        # duplicated onto the wire, so there is still exactly one place to read.
        assert "config" not in d



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

        state = service.upsert_reconciliation_state(
            "test-provider",
            {"status": "completed", "phase": "done", "message": "Sync complete"},
        )

        assert state["status"] == "completed"
        assert state.get("finished_at") is not None

    async def test_upsert_reconciliation_state_is_not_a_coroutine_function(self, service):
        """Synchronous since 2026-10-03 — one repository read, one merge, one
        commit, no suspension. `async def` callers reach it via
        `asyncio.to_thread`; an `async def` here would put that commit back on
        the event loop for every worker heartbeat."""
        import inspect

        assert not inspect.iscoroutinefunction(service.upsert_reconciliation_state)
