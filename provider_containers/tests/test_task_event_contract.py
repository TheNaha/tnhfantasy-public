"""Every `TaskEvent.event` member must have a producer and a consumer.

`TaskEvent.event` accumulated two members that no end of the pipeline ever
produced or acted on:

- **`started`** — the backend's *only* writer of `JobStatus.PRE_GENERATION`
  (`backend_v2/services/provider_client.py`), which is what `JobCard`'s
  "Preparing" state renders from. No worker emitted it, so that status and that
  UI state were unreachable. Fixed by emitting it in
  `provider_core/router.py::_with_started_event`, which is the one request path
  every image worker's `/inference` passes through.
- **`artifact`** — present in the `Literal`, in the class docstring and in
  `_TASK_EVENT_KINDS`, with no producer anywhere and no branch in the reducer.
  The backend's `if/elif` chain has no `else`, so such an event would be dropped
  silently by both ends. Removed.

The second case is the one worth a permanent guard: a kind that nothing produces
is not a feature, and it looks exactly like one in the type. This asserts the
property rather than trusting the schema, and asserts it in both directions — a
member with no producer and a member the backend does not handle are both defects.

Members may legitimately be worker-only (`delta` never reaches the image reducer)
or backend-only, so the consumer check is against *either* reducer rather than
both.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROVIDER_CORE = ROOT / "provider_containers" / "provider_core"
BACKEND = ROOT / "backend_v2"

# Deliberately no import of `provider_core.models`. The vocabulary is parsed from
# source rather than read off the class, so that a member which is declared but
# commented out — or the reverse — shows up as a disagreement instead of being
# invisible. It also keeps this file runnable from the provider venv without the
# worker engines' own dependencies.


def _declared_members() -> set[str]:
    """The members the `Literal` actually declares, parsed from the source.

    Read from source rather than from `typing.get_args` so a member that is
    declared but commented out, or vice versa, shows up as a disagreement instead
    of being invisible.
    """
    source = (PROVIDER_CORE / "models.py").read_text()
    block = re.search(r"event:\s*Literal\[(.*?)\]", source, re.S)
    assert block, "TaskEvent.event is no longer a Literal; this test needs updating"
    return set(re.findall(r'"([a-z_]+)"', block.group(1)))


def _derived_members() -> set[str]:
    source = (PROVIDER_CORE / "utils.py").read_text()
    block = re.search(r"_TASK_EVENT_KINDS\s*=\s*\{(.*?)\}", source, re.S)
    assert block, "_TASK_EVENT_KINDS is gone; it was meant to be derived, not retyped"
    return set(re.findall(r'"([a-z_]+)"', block.group(1)))


def _worker_producers() -> str:
    """Every non-test source in the worker engines, concatenated."""
    parts = []
    for sub in ("image_worker", "llm_worker", "tts_worker", "provider_core"):
        for path in sorted((ROOT / "provider_containers" / sub).rglob("*.py")):
            if "venv" in path.parts or "tests" in path.parts or path.name.startswith("test_"):
                continue
            parts.append(path.read_text())
    return "\n".join(parts)


def _backend_reducers() -> str:
    source = (BACKEND / "services" / "provider_client.py").read_text()
    return source


DECLARED = _declared_members()
WORKERS = _worker_producers()
BACKEND = _backend_reducers()


def test_the_parse_found_the_members():
    """A sweep matching nothing is indistinguishable from a healthy contract."""
    assert len(DECLARED) >= 5, f"only found {sorted(DECLARED)}; the parse is broken"
    assert {"completed", "failed", "cancelled"} <= DECLARED, (
        "the three terminal events must always be declared; if they are not, this "
        "test is reading something other than the event vocabulary"
    )


def test_the_derived_list_matches_the_literal():
    """`_TASK_EVENT_KINDS` is meant to be derived from `TaskEvent.event`.

    It was once a second hand-written literal, and `cached_nodes` was in one and
    not the other — so a canonical cached-nodes line was re-emitted as a
    contentless `progress`.
    """
    assert _derived_members() == DECLARED, (
        "_TASK_EVENT_KINDS and TaskEvent.event disagree: "
        f"only in the Literal {sorted(DECLARED - _derived_members())}, "
        f"only in _TASK_EVENT_KINDS {sorted(_derived_members() - DECLARED)}"
    )


@pytest.mark.parametrize("kind", sorted(DECLARED))
def test_every_declared_kind_has_a_producer(kind):
    """Nothing may declare an event no worker can send.

    This is the check that would have caught `artifact`, which sat in the
    `Literal`, the docstring and `_TASK_EVENT_KINDS` while being produced by
    nothing and handled by nothing.
    """
    if kind == "started":
        # Produced centrally rather than by an engine: see router.py's
        # `_with_started_event`, whose own test pins that it is first in the
        # stream. Asserted here so this file states the whole contract.
        assert "_with_started_event" in WORKERS, (
            "the central `started` injection is gone; nothing produces the event "
            "the backend's only PRE_GENERATION write depends on"
        )
        return
    assert f'"{kind}"' in WORKERS, (
        f"TaskEvent declares `{kind}` but no worker source mentions it, so it "
        "cannot be sent. Either a worker emits it or it is not part of the "
        "vocabulary — an unemittable member is a type that lies"
    )


@pytest.mark.parametrize("kind", sorted(DECLARED))
def test_every_declared_kind_is_handled_by_the_backend(kind):
    """Nothing may declare an event the backend silently drops.

    The reducers in `provider_client.py` are an `if/elif` chain with no `else`,
    so an unhandled kind is not an error — it vanishes, which is how an event can
    look wired end to end while doing nothing.
    """
    assert f'"{kind}"' in BACKEND, (
        f"TaskEvent declares `{kind}` but `services/provider_client.py` has no "
        "branch for it. With no `else` in the reducer chain such an event is "
        "dropped silently, so either handle it or drop it from the vocabulary"
    )


def test_started_is_the_first_event_of_every_stream():
    """Ordering is the point of `started`.

    Appended at the end it would arrive after `progress` and set
    `PRE_GENERATION` on a job already rendering, so the reducer would move the
    job backwards.
    """
    source = (PROVIDER_CORE / "router.py").read_text()
    body = re.search(r"async def with_started\(\):(.*?)\n\n", source, re.S)
    assert body, "router.py no longer has the with_started generator"
    lines = [ln.strip() for ln in body.group(1).splitlines() if ln.strip()]
    assert lines[0].startswith("yield TaskEvent(event=\"started\""), (
        f"the first thing the wrapped stream yields is {lines[0]!r}, not the "
        "started event"
    )