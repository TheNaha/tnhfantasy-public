"""Tests for the transport-aware provider telemetry + status engine (P1)."""

import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.entities import Job, JobStatus, Provider
from services import provider_telemetry_service as pts
from services.load_balancer import _provider_health_cache, set_poller_health
from services.provider_telemetry_service import ProviderTelemetryService


@pytest.fixture
def service():
    """A fresh telemetry service (no module-singleton leakage between tests)."""
    return ProviderTelemetryService()


def _provider(provider_id="colab-one", ptype="remote_hybrid", config=None):
    return Provider(
        id=provider_id,
        type=ptype,
        enabled=True,
        credentials={"remote_agent_token": "tok"},
        config=config or {},
    )


class TestStatusMachine:
    async def test_first_success_is_online_without_transition_event(self, service):
        """The first observation establishes `online` — nothing flipped, so no event."""
        provider = _provider()
        with patch.object(pts, "can_create_engine", return_value=True), patch.object(
            pts, "get_engine", return_value=AsyncMock(check_health=AsyncMock(return_value={"ready": True}))
        ):
            await service._poll_provider(provider)
        state = service._status[provider.id]
        assert state["status"] == "online"
        assert state["missed_probes"] == 0
        assert state["last_seen_at"] is not None

    async def test_two_misses_flip_offline(self, service):
        """2 consecutive missed probes → offline."""
        provider = _provider()
        failing = AsyncMock(check_health=AsyncMock(side_effect=RuntimeError("conn refused")))
        with patch.object(pts, "can_create_engine", return_value=True), patch.object(
            pts, "get_engine", return_value=failing
        ):
            await service._poll_provider(provider)
            assert service._status[provider.id]["status"] is None  # 1 miss, not yet offline
            await service._poll_provider(provider)
        state = service._status[provider.id]
        assert state["status"] == "offline"
        assert state["missed_probes"] == 2

    async def test_transition_writes_lb_cache_and_emits_event(self, service):
        """Offline and online transitions both hit the LB cache + event bus."""
        provider = _provider()
        failing = AsyncMock(check_health=AsyncMock(side_effect=RuntimeError("down")))
        with patch.object(pts, "can_create_engine", return_value=True), patch.object(
            pts, "get_engine", return_value=failing
        ), patch("services.load_balancer.set_poller_health") as mock_lb, patch(
            "core.events.emit_provider_event", new_callable=AsyncMock
        ) as mock_emit:
            await service._poll_provider(provider)   # miss 1 → no state yet
            mock_lb.assert_not_called()
            mock_emit.assert_not_called()
            await service._poll_provider(provider)   # miss 2 → offline transition
            mock_lb.assert_called_with(provider.id, healthy=False, task_types=("image", "llm", "tts"))
            mock_emit.assert_awaited_once()

    async def test_first_success_after_offline_flips_online(self, service):
        """One success after offline → online, LB cache healthy, event emitted."""
        provider = _provider()
        engine = AsyncMock(check_health=AsyncMock(side_effect=RuntimeError("down")))
        with patch.object(pts, "can_create_engine", return_value=True), patch.object(
            pts, "get_engine", return_value=engine
        ):
            await service._poll_provider(provider)
            await service._poll_provider(provider)
            assert service._status[provider.id]["status"] == "offline"
            engine.check_health = AsyncMock(return_value={"ready": True})
            with patch("services.load_balancer.set_poller_health") as mock_lb, patch(
                "core.events.emit_provider_event", new_callable=AsyncMock
            ) as mock_emit:
                await service._poll_provider(provider)
        assert service._status[provider.id]["status"] == "online"
        assert service._status[provider.id]["missed_probes"] == 0
        mock_lb.assert_called_with(provider.id, healthy=True, task_types=("image", "llm", "tts"))
        mock_emit.assert_awaited_once()

    async def test_health_timeout_counts_as_a_miss(self, service):
        """A hung engine is a miss, not a crash."""
        provider = _provider()
        engine = AsyncMock(check_health=AsyncMock(side_effect=asyncio.TimeoutError()))
        with patch.object(pts, "can_create_engine", return_value=True), patch.object(
            pts, "get_engine", return_value=engine
        ):
            await service._poll_provider(provider)
            await service._poll_provider(provider)
        assert service._status[provider.id]["status"] == "offline"


