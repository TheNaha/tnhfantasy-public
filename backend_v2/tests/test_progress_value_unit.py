"""A worker reporting 1 percent done must not be recorded as 100 percent.

`provider_core/utils.py` normalises every progress event to percent 0..100 and
now names the unit on the wire (`TaskEvent.value_unit == "percent"`). The backend
re-applied a legacy heuristic on top of that:

    percent = int(val * 100) if val <= 1 else int(val)

whose `val <= 1` branch reads a worker reporting exactly `value == 1` — one
percent done — as a fraction and records **100**. It is silent, it lands on the
single most-watched number in the UI, and no worker emits fractions any more, so
the branch could only ever misfire. A job that appeared finished had not run at
all.

The heuristic is still needed for a container deployed before `value_unit`
existed, which sends a 0..1 fraction and no unit. So the unit decides, and an
absent unit keeps the old reading. Both halves are pinned below.
"""

import pytest

from core.progress import coerce_worker_percent
from services.provider_client import _ImageReducer


class RecordingJobService:
    """Captures `update_job` calls instead of writing a row."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def update_job(self, job_id, **fields):
        self.calls.append(fields)
        return None


@pytest.fixture
def reducer():
    return _ImageReducer("job-1", RecordingJobService(), total_nodes=0, provider_id="p1")


async def _progress(reducer, **event):
    await reducer({"event": "progress", "value": 1, **event})
    return reducer.job_service.calls[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [1, 0, 1.0, 0.5, 7, 50, 99, 100])
async def test_a_declared_percent_is_taken_at_face_value(reducer, value):
    """`value_unit == "percent"` means the number already is the percentage."""
    fields = await _progress(reducer, value=value, value_unit="percent")
    assert fields["progress"] == int(value), (
        f"a worker declaring percent sent value={value}; recording "
        f"{fields['progress']} misreports how far the job has got"
    )


@pytest.mark.asyncio
async def test_one_percent_is_not_one_hundred_percent(reducer):
    """The specific misfire, named so a revert cannot pass quietly."""
    fields = await _progress(reducer, value=1, value_unit="percent")
    assert fields["progress"] == 1
    assert fields["message"] == "Rendering: 1%"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value,expected",
    [
        (0.5, 50),  # legacy fraction
        (1.0, 100),  # legacy fraction at the top of its range
        (0.01, 1),  # legacy fraction
        (42, 42),  # legacy container already sending percent
    ],
)
async def test_an_undeclared_unit_keeps_the_legacy_reading(reducer, value, expected):
    """A container predating `value_unit` sends no unit and a 0..1 fraction."""
    fields = await _progress(reducer, value=value)
    assert fields["progress"] == expected


@pytest.mark.asyncio
async def test_a_declared_fraction_is_honoured_explicitly(reducer):
    """A worker may declare the other unit; that is now readable too."""
    fields = await _progress(reducer, value=0.25, value_unit="fraction")
    assert fields["progress"] == 25


@pytest.mark.asyncio
async def test_every_worker_emits_the_unit_this_relies_on():
    """The backend's branch above is only sound if workers actually send it.

    The provider tier's `provider_core/utils.py` used to emit
    `value_unit=PROGRESS_VALUE_UNIT` from `comfy_status_to_task_event`, but those
    functions were dead code (removed 2026-10-09): `server.py` imports
    `determine_download_token` and path helpers from the same module but never the
    event translators. The in-process engines are the only live emission path,
    and they are covered by `test_in_process_engines_emit_the_unit_this_relies_on`.

    `TaskEvent` itself still declares `value_unit`, so the field is present on the
    wire — the guard below checks that.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "remote_agent"
    if not (root / "provider_core" / "models.py").exists():
        pytest.skip("remote_agent/provider_core tree not mounted in this environment")
    models = (root / "provider_core" / "models.py").read_text()
    assert "value_unit" in models, (
        "TaskEvent no longer declares value_unit, so it cannot be read off the "
        "wire at all"
    )


@pytest.mark.asyncio
async def test_in_process_engines_emit_the_unit_this_relies_on():
    """Same guarantee as above for the in-process engines: the shared legacy
    translator must name value_unit="percent" on every progress event it
    produces, since the reducer takes a declared percent at face value."""
    from services.engines.base import translate_legacy_image_update

    assert translate_legacy_image_update(
        {"status": "progress", "value": 5, "max": 10}, "job-x"
    ) == {"event": "progress", "job_id": "job-x", "value": 50, "value_unit": "percent"}


