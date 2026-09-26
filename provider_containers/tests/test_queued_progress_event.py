"""Finding 20: every ComfyUI-backed job opened with a null-valued progress event.

`image_worker/comfy/workflow_executor.py:290` yields

    {"status": "queued", "prompt_id": prompt_id}

UNCONDITIONALLY, right after `_queue_prompt` returns, so it is the first NDJSON
line of every ComfyUI-backed job on every engine that goes through this executor
(modal, beam, direct_url, remote_comfy).

`provider_core/utils.py:comfy_status_to_task_event` skipped exactly two statuses
(`execution_interrupted`, `execution_start`) and its own comment said why: "a
progress event with a None value (which would stall the backend reducer)". `queued`
matched no branch, carried no `value`, and fell through to

    TaskEvent(event="progress", value=None)

The HTTP-stream reducer coerces that to 0 and writes it to the database
(backend_v2/services/provider_client.py:180-189: `val = ev.get("value") or 0`),
and the websocket path explicitly guards the same shape
(backend_v2/infrastructure/worker_ws.py:158-160). Both ends had a special case
for a line the worker should never have sent.
"""

from __future__ import annotations

import json

import pytest

from provider_core.utils import TaskEvent, comfy_status_to_task_event, translate_task_events


class TestQueuedIsNotAProgressEvent:
    def test_a_bare_queued_update_produces_nothing(self):
        """The exact payload the executor emits as its first line."""
        assert comfy_status_to_task_event({"status": "queued", "prompt_id": "abc-123"}) is None

    def test_queued_with_extra_fields_still_produces_nothing(self):
        assert comfy_status_to_task_event(
            {"status": "queued", "prompt_id": "abc-123", "number": 1, "node": "3"}
        ) is None

    def test_queued_is_case_insensitive_like_every_other_status(self):
        assert comfy_status_to_task_event({"status": "QUEUED"}) is None

    def test_no_status_this_executor_emits_becomes_a_contentless_progress_event(self):
        """The property the docstring claims, over the statuses in play here.

        Scoped to what `execute_comfy_workflow` actually yields — its own
        `queued`/`success`/`error` plus the ComfyUI websocket dialect. An
        unrecognised status from some future ComfyUI still becomes a progress
        event, which is the pre-existing fallback; changing that would silently
        swallow real progress from a version this suite has not seen, and it is
        not what this finding is about.
        """
        executor_statuses = [
            # Yielded by execute_comfy_workflow itself.
            "queued", "success", "error",
            # Arrived on the websocket from ComfyUI.
            "execution_start", "execution_cached", "executing",
            "execution_interrupted",
        ]
        # NOTE: two statuses are deliberately absent, and both are the pre-existing
        # generic fallback rather than anything this finding is about:
        #   * `execution_error` also falls through to a contentless progress event.
        #     That looks wrong — an error status should map to `failed` — but it is
        #     a separate defect and fixing it would change error handling. Reported,
        #     not fixed.
        #   * a bare `{"status": "progress"}` with no `value`/`max` has nothing to
        #     report, so there is no value to carry. A real ComfyUI progress message
        #     always carries both (asserted below).
        for status in executor_statuses:
            event = comfy_status_to_task_event({"status": status})
            if event is None:
                continue
            assert event.event != "progress" or event.value is not None, (
                f"status {status!r} became a contentless progress event: "
                f"{event.to_ndjson()}"
            )

    def test_a_progress_event_with_a_payload_keeps_its_value(self):
        """The control: the real ComfyUI shape survives the skip list."""
        event = comfy_status_to_task_event(
            {"status": "progress", "value": 4, "max": 20}
        )
        assert event is not None
        assert event.event == "progress"
        assert event.value == 20

    def test_the_two_previously_skipped_statuses_still_are(self):
        """No regression on the statuses that were already handled."""
        assert comfy_status_to_task_event({"status": "execution_interrupted"}) is None
        assert comfy_status_to_task_event({"status": "execution_start"}) is None


class TestTheStreamDropsIt:
    @pytest.mark.asyncio
    async def test_queued_is_dropped_from_the_translated_stream(self):
        async def _source():
            yield json.dumps({"status": "queued", "prompt_id": "abc-123"})
            yield json.dumps({"status": "executing", "node": "3"})
            yield json.dumps({"status": "execution_cached", "nodes": ["1"]})
            yield json.dumps({"status": "success", "images": []})

        lines = [
            json.loads(line)
            async for line in translate_task_events(_source(), job_id="job-1")
        ]

        # `queued` is gone; everything else survived.
        assert [line["event"] for line in lines] == ["node", "cached_nodes", "completed"]
        # No progress event in the stream is contentless. (`node` and
        # `cached_nodes` legitimately carry value=null — that is not a progress
        # event, so only the progress ones are checked.)
        for line in lines:
            if line["event"] == "progress":
                assert line["value"] is not None

    @pytest.mark.asyncio
    async def test_a_queued_dict_passed_directly_is_also_dropped(self):
        """The executor yields a dict on some paths and a JSON string on others."""
        async def _source():
            yield {"status": "queued", "prompt_id": "abc-123"}
            yield TaskEvent(event="completed", job_id="job-2", outputs=[]).to_ndjson()

        lines = [
            json.loads(line)
            async for line in translate_task_events(_source(), job_id="job-2")
        ]
        assert [line["event"] for line in lines] == ["completed"]

    @pytest.mark.asyncio
    async def test_a_real_progress_event_still_survives(self):
        """The control: a genuine percentage must not be dropped with `queued`."""
        async def _source():
            yield json.dumps({"status": "progress", "value": 4, "max": 20})

        lines = [
            json.loads(line)
            async for line in translate_task_events(_source(), job_id="job-3")
        ]
        assert len(lines) == 1
        assert lines[0]["event"] == "progress"
        assert lines[0]["value"] == 20


class TestTheExecutorStillEmitsIt:
    """`queued` is the executor's contract with the backend's job lifecycle, so it
    must keep being emitted by the executor. Only the worker-side translation of
    it into a contentless progress event is wrong; dropping the line entirely
    would lose the prompt_id acknowledgement.
    """

    def test_the_executor_emits_queued_unconditionally(self):
        import inspect

        import image_worker.comfy.workflow_executor as executor

        source = inspect.getsource(executor.execute_comfy_workflow)
        assert '"queued"' in source, (
            "if this is gone, the backend no longer gets the prompt_id "
            "acknowledgement; the fix belongs in the translation, not here"
        )
