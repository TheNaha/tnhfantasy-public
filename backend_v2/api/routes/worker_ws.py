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


from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from api.deps import (
    get_job_service,
    get_logger,
    get_provider_service,
    get_session_context,
)
from core.entities import Job, JobStatus
from core.exceptions import NotFoundError
from infrastructure.worker_registry import (  # noqa: F401
    _get_live_worker,
    dispatch_job_to_worker,
    forget_job_future,
    get_connected_workers,
    is_worker_connected,
    register_worker,
    request_worker_job_cancel,
    resolve_job_future,
    touch_heartbeat,
    track_job_future,
    unregister_worker,
)
from services.job_processing import normalize_external_outputs
from services.provider_client import ProviderCallError

logger = get_logger("worker_ws")

router = APIRouter(tags=["worker-ws"])


async def _worker_owns_job(job_id: str | None, provider_id: str) -> bool:
    if not job_id:
        return False
    async with get_session_context() as session:
        job = session.get(Job, job_id)
    if job is None:
        return False
    # A job with no provider assigned must NOT be claimable by any worker that
    # happens to be connected: provider_id in {None, provider_id} let any worker
    # report progress/completion for a job it was never given.
    return job.provider_id == provider_id

def _coerce_percent(value) -> int:
    """Normalise a worker-reported progress value to a 0..100 integer.

    Canonical worker events are percent 0..100, but legacy containers still
    emit 0..1 fractions.  The result is always clamped into 0..100 because
    migration 047 added `CHECK (progress BETWEEN 0 AND 100)` on jobs — writing
    an out-of-range value raised IntegrityError inside the session context,
    which propagated to the socket-level handler and dropped the worker,
    leaving the job non-terminal.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if number != number:  # NaN
        return 0
    percent = number * 100 if 0 <= number <= 1 else number
    return max(0, min(100, int(percent)))


# Re-exported from infrastructure.worker_registry so callers (including tests)
# that historically imported these from the API route keep working.
# New code should import directly from infrastructure.worker_registry.


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
    worker = await register_worker(provider_id, websocket)

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
                await touch_heartbeat(worker)
                await websocket.send_json({"type": "heartbeat_ack"})
            
            elif msg_type == "job_started":
                job_id = data.get("job_id")
                if not await _worker_owns_job(job_id, provider_id) or (worker.current_job and worker.current_job != job_id):
                    await websocket.send_json({"type": "error", "message": "job is not assigned to this worker"})
                    continue
                worker.current_job = job_id
                logger.info("job_started", job_id=job_id)
                async with get_session_context() as session:
                    job_service = get_job_service(session)
                    await job_service.update_job(job_id, status=JobStatus.CONNECTED, message="Connected to external worker...")
            
            elif msg_type == "job_progress":
                payload = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
                job_id = data.get("job_id") or payload.get("job_id") or payload.get("id")
                if not await _worker_owns_job(job_id, provider_id) or (worker.current_job is not None and worker.current_job != job_id):
                    await websocket.send_json({"type": "error", "message": "job is not assigned to this worker"})
                    continue
                if worker.current_job is None:
                    worker.current_job = job_id
                if job_id:
                    updates = {}

                    # TaskEvent-shaped payloads (canonical): {"event": "progress", "value": percent 0..100}
                    if payload.get("event") == "progress" and payload.get("value") is not None:
                        percent = _coerce_percent(payload["value"])
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
                            updates["progress"] = _coerce_percent(payload["progress"])
                        if "overall_progress" in payload:
                            updates["overall_progress"] = _coerce_percent(payload["overall_progress"])
                        elif "progress" in payload:
                            updates["overall_progress"] = _coerce_percent(payload["progress"])
                    if "message" in payload:
                        updates["message"] = payload["message"]

                    if updates:
                        async with get_session_context() as session:

                            job_service = get_job_service(session)
                            await job_service.update_job(job_id, **updates)
            
            elif msg_type == "job_completed":
                job_id = data.get("job_id")
                if not await _worker_owns_job(job_id, provider_id) or (worker.current_job is not None and worker.current_job != job_id):
                    await websocket.send_json({"type": "error", "message": "job is not assigned to this worker"})
                    continue
                if worker.current_job is None:
                    worker.current_job = job_id
                result = data.get("result", {})
                async with get_session_context() as session:
                    job_service = get_job_service(session)
                    job = await job_service.get_job(job_id)
                    allow_text = getattr(job, "task_type", None) == "llm"
                try:
                    outputs = normalize_external_outputs(result.get("outputs", []), allow_text=allow_text)
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
                        job = await job_service.get_job(job_id)
                        from services.job_processing import finalize_successful_job

                        await finalize_successful_job(
                            job=job,
                            job_id=job_id,
                            job_service=job_service,
                            load_balancer=None,
                            provider_id=provider_id,
                            final_result=result,
                            process_image_background_fn=None,
                        )
                except Exception as finalize_exc:
                    # A bare `finally` here used to signal success even when
                    # finalization failed, then let the exception reach the
                    # socket handler — the job row stayed non-terminal while the
                    # caller believed it had succeeded.  Mark it FAILED so the
                    # row reaches a terminal state, and only resolve the future
                    # with a result on the success path.
                    logger.error("job_finalization_failed", job_id=job_id, error=str(finalize_exc))
                    worker.current_job = None
                    try:
                        async with get_session_context() as session:
                            job_service = get_job_service(session)
                            await job_service.update_job(
                                job_id,
                                status=JobStatus.FAILED,
                                error=f"FAILURE_FINALIZATION: {finalize_exc}",
                            )
                    except Exception as mark_exc:
                        logger.error("job_finalization_failure_mark_failed", job_id=job_id, error=str(mark_exc))
                    continue
                else:
                    await resolve_job_future(job_id, result={
                        "__handled_by_external_worker": True,
                        "outputs": outputs,
                    })
                    worker.current_job = None
                    worker.jobs_completed += 1
                    logger.info("job_post_processing", job_id=job_id)

            elif msg_type == "job_failed":
                job_id = data.get("job_id")
                if not await _worker_owns_job(job_id, provider_id) or (worker.current_job is not None and worker.current_job != job_id):
                    await websocket.send_json({"type": "error", "message": "job is not assigned to this worker"})
                    continue
                if worker.current_job is None:
                    worker.current_job = job_id
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
                    await resolve_job_future(
                        job_id,
                        error=ProviderCallError(error, provider_id=provider_id, is_retryable=False),
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
        await resolve_job_future(
            worker.current_job,
            error=ProviderCallError(
                f"External worker {provider_id} disconnected during job execution",
                provider_id=provider_id,
                is_retryable=True,
            ),
        )
        await unregister_worker(provider_id, worker)


# ============================================================================
# HTTP Endpoints for Worker Status
# ============================================================================

@router.get("/api/workers/connected")
async def list_connected_workers():
    """List all connected external workers."""
    workers = get_connected_workers()
    return {
        "workers": workers,
        "count": len(workers),
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
