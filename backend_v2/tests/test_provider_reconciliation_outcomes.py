"""An engine that answered must not leave the backend claiming it is still busy.

`ProviderLifecycleService.trigger_reconciliation` runs the in-process
reconciler and persists a state derived from the reconciler's own `status`
field — never from a transport detail. The property: **the state written is a
function of the engine's `status`, not of how it was invoked.**
Parametrised over the whole vocabulary the reconciler actually returns, so a
new status has to be classified rather than silently defaulting.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.provider_lifecycle_service import (
    _RECONCILIATION_FAILED_STATUSES,
    _RECONCILIATION_IN_FLIGHT_STATUSES,
    ProviderLifecycleService,
)


def _service(worker_type: str = "llm") -> ProviderLifecycleService:
    """A real `ProviderLifecycleService`, with only the outside world faked.

    Built through `__init__` rather than `__new__` so the test exercises the same
    object the route gets; `trigger_reconciliation` reads `self.provider_service`,
    `self.status_service` and the module-level `resolve_provider_runtime_async` /
    `trigger_in_process_reconciliation`, and patching those is the whole seam.
    """
    provider_service = MagicMock()
    provider_service.get_provider = AsyncMock(
        return_value=SimpleNamespace(
            id="llm-local",
            type="llm-local",
            worker_type=worker_type,
        )
    )

    # `upsert_reconciliation_state` records what the caller decided, so the test
    # reads the decision rather than the route's return value.
    written: list[dict] = []

    def _upsert(provider_id, state):
        written.append(state)
        return {"provider_id": provider_id, **state}

    provider_service.upsert_reconciliation_state = _upsert

    status_service = MagicMock()
    status_service.normalize_reconciliation_for_card = lambda state: state

    svc = ProviderLifecycleService(
        session=MagicMock(),
        provider_service=provider_service,
    )
    svc.status_service = status_service
    svc.written = written
    return svc


async def _trigger(svc: ProviderLifecycleService, status, **extra):
    """Call `trigger_reconciliation` with the reconciler's answer in place.

    `await`ed *inside* the patch context on purpose: returning the coroutine
    would let both patches expire before it ran, and the real resolver would
    answer — which fails for an `llm-local` fake, since an LLM provider has no
    model tree and reports `supports_reconciliation` accordingly.
    """
    result = {"status": status, "message": extra.pop("message", f"reconciler said {status}")}
    result.update(extra)
    with patch(
        "services.provider_lifecycle_service.resolve_provider_runtime_async",
        return_value=SimpleNamespace(mode="in_process"),
    ), patch(
        "services.in_process_reconciliation.trigger_in_process_reconciliation",
        AsyncMock(return_value=result),
    ):
        return await svc.trigger_reconciliation("llm-local")


class TestTheEngineStatusDecidesTheStoredState:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", sorted(_RECONCILIATION_IN_FLIGHT_STATUSES))
    async def test_an_in_flight_status_stays_reconciling(self, status):
        svc = _service()

        result = await _trigger(svc, status)

        assert result["status"] == "triggered", (
            f"{status!r} means the reconciler is working, so the "
            "provider is legitimately busy"
        )
        assert svc.written[0]["status"] == "reconciling"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status", ["ok", "skipped", "completed", "already-reconciled", "not_supported"]
    )
    async def test_a_terminal_status_does_not_leave_the_provider_busy(self, status):
        """The defect. `ok` and `skipped` are what engines with no model tree send."""
        svc = _service()

        result = await _trigger(svc, status, message="nothing to reconcile")

        assert result["status"] == "completed", (
            f"reconciler answered {status!r}, which is a finished answer, but the "
            "provider was recorded as 'reconciling' for three hours"
        )
        assert svc.written[0]["status"] == "completed"
        assert svc.written[0]["status"] != "reconciling"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", sorted(_RECONCILIATION_FAILED_STATUSES))
    async def test_an_error_status_is_recorded_as_failed(self, status):
        svc = _service()

        result = await _trigger(svc, status, message="storage unreachable")

        assert result["status"] == "failed"
        assert svc.written[0]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_an_unknown_status_is_treated_as_terminal_not_as_busy(self):
        """Fails safe.

        Defaulting an unrecognised status to "reconciling" is what produced a
        three-hour lie; defaulting it to a terminal state can at worst lose a
        progress bar, and the message names the reconciler's own word so an operator
        can see what happened.
        """
        svc = _service()

        result = await _trigger(svc, "something-new")

        assert result["status"] == "completed"
        assert "something-new" in result["message"]

    @pytest.mark.asyncio
    async def test_a_statusless_answer_is_not_read_as_busy(self):
        """A reconciler answer with no status field must not leave the provider
        busy — it is recorded terminal, not in flight."""
        svc = _service()
        with patch(
            "services.provider_lifecycle_service.resolve_provider_runtime_async",
            return_value=SimpleNamespace(mode="in_process"),
        ), patch(
            "services.in_process_reconciliation.trigger_in_process_reconciliation",
            AsyncMock(return_value={"message": "empty answer"}),
        ):
            result = await svc.trigger_reconciliation("llm-local")

        assert result["status"] == "completed"
        assert svc.written[0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_the_reconcilers_note_is_surfaced_verbatim(self):
        """`skipped` carries a `note` explaining what was skipped. An operator
        staring at a provider card needs that sentence, not "reconciliation
        started"."""
        svc = _service()
        note = "no model storage configured; nothing to reconcile"

        result = await _trigger(svc, "skipped", message=note)

        assert result["message"] == note

    @pytest.mark.asyncio
    async def test_a_reconciler_crash_propagates_without_a_busy_write(self):
        """An engine that raises is a failure worth surfacing, not a silent
        success — so this asserts the caller still learns about it AND that no
        "reconciling" state was persisted."""
        svc = _service()
        with patch(
            "services.provider_lifecycle_service.resolve_provider_runtime_async",
            return_value=SimpleNamespace(mode="in_process"),
        ), patch(
            "services.in_process_reconciliation.trigger_in_process_reconciliation",
            AsyncMock(side_effect=RuntimeError("engine blew up")),
        ):
            with pytest.raises(RuntimeError):
                await svc.trigger_reconciliation("llm-local")

        assert not svc.written, "a crashed trigger must not record the provider as busy"


