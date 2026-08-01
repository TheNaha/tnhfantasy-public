from typing import Any

from pydantic import BaseModel

# ============================================================================
# REQUEST MODELS
# ============================================================================

class AddModelRequest(BaseModel):
    """Request to add a model with selected versions."""
    civitai_data: dict[str, Any]  # Full CivitAI API response
    selected_versions: list[dict[str, Any]]  # [{version_id: str, is_default: bool}]


class UpdateProviderStatusRequest(BaseModel):
    """Request to update file status on a provider."""
    status: str  # pending, downloading, ready, failed
    storage_path: str | None = None
    size_bytes: int | None = None
    error_message: str | None = None


class SetDefaultVersionRequest(BaseModel):
    """Request to set default version."""
    version_id: str


class CheckInstalledBatchRequest(BaseModel):
    """Batch request for checking installed CivitAI models."""
    civitai_model_ids: list[int]


