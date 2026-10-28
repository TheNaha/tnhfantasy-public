"""
WebSocket Route Handler using Socket.IO

Provides bidirectional realtime communication between frontend and backend.
Replaces SSE for job updates, downloads, reconciliation, and provider status.

Features:
- Room-based subscriptions (jobs, downloads, reconciliation, provider)
- Bidirectional messaging (job cancellation, etc.)
- Automatic reconnection handling via Socket.IO protocol
- Integration with existing EventBus for event broadcasting
"""

import asyncio
import json
import logging
import os
import select
from datetime import datetime, timezone

import psycopg2
import socketio

from api.deps import (
    get_event_bus,
    get_job_service,
    get_provider_service,
    get_session_context,
)
from core.entities import JobStatus
from core.events import CROSS_PROCESS_EVENT_CHANNEL, EventType
from infrastructure.database import database_url

from services.job_queue import queue_manager
from services.provider_runtime import resolve_provider_runtime_async

# The rooms a client may join, derived from the event vocabulary. A room name is
# the prefix of an `EventType` value, so this is the complete set of rooms that
# can ever receive a broadcast — see `start_broadcasting`.
BROADCAST_TOPICS = frozenset(e.value.split(".")[0] for e in EventType)

logger = logging.getLogger(__name__)

# Determine CORS origins for WebSocket
# Reads from get_cors_origins() which honours config.json ("*" wildcard)
# so the Socket.IO server is consistent with the FastAPI CORS middleware.
# NOTE: sio is created at import time, so we must resolve the origins here
# using get_cors_origins() rather than the bare settings object (which only
# reflects env-var overrides, not config.json values).
def _get_ws_cors_origins():
    """Get CORS origins for WebSocket. Returns '*' if settings allow all origins."""
    from config import get_cors_origins
    origins = get_cors_origins()
    # If settings contains wildcard patterns or is empty, allow all
    if not origins or '*' in origins:
        return '*'
    return origins

# Create Socket.IO server with CORS support
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins=_get_ws_cors_origins(),
    logger=False,
    engineio_logger=False,
    ping_timeout=120,
    ping_interval=30,
)


# Track connected clients and their subscriptions
connected_clients: dict[str, set[str]] = {}  # sid -> set of rooms
try:
    WS_BROADCAST_QUEUE_SIZE = max(int(os.getenv("COMFY_WS_BROADCAST_QUEUE_SIZE", "500")), 1)
except (TypeError, ValueError):
    WS_BROADCAST_QUEUE_SIZE = 500