class TestServerlessSkipsStateMachine:
    async def test_modal_never_gains_a_liveness_status(self, service):
        """Modal/Beam get the config-only probe and no online/offline state."""
        provider = _provider("modal-x", "modal")
        engine = AsyncMock(check_health=AsyncMock(return_value={"probed": False, "ready": True}))
        with patch.object(pts, "can_create_engine", return_value=True), patch.object(
            pts, "get_engine", return_value=engine
        ):
            await service._poll_provider(provider)
            assert provider.id not in service._status
            # Config-only still refreshes the engine's own health fields for
            # the status card — the probe ran, the state machine did not.
            assert engine.check_health.await_count == 1


class TestVramSampling:
    async def test_remote_sample_lands_in_ring_buffer(self, service):
        """A remote_hybrid engine's agent VRAM endpoint is sampled into the ring."""
        provider = _provider()
        vram_payload = {
            "vram_used_mb": 8000,
            "vram_total_mb": 24000,
            "devices": [{"index": 0, "vram_used_mb": 8000, "vram_total_mb": 24000}],
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = vram_payload
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)

        engine = AsyncMock(
            check_health=AsyncMock(return_value={"ready": True}),
            agent_url="http://remote-server:8001",
            agent_token="tok",
        )
        with patch.object(pts, "can_create_engine", return_value=True), patch.object(
            pts, "get_engine", return_value=engine
        ), patch("httpx.AsyncClient", return_value=mock_client):
            await service._poll_provider(provider)

        history = service.get_vram_history(provider.id)
        assert len(history) == 1
        sample = history[0]
        assert sample["vram_used_mb"] == 8000
        assert sample["vram_total_mb"] == 24000
        assert sample["ts"]
        # Bearer header used for the agent's token auth
        assert mock_client.get.await_args.kwargs["headers"]["Authorization"] == "Bearer tok"

    async def test_vram_failure_does_not_flip_liveness(self, service):
        """A failed VRAM sample is not a missed health probe."""
        provider = _provider()
        engine = AsyncMock(
            check_health=AsyncMock(return_value={"ready": True}),
            agent_url="http://remote-server:8001",
            agent_token="tok",
        )
        with patch.object(pts, "can_create_engine", return_value=True), patch.object(
            pts, "get_engine", return_value=engine
        ), patch("httpx.AsyncClient", side_effect=RuntimeError("boom")):
            await service._poll_provider(provider)
        assert service._status[provider.id]["status"] == "online"
        assert service.get_vram_history(provider.id) == []

    async def test_engine_without_agent_url_is_not_sampled(self, service):
        """No agent_url → no VRAM call at all (hosted-API providers)."""
        provider = _provider("api-x", "openai_compat")
        engine = AsyncMock(check_health=AsyncMock(return_value={"ready": True}))
        engine.agent_url = ""
        with patch.object(pts, "can_create_engine", return_value=True), patch.object(
            pts, "get_engine", return_value=engine
        ), patch("httpx.AsyncClient") as mock_httpx:
            await service._poll_provider(provider)
        mock_httpx.assert_not_called()


