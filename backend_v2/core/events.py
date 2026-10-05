# Event Bus - Pub/Sub for real-time updates
#
# ARCHITECTURE:
# - EventBus: Central pub/sub system for backend events
# - WebSocket: Forwards events to connected frontend clients  
# - Events are typed and include structured data payloads
# - Event replay: Last 100 events buffered for debugging
import asyncio
import re
import time
from collections import deque
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from infrastructure.logging import get_logger

logger = get_logger("events")


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------
#
# Backend-side counterpart of `redact_api_key` in the provider layer
# (llm_worker/engines/google/client.py). That one knows the concrete secret and
# does a literal replace; this one is secret-agnostic and works on text the
# backend never had the key for — an httpx/requests exception that embedded a
# URL, a provider-reported error string, a log line.
#
# The concrete leak it exists for: provider_core/downloads.py:712 appends the
# CivitAI token to the download URL as `?token=<secret>`, the transport error
# text carries that whole URL, and the error is persisted as a reconciliation
# `error` and served by /api/v2/providers/status-cards. Redacting at the point
# where the message is stored/returned covers rows that already contain the
# secret as well as future ones.

REDACTED = "***REDACTED***"

# Query/header parameter names whose value is a credential. Matched
# case-insensitively so `?Token=`, `&API_KEY=` and `Authorization:` all hit.
SECRET_PARAM_NAMES = frozenset({
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "civitai_token",
    "hf_token",
    "key",
    "password",
    "proxy-authorization",
    "secret",
    "sig",
    "signature",
    "token",
    "x-amz-credential",
    "x-amz-signature",
    "x-api-key",
})

# Auth schemes that are followed by the actual credential rather than being it.
_AUTH_SCHEMES = r"(?:bearer|token|basic|digest)"

# `?token=abc&x=1` / `"api_key": "abc"` / `Authorization: Bearer hf_x` in free
# text. The separator and any quotes are preserved so the surrounding message
# (and its JSON) stays readable; the value stops at the usual URL/JSON/Python
# delimiters so the rest of the message survives intact.
_SECRET_PARAM_RE = re.compile(
    r"(?i)(?<![\w-])("
    + "|".join(sorted(re.escape(name) for name in SECRET_PARAM_NAMES))
    + r")(\"?\s*[=:]\s*\"?)((?:" + _AUTH_SCHEMES + r")\s+)?([^\s&\"'<>,;)\]}]+)"
)

