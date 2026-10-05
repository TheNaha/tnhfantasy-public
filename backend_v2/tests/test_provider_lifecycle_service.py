from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import docker
import httpx
import pytest

from core.events import EventType
from core.exceptions import ProviderError, ServiceUnavailableError
from services.provider_lifecycle_service import ProviderLifecycleService


@pytest.mark.asyncio
async def test_start_container_emits_event_and_invalidates_cache():
    provider_service = MagicMock()
    provider_service.get_provider = AsyncMock(
        return_value=SimpleNamespace(
            id="provider-1",
            type="modal",
            container_config={"port": 8000},
        )
    )
    provider_service.build_provider_environment.return_value = {"MODAL_TOKEN_ID": "abc"}

    container = MagicMock(short_id="container-123")
    container_manager = MagicMock()
    container_manager.start_container = AsyncMock(return_value=container)

    invalidate = MagicMock()

    service = ProviderLifecycleService(
        session=MagicMock(),
        provider_service=provider_service,
        container_manager=container_manager,
        invalidate_caches=invalidate,
    )

    with patch("services.provider_lifecycle_service.emit_provider_event", new=AsyncMock()) as mock_emit:
        result = await service.start_container("provider-1")

    assert result["container_id"] == "container-123"
    provider_service.build_provider_environment.assert_called_once_with(
        provider_service.get_provider.return_value
    )
    container_manager.start_container.assert_called_once()
    invalidate.assert_called_once_with("provider-1")
    mock_emit.assert_awaited_once_with(
        EventType.PROVIDER_CONTAINER_STATUS,
        "provider-1",
        {"status": "running"},
    )


@pytest.mark.asyncio
async def test_trigger_reconciliation_short_circuits_when_already_running():
    provider_service = MagicMock()
    provider_service.get_provider = AsyncMock(
        return_value=SimpleNamespace(id="provider-1", type="modal", container_config={"port": 8000})
    )
    provider_service.start_reconciliation_session = AsyncMock(
        return_value={
            "accepted": False,
            "state": {"status": "queued"},
            "message": "Reconciliation already in progress for this provider",
        }
    )

    service = ProviderLifecycleService(
        session=MagicMock(),
        provider_service=provider_service,
        container_manager=MagicMock(),
    )

    with patch(
        "services.provider_lifecycle_service.resolve_provider_runtime_async",
        return_value=SimpleNamespace(supports_reconciliation=True, mode="container_http", worker_url="http://worker"),
    ):
        result = await service.trigger_reconciliation("provider-1")

    assert result["status"] == "already_running"
    assert result["message"] == "Reconciliation already in progress for this provider"


@pytest.mark.asyncio
async def test_get_reconciliation_status_returns_warning_when_worker_unreachable():
    provider_service = MagicMock()
    provider_service.get_provider = AsyncMock(
        return_value=SimpleNamespace(id="provider-1", type="modal", container_config={"port": 8000})
    )
    provider_service.get_provider_reconciliation_state = AsyncMock(return_value={"status": "idle"})

    http_client = MagicMock()
    http_client.get = AsyncMock(side_effect=httpx.ConnectError("boom"))

    service = ProviderLifecycleService(
        session=MagicMock(),
        provider_service=provider_service,
        container_manager=MagicMock(),
    )

    with patch(
        "services.provider_lifecycle_service.resolve_provider_runtime_async",
        return_value=SimpleNamespace(mode="container_http", worker_url="http://worker"),
    ), patch("services.provider_lifecycle_service.get_http_client", return_value=http_client):
        result = await service.get_reconciliation_status("provider-1")

    assert result["status"] == "idle"
    assert "Cannot reach worker" in result["warning"]


@pytest.mark.asyncio
async def test_setup_provider_returns_accepted_for_queued_worker_response():
    provider_service = MagicMock()
    provider_service.get_provider = AsyncMock(
        return_value=SimpleNamespace(id="provider-1", type="modal", container_config={"port": 8000})
    )

    http_client = MagicMock()
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "status": "queued",
        "message": "Setup queued",
        "provider": "provider-1",
    }
    http_client.post = AsyncMock(return_value=response)

    service = ProviderLifecycleService(
        session=MagicMock(),
        provider_service=provider_service,
        container_manager=MagicMock(),
    )

    with patch(
        "services.provider_lifecycle_service.resolve_provider_runtime_async",
        return_value=SimpleNamespace(supports_setup=True, mode="container_http", worker_url="http://worker"),
    ), patch("services.provider_lifecycle_service.get_http_client", return_value=http_client):
        result = await service.setup_provider("provider-1")

    assert result["status"] == "accepted"
    assert result["message"] == "Setup queued"
    assert result["result"]["status"] == "queued"
    http_client.post.assert_awaited_once_with("http://worker/setup", timeout=30.0)


@pytest.mark.asyncio
async def test_setup_provider_wraps_timeout_with_provider_error():
    provider_service = MagicMock()
    provider_service.get_provider = AsyncMock(
        return_value=SimpleNamespace(id="provider-1", type="modal", container_config={"port": 8000})
    )

    http_client = MagicMock()
    http_client.post = AsyncMock(side_effect=httpx.ReadTimeout("", request=MagicMock()))

    service = ProviderLifecycleService(
        session=MagicMock(),
        provider_service=provider_service,
        container_manager=MagicMock(),
    )

    with patch(
        "services.provider_lifecycle_service.resolve_provider_runtime_async",
        return_value=SimpleNamespace(supports_setup=True, mode="container_http", worker_url="http://worker"),
    ), patch("services.provider_lifecycle_service.get_http_client", return_value=http_client):
        with pytest.raises(ProviderError, match="Setup request to worker timed out"):
            await service.setup_provider("provider-1")


