from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime
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
    metadata_: Dict[str, Any] = {}
