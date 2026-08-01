# Core module exports
#
# The `core` package contains pure domain objects with no framework dependencies:
#   entities    – SQLModel ORM models (database tables)
#   entities_v2 – Normalized V2 schema for richer model metadata
#   dtos        – Lightweight data-transfer objects (not persisted)
#   events      – EventBus and typed event constants for real-time pub/sub
#   exceptions  – Typed exceptions mapped to HTTP status codes
#   workflow_parser – Extracts model references from ComfyUI workflow JSON
from .dtos import JobQueueItem
from .entities import (
    Collection,
    CollectionImage,
    Job,
    JobStatus,
    LoadBalancerState,
    LoadBalancingConfig,
    ModelFile,
    ModelImage,
    ModelTag,
    ModelType,
    ModelV2,
    ModelVersion,
    Prompt,
    Provider,
    ProviderFileStatus,
    ProviderVersionStatus,
)
from .events import (
    Event,
    EventBus,
    EventType,
    emit_download_event,
    emit_job_event,
    emit_provider_event,
    event_bus,
)
from .exceptions import (
    ComfyError,
    ConfigurationError,
    ContainerError,
    DownloadError,
    JobError,
    NotFoundError,
    ProviderError,
    ValidationError,
)
from .workflow_parser import (
    extract_models_from_workflow,
    get_all_required_files,
    get_required_storage_paths,
)

__all__ = [
    # V1 Entities
    "Job", "JobStatus",
    "Provider",
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
