"""
Base In-Process Engine Interface.

Defines the contract for in-process compute providers (Modal, Direct ComfyUI, etc.),
allowing backend_v2 to dispatch inference, stream progress, query models, and retrieve
output files directly without requiring separate container microservices.
"""

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

import base64
import inspect
import logging

import httpx

logger = logging.getLogger(__name__)


#: The OpenAI-style end-of-stream sentinel, compared against the payload.
SSE_DONE = "[DONE]"


def sse_payload(line: str) -> str | None:
    """Payload of one ``data:`` SSE line, or None. Port of
    provider_core.sse.sse_payload: accepts ``data:``, ``data:{..}``,
    ``data:  {..}``, ``data: [DONE]``; keeps the payload tail intact."""
    candidate = line.rstrip("\r\n").lstrip()
    if not candidate.startswith("data:"):
        return None
    return candidate.removeprefix("data:").lstrip()


async def iter_sse_data(lines) -> AsyncIterator[str | None]:
    """Yield each ``data:`` frame's payload from an aiter_lines() source.

    Port of provider_core.sse.iter_sse_data (minus the job-tracker probe):
    a frame is one or more data lines dispatched by a blank line; ``[DONE]``
    flushes any buffered frame then ends the stream; a frame still buffered
    at EOF is flushed rather than dropped (the trailing-newline loss).
    """
    buffer: list[str] = []
    async for raw_line in lines:
        if raw_line.strip():
            one = sse_payload(raw_line)
            if one is None:
                continue
            if one == SSE_DONE:
                if buffer:
                    trailing = "\n".join(buffer)
                    buffer.clear()
                    if trailing.strip():
                        yield trailing
                return
            buffer.append(one)
            continue
        if not buffer:
            continue
        payload = "\n".join(buffer)
        buffer.clear()
        if payload.strip():
            yield payload
    if buffer:
        payload = "\n".join(buffer)
        buffer.clear()
        if payload.strip():
            yield payload


def retryable_for_status(status_code: int, detail: Any = None) -> bool:
    """Mirror provider_core.responses.retryable_for_status.

    4xx is permanent (re-dispatching reproduces the failure on every
    provider for the same money), except 408/429 which invite a retry;
    5xx is transient. A dict detail with an explicit ``retryable`` marker
    wins. Kept here so every engine shares one rule without importing
    provider_core.
    """
    if isinstance(detail, dict) and detail.get("retryable") is not None:
        return bool(detail["retryable"])
    if status_code in (408, 429):
        return True
    return status_code >= 500


def retryable_for_exception(exc: BaseException) -> bool:
    """Mirror provider_core.responses.retryable_for_exception.

    httpx.HTTPStatusError maps via its status; Timeout/Connect errors are
    transient; anything else (parse bugs, programming errors) is permanent.
    """
    marker = getattr(exc, "retryable", None)
    if isinstance(marker, bool):
        return marker
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return retryable_for_status(status)
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return retryable_for_status(status)
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    # Fallback: engine RuntimeErrors embed the upstream status as
    # "HTTP {code}" without a typed status_code (direct/beam/modal list,
    # validate, get-file, download). A 5xx/408/429 there is transient and
    # must not read as permanent clean-sweep material.
    import re

    m = re.search(r"http\s+(\d{3})", str(exc), re.IGNORECASE)
    if m:
        try:
            return retryable_for_status(int(m.group(1)))
        except ValueError:
            pass
    return False


def clamp_timeout(value: Any, default: float = 3600.0) -> float:
    """Coerce an inference timeout to a positive float.

    Mirrors the container clients' ``max(1.0, ...)`` guard: ``asyncio.timeout``
    with ``<= 0`` expires instantly (or raises ValueError), so a garbage or
    zero timeout must never reach it.
    """
    try:
        clamped = float(value if value else default)
    except (TypeError, ValueError):
        return default
    return max(1.0, clamped)