# `Bearer hf_xxx` on its own, with no parameter name in front of it.
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(" + _AUTH_SCHEMES + r"\s+)([^\s,;\"'}]+)"
)


def redact_secrets(value: Any) -> Any:
    """Strip credential-bearing parameters from a string, or any nested payload.

    Non-strings pass through unchanged, so this is safe to call on a
    reconciliation state dict or a diagnostics list. Applied at the boundary
    where a provider-supplied message is stored or returned, which is what makes
    it cover messages that were persisted before this helper existed.
    """
    if isinstance(value, str):
        redacted = _SECRET_PARAM_RE.sub(
            lambda m: f"{m.group(1)}{m.group(2) or ''}{m.group(3) or ''}{REDACTED}",
            value,
        )
        return _SECRET_VALUE_RE.sub(lambda m: f"{m.group(1)}{REDACTED}", redacted)
    if isinstance(value, dict):
        return {key: redact_secrets(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    return value


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
    
    # NOTE: there is deliberately no `download.*` family here. Model-download
    # status is served by polling the model-status endpoints, not pushed, so the
    # four members that used to sit in this enum (`download.started`,
    # `download.progress`, `download.completed`, `download.failed`) plus the
    # `emit_download_event` helper had zero producers in production code and
    # zero subscribers in the frontend, while the frontend mirrored all four
    # constants — a contract on both sides, implemented by neither, which reads
    # as "push is already wired" to the next person.
    # `frontend_v2/src/test/eventContractInvariants.test.js` fails if a member is
    # re-added without a producer and a frontend counterpart. It is a frontend
    # test because the vocabulary has to be compared across both trees, and it
    # runs in `frontend-tests.yml` rather than `backend-tests.yml` — so a backend
    # change to this enum is only covered once the frontend suite also runs. That
    # is a real gap in the trigger, not a detail: it is why this comment used to
    # name a `backend_v2/tests/test_event_type_invariants.py` that never existed,
    # which read as coverage while providing none.

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
    EventType.RECONCILIATION_COMPLETED,
    EventType.RECONCILIATION_FAILED,
    EventType.MODEL_SYNC_COMPLETED,
    EventType.MODEL_SYNC_FAILED,
    EventType.PROVIDER_DEPLOY_COMPLETED,
    EventType.PROVIDER_DEPLOY_FAILED,
}

# Terminal events whose payload IS the result. `EventBus._preserve_terminal_event`
# keeps a terminal event by evicting the OLDEST queued event to make room, so a
# burst of JOB_COMPLETED does not lose itself — it loses whatever was queued
# before it. When the evicted one is itself a JOB_COMPLETED, the evicted payload
# is a paid LLM response that services/world_integration_service.py is the only
# thing that will ever turn into a `messages` row. Nothing downstream can
# reconstruct it, so these are dropped loudly instead of as a counter tick.
CONTENT_BEARING_EVENT_TYPES = {EventType.JOB_COMPLETED}


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
        event: "Event | None" = None,
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

        if self._is_content_bearing(event_type):
            # ERROR, not WARNING: this is a paid generation whose output is being
            # thrown away, and the only durable trace of it is this line. The job
            # id is the one that names the reply an operator has to re-drive
            # (see world_integration_service.find_unpersisted_chat_replies).
            logger.error(
                "content_bearing_event_dropped",
                topic=topic,
                event_type=event_type,
                reason=reason,
                job_id=self._event_job_id(event),
                dropped_events=self._dropped_events,
                subscriber_count=subscriber_count,
                queue_size=queue.qsize(),
                queue_maxsize=queue.maxsize,
            )
            return

        if self._dropped_events == 1 or self._dropped_events % 50 == 0:
            logger.warning(
                "event_dropped",
                topic=topic,
                event_type=event_type,
                dropped_events=self._dropped_events,
                subscriber_count=subscriber_count,
                reason=reason,
            )

    @staticmethod
    def _is_content_bearing(event_type: str) -> bool:
        try:
            return EventType(event_type) in CONTENT_BEARING_EVENT_TYPES
        except ValueError:
            return False

    @staticmethod
    def _event_job_id(event: "Event | None") -> str | None:
        """Job id carried by a dropped event, for the ERROR log.

        The event is passed through rather than read off the replay buffer: at
        eviction time the newest queued event is the one being ADMITTED, so
        reading the buffer tail would name the wrong job — exactly the one the
        operator does not need to chase.
        """
        try:
            if event is None or not isinstance(event.data, dict):
                return None
            job = event.data.get("job")
            if isinstance(job, dict):
                return job.get("id")
        except Exception:  # pragma: no cover - diagnostics must never raise
            return None
        return None
    
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
                        event=event,
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
                        event=evicted_event,
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
            event=event,
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


def _read_job_terminal_state_sync(job_id: str) -> tuple[str, dict | None] | None:
    """Read one job row synchronously and return its terminal state, if any.

    Returns ``(status_value, first_output)`` when the job is COMPLETED / FAILED /
    CANCELLED, and ``None`` for every other case — the row is missing, or it is
    still active. Callers treat both identically (keep waiting), so the
    distinction is deliberately not surfaced.

    This is a BLOCKING read (SQLModel ``Session`` + ``session.refresh``), which
    is why it is only ever called through ``asyncio.to_thread``.
    """
    from core.entities import Job, JobStatus
    from infrastructure.database import get_session as _db_gs

    with _db_gs() as session:
        job = session.get(Job, job_id)
        if job is None:
            return None
        if job.status not in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return None
        return (job.status.value, job.outputs[0] if job.outputs else None)


async def wait_for_job_completion(
    job_id: str,
    timeout: float = 120.0,
    poll_interval: float = 2.0,
    *,
    poll_interval_max: float = 15.0,
    poll_backoff: float = 1.5,
) -> tuple[str, dict | None]:
    """
    Wait for a job to reach a terminal state via the EventBus.

    Returns:
        (status_str, output_dict_or_None)

    Subscribes to the "job" topic and listens for JOB_COMPLETED / JOB_FAILED /
    JOB_CANCELLED events matching *job_id*.  Falls back to DB polling for
    race-condition safety (the event may fire before we subscribe, and this
    hand-rolled queue can be squeezed by other "job" subscribers).

    The DB poll runs in a worker thread, never on the event loop. It used to be
    a bare `with get_session()` on the loop: this is called from inside the LLM
    job's own worker coroutine with a 330s timeout (orchestrator_service.py), so
    it was two blocking round trips every 2 seconds for over five minutes —
    stalling every other request and the WebSocket broadcast pump, from inside
    the code that is generating the reply it is waiting on. The interval also
    backs off (2s -> 15s) because the event almost always arrives long before
    the poll does; the poll exists for the missed-event race, not as the
    primary path.
    """
    terminal = {EventType.JOB_COMPLETED, EventType.JOB_FAILED, EventType.JOB_CANCELLED}
    result: dict | None = None
    final_status: str = "failed"
    timed_out = False

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    async with event_bus._lock:
        event_bus._subscribers.setdefault("job", []).append(queue)

    async def _poll() -> tuple[str, dict | None] | None:
        try:
            return await asyncio.to_thread(_read_job_terminal_state_sync, job_id)
        except Exception as exc:
            logger.warning(
                "wait_for_job_completion_poll_failed", job_id=job_id, error=str(exc)
            )
            return None

    try:
        # Race-condition guard: check if the job already finished
        state = await _poll()
        if state is not None:
            return state

        deadline = time.monotonic() + timeout
        interval = max(0.1, poll_interval)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=min(remaining, interval))
            except asyncio.TimeoutError:
                # No event — re-check DB, then widen the gap before the next one.
                state = await _poll()
                if state is not None:
                    return state
                interval = min(interval * poll_backoff, max(poll_interval, poll_interval_max))
                continue

            job_data = event.data.get("job", {})
            if job_data.get("id") != job_id:
                # Some other job's event. Reset the backoff: the bus is live, so a
                # short poll is worth it again.
                interval = max(0.1, poll_interval)
                continue

            if event.type in terminal:
                final_status = event.type.value.replace("job.", "")
                result = job_data.get("outputs", [None])[0] if job_data.get("outputs") else None
                return final_status, result
    finally:
        async with event_bus._lock:
            if queue in event_bus._subscribers.get("job", []):
                event_bus._subscribers["job"].remove(queue)

    if timed_out:
        return "timed_out", None
    return final_status, result
