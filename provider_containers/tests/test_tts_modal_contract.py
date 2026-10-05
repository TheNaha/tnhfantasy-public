"""The TTS Modal client's `event_stream` and file routes, against the app it calls.

Three of the five defects in this area were invisible to the suite because the
tests asserted *shape* — that the client is an `ImageWorkerProviderClient`, that
`select_client` does not route TTS, that `modal_app.py` mentions `TTSWorker`
(parsed with `ast`, never imported) — and never *behaviour*. So:

* `event_stream` re-wrapped every app event as `event="running"` with the real
  payload JSON-stringified into `message`, and then emitted an unconditional
  `completed` outside every `except`. `TaskEvent.outputs` was therefore never
  set, and the backend reducer — which ignores `running`, stores the terminal
  event, and finalizes on it — saw a success with `outputs=[]`. The app's own
  `{"status": "error", "retryable": True}` poll-timeout was reported green.

* The file routes called `modal.Volume.stat.remote`, `Volume.write_file.remote`
  and `Volume.remove_file.remote`. `modal.Volume` has no `stat` and no
  `write_file`, and `remove_file` is a container-local method with no `.remote`.
  `get_file` caught the resulting `AttributeError` as a 404 for files that
  exist; `delete_file` answered `{"status": "missing"}` while the file stayed on
  the volume; `upload_file` had no handler at all.

* `@tts_app.cls(..., keep_warm=0)` raises `DeprecationError` at import — Modal
  renamed it `min_containers` on 2025-02-24 — and `modal deploy` imports the
  module, so the TTS app could not be deployed from this tree at all. The test
  that should have caught it read the file and parsed it with `ast`.

Every test here drives the real code against a fake Modal handle.
"""

from __future__ import annotations

import importlib
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import tts_worker.engines.modal.client as tts_client

def _production_runtime_config():
    """The `runtime_config` a real TTS worker is constructed with.

    `tts_worker/worker.py` calls `build_runtime_config(...)` and hands the result
    to `select_client`. Reproducing it here is the point: it has no
    `job_tracker` key, which is what the old test supplied by hand and what made
    that test pass against a client that was broken in production.
    """
    from provider_core.worker_bootstrap import build_runtime_config

    return build_runtime_config(
        provider_id="tts-modal-hp196",
        backend_url="http://backend_v2:8002",
        storage_dir="/data",
        max_concurrent_downloads=2,
        validation_timeout_seconds=30.0,
        reconciliation_list_timeout_seconds=30.0,
        inference_timeout_seconds=1800.0,
    )


TASK_APP = "tts_worker.engines.modal.modal_app"


# --------------------------------------------------------------------- fakes


class _FakeRemote:
    """A Modal remote-call handle: `thing.method.remote.aio(...)`."""

    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.calls: list[tuple[tuple, dict]] = []

    def aio(self, *args, **kwargs):
        self.calls.append((args, kwargs))

        async def _call():
            if self._error is not None:
                raise self._error
            return self._result

        return _call()


class _FakeRemoteNamespace:
    def __init__(self, result=None, error=None):
        self.remote = _FakeRemote(result=result, error=error)


def _method(result=None, error=None):
    return _FakeRemoteNamespace(result=result, error=error)


class _FakeAppInstance:
    """What `modal.Cls.from_name(...)()` returns: a `run` with `remote_gen.aio`."""

    def __init__(self, events=(), error=None, stall_seconds=0.0):
        self.events = list(events)
        self.error = error
        self.stall_seconds = stall_seconds
        self.run = MagicMock()
        self.run.remote_gen = MagicMock()
        self.run.remote_gen.aio = self._stream

    async def _stream(self, workflow):
        import asyncio

        for event in self.events:
            yield event
        if self.stall_seconds:
            await asyncio.sleep(self.stall_seconds)
        if self.error is not None:
            raise self.error


def _patch_modal_cls(monkeypatch, instance):
    class _FakeCls:
        def __call__(self):
            return instance

    monkeypatch.setattr(
        tts_client.modal.Cls, "from_name", staticmethod(lambda *a, **k: _FakeCls())
    )


async def _drain(response) -> list[dict]:
    """Consume a StreamingResponse and parse its NDJSON TaskEvent lines."""
    events = []
    async for raw in response.body_iterator:
        if isinstance(raw, bytes):
            raw = raw.decode()
        events.append(json.loads(raw))
    return events