def is_auth_error(exc: BaseException) -> bool:
    """Whether this exception looks like rejected credentials (401/403).

    Auth failures are permanent: re-dispatching to another provider (or the
    same one after failover) reproduces the failure while spending a retry,
    so they must surface with ``retryable: False`` like the container
    clients' marker-less failure.
    """
    if isinstance(exc, EngineAuthError):
        return True
    for holder in (exc, getattr(exc, "response", None)):
        status = getattr(holder, "status_code", None)
        if status in (401, 403):
            return True
    text = f"{type(exc).__name__}: {exc}".lower()
    # NOTE: no bare "401"/"403" substring match — a size, count or port
    # containing those digits (e.g. "4010 bytes", "port 4031") is not an
    # auth rejection. Match word-boundary HTTP statuses and phrases only.
    import re

    if re.search(r"\b401\b|\b403\b", text):
        return True
    return any(
        marker in text
        for marker in (
            "unauthorized", "unauthenticated", "invalid credentials",
            "invalid token", "forbidden", "access denied",
        )
    )


def parse_sse_json(data_str: str) -> dict[str, Any] | None:
    """Parse one SSE data frame into a dict, or None when skippable.

    Non-dict JSON (list/str) and decode failures return None so the caller skips
    the frame instead of raising AttributeError on ``.get``. Catches
    ValueError+TypeError, not just JSONDecodeError, so a malformed UTF-8 frame
    is skipped rather than killing the stream.
    """
    import json

    try:
        data = json.loads(data_str)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def get_file_size_cap() -> int:
    """Ceiling for streamed get-file bodies, mirroring provider_core.

    Override with ``PROVIDER_GET_FILE_MAX_BYTES``. Zero or negative disables
    the cap (same semantics as the container side).
    """
    import os

    default = 512 * 1024 * 1024
    raw = os.getenv("PROVIDER_GET_FILE_MAX_BYTES", "").strip()
    if not raw:
        return default
    try:
        cap = int(raw)
    except (TypeError, ValueError):
        return default
    return cap if cap > 0 else 0


class EngineAuthError(RuntimeError):
    """Upstream rejected our credentials (HTTP 401/403 or equivalent).

    Raised by reconcile-probe methods (list/validate) instead of degrading
    to an empty success: a 401 that reads as "no files, nothing invalid"
    is the clean-sweep regression the container clients fixed by raising
    on non-200 (beam/client.py:493-497, remote_comfy/client.py:479-484).
    Callers that fan out per directory (maintenance scans, reconciliation)
    already catch Exception per directory, so this surfaces in their error
    lists instead of silently passing.
    """

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class FileTooLargeError(ValueError):
    """A provider file exceeds the get-file/streaming ceiling.

    Subclasses ValueError so existing ``except ValueError`` sites keep
    catching it, but carries the byte counts so a future HTTP route can map
    it to 413 (like the containers' ``HTTPException(413)``) instead of the
    500 an unmapped ValueError would produce. Raised for over-cap reads in
    every engine's ``get_file_stream``; job_processing treats it like any
    other fetch failure (skip that artifact, not the job).
    """

    def __init__(self, path: str, size: int | None = None, cap: int | None = None):
        self.path = path
        self.size = size
        self.cap = cap
        detail = f"'{path}'"
        if size is not None and cap is not None:
            detail += f" is {size} bytes; limit is {cap} bytes"
        elif cap is not None:
            detail += f" exceeds the {cap}-byte limit"
        super().__init__(f"File {detail}")


def get_upload_size_cap() -> int:
    """Ceiling for uploaded file bodies, mirroring provider_core.

    The containers enforce ``UPLOAD_MAX_BYTES`` (default 512 MiB, env
    ``PROVIDER_UPLOAD_MAX_BYTES``) on the raw bytes and
    ``UPLOAD_MAX_BYTES_ENCODED`` on the base64 body (models.py:135-142,
    router.py:296-309). Zero or negative disables the cap, same as there.
    """
    import os

    default = 512 * 1024 * 1024
    raw = os.getenv("PROVIDER_UPLOAD_MAX_BYTES", "").strip()
    if not raw:
        return default
    try:
        cap = int(raw)
    except (TypeError, ValueError):
        return default
    return cap if cap > 0 else 0


