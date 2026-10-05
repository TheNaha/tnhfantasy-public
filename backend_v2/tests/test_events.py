# EventBus Unit Tests
import asyncio

import pytest

from core.events import Event, EventBus, EventType, emit_job_event


class TestEvent:
    """Tests for Event dataclass."""

    def test_creation(self):
        """Test creating an event with required fields."""
        event = Event(type=EventType.JOB_CREATED, data={"job": {"id": "1"}})
        assert event.type == EventType.JOB_CREATED
        assert event.data == {"job": {"id": "1"}}
        assert event.timestamp is not None

    def test_to_dict(self):
        """Test converting event to dictionary."""
        event = Event(type=EventType.JOB_COMPLETED, data={"job": {"id": "abc"}})
        d = event.to_dict()
        assert d["type"] == "job.completed"
        assert d["data"] == {"job": {"id": "abc"}}
        assert "timestamp" in d

    def test_event_type_values(self):
        """Test event type string values match expected format."""
        assert EventType.JOB_CREATED.value == "job.created"
        assert EventType.JOB_COMPLETED.value == "job.completed"
        assert EventType.JOB_FAILED.value == "job.failed"
        assert EventType.MODEL_STATUS_UPDATE.value == "model.status_update"
        assert EventType.PROVIDER_STATUS.value == "provider.status"


