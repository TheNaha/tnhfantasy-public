"""
Shared Pydantic models for provider workers.
These models define the API contract for all provider worker endpoints.
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel


class TaskEvent(BaseModel):
    """Single, unified streaming event emitted by every worker.

    Both the image worker (ComfyUI progress/executing/success) and the LLM
    worker (SSE deltas/completed/tool-calls) translate their native stream
    into this one schema, so the backend needs a single reader + reducer pair
    instead of two divergent NDJSON dialects.

    event:
      started      job accepted, work beginning
      progress     coarse progress, 0..100 PERCENT (see `value` and `value_unit`)
      delta        incremental token text for llm jobs
      node         a ComfyUI node started executing (image jobs)
      completed    terminal success (carries ``outputs``)
      failed       terminal failure (carries ``message``)
      cancelled    terminal cancellation

    `value_unit` says what `value` counts. It is not decoration: the backend
    re-normalised a percent as if it might be a fraction
    (`backend_v2/services/provider_client.py`,
    `percent = int(val * 100) if val <= 1 else int(val)`), so a worker reporting
    exactly `value == 1` — one percent done — was recorded as 100%. No worker has
    emitted a fraction since the normalisation below, so that branch could only
    ever misfire, and nothing on the wire said which reading was correct. Every
    progress event this tier emits now carries `value_unit="percent"`, so the
    reading is a fact on the wire rather than a convention in a comment.
    """
    event: Literal[
        "started", "progress", "delta", "node", "cached_nodes", "completed", "failed", "cancelled"
    ]
    job_id: Optional[str] = None
    seq: Optional[int] = None
    value: Optional[float] = None          # progress, in `value_unit` (image workers); llm engines use text deltas
    value_unit: Optional[str] = None       # "percent" on every progress event this tier emits
    text: Optional[str] = None             # llm token delta
    node: Optional[str] = None             # executing comfy node
    nodes: Optional[List[str]] = None      # cached comfy nodes
    tool_calls: Optional[List[Dict[str, Any]]] = None  # llm tool calls (on completed)
    outputs: Optional[List[Dict[str, Any]]] = None      # final outputs (on completed)
    status: Optional[str] = None           # backend-facing status hint
    message: Optional[str] = None          # error / cancel / human message
    retryable: Optional[bool] = None       # failed: True if the job may be retried

    def to_ndjson(self) -> str:
        return self.model_dump_json() + "\n"


class ErrorResponse(BaseModel):
    """Standard error payload for worker endpoints and streamed updates."""
    status: Literal["error"] = "error"
    message: str
    retryable: bool = False
    code: Optional[int] = None


class StatusResponse(BaseModel):
    """Standard success and queued payload for worker endpoints."""
    status: Literal["success", "queued"]
    message: str
    provider: Optional[str] = None
    result: Optional[Any] = None
    files: Optional[List[Dict[str, Any]]] = None


def build_error_response(
    message: str,
    *,
    retryable: bool = False,
    code: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a normalized error payload."""
    return ErrorResponse(
        message=message,
        retryable=retryable,
        code=code,
    ).model_dump(exclude_none=True)


def build_status_response(
    status: Literal["success", "queued"],
    message: str,
    *,
    provider: Optional[str] = None,
    result: Optional[Any] = None,
    files: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build a normalized non-error payload for worker endpoints."""
    return StatusResponse(
        status=status,
        message=message,
        provider=provider,
        result=result,
        files=files,
    ).model_dump(exclude_none=True)


# Model directories used across providers
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
    "models/ipadapter",
]
