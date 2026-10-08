"""ProviderLifecycleService over in-process engines.

Providers execute via ``services/engines/``; this service is the seam over
engine setup and the in-process reconciler. There is no container to start,
no worker URL to POST to, and no Docker daemon to classify: setup and
reconciliation go through the engine, and status reads the persisted row.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.exceptions import ProviderError
from services.provider_lifecycle_service import ProviderLifecycleService


def _service(provider: SimpleNamespace) -> ProviderLifecycleService:
    provider_service = MagicMock()
    provider_service.get_provider = AsyncMock(return_value=provider)
    written: list[dict] = []

    def _upsert(provider_id, state):
        written.append(state)
        return {"provider_id": provider_id, **state}

    provider_service.upsert_reconciliation_state = _upsert
    provider_service.get_provider_reconciliation_state = AsyncMock(
        return_value={"provider_id": provider.id, "status": "idle"}
    )
    svc = ProviderLifecycleService(
        session=MagicMock(),
        provider_service=provider_service,
    )
    svc.status_service = MagicMock()
    svc.status_service.normalize_reconciliation_for_card = lambda state: state
    svc.written = written
    return svc


def _provider(**extra) -> SimpleNamespace:
    base = {"id": "provider-1", "type": "modal", "worker_type": "image"}
    base.update(extra)
    return SimpleNamespace(**base)


def _in_process():
    return patch(
        "services.provider_lifecycle_service.resolve_provider_runtime_async",
        AsyncMock(return_value=SimpleNamespace(mode="in_process")),
    )


# ---------------------------------------------------------------------------
# setup_provider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_provider_refuses_non_in_process_runtime():
    svc = _service(_provider())
    with patch(
        "services.provider_lifecycle_service.resolve_provider_runtime_async",
        AsyncMock(return_value=SimpleNamespace(mode="external_worker", worker_url="http://agent:8001")),
    ):
        with pytest.raises(ProviderError, match="in-process engine"):
            await svc.setup_provider("provider-1")


@pytest.mark.asyncio
async def test_setup_provider_skips_engines_without_a_model_tree():
    """Hosted-LLM/TTS engines own no model tree; setup is a no-op success."""
    svc = _service(_provider(type="google", worker_type="llm"))
    with _in_process(), patch(
        "services.engines.engine_factory.engine_supports_setup", return_value=False
    ):
        result = await svc.setup_provider("provider-1")

    assert result["status"] == "success"
    assert result["result"]["status"] == "skipped"


@pytest.mark.asyncio
async def test_setup_provider_runs_engine_setup_models():
    engine = MagicMock()
    engine.setup_models = AsyncMock(return_value=True)
    svc = _service(_provider())
    with _in_process(), patch(
        "services.engines.engine_factory.engine_supports_setup", return_value=True
    ), patch("services.engines.engine_factory.get_engine", return_value=engine):
        result = await svc.setup_provider("provider-1")

    assert result["status"] == "success"
    engine.setup_models.assert_awaited_once()


@pytest.mark.asyncio
async def test_setup_provider_reports_engine_failure():
    engine = MagicMock()
    engine.setup_models = AsyncMock(return_value=False)
    svc = _service(_provider())
    with _in_process(), patch(
        "services.engines.engine_factory.engine_supports_setup", return_value=True
    ), patch("services.engines.engine_factory.get_engine", return_value=engine):
        with pytest.raises(ProviderError, match="reported failure"):
            await svc.setup_provider("provider-1")


@pytest.mark.asyncio
async def test_setup_provider_wraps_timeout_with_provider_error():
    async def _hang():
        await asyncio.sleep(60)

    engine = MagicMock()
    engine.setup_models = _hang
    svc = _service(_provider())
    with _in_process(), patch(
        "services.engines.engine_factory.engine_supports_setup", return_value=True
    ), patch("services.engines.engine_factory.get_engine", return_value=engine):
        with pytest.raises(ProviderError, match="timed out"):
            await svc.setup_provider("provider-1")


# ---------------------------------------------------------------------------
# trigger_reconciliation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_reconciliation_refuses_non_in_process_runtime():
    svc = _service(_provider())
    with patch(
        "services.provider_lifecycle_service.resolve_provider_runtime_async",
        AsyncMock(return_value=SimpleNamespace(mode="external_worker", worker_url="http://agent:8001")),
    ):
        with pytest.raises(ProviderError, match="in-process engine"):
            await svc.trigger_reconciliation("provider-1")


@pytest.mark.asyncio
async def test_trigger_reconciliation_records_in_flight_as_reconciling():
    svc = _service(_provider())
    with _in_process(), patch(
        "services.engines.engine_factory.get_engine", return_value=MagicMock()
    ), patch(
        "services.in_process_reconciliation.trigger_in_process_reconciliation",
        AsyncMock(return_value={"status": "running", "message": "working"}),
    ):
        result = await svc.trigger_reconciliation("provider-1")

    assert result["status"] == "triggered"
    assert svc.written[0]["status"] == "reconciling"


@pytest.mark.asyncio
async def test_trigger_reconciliation_records_terminal_outcome():
    svc = _service(_provider())
    with _in_process(), patch(
        "services.engines.engine_factory.get_engine", return_value=MagicMock()
    ), patch(
        "services.in_process_reconciliation.trigger_in_process_reconciliation",
        AsyncMock(return_value={"status": "completed", "message": "done"}),
    ):
        result = await svc.trigger_reconciliation("provider-1")

    assert result["status"] == "completed"
    assert svc.written[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_sync_provider_models_forces_quick_sync():
    svc = _service(_provider())
    with _in_process(), patch(
        "services.engines.engine_factory.get_engine", return_value=MagicMock()
    ), patch(
        "services.in_process_reconciliation.trigger_in_process_reconciliation",
        AsyncMock(return_value={"status": "completed"}),
    ) as reconciler:
        await svc.sync_provider_models("provider-1")

    _, kwargs = reconciler.call_args
    assert kwargs["force"] is True
    assert kwargs["quick_sync"] is True


# ---------------------------------------------------------------------------
# get_reconciliation_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_reconciliation_status_returns_persisted_state():
    """The persisted row IS the live state — there is no worker to poll."""
    svc = _service(_provider())
    svc.provider_service.get_provider_reconciliation_state = AsyncMock(
        return_value={"provider_id": "provider-1", "status": "completed"}
    )

    result = await svc.get_reconciliation_status("provider-1")

    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_get_reconciliation_status_defaults_to_idle():
    svc = _service(_provider())
    svc.provider_service.get_provider_reconciliation_state = AsyncMock(return_value={})

    result = await svc.get_reconciliation_status("provider-1")

    assert result["status"] == "idle"
