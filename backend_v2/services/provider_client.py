import asyncio
import re
import time

from core.entities import JobStatus
from core.events import EventType
from core.progress import coerce_worker_percent
from infrastructure.logging import get_logger
from services.engines.base import EngineAuthError
from services.job_boot_metrics import stamp_boot_seconds

logger = get_logger("provider_client")


def _extract_http_status(message: str) -> int | None:
    """Extract an HTTP status code from an error message, if present.

    Looks for patterns like "HTTP 500", "500 Internal Server Error", or a
    standalone 3-digit code in the 4xx/5xx range. Returns None when none is
    found — callers treat that as "unknown status" and fall back to the
    default retry cap.
    """
    if not isinstance(message, str):
        return None
    # "HTTP 500" or "HTTP/1.1 500" style
    m = re.search(r"HTTP(?:/[\d.]+)?\s+(\d{3})", message)
    if m:
        code = int(m.group(1))
        if 400 <= code < 600:
            return code
    # Standalone 3-digit code at word boundary
    m = re.search(r"\b(\d{3})\b", message)
    if m:
        code = int(m.group(1))
        if 400 <= code < 600:
            return code
    return None

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

    def __init__(
        self,
        message: str,
        provider_id: str,
        is_retryable: bool = True,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.provider_id = provider_id
        self.is_retryable = is_retryable
        self.status_code = status_code


class JobTimeoutError(Exception):
    """Raised when a job exceeds its timeout."""


class JobCancelledError(Exception):
    """Raised when the worker confirms job cancellation."""

    def __init__(self, message: str, provider_id: str = ""):
        super().__init__(message)
        self.provider_id = provider_id


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
        self._latest_preview: str | None = None

    async def _persist_progress(self, **fields) -> None:
        """Write progress to the row, coalescing bursts. Terminal states bypass."""
        now = time.perf_counter()
        if now - self._last_persist_at < PROGRESS_PERSIST_INTERVAL_SECONDS:
            self._pending_progress = fields
            return
        self._last_persist_at = now
        self._pending_progress = None
        event_extra = {"preview": self._latest_preview} if self._latest_preview else None
        await self.job_service.update_job(self.job_id, event_extra=event_extra, **fields)

    async def __call__(self, ev: dict) -> None:
        event = ev.get("event")
        # First frame from the provider: stamp the dispatch→first-event leg
        # (for serverless that is the boot the user pays for). Re-stamp runs
        # are free after the first — the guard lives in the helper.
        await stamp_boot_seconds(self.job_service, self.job_id)
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
        elif event == "preview":
            preview = ev.get("preview")
            if preview:
                self._latest_preview = preview
                now = time.perf_counter()
                if now - self._last_persist_at >= PROGRESS_PERSIST_INTERVAL_SECONDS:
                    self._last_persist_at = now
                    await self.job_service.update_job(
                        self.job_id,
                        event_extra={"preview": preview},
                        event_type=EventType.JOB_PROGRESS,
                        include_full_metadata=False,
                    )
        elif event == "completed":
            # Terminal: the last coalesced progress frame is now moot, because
            # the completion path overwrites status, progress and message
            # anyway. Flushing here would be a redundant write.
            self._latest_preview = None
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
            if ev.get("timings"):
                self.final_result["timings"] = ev["timings"]
        elif event == "failed":
            self._latest_preview = None
            message = ev.get("message", "Image generation failed")
            status_code = _extract_http_status(message)
            raise ProviderCallError(
                message, provider_id=self.provider_id,
                is_retryable=bool(ev.get("retryable", False)),
                status_code=status_code,
            )
        elif event == "cancelled":
            self._latest_preview = None
            raise JobCancelledError(ev.get("message") or "Job cancelled by user", provider_id=self.provider_id)

    def finalize(self):
        if self.final_result:
            return self.final_result
        raise ProviderCallError("No completed event received from worker", provider_id=self.provider_id, is_retryable=True)


class _LLMReducer:
    """Reduce unified TaskEvents into LLM-job state + final result (text/tool_calls).

    The frames go out through `update_job`, like every other job event, so
    there is ONE contract.

    They used to be built by hand and pushed straight to `emit_job_event`.
    That had three consequences, all of them invisible from the outside:

      * the payload carried no `task_type`, and the frontend's global
        realtime handler drops any event without one - so the LLM progress
        frames never reached the global subscribers at all;

      * the payload's `status` was a hand-written string ("evaluating_prompt",
        "generating") rather than a `JobStatus`, so the job's `status` field
        had two different vocabularies depending on which event you read;

      * the payload's `metadata` REPLACED the job's own metadata with a
        hand-built eight-key dict. The frontend's background-job guard
        reads `meta.background`, and that flag was never in the payload -
        so a memory-extraction job could render as a second "X is thinking"
        bubble under the reply it was extracted from. Every other key the
        job carried was lost the same way.

    `status` says what the job IS. The LLM sub-state is what it is DOING,
    and that travels as `phase`.
    """

    def __init__(self, job_id, job_service, provider_id, workflow):
        self.job_id = job_id
        self.job_service = job_service
        self.provider_id = provider_id
        self.workflow = workflow
        self.full_content = ""
        self.last_emit = 0.0
        self.token_count = 0
        self.start_time = time.monotonic()
        self.first_token_time = None

    async def _emit_phase(self, *, phase: str, stream_chunk: str, text: str, **extra) -> None:
        """One streaming frame, on the canonical job path."""
        event_extra = {
            "stream_chunk": stream_chunk,
            "text": text,
            "phase": phase,
            "provider_id": self.provider_id,
            "model": self.workflow.get("model"),
            **extra,
        }
        await self.job_service.update_job(
            self.job_id,
            event_extra=event_extra,
            event_type=EventType.JOB_PROGRESS,
            include_full_metadata=False,
        )

    async def __call__(self, ev: dict) -> None:
        event = ev.get("event")
        # First frame from the provider: stamp the dispatch→first-event leg
        # (for serverless that is the boot the user pays for). Re-stamp runs
        # are free after the first — the guard lives in the helper.
        await stamp_boot_seconds(self.job_service, self.job_id)
        if event == "started":
            await self._emit_phase(phase="evaluating_prompt", stream_chunk="", text="")
        elif event == "delta":
            msg = ev.get("text") or ""
            self.full_content += msg
            self.token_count += 1
            now = time.monotonic()
            if self.first_token_time is None:
                self.first_token_time = now
            elapsed = now - self.first_token_time
            speed_tps = round(self.token_count / max(elapsed, 0.001), 1) if elapsed > 0 else 0.0

            if now - self.last_emit >= LLM_PROGRESS_THROTTLE_SECONDS:
                self.last_emit = now
                await self._emit_phase(
                    phase="generating",
                    stream_chunk=msg,
                    text=self.full_content,
                    token_count=self.token_count,
                    speed_tps=speed_tps,
                    elapsed_seconds=round(now - self.start_time, 1),
                )
        elif event == "completed":
            now = time.monotonic()
            elapsed_total = max(now - self.start_time, 0.001)
            avg_speed_tps = round(self.token_count / elapsed_total, 1) if self.token_count > 0 else 0.0
            if self.full_content:
                await self._emit_phase(
                    phase="generating",
                    stream_chunk="",
                    text=self.full_content,
                    token_count=self.token_count,
                    speed_tps=avg_speed_tps,
                    elapsed_seconds=round(elapsed_total, 1),
                )
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
                "metrics": {
                    "token_count": self.token_count,
                    "speed_tps": avg_speed_tps,
                    "elapsed_seconds": round(elapsed_total, 1),
                },
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

    raw_model = workflow.get("model")
    resolved_model = raw_model
    if not resolved_model or resolved_model == "default":
        kind = workflow.get("type") or workflow.get("kind")
        from services.llm_config import get_default_llm_model, resolve_model_for_kind

        session = getattr(job_service, "session", None)
        if kind and session:
            try:
                resolved_model = resolve_model_for_kind(kind, session=session)
            except Exception:
                resolved_model = get_default_llm_model()
        else:
            resolved_model = get_default_llm_model()

    payload = {
        "messages": workflow.get("messages"),
        "tools": workflow.get("tools"),
        "model": resolved_model,
        "type": workflow.get("type"),
        "role": workflow.get("role"),
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
