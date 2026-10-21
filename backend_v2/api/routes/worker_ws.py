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

The message types and their payload shapes are declared once, in
`infrastructure.worker_registry` (the `worker protocol` section). This module
consumes the inbound models and builds its outbound frames from the outbound
models, so both halves of the socket read from a single contract.
"""

import asyncio
import hmac
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlmodel import select

from api.deps import (
    get_job_service,
    get_logger,
    get_model_service_v2,
    get_provider_service,
    get_session_context,
)
from core.entities import Job, JobStatus
from core.exceptions import NotFoundError
from core.progress import coerce_worker_percent
from infrastructure.worker_registry import (  # noqa: F401
    dispatch_job_to_worker,
    forget_job_future,
    is_worker_connected,
    register_worker,
    request_worker_job_cancel,
    resolve_job_future,
    touch_heartbeat,
    track_job_future,
    unregister_worker,
)
from infrastructure.worker_registry import (
    ConnectedMessage,
    GetPendingModelsMessage,
    HeartbeatAckMessage,
    HeartbeatMessage,
    JobCompletedMessage,
    JobFailedMessage,
    JobProgressMessage,
    JobStartedMessage,
    PendingModelsMessage,
    ProtocolErrorMessage,
    parse_worker_message,
)
from services.job_processing import normalize_external_outputs
from services.provider_client import ProviderCallError

logger = get_logger("worker_ws")

router = APIRouter(tags=["worker-ws"])


def _assigned_provider_id(job_id: str) -> str | None:
    """The provider a job is assigned to, or `None` if the job does not exist.

    BLOCKING. Reads one column, not the row: the old form did
    `session.get(Job, job_id)`, which loaded the whole `Job` — `workflow` and
    `metadata_` jsonb included — to compare one string field, and did it on the
    event loop for **every inbound frame** including every progress tick of a
    live generation. A worker streaming progress for a 60-second image was doing
    a full-row SELECT per tick on the loop that every other request needed.
    """
    from api.deps import get_session_sync

    session = get_session_sync()
    try:
        return session.exec(
            select(Job.provider_id).where(Job.id == job_id)
        ).first()
    finally:
        session.close()


async def _worker_owns_job(job_id: str | None, provider_id: str) -> bool:
    if not job_id:
        return False
    assigned = await asyncio.to_thread(_assigned_provider_id, job_id)
    if assigned is None:
        return False
    # A job with no provider assigned must NOT be claimable by any worker that
    # happens to be connected: provider_id in {None, provider_id} let any worker
    # report progress/completion for a job it was never given.
    return assigned == provider_id

def _coerce_percent(value, value_unit: str | None = None) -> int:
    """Normalise a worker-reported progress value to a 0..100 integer.

    Delegates to `core.progress.coerce_worker_percent`. This used to keep its own
    copy of the `0 <= value <= 1 means a fraction` heuristic while
    `services/provider_client._ImageReducer` had already been converted to the
    `value_unit` field the current worker contract carries — so a canonical event
    carrying `value == 1` was recorded as 100% here and as 1% there. Two halves
    of one socket, one number, two answers. The rule now lives in one place.
    """
    return coerce_worker_percent(value, value_unit)


# Re-exported from infrastructure.worker_registry so callers (including tests)
# that historically imported these from the API route keep working.
# New code should import directly from infrastructure.worker_registry.


# ============================================================================
# Inbound handlers — one per declared message type
# ============================================================================

Handler = Callable[[WebSocket, Any, str, BaseModel], Awaitable[None]]


async def _send_not_assigned(websocket: WebSocket) -> None:
    await websocket.send_json(ProtocolErrorMessage(message="job is not assigned to this worker").model_dump())


async def _fetch_pending_models(provider_id: str) -> list:
    """Off the loop for the same reason as `_worker_owns_job`.

    This one is on a handshake rather than a per-frame path, but it is a
    multi-table read of every pending download for a provider, and a worker
    reconnecting during a burst of downloads is exactly when several sockets are
    doing this at once.
    """
    def _load() -> list:
        from api.deps import get_session_sync

        session = get_session_sync()
        try:
            return get_model_service_v2(session).get_pending_downloads(provider_id)
        finally:
            session.close()

    return await asyncio.to_thread(_load)


async def _send_pending_models(websocket: WebSocket, models: list) -> None:
    await websocket.send_json(PendingModelsMessage(models=models).model_dump())


async def _handle_heartbeat(websocket: WebSocket, worker, provider_id: str, message: HeartbeatMessage) -> None:
    await touch_heartbeat(worker)
    await websocket.send_json(HeartbeatAckMessage().model_dump())


async def _handle_job_started(websocket: WebSocket, worker, provider_id: str, message: JobStartedMessage) -> None:
    job_id = message.job_id
    if not await _worker_owns_job(job_id, provider_id) or (worker.current_job and worker.current_job != job_id):
        await _send_not_assigned(websocket)
        return
    worker.current_job = job_id
    logger.info("job_started", job_id=job_id)
    async with get_session_context() as session:
        job_service = get_job_service(session)
        await job_service.update_job(job_id, status=JobStatus.CONNECTED, message="Connected to external worker...")


async def _handle_job_progress(websocket: WebSocket, worker, provider_id: str, message: JobProgressMessage) -> None:
    job_id = message.job_id
    if not await _worker_owns_job(job_id, provider_id) or (worker.current_job is not None and worker.current_job != job_id):
        await _send_not_assigned(websocket)
        return
    if worker.current_job is None:
        worker.current_job = job_id
    # `_worker_owns_job` is False for a missing job_id, so the guard above has
    # already established that there is one.
    payload = message.data
    updates = {}

    # TaskEvent-shaped payloads (canonical): {"event": "progress", "value": percent 0..100}
    if payload.get("event") == "progress" and payload.get("value") is not None:
        percent = _coerce_percent(payload["value"], payload.get("value_unit"))
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


async def _handle_job_completed(websocket: WebSocket, worker, provider_id: str, message: JobCompletedMessage) -> None:
    job_id = message.job_id
    if not await _worker_owns_job(job_id, provider_id) or (worker.current_job is not None and worker.current_job != job_id):
        await _send_not_assigned(websocket)
        return
    if worker.current_job is None:
        worker.current_job = job_id
    result = message.result
    async with get_session_context() as session:
        job_service = get_job_service(session)
        job = await job_service.get_job(job_id)
        allow_text = getattr(job, "task_type", None) == "llm"
    try:
        outputs = normalize_external_outputs(result.get("outputs", []), allow_text=allow_text)
    except ValueError as exc:
        async with get_session_context() as session:
            job_service = get_job_service(session)
            await job_service.update_job(
                job_id,
                status=JobStatus.FAILED,
                error=str(exc)
            )

        worker.current_job = None
        logger.error("invalid_completed_payload", job_id=job_id, error=str(exc))
        return

    try:
        async with get_session_context() as session:
            job_service = get_job_service(session)
            job = await job_service.get_job(job_id)
            # Imported here, not at module scope: the job-processing tests patch
            # `services.job_processing.finalize_successful_job`, and only a
            # call-time import sees the patch.
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
        logger.error("job_finalization_failed", job_id=job_id, error=str(finalize_exc), exc_info=True)
        worker.current_job = None
        try:
            async with get_session_context() as session:
                job_service = get_job_service(session)
                await job_service.update_job(
                    job_id,
                    status=JobStatus.FAILED,
                    # A stable code, not the exception text. `jobs.error` is
                    # returned by `GET /api/jobs/{id}` and embedded in the
                    # `diagnostics` block, so `str(finalize_exc)` put a
                    # SQLAlchemy or httpx traceback — possibly a connection URL —
                    # in front of a browser. The full text is in the log line
                    # above, which is where a traceback belongs.
                    error=(
                        "Generation finished, but saving the result failed. "
                        "The image may still be on disk; see the server log "
                        "(job_finalization_failed) for the cause."
                    ),
                )
        except Exception as mark_exc:
            logger.error("job_finalization_failure_mark_failed", job_id=job_id, error=str(mark_exc))
        return
    else:
        await resolve_job_future(job_id, result={
            "__handled_by_external_worker": True,
            "outputs": outputs,
        })
        worker.current_job = None
        worker.jobs_completed += 1
        logger.info("job_post_processing", job_id=job_id)


async def _handle_job_failed(websocket: WebSocket, worker, provider_id: str, message: JobFailedMessage) -> None:
    job_id = message.job_id
    if not await _worker_owns_job(job_id, provider_id) or (worker.current_job is not None and worker.current_job != job_id):
        await _send_not_assigned(websocket)
        return
    if worker.current_job is None:
        worker.current_job = job_id
    error = message.error

    try:
        async with get_session_context() as session:
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


async def _handle_get_pending_models(websocket: WebSocket, worker, provider_id: str, message: GetPendingModelsMessage) -> None:
    # Return models that need to be synced
    await _send_pending_models(websocket, await _fetch_pending_models(provider_id))


# The dispatch table. Keyed by the declared model class, so it cannot name a
# `type` the contract does not declare, and a declared type with no entry here
# would fall through the loop unhandled. tests/test_worker_ws.py asserts the
# two sets are identical so neither half can drift.
INBOUND_HANDLERS: dict[type[BaseModel], Handler] = {
    HeartbeatMessage: _handle_heartbeat,
    JobStartedMessage: _handle_job_started,
    JobProgressMessage: _handle_job_progress,
    JobCompletedMessage: _handle_job_completed,
    JobFailedMessage: _handle_job_failed,
    GetPendingModelsMessage: _handle_get_pending_models,
}


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
            # Constant-time: every other bearer-token gate in the repo
            # (discovery, the provider X-Provider-Token header, remote_agent)
            # uses hmac.compare_digest, and a `!=` here is a timing oracle on a
            # credential that is now mintable through the API.
            if not expected_token or not hmac.compare_digest(token, expected_token):
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
    await websocket.send_json(
        ConnectedMessage(
            provider_id=provider_id,
            message="Connected to ComfyUI backend",
        ).model_dump()
    )
    
    # Push pending downloads immediately on connect. Only when there are any:
    # the frame is the same one `get_pending_models` replies with, but a
    # freshly-connected worker with an empty queue never received it.
    try:
        pending = await _fetch_pending_models(provider_id)
        if pending:
            await _send_pending_models(websocket, pending)
            logger.info("pending_downloads_pushed", count=len(pending), provider_id=provider_id)
    except Exception as exc:
        logger.warning("pending_models_push_failed", provider_id=provider_id, error=str(exc))
    
    try:
        # Main message loop
        while True:
            message = parse_worker_message(await websocket.receive_json())
            if message is None:
                # Not a frame the protocol declares (or one that does not
                # validate). The old `if/elif` chain fell through for an
                # unrecognised `type`; keep reading.
                continue
            handler = INBOUND_HANDLERS.get(type(message))
            if handler is None:
                continue
            await handler(websocket, worker, provider_id, message)
    
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
#
# `GET /api/workers/connected` and `GET /api/workers/{provider_id}/status`
# are GONE (2026-10-21). Nothing consumed them: the provider list
# (`GET /api/v2/providers/`) is where the UI reads provider health, and a
# connected external worker is visible there through its provider's runtime
# state.
