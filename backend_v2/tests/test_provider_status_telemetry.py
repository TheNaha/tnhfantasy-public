"""P2: the status card / diagnostics expose the telemetry engine's surface.

Covers: liveness (status / last_seen_at / missed_probes), VRAM history ring,
serverless warm-window lifecycle, normalized component chips — and the
recent-jobs payload carrying ``boot_seconds`` from job metadata.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session

from core.entities import Job, JobStatus, Provider
from services.provider_status_service import ProviderStatusService
from services.provider_telemetry_service import telemetry_service


def _remote_provider(session: Session) -> Provider:
    provider = Provider(
        id="lb-remote", type="remote_hybrid", enabled=True,
        credentials={"remote_agent_token": "tok"},
        config={"remote_agent_url": "http://remote:8001"},
    )
    session.add(provider)
    session.commit()
    return provider


@pytest.fixture(autouse=True)
def _clean_telemetry_state():
    telemetry_service._status.clear()
    telemetry_service._vram_history.clear()
    telemetry_service._lifecycle_cache.clear()
    yield
    telemetry_service._status.clear()
    telemetry_service._vram_history.clear()
    telemetry_service._lifecycle_cache.clear()


@pytest.fixture(autouse=True)
def _stub_card_dependencies(monkeypatch):
    """The card's non-telemetry dependencies are stubbed: this file pins the
    telemetry surface, not reconciliation/storage assembly."""

    class _R:
        worker_url = None
        mode = "in_process"
        connected = True
        supports_setup = True
        supports_reconciliation = True
        status = "in_process"

    monkeypatch.setattr(
        "services.provider_status_service.resolve_provider_runtime_async",
        lambda _p: _async(_R()),
    )
    monkeypatch.setattr(
        ProviderStatusService, "get_provider_sync_stats",
        lambda self, pid, provider=None: _async({
            "total_models": 0, "stats": {}, "catalog_models": 0,
            "has_install_intent": False, "is_image_provider": True,
        }),
    )
    monkeypatch.setattr(
        ProviderStatusService, "get_live_reconciliation_state",
        lambda self, pid, provider=None: _async({"status": "idle"}),
    )
    monkeypatch.setattr(
        ProviderStatusService, "get_live_deploy_state",
        lambda self, pid, provider=None: _async({"status": "idle"}),
    )
    monkeypatch.setattr(
        ProviderStatusService, "get_provider_storage_stats",
        lambda self, pid, provider=None, reconciliation_state=None: _async({
            "provider_id": pid, "total": 0, "by_directory": {},
        }),
    )


async def _async(value):
    return value


@pytest.mark.asyncio
async def test_card_exposes_liveness_history_and_components(session):
    """Remote provider card carries poller liveness + VRAM ring + normalized chips."""
    _remote_provider(session)

    telemetry_service._status["lb-remote"] = {
        "status": "online",
        "last_seen_at": "2026-10-29T00:00:00+00:00",
        "missed_probes": 0,
    }
    telemetry_service._vram_history["lb-remote"] = [
        {"ts": "2026-10-29T00:00:00+00:00", "vram_used_mb": 8000, "vram_total_mb": 24000},
        {"ts": "2026-10-29T00:01:00+00:00", "vram_used_mb": 9200, "vram_total_mb": 24000},
    ]

    engine = MagicMock()
    engine._last_health = {
        "components": {
            "comfyui": {"status": "healthy", "port": 8188, "latency_ms": 12},
            "agent": {"status": "healthy", "port": 8001},
        }
    }
    with patch.dict(
        "services.engines.engine_factory._ENGINE_CACHE", {"lb-remote": engine}
    ):
        card = await ProviderStatusService(session=session).build_provider_status_card("lb-remote")

    telemetry = card["runtime"]["telemetry"]
    assert telemetry["status"] == "online"
    assert telemetry["last_seen_at"] == "2026-10-29T00:00:00+00:00"
    assert telemetry["missed_probes"] == 0
    assert len(telemetry["history"]["vram"]) == 2
    assert telemetry["history"]["vram"][1]["vram_used_mb"] == 9200
    # Remote transports have no serverless lifecycle to infer.
    assert telemetry["lifecycle"] is None
    assert telemetry["transport"] == "remote"

    chips = telemetry["components"]
    assert set(chips) == {"comfyui", "agent"}
    assert chips["comfyui"]["name"] == "comfyui"
    assert chips["comfyui"]["status"] == "healthy"
    assert chips["comfyui"]["port"] == 8188
    assert chips["agent"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_card_components_are_normalized_when_engine_reports_none(session):
    """Engines without health yet still produce explicit-unknown chips."""
    _remote_provider(session)
    engine = MagicMock(spec=["comfy_port", "agent_port", "llm_port"])
    engine.comfy_port = 8188
    engine.agent_port = 8001
    engine.llm_port = 8003
    engine._last_health = {}

    with patch.dict(
        "services.engines.engine_factory._ENGINE_CACHE", {"lb-remote": engine}
    ):
        card = await ProviderStatusService(session=session).build_provider_status_card("lb-remote")

    chips = card["runtime"]["telemetry"]["components"]
    assert chips["comfyui"] == {
        "name": "comfyui", "status": "unknown", "port": 8188, "url": None, "latency_ms": None,
    }


@pytest.mark.asyncio
async def test_card_without_engine_still_reports_the_poller(session):
    """A provider no engine can be built for still shows liveness fields."""
    _remote_provider(session)
    telemetry_service._status["lb-remote"] = {
        "status": "offline", "last_seen_at": "2026-10-28T23:00:00+00:00", "missed_probes": 2,
    }
    card = await ProviderStatusService(session=session).build_provider_status_card("lb-remote")

    telemetry = card["runtime"]["telemetry"]
    assert telemetry["status"] == "offline"
    assert telemetry["last_seen_at"] == "2026-10-28T23:00:00+00:00"
    assert telemetry["missed_probes"] == 2
    assert telemetry["history"]["vram"] == []
    assert telemetry["components"] is None


@pytest.mark.asyncio
async def test_modal_card_infers_lifecycle_from_last_completed_job(session):
    """Modal/Beam: the card carries the warm-window inference, marked estimated."""
    provider = Provider(
        id="lb-modal", type="modal", enabled=True,
        credentials={"token_id": "t", "token_secret": "s"},
        config={"app_name": "x", "deploy_config": {"scaledown_window": 300}},
    )
    session.add(provider)
    session.add(Job(
        id="lb-modal-job", provider_id="lb-modal", task_type="image",
        status=JobStatus.COMPLETED,
        completed_at=datetime.now(timezone.utc) - timedelta(seconds=60),
    ))
    session.commit()

    card = await ProviderStatusService(session=session).build_provider_status_card("lb-modal")

    telemetry = card["runtime"]["telemetry"]
    lifecycle = telemetry["lifecycle"]
    assert lifecycle is not None
    assert lifecycle["state"] == "warm"
    assert lifecycle["estimated"] is True
    assert lifecycle["window_seconds"] == 300
    # Serverless transports never get a liveness verdict from the poller.
    assert telemetry["status"] is None


@pytest.mark.asyncio
async def test_logs_route_recent_jobs_carry_boot_seconds(session, client):
    """GET /{id}/logs recent_jobs includes job.metadata_['boot_seconds']."""
    from infrastructure.repositories import ProviderRepository

    ProviderRepository(session).create({
        "id": "lb-jobs", "type": "modal", "enabled": True,
        "credentials": {"token_id": "t", "token_secret": "s"},
        "config": {"app_name": "x"},
    })
    session.add(Job(
        id="job-booted", provider_id="lb-jobs", task_type="image",
        status=JobStatus.COMPLETED,
        metadata_={"boot_seconds": 3.4},
    ))
    session.commit()

    # The logs route builds the real status card; the storage/service deps are
    # heavy, so stub the card builder to a minimal success payload.
    from services.provider_status_service import invalidate_provider_status_caches

    invalidate_provider_status_caches()

    def _fake_card(*args, **kwargs):
        return _async({
            "provider_id": "lb-jobs",
            "diagnostics": {"worker": {"mode": "in_process"}},
            "runtime": {"mode": "in_process", "connected": True},
            "reconciliation": {"status": "idle"},
        })

    with patch.object(
        ProviderStatusService,
        "build_provider_status_card",
        _fake_card,
    ):
        response = client.get("/api/v2/providers/lb-jobs/logs")

    assert response.status_code == 200
    data = response.json()
    jobs = data["recent_jobs"]
    assert jobs and jobs[0]["id"] == "job-booted"
    assert jobs[0]["boot_seconds"] == 3.4
