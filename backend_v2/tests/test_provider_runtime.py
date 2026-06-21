from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.provider_runtime import resolve_provider_runtime


def test_container_provider_defaults_to_unknown_until_probe_succeeds():
    provider = SimpleNamespace(
        id="provider-1",
        type="modal",
        container_config={"port": 8000},
    )

    with patch("services.container_manager.get_container_manager", return_value=None):
        runtime = resolve_provider_runtime(provider)

    assert runtime.mode == "unavailable"
    assert runtime.connected is False
    assert runtime.status == "unavailable"
    assert runtime.healthy is False


def test_container_provider_reports_connected_when_container_probe_succeeds():
    container = MagicMock()
    container.status = "running"
    container.short_id = "container-123"
    container.attrs = {"State": {"Health": {"Status": "healthy"}}}
    container.reload.return_value = None

    container_manager = MagicMock()
    container_manager.running_containers = {}
    container_manager.client.containers.get.return_value = container

    provider = SimpleNamespace(
        id="provider-1",
        type="modal",
        container_config={"port": 8000},
    )

    with patch("services.container_manager.get_container_manager", return_value=container_manager):
        runtime = resolve_provider_runtime(provider)

    assert runtime.connected is True
    assert runtime.status == "running"
    assert runtime.healthy is True