class TestWarmWindow:
    async def test_unknown_without_completed_jobs(self, session, service):
        provider = _provider("modal-warm", "modal", config={"deploy_config": {"scaledown_window": 300}})
        session.add(provider)
        session.commit()

        result = await service.compute_serverless_lifecycle(provider)
        assert result["state"] == "unknown"
        assert result["estimated"] is True

    async def test_recent_completion_is_warm_with_countdown(self, session, service):
        provider = _provider("modal-warm", "modal", config={"deploy_config": {"scaledown_window": 300}})
        session.add(provider)
        completed = datetime.now(timezone.utc) - timedelta(seconds=60)
        session.add(Job(
            id="job-warm", provider_id="modal-warm", task_type="image",
            status=JobStatus.COMPLETED, completed_at=completed,
        ))
        session.commit()

        result = await service.compute_serverless_lifecycle(provider)
        assert result["state"] == "warm"
        assert result["window_seconds"] == 300
        assert result["seconds_left"] == pytest.approx(240, abs=5)
        assert result["last_completed_job_id"] == "job-warm"

    async def test_expired_window_is_cold(self, session, service):
        provider = _provider("modal-cold", "modal", config={"deploy_config": {"scaledown_window": 300}})
        session.add(provider)
        completed = datetime.now(timezone.utc) - timedelta(seconds=600)
        session.add(Job(
            id="job-cold", provider_id="modal-cold", task_type="image",
            status=JobStatus.COMPLETED, completed_at=completed,
        ))
        session.commit()

        result = await service.compute_serverless_lifecycle(provider)
        assert result["state"] == "cold"

    async def test_window_tail_is_cooling(self, session, service):
        provider = _provider("modal-cool", "modal", config={"deploy_config": {"scaledown_window": 300}})
        session.add(provider)
        completed = datetime.now(timezone.utc) - timedelta(seconds=280)
        session.add(Job(
            id="job-cool", provider_id="modal-cool", task_type="image",
            status=JobStatus.COMPLETED, completed_at=completed,
        ))
        session.commit()

        result = await service.compute_serverless_lifecycle(provider)
        assert result["state"] == "cooling"

    async def test_fallback_window_when_deploy_config_silent(self, session, service):
        """No deploy_config key → the 300s fallback, env-overridable."""
        provider = _provider()
        session.add(Job(
            id="job-fb", provider_id=provider.id, task_type="image",
            status=JobStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc),
        ))
        session.commit()
        # provider itself not persisted — fine: it's only read for config/type.
        result = await service.compute_serverless_lifecycle(provider)
        assert result["window_seconds"] == 300.0
        assert result["state"] == "warm"

    async def test_lifecycle_result_is_cached_briefly(self, session, service):
        provider = _provider("modal-cache", "modal", config={"deploy_config": {"scaledown_window": 300}})
        session.add(Job(
            id="job-cache", provider_id="modal-cache", task_type="image",
            status=JobStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc),
        ))
        session.commit()
        first = await service.compute_serverless_lifecycle(provider)
        second = await service.compute_serverless_lifecycle(provider)
        assert first == second


class TestSetPollerHealth:
    def setup_method(self):
        _provider_health_cache.clear()

    def teardown_method(self):
        _provider_health_cache.clear()

    def test_offline_writes_false_for_given_task_types(self):
        set_poller_health("p-off", healthy=False, task_types=("llm",))
        assert _provider_health_cache["in_process:p-off:llm"] is False

    def test_online_writes_true_per_task_type_and_base(self):
        set_poller_health("p-on", healthy=True)
        assert _provider_health_cache["in_process:p-on"] is True
        for task_type in ("image", "llm", "tts"):
            assert _provider_health_cache[f"in_process:p-on:{task_type}"] is True

    def test_checks_do_not_fail_empty_task_type(self):
        set_poller_health("p-mix", healthy=True, task_types=())
        assert _provider_health_cache["in_process:p-mix"] is True


class TestAccessors:
    def test_unknown_provider_status_defaults(self, service):
        assert service.get_provider_status("nope") == {
            "status": None, "last_seen_at": None, "missed_probes": 0,
        }

    def test_forget_provider_drops_everything(self, service):
        service._status["gone"] = {"status": "online", "last_seen_at": "x", "missed_probes": 0}
        service._vram_history["gone"] = deque([{"ts": "t"}])
        service._lifecycle_cache["gone"] = (0.0, {})
        service.forget_provider("gone")
        assert "gone" not in service._status
        assert "gone" not in service._vram_history
        assert "gone" not in service._lifecycle_cache