class TestOnlyImageProvidersReportImageModelCounts:
    """`is_image_provider` was `worker_type == "llm"`, so TTS fell through.

    Live on the running stack, `tts-modal-hp196`:
    `"worker_type": "tts", "declared_capabilities": ["tts"]` alongside
    `"is_image_provider": true, "catalog_models": 525, "total_models": 0`.

    A TTS provider does not install image models, so a catalogue count on its
    card is fiction — and 525 is the size of the whole image catalogue on this
    instance. The docstring already said "an LLM provider reports all zeros"; TTS
    has the same property and was not considered.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("worker_type", ["tts", "llm"])
    async def test_a_non_image_worker_reports_no_image_models(self, worker_type):
        from services.provider_status_service import ProviderStatusService

        svc = ProviderStatusService.__new__(ProviderStatusService)
        svc.provider_service = MagicMock()
        svc.provider_service.get_provider = AsyncMock(
            return_value=SimpleNamespace(id=f"{worker_type}-x", worker_type=worker_type)
        )

        result = await svc.get_provider_sync_stats(f"{worker_type}-x")

        assert result["is_image_provider"] is False, (
            f"worker_type {worker_type!r} reported itself as an image provider, "
            "so its card claimed to track the image model catalogue"
        )
        assert result["catalog_models"] is None
        assert result["has_install_intent"] is False
        assert result["total_models"] == 0

    @pytest.mark.asyncio
    async def test_an_image_worker_still_reports_its_counts(self):
        """The other direction, so the fix is not just "always return zeros"."""
        from services.provider_status_service import ProviderStatusService

        svc = ProviderStatusService.__new__(ProviderStatusService)
        svc.session = MagicMock()
        svc.provider_service = MagicMock()
        svc.provider_service.get_provider = AsyncMock(
            return_value=SimpleNamespace(id="modal-hp196", worker_type="image")
        )
        svc.provider_service.get_provider_model_statuses = AsyncMock(
            return_value=[
                {"id": 1, "status": "installed", "version_data": {"files": [{"size": 1}]}},
            ]
        )
        svc.provider_service.get_provider_models = AsyncMock(return_value=[{"id": 1}])

        result = await svc.get_provider_sync_stats("modal-hp196")

        assert result["is_image_provider"] is True
        assert result["catalog_models"] is not None


class TestReconcilerStoragePathKeying:
    """What path a listed file is filed under.

    The listing is matched against `get_all_storage_paths()`, which builds
    `models/{model.directory}/{filename}` — a directory that may itself hold
    an intermediate segment (`ultralytics/bbox`). Keying a listed file on
    `directory + basename` drops any segment beyond the requested directory,
    so a nested file matches nothing: it is re-marked pending forever and
    reported as an orphan on every tick.
    """

    def test_a_reported_path_is_used_verbatim(self):
        from services.in_process_reconciliation import _storage_path_for_entry

        entry = {"name": "yolo.pt", "path": "models/checkpoints/sub/yolo.pt", "size": 1}

        assert _storage_path_for_entry(entry, "models/checkpoints") == (
            "models/checkpoints/sub/yolo.pt"
        )

    def test_a_nested_directory_directory_is_preserved(self):
        """`directory` from MODEL_DIRECTORIES can be two segments deep."""
        from services.in_process_reconciliation import _storage_path_for_entry

        entry = {"name": "yolo.pt", "path": "models/ultralytics/seg/yolo.pt"}

        assert _storage_path_for_entry(entry, "models/ultralytics/seg") == (
            "models/ultralytics/seg/yolo.pt"
        )

    def test_storage_path_is_accepted_as_the_path(self):
        from services.in_process_reconciliation import _storage_path_for_entry

        entry = {"name": "x.pt", "storage_path": "models/loras/deep/x.pt"}

        assert _storage_path_for_entry(entry, "models/loras") == "models/loras/deep/x.pt"

    def test_a_name_only_entry_falls_back_to_directory(self):
        """Payloads that never send a path keep the old, correct behaviour."""
        from services.in_process_reconciliation import _storage_path_for_entry

        assert _storage_path_for_entry({"name": "sd.ckpt"}, "models/checkpoints") == (
            "models/checkpoints/sd.ckpt"
        )

    def test_an_entry_with_neither_is_dropped(self):
        from services.in_process_reconciliation import _storage_path_for_entry

        assert _storage_path_for_entry({"size": 12}, "models/checkpoints") is None
        assert _storage_path_for_entry({}, "models/checkpoints") is None

    def test_decomposed_nfd_path_is_normalized_to_nfc(self):
        """Filesystem returning NFD (e.g. Google Drive/Colab FUSE) is normalized to NFC."""
        import unicodedata
        from services.in_process_reconciliation import _storage_path_for_entry

        nfd_filename = unicodedata.normalize("NFD", "ako_amau_天雨アコ_-_blue_archive_ブ_booru_430792.safetensors")
        nfd_path = f"models/loras/{nfd_filename}"
        assert nfd_filename != unicodedata.normalize("NFC", nfd_filename)

        entry = {"name": nfd_filename, "path": nfd_path}
        expected_nfc = unicodedata.normalize("NFC", nfd_path)
        assert _storage_path_for_entry(entry, "models/loras") == expected_nfc

    def test_decomposed_nfd_name_only_is_normalized_to_nfc(self):
        import unicodedata
        from services.in_process_reconciliation import _storage_path_for_entry

        nfd_filename = unicodedata.normalize("NFD", "deltaデルタ_the_eminence_in_shado_v1_illustrious_1330640.safetensors")
        entry = {"name": nfd_filename}
        expected_nfc = unicodedata.normalize("NFC", f"models/loras/{nfd_filename}")
        assert _storage_path_for_entry(entry, "models/loras") == expected_nfc
