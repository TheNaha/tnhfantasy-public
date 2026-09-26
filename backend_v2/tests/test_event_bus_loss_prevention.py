"""Tests for the event-bus side of the lost-paid-LLM-reply defect, and for
`wait_for_job_completion` no longer blocking the event loop.

The chain: a single world-integration consumer subscribes to the `job` topic and
is the only writer of AI chat replies. It was subscribed at the EventBus default
queue depth of 100, and on overflow `publish` keeps a terminal event by
evicting the OLDEST queued one. A 60-image batch is enough to fall 100 behind,
at which point the evicted events are the oldest — and if those were chat_reply
jobs, the generated text was paid for, marked COMPLETED in the DB, and never
written anywhere.
"""

import asyncio
import time

import pytest

import core.events as events_module
from core.events import CONTENT_BEARING_EVENT_TYPES, Event, EventBus, EventType
from services.world_integration_service import WORLD_INTEGRATION_QUEUE_SIZE


# ── consumer buffer depth ───────────────────────────────────────────────────

def test_world_integration_buffer_is_far_larger_than_the_event_bus_default():
    default_depth = 100  # EventBus.subscribe's max_queue_size default

    assert WORLD_INTEGRATION_QUEUE_SIZE > default_depth * 10
    # A 60-image batch plus the LLM replies it triggers, with margin.
    assert WORLD_INTEGRATION_QUEUE_SIZE >= 200


def test_world_integration_subscribe_uses_the_explicit_buffer():
    """Regression guard: the call must not go back to the default."""
    import inspect

    import services.world_integration_service as wis

    source = inspect.getsource(wis.start_world_integration_service)

    assert "max_queue_size=WORLD_INTEGRATION_QUEUE_SIZE" in source


def test_a_large_burst_no_longer_evicts_a_content_bearing_event():
    """2000 JOB_COMPLETED events, far past the old 100-deep queue."""
    bus = EventBus()
    received: list[Event] = []

    async def consume():
        async for event in bus.subscribe(
            "job", max_queue_size=WORLD_INTEGRATION_QUEUE_SIZE
        ):
            received.append(event)
            if len(received) >= 1500:
                return

    async def publish():
        consumer = asyncio.create_task(consume())
        # Let the consumer attach before anything is published.
        await asyncio.sleep(0)
        for index in range(1500):
            await bus.publish(Event(
                type=EventType.JOB_COMPLETED,
                data={"job": {"id": f"job-{index}", "outputs": [{"content": "x"}]}},
            ))
        await asyncio.wait_for(consumer, timeout=5)

    asyncio.run(publish())

    assert bus.dropped_event_count() == 0
    assert [e.data["job"]["id"] for e in received][:3] == ["job-0", "job-1", "job-2"]
    assert len(received) == 1500


# ── loss is at least visible ────────────────────────────────────────────────

def test_evicting_a_job_completed_is_logged_at_error_with_the_job_id(capsys):
    """An evicted JOB_COMPLETED is a paid LLM response with no other trace.

    Asserted on stdout because `infrastructure.logging` configures structlog with
    a PrintLogger, which bypasses both the stdlib root logger and `caplog`.
    """
    bus = EventBus()

    async def scenario():
        # A subscriber that never drains: the queue fills and every later
        # terminal event has to evict something to get in.
        drainer = asyncio.create_task(_drain_forever(bus, [], take=0))
        await asyncio.sleep(0)
        for index in range(4):
            await bus.publish(Event(
                type=EventType.JOB_COMPLETED,
                data={"job": {"id": f"job-{index}"}},
            ))
        drainer.cancel()

    asyncio.run(scenario())
    logged = capsys.readouterr().out

    assert bus.dropped_event_count() > 0, "the queue never overflowed"
    assert "content_bearing_event_dropped" in logged
    assert "[error" in logged, "the drop must be an ERROR, not a counter tick"
    # The id must be the EVICTED job (the one an operator has to re-drive), not
    # the newest one that was admitted.
    assert "job_id=job-0" in logged


def test_content_bearing_types_cover_job_completed_only():
    """Only JOB_COMPLETED's payload is irreplaceable persisted content."""
    assert EventType.JOB_COMPLETED in CONTENT_BEARING_EVENT_TYPES
    for harmless in (EventType.JOB_PROGRESS, EventType.JOB_UPDATED, EventType.JOB_FAILED):
        assert harmless not in CONTENT_BEARING_EVENT_TYPES


def test_ordinary_progress_drops_stay_quiet(capsys):
    """A progress event is not worth an ERROR per drop."""
    bus = EventBus()

    async def scenario():
        drainer = asyncio.create_task(_drain_forever(bus, [], take=0))
        await asyncio.sleep(0)
        for index in range(5):
            await bus.publish(Event(
                type=EventType.JOB_PROGRESS,
                data={"job": {"id": f"job-{index}"}},
            ))
        drainer.cancel()

    asyncio.run(scenario())
    logged = capsys.readouterr().out

    assert bus.dropped_event_count() > 0
    assert bus.get_stats()["terminal_events_dropped"] == 0
    assert "content_bearing_event_dropped" not in logged


