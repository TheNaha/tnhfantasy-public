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

    Parsed from the source rather than imported, because the emitting module is
    the provider tier's and is not importable here.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "provider_containers"
    utils = (root / "provider_core" / "utils.py").read_text()
    models = (root / "provider_core" / "models.py").read_text()
    assert 'value_unit=PROGRESS_VALUE_UNIT' in utils, (
        "the single progress emission point no longer names the unit, so the "
        "backend falls back to the heuristic this test exists to constrain"
    )
    assert 'PROGRESS_VALUE_UNIT = "percent"' in utils, (
        "the unit sent is no longer 'percent'; the backend's face-value branch "
        "would be wrong for whatever replaced it"
    )
    assert "value_unit" in models, (
        "TaskEvent no longer declares value_unit, so it cannot be read off the "
        "wire at all"
    )


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
