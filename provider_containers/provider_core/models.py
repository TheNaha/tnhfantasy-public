"""
Shared Pydantic models for provider workers.
These models define the API contract for all provider worker endpoints.
"""

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, model_validator


class InferenceRequest(BaseModel):
    """Unified inference request for ALL worker types (image, llm, audio, video).

    The worker dispatches on which payload fields are present:
      - image jobs: ``workflow`` holds the ComfyUI graph.
      - llm jobs: ``messages`` / ``tools`` / ``model`` hold the chat payload.
    This replaces the old ComfyUI-shaped contract where LLM messages were
    smuggled inside ``workflow``.
    """
    workflow: Optional[Dict[str, Any]] = None
    messages: Optional[List[Dict[str, Any]]] = None
    tools: Optional[List[Dict[str, Any]]] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    use_snapshot: bool = False
    job_id: Optional[str] = None
    timeout_seconds: Optional[float] = None

    @model_validator(mode="after")
    def _ensure_payload_present(self):
        if not (self.workflow or self.messages or self.tools or self.model):
            raise ValueError(
                "InferenceRequest requires at least one of: workflow, messages, tools, or model"
            )
        return self


class TaskEvent(BaseModel):
    """Single, unified streaming event emitted by every worker.

    Both the image worker (ComfyUI progress/executing/success) and the LLM
    worker (SSE deltas/completed/tool-calls) translate their native stream
    into this one schema, so the backend needs a single reader + reducer pair
    instead of two divergent NDJSON dialects.

    event:
      started      job accepted, work beginning
      progress     coarse progress fraction (0..1) for image jobs
      delta        incremental token text for llm jobs
      node         a ComfyUI node started executing (image jobs)
      artifact     a finished output (image path / text)
      completed    terminal success (carries ``outputs``)
      failed       terminal failure (carries ``message``)
      cancelled    terminal cancellation
    """
    event: Literal[
        "started", "progress", "delta", "node", "cached_nodes", "artifact", "completed", "failed", "cancelled"
    ]
    job_id: Optional[str] = None
    seq: Optional[int] = None
    value: Optional[float] = None          # progress fraction 0..1
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


class CancelJobRequest(BaseModel):
    """Request for cancelling a running job."""
    job_id: str


class DownloadRequest(BaseModel):
    """Request for downloading a model file."""
    url: str
    path: str
    token: Optional[str] = None
    preview_url: Optional[str] = None
    metadata: Optional[Dict] = None
    info: Optional[Dict] = None  # Deprecated: use `metadata` instead. Kept for backwards compatibility.


class ListModelsRequest(BaseModel):
    """Request for listing models in a directory."""
    directory: str


class DeleteModelRequest(BaseModel):
    """Request for deleting a model file."""
    path: str


class DeleteFileRequest(BaseModel):
    """Request for deleting a file."""
    path: str


class UploadFileRequest(BaseModel):
    """Request for uploading a file to provider storage."""
    filename: str
    content_base64: str
    directory: str


class ValidateModelsRequest(BaseModel):
    """Request for validating models in one or more directories."""
    directory: Union[str, List[str]]
    delete_invalid: bool = False

    @property
    def directories(self) -> List[str]:
        """Normalized list of directories to validate."""
        return [self.directory] if isinstance(self.directory, str) else self.directory


class ReconcileRequest(BaseModel):
    """Request for reconciling models."""
    quick_sync: bool = False


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
]