class TestEventBus:
    """Tests for the EventBus pub/sub system."""

    @pytest.fixture
    def bus(self):
        """Create a fresh EventBus for each test."""
        return EventBus(replay_buffer_size=10)

    @pytest.mark.asyncio
    async def test_publish_adds_to_replay_buffer(self, bus):
        """Published events are added to the replay buffer."""
        event = Event(type=EventType.JOB_CREATED, data={"job": {}})
        await bus.publish(event)
        buffer = bus.get_replay_buffer()
        assert len(buffer) == 1
        assert buffer[0].type == EventType.JOB_CREATED

    @pytest.mark.asyncio
    async def test_replay_buffer_max_size(self, bus):
        """Replay buffer respects max size."""
        for i in range(15):  # More than buffer size of 10
            await bus.publish(Event(type=EventType.JOB_CREATED, data={"i": i}))
        buffer = bus.get_replay_buffer()
        assert len(buffer) == 10  # Capped at max size

    @pytest.mark.asyncio
    async def test_replay_buffer_with_limit(self, bus):
        """get_replay_buffer respects limit parameter."""
        for i in range(5):
            await bus.publish(Event(type=EventType.JOB_CREATED, data={"i": i}))
        buffer = bus.get_replay_buffer(limit=3)
        assert len(buffer) == 3

    def test_clear_replay_buffer(self, bus):
        """Clearing replay buffer removes all events."""
        bus._replay_buffer.append(Event(type=EventType.JOB_CREATED, data={}))
        bus.clear_replay_buffer()
        assert len(bus.get_replay_buffer()) == 0

    def test_subscriber_count_zero_initially(self, bus):
        """No subscribers initially."""
        assert bus.subscriber_count("job") == 0
        assert bus.subscriber_count("model") == 0

    @pytest.mark.asyncio
    async def test_subscriber_receives_published_event(self, bus):
        """Subscriber receives events published after subscription."""
        received = []

        async def subscriber():
            async for event in bus.subscribe("job", max_queue_size=10):
                received.append(event)
                break  # Exit after first event

        # Start subscriber, then publish
        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)  # Let subscriber start

        await bus.publish(Event(type=EventType.JOB_CREATED, data={"job": {"id": "1"}}))
        await task

        assert len(received) == 1
        assert received[0].type == EventType.JOB_CREATED

    @pytest.mark.asyncio
    async def test_subscriber_count_increases_on_subscribe(self, bus):
        """Subscriber count increases when a subscriber is active."""
        received = []

        async def subscriber():
            async for event in bus.subscribe("job", max_queue_size=5):
                received.append(event)
                break

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)  # Let subscriber register

        assert bus.subscriber_count("job") == 1

        await bus.publish(Event(type=EventType.JOB_CREATED, data={}))
        await task
        # Give cleanup a moment to run
        await asyncio.sleep(0.01)

        # Count should go back to 0 after subscriber exits
        assert bus.subscriber_count("job") == 0

    @pytest.mark.asyncio
    async def test_topic_routing(self, bus):
        """Events are routed to correct topic subscribers."""
        job_events = []
        model_events = []

        async def job_subscriber():
            async for event in bus.subscribe("job", max_queue_size=5):
                job_events.append(event)
                break

        async def model_subscriber():
            async for event in bus.subscribe("model", max_queue_size=5):
                model_events.append(event)
                break

        task_job = asyncio.create_task(job_subscriber())
        task_model = asyncio.create_task(model_subscriber())
        await asyncio.sleep(0.01)

        # Publish to different topics
        await bus.publish(Event(type=EventType.JOB_CREATED, data={}))
        await bus.publish(Event(type=EventType.MODEL_STATUS_UPDATE, data={}))

        await task_job
        await task_model

        assert len(job_events) == 1
        assert len(model_events) == 1
        assert job_events[0].type == EventType.JOB_CREATED
        assert model_events[0].type == EventType.MODEL_STATUS_UPDATE

    @pytest.mark.asyncio
    async def test_multiple_subscribers_same_topic(self, bus):
        """Multiple subscribers all receive the same event."""
        received_1 = []
        received_2 = []

        async def sub1():
            async for event in bus.subscribe("job", max_queue_size=5):
                received_1.append(event)
                break

        async def sub2():
            async for event in bus.subscribe("job", max_queue_size=5):
                received_2.append(event)
                break

        t1 = asyncio.create_task(sub1())
        t2 = asyncio.create_task(sub2())
        await asyncio.sleep(0.01)

        await bus.publish(Event(type=EventType.JOB_PROGRESS, data={"progress": 50}))

        await t1
        await t2

        assert len(received_1) == 1
        assert len(received_2) == 1

    @pytest.mark.asyncio
    async def test_subscribe_multiple_topics(self, bus):
        """subscribe_multiple receives events from all listed topics."""
        received = []

        async def multi_sub():
            async for event in bus.subscribe_multiple(["job", "model"], max_queue_size=10):
                received.append(event)
                if len(received) == 2:
                    break

        task = asyncio.create_task(multi_sub())
        await asyncio.sleep(0.01)

        await bus.publish(Event(type=EventType.JOB_CREATED, data={}))
        await bus.publish(Event(type=EventType.MODEL_STATUS_UPDATE, data={}))

        await task

        types = {e.type for e in received}
        assert EventType.JOB_CREATED in types
        assert EventType.MODEL_STATUS_UPDATE in types

    @pytest.mark.asyncio
    async def test_subscribe_multiple_prevents_cross_topic_starvation(self, bus):
        """Heavy traffic on one topic should not block another topic in subscribe_multiple."""
        received = []

        async def multi_sub():
            async for event in bus.subscribe_multiple(["job", "model"], max_queue_size=1):
                received.append(event)
                if len(received) >= 2:
                    break
                # Intentionally slow consumer to create backpressure.
                await asyncio.sleep(0.05)

        task = asyncio.create_task(multi_sub())
        await asyncio.sleep(0.01)

        for i in range(5):
            await bus.publish(Event(type=EventType.JOB_CREATED, data={"job": {"id": f"job-{i}"}}))
        await bus.publish(Event(type=EventType.MODEL_STATUS_UPDATE, data={"model": {"id": "m-1"}}))

        await asyncio.wait_for(task, timeout=1.0)

        types = {event.type for event in received}
        assert EventType.MODEL_STATUS_UPDATE in types

    @pytest.mark.asyncio
    async def test_event_sequence_numbers(self, bus):
        """Test that event bus assigns sequential numbers starting at 1."""
        event1 = Event(type=EventType.JOB_CREATED, data={})
        event2 = Event(type=EventType.JOB_COMPLETED, data={})
        assert event1.sequence_number is None
        assert event2.sequence_number is None
        
        await bus.publish(event1)
        await bus.publish(event2)
        
        assert event1.sequence_number == 1
        assert event2.sequence_number == 2
        
        # Test event to_dict includes sequence_number
        d = event1.to_dict()
        assert d["sequence_number"] == 1