def _client():
    return tts_client.ModalTTSProviderClient({"provider_id": "tts-modal-hp196"})


def _workflow_request(timeout_seconds: float | None = None):
    return tts_client.InferenceRequest(
        workflow={"1": {"class_type": "SaveAudio"}}, job_id="job-1", timeout_seconds=timeout_seconds
    )


# ----------------------------------------------------------------------- D1


@pytest.mark.asyncio
class TestEventStreamCarriesOutputs:
    async def test_a_success_event_becomes_completed_with_its_outputs(self, monkeypatch):
        """The whole point: `outputs` must survive, with the app's own fields.

        The TTS app returns `{filename, subfolder, type}` and no base64 bytes —
        the audio stays on the volume. Passing the list through verbatim is what
        gives the backend a path to fetch.
        """
        outputs = [
            {"filename": "line_01.wav", "subfolder": "tts", "type": "output"},
            {"filename": "line_02.wav", "subfolder": "tts", "type": "output"},
        ]
        _patch_modal_cls(
            monkeypatch,
            _FakeAppInstance([{"status": "running", "prompt_id": "p1"},
                              {"status": "success", "prompt_id": "p1", "outputs": outputs}]),
        )

        events = await _drain(await _client().inference(_workflow_request()))

        completed = [e for e in events if e["event"] == "completed"]
        assert len(completed) == 1, events
        assert completed[0]["outputs"] == outputs
        assert completed[0]["job_id"] == "job-1"

    async def test_a_success_is_never_preceded_by_a_fake_completion(self, monkeypatch):
        _patch_modal_cls(
            monkeypatch,
            _FakeAppInstance([{"status": "success", "outputs": []}]),
        )

        events = await _drain(await _client().inference(_workflow_request()))

        assert [e["event"] for e in events] == ["completed"], events


@pytest.mark.asyncio
class TestEventStreamReportsFailureAsFailure:
    async def test_a_permanent_app_error_is_failed_and_not_retryable(self, monkeypatch):
        """`modal_app.py` answers a rejected graph with `retryable: False`; the
        flag is the app's verdict and re-deciding it here as `True` spends real
        money re-running a graph that cannot execute on any other provider."""
        _patch_modal_cls(
            monkeypatch,
            _FakeAppInstance(
                [{"status": "error", "message": "ComfyUI rejected the workflow: boom",
                  "retryable": False}]
            ),
        )

        events = await _drain(await _client().inference(_workflow_request()))

        failed = [e for e in events if e["event"] == "failed"]
        assert len(failed) == 1, events
        assert failed[0]["retryable"] is False
        assert "ComfyUI rejected the workflow" in failed[0]["message"]
        assert not [e for e in events if e["event"] == "completed"], (
            "a failure followed by `completed` is the exact shape that made a "
            "TTS job go green with no audio and no error"
        )

    async def test_the_apps_poll_timeout_is_a_retryable_failure(self, monkeypatch):
        """`modal_app.py:305-309` yields `{"status": "error", "retryable": True}`
        after `TIMEOUT` seconds of polling. That is a genuine transient — worth
        another provider — and it was being reported as a success."""
        _patch_modal_cls(
            monkeypatch,
            _FakeAppInstance(
                [{"status": "error", "message": "Timed out after 1800s", "retryable": True}]
            ),
        )

        events = await _drain(await _client().inference(_workflow_request()))

        failed = [e for e in events if e["event"] == "failed"]
        assert len(failed) == 1, events
        assert failed[0]["retryable"] is True
        assert "Timed out" in failed[0]["message"]
        assert not [e for e in events if e["event"] == "completed"], events

    async def test_the_clients_own_deadline_is_a_retryable_failure(self, monkeypatch):
        """The other timeout: the app's generator stops answering entirely."""
        _patch_modal_cls(monkeypatch, _FakeAppInstance(stall_seconds=5.0))

        events = await _drain(
            await _client().inference(_workflow_request(timeout_seconds=0.01))
        )

        failed = [e for e in events if e["event"] == "failed"]
        assert len(failed) == 1, events
        assert failed[0]["retryable"] is True
        assert "timed out" in failed[0]["message"].lower()

    async def test_an_uncaught_app_exception_is_reported_and_not_completed(self, monkeypatch):
        _patch_modal_cls(
            monkeypatch, _FakeAppInstance(error=RuntimeError("container went away"))
        )

        events = await _drain(await _client().inference(_workflow_request()))

        failed = [e for e in events if e["event"] == "failed"]
        assert len(failed) == 1, events
        assert "container went away" in failed[0]["message"]
        assert not [e for e in events if e["event"] == "completed"], events

    async def test_a_truncated_stream_fails_instead_of_inventing_a_completion(self, monkeypatch):
        """No terminal event at all. The old code appended `completed` here, so
        a container that died mid-run produced a green job with `outputs=[]`."""
        _patch_modal_cls(
            monkeypatch, _FakeAppInstance([{"status": "running", "prompt_id": "p1"}])
        )

        events = await _drain(await _client().inference(_workflow_request()))

        assert [e["event"] for e in events] == ["failed"], events
        assert events[0]["retryable"] is True

    async def test_the_job_tracker_is_released_even_on_a_failure(self, monkeypatch):
        """The tracker is a process singleton, so the fake has to be installed as
        one. Passing it as `runtime_config["job_tracker"]` used to work here and
        nowhere in production — `build_runtime_config` has no such key, and the
        client read it instead of the tracker its base class had already
        installed. That left `self.job_tracker` `None` on every real deployment:
        `POST /cancel-job` answered 500 and `inference` registered nothing.
        """
        tracker = MagicMock()
        tracker.start_job = AsyncMock()
        tracker.end_job = AsyncMock()
        # Patched where it is *looked up*: `base_client.py` binds
        # `get_job_tracker` into its own namespace at import time, so patching
        # `provider_core.background` would miss it — the same late-binding
        # mistake `test_app_boot_smoke.py` documents for the lifespan.
        monkeypatch.setattr(
            "provider_core.base_client.get_job_tracker", lambda: tracker
        )
        _patch_modal_cls(
            monkeypatch,
            _FakeAppInstance([{"status": "error", "message": "nope", "retryable": False}]),
        )
        client = tts_client.ModalTTSProviderClient(_production_runtime_config())

        await _drain(await client.inference(_workflow_request()))

        tracker.start_job.assert_awaited_once_with("job-1")
        tracker.end_job.assert_awaited_once_with("job-1")


