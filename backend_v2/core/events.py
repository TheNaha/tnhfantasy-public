# Event Bus - Pub/Sub for real-time updates
#
# ARCHITECTURE:
# - EventBus: Central pub/sub system for backend events
# - WebSocket: Forwards events to connected frontend clients  
# - Events are typed and include structured data payloads
# - Event replay: Last 100 events buffered for debugging
import asyncio
from collections import deque
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from infrastructure.logging import get_logger

logger = get_logger("events")


class EventType(str, Enum):
    """Event types for real-time updates."""
    # Job events
    JOB_CREATED = "job.created"
    JOB_UPDATED = "job.updated"
    JOB_PROGRESS = "job.progress"
    JOB_COMPLETED = "job.completed"
    JOB_POST_PROCESSING = "job.post_processing"
    JOB_FAILED = "job.failed"
    JOB_CANCELLED = "job.cancelled"
    
    # Download events
    DOWNLOAD_STARTED = "download.started"
    DOWNLOAD_PROGRESS = "download.progress"
    DOWNLOAD_COMPLETED = "download.completed"
    DOWNLOAD_FAILED = "download.failed"
    
    # Provider events
    PROVIDER_STATUS = "provider.status"
    PROVIDER_CONTAINER_STATUS = "provider.container_status"
    PROVIDER_STATS_UPDATE = "provider.stats_update"  # Modal stats, sync counts
    
    # Deployment events
    PROVIDER_DEPLOY_STARTED = "provider.deploy_started"
    PROVIDER_DEPLOY_PROGRESS = "provider.deploy_progress"
    PROVIDER_DEPLOY_COMPLETED = "provider.deploy_completed"
    PROVIDER_DEPLOY_FAILED = "provider.deploy_failed"
    
    # Model status events (for frontend cache invalidation)
    MODEL_STATUS_UPDATE = "model.status_update"  # Per-provider model status changes
    
    # Reconciliation events
    RECONCILIATION_STARTED = "reconciliation.started"
    RECONCILIATION_PROGRESS = "reconciliation.progress"
    RECONCILIATION_COMPLETED = "reconciliation.completed"
    RECONCILIATION_FAILED = "reconciliation.failed"
    
    # Model sync events (for per-model download progress)
    MODEL_SYNC_STARTED = "model.sync_started"
    MODEL_SYNC_PROGRESS = "model.sync_progress"
    MODEL_SYNC_COMPLETED = "model.sync_completed"
    MODEL_SYNC_FAILED = "model.sync_failed"


TERMINAL_EVENT_TYPES = {
    EventType.JOB_COMPLETED,
    EventType.JOB_FAILED,
    EventType.JOB_CANCELLED,
    EventType.DOWNLOAD_COMPLETED,
    EventType.DOWNLOAD_FAILED,
    EventType.RECONCILIATION_COMPLETED,
    EventType.RECONCILIATION_FAILED,
    EventType.MODEL_SYNC_COMPLETED,
    EventType.MODEL_SYNC_FAILED,
    EventType.PROVIDER_DEPLOY_COMPLETED,
    EventType.PROVIDER_DEPLOY_FAILED,
}


@dataclass
class Event:
    """Event payload for SSE streaming."""
    type: EventType
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    sequence_number: int | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "sequence_number": self.sequence_number
        }


