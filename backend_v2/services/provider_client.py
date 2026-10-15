import asyncio
import json
import time

from core.entities import JobStatus
from core.events import emit_job_event, EventType
from core.progress import coerce_worker_percent
from infrastructure.logging import get_logger
from services.engines.base import EngineAuthError

logger = get_logger("provider_client")

# Cap LLM progress emission at ~60fps. LLM workers stream one JOB_PROGRESS per
# token; capping the emit rate reduces WebSocket fan-out and the per-token JS
# handling on low-end mobile devices (issue #1a). The frontend already keeps
# only the latest payload per job (lossless), so fewer emits never drop tokens.
LLM_PROGRESS_THROTTLE_SECONDS = 1.0 / 60.0

# How often a generation's progress may be written to the `jobs` row. The
# websocket event is unaffected, so the UI still updates smoothly; this bounds
# the number of synchronous commits on the event loop per generation.
PROGRESS_PERSIST_INTERVAL_SECONDS = 1.0


class ProviderCallError(Exception):
    """Raised when a provider call fails and may be retried."""

    def __init__(self, message: str, provider_id: str, is_retryable: bool = True):
        super().__init__(message)
        self.provider_id = provider_id
        self.is_retryable = is_retryable


class JobTimeoutError(Exception):
    """Raised when a job exceeds its timeout."""


class JobCancelledError(Exception):
    """Raised when the worker confirms job cancellation."""

    def __init__(self, message: str, provider_id: str = ""):
        super().__init__(message)
        self.provider_id = provider_id


def extract_worker_error_message(update: dict) -> str:
    """Normalize worker error payloads from different providers."""
    return update.get("message", "Unknown worker error")


def format_worker_http_error(status_code: int, error_text: str) -> str:
    """Produce a readable error for non-200 worker responses."""
    if not error_text:
        return f"Worker returned {status_code}"

    try:
        payload = json.loads(error_text)
    except json.JSONDecodeError:
        return f"Worker returned {status_code}: {error_text}"

    if isinstance(payload, dict):
        return f"Worker returned {status_code}: {extract_worker_error_message(payload)}"
    return f"Worker returned {status_code}: {payload}"


def validate_image_outputs(payload: dict) -> None:
    """Validate a completed image TaskEvent's ``outputs`` before finalization."""
    if not isinstance(payload, dict):
        raise ValueError("image result must be an object")
    outputs = payload.get("outputs")
    if outputs is None:
        return
    if not isinstance(outputs, list):
        raise ValueError("image outputs must be a list")
    for index, img in enumerate(outputs):
        if not isinstance(img, dict):
            raise ValueError(f"image outputs[{index}] must be an object")
        if img.get("data") is None and img.get("filename") is None:
            raise ValueError(f"image outputs[{index}] missing data or filename")