class TestTheTrackerIsTheOneProductionBuilds:
    """The tracker is a process singleton, not a `runtime_config` entry.

    `ModalTTSProviderClient.__init__` overwrote the tracker that
    `BaseProviderClient.__init__` had just installed with
    `runtime_config.get("job_tracker")` — a key `build_runtime_config` has never
    produced. In production `self.job_tracker` was therefore always `None`:

      * `BaseProviderClient.cancel_job` raised
        `AttributeError: 'NoneType' object has no attribute 'cancel_job'`, so
        `POST /cancel-job` returned a 500 with `retryable: true`.
      * `inference` guards `start_job`/`end_job` on `if job_id and
        self.job_tracker`, so nothing was ever registered and a cancellation
        could not be observed mid-stream.

    The old test could not see it because it constructed the client with
    `{"provider_id": "p", "job_tracker": tracker}` — a shape no caller builds.
    Every test here goes through the real construction path instead:
    `select_client(TTS_ENGINES, ENGINE, build_runtime_config(...))`, which is
    what `tts_worker/worker.py` does.
    """

    def test_a_client_built_the_production_way_has_a_tracker(self):
        from provider_core.worker_bootstrap import TTS_ENGINES, select_client

        runtime_config = _production_runtime_config()
        # Nothing named `job_tracker`, which is the whole point.
        assert "job_tracker" not in runtime_config

        client = select_client(TTS_ENGINES, "modal", runtime_config)

        assert client.job_tracker is not None, (
            "the TTS client has no job tracker, so /cancel-job raises "
            "AttributeError and cancellation is never tracked"
        )
        assert hasattr(client.job_tracker, "cancel_job")

    def test_the_singleton_is_shared_with_the_base_client(self):
        """Not merely present: the *same* tracker every other route cancels on."""
        from provider_core.background import get_job_tracker

        client = tts_client.ModalTTSProviderClient(_production_runtime_config())

        assert client.job_tracker is get_job_tracker()

    @pytest.mark.asyncio
    async def test_cancel_job_does_not_raise(self):
        """The end-to-end symptom: the route used to answer 500."""
        from provider_core.models import CancelJobRequest

        client = tts_client.ModalTTSProviderClient(_production_runtime_config())

        # `cancel_job` on a job the tracker has never seen returns a falsy
        # "not cancelled" verdict; what matters is that it returns at all rather
        # than raising `AttributeError` on `None`.
        result = await client.cancel_job(CancelJobRequest(job_id="never-seen"))
        assert result is not None
        assert result.get("status") in {"cancelled", "not_found", "not_running", "ok"}


