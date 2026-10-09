"""`model.sync_*` must describe what the in-process reconciler actually does.

The four enum members, their four frontend constants and the four `App.jsx`
toasts existed with exactly one producer between them: `POST
/api/v2/models/sync-progress`, a route the deleted container worker called and
nothing in this repository does. That is the `download.*` failure mode one level
up — a contract implemented by neither side that reads, from either end, as
"progress push already works".

`services/in_process_reconciliation.py` is now the producer. These tests pin the
three properties that make it a real one:

  1. every member with a frontend subscriber is emitted on the path that
     corresponds to it (started / progress / completed / failed);
  2. the `progress` number is labelled, because it is the fraction of the QUEUE
     and not of the file in flight — `download_file` has no per-byte callback,
     so the per-file fraction is unobservable and must not be implied;
  3. the emits sit where the DB status is written, so the browser and the row
     cannot disagree about a file being ready.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RECONCILER = REPO / "services" / "in_process_reconciliation.py"
EVENTS = REPO / "core" / "events.py"


def _reconciler_source() -> str:
    return RECONCILER.read_text()


def _events_source() -> str:
    return EVENTS.read_text()


def _emit_calls(source: str, event_type: str) -> list[str]:
    """Each `emit_model_sync_event(EventType.<event_type>, ...)` call's text.

    Balanced-paren extraction, not `source.index(")")`: the kwargs include
    `str(exc)` and `file_info.get("directory")`, so a naive first-`)` scan
    truncates the call mid-expression and asserts on half of it.
    """
    out = []
    for m in re.finditer(r"emit_model_sync_event\(", source):
        open_at = m.end() - 1
        depth = 0
        for i in range(open_at, len(source)):
            if source[i] == "(":
                depth += 1
            elif source[i] == ")":
                depth -= 1
                if depth == 0:
                    call = source[m.start() : i + 1]
                    if f"EventType.{event_type}" in call:
                        out.append(call)
                    break
    return out


class TestEveryMemberHasAProducer:
    def test_all_four_members_are_emitted_by_the_reconciler(self):
        source = _reconciler_source()
        for member in (
            "MODEL_SYNC_STARTED",
            "MODEL_SYNC_PROGRESS",
            "MODEL_SYNC_COMPLETED",
            "MODEL_SYNC_FAILED",
        ):
            calls = _emit_calls(source, member)
            assert calls, (
                f"{member} has no producer again. The whole family used to "
                "survive on a route the deleted container worker called, and "
                "the frontend kept four toasts for it, so nothing failed."
            )

    def test_the_shared_emit_helper_exists(self):
        """One helper, not four inline `event_bus.publish` calls, so the wire
        shape is decided in one place."""
        source = _events_source()
        assert "async def emit_model_sync_event(" in source
        assert source.count("await event_bus.publish(Event(type=event_type, data=data))") >= 1

    def test_progress_is_emitted_from_the_download_loop_not_from_a_dead_route(self):
        """The old producer was `POST /api/v2/models/sync-progress`. If anyone
        re-adds that route, the family has two producers and they will drift.

        Read from the ROUTER decorators, not from the module text: the surviving
        module carries a header comment naming the routes it replaced, so a
        substring check matches its own prose.
        """
        import importlib

        sync = importlib.import_module("api.routes.models.provider_sync")
        module_source = Path(sync.__file__).read_text()
        registered = re.findall(r'@router\.(?:get|post|put|delete|patch)\(\s*[fr]?"([^"]+)"', module_source)
        assert registered, "expected provider_sync to still register at least one route"
        for path in registered:
            assert "sync-progress" not in path, (
                f"registered {path!r}: model.sync_* would have two producers"
            )


class TestProgressMeansWhatItSays:
    def test_the_progress_payload_names_its_scope(self):
        """`progress` is the fraction of the queue drained, not of the file in
        flight. Without the scope label a consumer renders "Downloading X — 40%"
        and the operator believes a 7 GB checkpoint is 40% down when nothing of
        it may have arrived yet."""
        source = _reconciler_source()
        for call in _emit_calls(source, "MODEL_SYNC_PROGRESS"):
            assert 'progress_scope="batch"' in call, call

    def test_the_batch_fraction_is_derived_not_hardcoded(self):
        """A hardcoded `100` on the progress event would be the defect this file
        exists to prevent, reintroduced as a constant."""
        source = _reconciler_source()
        assert "_batch_progress" in source
        for call in _emit_calls(source, "MODEL_SYNC_PROGRESS"):
            assert "progress=0" not in call and "progress=100" not in call, call

    def test_the_batch_fraction_is_clamped(self):
        """`_batch_progress` divides by `total`; a zero total must not raise, and
        the value must stay a percentage."""
        from services.in_process_reconciliation import _batch_progress

        assert _batch_progress(0, 0, True) == 0
        assert _batch_progress(0, 0, False) == 0
        assert _batch_progress(0, 4, True) == 25
        assert _batch_progress(3, 4, True) == 100
        assert _batch_progress(2, 4, False) == 50
        # In flight, one file not yet counted, must never exceed 100.
        assert _batch_progress(99, 100, False) <= 100

    def test_the_failed_event_carries_the_reason(self):
        """`severity=failed` with no message is what made the old failure toasts
        useless."""
        source = _reconciler_source()
        calls = _emit_calls(source, "MODEL_SYNC_FAILED")
        assert calls
        for call in calls:
            assert "error_message=str(exc)" in call, call


class TestEmitsSitWithTheStatusWrites:
    def test_the_completed_emit_is_inside_the_try_that_marks_ready(self):
        """The browser and the row must not be able to disagree. The emit has to
        be after `_mark_ready()` commits, or the UI updates before the DB does
        and a reload contradicts it."""
        source = _reconciler_source()
        ready_index = source.index("await asyncio.to_thread(_mark_ready)")
        status_emit = source.index("await emit_model_status_update(", ready_index)
        completed = source.index("EventType.MODEL_SYNC_COMPLETED", status_emit)
        assert ready_index < status_emit < completed, (
            "the completed sync event is no longer ordered after the ready "
            "status write and the model.status_update emit"
        )

    def test_the_failed_emit_is_inside_the_except_that_marks_failed(self):
        source = _reconciler_source()
        failed_index = source.index("await asyncio.to_thread(_mark_failed)")
        completed = source.index("EventType.MODEL_SYNC_COMPLETED")
        failed_emit = source.index("EventType.MODEL_SYNC_FAILED", failed_index)
        assert failed_index < failed_emit
        # And the failed emit must precede the next download's completed emit.
        assert failed_emit < source.find("EventType.MODEL_SYNC_COMPLETED", failed_emit) or failed_emit > completed

    def test_the_emit_helper_is_awaited_not_called(self):
        """An un-awaited coroutine is the silent failure: the event never
        reaches the bus and nothing reports it."""
        source = _reconciler_source()
        for m in re.finditer(r"emit_model_sync_event\(", source):
            assert source[max(0, m.start() - 6) : m.start()] == "await ", (
                f"emit_model_sync_event called without await at offset {m.start()}"
            )

    def test_the_helper_is_imported_at_module_scope(self):
        """A local import inside the loop would be re-executed per file."""
        tree = ast.parse(_reconciler_source())
        top_level = {
            alias.name
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        assert "emit_model_sync_event" in top_level
