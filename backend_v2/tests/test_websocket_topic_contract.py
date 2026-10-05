"""A client may only join a room that can actually receive an event.

The room name is the prefix of an `EventType` value — `start_broadcasting` does
`event.type.value.split(".")[0]` — so the set of rooms that can ever receive a
broadcast is exactly the set of enum prefixes. That makes it derivable, and
deriving it is the fix: the hand-maintained list still contained `"download"`
after the entire `download.*` event family was removed on 2026-10-03, so a client
could subscribe to a room that could never receive anything and be told
`{"event": "subscribed", "topics": ["download"]}`.

A second copy of the same list lived in the `subscribe` handler's allowlist
filter. Two copies of a derived value is how they drift, so both now read one
`BROADCAST_TOPICS` constant and this asserts the constant is still derived rather
than retyped.
"""

import re
from pathlib import Path

from api.routes.websocket import BROADCAST_TOPICS
from core.events import EventType

WS_SOURCE = (Path(__file__).resolve().parents[1] / "api" / "routes" / "websocket.py").read_text()


def _expected() -> set[str]:
    return {e.value.split(".")[0] for e in EventType}


def test_the_constant_matches_the_event_vocabulary():
    assert set(BROADCAST_TOPICS) == _expected(), (
        "BROADCAST_TOPICS does not match the room names the broadcaster can "
        f"produce. Missing {sorted(_expected() - set(BROADCAST_TOPICS))}, "
        f"extra {sorted(set(BROADCAST_TOPICS) - _expected())}"
    )


def test_the_constant_is_derived_not_retyped():
    """The defect was a hand-written list, so the shape is what is pinned.

    A literal set of topic strings is the thing that went stale; deriving it from
    `EventType` cannot. This fails if someone replaces the comprehension with the
    literal it used to be.
    """
    assert re.search(r"BROADCAST_TOPICS\s*=\s*frozenset\(\s*e\.value\.split", WS_SOURCE), (
        "BROADCAST_TOPICS is no longer derived from EventType. Re-deriving it is "
        "the whole point: a hand-written list is what left a dead `download` room "
        "subscribable after the family behind it was deleted"
    )


def test_no_room_is_subscribable_without_a_producer():
    """The specific regression, named so it cannot come back quietly."""
    orphans = sorted(
        topic
        for topic in BROADCAST_TOPICS
        if not any(e.value.startswith(topic + ".") for e in EventType)
    )
    assert not orphans, (
        f"these rooms are subscribable but no EventType can be broadcast to them: "
        f"{orphans}. A client joining one gets an ack and then silence"
    )


def test_the_retired_download_family_stays_retired():
    assert not [e for e in EventType if e.value.startswith("download.")], (
        "a download.* event was re-added. The family had zero producers and zero "
        "subscribers and was removed on 2026-10-03; if it is coming back it needs "
        "a producer, a consumer and a reason in this file"
    )


def test_the_broadcaster_subscribe_filter_is_not_a_second_list():
    """Two copies of a derived value is how they drift."""
    literals = re.findall(r'topic in \{[^}]*["\']job["\']', WS_SOURCE)
    assert not literals, (
        "a subscribe handler re-declared the topic allowlist as a literal set. "
        "Use BROADCAST_TOPICS"
    )