@pytest.mark.asyncio
async def test_get_container_status_uses_async_health_probe_when_container_is_running():
    provider_service = MagicMock()
    provider_service.get_provider = AsyncMock(
        return_value=SimpleNamespace(id="provider-1", type="modal", container_config={"port": 8000})
    )

    container = MagicMock()
    container.status = "running"
    container.short_id = "container-123"
    container.ports = {"8000/tcp": [{"HostPort": "18000"}]}
    container.attrs = {"State": {"Health": {}}}
    container.reload.return_value = None

    container_manager = MagicMock()
    container_manager.client.containers.get.return_value = container
    container_manager.running_containers = {}

    response = MagicMock()
    response.status_code = 200

    async_client = MagicMock()
    async_client.get = AsyncMock(return_value=response)

    service = ProviderLifecycleService(
        session=MagicMock(),
        provider_service=provider_service,
        container_manager=container_manager,
    )

    with patch("services.provider_lifecycle_service.get_http_client", return_value=async_client):
        result = await service.get_container_status("provider-1")

    assert result["status"] == "running"
    assert result["running"] is True
    assert result["healthy"] is True
    async_client.get.assert_awaited_once_with("http://localhost:18000/health", timeout=2.0)


# ---------------------------------------------------------------------------
# Container status: "stopped" must mean stopped, not "Docker is unreachable"
# ---------------------------------------------------------------------------


def _status_service_for(container_manager):
    provider_service = MagicMock()
    provider_service.get_provider = AsyncMock(
        return_value=SimpleNamespace(
            id="provider-1",
            type="modal",
            container_config={"port": 8000},
        )
    )
    return ProviderLifecycleService(
        session=MagicMock(),
        provider_service=provider_service,
        container_manager=container_manager,
    )


@pytest.mark.asyncio
async def test_get_container_status_reports_stopped_only_on_a_genuine_not_found():
    """`docker.errors.NotFound` is the one failure that means "not running"."""
    container_manager = MagicMock()
    container_manager.client.containers.get.side_effect = docker.errors.NotFound("no such container")

    result = await _status_service_for(container_manager).get_container_status("provider-1")

    assert result["status"] == "stopped"
    assert result["running"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(docker.errors.DockerException("daemon unreachable"), id="daemon-down"),
        pytest.param(ConnectionError("socket gone"), id="socket-missing"),
        pytest.param(PermissionError("permission denied"), id="permission-denied"),
        pytest.param(docker.errors.APIError("tls handshake failed"), id="tls-failure"),
    ],
)
async def test_get_container_status_refuses_to_call_an_unreachable_runtime_stopped(failure):
    """A host-wide Docker outage must not read as N stopped containers.

    The bare `except Exception` this replaces answered "the container is
    stopped" for every way the daemon can fail *other than* reporting the
    container absent — daemon down, socket permission denied, TLS failure, a
    context that no longer exists. A caller could not tell a real stop from a
    broken runtime, and there was no degraded signal to say "this answer is not
    trustworthy". So a Docker outage produced a clean-looking, entirely false
    answer instead of one that says the dependency is down.
    """
    container_manager = MagicMock()
    container_manager.client.containers.get.side_effect = failure

    with pytest.raises(ServiceUnavailableError) as excinfo:
        await _status_service_for(container_manager).get_container_status("provider-1")

    assert excinfo.value.service == "container_runtime"
    assert excinfo.value.code == "SERVICE_UNAVAILABLE"
    # Chained to the original so the log names the real cause.
    assert excinfo.value.__cause__ is failure


@pytest.mark.asyncio
async def test_get_container_status_unreachable_is_503_not_500():
    """`ComfyError` maps to 500; "your dependency is down" is a retry, not a bug."""
    container_manager = MagicMock()
    container_manager.client.containers.get.side_effect = docker.errors.DockerException("boom")

    with pytest.raises(ServiceUnavailableError) as excinfo:
        await _status_service_for(container_manager).get_container_status("provider-1")

    assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_get_container_status_logs_the_real_cause_before_raising():
    """The replaced branch swallowed the cause with no log at all.

    The project logs through structlog, which pytest's caplog does not see, so
    the logger is spied on directly.
    """
    container_manager = MagicMock()
    container_manager.client.containers.get.side_effect = docker.errors.DockerException(
        "Cannot connect to the Docker daemon"
    )

    import services.provider_lifecycle_service as lifecycle_module

    calls: list[tuple] = []
    original_error = lifecycle_module.logger.error
    lifecycle_module.logger.error = lambda event, **kw: calls.append((event, kw))
    try:
        with pytest.raises(ServiceUnavailableError):
            await _status_service_for(container_manager).get_container_status("provider-1")
    finally:
        lifecycle_module.logger.error = original_error

    assert calls, "an unreachable runtime must be logged, not silently reshaped"
    event, kwargs = calls[0]
    assert event == "container_runtime_unreachable"
    assert kwargs["provider_id"] == "provider-1"
    assert "Cannot connect to the Docker daemon" in kwargs["error"]
