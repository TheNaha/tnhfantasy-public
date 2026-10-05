"""Progress events state their unit on the wire.

The normalisation in `provider_core/utils.py` ends in percent 0..100 — the
`TaskEvent.value` comment has said so since before this file existed. What it did
not do was make that a *fact* rather than a convention, and the receiver did not
assume it:

    backend_v2/services/provider_client.py
        val = ev.get("value") or 0
        # Canonical worker events carry percent 0..100; legacy deployed
        # containers still emit 0..1 fractions until they are redeployed.
        percent = int(val * 100) if val <= 1 else int(val)

So a worker reporting exactly `value == 1` — one percent done — is recorded as
100 percent, and the job's progress bar jumps from nothing to finished. No worker
has emitted a fraction since the normalisation above, so the branch has nothing
left to detect and can only misfire.

The re-heuristic lives in the backend, which another agent owns, so these tests
pin what this side can own: that every progress event names its unit, and that the
value is in 0..100 including at the boundary the heuristic breaks on.
"""

from __future__ import annotations

import pytest


def _progress(update):
    from provider_core.utils import comfy_status_to_task_event

    return comfy_status_to_task_event(update, job_id="beam-worker")


class TestEveryProgressEventNamesItsUnit:
    @pytest.mark.parametrize(
        "update",
        [
            {"status": "progress", "value": 1, "max": 100},
            {"status": "progress", "value": 0, "max": 100},
            {"status": "progress", "value": 100, "max": 100},
            {"status": "progress", "value": 50, "max": 200},
            {"status": "progress", "progress": {"value": 3, "max": 7}},
            {"status": "progress", "value": 42},
        ],
    )
    def test_the_unit_is_on_the_wire(self, update):
        event = _progress(update)
        assert event is not None, update
        assert event.event == "progress"
        assert event.value_unit == "percent", event.model_dump()

    @pytest.mark.parametrize(
        "update",
        [
            {"status": "progress", "value": 1, "max": 100},
            {"status": "progress", "value": 50, "max": 200},
            {"status": "progress", "progress": {"value": 3, "max": 7}},
            {"status": "progress", "value": 42},
        ],
    )
    def test_the_value_is_percent_so_a_reader_needs_no_heuristic(self, update):
        """The backend's line, restated: `int(val * 100) if val <= 1 else int(val)`.

        `value == 1` is the only value the two readings disagree about, and it is
        reachable — one step of a 100-step sampler is a completely ordinary first
        progress event.
        """
        event = _progress(update)
        assert event.value is not None, update
        assert 0.0 <= event.value <= 100.0, event.value

    def test_the_one_percent_case_is_one_percent(self):
        event = _progress({"status": "progress", "value": 1, "max": 100})
        assert event.value == 1, (
            "1/100 is one percent; a receiver applying `val * 100 if val <= 1` "
            "records it as 100"
        )
        assert event.value_unit == "percent"


class TestNonProgressEventsAreUnchanged:
    @pytest.mark.parametrize(
        "update",
        [
            {"status": "executing", "node": "1"},
            {"status": "error", "message": "boom"},
            {"status": "cancelled"},
            # `queued` and `execution_start` emit no event at all.
            {"status": "queued"},
            {"status": "execution_start"},
        ],
    )
    def test_no_unit_is_claimed_where_none_applies(self, update):
        """`value_unit` describes a `value`; a node event has neither."""
        event = _progress(update)
        if event is None:
            return  # queued / execution_start emit nothing at all
        assert event.event != "progress", event.model_dump()
        assert event.value_unit is None, event.model_dump()

    def test_a_progress_with_no_readable_value_still_declares_the_unit(self):
        """`value=None` with nothing to derive it from — the shape the backend
        reducer has a coercion for. Still labelled `progress`, so the unit belongs
        on it."""
        event = _progress({"status": "progress"})
        assert event.event == "progress", event.model_dump()
        assert event.value is None, event.model_dump()
        assert event.value_unit == "percent", event.model_dump()

    def test_a_populated_success_is_not_a_progress_event(self):
        """The control for the one above. ComfyUI's terminal status is `success`,
        and its images become `outputs`."""
        import base64

        event = _progress(
            {
                "status": "success",
                "images": [
                    {
                        "filename": "a.png",
                        "subfolder": "",
                        "type": "output",
                        "data": base64.b64encode(b"x").decode(),
                    }
                ],
            }
        )
        assert event.event == "completed", event.model_dump()
        assert event.value_unit is None, event.model_dump()


class TestTheFieldSurvivesSerialisation:
    def test_it_is_in_the_ndjson_the_backend_reads(self):
        from provider_core.utils import comfy_status_to_task_event

        line = comfy_status_to_task_event(
            {"status": "progress", "value": 1, "max": 100}, job_id="beam-worker"
        ).to_ndjson()

        import json

        assert json.loads(line)["value_unit"] == "percent", line

    def test_it_is_optional_for_compatibility(self):
        """Additive on the wire only. The backend reads events as plain dicts
        (`ev.get("value")`), so an extra key cannot fail a parse — but the field
        must still default, so anything constructing a TaskEvent by hand keeps
        working."""
        from provider_core.models import TaskEvent

        assert TaskEvent(event="progress", value=1).value_unit is None
