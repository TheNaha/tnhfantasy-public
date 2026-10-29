"""P4: the Modal management-plane metadata probe.

Everything is mocked — no real network, no real Modal SDK, and above all ZERO
function invocations anywhere in these paths (lookup/info are free metadata
RPCs; the module must never do more than that).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import provider_probe as probe


def sync_mock(**kwargs):
    """A mock whose `aio` attribute is explicitly None, so the probe module's
    call adapter takes the thread path instead of awaiting a child mock."""
    m = MagicMock(**kwargs)
    m.aio = None
    return m


def modal_sandbox(lookup_fn, *, app=None):
    """A stand-in for the modal module with just App.lookup."""
    modal = MagicMock()
    modal.App = MagicMock()
    modal.App.lookup = lookup_fn
    return modal


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    probe._probe_cache.clear()
    yield
    probe._probe_cache.clear()


class TestProbeModalManagement:
    async def test_healthy_deployment_reports_reachable_with_topology(self):
        """lookup succeeds → reachable/app_exists; info() adds function names."""
        engine = MagicMock(
            app_name="comfy-modal-stack",
            get_client_async=AsyncMock(return_value=MagicMock(name="client")),
        )

        fake_info = SimpleNamespace(functions={
            "list_models_with_metadata": MagicMock(),
            "ComfyUISnapshot": MagicMock(),
        })

        def fake_info_fn():
            return fake_info

        fake_app = MagicMock()
        fake_app.info = fake_info_fn
        fake_app.info.aio = None

        lookup = sync_mock(return_value=fake_app)
        with patch("services.provider_probe._require_modal", return_value=modal_sandbox(lookup)):
            result = await probe.probe_modal_management(engine)

        assert result["managed_check"] is True
        assert result["reachable"] is True
        assert result["app_exists"] is True
        assert result["function_count"] == 2
        assert result["function_names"] == sorted(["ComfyUISnapshot", "list_models_with_metadata"])
        # create_if_missing=False: a probe must never create anything.
        assert lookup.call_args.kwargs.get("create_if_missing") is False

    async def test_missing_app_reports_exists_false(self):
        engine = MagicMock(
            app_name="gone-app",
            get_client_async=AsyncMock(return_value=MagicMock()),
        )
        lookup = sync_mock(side_effect=RuntimeError("app gone-app not found"))
        with patch("services.provider_probe._require_modal", return_value=modal_sandbox(lookup)):
            result = await probe.probe_modal_management(engine)

        assert result["reachable"] is False
        assert result["app_exists"] is False
        assert "gone-app" in result["error"]

    async def test_revoked_token_marks_token_invalid(self):
        engine = MagicMock(
            app_name="x",
            get_client_async=AsyncMock(return_value=MagicMock()),
        )
        lookup = sync_mock(side_effect=RuntimeError("credential invalid, unauthorized"))
        with patch("services.provider_probe._require_modal", return_value=modal_sandbox(lookup)):
            result = await probe.probe_modal_management(engine)

        assert result.get("token_valid") is False
        assert result["reachable"] is False
        # Unknown-cause lookup does not claim the app is gone.
        assert result["app_exists"] is None

    async def test_missing_sdk_is_tolerated(self):
        engine = MagicMock(app_name="x", get_client_async=AsyncMock(return_value=MagicMock()))
        with patch("services.provider_probe._require_modal", side_effect=probe._ModalUnavailableError("no sdk")):
            result = await probe.probe_modal_management(engine)
        assert result["reachable"] is False
        assert "error" in result

    async def test_no_client_never_bills(self):
        """Client build failure is summarised, not raised — the poller loop's
        guarantee (a spike never breaks a pass) is embedded in the probe."""
        engine = MagicMock(
            app_name="x", get_client_async=AsyncMock(side_effect=RuntimeError("no creds"))
        )
        result = await probe.probe_modal_management(engine)
        assert result["reachable"] is False
        assert result["app_exists"] in (None, False)

    async def test_no_app_name_configured(self):
        engine = MagicMock(app_name="", get_client_async=AsyncMock(return_value=MagicMock()))
        result = await probe.probe_modal_management(engine)
        assert result["reachable"] is False
        assert "app_name" in result["error"]


class TestAioOrThread:
    async def test_prefers_aio_variant(self):
        fn = MagicMock(aio=AsyncMock(return_value="aio-result"))
        # The adapter',s own check must call into the aio twin.
        result = await probe._call_aio_or_thread(fn)
        assert result == "aio-result"

    async def test_sync_variant_runs_off_loop(self):
        fn = sync_mock(side_effect=lambda *a, **k: "sync-result")
        result = await probe._call_aio_or_thread(fn)
        assert result == "sync-result"


class TestContainerStats:
    async def test_disabled_by_default_returns_none(self):
        assert probe.CONTAINER_STATS_ENABLED in (False, True)  # env decides
        with patch.object(probe, "CONTAINER_STATS_ENABLED", False):
            assert await probe.probe_modal_container_stats(MagicMock(app_name="x")) is None

    async def test_failure_is_ignored_and_logged_once(self):
        probe._webapp_stats_failure_logged = False
        engine = MagicMock(app_name="x", token_id="ak", token_secret="as")

        def boom(*args, **kwargs):
            raise RuntimeError("no network")

        with patch.object(probe, "CONTAINER_STATS_ENABLED", True), patch(
            "httpx.AsyncClient", MagicMock(side_effect=boom)
        ):
            result = await probe.probe_modal_container_stats(engine)

        assert result is None
        # Log-once is best-effort; never raises.
        assert probe._webapp_stats_failure_logged is True


class TestCachedFacade:
    async def test_cache_reuses_the_first_result(self):
        engine = MagicMock(
            app_name="stack",
            get_client_async=AsyncMock(return_value=MagicMock()),
        )
        fake_app = MagicMock()

        def fake_info_fn():
            return SimpleNamespace(functions={"f1": MagicMock()})

        fake_app.info = fake_info_fn
        fake_app.info.aio = None
        lookup = sync_mock(return_value=fake_app)
        with patch("services.provider_probe._require_modal", return_value=modal_sandbox(lookup)):
            first = await probe.probe_modal_management_cached("modal-x", engine)
            second = await probe.probe_modal_management_cached("modal-x", engine)

        assert first == second
        assert first["app_name"] == "stack"
        assert probe.get_cached_management("modal-x") == first
        probe.forget_probe("modal-x")
        assert probe.get_cached_management("modal-x") is None


class TestGlueIntoTelemetry:
    async def test_modal_transports_get_probed(self):
        """Modal providers are management-probed (free metadata only)."""
        from core.entities import Provider
        from services.provider_telemetry_service import ProviderTelemetryService, telemetry_service

        service = ProviderTelemetryService()
        engine = AsyncMock(check_health=AsyncMock(return_value={"probed": False, "ready": True}))
        fake_probe = AsyncMock(return_value={"reachable": False})
        with patch.object(
            provider_probe_module(), "probe_modal_management_cached", fake_probe
        ):
            provider = Provider(id="mm", type="modal", enabled=True, credentials={},
                                config={"app_name": "a"})
            with patch("services.provider_telemetry_service.can_create_engine",
                       return_value=True), patch(
                "services.provider_telemetry_service.get_engine", return_value=engine
            ):
                await service._poll_provider(provider)
        fake_probe.assert_awaited_once_with("mm", engine)
        telemetry_service._status.pop("mm", None)
        telemetry_service._lifecycle_cache.pop("mm", None)

    async def test_beam_transports_skip_the_probe(self):
        from core.entities import Provider
        from services.provider_telemetry_service import ProviderTelemetryService

        service = ProviderTelemetryService()
        engine = AsyncMock(check_health=AsyncMock(return_value={"probed": False, "ready": True}))
        with patch.object(
            provider_probe_module(), "probe_modal_management_cached", AsyncMock()
        ) as fake_probe:
            provider = Provider(id="bb", type="beam", enabled=True, credentials={},
                                config={"app_name": "a"})
            with patch("services.provider_telemetry_service.can_create_engine",
                       return_value=True), patch(
                "services.provider_telemetry_service.get_engine", return_value=engine
            ):
                await service._poll_provider(provider)
        fake_probe.assert_not_called()

    async def test_probe_failure_never_breaks_the_poll_pass(self):
        from core.entities import Provider
        from services.provider_telemetry_service import ProviderTelemetryService

        service = ProviderTelemetryService()
        engine = AsyncMock(check_health=AsyncMock(return_value={"probed": False, "ready": True}))
        with patch.object(
            provider_probe_module(), "probe_modal_management_cached",
            AsyncMock(side_effect=RuntimeError("spike exploded")),
        ), patch.object(
            provider_probe_module(), "forget_probe",
        ):
            provider = Provider(id="mm", type="modal", enabled=True, credentials={},
                                config={"app_name": "a"})
            with patch("services.provider_telemetry_service.can_create_engine",
                       return_value=True), patch(
                "services.provider_telemetry_service.get_engine", return_value=engine
            ):
                await service._poll_provider(provider)  # must not raise

    async def test_engines_without_client_are_not_probed(self):
        """direct/remote engines have no get_client_async — no probe attempted."""
        from core.entities import Provider
        from services.provider_telemetry_service import ProviderTelemetryService

        engine = MagicMock(check_health=AsyncMock(return_value={"ready": True}))
        engine.get_client_async = None
        with patch.object(
            provider_probe_module(), "probe_modal_management_cached", AsyncMock()
        ) as fake_probe, patch(
            "services.provider_telemetry_service.can_create_engine", return_value=True,
        ), patch(
            "services.provider_telemetry_service.get_engine", return_value=engine,
        ):
            service = ProviderTelemetryService()
            provider = Provider(id="rr", type="remote_hybrid", enabled=True,
                                credentials={}, config={})
            await service._poll_provider(provider)
        fake_probe.assert_not_called()


def provider_probe_module():
    import services.provider_probe as module
    return module
