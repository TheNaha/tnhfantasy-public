"""Connected-worker registry.

Shared state and operations for tracking external (WebSocket) worker connections.
Both the worker-ws endpoint and runtime services import from here so that no
service reaches into ``api.routes`` (which would invert the dependency direction).

This module also owns the ``/ws/worker/{provider_id}`` wire contract: every
message type and its payload shape is declared once, in the
``worker protocol`` section below, and both halves of the socket import it —
``api.routes.worker_ws`` dispatches on the parsed inbound models, and the
senders in this file build outbound frames from the outbound models. See
``INBOUND_MESSAGES`` for the registry itself.
"""

import asyncio
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import WebSocket
from pydantic import BaseModel, Field, TypeAdapter, ValidationError, model_validator

from infrastructure.logging import get_logger
from services.provider_client import ProviderCallError

logger = get_logger("worker_registry")

WORKER_HEARTBEAT_TIMEOUT_SECONDS = 90

connected_workers: dict[str, "ConnectedWorker"] = {}  # provider_id -> worker
pending_job_futures: dict[str, asyncio.Future] = {}
_workers_lock = asyncio.Lock()
_futures_lock = asyncio.Lock()


# ============================================================================
# Worker protocol
# ============================================================================
#
# Every frame that crosses /ws/worker/{provider_id} in either direction is
# declared here, once. The two halves of the socket used to have to be read
# together to see the contract: the handler branched on `data.get("type")` and
# the senders built dicts inline, so a type added on one side was invisible on
# the other. Now:
#
#   * `msg_type` and its payload fields come from the model declarations below;
#   * the handler parses frames into these models and dispatches on the model
#     class (see `INBOUND_HANDLERS` in api/routes/worker_ws.py);
#   * every sender builds its frame from the outbound models.
#
# `tests/test_worker_ws.py` asserts the inbound model registry and the handler
# dispatch table hold the same set of types in both directions, so a type cannot
# be declared on one side only.
#
# The wire format is unchanged. `scripts/external_worker_client.py` is a working
# reference client for exactly these frames and still passes unmodified.
#
# `job_id` is declared optional on the job_* inbound types on purpose: a frame
# that omits it (or carries a bogus one) must still get the standard
# "job is not assigned to this worker" error rather than failing validation,
# because that ownership check is the thing rejecting it.

# --- Inbound: worker -> backend -------------------------------------------


class HeartbeatMessage(BaseModel):
    type: Literal["heartbeat"] = "heartbeat"


class JobStartedMessage(BaseModel):
    type: Literal["job_started"] = "job_started"
    job_id: str | None = None


class JobProgressMessage(BaseModel):
    """Progress for a running job.

    `data` carries the progress payload and has two accepted shapes, both of
    which must keep working:

    * canonical TaskEvent — ``{"event": "progress", "value": 0..100}``
    * legacy ad-hoc fields — ``{"progress": .., "overall_progress": ..,
      "status": .., "message": ..}``

    `job_id` has historically been sent both at the top level and inside `data`
    (as `job_id`, and as `id` by some older containers), so it is resolved from
    all three here rather than at each consumer.
    """

    type: Literal["job_progress"] = "job_progress"
    job_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _resolve_job_id(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        # A non-dict `data` has always been treated as an empty payload.
        payload = raw.get("data")
        if not isinstance(payload, dict):
            return {**raw, "data": {}}
        if not raw.get("job_id"):
            resolved = payload.get("job_id") or payload.get("id")
            if resolved:
                return {**raw, "job_id": resolved}
        return raw


class JobCompletedMessage(BaseModel):
    type: Literal["job_completed"] = "job_completed"
    job_id: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)


class JobFailedMessage(BaseModel):
    type: Literal["job_failed"] = "job_failed"
    job_id: str | None = None
    error: str = "Unknown error"


class GetPendingModelsMessage(BaseModel):
    type: Literal["get_pending_models"] = "get_pending_models"


InboundMessage = Annotated[
    HeartbeatMessage
    | JobStartedMessage
    | JobProgressMessage
    | JobCompletedMessage
    | JobFailedMessage
    | GetPendingModelsMessage,
    Field(discriminator="type"),
]

# Keyed by the Literal default of each model's `type` field, so the registry
# cannot disagree with the model it indexes.
INBOUND_MESSAGES: dict[str, type[BaseModel]] = {
    m.model_fields["type"].default: m
    for m in (
        HeartbeatMessage,
        JobStartedMessage,
        JobProgressMessage,
        JobCompletedMessage,
        JobFailedMessage,
        GetPendingModelsMessage,
    )
}

_inbound_adapter = TypeAdapter(InboundMessage)


