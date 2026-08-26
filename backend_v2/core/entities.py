# Core domain entities as SQLModel models
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import JSON, Index, UniqueConstraint
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableList
from sqlmodel import Column, Field, Relationship, SQLModel
from pydantic import field_validator

# JSON stored as JSONB on PostgreSQL (indexable/queryable), plain JSON elsewhere.
JSONColumn = JSON().with_variant(JSONB(), "postgresql")


class JobStatus(str, Enum):
    """Job lifecycle states."""
    PENDING = "pending"
    RETRYING = "retrying"  # In backoff before re-attempting the same provider
    SENT_TO_PROVIDER = "sent-to-provider"
    CONNECTED = "connected"
    PRE_GENERATION = "pre-generation"
    GENERATING = "generating"
    COMPLETED = "completed"
    POST_PROCESSING = "post-processing"
    FAILED = "failed"
    CANCELLED = "cancelled"  # User-initiated cancellation


# Canonical worker/task type vocabulary. Anything else is rejected so
# ad-hoc values (e.g. "text") can't silently fall into the image queue.
VALID_TASK_TYPES = {"image", "llm"}


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
    task_type: str = Field(default="image")
    status: JobStatus = Field(default=JobStatus.PENDING)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    @field_validator("task_type")
    @classmethod
    def _validate_task_type(cls, value: str) -> str:
        if value not in VALID_TASK_TYPES:
            raise ValueError(f"task_type must be one of {sorted(VALID_TASK_TYPES)}, got {value!r}")
        return value
    
    # Timing for ETA calculation
    started_at: datetime | None = Field(default=None)  # When job started processing
    completed_at: datetime | None = Field(default=None)  # When job finished
    
    # Workflow data (ComfyUI workflow JSON)
    workflow: dict[str, Any] = Field(default={}, sa_column=Column(JSONColumn))
    
    # Metadata (prompt, seed, dimensions, etc.)
    metadata_: dict[str, Any] = Field(default={}, sa_column=Column(JSONColumn), alias="metadata")
    
    # Structured output entries produced by workers/post-processing.
    outputs: list[dict[str, Any]] = Field(default=[], sa_column=Column(JSONColumn))
    
    # Progress tracking
    progress: float = Field(default=0.0)
    overall_progress: float = Field(default=0.0)
    message: str | None = Field(default=None)
    error: str | None = Field(default=None)
    
    # Provider assignment
    provider_id: str | None = Field(default=None)

    # Claim marker for the Postgres-backed job queue (SELECT ... FOR UPDATE SKIP LOCKED).
    # Not NULL while a worker owns the job; cleared when processing finishes.
    claimed_at: datetime | None = Field(default=None)

    # Typed routing columns (backed by metadata_ JSON; populated on write, indexed for SQL queries).
    workspace: str | None = Field(default=None, index=True)
    character_id: str | None = Field(default=None, index=True)
    story_id: str | None = Field(default=None, index=True)
    source: str | None = Field(default=None, index=True)

    # Queue position (calculated, not stored)
    queue_position: int | None = Field(default=None)


class Provider(SQLModel, table=True):
    """
    Represents a serverless compute provider configuration.
    Image: Modal, Beam, direct_url. LLM: openai_compat, anthropic, google, modal_llm.
    """
    __tablename__ = "providers"
    
    id: str = Field(primary_key=True)  # e.g., "modal-primary", "modal-step"
    type: str = Field(default="modal")  # Provider type
    worker_type: str = Field(default="image")  # e.g., image, llm, audio
    enabled: bool = Field(default=True)
    priority: int = Field(default=1)  # Lower = higher priority

    @field_validator("worker_type")
    @classmethod
    def _validate_worker_type(cls, value: str) -> str:
        if value not in VALID_TASK_TYPES:
            raise ValueError(f"worker_type must be one of {sorted(VALID_TASK_TYPES)}, got {value!r}")
        return value
    
    # Credentials (stored securely, used for container env vars)
    credentials: dict[str, Any] = Field(default={}, sa_column=Column(JSONColumn))
    
    # Provider-specific config
    config: dict[str, Any] = Field(default={}, sa_column=Column(JSONColumn))
    
    # Container config for multi-profile mode
    container_config: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONColumn))



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
    provider_job_counts: dict[str, int] = Field(default={}, sa_column=Column(JSONColumn))
    provider_failures: dict[str, int] = Field(default={}, sa_column=Column(JSONColumn))
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
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(index=True)
    text: str  # Positive prompt
    negative: str | None = Field(default=None)
    category: str = Field(default="Custom")
    description: str | None = Field(default=None)
    tags: list[str] = Field(default=[], sa_column=Column(JSONColumn))
    favorite: bool = Field(default=False)
    usage_count: int = Field(default=0)
    
    # Full generation settings (optional, includes model, LoRAs, etc.)
    settings: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONColumn))
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# COLLECTIONS
# ============================================================================

