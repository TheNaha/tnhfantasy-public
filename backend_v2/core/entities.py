# Core domain entities as SQLModel models
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON, Index
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from enum import Enum
import uuid


class JobStatus(str, Enum):
    """Job lifecycle states."""
    PENDING = "pending"
    SENT_TO_PROVIDER = "sent-to-provider"
    CONNECTED = "connected"
    PRE_GENERATION = "pre-generation"
    GENERATING = "generating"
    RUNNING = "running"
    COMPLETED = "completed"
    POST_PROCESSING = "post-processing"
    FAILED = "failed"
    CANCELLED = "cancelled"  # User-initiated cancellation


class Job(SQLModel, table=True):
    """
    Represents a ComfyUI workflow execution job.
    Migrated from JSON file storage to SQLite.
    """
    __tablename__ = "jobs"
    __table_args__ = (
        # Composite index for listing jobs by status (dashboard queries)
        Index('idx_job_status_created', 'status', 'created_at'),
        # Composite index for provider-specific queries (load balancer)
        Index('idx_job_provider_status', 'provider_id', 'status'),
    )
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    status: JobStatus = Field(default=JobStatus.PENDING)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Timing for ETA calculation
    started_at: Optional[datetime] = Field(default=None)  # When job started processing
    completed_at: Optional[datetime] = Field(default=None)  # When job finished
    
    # Workflow data (ComfyUI workflow JSON)
    workflow: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    
    # Metadata (prompt, seed, dimensions, etc.)
    metadata_: Dict[str, Any] = Field(default={}, sa_column=Column(JSON), alias="metadata")
    
    # Structured output entries produced by workers/post-processing.
    outputs: List[Dict[str, Any]] = Field(default=[], sa_column=Column(JSON))
    
    # Progress tracking
    progress: float = Field(default=0.0)
    overall_progress: float = Field(default=0.0)
    message: Optional[str] = Field(default=None)
    error: Optional[str] = Field(default=None)
    
    # Provider assignment
    provider_id: Optional[str] = Field(default=None)
    
    # Queue position (calculated, not stored)
    queue_position: Optional[int] = Field(default=None, exclude=True)


class Provider(SQLModel, table=True):
    """
    Represents a serverless compute provider configuration.
    Currently supports Modal, extensible to Beam, RunPod, etc.
    """
    __tablename__ = "providers"
    
    id: str = Field(primary_key=True)  # e.g., "modal-primary", "modal-step"
    type: str = Field(default="modal")  # Provider type
    enabled: bool = Field(default=True)
    priority: int = Field(default=1)  # Lower = higher priority
    
    # Credentials (stored securely, used for container env vars)
    credentials: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    
    # Provider-specific config
    config: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    
    # Container config for multi-profile mode
    container_config: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))



class LoadBalancingConfig(SQLModel, table=True):
    """Load balancing configuration singleton."""
    __tablename__ = "load_balancing_config"
    
    id: int = Field(default=1, primary_key=True)
    strategy: str = Field(default="round-robin")  # round-robin, random, priority
    fallback_enabled: bool = Field(default=True)


class LoadBalancerState(SQLModel, table=True):
    """
    Persistent state for load balancer.
    Tracks round-robin index and per-provider statistics.
    """
    __tablename__ = "load_balancer_state"
    
    id: int = Field(default=1, primary_key=True)
    round_robin_index: int = Field(default=0)
    provider_job_counts: Dict[str, int] = Field(default={}, sa_column=Column(JSON))
    provider_failures: Dict[str, int] = Field(default={}, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# PROMPT LIBRARY
# ============================================================================

class Prompt(SQLModel, table=True):
    """
    Saved prompt template with full generation settings.
    Migrated from localStorage to server-side for cross-device sync and FTS5 search.
    """
    __tablename__ = "prompts"
    __table_args__ = (
        Index('idx_prompt_category', 'category'),
        Index('idx_prompt_favorite', 'favorite'),
    )
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    text: str  # Positive prompt
    negative: Optional[str] = Field(default=None)
    category: str = Field(default="Custom")
    description: Optional[str] = Field(default=None)
    tags: List[str] = Field(default=[], sa_column=Column(JSON))
    favorite: bool = Field(default=False)
    usage_count: int = Field(default=0)
    
    # Full generation settings (optional, includes model, LoRAs, etc.)
    settings: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# COLLECTIONS
# ============================================================================

class Collection(SQLModel, table=True):
    """Image collection/album for organizing generated images."""
    __tablename__ = "collections"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    color: str = Field(default="#3B82F6")
    description: Optional[str] = Field(default=None)
    thumbnail: Optional[str] = Field(default=None)  # First image filename
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CollectionImage(SQLModel, table=True):
    """Many-to-many relationship between collections and images."""
    __tablename__ = "collection_images"
    __table_args__ = (
        Index('idx_collection_image', 'collection_id', 'image_filename'),
    )
    
    id: Optional[int] = Field(default=None, primary_key=True)
    collection_id: int = Field(foreign_key="collections.id", index=True)
    image_filename: str = Field(index=True)  # References output filename
    added_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