@pytest.mark.asyncio
class TestEventStreamHandlesTheWireShapesModalActuallyDelivers:
    async def test_a_json_string_event_is_parsed(self, monkeypatch):
        """`remote_gen` can deliver a string, and the app itself may be an older
        deployment. The old code did `json.loads` then discarded the fields; now
        the fields decide the event."""
        _patch_modal_cls(
            monkeypatch,
            _FakeAppInstance(
                ['{"status": "success", "prompt_id": "p1", '
                 '"outputs": [{"filename": "a.wav", "subfolder": "", "type": "output"}]}']
            ),
        )

        events = await _drain(await _client().inference(_workflow_request()))

        assert [e["event"] for e in events] == ["completed"], events
        assert events[0]["outputs"] == [
            {"filename": "a.wav", "subfolder": "", "type": "output"}
        ]

    async def test_a_running_heartbeat_produces_no_event(self, monkeypatch):
        """The app polls once a second. `event="progress"` with no value is the
        contentless frame `comfy_status_to_task_event` documents as an
        anti-pattern, and the backend reducer has no branch for a bare
        `running` either — so one forwards nothing."""
        _patch_modal_cls(
            monkeypatch,
            _FakeAppInstance([{"status": "running", "prompt_id": "p1"}] * 5),
        )

        events = await _drain(await _client().inference(_workflow_request()))

        assert [e["event"] for e in events] == ["failed"], events
        assert "without a terminal event" in events[0]["message"]

    async def test_an_unreadable_payload_is_a_permanent_failure(self, monkeypatch):
        _patch_modal_cls(monkeypatch, _FakeAppInstance(["not json at all"]))

        events = await _drain(await _client().inference(_workflow_request()))

        assert [e["event"] for e in events] == ["failed"], events
        assert events[0]["retryable"] is False


class TestTaskEventForUpdateIsTotal:
    """The translator on its own, because the app's vocabulary is the contract."""

    @pytest.mark.parametrize(
        "update",
        [
            None,
            123,
            b'{"status": "success"}',
            "[]",
            "not json",
            {"status": "unknown-thing"},
            {},
        ],
    )
    def test_nothing_unreadable_raises(self, update):
        result = tts_client.task_event_for_update(update, "job-1")
        if result is not None:
            assert result.event in {"failed", "cancelled", "completed"}

    def test_a_cancelled_app_event_stays_cancelled(self):
        event = tts_client.task_event_for_update(
            {"status": "cancelled", "message": "stopped"}, "job-1"
        )
        assert event.event == "cancelled"
        assert event.message == "stopped"

    def test_outputs_default_to_a_list_not_none(self):
        """`outputs=[]` rather than `None`, so the backend's
        `ev.get("outputs") or []` and a JSON consumer agree."""
        event = tts_client.task_event_for_update({"status": "success"})
        assert event.outputs == []


# ----------------------------------------------------------------------- D4


