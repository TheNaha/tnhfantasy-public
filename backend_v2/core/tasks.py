from typing import Any

from pydantic import BaseModel, Field


class UniversalTask(BaseModel):
    """
    Standardized task intent payload.
    Decouples the frontend's intent from the provider's specific execution runner.
    """
    task_type: str = Field(..., description="E.g., image, text, audio")
    intent: str = Field(..., description="E.g., generate, chat, transcribe")
    payload: dict[str, Any] = Field(default_factory=dict, description="The actual request data")
    config: dict[str, Any] | None = Field(default=None, description="Execution overrides")
