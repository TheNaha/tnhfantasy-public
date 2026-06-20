# Core domain entities for normalized model metadata (V2 Schema)
# Replaces flat metadata_ JSON with proper relational tables
from sqlmodel import SQLModel, Field, Column, Relationship
from sqlalchemy import JSON, Index, UniqueConstraint, Text
from typing import Optional, Dict, Any, List, TYPE_CHECKING
from datetime import datetime, timezone
from enum import Enum

if TYPE_CHECKING:
    from typing import List as TypeList


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
    
    id: Optional[int] = Field(default=None, primary_key=True)
    civitai_model_id: Optional[int] = Field(default=None, index=True)
    
    # Basic info
    name: str = Field(index=True)  # Model display name
    type: str = Field(index=True)  # Checkpoint, LORA, ControlNet, etc.
    directory: str = Field(index=True)  # ComfyUI directory: checkpoints, loras, etc.
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    
    # NSFW/Safety
    nsfw: bool = Field(default=False)
    nsfw_level: int = Field(default=1)
    
    # Creator info
    creator_username: Optional[str] = Field(default=None, index=True)
    creator_image: Optional[str] = None
    
    # Stats (cached, can be refreshed periodically)
    stats_downloads: int = Field(default=0)
    stats_thumbs_up: int = Field(default=0)
    stats_thumbs_down: int = Field(default=0)
    stats_comments: int = Field(default=0)
    stats_updated_at: Optional[datetime] = None
    
    # Source tracking
    source: str = Field(default="civitai")  # civitai, huggingface, custom
    source_url: Optional[str] = None  # Original URL for reference
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Relationships (for eager loading)
    versions: List["ModelVersion"] = Relationship(back_populates="model")
    tags: List["ModelTag"] = Relationship(back_populates="model")


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
    
    id: Optional[int] = Field(default=None, primary_key=True)
    model_id: int = Field(foreign_key="models_v2.id", index=True)
    civitai_version_id: Optional[int] = Field(default=None, index=True)
    
    # Version info
    name: str  # "v1.0", "v2.0-inpainting", etc.
    base_model: Optional[str] = None  # "SDXL", "SD1.5", "Illustrious", "Pony"
    base_model_type: Optional[str] = None  # "Standard", "Inpainting", "Turbo"
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    
    # User selection state
    is_enabled: bool = Field(default=True)  # User can disable without deleting
    is_default: bool = Field(default=False)  # Default version for generation
    
    # LoRA-specific: trigger words (stored as JSON array string)
    trained_words: Optional[str] = None
    
    # Timestamps from CivitAI
    civitai_created_at: Optional[datetime] = None
    civitai_published_at: Optional[datetime] = None
    
    # Local timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Relationships
    model: Optional["ModelV2"] = Relationship(back_populates="versions")
    files: List["ModelFile"] = Relationship(back_populates="version")
    images: List["ModelImage"] = Relationship(back_populates="version")


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
    
    id: Optional[int] = Field(default=None, primary_key=True)
    version_id: int = Field(foreign_key="model_versions.id", index=True)
    civitai_file_id: Optional[int] = Field(default=None, index=True)
    
    # File info
    original_filename: str  # Original filename from source
    storage_filename: str  # Computed: {model}_{version}_{id}.safetensors
    size_kb: float = Field(default=0.0)
    format: Optional[str] = None  # SafeTensor, PickleTensor, Diffusers, etc.
    
    # Hashes for integrity verification
    hash_sha256: Optional[str] = None
    hash_autov2: Optional[str] = None
    hash_blake3: Optional[str] = None
    hash_crc32: Optional[str] = None
    
    # Download URL (with token placeholder)
    download_url: Optional[str] = None
    
    # File type
    is_primary: bool = Field(default=True)  # Primary model file for this version
    file_type: str = Field(default="Model")  # Model, Config, VAE, etc.
    
    # Relationships
    version: Optional["ModelVersion"] = Relationship(back_populates="files")
    provider_statuses: List["ProviderVersionStatus"] = Relationship(back_populates="file")


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
    
    id: Optional[int] = Field(default=None, primary_key=True)
    version_id: int = Field(foreign_key="model_versions.id", index=True)
    
    # Image data
    url: str
    width: Optional[int] = None
    height: Optional[int] = None
    blurhash: Optional[str] = None  # For progressive loading
    
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
        Index('idx_provider_status_legacy', 'provider_name', 'status'),
    )
    
    id: Optional[int] = Field(default=None, primary_key=True)
    file_id: int = Field(foreign_key="model_files.id", index=True)
    provider_id: Optional[str] = Field(default=None, foreign_key="providers.id", index=True)
    provider_name: Optional[str] = Field(default=None, index=True)
    
    # Status tracking
    status: str = Field(default="pending")  # pending, downloading, ready, failed
    storage_path: Optional[str] = None  # Actual path on provider storage
    size_bytes: Optional[int] = None  # Actual size after download
    
    # Timestamps
    queued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    downloaded_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None  # Last integrity check
    
    # Error tracking
    error_message: Optional[str] = None
    retry_count: int = Field(default=0)
    
    # Relationships
    file: Optional["ModelFile"] = Relationship(back_populates="provider_statuses")

    @property
    def provider_key(self) -> Optional[str]:
        """Return canonical provider identifier with fallback for legacy rows."""
        return self.provider_id or self.provider_name


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
    
    id: Optional[int] = Field(default=None, primary_key=True)
    model_id: int = Field(foreign_key="models_v2.id", index=True)
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
    id: Optional[int] = Field(default=None, primary_key=True)
    storage_path: str = Field(index=True, unique=True)
    deleted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
