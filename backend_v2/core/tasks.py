from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

class UniversalTask(BaseModel):
    """
    Standardized task intent payload.
    Decouples the frontend's intent from the provider's specific execution runner.
    """
    task_type: str = Field(..., description="E.g., image, text, audio")
    intent: str = Field(..., description="E.g., generate, chat, transcribe")
    payload: Dict[str, Any] = Field(default_factory=dict, description="The actual request data")
    config: Optional[Dict[str, Any]] = Field(default=None, description="Execution overrides")