class _ImageReducer:
    """Reduce unified TaskEvents into image-job state + final result."""

    def __init__(self, job_id, job_service, total_nodes, provider_id):
        self.job_id = job_id
        self.job_service = job_service
        self.total_nodes = total_nodes
        self.provider_id = provider_id
        self.executed_nodes = set()
        self.final_result = None
        # Progress frames are coalesced for the database, not for the UI.
        # ComfyUI emits a `node` and a `progress` event for every step of every
        # attempt, so a 20-step SDXL job produced 40-60 `update_job` calls, each
        # one a synchronous SELECT + UPDATE + COMMIT + REFRESH on the event
        # loop plus a websocket broadcast and a flushed log line. Every gallery,
        # job-list and provider-status request queued behind them.
        #
        # The websocket event still goes out on every frame — that is what the
        # progress bar reads, and it is cheap. Only the row write is throttled,
        # to at most one per PROGRESS_PERSIST_INTERVAL_SECONDS.
        #
        # No flush is needed. Every terminal branch below discards the pending
        # frame, because `completed`/`failed`/`cancelled` all overwrite status,
        # progress and message anyway. And a stream that ends with no terminal
        # event raises in `finalize()`, which routes to the job's failure path —
        # so there is no exit where a dropped frame is the last thing the user
        # would have seen.
        self._last_persist_at = 0.0
        self._pending_progress: dict | None = None

    async def _persist_progress(self, **fields) -> None:
        """Write progress to the row, coalescing bursts. Terminal states bypass."""
        now = time.perf_counter()
        if now - self._last_persist_at < PROGRESS_PERSIST_INTERVAL_SECONDS:
            self._pending_progress = fields
            return
        self._last_persist_at = now
        self._pending_progress = None
        await self.job_service.update_job(self.job_id, **fields)

    async def __call__(self, ev: dict) -> None:
        event = ev.get("event")
        if event == "started":
            await self.job_service.update_job(self.job_id, status=JobStatus.PRE_GENERATION, message="Queued in worker...")
        elif event == "progress":
            # One definition of the rule, shared with `api/routes/worker_ws`.
            # That half had kept the pre-`value_unit` `val <= 1` heuristic while
            # this half had been converted, so a canonical event carrying
            # `value == 1` — one percent done — read as 1% here and 100% there.
            percent = coerce_worker_percent(ev.get("value") or 0, ev.get("value_unit"))
            overall = int((len(self.executed_nodes) / self.total_nodes) * 100) if self.total_nodes > 0 else percent
            await self._persist_progress(
                status=JobStatus.GENERATING, progress=percent,
                overall_progress=overall, message=f"Rendering: {percent}%",
            )
        elif event == "node":
            node_id = ev.get("node")
            if node_id:
                self.executed_nodes.add(node_id)
            overall = int((len(self.executed_nodes) / self.total_nodes) * 100) if self.total_nodes > 0 else 0
            await self._persist_progress(
                status=JobStatus.GENERATING, overall_progress=overall,
                message=f"Executing node {len(self.executed_nodes)}/{self.total_nodes}...",
            )
        elif event == "cached_nodes":
            nodes = ev.get("nodes") or []
            for node_id in nodes:
                self.executed_nodes.add(node_id)
            overall = int((len(self.executed_nodes) / self.total_nodes) * 100) if self.total_nodes > 0 else 0
            await self._persist_progress(
                status=JobStatus.GENERATING, overall_progress=overall,
                message=f"Cached {len(nodes)} nodes...",
            )
        elif event == "completed":
            # Terminal: the last coalesced progress frame is now moot, because
            # the completion path overwrites status, progress and message
            # anyway. Flushing here would be a redundant write.
            self._pending_progress = None
            try:
                validate_image_outputs(ev)
            except ValueError as error:
                # Not retryable. A malformed *success* payload is deterministic:
                # the provider already ran the graph and answered with a shape
                # this client cannot use, and re-sending the identical request
                # produces the identical unusable answer. `is_retryable=True`
                # here routed straight into `maybe_retry_current_provider`
                # (max_retries 3, base_delay 1.0, max_delay 60.0) and then into
                # failover, so one bad response cost up to four paid inferences
                # per provider plus one per remaining provider. Fail the job
                # instead — the operator needs to see the bad payload, not a
                # bill for it.
                raise ProviderCallError(
                    f"Invalid success payload: {error}",
                    provider_id=self.provider_id,
                    is_retryable=False,
                ) from error
            artifacts = ev.get("outputs") or []
            # Split artifacts: base64 payloads must be decoded and written to disk
            # by build_job_outputs (legacy ``images`` shape); already-persisted
            # files (direct_url providers on a shared mount) pass through as
            # ``outputs`` so they are never decoded from base64 again.
            base64_images = [a for a in artifacts if isinstance(a, dict) and a.get("data")]
            persisted_outputs = [a for a in artifacts if isinstance(a, dict) and not a.get("data")]
            if base64_images:
                for img in base64_images:
                    img.setdefault("_base64_encoded", True)
                    img.setdefault("subfolder", "")
                self.final_result = {"images": base64_images, "outputs": persisted_outputs}
            else:
                self.final_result = ev
        elif event == "failed":
            self._pending_progress = None
            raise ProviderCallError(ev.get("message", "Image generation failed"), provider_id=self.provider_id,
                                    is_retryable=bool(ev.get("retryable", False)))
        elif event == "cancelled":
            self._pending_progress = None
            raise JobCancelledError(ev.get("message") or "Job cancelled by user", provider_id=self.provider_id)

    def finalize(self):
        if self.final_result:
            return self.final_result
        raise ProviderCallError("No completed event received from worker", provider_id=self.provider_id, is_retryable=True)


class _LLMReducer:
    """Reduce unified TaskEvents into LLM-job state + final result (text/tool_calls)."""

    def __init__(self, job_id, job_service, provider_id, workflow):
        self.job_id = job_id
        self.job_service = job_service
        self.provider_id = provider_id
        self.workflow = workflow
        self.full_content = ""
        self.last_emit = 0.0

    async def __call__(self, ev: dict) -> None:
        event = ev.get("event")
        if event == "delta":
            msg = ev.get("text") or ""
            self.full_content += msg
            now = time.monotonic()
            if now - self.last_emit >= LLM_PROGRESS_THROTTLE_SECONDS:
                self.last_emit = now
                await emit_job_event(EventType.JOB_PROGRESS, {
                    "id": self.job_id, "status": "generating", "stream_chunk": msg, "text": self.full_content,
                    "metadata_": {
                        "chat_id": self.workflow.get("chat_id"),
                        "story_id": self.workflow.get("story_id"),
                        "chapter_id": self.workflow.get("chapter_id"),
                        "type": self.workflow.get("type"),
                    },
                })
        elif event == "completed":
            if self.full_content:
                await emit_job_event(EventType.JOB_PROGRESS, {
                    "id": self.job_id, "status": "generating", "stream_chunk": "", "text": self.full_content,
                    "metadata_": {
                        "chat_id": self.workflow.get("chat_id"),
                        "story_id": self.workflow.get("story_id"),
                        "chapter_id": self.workflow.get("chapter_id"),
                        "type": self.workflow.get("type"),
                    },
                })
            outputs = ev.get("outputs") or []
            first = outputs[0] if outputs and isinstance(outputs[0], dict) else {}
            cancelled = ev.get("status") == "cancelled" or bool(first.get("cancelled"))
            if cancelled:
                raise JobCancelledError(ev.get("message") or "Job cancelled by user")
            return {
                "status": "success",
                "type": "text",
                "outputs": outputs,
                "chat_id": self.workflow.get("chat_id"),
                "story_id": self.workflow.get("story_id"),
                "chapter_id": self.workflow.get("chapter_id"),
            }
        elif event == "failed":
            raise ProviderCallError(ev.get("message", "Unknown error"), provider_id=self.provider_id,
                                    is_retryable=bool(ev.get("retryable", False)))
        elif event == "cancelled":
            raise JobCancelledError(ev.get("message") or "Job cancelled by user", provider_id=self.provider_id)

    def finalize(self):
        raise ProviderCallError("No completed event received from worker", provider_id=self.provider_id, is_retryable=True)