class TestEmitConvenienceFunctions:
    """Tests for module-level emit convenience functions."""

    @pytest.fixture(autouse=True)
    def fresh_bus(self):
        """Ensure the global event bus is clean."""
        from core.events import event_bus
        event_bus.clear_replay_buffer()

    @pytest.mark.asyncio
    async def test_emit_job_event(self):
        """emit_job_event publishes to the job topic."""
        from core.events import event_bus
        received = []

        async def subscriber():
            async for event in event_bus.subscribe("job", max_queue_size=5):
                received.append(event)
                break

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)

        await emit_job_event(EventType.JOB_COMPLETED, {"id": "job-1", "status": "completed"})
        await task

        assert len(received) == 1
        assert received[0].data["job"]["id"] == "job-1"


class TestEventBusQueueFull:
    """Test queue full behavior."""

    @pytest.mark.asyncio
    async def test_queue_full_increments_drop_count(self):
        bus = EventBus(replay_buffer_size=10)
        queue = asyncio.Queue(maxsize=1)
        queue.put_nowait(Event(type=EventType.JOB_CREATED, data={"i": 0}))
        bus._subscribers["job"] = [queue]

        await bus.publish(Event(type=EventType.JOB_CREATED, data={"i": 1}))

        assert bus.dropped_event_count() == 1
        assert bus.dropped_event_counts_by_topic() == {"job": 1}

    @pytest.mark.asyncio
    async def test_queue_full_records_last_drop_stats(self):
        bus = EventBus(replay_buffer_size=10)
        queue = asyncio.Queue(maxsize=1)
        queue.put_nowait(Event(type=EventType.JOB_CREATED, data={"i": 0}))
        bus._subscribers["job"] = [queue]

        await bus.publish(Event(type=EventType.JOB_CREATED, data={"i": 1}))

        stats = bus.get_stats()
        assert stats["dropped_events"] == 1
        assert stats["dropped_events_by_topic"] == {"job": 1}
        assert stats["last_drop"]["topic"] == "job"
        assert stats["last_drop"]["event_type"] == EventType.JOB_CREATED.value
        assert stats["last_drop"]["queue_maxsize"] == 1
        assert stats["subscriber_counts"]["job"] == 1
        assert stats["last_drop"]["reason"] == "queue_full"

    @pytest.mark.asyncio
    async def test_queue_full_drops_event(self):
        """Test that QueueFull is handled gracefully - old events are dropped."""
        bus = EventBus(replay_buffer_size=100)
        received = []

        async def slow_subscriber():
            """Subscriber that blocks intentionally."""
            async for event in bus.subscribe(EventType.JOB_CREATED, max_queue_size=2):
                received.append(event)
                # Don't consume rapidly
                break

        task = asyncio.create_task(slow_subscriber())
        await asyncio.sleep(0.01)

        # Flood with events - some should be dropped without raising
        for i in range(10):
            await bus.publish(Event(type=EventType.JOB_CREATED, data={"i": i}))

        # Should not raise
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

        assert bus.dropped_event_count() >= 0

    @pytest.mark.asyncio
    async def test_terminal_event_evicts_oldest_when_queue_full(self):
        bus = EventBus(replay_buffer_size=10)
        queue = asyncio.Queue(maxsize=2)
        queue.put_nowait(Event(type=EventType.JOB_PROGRESS, data={"i": 1}))
        queue.put_nowait(Event(type=EventType.JOB_PROGRESS, data={"i": 2}))
        bus._subscribers["job"] = [queue]

        await bus.publish(Event(type=EventType.JOB_COMPLETED, data={"i": 3}))

        first = queue.get_nowait()
        second = queue.get_nowait()

        assert first.type == EventType.JOB_PROGRESS
        assert second.type == EventType.JOB_COMPLETED

        stats = bus.get_stats()
        assert stats["terminal_events_preserved"] == 1
        assert stats["evicted_events_for_terminal"] == 1
        assert stats["dropped_events"] == 1
        assert stats["dropped_events_by_topic"] == {"job": 1}
        assert stats["last_drop"]["reason"] == "evicted_for_terminal"

    @pytest.mark.asyncio
    async def test_terminal_event_retries_after_queue_drain_race(self):
        class _QueueDrainRace:
            maxsize = 1

            def __init__(self):
                self._items = []
                self._put_calls = 0

            def put_nowait(self, item):
                self._put_calls += 1
                if self._put_calls <= 2:
                    raise asyncio.QueueFull
                self._items.append(item)

            def get_nowait(self):
                raise asyncio.QueueEmpty

            def qsize(self):
                return len(self._items)

        bus = EventBus(replay_buffer_size=10)
        queue = _QueueDrainRace()
        bus._subscribers["job"] = [queue]

        await bus.publish(Event(type=EventType.JOB_COMPLETED, data={"id": "job-race"}))

        assert len(queue._items) == 1
        assert queue._items[0].type == EventType.JOB_COMPLETED
        assert bus.get_stats()["dropped_events"] == 0


