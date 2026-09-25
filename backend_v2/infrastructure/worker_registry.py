"""Connected-worker registry.

Shared state and operations for tracking external (WebSocket) worker connections.
Both the worker-ws endpoint and runtime services import from here so that no
service reaches into ``api.routes`` (which would invert the dependency direction).
"""

import asyncio
from datetime import datetime, timezone

from fastapi import WebSocket

from infrastructure.logging import get_logger
from services.provider_client import ProviderCallError

logger = get_logger("worker_registry")

WORKER_HEARTBEAT_TIMEOUT_SECONDS = 90

connected_workers: dict[str, "ConnectedWorker"] = {}  # provider_id -> worker
pending_job_futures: dict[str, asyncio.Future] = {}
_workers_lock = asyncio.Lock()
_futures_lock = asyncio.Lock()


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


async def register_worker(provider_id: str, ws: WebSocket) -> ConnectedWorker:
    """Register a freshly-connected worker, returning the handle."""
    worker = ConnectedWorker(ws, provider_id)
    async with _workers_lock:
        connected_workers[provider_id] = worker
    return worker


async def unregister_worker(provider_id: str, worker: ConnectedWorker | None = None) -> None:
    """Remove a worker and fail any dispatch still waiting on it."""
    async with _workers_lock:
        if worker is not None and connected_workers.get(provider_id) is not worker:
            return
        connected_workers.pop(provider_id, None)
        current_job = worker.current_job if worker is not None else None
        if worker is not None:
            worker.current_job = None
    if current_job:
        await resolve_job_future(
            current_job,
            error=ProviderCallError(
                f"Worker {provider_id} disconnected before completing the job",
                provider_id=provider_id,
                is_retryable=True,
            ),
        )


async def touch_heartbeat(worker: ConnectedWorker) -> None:
    worker.last_heartbeat = datetime.now(timezone.utc)


async def track_job_future(job_id: str, future: asyncio.Future) -> None:
    async with _futures_lock:
        pending_job_futures[job_id] = future


async def resolve_job_future(job_id: str, result: dict | None = None, error: Exception | None = None) -> None:
    async with _futures_lock:
        future = pending_job_futures.pop(job_id, None)
    if future and not future.done():
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(result)


async def forget_job_future(job_id: str) -> None:
    """Remove a tracked future without resolving it (dispatch cancelled/timed out)."""
    async with _futures_lock:
        pending_job_futures.pop(job_id, None)


async def dispatch_job_to_worker(provider_id: str, job_data: dict, timeout: float) -> dict:
    """Send a job to a connected external worker and await its terminal result."""
    worker = await _get_live_worker(provider_id)
    if not worker:
        raise ProviderCallError(
            f"No external worker connected for provider {provider_id}",
            provider_id=provider_id,
            is_retryable=True,
        )

    if worker.current_job:
        raise ProviderCallError(
            f"Worker {provider_id} is busy with job {worker.current_job}",
            provider_id=provider_id,
            is_retryable=True,
        )

    job_id = job_data.get("id")
    if not job_id:
        raise ValueError("job_data.id is required")

    loop = asyncio.get_running_loop()
    future = loop.create_future()
    await track_job_future(job_id, future)

    try:
        await worker.ws.send_json({
            "type": "job",
            "data": job_data,
        })
        worker.current_job = job_id
    except Exception as exc:
        await forget_job_future(job_id)
        raise ProviderCallError(
            f"Failed to dispatch job to external worker: {exc}",
            provider_id=provider_id,
            is_retryable=True,
        ) from exc

    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError as exc:
        await forget_job_future(job_id)
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