async def _drain_forever(bus: EventBus, sink: list, take: int) -> None:
    async for event in bus.subscribe("job", max_queue_size=2):
        sink.append(event)
        if take and len(sink) >= take:
            return


# ── wait_for_job_completion no longer blocks the loop ───────────────────────

def _patch_job_state(monkeypatch, result):
    calls: list[str] = []

    def fake(job_id):
        calls.append(job_id)
        if callable(result):
            return result(job_id)
        return result

    monkeypatch.setattr(events_module, "_read_job_terminal_state_sync", fake)
    return calls


def test_poll_read_does_not_block_the_event_loop(monkeypatch):
    """`with get_session()` on the loop stalled every other request — including
    the WebSocket broadcast pump — for the length of each round trip, ~165 times
    over a 5.5 minute agentic generation."""
    def slow_read(job_id):
        time.sleep(0.05)  # stands in for a blocking DB round trip
        return ("completed", {"content": "done"})

    monkeypatch.setattr(events_module, "_read_job_terminal_state_sync", slow_read)

    async def scenario():
        ticks = 0
        stop = False

        async def heartbeat():
            nonlocal ticks
            while not stop:
                await asyncio.sleep(0.005)
                ticks += 1

        beat = asyncio.create_task(heartbeat())
        result = await events_module.wait_for_job_completion("job-x", timeout=1.0)
        stop = True
        await beat
        return result, ticks

    (status, output), ticks = asyncio.run(scenario())

    assert status == "completed"
    assert output == {"content": "done"}
    # A 50ms blocking read on the loop would leave the loop with no time at all.
    assert ticks >= 3, f"the loop only got {ticks} ticks during a 50ms read"


def test_poll_read_uses_a_worker_thread(monkeypatch):
    import threading

    main_thread = threading.get_ident()
    seen: list[int] = []

    def fake(job_id):
        seen.append(threading.get_ident())
        return ("failed", None)

    monkeypatch.setattr(events_module, "_read_job_terminal_state_sync", fake)

    status, _ = asyncio.run(
        events_module.wait_for_job_completion("job-y", timeout=1.0)
    )

    assert status == "failed"
    assert seen and all(ident != main_thread for ident in seen)


def test_poll_interval_backs_off_instead_of_fixing_it_at_two_seconds(monkeypatch):
    """Flat 2s meant ~165 blocking reads over a 5.5 minute agentic generation."""
    waits: list[float] = []
    loop_calls = {"n": 0}

    def fake(job_id):
        loop_calls["n"] += 1
        # Never terminal: force the timeout path to keep polling.
        return None

    monkeypatch.setattr(events_module, "_read_job_terminal_state_sync", fake)

    real_wait_for = asyncio.wait_for

    async def spy_wait_for(awaitable, timeout=None):
        waits.append(timeout)
        return await real_wait_for(awaitable, timeout=0.01)

    monkeypatch.setattr(asyncio, "wait_for", spy_wait_for)

    asyncio.run(events_module.wait_for_job_completion(
        "job-z", timeout=30.0, poll_interval=2.0,
    ))

    assert len(waits) >= 3
    # Each wait is capped by the (growing) interval, and the interval grows.
    assert waits[0] == pytest.approx(2.0)
    assert waits[1] > waits[0]
    assert waits[2] > waits[1]


def test_poll_interval_respects_the_remaining_time(monkeypatch):
    """The last wait before the deadline must not overshoot it."""
    _patch_job_state(monkeypatch, None)
    waits: list[float] = []

    real_wait_for = asyncio.wait_for

    async def spy_wait_for(awaitable, timeout=None):
        waits.append(timeout)
        return await real_wait_for(awaitable, timeout=0.01)

    monkeypatch.setattr(asyncio, "wait_for", spy_wait_for)

    asyncio.run(events_module.wait_for_job_completion("job-w", timeout=0.05))

    assert waits
    assert all(wait <= 0.05 + 0.01 for wait in waits)


def test_terminal_event_short_circuits_the_db_poll(monkeypatch):
    """The event is the normal path; the DB is only the missed-event race."""
    calls = _patch_job_state(monkeypatch, None)

    async def scenario():
        # Publish the terminal event right after subscribing.
        async def publisher():
            await asyncio.sleep(0.01)
            await events_module.event_bus.publish(Event(
                type=EventType.JOB_COMPLETED,
                data={"job": {"id": "job-v", "outputs": [{"content": "hi"}]}},
            ))

        pub = asyncio.create_task(publisher())
        result = await events_module.wait_for_job_completion("job-v", timeout=2.0)
        await pub
        return result

    status, output = asyncio.run(scenario())

    assert status == "completed"
    assert output == {"content": "hi"}
    # The initial guard read happened; it did not have to keep polling.
    assert calls == ["job-v"]
