"""
Shared Pydantic models for provider workers.
These models define the API contract for all provider worker endpoints.
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel


class InferenceRequest(BaseModel):
    """Request for running ComfyUI workflow inference."""
    workflow: Dict[str, Any]
    use_snapshot: bool = False
    job_id: Optional[str] = None
    timeout_seconds: Optional[float] = None


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


class UploadFileRequest(BaseModel):
    """Request for uploading a file to provider storage."""
    filename: str
    content_base64: str
    directory: str = "input"


class ValidateModelsRequest(BaseModel):
    """Request for validating models in a directory."""
    directory: str = "models/checkpoints"
    delete_invalid: bool = False


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
    "models/motion_modules",
]
