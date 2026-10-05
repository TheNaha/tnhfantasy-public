"""A worker that answered must not leave the backend claiming it is still busy.

`ProviderLifecycleService.trigger_reconciliation` used to treat any HTTP 200 from
`POST /reconcile` as "work started" and persist:

    status  "reconciling"
    phase   "starting"
    message "Reconciliation started in worker"

That is true for `image_worker`, which spawns a task and then POSTs progress to
`/api/v2/providers/{id}/reconciliation-event` until it finishes. It is false for
the LLM and TTS workers, which have no model tree to reconcile: they answer
`{"status": "ok"}` or `{"status": "skipped", "note": ...}` with counts,
synchronously, and never push a terminal state — so nothing ever moves the row
off "reconciling".

Live proof on the running stack, two providers frozen at
`status: "reconciling", phase: "starting", message: "Reconciliation started in
worker"` with `updated_at` unchanged:

    llm-local          worker_type "llm"   total_models 0
    tts-modal-hp196    worker_type "tts"   total_models 0

`RECONCILIATION_IN_PROGRESS_TTL` is 10800s — three hours — so each manual
trigger produced three hours of a provider card claiming to be busy while the
worker had answered in milliseconds. The same file's `setup_models`, twenty
lines away, already read `worker_status` and branched on it.

The property: **the state written on a 200 is a function of the worker's own
`status` field, not of the HTTP code alone.** Parametrised over the whole
vocabulary the three workers actually use, so a new status has to be classified
rather than silently defaulting to one of two answers.
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
    `self.status_service` and the module-level `get_http_client` /
    `resolve_provider_runtime_async`, and patching those four is the whole seam.
    """
    provider_service = MagicMock()
    provider_service.get_provider = AsyncMock(
        return_value=SimpleNamespace(
            id="llm-local",
            type="llm-local",
            worker_type=worker_type,
            container_config={"port": 8001},
        )
    )
    provider_service.start_reconciliation_session = AsyncMock(
        return_value={"accepted": True, "already_running": False}
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
        container_manager=MagicMock(),
    )
    svc.status_service = status_service
    svc.written = written
    return svc


async def _trigger(svc: ProviderLifecycleService, response):
    """Call `trigger_reconciliation` with the worker's answer in place.

    `await`ed *inside* the patch context on purpose: returning the coroutine
    would let both patches expire before it ran, and the real resolver would
    answer — which fails for an `llm-local` fake, since an LLM provider has no
    model tree and reports `supports_reconciliation` accordingly.
    """
    http_client = MagicMock()
    http_client.post = AsyncMock(return_value=response)
    with patch(
        "services.provider_lifecycle_service.resolve_provider_runtime_async",
        return_value=SimpleNamespace(
            supports_reconciliation=True,
            mode="container_http",
            worker_url="http://worker:8000",
        ),
    ), patch(
        "services.provider_lifecycle_service.get_http_client",
        return_value=http_client,
    ):
        return await svc.trigger_reconciliation("llm-local")


def _response(status: str | None, **extra) -> MagicMock:
    body: dict = {}
    if status is not None:
        body["status"] = status
    body.update(extra)
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = body
    return resp


class TestTheWorkerStatusDecidesTheStoredState:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", sorted(_RECONCILIATION_IN_FLIGHT_STATUSES))
    async def test_an_in_flight_status_stays_reconciling(self, status):
        svc = _service()
        resp = _response(status)

        result = await _trigger(svc, resp)

        assert result["status"] == "triggered", (
            f"{status!r} means the worker is working and will report back, so the "
            "provider is legitimately busy"
        )
        assert svc.written[0]["status"] == "reconciling"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status", ["ok", "skipped", "completed", "already-reconciled", "not_supported"]
    )
    async def test_a_terminal_status_does_not_leave_the_provider_busy(self, status):
        """The defect. `ok` and `skipped` are what the LLM and TTS workers send."""
        svc = _service()
        resp = _response(status, note="nothing to reconcile")

        result = await _trigger(svc, resp)

        assert result["status"] == "completed", (
            f"worker answered {status!r}, which is a finished answer, but the "
            "provider was recorded as 'reconciling' for three hours"
        )
        assert svc.written[0]["status"] == "completed"
        assert svc.written[0]["status"] != "reconciling"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", sorted(_RECONCILIATION_FAILED_STATUSES))
    async def test_an_error_status_is_recorded_as_failed(self, status):
        svc = _service()
        resp = _response(status, message="storage container unreachable")

        result = await _trigger(svc, resp)

        assert result["status"] == "failed"
        assert svc.written[0]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_an_unknown_status_is_treated_as_terminal_not_as_busy(self):
        """Fails safe.

        Defaulting an unrecognised status to "reconciling" is what produced a
        three-hour lie; defaulting it to a terminal state can at worst lose a
        progress bar, and the message names the worker's own word so an operator
        can see what happened.
        """
        svc = _service()
        resp = _response("something-new")

        result = await _trigger(svc, resp)

        assert result["status"] == "completed"
        assert "something-new" in result["message"]

    @pytest.mark.asyncio
    async def test_a_200_with_no_json_object_is_not_read_as_busy(self):
        """A proxy can answer 200 with an HTML error page, and an older worker
        can answer 200 with a bare list. Neither justifies "still working"."""
        svc = _service()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("not json")

        result = await _trigger(svc, resp)

        assert result["status"] == "completed"
        assert svc.written[0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_the_workers_note_is_surfaced_verbatim(self):
        """`skipped` carries a `note` explaining what was skipped. An operator
        staring at a provider card needs that sentence, not "Reconciliation
        started in worker"."""
        svc = _service()
        note = "no model storage configured; nothing to reconcile"
        resp = _response("skipped", note=note)

        result = await _trigger(svc, resp)

        assert result["message"] == note

    @pytest.mark.asyncio
    async def test_a_non_200_is_recorded_as_failed_and_still_raises(self):
        """A worker that cannot be reached is a failure worth persisting, not a
        silent success — so this asserts the state is written AND that the
        caller still learns about it."""
        svc = _service()
        resp = MagicMock()
        resp.status_code = 502
        resp.json.return_value = {}

        with pytest.raises(Exception):
            await _trigger(svc, resp)

        assert svc.written, "a trigger that failed to reach the worker is a failure"
        assert svc.written[0]["status"] == "failed"


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