class Collection(SQLModel, table=True):
    """Image collection/album for organizing generated images."""
    __tablename__ = "collections"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(index=True)
    color: str = Field(default="#3B82F6")
    description: str | None = Field(default=None)
    thumbnail: str | None = Field(default=None)  # First image filename
    character_id: str | None = Field(foreign_key="characters.id", default=None, index=True)  # Link to character for auto-generated galleries
    workspace: str | None = Field(default=None, index=True)  # Scope album to a workspace: 'image' | 'chat' | 'story' (issue #5)
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    character: Optional["Character"] = Relationship(back_populates="collections")
    images: list["CollectionImage"] = Relationship(
        back_populates="collection",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class CollectionImage(SQLModel, table=True):
    """Many-to-many relationship between collections and images."""
    __tablename__ = "collection_images"
    __table_args__ = (
        Index('idx_collection_image', 'collection_id', 'image_filename'),
    )
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    collection_id: str = Field(foreign_key="collections.id", index=True)
    image_filename: str = Field(index=True)  # References output filename
    added_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    collection: Optional["Collection"] = Relationship(back_populates="images")


class AssetKind(str, Enum):
    """Type of a stored asset."""
    IMAGE = "image"
    TEXT = "text"
    AUDIO = "audio"
    VIDEO = "video"


class Asset(SQLModel, table=True):
    """DB-backed index of a generated/interoperable asset on the filesystem.

    The filesystem remains the source of truth for bytes; this table is the
    fast, queryable index (replacing the in-memory GalleryIndexer). It enables
    workspace/character/story-scoped galleries, keyset pagination, and the
    future `/{user_id}/` partition without scanning thousands of files.
    """
    __tablename__ = "assets"
    __table_args__ = (
        Index("idx_asset_user_created", "user_id", "created_at"),
        Index("idx_asset_workspace", "user_id", "workspace", "created_at"),
        Index("idx_asset_character", "user_id", "character_id"),
        Index("idx_asset_story", "user_id", "story_id"),
        UniqueConstraint("relative_path", name="uq_assets_relative_path"),
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(default="default_user", index=True)
    filename: str = Field(index=True)
    relative_path: str  # path relative to OUTPUT_DIR, e.g. default_user/chat/2026/08/09/foo.png
    kind: AssetKind = Field(default=AssetKind.IMAGE)
    workspace: str = Field(default="main", index=True)
    character_id: str | None = Field(default=None, index=True)
    story_id: str | None = Field(default=None, index=True)
    job_id: str | None = Field(default=None, index=True)
    width: int | None = Field(default=None)
    height: int | None = Field(default=None)
    blurhash: str | None = Field(default=None)
    thumbnail_relative_path: str | None = Field(default=None)
    metadata_: dict | None = Field(default=None, sa_column=Column(JSONColumn))
    generated_at: datetime | None = Field(default=None, index=True)  # image creation time (from PNG meta or mtime)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: datetime | None = Field(default=None, index=True)  # soft delete


# Core domain entities for normalized model metadata (V2 Schema)
# Replaces flat metadata_ JSON with proper relational tables
from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Text


class ModelType(str, Enum):
    """CivitAI model types."""
    CHECKPOINT = "Checkpoint"
    LORA = "LORA"
    LOCON = "LoCon"
    TEXTUAL_INVERSION = "TextualInversion"
    HYPERNETWORK = "Hypernetwork"
    CONTROLNET = "Controlnet"
    VAE = "VAE"
    UPSCALER = "Upscaler"
    MOTION_MODULE = "MotionModule"
    POSES = "Poses"
    WILDCARDS = "Wildcards"
    OTHER = "Other"


class ProviderFileStatus(str, Enum):
    """Download status for a file on a provider."""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    READY = "ready"
    FAILED = "failed"
    DELETING = "deleting"


# ============================================================================
# BASE MODEL
# ============================================================================

class ModelV2(SQLModel, table=True):
    """
    Base model - represents a CivitAI/HuggingFace model.
    This is the "parent" entity that groups all versions together.
    """
    __tablename__ = "models_v2"
    __table_args__ = (
        UniqueConstraint('civitai_model_id', name='uq_civitai_model_id'),
    )
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    civitai_model_id: int | None = Field(default=None, index=True)
    
    # Basic info
    name: str = Field(index=True)  # Model display name
    type: str = Field(index=True)  # Checkpoint, LORA, ControlNet, etc.
    directory: str = Field(index=True)  # ComfyUI directory: checkpoints, loras, etc.
    description: str | None = Field(default=None, sa_column=Column(Text))
    
    # NSFW/Safety
    nsfw: bool = Field(default=False)
    nsfw_level: int = Field(default=1)
    
    # Creator info
    creator_username: str | None = Field(default=None, index=True)
    creator_image: str | None = None
    
    # Stats (cached, can be refreshed periodically)
    stats_downloads: int = Field(default=0)
    stats_thumbs_up: int = Field(default=0)
    stats_thumbs_down: int = Field(default=0)
    stats_comments: int = Field(default=0)
    stats_updated_at: datetime | None = None
    
    # Source tracking
    source: str = Field(default="civitai")  # civitai, huggingface, custom
    source_url: str | None = None  # Original URL for reference
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Relationships (for eager loading)
    versions: list["ModelVersion"] = Relationship(
        back_populates="model",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    tags: list["ModelTag"] = Relationship(
        back_populates="model",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


# ============================================================================
# MODEL VERSION
# ============================================================================

class ModelVersion(SQLModel, table=True):
    """
    A specific version of a model.
    Only versions explicitly selected by the user are stored.
    """
    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint('civitai_version_id', name='uq_civitai_version_id'),
        Index('idx_version_model', 'model_id'),
    )
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    model_id: str = Field(foreign_key="models_v2.id", index=True)
    civitai_version_id: int | None = Field(default=None, index=True)
    
    # Version info
    name: str  # "v1.0", "v2.0-inpainting", etc.
    base_model: str | None = None  # "SDXL", "SD1.5", "Illustrious", "Pony"
    base_model_type: str | None = None  # "Standard", "Inpainting", "Turbo"
    description: str | None = Field(default=None, sa_column=Column(Text))
    
    # User selection state
    is_enabled: bool = Field(default=True)  # User can disable without deleting
    is_default: bool = Field(default=False)  # Default version for generation
    
    # LoRA-specific: trigger words (stored as JSON array string)
    trained_words: str | None = None
    
    # Timestamps from CivitAI
    civitai_created_at: datetime | None = None
    civitai_published_at: datetime | None = None
    
    # Local timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Relationships
    model: Optional["ModelV2"] = Relationship(back_populates="versions")
    files: list["ModelFile"] = Relationship(
        back_populates="version",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    images: list["ModelImage"] = Relationship(
        back_populates="version",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


# ============================================================================
# MODEL FILE
# ============================================================================

class ModelFile(SQLModel, table=True):
    """
    Individual file within a model version.
    Models can have multiple files (e.g., model + config, fp16 + fp32).
    """
    __tablename__ = "model_files"
    __table_args__ = (
        Index('idx_file_version', 'version_id'),
    )
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    version_id: str = Field(foreign_key="model_versions.id", index=True)
    civitai_file_id: int | None = Field(default=None, index=True)
    
    # File info
    original_filename: str  # Original filename from source
    storage_filename: str  # Computed: {model}_{version}_{id}.safetensors
    size_kb: float = Field(default=0.0)
    format: str | None = None  # SafeTensor, PickleTensor, Diffusers, etc.
    
    # Hashes for integrity verification
    hash_sha256: str | None = None
    hash_autov2: str | None = None
    hash_blake3: str | None = None
    hash_crc32: str | None = None
    
    # Download URL (with token placeholder)
    download_url: str | None = None
    
    # File type
    is_primary: bool = Field(default=True)  # Primary model file for this version
    file_type: str = Field(default="Model")  # Model, Config, VAE, etc.
    
    # Relationships
    version: Optional["ModelVersion"] = Relationship(back_populates="files")
    provider_statuses: list["ProviderVersionStatus"] = Relationship(
        back_populates="file",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


# ============================================================================
# MODEL IMAGE
# ============================================================================

class ModelImage(SQLModel, table=True):
    """
    Preview/example images for a model version.
    Used for display in Model Manager and search results.
    """
    __tablename__ = "model_images"
    __table_args__ = (
        Index('idx_image_version', 'version_id'),
    )
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    version_id: str = Field(foreign_key="model_versions.id", index=True)
    
    # Image data
    url: str
    width: int | None = None
    height: int | None = None
    blurhash: str | None = None  # For progressive loading
    
    # Type and safety
    type: str = Field(default="image")  # image, video
    nsfw_level: int = Field(default=1)  # 1=SFW, higher=NSFW
    
    # Metadata flags
    has_meta: bool = Field(default=False)  # Has generation metadata
    has_positive_prompt: bool = Field(default=False)
    
    # Sort order (first image is primary)
    sort_order: int = Field(default=0)
    
    # Relationships
    version: Optional["ModelVersion"] = Relationship(back_populates="images")


# ============================================================================
# PROVIDER VERSION STATUS
# ============================================================================

class ProviderVersionStatus(SQLModel, table=True):
    """
    Tracks download status of a specific file on a specific provider.
    This is the key table for reconciliation.
    """
    __tablename__ = "provider_version_status"
    __table_args__ = (
        Index('idx_file_provider_id_unique', 'file_id', 'provider_id', unique=True),
        Index('idx_provider_status_provider_id', 'provider_id', 'status'),
    )
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    file_id: str = Field(foreign_key="model_files.id", index=True)
    provider_id: str | None = Field(default=None, index=True)
    
    # Status tracking
    status: str = Field(default="pending")  # pending, downloading, ready, failed
    storage_path: str | None = None  # Actual path on provider storage
    size_bytes: int | None = Field(default=None, sa_type=BigInteger)  # Actual size after download
    
    # Timestamps
    queued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    downloaded_at: datetime | None = None
    verified_at: datetime | None = None  # Last integrity check
    
    # Error tracking
    error_message: str | None = None
    retry_count: int = Field(default=0)
    
    # Relationships
    file: Optional["ModelFile"] = Relationship(back_populates="provider_statuses")


# ============================================================================
# MODEL TAG
# ============================================================================

class ModelTag(SQLModel, table=True):
    """
    Tags for model searchability.
    Normalized from CivitAI tags array.
    """
    __tablename__ = "model_tags"
    __table_args__ = (
        UniqueConstraint('model_id', 'tag', name='uq_model_tag'),
        Index('idx_tag_search', 'tag'),
    )
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    model_id: str = Field(foreign_key="models_v2.id", index=True)
    tag: str = Field(index=True)
    
    # Relationships
    model: Optional["ModelV2"] = Relationship(back_populates="tags")


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_directory_from_type(model_type: str, base_model: str = None) -> str:
    """
    Map CivitAI model type to ComfyUI directory.
    
    Args:
        model_type: CivitAI model type (e.g., "Checkpoint", "LORA")
        base_model: Optional base model string (e.g., "Flux.1 D", "SDXL")
        
    Returns:
        ComfyUI directory name
    """
    # Special case: Flux "Checkpoints" are actually UNETs
    if model_type == "Checkpoint" and base_model and is_unet_only_model(base_model):
        return "unet"
    
    type_to_dir = {
        "Checkpoint": "checkpoints",
        "LORA": "loras",
        "LoCon": "loras",
        "TextualInversion": "embeddings",
        "Hypernetwork": "hypernetworks",
        "Controlnet": "controlnet",
        "VAE": "vae",
        "Upscaler": "upscale_models",
        "MotionModule": "motion_modules",
        "Poses": "poses",
        "Wildcards": "wildcards",
    }
    return type_to_dir.get(model_type, "other")


def compute_storage_filename(
    model_name: str,
    version_name: str,
    version_id: int,
    original_filename: str
) -> str:
    """
    Compute standardized storage filename to avoid conflicts.
    Format: {sanitized_model}_{sanitized_version}_{version_id}.{ext}
    """
    import re
    
    # Sanitize names (remove special chars, replace spaces with underscores)
    def sanitize(s: str) -> str:
        s = re.sub(r'[^\w\s-]', '', s)
        s = re.sub(r'[\s]+', '_', s)
        return s.lower()[:30]  # Limit length
    
    # Get extension from original filename
    ext = original_filename.rsplit('.', 1)[-1] if '.' in original_filename else 'safetensors'
    
    model_part = sanitize(model_name)
    version_part = sanitize(version_name)
    
    return f"{model_part}_{version_part}_{version_id}.{ext}"


# ============================================================================
# UNET-ONLY MODEL DETECTION
# ============================================================================

# Base models that are UNET-only (require separate CLIP and VAE)
UNET_ONLY_BASE_MODELS = [
    # Flux family
    "Flux.1 D",
    "Flux.1 S", 
    "Flux.2",
    "Flux",
    # AuraFlow (DiT-based, may lack CLIP)
    "AuraFlow",
]


def is_unet_only_model(base_model: str) -> bool:
    """
    Check if a model is UNET-only based on its base_model.
    
    UNET-only models require separate CLIP and VAE loaders.
    """
    if not base_model:
        return False
    
    # Normalize for comparison
    base_lower = base_model.lower().strip()
    
    for unet_base in UNET_ONLY_BASE_MODELS:
        if unet_base.lower() in base_lower or base_lower.startswith("flux") or base_lower.startswith("aura"):
            return True
    
    return False


# Default components for UNET-only architectures
FLUX_DEFAULT_COMPONENTS = {
    "clip": [
        {
            "name": "t5xxl_fp16.safetensors",
            "url": "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors",
            "directory": "clip",
            "size_mb": 9787,
            "description": "T5-XXL Text Encoder (FP16) - Required for Flux"
        },
        {
            "name": "clip_l.safetensors",
            "url": "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors",
            "directory": "clip",
            "size_mb": 246,
            "description": "CLIP-L Text Encoder - Required for Flux"
        }
    ],
    "vae": [
        {
            "name": "ae.safetensors",
            "url": "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors",
            "directory": "vae",
            "size_mb": 335,
            "description": "Flux VAE (Autoencoder) - From Kijai/flux-fp8 mirror"
        }
    ]
}

# Default components for AuraFlow (uses SDXL VAE + T5)
AURAFLOW_DEFAULT_COMPONENTS = {
    "clip": [
        {
            "name": "pile_t5xl.safetensors",
            "url": "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors",
            "directory": "clip",
            "size_mb": 9787,
            "description": "T5-XL Text Encoder - Required for AuraFlow"
        }
    ],
    "vae": [
        {
            "name": "sdxl_vae.safetensors",
            "url": "https://huggingface.co/stabilityai/sdxl-vae/resolve/main/sdxl_vae.safetensors",
            "directory": "vae",
            "size_mb": 335,
            "description": "SDXL VAE - Required for AuraFlow"
        }
    ]
}



# Popular VAE options by style
POPULAR_VAE_OPTIONS = {
    "anime": [
        {
            "name": "kl-f8-anime2.safetensors",
            "url": "https://huggingface.co/hakurei/waifu-diffusion-v1-4/resolve/main/vae/kl-f8-anime2.ckpt",
            "description": "Waifu Diffusion VAE - Vibrant anime colors"
        },
        {
            "name": "orangemix.vae.pt", 
            "url": "https://huggingface.co/WarriorMama777/OrangeMixs/resolve/main/VAEs/orangemix.vae.pt",
            "description": "OrangeMix VAE - Anime style"
        }
    ],
    "realistic": [
        {
            "name": "vae-ft-mse-840000-ema-pruned.safetensors",
            "url": "https://huggingface.co/stabilityai/sd-vae-ft-mse-original/resolve/main/vae-ft-mse-840000-ema-pruned.safetensors",
            "description": "Stability AI MSE VAE - Best for realistic images"
        }
    ],
    "sdxl": [
        {
            "name": "sdxl_vae.safetensors",
            "url": "https://huggingface.co/stabilityai/sdxl-vae/resolve/main/sdxl_vae.safetensors",
            "description": "Official SDXL VAE"
        },
        {
            "name": "sdxl-vae-fp16-fix.safetensors",
            "url": "https://huggingface.co/madebyollin/sdxl-vae-fp16-fix/resolve/main/sdxl_vae.safetensors",
            "description": "SDXL VAE FP16 Fix - More stable"
        }
    ]
}

class DeletedFileTombstone(SQLModel, table=True):
    __tablename__ = "deleted_file_tombstones"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    storage_path: str = Field(index=True, unique=True)
    deleted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# WORLD VAULT (ROLEPLAY & STORY)
# ============================================================================

class VoiceModel(SQLModel, table=True):
    __tablename__ = "voice_models"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(index=True)
    description: str | None = Field(default=None, sa_column=Column(Text))
    type: str = Field(default="xtts")  # "xtts", "bark", "embedding"
    voice_profile: str | None = Field(default=None)  # Profile name or speaker reference
    model_path: str | None = Field(default=None)  # Path to model files
    language: str | None = Field(default=None)  # e.g. "en", "ja"
    preview_text: str | None = Field(default=None, sa_column=Column(Text))
    preview_path: str | None = Field(default=None)  # Audio file produced by a preview TTS job
    character_id: str | None = Field(foreign_key="characters.id", default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    character: Optional["Character"] = Relationship(
        back_populates="voice_models",
        sa_relationship_kwargs={"foreign_keys": "VoiceModel.character_id"},
    )


class Character(SQLModel, table=True):
    __tablename__ = "characters"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(index=True)
    description: str | None = Field(default=None, sa_column=Column(Text))
    personality: str | None = Field(default=None, sa_column=Column(Text))
    scenario: str | None = Field(default=None, sa_column=Column(Text))
    first_mes: str | None = Field(default=None, sa_column=Column(Text))
    mes_example: str | None = Field(default=None, sa_column=Column(Text))
    creator_notes: str | None = Field(default=None, sa_column=Column(Text))
    system_prompt: str | None = Field(default=None, sa_column=Column(Text))
    # Extra instructions appended after the character's main system prompt
    append_system_prompt: str | None = Field(default=None, sa_column=Column(Text))
    # Suggested user persona when chatting with this character
    suggested_persona: str | None = Field(default=None, sa_column=Column(Text))
    
    visual_tags: list[str] = Field(default=[], sa_column=Column(JSONColumn))
    lora_triggers: list[str] | None = Field(default=None, sa_column=Column(JSONColumn))
    voice_profile: str | None = Field(default=None) # Optional voice model profile
    voice_model_id: str | None = Field(foreign_key="voice_models.id", default=None, index=True)
    alternate_greetings: list[str] | None = Field(default=None, sa_column=Column(JSONColumn))
    expressions: dict[str, str] | None = Field(default=None, sa_column=Column(JSONColumn))  # emotion name → avatar_path
    expressions_lora: list[str] | None = Field(default=None, sa_column=Column(JSONColumn))  # LORA triggers per expression
    
    # Generation Settings
    checkpoint: str | None = Field(default=None)
    lora: str | None = Field(default=None)
    
    # World Context
    default_time: str | None = Field(default=None)
    default_location: str | None = Field(default=None)
    
    avatar_path: str | None = Field(default=None)
    sort_order: int = Field(default=0, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    collections: list["Collection"] = Relationship(
        back_populates="character",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    chats: list["Chat"] = Relationship(
        back_populates="character",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    voice_models: list["VoiceModel"] = Relationship(
        back_populates="character",
        sa_relationship_kwargs={"foreign_keys": "VoiceModel.character_id"},
    )
    memories: list["CharacterMemory"] = Relationship(
        back_populates="character",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

class Chat(SQLModel, table=True):
    __tablename__ = "chats"
    __table_args__ = (Index('idx_chat_type', 'chat_type'),)
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    character_id: str | None = Field(foreign_key="characters.id", default=None, index=True)
    name: str = Field(default="New Chat")
    chat_type: str = Field(default="chat") # "chat" or "story"
    persona_name: str | None = Field(default=None) # Used for {{user}} substitutions
    additional_character_ids: list[str] = Field(default=[], sa_column=Column(JSONColumn))
    story_time: str | None = Field(default=None)
    story_location: str | None = Field(default=None)
    location_id: str | None = Field(default=None, foreign_key="locations.id", index=True)  # Links to a Location entity
    llm_model: str | None = Field(default=None) # Per-chat LLM model override (falls back to global default)
    allow_image_generation: bool = Field(default=True) # Gates the agentic generate_image tool
    allow_narration: bool = Field(default=True) # Gates the agentic narrate_scene tool
    idle_sim_enabled: bool = Field(default=False) # Opt-in idle simulation: background cron keeps the scene alive
    # Tiered system-prompt customisation:
    #   system_prompt_override — replaces EVERYTHING (character prompt + all blocks).
    #   append_system_prompt   — appended after the character block, before global roleplay_default.
    # Priority: override > (character_prompt + char.append) > chat.append > roleplay_default
    system_prompt_override: str | None = Field(default=None, sa_column=Column(Text))
    append_system_prompt: str | None = Field(default=None, sa_column=Column(Text))
    # Per-chat LLM context window in tokens (None → use global setting → 4096 fallback)
    max_context_tokens: int | None = Field(default=None)
    # Per-chat agentic loop depth limit (None → use global MAX_AGENTIC_DEPTH)
    max_agentic_depth: int | None = Field(default=None)
    # Per-chat LLM sampling overrides (None → global defaults from settings)
    temperature: float | None = Field(default=None)
    top_p: float | None = Field(default=None)
    max_output_tokens: int | None = Field(default=None)
    frequency_penalty: float | None = Field(default=None)
    presence_penalty: float | None = Field(default=None)
    # Per-chat TTS voice override (None → character voice → server default)
    tts_voice_id: str | None = Field(default=None, foreign_key="voice_models.id", index=True)
    # Per-chat user persona description injected into the system prompt
    persona_description: str | None = Field(default=None, sa_column=Column(Text))
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    active_lorebook_ids: list[str] = Field(default=[], sa_column=Column(JSONColumn))

    character: Optional["Character"] = Relationship(back_populates="chats")
    messages: list["Message"] = Relationship(
        back_populates="chat",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

class MessageRole(str, Enum):
    USER = "user"
    CHAR = "char"
    SYSTEM = "system"
    STORY = "story"


class MessageKind(str, Enum):
    """Semantic classification of a message, orthogonal to `role`.

    `role` carries the speaker (user/char/system/story). `kind` carries *what
    the message is* so the context builder and UI can treat narrator turns,
    generated images, and tool-call transcripts differently without abusing
    `role=SYSTEM` (which previously made them exempt from context pruning and
    silently ate the whole context window).
    """
    USER = "user"
    CHAR = "char"
    SYSTEM = "system"
    NARRATOR = "narrator"
    IMAGE = "image"
    TOOL = "tool"


class Message(SQLModel, table=True):
    __tablename__ = "messages"
    __table_args__ = (
        Index('idx_message_chat_id', 'chat_id'),
        Index('idx_message_chat_created', 'chat_id', 'created_at'),
    )
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    chat_id: str = Field(foreign_key="chats.id", index=True)
    role: MessageRole
    kind: MessageKind | None = Field(
        default=None,
        sa_column=Column(
            SQLEnum(MessageKind, values_callable=lambda e: [m.value for m in e], native_enum=False),
            index=True,
        ),
    )
    content: str = Field(sa_column=Column(Text))
    image_path: str | None = Field(default=None)
    # Speaking character for group chats (None = narrator/user/primary-agnostic)
    character_id: str | None = Field(default=None, foreign_key="characters.id", index=True)
    tool_calls: dict | None = Field(default=None, sa_column=Column(JSONColumn))
    message_metadata: dict | None = Field(default=None, sa_column=Column(JSONColumn))
    pinned: bool = Field(default=False)
    # Branching / timeline support
    parent_id: str | None = Field(default=None, foreign_key="messages.id", index=True, description="Parent message this is a reply/alternate of")
    branch_id: str | None = Field(default=None, index=True, description="UUID grouping messages within the same conversation branch")
    branch_name: str | None = Field(default=None, description="Human-readable branch label, e.g. 'Original', 'Branch 1'")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    chat: Optional["Chat"] = Relationship(back_populates="messages")
    children: list["Message"] = Relationship(
        sa_relationship_kwargs={"remote_side": "Message.id"},
        back_populates="parent",
    )
    parent: Optional["Message"] = Relationship(back_populates="children")


class CharacterMemory(SQLModel, table=True):
    __tablename__ = "character_memories"
    __table_args__ = (
        Index('idx_character_memory_char', 'character_id'),
        Index('idx_character_memory_accessed', 'last_accessed_at'),
    )
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    character_id: str = Field(foreign_key="characters.id", index=True)
    content: str = Field(sa_column=Column(Text))
    embedding: list[float] | None = Field(default=None, sa_column=Column(Vector(384)))
    tags: list[str] = Field(default=[], sa_column=Column(JSONColumn))
    importance: int = Field(default=5, ge=1, le=10)
    last_accessed_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    character: Optional["Character"] = Relationship(back_populates="memories")

class Lorebook(SQLModel, table=True):
    __tablename__ = "lorebooks"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(index=True)
    description: str | None = Field(default=None, sa_column=Column(Text))
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Relationships
    entries: list["LorebookEntry"] = Relationship(
        back_populates="lorebook",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

class LorebookEntry(SQLModel, table=True):
    __tablename__ = "lorebook_entries"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    lorebook_id: str = Field(foreign_key="lorebooks.id", index=True)
    
    # Trigger words or keys for this entry
    keys: list[str] = Field(default=[], sa_column=Column(JSONColumn))
    content: str = Field(sa_column=Column(Text))
    
    # 384 dimensions for all-MiniLM-L6-v2 (CPU optimized)
    embedding: list[float] | None = Field(default=None, sa_column=Column(Vector(384)))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    lorebook: Optional["Lorebook"] = Relationship(back_populates="entries")

class Scenario(SQLModel, table=True):
    __tablename__ = "scenarios"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(index=True)
    description: str | None = Field(default=None, sa_column=Column(Text))
    prompt_template: str = Field(sa_column=Column(Text))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Story(SQLModel, table=True):
    __tablename__ = "stories"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    title: str = Field(index=True)
    description: str | None = Field(default=None, sa_column=Column(Text))
    genre: str | None = Field(default=None)  # e.g., "fantasy", "sci-fi", "horror"
    # World Vault associations
    character_ids: list[str] = Field(default=[], sa_column=Column(JSONColumn))  # protagonist characters
    lorebook_ids: list[str] = Field(default=[], sa_column=Column(JSONColumn))  # active lorebooks
    location_ids: list[str] = Field(default=[], sa_column=Column(JSONColumn))  # active locations
    scenario_id: str | None = Field(default=None)  # base scenario
    llm_model: str | None = Field(default=None)  # Per-story LLM model override
    memory: str | None = Field(default=None, sa_column=Column(Text))  # Global author's note / story memory
    # Story state
    is_archived: bool = Field(default=False)
    # Per-story agentic loop depth limit (None → use global MAX_AGENTIC_DEPTH)
    max_agentic_depth: int | None = Field(default=None)
    # Per-story LLM sampling overrides (None → global defaults from settings)
    temperature: float | None = Field(default=None)
    top_p: float | None = Field(default=None)
    max_output_tokens: int | None = Field(default=None)
    frequency_penalty: float | None = Field(default=None)
    presence_penalty: float | None = Field(default=None)
    # Writing preferences
    word_count_goal: int | None = Field(default=None)  # optional target length for progress tracking
    pov: str | None = Field(default=None)  # narration perspective: first | second | third
    # Publishing / export
    published_token: str | None = Field(default=None, index=True)
    is_published: bool = Field(default=False)
    published_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    chapters: list["StoryChapter"] = Relationship(
        back_populates="story",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    __table_args__ = (Index('idx_story_updated', 'updated_at'),)

class StoryBeatRole(str, Enum):
    NARRATOR = "narrator"  # AI-generated story prose
    USER = "user"          # Player/user input
    SYSTEM = "system"      # System injections (scene breaks, etc.)

class StoryChapter(SQLModel, table=True):
    __tablename__ = "story_chapters"
    __table_args__ = (Index('idx_chapter_story_id', 'story_id'),)
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    story_id: str = Field(foreign_key="stories.id", index=True)
    chapter_number: int = Field(default=1)
    title: str | None = Field(default=None)
    # Full chapter content as accumulated prose (snapshot)
    content: str = Field(default="", sa_column=Column(Text))
    # Individual beats/turns within the chapter
    # MutableList tracks in-place appends (JSON columns don't by default).
    # A fresh JSON type is used so as_mutable() does not poison the shared JSONColumn.
    beats: list[dict[str, Any]] = Field(default=[], sa_column=Column(MutableList.as_mutable(JSON().with_variant(JSONB(), "postgresql"))))
    # Images generated for this chapter
    image_paths: list[str] = Field(default=[], sa_column=Column(JSONColumn))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    story: Optional["Story"] = Relationship(back_populates="chapters")

class StoryChapterRevision(SQLModel, table=True):
    """Immutable point-in-time snapshot of a chapter's prose."""
    __tablename__ = "story_chapter_revisions"
    __table_args__ = (Index('idx_revision_chapter_id', 'chapter_id'),)
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    chapter_id: str = Field(foreign_key="story_chapters.id", index=True)
    story_id: str = Field(foreign_key="stories.id", index=True)
    content: str = Field(default="", sa_column=Column(Text))
    # manual | pre_retry | pre_beat_edit | pre_beat_delete | pre_restore
    source: str = Field(default="manual")
    word_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Location(SQLModel, table=True):
    __tablename__ = "locations"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(index=True)
    description: str | None = Field(default=None, sa_column=Column(Text))
    atmosphere: str | None = Field(default=None, sa_column=Column(Text))
    tags: list[str] = Field(default=[], sa_column=Column(JSONColumn))
    image_path: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Campaign(SQLModel, table=True):
    __tablename__ = "campaigns"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(index=True)
    description: str | None = Field(default=None, sa_column=Column(Text))
    character_ids: list[str] = Field(default=[], sa_column=Column(JSONColumn))
    story_ids: list[str] = Field(default=[], sa_column=Column(JSONColumn))
    chat_ids: list[str] = Field(default=[], sa_column=Column(JSONColumn))
    location_ids: list[str] = Field(default=[], sa_column=Column(JSONColumn))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GraphLayout(SQLModel, table=True):
    __tablename__ = "graph_layouts"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(default="default", index=True)
    entity_type: str = Field(index=True)  # "character", "story", "chat", "lorebook", "location", "voice"
    entity_id: str = Field(index=True)
    x: float = Field(default=0.0)
    y: float = Field(default=0.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index('idx_graph_layout_name_entity', 'name', 'entity_type', 'entity_id', unique=True),
    )

