# Core module exports
#
# The `core` package contains pure domain objects with no framework dependencies:
#   entities    – SQLModel ORM models (database tables)
#   entities_v2 – Normalized V2 schema for richer model metadata
#   dtos        – Lightweight data-transfer objects (not persisted)
#   events      – EventBus and typed event constants for real-time pub/sub
#   exceptions  – Typed exceptions mapped to HTTP status codes
#   workflow_parser – Extracts model references from ComfyUI workflow JSON
from .entities import (
    Job, JobStatus,
    Provider,
    Download,
    LoadBalancingConfig, LoadBalancerState,
    Prompt,
    Collection, CollectionImage,
)
from .entities_v2 import (
    ModelV2, ModelVersion, ModelFile, ModelImage,
    ModelTag, ProviderVersionStatus,
    ModelType, ProviderFileStatus,
)
from .events import (
    Event, EventType, EventBus,
    event_bus,
    emit_job_event, emit_download_event, emit_provider_event
)
from .exceptions import (
    ComfyError,
    NotFoundError,
    ValidationError,
    ProviderError,
    ContainerError,
    JobError,
    DownloadError,
    ConfigurationError
)
from .dtos import JobQueueItem
from .workflow_parser import extract_models_from_workflow, get_all_required_files, get_required_storage_paths

__all__ = [
    # V1 Entities
    "Job", "JobStatus",
    "Provider",
    "Download",
    "LoadBalancingConfig", "LoadBalancerState",
    "Prompt",
    "Collection", "CollectionImage",
    # V2 Entities
    "ModelV2", "ModelVersion", "ModelFile", "ModelImage",
    "ModelTag", "ProviderVersionStatus",
    "ModelType", "ProviderFileStatus",
    # DTOs
    "JobQueueItem",
    # Events
    "Event", "EventType", "EventBus",
    "event_bus",
    "emit_job_event", "emit_download_event", "emit_provider_event",
    # Exceptions
    "ComfyError",
    "NotFoundError",
    "ValidationError",
    "ProviderError",
    "ContainerError",
    "JobError",
    "DownloadError",
    "ConfigurationError",
    # Workflow Parser
    "extract_models_from_workflow", "get_all_required_files", "get_required_storage_paths",
]
