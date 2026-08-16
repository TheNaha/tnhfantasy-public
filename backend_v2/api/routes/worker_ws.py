"""
Worker WebSocket Endpoint

Allows external workers (Kaggle, Colab, etc.) to connect and receive jobs.
Workers are ephemeral - they connect, process jobs, and disconnect.

Protocol:
1. Worker connects to /ws/worker/{provider_id} with auth token
2. Backend authenticates and registers worker
3. Jobs are pushed to connected workers via WebSocket
4. Worker sends results back
5. Heartbeat keeps connection alive
"""

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from api.deps import (
    get_job_service,
    get_logger,
    get_provider_service,
    get_session_context,
)
from core.exceptions import NotFoundError
from services.job_processing import (
    finalize_persisted_job_outputs,
    normalize_external_outputs,
)
from services.provider_client import ProviderCallError

logger = get_logger("worker_ws")

router = APIRouter(tags=["worker-ws"])


# ============================================================================
# Connected Workers Registry
# ============================================================================

class ConnectedWorker:
    """Tracks a connected worker session."""
    def __init__(self, ws: WebSocket, provider_id: str):
        self.ws = ws
        self.provider_id = provider_id
        self.connected_at = datetime.now(timezone.utc)
        self.last_heartbeat = datetime.now(timezone.utc)
        self.current_job: str | None = None
        self.jobs_completed: int = 0
    
    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "connected_at": self.connected_at.isoformat(),
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "current_job": self.current_job,
            "jobs_completed": self.jobs_completed,
        }


# Global registry of connected workers
connected_workers: dict[str, ConnectedWorker] = {}  # provider_id -> worker
pending_job_futures: dict[str, asyncio.Future] = {}
WORKER_HEARTBEAT_TIMEOUT_SECONDS = 90
_workers_lock = asyncio.Lock()
_futures_lock = asyncio.Lock()


def _is_socket_connected(worker: ConnectedWorker) -> bool:
    state = getattr(worker.ws, "client_state", None)
    if state is None:
        return True
    return getattr(state, "name", "").upper() == "CONNECTED"


def _get_live_worker_unlocked(provider_id: str) -> ConnectedWorker | None:
    """Read-only worker lookup. Caller must hold _workers_lock if mutation is needed."""
    worker = connected_workers.get(provider_id)
    if not worker:
        return None

    if not _is_socket_connected(worker):
        return None

    heartbeat_age = (datetime.now(timezone.utc) - worker.last_heartbeat).total_seconds()
    if heartbeat_age > WORKER_HEARTBEAT_TIMEOUT_SECONDS:
        logger.warning(
            "worker_heartbeat_stale",
            provider_id=provider_id,
            age_seconds=round(heartbeat_age, 1),
        )
        return None

    return worker


async def _get_live_worker(provider_id: str) -> ConnectedWorker | None:
    async with _workers_lock:
        worker = _get_live_worker_unlocked(provider_id)
        if worker is None:
            connected_workers.pop(provider_id, None)
        return worker


def get_connected_workers() -> dict[str, dict]:
    """Get info about all connected workers."""
    workers: dict[str, dict] = {}
    for provider_id in list(connected_workers.keys()):
        worker = _get_live_worker_unlocked(provider_id)
        if worker:
            workers[provider_id] = worker.to_dict()
    return workers


def is_worker_connected(provider_id: str) -> bool:
    """Check if a worker is connected for this provider."""
    return _get_live_worker_unlocked(provider_id) is not None


async def dispatch_job_to_worker(provider_id: str, job_data: dict, timeout: float) -> dict:
    """Send a job to a connected external worker and await its terminal result."""
    worker = await _get_live_worker(provider_id)
    if not worker:
        raise ProviderCallError(
            f"No external worker connected for provider {provider_id}",
            provider_id=provider_id,
            is_retryable=True,
        )

    job_id = job_data.get("id")
    if not job_id:
        raise ValueError("job_data.id is required")

    loop = asyncio.get_running_loop()
    future = loop.create_future()
    async with _futures_lock:
        pending_job_futures[job_id] = future

    try:
        await worker.ws.send_json({
            "type": "job",
            "data": job_data,
        })
        worker.current_job = job_id
    except Exception as exc:
        async with _futures_lock:
            pending_job_futures.pop(job_id, None)
        raise ProviderCallError(
            f"Failed to dispatch job to external worker: {exc}",
            provider_id=provider_id,
            is_retryable=True,
        ) from exc

    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError as exc:
        async with _futures_lock:
            pending_job_futures.pop(job_id, None)
        raise exc


