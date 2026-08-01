from typing import Dict, Any, Optional, List
from pydantic import BaseModel

# ============================================================================
# REQUEST MODELS
# ============================================================================

class AddModelRequest(BaseModel):
    """Request to add a model with selected versions."""
    civitai_data: Dict[str, Any]  # Full CivitAI API response
    selected_versions: List[Dict[str, Any]]  # [{version_id: str, is_default: bool}]


class UpdateProviderStatusRequest(BaseModel):
    """Request to update file status on a provider."""
    status: str  # pending, downloading, ready, failed
    storage_path: Optional[str] = None
    size_bytes: Optional[int] = None
    error_message: Optional[str] = None


class SetDefaultVersionRequest(BaseModel):
    """Request to set default version."""
    version_id: str


class CheckInstalledBatchRequest(BaseModel):
    """Batch request for checking installed CivitAI models."""
    civitai_model_ids: List[int]


