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
from core.exceptions import NotFoundError
from infrastructure.background_tasks import start_background_task

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


def get_connected_workers() -> Dict[str, dict]:
    """Get info about all connected workers."""
    return {pid: w.to_dict() for pid, w in connected_workers.items()}


def is_worker_connected(provider_id: str) -> bool:
    """Check if a worker is connected for this provider."""
    return provider_id in connected_workers


def _normalize_external_outputs(outputs) -> list:
    """Accept only persisted structured outputs from external workers."""
    if not isinstance(outputs, list):
        raise ValueError("Worker result outputs must be a list")

    normalized = []
    for output in outputs:
        if not isinstance(output, dict):
            raise ValueError("External worker outputs must be structured objects")
        if not output.get("filename"):
            raise ValueError("External worker outputs must include filename")
        if not (output.get("relative_path") or output.get("path") or output.get("subfolder")):
            raise ValueError("External worker outputs must include a persisted path")

        normalized.append({
            "type": output.get("type", "image"),
            "filename": output["filename"],
            "relative_path": output.get("relative_path"),
            "subfolder": output.get("subfolder", ""),
            "path": output.get("path"),
            "thumbnail": output.get("thumbnail"),
            "blurhash": output.get("blurhash"),
            "width": output.get("width"),
            "height": output.get("height"),
        })

    return normalized


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
                # Forward progress to main WebSocket for frontend
                from api.routes.websocket import broadcast_to_room
                await broadcast_to_room("job", "job.progress", data.get("data", {}))
            
            elif msg_type == "job_completed":
                job_id = data.get("job_id")
                result = data.get("result", {})
                try:
                    outputs = _normalize_external_outputs(result.get("outputs", []))
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
                
                # Update job in database to POST_PROCESSING first
                async with get_session_context() as session:
                    from services.job_service import JobService
                    from core.entities import JobStatus
                    job_service = JobService(session)
                    await job_service.update_job(
                        job_id,
                        status=JobStatus.POST_PROCESSING,
                        outputs=outputs
                    )
                
                worker.current_job = None
                worker.jobs_completed += 1
                logger.info(f"[Worker WS] Job entering post-processing: {job_id}")
                
                # Broadcast post-processing
                from api.routes.websocket import broadcast_to_room
                await broadcast_to_room("job", "job.post_processing", {
                    "job": {
                        "id": job_id,
                        "provider_id": provider_id,
                        "status": "post_processing",
                        "outputs": outputs
                    }
                })

                # Schedule background task to wait for GalleryIndexer
                async def finalize_job(j_id, outps, p_id):
                    from api.routes.statistics import gallery_indexer
                    import asyncio

                    # Poll for up to 10 seconds (20 * 0.5s)
                    output_refs = [
                        output.get("relative_path") or output.get("filename")
                        for output in outps
                        if isinstance(output, dict) and output.get("filename")
                    ]

                    for _ in range(20):
                        if output_refs and all(gallery_indexer.get_path(ref) for ref in output_refs):
                            break
                        await asyncio.sleep(0.5)

                    try:
                        async with get_session_context() as session:
                            js = JobService(session)
                            await js.update_job(
                                j_id,
                                status=JobStatus.COMPLETED
                            )
                        logger.info(f"[Worker WS] Job completed: {j_id}")
                        await broadcast_to_room("job", "job.completed", {
                            "job": {
                                "id": j_id,
                                "provider_id": p_id,
                                "status": "completed",
                                "outputs": outps
                            }
                        })
                    except Exception as e:
                        logger.error(f"[Worker WS] Finalize failed for {j_id}: {e}")

                start_background_task(
                    finalize_job(job_id, outputs, provider_id),
                    task_name=f"worker_finalize_job:{job_id}",
                )
            
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
