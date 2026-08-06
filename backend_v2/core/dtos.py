from datetime import datetime
from typing import Any

from pydantic import BaseModel

from core.entities import JobStatus


class JobQueueItem(BaseModel):
    """
    Lightweight DTO for job queue items.
    Excludes heavy workflow JSON to optimize queue polling.
    """
    id: str
    status: JobStatus
    created_at: datetime
    overall_progress: float = 0.0
    metadata_: dict[str, Any] = {}
    task_type: str = "image"