class EventBus:
    """
    In-memory event bus for real-time updates.
    
    Publishers emit events, subscribers receive them via async generators.
    Topics are derived from event type prefixes (job, download, provider, etc.)
    
    Features:
    - Event replay buffer (last 100 events for debugging)
    - Non-blocking publish (slow subscribers don't block publishers)
    - Multi-topic subscriptions
    """
    
    def __init__(self, replay_buffer_size: int = 100):
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
        self._replay_buffer: deque = deque(maxlen=replay_buffer_size)
        self._replay_enabled = True
        self._dropped_events = 0
        self._dropped_events_by_topic: dict[str, int] = {}
        self._terminal_events_preserved = 0
        self._terminal_events_dropped = 0
        self._evicted_events_for_terminal = 0
        self._last_drop: dict[str, Any] | None = None
        self._sequence_counter = 0

    def _record_drop(
        self,
        *,
        topic: str,
        event_type: str,
        subscriber_count: int,
        queue: asyncio.Queue,
        reason: str,
    ) -> None:
        self._dropped_events += 1
        self._dropped_events_by_topic[topic] = self._dropped_events_by_topic.get(topic, 0) + 1
        self._last_drop = {
            "topic": topic,
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "subscriber_count": subscriber_count,
            "queue_size": queue.qsize(),
            "queue_maxsize": queue.maxsize,
            "reason": reason,
        }
        if reason == "terminal_event_dropped":
            self._terminal_events_dropped += 1
        elif reason == "evicted_for_terminal":
            self._evicted_events_for_terminal += 1

        if self._dropped_events == 1 or self._dropped_events % 50 == 0:
            logger.warning(
                "event_dropped",
                topic=topic,
                event_type=event_type,
                dropped_events=self._dropped_events,
                subscriber_count=subscriber_count,
                reason=reason,
            )
    
    async def publish(self, event: Event) -> None:
        """
        Publish an event to all subscribers of its topic.
        
        Args:
            event: Event to publish
        """
        # Extract topic from event type (e.g., "job" from "job.created")
        topic = event.type.value.split(".")[0]
        
        async with self._lock:
            self._sequence_counter += 1
            event.sequence_number = self._sequence_counter
            # Add to replay buffer
            if self._replay_enabled:
                self._replay_buffer.append(event)
            
            queues = self._subscribers.get(topic, [])
            for queue in queues:
                try:
                    # Non-blocking put to avoid slow subscribers blocking publishers
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    # Preserve terminal events by retrying enqueue and evicting stale
                    # queued events as needed.
                    if event.type in TERMINAL_EVENT_TYPES and self._preserve_terminal_event(
                        queue=queue,
                        event=event,
                        subscriber_count=len(queues),
                    ):
                        continue

                    self._record_drop(
                        topic=topic,
                        event_type=event.type.value,
                        subscriber_count=len(queues),
                        queue=queue,
                        reason="queue_full",
                    )

    def _preserve_terminal_event(
        self,
        *,
        queue: asyncio.Queue,
        event: Event,
        subscriber_count: int,
    ) -> bool:
        """Best-effort enqueue for terminal events under backpressure."""
        topic = event.type.value.split(".")[0]
        evicted_any = False
        max_attempts = max(3, (queue.maxsize if queue.maxsize > 0 else 1) + 1)

        for _attempt in range(max_attempts):
            try:
                queue.put_nowait(event)
                if evicted_any:
                    self._terminal_events_preserved += 1
                return True
            except asyncio.QueueFull:
                try:
                    evicted_event = queue.get_nowait()
                    evicted_any = True
                    evicted_topic = evicted_event.type.value.split(".")[0]
                    self._record_drop(
                        topic=evicted_topic,
                        event_type=evicted_event.type.value,
                        subscriber_count=subscriber_count,
                        queue=queue,
                        reason="evicted_for_terminal",
                    )
                except asyncio.QueueEmpty:
                    # Consumer may have drained queue after QueueFull check; retry put.
                    continue

        self._record_drop(
            topic=topic,
            event_type=event.type.value,
            subscriber_count=subscriber_count,
            queue=queue,
            reason="terminal_event_dropped",
        )
        return False
    
    async def subscribe(self, topic: str, max_queue_size: int = 100) -> AsyncGenerator[Event, None]:
        """
        Subscribe to events of a specific topic.
        
        Args:
            topic: Topic to subscribe to (e.g., "job", "download")
            max_queue_size: Maximum events to buffer
            
        Yields:
            Events as they are published
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        
        async with self._lock:
            self._subscribers.setdefault(topic, []).append(queue)
        
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            async with self._lock:
                self._subscribers[topic].remove(queue)
    
    async def subscribe_multiple(self, topics: list[str], max_queue_size: int = 100) -> AsyncGenerator[Event, None]:
        """
        Subscribe to multiple topics.
        
        Args:
            topics: List of topics to subscribe to
            max_queue_size: Maximum events to buffer per topic
        """
        topic_queues: dict[str, asyncio.Queue] = {}

        async with self._lock:
            for topic in topics:
                queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
                topic_queues[topic] = queue
                self._subscribers.setdefault(topic, []).append(queue)

        pending_gets = {
            asyncio.create_task(queue.get()): topic
            for topic, queue in topic_queues.items()
        }
        
        try:
            while True:
                done, _ = await asyncio.wait(
                    pending_gets.keys(),
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in done:
                    topic = pending_gets.pop(task, None)
                    if topic is None:
                        continue

                    try:
                        event = task.result()
                    except asyncio.CancelledError:
                        continue

                    # Re-arm the queue read for the same topic before yielding.
                    pending_gets[asyncio.create_task(topic_queues[topic].get())] = topic
                    yield event
        finally:
            for task in pending_gets:
                task.cancel()
            if pending_gets:
                await asyncio.gather(*pending_gets.keys(), return_exceptions=True)

            async with self._lock:
                for topic, queue in topic_queues.items():
                    if queue in self._subscribers.get(topic, []):
                        self._subscribers[topic].remove(queue)
    
    def subscriber_count(self, topic: str) -> int:
        """Get number of subscribers for a topic."""
        return len(self._subscribers.get(topic, []))

    def dropped_event_count(self) -> int:
        """Get the number of events dropped because subscriber queues were full."""
        return self._dropped_events

    def dropped_event_counts_by_topic(self) -> dict[str, int]:
        """Get drop counts grouped by topic."""
        return dict(self._dropped_events_by_topic)

    def get_stats(self) -> dict[str, Any]:
        """Get a snapshot of event bus health for diagnostics."""
        return {
            "subscriber_counts": {
                topic: len(queues)
                for topic, queues in self._subscribers.items()
            },
            "replay_buffer_size": len(self._replay_buffer),
            "replay_buffer_capacity": self._replay_buffer.maxlen,
            "dropped_events": self._dropped_events,
            "dropped_events_by_topic": dict(self._dropped_events_by_topic),
            "terminal_events_preserved": self._terminal_events_preserved,
            "terminal_events_dropped": self._terminal_events_dropped,
            "evicted_events_for_terminal": self._evicted_events_for_terminal,
            "last_drop": dict(self._last_drop) if self._last_drop else None,
        }
    
    def get_replay_buffer(self, limit: int | None = None) -> list[Event]:
        """
        Get recent events from replay buffer (for debugging).
        
        Args:
            limit: Maximum number of events to return (None = all)
        """
        events = list(self._replay_buffer)
        if limit:
            return events[-limit:]
        return events
    
    def clear_replay_buffer(self) -> None:
        """Clear the replay buffer."""
        self._replay_buffer.clear()


# Global singleton instance
event_bus = EventBus()


# Convenience functions for publishing events
async def emit_job_event(event_type: EventType, job_data: dict[str, Any]) -> None:
    """Emit a job-related event."""
    await event_bus.publish(Event(type=event_type, data={"job": job_data}))


async def emit_download_event(event_type: EventType, download_data: dict[str, Any]) -> None:
    """Emit a download-related event."""
    await event_bus.publish(Event(type=event_type, data={"download": download_data}))


async def emit_provider_event(event_type: EventType, provider_id: str, data: dict[str, Any]) -> None:
    """Emit a provider-related event."""
    await event_bus.publish(Event(type=event_type, data={"provider_id": provider_id, **data}))


async def emit_provider_stats(provider_id: str, stats: dict[str, Any]) -> None:
    """Emit provider stats update (replaces polling for modal-stats)."""
    await event_bus.publish(Event(
        type=EventType.PROVIDER_STATS_UPDATE,
        data={"provider_id": provider_id, "stats": stats}
    ))


async def emit_model_status_update(provider_id: str, file_id: int, status: str, extra: dict[str, Any] = None) -> None:
    """Emit model status update (replaces polling for sync-status)."""
    data = {
        "provider_id": provider_id,
        "file_id": file_id,
        "status": status,
        **(extra or {})
    }
    await event_bus.publish(Event(type=EventType.MODEL_STATUS_UPDATE, data=data))