class TestTheLegacyTranslatorDoesNotGuessTheUnit:
    """`translate_legacy_image_update` must not apply a fraction heuristic to a
    number it then labels as percent.

    The three-window defect: a bare `value` with no `max` was multiplied by 100
    when it was `<= 1`, and the same function declared `value_unit="percent"` on
    the result. A canonical percent producer's `value == 1` — one percent done,
    the first step of every image job — came out as 100, in the one number the
    user watches. The reducer then read `value_unit == "percent"` and took the
    100 at face value, so both halves agreed on a wrong number.
    """

    @pytest.mark.parametrize(
        "value",
        [0, 0.01, 0.25, 0.5, 0.99, 1, 1.0, 1.5, 2, 42, 99, 100],
    )
    def test_a_bare_value_is_a_percent_not_a_fraction(self, value):
        from services.engines.base import translate_legacy_image_update

        out = translate_legacy_image_update({"value": value}, "job-x")
        assert out["value"] == value, (
            f"value={value!r} was rescaled, which is the fraction heuristic "
            "firing on a percent producer's number"
        )
        assert out["value_unit"] == "percent"

    @pytest.mark.parametrize(
        "value,max_v",
        [(5, 10), (1, 100), (0, 10), (10, 10), (3, 4)],
    )
    def test_a_value_max_pair_still_becomes_a_percentage(self, value, max_v):
        """The one branch that is unambiguous, and must keep working: dividing is
        the only way to turn a pair into a percentage."""
        from services.engines.base import translate_legacy_image_update

        out = translate_legacy_image_update(
            {"value": value, "max": max_v}, "job-x"
        )
        assert out["value"] == round(value / max_v * 100)
        assert out["value_unit"] == "percent"

    def test_the_fraction_heuristic_is_not_in_the_source(self):
        """Read from the module text so a re-added heuristic fails by name.

        Asserting the behaviour alone would pass for a heuristic restricted to
        values the parametrisation above does not cover.
        """
        import inspect

        from services.engines import base as base_module

        # Strip comments first: this test's own explanation in `base.py` quotes
        # the expression it removed, and a substring scan would match its prose.
        src = "\n".join(
            line
            for line in inspect.getsource(
                base_module.translate_legacy_image_update
            ).splitlines()
            if not line.lstrip().startswith("#")
        )
        assert "value * 100" not in src, (
            "the `value <= 1` fraction heuristic is back; a percent producer's "
            "1% becomes 100% again"
        )
        assert "value <= 1" not in src


@pytest.mark.asyncio
async def test_missing_value_is_zero_not_an_error(reducer):
    """A progress frame with no value must not become 100 percent."""
    await reducer({"event": "progress", "value_unit": "percent"})
    assert reducer.job_service.calls[-1]["progress"] == 0

class TestBothHalvesAgree:
    """One rule, two call sites, and the guard that keeps them one rule.

    `api/routes/worker_ws._coerce_percent` and `services/provider_client`'s
    reducer are the two consumers of a worker's progress frame. They had already
    drifted: this side was converted to `value_unit`, that side kept
    `0 <= value <= 1 means a fraction`, so a canonical `value == 1` read as 1%
    here and 100% there — the same socket, the same frame, two answers, silently.

    Comparing the two is the only guard that can catch a third copy appearing,
    or one of them being edited back to a local heuristic.
    """

    @pytest.mark.parametrize(
        "value,unit",
        [
            (0, "percent"), (0.01, "percent"), (0.25, "percent"), (1, "percent"),
            (1.5, "percent"), (2, "percent"), (42, "percent"), (99, "percent"),
            (100, "percent"), (150, "percent"), (-5, "percent"),
            (None, "percent"), ("nan", "percent"), ("x", "percent"),
            (0.5, None), (1, None), (0, None), (1.0, None), (42, None),
        ],
    )
    def test_socket_and_client_halves_return_the_same_integer(self, value, unit):
        from api.routes.worker_ws import _coerce_percent

        assert _coerce_percent(value, unit) == coerce_worker_percent(value, unit)

    def test_the_client_half_reads_value_unit_from_the_frame(self):
        """The reducer must pass the frame's own `value_unit` through, not
        re-derive it. Before the consolidation it hardcoded the branch inline."""
        import inspect

        source = inspect.getsource(_ImageReducer.__call__)
        assert "coerce_worker_percent" in source
        assert 'value_unit' in source
        assert "val * 100" not in source, "the local heuristic must be gone"


@pytest.mark.asyncio
async def test_preview_timer_decoupled_from_progress(reducer):
    """Progress frames must emit immediately while preview frames are rate-bounded."""
    # Progress frames arrive rapidly
    for i in range(1, 6):
        await reducer({"event": "progress", "value": i * 10, "value_unit": "percent"})
    assert len(reducer.job_service.calls) == 5
    assert reducer.job_service.calls[-1]["progress"] == 50

    # First preview frame emits
    await reducer({"event": "preview", "preview": "frame_1"})
    assert len(reducer.job_service.calls) == 6
    assert reducer.job_service.calls[-1]["event_extra"]["preview"] == "frame_1"

    # Immediate second preview frame (within 0.5s throttle) is absorbed without dropping progress
    await reducer({"event": "preview", "preview": "frame_2"})
    assert len(reducer.job_service.calls) == 6

    # Progress continues immediately
    await reducer({"event": "progress", "value": 60, "value_unit": "percent"})
    assert len(reducer.job_service.calls) == 7
    assert reducer.job_service.calls[-1]["progress"] == 60

    # Completion immediately clears the latest preview reference
    await reducer({"event": "completed", "outputs": [{"filename": "out.png"}]})
    assert reducer._latest_preview is None
