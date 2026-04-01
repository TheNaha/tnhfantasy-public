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
import logging
from typing import Dict, Optional
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from api.deps import get_session_context
from api.job_processing import finalize_persisted_job_outputs, normalize_external_outputs
from core.exceptions import NotFoundError
from api.provider_client import ProviderCallError
from core.entities import JobStatus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["worker-ws"])


# ============================================================================
# Connected Workers Registry
# ============================================================================

class ConnectedWorker:
    """Tracks a connected worker session."""
    def __init__(self, ws: WebSocket, provider_id: str):
        self.ws = ws
        self.provider_id = provider_id
        self.connected_at = datetime.utcnow()
        self.last_heartbeat = datetime.utcnow()
        self.current_job: Optional[str] = None
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
connected_workers: Dict[str, ConnectedWorker] = {}  # provider_id -> worker
pending_job_futures: Dict[str, asyncio.Future] = {}


def get_connected_workers() -> Dict[str, dict]:
    """Get info about all connected workers."""
    return {pid: w.to_dict() for pid, w in connected_workers.items()}


def is_worker_connected(provider_id: str) -> bool:
    """Check if a worker is connected for this provider."""
    return provider_id in connected_workers


async def push_job_to_worker(provider_id: str, job_data: dict) -> bool:
    """Push a job to a connected worker. Returns True if successful."""
    worker = connected_workers.get(provider_id)
    if not worker:
        return False
    
    try:
        await worker.ws.send_json({
            "type": "job",
            "data": job_data
        })
        worker.current_job = job_data.get("id")
        return True
    except Exception as e:
        logger.error(f"[Worker WS] Failed to push job to {provider_id}: {e}")
        return False


async def dispatch_job_to_worker(provider_id: str, job_data: dict, timeout: float) -> dict:
    """Send a job to a connected external worker and await its terminal result."""
    worker = connected_workers.get(provider_id)
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
    pending_job_futures[job_id] = future

    try:
        await worker.ws.send_json({
            "type": "job",
            "data": job_data,
        })
        worker.current_job = job_id
    except Exception as exc:
        pending_job_futures.pop(job_id, None)
        raise ProviderCallError(
            f"Failed to dispatch job to external worker: {exc}",
            provider_id=provider_id,
            is_retryable=True,
        ) from exc

    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError as exc:
        pending_job_futures.pop(job_id, None)
        raise exc


async def request_worker_job_cancel(provider_id: str, job_id: str) -> bool:
    """Request cancellation from a connected external worker."""
    worker = connected_workers.get(provider_id)
    if not worker:
        return False

    try:
        await worker.ws.send_json({
            "type": "cancel_job",
            "job_id": job_id,
        })
        return True
    except Exception as exc:
        logger.warning(f"[Worker WS] Failed to send cancellation for {job_id} to {provider_id}: {exc}")
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
    from services.provider_service import ProviderService
    
    # Authenticate
    try:
        async with get_session_context() as session:
            provider_service = ProviderService(session)
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
    connected_workers[provider_id] = worker
    
    logger.info(f"[Worker WS] Worker connected: {provider_id}")
    
    # Send welcome message
    await websocket.send_json({
        "type": "connected",
        "provider_id": provider_id,
        "message": "Connected to ComfyUI backend"
    })
    
    try:
        # Main message loop
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            
            if msg_type == "heartbeat":
                worker.last_heartbeat = datetime.utcnow()
                await websocket.send_json({"type": "heartbeat_ack"})
            
            elif msg_type == "job_started":
                job_id = data.get("job_id")
                worker.current_job = job_id
                logger.info(f"[Worker WS] Job started: {job_id}")
            
            elif msg_type == "job_progress":
                payload = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
                job_id = data.get("job_id") or payload.get("job_id") or payload.get("id")
                if job_id:
                    updates = {}

                    if "status" in payload:
                        try:
                            updates["status"] = JobStatus(payload["status"])
                        except ValueError:
                            pass
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
                            from services.job_service import JobService

                            job_service = JobService(session)
                            await job_service.update_job(job_id, **updates)
            
            elif msg_type == "job_completed":
                job_id = data.get("job_id")
                result = data.get("result", {})
                try:
                    outputs = normalize_external_outputs(result.get("outputs", []))
                except ValueError as exc:
                    async with get_session_context() as session:
                        from services.job_service import JobService
                        from core.entities import JobStatus

                        job_service = JobService(session)
                        await job_service.update_job(
                            job_id,
                            status=JobStatus.FAILED,
                            error=str(exc)
                        )

                    worker.current_job = None
                    logger.error(f"[Worker WS] Invalid completed payload for {job_id}: {exc}")
                    continue
                
                async with get_session_context() as session:
                    from services.job_service import JobService
                    job_service = JobService(session)
                    await finalize_persisted_job_outputs(
                        job_service=job_service,
                        job_id=job_id,
                        outputs=outputs,
                        provider_id=provider_id,
                    )
                
                future = pending_job_futures.pop(job_id, None)
                if future and not future.done():
                    future.set_result({
                        "__handled_by_external_worker": True,
                        "outputs": outputs,
                    })
                worker.current_job = None
                worker.jobs_completed += 1
                logger.info(f"[Worker WS] Job entering post-processing: {job_id}")

            elif msg_type == "job_failed":
                job_id = data.get("job_id")
                error = data.get("error", "Unknown error")
                
                async with get_session_context() as session:
                    from services.job_service import JobService
                    from core.entities import JobStatus
                    job_service = JobService(session)
                    await job_service.update_job(
                        job_id,
                        status=JobStatus.FAILED,
                        error=error
                    )
                
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
                logger.error(f"[Worker WS] Job failed: {job_id} - {error}")
            
            elif msg_type == "get_pending_models":
                # Return models that need to be synced
                async with get_session_context() as session:
                    from services.model_service_v2 import ModelServiceV2
                    service = ModelServiceV2(session)
                    pending = service.get_pending_downloads(provider_id)
                    await websocket.send_json({
                        "type": "pending_models",
                        "models": pending
                    })
    
    except WebSocketDisconnect:
        logger.info(f"[Worker WS] Worker disconnected: {provider_id}")
    except Exception as e:
        logger.error(f"[Worker WS] Error for {provider_id}: {e}")
    finally:
        # Cleanup
        if worker.current_job:
            future = pending_job_futures.pop(worker.current_job, None)
            if future and not future.done():
                future.set_exception(
                    ProviderCallError(
                        f"External worker {provider_id} disconnected during job execution",
                        provider_id=provider_id,
                        is_retryable=True,
                    )
                )
        if provider_id in connected_workers:
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
    if provider_id not in connected_workers:
        return {"connected": False}
    
    worker = connected_workers[provider_id]
    return {
        "connected": True,
        **worker.to_dict()
    }