class WebSocketManager:
    """
    Manages WebSocket connections and broadcasts events from EventBus.
    
    Integrates with the existing EventBus to forward events to connected clients.
    """
    
    def __init__(self):
        self._broadcast_task: asyncio.Task | None = None
        self._notify_task: asyncio.Task | None = None
        self._running = False
    
    async def start_broadcasting(self):
        """Start listening to EventBus and broadcasting to WebSocket clients."""
        if self._running:
            return
        
        self._running = True
        # Recorded so `stop_broadcasting` can cancel it. This was assigned only in
        # `__init__` as `None` and never set, so the `if self._broadcast_task:`
        # guard in the stop path was permanently False and lines 111-115 never
        # ran — `_running = False` was the only thing the stop method did.
        #
        # It also could not have worked by polling: the loop checks `_running`
        # only *after* receiving an event, so on a quiet bus it never re-checks
        # and a bare flag flip is not enough to stop it. Cancelling the task is,
        # and `EventBus.subscribe_multiple` has a `finally` that cancels its
        # pending queue reads and unsubscribes, so this is the clean exit.
        self._broadcast_task = asyncio.current_task()
        logger.info("[WebSocket] Starting EventBus broadcast listener")
        
        # Cross-process event relay: LISTEN on Postgres NOTIFY channel and
        # re-broadcast to local Socket.IO clients. Without this, events emitted
        # on another backend worker process (UVICORN_WORKERS > 1) never reach
        # the WebSocket clients connected to this process.
        if database_url.startswith("postgresql"):
            self._notify_task = asyncio.create_task(
                self._notify_listener(), name="ws_notify_listener"
            )
            logger.info(
                "[WebSocket] Starting cross-process NOTIFY listener",
                channel=CROSS_PROCESS_EVENT_CHANNEL,
            )
        
        # Derived from `EventType` rather than listed by hand, because the room
        # name is `event.type.value.split(".")[0]` (below) — so the set of rooms
        # that can ever receive anything IS the set of enum prefixes. The list was
        # hand-maintained and still contained `"download"` after the whole
        # `download.*` family was removed on 2026-10-03, which meant a client
        # could subscribe to a room that would never receive an event and receive
        # an `ack` saying it had.
        topics = sorted(BROADCAST_TOPICS)
        
        async for event in get_event_bus().subscribe_multiple(topics, max_queue_size=WS_BROADCAST_QUEUE_SIZE):
            if not self._running:
                break
            
            # Broadcast to appropriate room based on event type
            topic = event.type.value.split(".")[0]
            room = topic  # e.g., "job", "download", "provider"
            
            try:
                await sio.emit(
                    event.type.value,  # Event name (e.g., "job.progress")
                    event.to_dict(),   # Event data
                    room=room          # Only send to clients in this room
                )
            except Exception as e:
                logger.error(f"[WebSocket] Error broadcasting event {event.type.value}: {e}")
    
    async def stop_broadcasting(self):
        """Stop the broadcast listener."""
        self._running = False
        if self._broadcast_task:
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass
        if self._notify_task:
            self._notify_task.cancel()
            try:
                await self._notify_task
            except asyncio.CancelledError:
                pass
        logger.info("[WebSocket] Stopped EventBus broadcast listener")

    async def _notify_listener(self) -> None:
        """LISTEN on Postgres NOTIFY channel and re-broadcast to local WS clients.

        Runs for the life of the WebSocketManager. On each NOTIFY, parses the
        payload and emits the event to the appropriate Socket.IO room so
        clients connected to this process see events from sibling processes.
        """
        conn = psycopg2.connect(database_url)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(f"LISTEN {CROSS_PROCESS_EVENT_CHANNEL}")
            logger.info(
                "[WebSocket] NOTIFY listener connected",
                channel=CROSS_PROCESS_EVENT_CHANNEL,
            )
            while self._running:
                # Wait up to 1 second for a notification so we can check
                # _running regularly and exit cleanly on shutdown.
                if select.select([conn], [], [], 1.0) == ([], [], []):
                    continue
                conn.poll()
                for notify in conn.notifies:
                    conn.notifies.clear()
                    try:
                        payload = json.loads(notify.payload)
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(
                            "[WebSocket] Invalid NOTIFY payload",
                            channel=CROSS_PROCESS_EVENT_CHANNEL,
                            payload=notify.payload[:200],
                        )
                        continue

                    event_type = payload.get("event")
                    job = payload.get("job", {})
                    if not event_type:
                        continue

                    # Emit to the room derived from the event type prefix,
                    # same as the EventBus path. Job data is minimal (id only);
                    # clients that need more poll GET /api/jobs/{id}.
                    room = event_type.split(".")[0] if "." in event_type else event_type
                    try:
                        await sio.emit(
                            event_type,
                            {"job": job},
                            room=room,
                        )
                    except Exception as e:
                        logger.error(
                            "[WebSocket] Error re-broadcasting NOTIFY event",
                            event=event_type,
                            error=str(e),
                        )
        except asyncio.CancelledError:
            logger.info(
                "[WebSocket] NOTIFY listener cancelled",
                channel=CROSS_PROCESS_EVENT_CHANNEL,
            )
            raise
        except Exception as e:
            logger.error(
                "[WebSocket] NOTIFY listener error",
                channel=CROSS_PROCESS_EVENT_CHANNEL,
                error=str(e),
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass
            logger.info(
                "[WebSocket] NOTIFY listener stopped",
                channel=CROSS_PROCESS_EVENT_CHANNEL,
            )


# Global manager instance
ws_manager = WebSocketManager()


# ============================================================================
# Socket.IO Event Handlers
# ============================================================================

@sio.event
async def connect(sid, environ):
    """Handle client connection."""
    connected_clients[sid] = set()
    logger.info(f"[WebSocket] Client connected: {sid}")
    
    # Send welcome message with connection info
    await sio.emit('connected', {
        'sid': sid,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'message': 'Connected to ComfyUI WebSocket'
    }, room=sid)


@sio.event
async def disconnect(sid):
    """Handle client disconnection."""
    # Leave all rooms
    rooms = connected_clients.pop(sid, set())
    for room in rooms:
        await sio.leave_room(sid, room)
    logger.info(f"[WebSocket] Client disconnected: {sid} (was in rooms: {rooms})")


@sio.event
async def subscribe(sid, data):
    """
    Subscribe to a topic (join a room).
    
    Client sends: { "topic": "job" } or { "topics": ["job", "download"] }
    """
    topics = data.get('topics', [])
    if not topics and 'topic' in data:
        topics = [data['topic']]
    
    topics = [topic for topic in topics if topic in BROADCAST_TOPICS]
    for topic in topics:
        await sio.enter_room(sid, topic)
        connected_clients.setdefault(sid, set()).add(topic)
        logger.debug(f"[WebSocket] Client {sid} subscribed to: {topic}")
    
    await sio.emit('subscribed', {'topics': topics}, room=sid)


@sio.event
async def unsubscribe(sid, data):
    """
    Unsubscribe from a topic (leave a room).
    
    Client sends: { "topic": "job" } or { "topics": ["job", "download"] }
    """
    topics = data.get('topics', [])
    if not topics and 'topic' in data:
        topics = [data['topic']]
    
    for topic in topics:
        await sio.leave_room(sid, topic)
        connected_clients.get(sid, set()).discard(topic)
        logger.debug(f"[WebSocket] Client {sid} unsubscribed from: {topic}")
    
    await sio.emit('unsubscribed', {'topics': topics}, room=sid)


@sio.event
async def cancel_job(sid, data):
    """
    Handle job cancellation request from client.
    
    Client sends: { "job_id": "xxx" }
    """
    job_id = data.get('job_id')
    if not job_id:
        await sio.emit('error', {'message': 'job_id required'}, room=sid)
        return
    
    logger.info(f"[WebSocket] Job cancellation requested: {job_id} by {sid}")
    
    try:
        # Check if job is active in queue.
        #
        # ANY pool: the TTS pool used to be left out of this test, so a
        # running TTS generation fell into the "still queued" branch, whose
        # status check is false for a running job - the client was told
        # "cannot cancel" and the provider was never signalled, so the
        # generation kept running and billing.
        if queue_manager.is_job_active_anywhere(job_id):
            # Job is currently being processed - signal cancellation to worker
            async with get_session_context() as session:
                job_service = get_job_service(session)
                job = await job_service.get_job(job_id)
                
                # Try to cancel on the provider worker
                if job.provider_id:
                    provider_service = get_provider_service(session)
                    provider = await provider_service.get_provider(job.provider_id)
                    runtime = await resolve_provider_runtime_async(provider)

                    if runtime.mode == "in_process":
                        # Reach the engine instance actually streaming the job;
                        # the factory cache may hold a different instance.
                        try:
                            from services.engines.base import find_engine_for_job
                            from services.engines.engine_factory import get_engine

                            engine = find_engine_for_job(job_id) or get_engine(provider.id)
                            if engine and hasattr(engine, "cancel_job"):
                                await engine.cancel_job(job_id)
                                logger.info(f"[WebSocket] In-process engine acknowledged cancel for {job_id}")
                        except Exception as cancel_err:
                            logger.warning(f"[WebSocket] Could not signal in-process engine to cancel: {cancel_err}")
                    elif runtime.mode == "external_worker":
                        try:
                            from infrastructure.worker_registry import request_worker_job_cancel

                            await request_worker_job_cancel(provider.id, job_id)
                        except Exception as cancel_err:
                            logger.warning(f"[WebSocket] Could not signal external worker to cancel: {cancel_err}")
                
                # Mark as cancelled in DB
                await job_service.update_job(job_id, status=JobStatus.CANCELLED)
            
            await sio.emit('cancel_job_ack', {
                'job_id': job_id,
                'status': 'cancellation_requested',
                'message': 'Job is running, cancellation signal sent'
            }, room=sid)
        else:
            # Job is pending in queue - can cancel immediately
            async with get_session_context() as session:
                job_service = get_job_service(session)
                job = await job_service.get_job(job_id)
                
                if job.status.value == 'pending':
                    await job_service.update_job(job_id, status=JobStatus.CANCELLED)
                    await sio.emit('cancel_job_ack', {
                        'job_id': job_id,
                        'status': 'cancelled',
                        'message': 'Pending job cancelled'
                    }, room=sid)
                else:
                    await sio.emit('cancel_job_ack', {
                        'job_id': job_id,
                        'status': 'cannot_cancel',
                        'message': f'Job is {job.status.value}, cannot cancel'
                    }, room=sid)
                    
    except Exception as e:
        logger.error(f"[WebSocket] Cancel job error: {e}")
        await sio.emit('error', {
            'message': f'Failed to cancel job: {e!s}',
            'job_id': job_id
        }, room=sid)


@sio.event
async def ping(sid, data):
    """Handle ping for connection keepalive."""
    await sio.emit('pong', {'timestamp': datetime.now(timezone.utc).isoformat()}, room=sid)


@sio.event
async def request_replay(sid, data):
    """
    Handle replay request from client.
    Allows clients to request events from the replay buffer having a sequence number 
    greater than a client-provided last_sequence_number.
    """
    if not isinstance(data, dict):
        last_seq = data
    else:
        last_seq = data.get('last_sequence_number')
        
    if last_seq is None:
        await sio.emit('error', {'message': 'last_sequence_number is required'}, room=sid)
        return
        
    try:
        last_seq = int(last_seq)
    except (ValueError, TypeError):
        await sio.emit('error', {'message': 'last_sequence_number must be an integer'}, room=sid)
        return
        
    events = get_event_bus().get_replay_buffer()
    filtered_events = [
        event.to_dict() for event in events
        if event.sequence_number is not None and event.sequence_number > last_seq
    ]
    
    await sio.emit('replay_events', {'events': filtered_events}, room=sid)


# ============================================================================
# Utility Functions
# ============================================================================

async def broadcast_to_room(room: str, event_type: str, data: dict):
    """
    Broadcast an event to all clients in a room.
    
    Can be called from other parts of the application to send events.
    """
    await sio.emit(event_type, data, room=room)


async def broadcast_to_all(event_type: str, data: dict):
    """Broadcast an event to all connected clients."""
    await sio.emit(event_type, data)


def get_connected_count() -> int:
    """Get number of connected clients."""
    return len(connected_clients)


def get_room_count(room: str) -> int:
    """Get number of clients subscribed to a room."""
    count = 0
    for sid, rooms in connected_clients.items():
        if room in rooms:
            count += 1
    return count


# ============================================================================
# ASGI App for mounting in FastAPI
# ============================================================================

# Create ASGI app wrapper for Socket.IO
socket_app = socketio.ASGIApp(sio)