#: Encoded (base64) counterpart of the upload cap, mirroring
#: provider_core.models.UPLOAD_MAX_BYTES_ENCODED = (n//3)*4 + 4096.
def get_upload_max_bytes_encoded() -> int:
    cap = get_upload_size_cap()
    return (cap // 3) * 4 + 4096 if cap else 0


def encoded_upload_over_cap(encoded_len: int) -> bool:
    """Is a base64 body over the upload cap?

    The one place the encoded-length verdict is made. `get_upload_size_cap`
    answers 0 for *disabled*, so a bare `encoded_len > cap` is true for every
    non-empty body — which is how four engines came to refuse all uploads for
    an operator who set PROVIDER_UPLOAD_MAX_BYTES=0 to turn the cap off.
    """
    cap = get_upload_max_bytes_encoded()
    return bool(cap) and encoded_len > cap


#: Model directories every image engine reconciles, mirroring
#: provider_core.models.MODEL_DIRECTORIES. Kept here (not imported from
#: provider_containers) so the backend never depends on the containers it
#: is deprecating.
MODEL_DIRECTORIES = [
    "models/checkpoints",
    "models/loras",
    "models/vae",
    "models/controlnet",
    "models/unet",
    "models/clip",
    "models/upscale_models",
    "models/embeddings",
    "models/hypernetworks",
    "models/aesthetics",
    "models/poses",
    "models/wildcards",
    "models/ultralytics/bbox",
    "models/ultralytics/seg",
    "models/motion_modules",
    "models/clip_vision",
]

#: Canonical TaskEvent kinds, mirroring
#: provider_core.utils._TASK_EVENT_KINDS. A payload carrying one of these
#: in ``event`` is already translated and must pass through untouched —
#: never be misread as a legacy ``{"status": ...}`` update.
CANONICAL_EVENT_KINDS = frozenset({
    "started", "progress", "delta", "node", "cached_nodes",
    "completed", "failed", "cancelled",
})

#: Events that end a job's stream — used by every engine's fetcher loop to know
#: when to stop listening. Centralised here so a new terminal kind (e.g.
#: ``"timeout"``) updates all three engines at once instead of being silently
#: missed in one of them — the old per-engine tuple drift let a ``cancelled``
#: frame be reported as ``completed`` by beam but correctly as ``cancelled``
#: by modal, because beam_engine omitted ``cancelled`` from its inline set.
TERMINAL_EVENTS = frozenset({"completed", "failed", "cancelled"})

#: Legacy statuses that carry no progress and translate to nothing,
#: mirroring provider_core.utils.comfy_status_to_task_event.
_QUIET_LEGACY_STATUSES = frozenset({"execution_interrupted", "execution_start", "queued"})


def translate_legacy_image_update(update: Any, job_id: str | None) -> dict[str, Any] | None:
    """Translate one legacy ComfyUI ``{"status": ...}`` dict into a canonical event.

    Port of provider_core.utils.comfy_status_to_task_event, returning plain
    dicts instead of TaskEvent models. Canonical ``{"event": ...}`` payloads
    pass through with ``job_id`` filled in; anything without meaningful
    progress returns None.
    """
    if not isinstance(update, dict):
        return None
    event_kind = update.get("event")
    if event_kind in CANONICAL_EVENT_KINDS:
        return {**update, "job_id": job_id}
    status = (update.get("status") or "").lower()
    data = update.get("data") or {}

    if status == "success":
        # Only a terminal success promotes to completed. A progress update
        # carrying image previews must not (parity with
        # provider_core.utils.comfy_status_to_task_event which requires
        # status=="success").
        # ComfyUI returns images as a list of {"data": base64, ...} or
        # {"filename": ..., "subfolder": ..., "type": ...}. The canonical
        # artifact keeps the storage ``type`` as ``image_type`` and marks
        # base64 payloads so the reducer decodes them instead of treating
        # them as already-on-disk files.
        raw_images = update.get("images") or data.get("images") or []
        if isinstance(raw_images, dict):
            raw_images = [raw_images]
        artifacts = []
        for img in raw_images:
            if not isinstance(img, dict):
                continue
            data = img.get("data")
            if isinstance(data, bytes):
                # Modal remotes hand back raw bytes objects; the wire and
                # the reducer only speak base64 text (or filenames).
                data = base64.b64encode(data).decode("utf-8")
            artifact = {
                "type": "image",
                "data": data,
                "filename": img.get("filename"),
                "subfolder": img.get("subfolder", ""),
                "image_type": img.get("type"),
            }
            if img.get("_base64_encoded") or img.get("data"):
                artifact["_base64_encoded"] = True
            artifacts.append(artifact)
        return {"event": "completed", "job_id": job_id, "outputs": artifacts}

    if status == "error":
        # Preserve the app's own retryable marker verbatim (may be None):
        # the reducer coerces a missing marker to non-retryable, which is
        # exactly what the container path produced. modal_app sets True on
        # stall/1006/timeout yields and False on websocket_error.
        return {
            "event": "failed",
            "job_id": job_id,
            "message": update.get("message") or "Image generation failed",
            "retryable": update.get("retryable"),
        }

    if status == "cancelled":
        return {"event": "cancelled", "job_id": job_id, "message": update.get("message")}

    if status == "executing":
        raw_node = update.get("node")
        return {
            "event": "node",
            "job_id": job_id,
            "node": None if raw_node is None else str(raw_node),
        }

    if status in _QUIET_LEGACY_STATUSES:
        return None

    if status == "execution_cached":
        raw_nodes = update.get("nodes") or data.get("nodes") or []
        return {
            "event": "cached_nodes",
            "job_id": job_id,
            "nodes": [str(n) for n in raw_nodes] if isinstance(raw_nodes, (list, tuple)) else None,
        }

    value = update.get("value")
    max_v = update.get("max") or 0
    if value is not None and max_v:
        # A (value, max) PAIR is a fraction by construction: dividing is the only
        # way to get a percentage out of it, so this branch is always right.
        value = round(value / max_v * 100)
    elif value is None:
        progress = update.get("progress")
        if isinstance(progress, dict):
            p_max = progress.get("max") or 0
            p_cur = progress.get("value") or 0
            value = round(p_cur / p_max * 100) if p_max else None

    # A bare `value` with no `max` is taken at face value as a percent.
    #
    # This used to be followed by `elif value is not None and value <= 1: value =
    # round(value * 100)`, "defensive: legacy workers may emit a 0..1 fraction".
    # That branch is why the declared unit below is a lie: it is a heuristic, and
    # for a canonical percent producer `value == 1` — one percent done — became
    # 100, in the same frame the reducer reads `value_unit == "percent"` and
    # takes at face value. The single most-watched number in the UI jumped to
    # full on the first render step.
    #
    # The branch was also unreachable in its own terms: the only way to reach it
    # was `value is not None and not max_v`, i.e. a frame with no `max` at all,
    # which is exactly the shape a percent producer sends and a fraction producer
    # cannot disambiguate. A real fraction is declared — `value_unit: "fraction"`
    # is the wire contract and the reducer honours it — not guessed at.
    return {"event": "progress", "job_id": job_id, "value": value, "value_unit": "percent"}


def normalize_validation_result(result: Any, directories: list[str] | None = None) -> dict[str, Any]:
    """Normalize an upstream validation answer to the totals contract.

    Reconciliation step 0 reads ``total_invalid``/``total_partial``; some
    upstreams answer per-directory file lists instead of totals. Fill both
    shapes so either dialect feeds the reconciler.
    """
    if not isinstance(result, dict):
        result = {"status": "ok", "result": result}
    normalized = dict(result)
    valid = normalized.get("valid")
    invalid = normalized.get("invalid")
    partial = normalized.get("partial")
    if not isinstance(valid, list):
        valid = []
        normalized["valid"] = valid
    if not isinstance(invalid, list):
        invalid = []
        normalized["invalid"] = invalid
    if not isinstance(partial, list):
        partial = []
        normalized["partial"] = partial
    if not isinstance(normalized.get("by_directory"), dict):
        normalized["by_directory"] = {}
    normalized.setdefault("status", "ok")
    for key, bucket in (
        ("total_valid", valid),
        ("total_invalid", invalid),
        ("total_partial", partial),
    ):
        try:
            total = int(normalized.get(key, len(bucket)) or 0)
        except (TypeError, ValueError):
            total = len(bucket)
        normalized[key] = total
    try:
        normalized["total_indeterminate"] = int(normalized.get("total_indeterminate", 0) or 0)
    except (TypeError, ValueError):
        normalized["total_indeterminate"] = 0
    if directories:
        normalized.setdefault("directories", list(directories))
    return normalized


#: job_id -> engine currently running it. Cancellation resolves through this
#: registry first so a cancel reaches the instance actually streaming the job
#: even after the factory cache rebuilt or evicted it (cache TTL < job TTL).
_ACTIVE_JOB_ENGINES: "dict[str, InProcessEngine]" = {}


def find_engine_for_job(job_id: str | None) -> "InProcessEngine | None":
    if not job_id:
        return None
    return _ACTIVE_JOB_ENGINES.get(job_id)


class InProcessEngine(ABC):
    """Abstract base class for all in-process execution engines."""

    #: True when the engine owns a model tree that participates in model
    #: reconciliation (Modal, Beam, Direct-with-agent). LLM and TTS engines
    #: leave this False — they have no model files to download or validate.
    manages_model_files: bool = False

    def __init__(self, provider_id: str):
        self.provider_id = provider_id
        self._active_jobs: set[str] = set()
        self._cancelled_jobs: set[str] = set()
        # Per-job upstream abort, registered by each engine's inference loop when
        # it opens its stream and dropped when the stream closes. See
        # `register_abort`. Cancel without this only sets the promise of a flag,
        # which a parked stream cannot observe — see `_on_cancel`.
        self._job_aborts: dict[str, Any] = {}

    def register_abort(self, job_id: str | None, abort: Any) -> None:
        """Publish the callable that stops THIS job's upstream work.

        Every engine's inference loop is a stream, and a user cancel has to
        interrupt the *read*, not wait for the next item to arrive. Without a
        registered abort a cancel only sets `_cancelled_jobs`, which the loop
        checks between items — so a provider that is quiet (a long denoise
        step, a model still loading, an LLM idle between tokens) keeps
        generating, and billing, until the next frame or the caller's timeout.
        Only one abort per job; registering again replaces the previous one.
        """
        if not job_id:
            return
        if abort is None:
            self._job_aborts.pop(job_id, None)
        else:
            self._job_aborts[job_id] = abort

    def register_stream_abort(self, job_id: str | None, response: Any) -> None:
        """Register a stream response's `aclose` as this job's upstream abort.

        Closing the response terminates the HTTP request itself, which is the only
        thing that actually stops an upstream generation — and what stops it being
        billed. The flag the inference loop checks is the *fallback* either side of
        this registration; an idle stream (a provider thinking before its first
        token) would otherwise sit there until the caller's timeout, which is the
        whole defect this closes.

        Registered defensively: `aclose` is read through `getattr` rather than
        resolved eagerly, because `register_abort(job_id, response.aclose)`
        evaluates the attribute at the call and would take the whole inference
        down if it is missing. `_abort_job` already swallows a failing abort, but
        not a failing attribute access while registering one.
        """
        aclose = getattr(response, "aclose", None)
        if aclose is None:
            return
        self.register_abort(job_id, aclose)

    def _abort_job(self, job_id: str | None) -> Any:
        """Invoke the registered abort, swallowing anything it raises.

        Returns whatever the abort returned so the caller can await it — the
        sync form (`task.cancel`) and the async form (`response.aclose`, for a
        stream that has to be torn down over the network) both live in this one
        registry. A failing abort is never allowed to fail the cancel call the
        user made: the flag still stops the loop, so this is an optimisation on
        top of a correct baseline.
        """
        if not job_id:
            return None
        abort = self._job_aborts.get(job_id)
        if abort is None:
            return None
        try:
            return abort()
        except Exception:
            return None

    async def run_inference(
        self,
        workflow: dict[str, Any],
        job_id: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run ``inference`` with job tracking, mirroring provider_core's
        JobCancellationTracker (background.py start_job/end_job).

        A stale cancel flag from an aborted earlier attempt is cleared on
        entry, so a retry on the same engine is never born cancelled, and
        both the flag and the active marker are dropped on every exit path.
        The inner generator is always closed, so remote streams and
        ``asyncio.timeout`` scopes are torn down deterministically.
        """
        import contextlib

        if job_id:
            self._cancelled_jobs.discard(job_id)
            self._active_jobs.add(job_id)
            _ACTIVE_JOB_ENGINES[job_id] = self
        try:
            async with contextlib.aclosing(self.inference(workflow, job_id=job_id, **kwargs)) as stream:
                async for event in stream:
                    yield event
        finally:
            if job_id:
                self._active_jobs.discard(job_id)
                self._cancelled_jobs.discard(job_id)
                self.register_abort(job_id, None)
                if _ACTIVE_JOB_ENGINES.get(job_id) is self:
                    _ACTIVE_JOB_ENGINES.pop(job_id, None)
            # If this engine was invalidated mid-job (credentials rotated, provider
            # PATCHed), its close was deferred to here — closing it earlier would
            # have aborted the stream on a connection the provider had already been
            # paid for. Import is local: base must not import engine_factory, which
            # imports base.
            if not self._active_jobs:
                try:
                    from services.engines.engine_factory import drain_pending_engine_closes

                    drain_pending_engine_closes(self)
                except Exception:
                    pass

    #: A rig the engine cannot write to (plain Direct ComfyUI) still gets a
    #: reconciliation pass: list what is loadable and mark those registry
    #: rows ready, without validation or downloads. Mirrors the legacy
    #: direct_url run_reconciliation register-discovered path.
    supports_discovery_reconcile: bool = False

    def is_job_active(self, job_id: str | None) -> bool:
        return bool(job_id) and job_id in self._active_jobs

    def is_cancelled(self, job_id: str | None) -> bool:
        return bool(job_id) and job_id in self._cancelled_jobs

    async def _on_cancel(self, job_id: str) -> None:
        """Hook for engines that can interrupt the upstream (e.g. ComfyUI)."""
        return None

    @abstractmethod
    async def check_health(self) -> dict[str, Any]:
        """Check connection health and upstream availability."""
        raise NotImplementedError

    @abstractmethod
    async def inference(
        self,
        workflow: dict[str, Any],
        job_id: str | None = None,
        use_snapshot: bool = False,
        timeout: float = 3600.0,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Execute an inference workflow, yielding TaskEvent dictionaries:
        - {"event": "started", "job_id": ...}
        - {"event": "node", "node": ...}
        - {"event": "progress", "value": ..., "max": ...}
        - {"event": "completed", "outputs": [...]}
        - {"event": "failed", "message": ...}
        """
        raise NotImplementedError

    @abstractmethod
    async def list_models(self, directory: str) -> list[dict[str, Any]]:
        """List model files available in the specified directory on provider storage."""
        raise NotImplementedError

    @abstractmethod
    async def get_file_stream(self, path: str) -> AsyncIterator[bytes]:
        """Stream a file from provider storage (e.g. generated image or checkpoint)."""
        raise NotImplementedError

    @abstractmethod
    async def delete_file(self, path: str) -> bool:
        """Delete a file from provider storage."""
        raise NotImplementedError

    async def cancel_job(self, job_id: str) -> bool:
        """Best-effort cancellation of a running job.

        Only jobs currently streaming through ``run_inference`` are flagged,
        like the container's /cancel-job which answered ``not_found`` for an
        inactive job. Flagging an inactive id would poison the next attempt.

        The abort runs *before* `_on_cancel`, and is awaited: an LLM stream is
        stopped by closing its HTTP response, which is I/O and cannot be a
        fire-and-forget task. Engines that keep a fetcher task register
        `task.cancel` instead. Without either, a cancel only sets a flag the
        loop checks between items — so a provider that is quiet keeps
        generating, and billing, until the next frame or the caller's timeout.
        """
        if not self.is_job_active(job_id):
            return False
        self._cancelled_jobs.add(job_id)
        try:
            result = self._abort_job(job_id)
            if inspect.isawaitable(result):
                await result
        except Exception:
            # Never let the abort path fail the cancel the user asked for.
            pass
        await self._on_cancel(job_id)
        return True

    async def validate_models(self, directories: list[str]) -> dict[str, Any]:
        """Validate integrity of models in specified directories."""
        return {"status": "ok", "valid": True}

    async def setup_models(self) -> bool:
        """Initialise provider storage directories. False when unsupported."""
        return False

    async def upload_file(self, filename: str, content_base64: str, directory: str = "") -> bool:
        """Upload a small file to provider storage. False when unsupported."""
        return False

    async def deploy(self) -> dict[str, Any]:
        """No-op deploy: in-process engines need no container deploy.

        Present for parity with legacy container clients (`modal deploy` /
        `beam deploy` of the worker app) so callers probing the method get
        the `not_applicable` vocabulary the lifecycle route serves.
        """
        return {"status": "not_applicable", "mode": "in_process", "provider_id": self.provider_id}

    async def get_object_info(self) -> dict[str, Any]:
        """Extract ComfyUI node definitions. Raises when unsupported."""
        raise NotImplementedError

    async def get_info(self) -> dict[str, Any]:
        """Return provider info (engine type, provider_id). Override for richer shapes."""
        return {"provider_id": self.provider_id, "engine": type(self).__name__}

    async def get_storage_stats(self) -> dict[str, Any]:
        """Return model counts by directory by listing all MODEL_DIRECTORIES.

        Mirrors the container's `/provider-stats` shape. Engines that do not
        manage model files (LLM, TTS) override to return an empty payload.
        """
        if not getattr(self, "manages_model_files", False):
            return {"provider_id": self.provider_id, "total": 0, "by_directory": {}}
        by_directory: dict[str, int] = {}
        total = 0
        for directory in MODEL_DIRECTORIES:
            try:
                entries = await self.list_models(directory)
            except Exception as exc:
                logger.warning("engine_list_models_failed", provider_id=self.provider_id, directory=directory, error=str(exc))
                entries = []
            count = len([e for e in entries if isinstance(e, dict) and e.get("name")])
            by_directory[directory] = count
            total += count
        return {"provider_id": self.provider_id, "total": total, "by_directory": by_directory}

    async def download_file(
        self,
        download_url: str,
        storage_path: str,
        token: str | None = None,
        timeout: float = 3600.0,
    ) -> dict[str, Any]:
        """Download one model into provider storage, awaiting completion."""
        raise NotImplementedError