async def call_in_process_image_provider(
    engine,
    workflow: dict,
    job_id: str,
    job_service,
    total_nodes: int,
    timeout: float,
    use_snapshot: bool = False,
    provider_id: str = "",
) -> dict:
    reducer = _ImageReducer(job_id, job_service, total_nodes, provider_id)
    await job_service.update_job(job_id, status=JobStatus.CONNECTED, message=f"Connected to {provider_id}...")
    try:
        async with asyncio.timeout(timeout):
            async for event in engine.run_inference(
                workflow=workflow,
                job_id=job_id,
                use_snapshot=use_snapshot,
                timeout=timeout,
            ):
                result = await reducer(event)
                if result is not None:
                    return result
    except TimeoutError as exc:
        raise JobTimeoutError(f"Job timed out after {timeout}s") from exc
    except EngineAuthError as exc:
        raise ProviderCallError(str(exc), provider_id=provider_id, is_retryable=False) from exc
    return reducer.finalize()


async def call_in_process_tts_provider(
    engine,
    workflow: dict,
    job_id: str,
    job_service,
    total_nodes: int,
    timeout: float,
    use_snapshot: bool = False,
    provider_id: str = "",
) -> dict:
    """TTS execute path (parity with container routing).

    TTS workers emit the same terminal TaskEvent dialect (completed with
    ``outputs`` filename refs, failed with explicit retryable, cancelled),
    so the image reducer already finalizes them and ``job_processing``
    fetches the audio off the engine afterwards. Kept as a named wrapper
    (rather than calling the image helper) so dispatch, logs and timeout
    ownership read as TTS, matching the ``task_type`` the worker sees.
    """
    return await call_in_process_image_provider(
        engine=engine,
        workflow=workflow,
        job_id=job_id,
        job_service=job_service,
        total_nodes=total_nodes,
        timeout=timeout,
        use_snapshot=use_snapshot,
        provider_id=provider_id,
    )


async def call_in_process_llm_provider(
    engine,
    workflow: dict,
    job_id: str,
    job_service,
    timeout: float,
    provider_id: str = "",
) -> dict:
    reducer = _LLMReducer(job_id, job_service, provider_id, workflow)
    await job_service.update_job(job_id, status=JobStatus.CONNECTED, message=f"Connected to {provider_id}...")
    try:
        from config import get_config
        global_ai = ((get_config() or {}).get("ai") or {})
    except Exception as exc:
        logger.warning("global_ai_config_read_failed", job_id=job_id, error=str(exc))
        global_ai = {}

    def _resolve(key: str):
        # Per-job override wins; otherwise the global default (may be None).
        return workflow.get(key) if workflow.get(key) is not None else global_ai.get(key)

    payload = {
        "messages": workflow.get("messages"),
        "tools": workflow.get("tools"),
        "model": workflow.get("model"),
        "temperature": _resolve("temperature"),
        "top_p": _resolve("top_p"),
        "max_output_tokens": _resolve("max_output_tokens"),
        "frequency_penalty": _resolve("frequency_penalty"),
        "presence_penalty": _resolve("presence_penalty"),
        "job_id": job_id,
        "timeout_seconds": timeout,
    }

    # Same timeout ownership as the image path: a hung engine must fail the
    # job, not hang it forever. The container fns owned their own timeout
    # semantics; in-process the caller enforces the budget.
    try:
        async with asyncio.timeout(timeout):
            async for event in engine.run_inference(
                workflow=payload,
                job_id=job_id,
                timeout=timeout,
            ):
                result = await reducer(event)
                if result is not None:
                    return result
    except TimeoutError as exc:
        raise JobTimeoutError(f"Job timed out after {timeout}s") from exc
    except EngineAuthError as exc:
        raise ProviderCallError(str(exc), provider_id=provider_id, is_retryable=False) from exc
    return reducer.finalize()