@pytest.mark.asyncio
class TestFileRoutesUseTheAppsClass:
    """`modal.Volume` has no `stat` and no `write_file`, and its `remove_file`
    is container-local with no `.remote`. These assertions fail against the real
    installed `modal` package if a route goes back to the handle."""

    async def test_get_file_reads_through_the_storage_class(self, monkeypatch):
        storage = MagicMock()
        storage.file_size = _method(result=11)
        storage.read_file = _method(result=b"RIFFfakewave")
        _patch_storage(monkeypatch, storage)

        response = await _client().get_file("output/tts/a.wav")

        assert response.body == b"RIFFfakewave"
        assert storage.file_size.remote.calls[0][0] == ("output/tts/a.wav",)

    async def test_get_file_404s_only_for_a_file_that_is_really_absent(self, monkeypatch):
        """The old code caught bare `Exception` around a `Volume.stat` that does
        not exist, so every request — including for files that exist — was a 404."""
        storage = MagicMock()
        storage.file_size = _method(error=FileNotFoundError("nope"))
        _patch_storage(monkeypatch, storage)

        with pytest.raises(HTTPException) as exc:
            await _client().get_file("output/tts/missing.wav")
        assert exc.value.status_code == 404

    async def test_get_file_does_not_swallow_a_transport_failure_into_a_404(self, monkeypatch):
        storage = MagicMock()
        storage.file_size = _method(error=ConnectionError("modal unreachable"))
        _patch_storage(monkeypatch, storage)

        with pytest.raises(ConnectionError):
            await _client().get_file("output/tts/a.wav")

    async def test_get_file_refuses_a_file_over_the_audio_ceiling(self, monkeypatch):
        storage = MagicMock()
        storage.file_size = _method(result=tts_client._MAX_AUDIO_BYTES + 1)
        storage.read_file = _method(result=b"")
        _patch_storage(monkeypatch, storage)

        with pytest.raises(HTTPException) as exc:
            await _client().get_file("models/checkpoints/huge.safetensors")
        assert exc.value.status_code == 413
        assert storage.read_file.remote.calls == []

    async def test_upload_file_writes_through_the_storage_class(self, monkeypatch):
        import base64

        storage = MagicMock()
        storage.put_file = _method(result=5)
        _patch_storage(monkeypatch, storage)

        request = MagicMock()
        request.directory = "input"
        request.filename = "ref.wav"
        request.content_base64 = base64.b64encode(b"hello").decode()

        result = await _client().upload_file(request)

        args, kwargs = storage.put_file.remote.calls[0]
        assert kwargs["path"] == "input/ref.wav"
        assert kwargs["content"] == b"hello"
        assert args == ()
        assert result["path"] == "input/ref.wav"
        assert result["size"] == 5

    async def test_delete_file_reports_missing_without_claiming_it_deleted(self, monkeypatch):
        """`{"status": "missing"}` with HTTP 200 was what the old route returned
        for a file it had never removed, so the caller believed a successful
        delete of a file still on the volume."""
        storage = MagicMock()
        storage.delete_file = _method(result=False)
        _patch_storage(monkeypatch, storage)

        result = await _client().delete_file("output/tts/a.wav")

        assert result["status"] == "error"
        assert result["code"] == 404
        assert storage.delete_file.remote.calls[0][0] == ("output/tts/a.wav",)

    async def test_delete_file_reports_a_real_delete(self, monkeypatch):
        storage = MagicMock()
        storage.delete_file = _method(result=True)
        _patch_storage(monkeypatch, storage)

        result = await _client().delete_file("output/tts/a.wav")

        assert result["status"] == "success"
        assert result["success"] is True


def _patch_storage(monkeypatch, storage):
    class _FakeCls:
        def __call__(self):
            return storage

    monkeypatch.setattr(
        tts_client.modal.Cls, "from_name", staticmethod(lambda *a, **k: _FakeCls())
    )


# ----------------------------------------------------------------------- D3


class TestTheTTSAppIsImportable:
    """`modal deploy` imports this module, so anything that raises at import is
    an app that cannot be deployed. `tests/test_tts_app_routing.py` used to
    `ast.parse` the file instead of importing it, which is why `keep_warm=0`
    shipped: the name is syntactically fine and raises only at decoration."""

    def test_it_imports(self):
        module = importlib.import_module(TASK_APP)
        assert module.TTS_APP_NAME

    def test_the_worker_class_exists_after_import(self):
        module = importlib.import_module(TASK_APP)
        assert module.TTSWorker is not None
        assert module.TTSFileStorage is not None

    def test_the_storage_class_the_client_asks_for_is_the_one_the_app_defines(self):
        """A rename on one side only fails at the first file route — and a 404
        that reads as "no such file" is exactly what that produced."""
        module = importlib.import_module(TASK_APP)
        assert hasattr(module, tts_client.TTS_STORAGE_CLASS_NAME)
        assert hasattr(module, tts_client.TTS_CLASS_NAME)

    def test_no_removed_modal_parameter_is_passed(self):
        """`keep_warm` was renamed `min_containers` on 2025-02-24 and the
        decorator now raises `DeprecationError`."""
        import modal

        module = importlib.import_module(TASK_APP)
        with pytest.raises(modal.exception.DeprecationError):
            modal.App("probe").cls(image=module.tts_image, keep_warm=0)
