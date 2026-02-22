# Event Bus - Pub/Sub for real-time updates
#
# ARCHITECTURE:
# - EventBus: Central pub/sub system for backend events
# - WebSocket: Forwards events to connected frontend clients  
# - Events are typed and include structured data payloads
# - Event replay: Last 100 events buffered for debugging
import asyncio
import json
from typing import Dict, List, Any, AsyncGenerator, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from collections import deque


class EventType(str, Enum):
    """Event types for real-time updates."""
    # Job events
    JOB_CREATED = "job.created"
    JOB_UPDATED = "job.updated"
    JOB_PROGRESS = "job.progress"
    JOB_COMPLETED = "job.completed"
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
    
    # Model status events (for frontend cache invalidation)
    MODEL_STATUS_UPDATE = "model.status_update"  # Per-provider model status changes
    
    # Reconciliation events
    RECONCILIATION_STARTED = "reconciliation.started"
    RECONCILIATION_PROGRESS = "reconciliation.progress"
    RECONCILIATION_COMPLETED = "reconciliation.completed"
    
    # Model sync events (for per-model download progress)
    MODEL_SYNC_STARTED = "model.sync_started"
    MODEL_SYNC_PROGRESS = "model.sync_progress"
    MODEL_SYNC_COMPLETED = "model.sync_completed"
    MODEL_SYNC_FAILED = "model.sync_failed"


@dataclass
class Event:
    """Event payload for SSE streaming."""
    type: EventType
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    

    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp.isoformat()
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
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
        self._replay_buffer: deque = deque(maxlen=replay_buffer_size)
        self._replay_enabled = True
    
    async def publish(self, event: Event) -> None:
        """
        Publish an event to all subscribers of its topic.
        
        Args:
            event: Event to publish
        """
        # Extract topic from event type (e.g., "job" from "job.created")
        topic = event.type.value.split(".")[0]
        
        async with self._lock:
            # Add to replay buffer
            if self._replay_enabled:
                self._replay_buffer.append(event)
            
            queues = self._subscribers.get(topic, [])
            for queue in queues:
                try:
                    # Non-blocking put to avoid slow subscribers blocking publishers
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    # Drop event if queue is full (subscriber too slow)
                    pass
    
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
    
    async def subscribe_multiple(self, topics: List[str], max_queue_size: int = 100) -> AsyncGenerator[Event, None]:
        """
        Subscribe to multiple topics.
        
        Args:
            topics: List of topics to subscribe to
            max_queue_size: Maximum events to buffer per topic
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        
        async with self._lock:
            for topic in topics:
                self._subscribers.setdefault(topic, []).append(queue)
        
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            async with self._lock:
                for topic in topics:
                    if queue in self._subscribers.get(topic, []):
                        self._subscribers[topic].remove(queue)
    
    def subscriber_count(self, topic: str) -> int:
        """Get number of subscribers for a topic."""
        return len(self._subscribers.get(topic, []))
    
    def get_replay_buffer(self, limit: Optional[int] = None) -> List[Event]:
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
async def emit_job_event(event_type: EventType, job_data: Dict[str, Any]) -> None:
    """Emit a job-related event."""
    await event_bus.publish(Event(type=event_type, data={"job": job_data}))


async def emit_download_event(event_type: EventType, download_data: Dict[str, Any]) -> None:
    """Emit a download-related event."""
    await event_bus.publish(Event(type=event_type, data={"download": download_data}))


async def emit_provider_event(event_type: EventType, provider_id: str, data: Dict[str, Any]) -> None:
    """Emit a provider-related event."""
    await event_bus.publish(Event(type=event_type, data={"provider_id": provider_id, **data}))


async def emit_provider_stats(provider_id: str, stats: Dict[str, Any]) -> None:
    """Emit provider stats update (replaces polling for modal-stats)."""
    await event_bus.publish(Event(
        type=EventType.PROVIDER_STATS_UPDATE,
        data={"provider_id": provider_id, "stats": stats}
    ))


async def emit_model_status_update(provider_id: str, file_id: int, status: str, extra: Dict[str, Any] = None) -> None:
    """Emit model status update (replaces polling for sync-status)."""
    data = {
        "provider_id": provider_id,
        "file_id": file_id,
        "status": status,
        **(extra or {})
    }
    await event_bus.publish(Event(type=EventType.MODEL_STATUS_UPDATE, data=data))
