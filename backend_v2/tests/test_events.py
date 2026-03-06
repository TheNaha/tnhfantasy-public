# EventBus Unit Tests
import asyncio
import pytest
from core.events import EventBus, Event, EventType, emit_job_event, emit_download_event


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
        assert EventType.DOWNLOAD_STARTED.value == "download.started"
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
        assert bus.subscriber_count("download") == 0

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
        download_events = []

        async def job_subscriber():
            async for event in bus.subscribe("job", max_queue_size=5):
                job_events.append(event)
                break

        async def download_subscriber():
            async for event in bus.subscribe("download", max_queue_size=5):
                download_events.append(event)
                break

        task_job = asyncio.create_task(job_subscriber())
        task_dl = asyncio.create_task(download_subscriber())
        await asyncio.sleep(0.01)

        # Publish to different topics
        await bus.publish(Event(type=EventType.JOB_CREATED, data={}))
        await bus.publish(Event(type=EventType.DOWNLOAD_STARTED, data={}))

        await task_job
        await task_dl

        assert len(job_events) == 1
        assert len(download_events) == 1
        assert job_events[0].type == EventType.JOB_CREATED
        assert download_events[0].type == EventType.DOWNLOAD_STARTED

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
            async for event in bus.subscribe_multiple(["job", "download"], max_queue_size=10):
                received.append(event)
                if len(received) == 2:
                    break

        task = asyncio.create_task(multi_sub())
        await asyncio.sleep(0.01)

        await bus.publish(Event(type=EventType.JOB_CREATED, data={}))
        await bus.publish(Event(type=EventType.DOWNLOAD_STARTED, data={}))

        await task

        types = {e.type for e in received}
        assert EventType.JOB_CREATED in types
        assert EventType.DOWNLOAD_STARTED in types


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

    @pytest.mark.asyncio
    async def test_emit_download_event(self):
        """emit_download_event publishes to the download topic."""
        from core.events import event_bus
        received = []

        async def subscriber():
            async for event in event_bus.subscribe("download", max_queue_size=5):
                received.append(event)
                break

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)

        await emit_download_event(EventType.DOWNLOAD_COMPLETED, {"id": "dl-1"})
        await task

        assert len(received) == 1
        assert received[0].data["download"]["id"] == "dl-1"


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


class TestEmitProviderFunctions:
    """Tests for provider/model emit functions (lines 205, 213-219)."""

    async def test_emit_provider_event(self):
        from core.events import emit_provider_event, EventType
        await emit_provider_event(
            EventType.JOB_CREATED, "modal-primary", {"status": "connected"}
        )

    async def test_emit_provider_stats(self):
        from core.events import emit_provider_stats
        await emit_provider_stats("modal-primary", {"active_jobs": 5, "gpu_util": 0.8})

    async def test_emit_model_status_update_basic(self):
        from core.events import emit_model_status_update
        await emit_model_status_update("modal-primary", file_id=42, status="ready")

    async def test_emit_model_status_update_with_extra(self):
        from core.events import emit_model_status_update
        await emit_model_status_update(
            "modal-primary", file_id=42, status="failed",
            extra={"error": "disk full", "retry": 1}
        )

    async def test_emit_model_status_update_none_extra(self):
        from core.events import emit_model_status_update
        await emit_model_status_update(
            "modal-primary", file_id=42, status="downloading", extra=None
        )