async def request_worker_job_cancel(provider_id: str, job_id: str) -> bool:
    """Request cancellation from a connected external worker."""
    worker = await _get_live_worker(provider_id)
    if not worker:
        return False

    try:
        await worker.ws.send_json({
            "type": "cancel_job",
            "job_id": job_id,
        })
        return True
    except Exception as exc:
        logger.warning("cancel_send_failed", job_id=job_id, provider_id=provider_id, error=str(exc))
        return False


# ============================================================================
# WebSocket Endpoint
# ============================================================================

@router.websocket("/ws/worker/{provider_id}")
async def worker_websocket(
    websocket: WebSocket,
    provider_id: str,
    token: str = Query(..., description="Provider auth token")
):
    """
    WebSocket endpoint for external workers to connect.
    
    Workers should connect with their provider_id and auth token.
    Once connected, they will receive jobs and send results.
    """
    # Import here to avoid circular imports
    
    # Authenticate
    try:
        async with get_session_context() as session:
            provider_service = get_provider_service(session)
            provider = await provider_service.get_provider(provider_id)
            
            # Verify token matches provider's configured token
            expected_token = provider.config.get("worker_token") if provider.config else None
            if not expected_token or token != expected_token:
                await websocket.close(code=4002, reason="Invalid token")
                return
    except NotFoundError:
        await websocket.close(code=4001, reason="Provider not found")
        return
    
    # Accept connection
    await websocket.accept()
    
    # Register worker
    worker = ConnectedWorker(websocket, provider_id)
    async with _workers_lock:
        connected_workers[provider_id] = worker
    
    logger.info("worker_connected", provider_id=provider_id)
    
    # Send welcome message
    await websocket.send_json({
        "type": "connected",
        "provider_id": provider_id,
        "message": "Connected to ComfyUI backend"
    })
    
    # Push pending downloads immediately on connect
    try:
        async with get_session_context() as session:
            from api.deps import get_model_service_v2
            service = get_model_service_v2(session)
            pending = service.get_pending_downloads(provider_id)
            if pending:
                await websocket.send_json({
                    "type": "pending_models",
                    "models": pending
                })
                logger.info("pending_downloads_pushed", count=len(pending), provider_id=provider_id)
    except Exception as exc:
        logger.warning("pending_models_push_failed", provider_id=provider_id, error=str(exc))
    
    try:
        # Main message loop
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            
            if msg_type == "heartbeat":
                worker.last_heartbeat = datetime.now(timezone.utc)
                await websocket.send_json({"type": "heartbeat_ack"})
            
            elif msg_type == "job_started":
                job_id = data.get("job_id")
                worker.current_job = job_id
                logger.info("job_started", job_id=job_id)
                async with get_session_context() as session:
                    from core.entities import JobStatus
                    job_service = get_job_service(session)
                    await job_service.update_job(job_id, status=JobStatus.CONNECTED, message="Connected to external worker...")
            
            elif msg_type == "job_progress":
                payload = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
                job_id = data.get("job_id") or payload.get("job_id") or payload.get("id")
                if job_id:
                    updates = {}

                    # TaskEvent-shaped payloads (canonical): {"event": "progress", "value": 0..1}
                    if payload.get("event") == "progress" and payload.get("value") is not None:
                        val = payload["value"]
                        percent = int(val * 100) if val <= 1 else int(val)
                        updates["progress"] = percent
                        updates["overall_progress"] = percent
                    else:
                        # Legacy ad-hoc fields: raw progress / overall_progress
                        if "status" in payload:
                            try:
                                updates["status"] = JobStatus(payload["status"])
                            except ValueError as exc:
                                logger.debug("unknown_job_status", status=payload.get("status"), error=str(exc))
                        if "progress" in payload:
                            updates["progress"] = payload["progress"]
                        if "overall_progress" in payload:
                            updates["overall_progress"] = payload["overall_progress"]
                        elif "progress" in payload:
                            updates["overall_progress"] = payload["progress"]
                    if "message" in payload:
                        updates["message"] = payload["message"]

                    if updates:
                        async with get_session_context() as session:

                            job_service = get_job_service(session)
                            await job_service.update_job(job_id, **updates)
            
            elif msg_type == "job_completed":
                job_id = data.get("job_id")
                result = data.get("result", {})
                try:
                    outputs = normalize_external_outputs(result.get("outputs", []))
                except ValueError as exc:
                    async with get_session_context() as session:
                        from core.entities import JobStatus

                        job_service = get_job_service(session)
                        await job_service.update_job(
                            job_id,
                            status=JobStatus.FAILED,
                            error=str(exc)
                        )

                    worker.current_job = None
                    logger.error("invalid_completed_payload", job_id=job_id, error=str(exc))
                    continue
                
                try:
                    async with get_session_context() as session:
                        job_service = get_job_service(session)
                        await finalize_persisted_job_outputs(
                            job_service=job_service,
                            job_id=job_id,
                            outputs=outputs,
                            provider_id=provider_id,
                        )
                finally:
                    async with _futures_lock:
                        future = pending_job_futures.pop(job_id, None)
                    if future and not future.done():
                        future.set_result({
                            "__handled_by_external_worker": True,
                            "outputs": outputs,
                        })
                    worker.current_job = None
                    worker.jobs_completed += 1
                    logger.info("job_post_processing", job_id=job_id)

            elif msg_type == "job_failed":
                job_id = data.get("job_id")
                error = data.get("error", "Unknown error")
                
                try:
                    async with get_session_context() as session:
                        from core.entities import JobStatus
                        job_service = get_job_service(session)
                        await job_service.update_job(
                            job_id,
                            status=JobStatus.FAILED,
                            error=error
                        )
                finally:
                    async with _futures_lock:
                        future = pending_job_futures.pop(job_id, None)
                    if future and not future.done():
                        future.set_exception(
                            ProviderCallError(
                                error,
                                provider_id=provider_id,
                                is_retryable=False,
                            )
                        )
                    worker.current_job = None
                    logger.error("job_failed", job_id=job_id, error=error)
            
            elif msg_type == "get_pending_models":
                # Return models that need to be synced
                async with get_session_context() as session:
                    from api.deps import get_model_service_v2
                    service = get_model_service_v2(session)
                    pending = service.get_pending_downloads(provider_id)
                    await websocket.send_json({
                        "type": "pending_models",
                        "models": pending
                    })
    
    except WebSocketDisconnect:
        logger.info("worker_disconnected", provider_id=provider_id)
    except Exception as e:
        logger.error("worker_error", provider_id=provider_id, error=str(e))
    finally:
        # Cleanup
        async with _futures_lock:
            future = pending_job_futures.pop(worker.current_job, None)
        if future and not future.done():
            future.set_exception(
                ProviderCallError(
                    f"External worker {provider_id} disconnected during job execution",
                    provider_id=provider_id,
                    is_retryable=True,
                )
            )
        async with _workers_lock:
            if connected_workers.get(provider_id) is worker:
                del connected_workers[provider_id]


# ============================================================================
# HTTP Endpoints for Worker Status
# ============================================================================

@router.get("/api/workers/connected")
async def list_connected_workers():
    """List all connected external workers."""
    return {
        "workers": get_connected_workers(),
        "count": len(connected_workers)
    }


@router.get("/api/workers/{provider_id}/status")
async def get_worker_status(provider_id: str):
    """Get status of a specific worker."""
    worker = await _get_live_worker(provider_id)
    if worker is None:
        return {"connected": False}

    return {
        "connected": True,
        **worker.to_dict()
    }