def parse_worker_message(raw: Any) -> InboundMessage | None:
    """Validate one frame received from a worker.

    Returns None — and never raises — for a frame the protocol does not declare
    (missing/blank `type`, an unknown type) or for a declared type whose payload
    does not validate. The socket loop treats None as "ignore and keep reading",
    which is what the old `if/elif` chain did for an unrecognised `type`.
    """
    try:
        return _inbound_adapter.validate_python(raw)
    except ValidationError as exc:
        kind = raw.get("type") if isinstance(raw, dict) else None
        logger.debug("worker_message_rejected", msg_type=kind, error=str(exc))
        return None


# --- Outbound: backend -> worker -------------------------------------------


class ConnectedMessage(BaseModel):
    type: Literal["connected"] = "connected"
    provider_id: str
    message: str


class PendingModelsMessage(BaseModel):
    type: Literal["pending_models"] = "pending_models"
    models: list[Any] = Field(default_factory=list)


class HeartbeatAckMessage(BaseModel):
    type: Literal["heartbeat_ack"] = "heartbeat_ack"


class ProtocolErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    message: str


class JobDispatchMessage(BaseModel):
    type: Literal["job"] = "job"
    data: dict[str, Any]


class CancelJobMessage(BaseModel):
    type: Literal["cancel_job"] = "cancel_job"
    job_id: str


OUTBOUND_MESSAGES: dict[str, type[BaseModel]] = {
    m.model_fields["type"].default: m
    for m in (
        ConnectedMessage,
        PendingModelsMessage,
        HeartbeatAckMessage,
        ProtocolErrorMessage,
        JobDispatchMessage,
        CancelJobMessage,
    )
}

# Every type the socket can carry, either way. Not used for dispatch — the
# handler and the senders are the only dispatchers — but it is the set a new
# message type has to be added to, and it is asserted in the tests.
WORKER_MESSAGE_TYPES: frozenset[str] = frozenset(INBOUND_MESSAGES) | frozenset(OUTBOUND_MESSAGES)


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


async def _claim_worker_slot(worker: ConnectedWorker, job_id: str) -> str | None:
    """Reserve the worker's one job slot. Returns None on success, else the
    job that already holds it.

    The check and the claim have to be ONE critical section. They were not: the
    busy check ran after `_get_live_worker` had already released
    `_workers_lock`, and the assignment ran *after* an `await send_json`. Two
    concurrent dispatches to the same provider therefore both passed the check
    and both dispatched. `unregister_worker` can only fail one `current_job`
    future, so the other dispatch sat on its future until the full timeout
    expired — and the worker was running a job the backend had no handle on.
    """
    async with _workers_lock:
        if worker.current_job:
            return worker.current_job
        worker.current_job = job_id
        return None


async def _release_worker_slot(worker: ConnectedWorker, job_id: str) -> None:
    """Undo `_claim_worker_slot` when the dispatch never reached the worker."""
    async with _workers_lock:
        if worker.current_job == job_id:
            worker.current_job = None


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

    busy_with = await _claim_worker_slot(worker, job_id)
    if busy_with is not None:
        raise ProviderCallError(
            f"Worker {provider_id} is busy with job {busy_with}",
            provider_id=provider_id,
            is_retryable=True,
        )

    loop = asyncio.get_running_loop()
    future = loop.create_future()
    await track_job_future(job_id, future)

    try:
        await worker.ws.send_json(JobDispatchMessage(data=job_data).model_dump())
    except Exception as exc:
        await forget_job_future(job_id)
        await _release_worker_slot(worker, job_id)
        raise ProviderCallError(
            f"Failed to dispatch job to external worker: {exc}",
            provider_id=provider_id,
            is_retryable=True,
        ) from exc

    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError as exc:
        # The slot has to be released here as well as on the send failure above.
        # `worker.current_job` stayed pinned to the timed-out job, so
        # `_claim_worker_slot` answered `busy_with` for every later dispatch —
        # each one a retryable ProviderCallError, so a single-worker provider
        # exhausted the job's attempts and the only things that could clear it
        # were a worker reconnect or the 90s heartbeat-stale eviction.
        await forget_job_future(job_id)
        await _release_worker_slot(worker, job_id)
        raise exc


async def request_worker_job_cancel(provider_id: str, job_id: str) -> bool:
    """Request cancellation from a connected external worker."""
    worker = await _get_live_worker(provider_id)
    if not worker:
        return False

    try:
        await worker.ws.send_json(CancelJobMessage(job_id=job_id).model_dump())
        return True
    except Exception as exc:
        logger.warning("cancel_send_failed", job_id=job_id, provider_id=provider_id, error=str(exc))
        return False
