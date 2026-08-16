import json
import time

from core.entities import JobStatus
from core.events import emit_job_event, EventType
from infrastructure.http_client import get_streaming_client
from infrastructure.logging import get_logger

logger = get_logger("provider_client")

# Cap LLM progress emission at ~60fps. LLM workers stream one JOB_PROGRESS per
# token; capping the emit rate reduces WebSocket fan-out and the per-token JS
# handling on low-end mobile devices (issue #1a). The frontend already keeps
# only the latest payload per job (lossless), so fewer emits never drop tokens.
LLM_PROGRESS_THROTTLE_SECONDS = 1.0 / 60.0


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


async def stream_task_events(
    worker_url: str,
    payload: dict,
    job_id: str,
    *,
    task_type: str,
    job_service,
    timeout: float,
    provider_id: str = "",
    total_nodes: int = 0,
    reducer=None,
):
    """Single, unified reader for ALL worker streams.

    Workers emit a unified ``TaskEvent`` NDJSON schema (see
    provider_core.models.TaskEvent). This coroutine resolves the HTTP stream,
    parses each line into a TaskEvent, and delegates handling to ``reducer``
    (per task_type). Returns whatever ``reducer`` returns on ``completed``.
    """
    import httpx

    async with get_streaming_client(timeout=timeout) as client:
        try:
            async with client.stream(
                "POST",
                f"{worker_url}/inference",
                json=payload,
                timeout=timeout,
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    is_retryable = response.status_code >= 500
                    try:
                        p = json.loads(error_text.decode())
                        if isinstance(p, dict) and "retryable" in p:
                            is_retryable = bool(p["retryable"])
                    except Exception as exc:
                        logger.debug("error_body_parse_failed", error=str(exc))
                    raise ProviderCallError(
                        format_worker_http_error(response.status_code, error_text.decode()),
                        provider_id=provider_id,
                        is_retryable=is_retryable,
                    )

                await job_service.update_job(job_id, status=JobStatus.CONNECTED, message="Connected to provider...")

                buffer = ""

                async def process_line(raw: str) -> None:
                    line = raw.strip()
                    if not line:
                        return
                    try:
                        update = json.loads(line)
                    except json.JSONDecodeError as error:
                        logger.warning("job_parse_error", job_id=job_id, error=str(error))
                        return
                    result = await reducer(update)
                    if result is not None:
                        # Reducers return a value on terminal ``completed`` events
                        # (e.g. the LLM reducer). Capture it so it isn't lost when
                        # we also call finalize() below.
                        nonlocal _terminal_result
                        _terminal_result = result

                _terminal_result = None
                async for chunk in response.aiter_bytes():
                    buffer += chunk.decode("utf-8")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        await process_line(line)
                if buffer.strip():
                    await process_line(buffer)

                if _terminal_result is not None:
                    return _terminal_result
                return reducer.finalize()

        except httpx.TimeoutException:
            raise JobTimeoutError(f"Job timed out after {timeout}s")
        except httpx.ConnectError as error:
            raise ProviderCallError(f"Failed to connect to worker: {error}", provider_id=provider_id, is_retryable=True)
        except httpx.HTTPError as error:
            is_retryable = not isinstance(error, httpx.LocalProtocolError)
            raise ProviderCallError(f"HTTP error: {error}", provider_id=provider_id, is_retryable=is_retryable)


class _ImageReducer:
    """Reduce unified TaskEvents into image-job state + final result."""

    def __init__(self, job_id, job_service, total_nodes, provider_id):
        self.job_id = job_id
        self.job_service = job_service
        self.total_nodes = total_nodes
        self.provider_id = provider_id
        self.executed_nodes = set()
        self.final_result = None

    async def __call__(self, ev: dict) -> None:
        event = ev.get("event")
        if event == "started":
            await self.job_service.update_job(self.job_id, status=JobStatus.PRE_GENERATION, message="Queued in worker...")
        elif event == "progress":
            val = ev.get("value") or 0
            percent = int(val * 100) if val and val <= 1 else int(val)
            overall = int((len(self.executed_nodes) / self.total_nodes) * 100) if self.total_nodes > 0 else percent
            await self.job_service.update_job(
                self.job_id, status=JobStatus.GENERATING, progress=percent,
                overall_progress=overall, message=f"Rendering: {percent}%",
            )
        elif event == "node":
            node_id = ev.get("node")
            if node_id:
                self.executed_nodes.add(node_id)
            overall = int((len(self.executed_nodes) / self.total_nodes) * 100) if self.total_nodes > 0 else 0
            await self.job_service.update_job(
                self.job_id, status=JobStatus.GENERATING, overall_progress=overall,
                message=f"Executing node {len(self.executed_nodes)}/{self.total_nodes}...",
            )
        elif event == "cached_nodes":
            nodes = ev.get("nodes") or []
            for node_id in nodes:
                self.executed_nodes.add(node_id)
            overall = int((len(self.executed_nodes) / self.total_nodes) * 100) if self.total_nodes > 0 else 0
            await self.job_service.update_job(
                self.job_id, status=JobStatus.GENERATING, overall_progress=overall,
                message=f"Cached {len(nodes)} nodes...",
            )
        elif event == "completed":
            try:
                validate_image_outputs(ev)
            except ValueError as error:
                raise ProviderCallError(f"Invalid success payload: {error}", provider_id=self.provider_id, is_retryable=True) from error
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
            raise ProviderCallError(ev.get("message", "Image generation failed"), provider_id=self.provider_id,
                                    is_retryable=bool(ev.get("retryable", False)))
        elif event == "cancelled":
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
        import time
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


async def call_image_provider(
    worker_url: str,
    workflow: dict,
    job_id: str,
    job_service,
    total_nodes: int,
    timeout: float,
    use_snapshot: bool = False,
    provider_id: str = "",
) -> dict:
    reducer = _ImageReducer(job_id, job_service, total_nodes, provider_id)
    return await stream_task_events(
        worker_url,
        {"workflow": workflow, "use_snapshot": use_snapshot, "job_id": job_id, "timeout_seconds": timeout},
        job_id,
        task_type="image",
        job_service=job_service,
        timeout=timeout,
        provider_id=provider_id,
        total_nodes=total_nodes,
        reducer=reducer,
    )


async def call_llm_provider(
    worker_url: str,
    workflow: dict,
    job_id: str,
    job_service,
    timeout: float,
    provider_id: str = "",
    provider_type: str = "modal",
) -> dict:
    reducer = _LLMReducer(job_id, job_service, provider_id, workflow)
    temperature = workflow.get("temperature")
    if temperature is None:
        try:
            from config import get_config
            temperature = (get_config() or {}).get("ai", {}).get("temperature")
        except Exception:
            temperature = None
    payload = {
        "messages": workflow.get("messages"),
        "tools": workflow.get("tools"),
        "model": workflow.get("model"),
        "temperature": temperature,
        "job_id": job_id,
        "timeout_seconds": timeout,
    }
    return await stream_task_events(
        worker_url,
        payload,
        job_id,
        task_type="llm",
        job_service=job_service,
        timeout=timeout,
        provider_id=provider_id,
        reducer=reducer,
    )
