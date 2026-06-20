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

import socketio
import asyncio
import logging
import os
from typing import Dict, Set, Any
from datetime import datetime, timezone

from core.events import event_bus, Event, EventType
from config import settings

logger = logging.getLogger(__name__)

# Determine CORS origins for WebSocket
# Default: accept all connections (for easier development/deployment)
# Can be restricted via COMFY_CORS_ORIGINS environment variable
def _get_ws_cors_origins():
    """Get CORS origins for WebSocket. Returns '*' if settings allow all origins."""
    origins = settings.cors_origins
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
connected_clients: Dict[str, Set[str]] = {}  # sid -> set of rooms
WS_BROADCAST_QUEUE_SIZE = max(int(os.getenv("COMFY_WS_BROADCAST_QUEUE_SIZE", "500")), 1)


class WebSocketManager:
    """
    Manages WebSocket connections and broadcasts events from EventBus.
    
    Integrates with the existing EventBus to forward events to connected clients.
    """
    
    def __init__(self):
        self._broadcast_task = None
        self._running = False
    
    async def start_broadcasting(self):
        """Start listening to EventBus and broadcasting to WebSocket clients."""
        if self._running:
            return
        
        self._running = True
        logger.info("[WebSocket] Starting EventBus broadcast listener")
        
        # Subscribe to all topics
        topics = ["job", "download", "provider", "reconciliation", "model"]
        
        async for event in event_bus.subscribe_multiple(topics, max_queue_size=WS_BROADCAST_QUEUE_SIZE):
            if not self._running:
                break
            
            # Broadcast to appropriate room based on event type
            topic = event.type.value.split(".")[0]
            room = topic  # e.g., "job", "download", "provider"
            
            await sio.emit(
                event.type.value,  # Event name (e.g., "job.progress")
                event.to_dict(),   # Event data
                room=room          # Only send to clients in this room
            )
    
    async def stop_broadcasting(self):
        """Stop the broadcast listener."""
        self._running = False
        if self._broadcast_task:
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass
        logger.info("[WebSocket] Stopped EventBus broadcast listener")


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
    
    # Import here to avoid circular imports
    from services.job_queue import job_queue
    from services.job_service import JobService
    from services.provider_service import ProviderService
    from core.entities import JobStatus
    from api.deps import get_session_context, get_job_service, get_provider_service
    from infrastructure.http_client import get_http_client
    from api.provider_runtime import resolve_provider_runtime
    
    try:
        # Check if job is active in queue
        if job_queue.is_job_active(job_id):
            # Job is currently being processed - signal cancellation to worker
            async with get_session_context() as session:
                job_service = get_job_service(session)
                job = await job_service.get_job(job_id)
                
                # Try to cancel on the provider worker
                if job.provider_id:
                    provider_service = get_provider_service(session)
                    provider = await provider_service.get_provider(job.provider_id)
                    runtime = resolve_provider_runtime(provider)

                    if runtime.mode in ("container_http", "discovery"):
                        try:
                            http_client = get_http_client()
                            response = await http_client.post(
                                f"{runtime.worker_url}/cancel-job",
                                json={"job_id": job_id},
                                timeout=5.0
                            )
                            if response.status_code == 200:
                                logger.info(f"[WebSocket] Worker acknowledged cancel for {job_id}")
                        except Exception as cancel_err:
                            logger.warning(f"[WebSocket] Could not reach worker to cancel: {cancel_err}")
                    elif runtime.mode == "external_worker":
                        try:
                            from api.routes.worker_ws import request_worker_job_cancel

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
            'message': f'Failed to cancel job: {str(e)}',
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
        
    events = event_bus.get_replay_buffer()
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
