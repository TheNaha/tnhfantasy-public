from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.container_manager import ContainerSnapshot
from services.provider_runtime import resolve_provider_runtime, resolve_provider_runtime_async


def _container_provider(**container_config):
    return SimpleNamespace(
        id="provider-1",
        type="modal",
        container_config={"port": 8000, **container_config},
    )


def test_container_provider_defaults_to_unknown_until_probe_succeeds():
    provider = _container_provider()

    with patch("infrastructure.deps.get_container_manager", return_value=None):
        runtime = resolve_provider_runtime(provider)

    assert runtime.mode == "unavailable"
    assert runtime.connected is False
    assert runtime.status == "unavailable"
    assert runtime.healthy is False


def test_container_provider_reports_connected_when_container_probe_succeeds():
    container_manager = MagicMock()
    container_manager.get_container_snapshot.return_value = ContainerSnapshot(
        name="tnhcomfy-provider-1", status="running", health="healthy"
    )

    provider = _container_provider()

    with patch("infrastructure.deps.get_container_manager", return_value=container_manager):
        runtime = resolve_provider_runtime(provider)

    assert runtime.connected is True
    assert runtime.status == "running"
    assert runtime.healthy is True


def test_container_provider_is_unhealthy_when_the_healthcheck_fails():
    """A running container whose image HEALTHCHECK reports unhealthy is not
    usable, and reporting it as connected is how a broken provider looks fine."""
    container_manager = MagicMock()
    container_manager.get_container_snapshot.return_value = ContainerSnapshot(
        name="tnhcomfy-provider-1", status="running", health="unhealthy"
    )

    with patch("infrastructure.deps.get_container_manager", return_value=container_manager):
        runtime = resolve_provider_runtime(_container_provider())

    assert runtime.connected is False
    assert runtime.healthy is False


def test_container_provider_without_a_healthcheck_is_connected_when_running():
    """No HEALTHCHECK in the image means `health is None`, which must not be read
    as "unhealthy"."""
    container_manager = MagicMock()
    container_manager.get_container_snapshot.return_value = ContainerSnapshot(
        name="tnhcomfy-provider-1", status="running", health=None
    )

    with patch("infrastructure.deps.get_container_manager", return_value=container_manager):
        runtime = resolve_provider_runtime(_container_provider())

    assert runtime.connected is True
    assert runtime.healthy is None


def test_missing_container_falls_through_to_discovery_url():
    """A provider this process did not start, or one already removed, must not be
    pinned to an unreachable container name."""
    container_manager = MagicMock()
    container_manager.get_container_snapshot.return_value = None

    provider = SimpleNamespace(
        id="provider-1",
        type="modal",
        container_config={"port": 8000},
        config={"discovery_url": "http://discovered:8000"},
    )

    with patch("infrastructure.deps.get_container_manager", return_value=container_manager):
        runtime = resolve_provider_runtime(provider)

    assert runtime.mode == "discovery"
    assert runtime.worker_url == "http://discovered:8000"


def test_snapshot_probe_failure_degrades_instead_of_raising():
    """An unreachable Docker socket used to raise out of the probe; the old
    `except Exception` swallowed it, and the new accessor must too."""
    container_manager = MagicMock()
    container_manager.get_container_snapshot.side_effect = OSError("docker socket gone")

    with patch("infrastructure.deps.get_container_manager", return_value=container_manager):
        runtime = resolve_provider_runtime(_container_provider())

    assert runtime.mode == "unavailable"


def test_async_resolver_returns_the_same_target():
    import asyncio

    container_manager = MagicMock()
    container_manager.get_container_snapshot.return_value = ContainerSnapshot(
        name="tnhcomfy-provider-1", status="running", health="healthy"
    )

    with patch("infrastructure.deps.get_container_manager", return_value=container_manager):
        runtime = asyncio.run(resolve_provider_runtime_async(_container_provider()))

    assert runtime.mode == "container_http"
    assert runtime.connected is True


def test_async_resolver_degrades_on_timeout():
    """A wedged Docker daemon must not hold the request open, and must not 500 —
    the caller degrades to `unavailable` and the route still answers."""
    import asyncio

    def _hang(_provider):
        import time

        time.sleep(5)
        raise AssertionError("should have been cancelled")

    with patch("services.provider_runtime.resolve_provider_runtime", _hang):
        runtime = asyncio.run(
            resolve_provider_runtime_async(_container_provider()),
        )

    assert runtime.mode == "unavailable"
    assert runtime.status == "probe_timeout"
    assert runtime.connected is False


def test_container_placement_in_config_resolves_without_legacy_key():
    """Migration 089: container_name/port healed into `config` must resolve
    identically to the legacy `container_config` placement."""
    container_manager = MagicMock()
    container_manager.get_container_snapshot.return_value = ContainerSnapshot(
        name="custom-container", status="running", health="healthy"
    )

    provider = SimpleNamespace(
        id="provider-1",
        type="modal",
        container_config=None,
        config={"container_name": "custom-container", "port": 9000},
    )

    with patch("infrastructure.deps.get_container_manager", return_value=container_manager):
        runtime = resolve_provider_runtime(provider)

    assert runtime.mode == "container_http"
    assert runtime.container_name == "custom-container"
    assert runtime.worker_url == "http://custom-container:9000"
    assert runtime.connected is True


def test_config_wins_over_legacy_container_config():
    """On conflict the newer `config` write path wins (migration 089 rule)."""
    container_manager = MagicMock()
    container_manager.get_container_snapshot.return_value = ContainerSnapshot(
        name="new-container", status="running", health="healthy"
    )

    provider = SimpleNamespace(
        id="provider-1",
        type="modal",
        container_config={"container_name": "old-container", "port": 8000},
        config={"container_name": "new-container"},
    )

    with patch("infrastructure.deps.get_container_manager", return_value=container_manager):
        runtime = resolve_provider_runtime(provider)

    assert runtime.mode == "container_http"
    assert runtime.container_name == "new-container"