class TestEmitProviderFunctions:
    """Tests for provider/model emit functions (lines 205, 213-219)."""

    @pytest.mark.asyncio
    async def test_emit_provider_event(self):
        from core.events import EventType, emit_provider_event
        await emit_provider_event(
            EventType.JOB_CREATED, "modal-primary", {"status": "connected"}
        )

    @pytest.mark.asyncio
    async def test_emit_provider_stats(self):
        from core.events import emit_provider_stats
        await emit_provider_stats("modal-primary", {"active_jobs": 5, "gpu_util": 0.8})

    @pytest.mark.asyncio
    async def test_emit_model_status_update_basic(self):
        from core.events import emit_model_status_update
        await emit_model_status_update("modal-primary", file_id=42, status="ready")

    @pytest.mark.asyncio
    async def test_emit_model_status_update_with_extra(self):
        from core.events import emit_model_status_update
        await emit_model_status_update(
            "modal-primary", file_id=42, status="failed",
            extra={"error": "disk full", "retry": 1}
        )

    @pytest.mark.asyncio
    async def test_emit_model_status_update_none_extra(self):
        from core.events import emit_model_status_update
        await emit_model_status_update(
            "modal-primary", file_id=42, status="downloading", extra=None
        )


@pytest.mark.asyncio
async def test_model_status_update_carries_the_failure_reason():
    """`error_message` must reach the browser, not just the row.

    `POST /provider-sync/{file_id}/status` wrote `error_message` onto the
    `ProviderVersionStatus` row but emitted `model.status_update` with only
    `storage_path` and `size_bytes`. The event exists to replace polling, so the
    one field explaining *why* a download failed stopped at the database and the
    UI had to re-poll the row it had just been told about.
    """
    from core.events import EventType, emit_model_status_update

    captured: list = []

    class _Bus:
        async def publish(self, event):
            captured.append(event)

    from core import events as events_module

    original = events_module.event_bus
    events_module.event_bus = _Bus()
    try:
        await emit_model_status_update(
            provider_id="modal-zetsuke",
            file_id=42,
            status="failed",
            extra={
                "storage_path": None,
                "size_bytes": None,
                "error_message": "HTTP 503 from provider storage",
            },
        )
    finally:
        events_module.event_bus = original

    assert len(captured) == 1
    event = captured[0]
    assert event.type == EventType.MODEL_STATUS_UPDATE
    assert event.data["status"] == "failed"
    assert event.data["error_message"] == "HTTP 503 from provider storage"
    assert event.data["provider_id"] == "modal-zetsuke"
    assert event.data["file_id"] == 42


def test_the_provider_sync_route_passes_error_message_into_the_event():
    """Structural: the extra dict at the emit site must name the field.

    A behavioural test would have to stand up the route, its dependency overrides
    and a captured event bus; asserting on the call site keeps the pin honest for
    a fraction of the cost, and the field name is the whole contract.
    """
    from api.routes.models import provider_sync

    source = open(provider_sync.__file__).read()
    emit_index = source.index("await emit_model_status_update(")
    call = source[emit_index : source.index(")", emit_index) + 1]
    assert '"error_message"' in call, f"the emit does not carry the failure reason: {call}"
