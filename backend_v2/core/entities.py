# Core domain entities as SQLModel models
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import JSON, Index, UniqueConstraint, BigInteger
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import validates
from sqlmodel import Column, Field, Relationship, SQLModel
from pydantic import field_validator

from core.exceptions import ValidationError

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


# The states in which a worker has picked the job up and it is no longer queued.
#
# This lives beside the enum rather than in `services/job_service` because three
# services need it and two of them had their own transcription. `load_balancer`
# and `job_service.update_job` both re-spelled the tuple without `RETRYING`,
# which is the one state that most obviously belongs in it — a job in retry
# backoff is holding its slot on the provider. Under `least-connections` that
# read as zero in-flight jobs, so the balancer could hand the same provider a
# second job while the first was still there.
#
# `RETRYING` is the state most likely to be forgotten when a new one is added,
# because nothing about the name suggests "still occupying the worker".
ACTIVE_JOB_STATUSES = (
    JobStatus.SENT_TO_PROVIDER,
    JobStatus.CONNECTED,
    JobStatus.PRE_GENERATION,
    JobStatus.GENERATING,
    JobStatus.POST_PROCESSING,
    JobStatus.RETRYING,
)

# The states a job can never leave on its own.
TERMINAL_JOB_STATUSES = (
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
)


# Canonical worker/task type vocabulary. Anything else is rejected so
# ad-hoc values (e.g. "text") can't silently fall into the image queue.
# Task types a Job can carry, and a Provider can serve.
#
# `tts` is new and is the reason `Provider.capabilities` exists. `worker_type`
# alone is a SINGLE value, so a provider is either an image worker or an LLM
# endpoint — it cannot be both, and it cannot say "image, and also speech". TTS
# is the first task type served by the same ComfyUI container as image work, so
# the second dimension is now modelled explicitly rather than by overloading
# `worker_type`.
#
# `worker_type` is kept, not replaced: it still decides which execution path a
# provider uses (a ComfyUI container vs an always-on API endpoint), and the
# load balancer branches on it. `capabilities` decides which *jobs* it may be
# handed. Splitting those two questions is the point.
# ---------------------------------------------------------------------------
# Provider categories
#
# A provider's CATEGORY is the kind of work it does, and it is stored in the
# `worker_type` column — kept under its original name so no provider row and no
# API payload has to move. Read it through `Provider.category`, which is the
# property that says what it is.
#
# The word "worker" was doing two jobs at once: it named the category *and*
# implied an execution shape. That is what made the provider page read as
# ambiguous — a `tts` worker counts as an image worker for pool sizing while its
# jobs claim from the pool called "image", because the old rules were
# `worker_type != "llm"` and `task_type in {"image", "tts"}`. The category is now
# three named things, each with exactly one job pool, and the execution shape is
# a separate, explicit axis (`Provider.transport`, from the engine registry).
# ---------------------------------------------------------------------------
CATEGORY_IMAGE = "image"
CATEGORY_LLM = "llm"
CATEGORY_TTS = "tts"

VALID_TASK_TYPES = {CATEGORY_IMAGE, CATEGORY_LLM, CATEGORY_TTS}
VALID_CATEGORIES = VALID_TASK_TYPES  # same three values, said properly

#: Categories whose workloads run as a ComfyUI graph — model files, a workflow
#: dict, node-level progress. The remaining category (`llm`) is a plain HTTP
#: protocol endpoint. Kept under its old name because providers/crud.py and
#: tests reference it; it is a *category* set, not an engine-type set, and TTS
#: belongs to it for the reason above.
ENGINE_TASK_TYPES = {CATEGORY_IMAGE, CATEGORY_TTS}
COMFY_CATEGORIES = ENGINE_TASK_TYPES
CONTAINER_TASK_TYPES = ENGINE_TASK_TYPES  # backward-compat alias

#: Which task types each category's job pool may claim. One category, one pool,
#: one claim set — a job can only be served by the category that owns it, so
#: there is nothing to add on top.
CATEGORY_CLAIM_TASK_TYPES = {
    CATEGORY_IMAGE: frozenset({CATEGORY_IMAGE}),
    CATEGORY_LLM: frozenset({CATEGORY_LLM}),
    CATEGORY_TTS: frozenset({CATEGORY_TTS}),
}


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
    # Set when the user has read a failure and does not want it surfaced or
    # retried. Distinct from deletion on purpose: the job history is the only
    # record of what a provider did, so a failure the user has dealt with is
    # hidden rather than removed, and clearing this brings it back.
    acknowledged_at: datetime | None = Field(default=None, index=True)
    error: str | None = Field(default=None)
    
    # Provider assignment
    provider_id: str | None = Field(default=None)

    # Claim marker for the Postgres-backed job queue (SELECT ... FOR UPDATE SKIP LOCKED).
    # Not NULL while a worker owns the job; cleared when processing finishes.
    claimed_at: datetime | None = Field(default=None)

    # "This row was handed to the queue", as a queryable fact rather than an
    # assumption. `QueueManager.enqueue` is the only place a job becomes
    # dispatchable, but the claim query used to select *any* PENDING,
    # unclaimed row of the task type — so `orchestrator_service._tool_narrate_scene`,
    # which deliberately creates a row and runs it inline (it holds the parent
    # job's queue slot, so a queued narrator job could never be claimed),
    # was picked up by the LLM worker as well. Every agentic `narrate_scene`
    # turn therefore cost two paid LLM calls and inserted its narration twice.
    # The claim now requires this column to be set, so "created but not
    # enqueued" is expressible and the inline path is actually exclusive.
    # NULL for a job that is being executed inline by its creator.
    enqueued_at: datetime | None = Field(default=None, index=True)

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
    worker_type: str = Field(default="image")  # e.g., image, llm
    enabled: bool = Field(default=True)
    priority: int = Field(default=1)  # Lower = higher priority

    # Task types this provider may be handed. A LIST, because one ComfyUI
    # container serves both `image` and `tts` — the difference is the workflow
    # graph, not the machine. Empty means "whatever `worker_type` says", which is
    # what every provider existing before this column had, so a NULL here is a
    # supported state rather than an unconfigured one. See `Provider.serves()`.
    capabilities: list[str] = Field(default=[], sa_column=Column(JSONColumn))

    @field_validator("worker_type")
    @classmethod
    def _validate_worker_type(cls, value: str) -> str:
        if value not in VALID_TASK_TYPES:
            raise ValueError(f"worker_type must be one of {sorted(VALID_TASK_TYPES)}, got {value!r}")
        return value

    @field_validator("capabilities")
    @classmethod
    def _validate_capabilities(cls, value: list[str]) -> list[str]:
        """Reject an unknown capability rather than accepting a typo.

        A misspelt entry here is worse than a missing one: the load balancer
        would filter the provider out for a task type nobody asked about, and the
        job would fail as "no provider available" with nothing pointing at a
        spelling mistake in a JSON column.
        """
        for item in value or []:
            if item not in VALID_TASK_TYPES:
                raise ValueError(
                    f"capability {item!r} must be one of {sorted(VALID_TASK_TYPES)}"
                )
        # A provider that declares nothing serves whatever its worker_type says.
        # Returning worker_type here rather than keeping the list empty means
        # callers never have to remember the fallback rule.
        return list(value or [])

    @property
    def category(self) -> str:
        """The kind of work this provider does: image, llm, or tts.

        The stored column is `worker_type`, and it stays that way — every
        provider row, every API payload and every SQLite file would otherwise
        have to move for a rename. This property exists so new code says
        "category", which is the actual question, and so the pool-sizing and
        capability rules have one word to hang off.
        """
        return self.worker_type or CATEGORY_IMAGE

    @property
    def transport(self) -> str | None:
        """How the backend reaches this provider: modal/beam/remote/direct.

        Resolved from `type` through the engine registry rather than stored, so
        the registry stays the single place that knows a `beam_llm` provider
        talks to Beam. Unknown types resolve to None, which the pool sizing and
        the provider UI treat as "ask the registry".
        """
        from services.engines.registry import resolve_transport

        return resolve_transport(self.type)

    def serves(self, task_type: str) -> bool:
        """Whether this provider may be handed a job of `task_type`.

        ADDITIVE, and deliberately so. A provider always serves its own
        `worker_type`, because that is the execution path it was deployed with;
        `capabilities` only ever ADDS further task types on top.

        The first version made `capabilities` authoritative when set, so a
        provider declaring `["tts"]` would stop serving `image`. That is a
        footgun reachable from the UI: any editor that sent the capabilities it
        happened to know about would silently take a working image provider out
        of rotation, and the symptom — "no provider available" for every image
        job — points at routing, not at a form field. Under the additive rule,
        `["tts"]` on an image worker means "also does tts", and the worst a
        mistaken value can do is grant a capability the provider may not really
        have, which surfaces as a failed job on that task type alone.
        """
        if task_type == self.worker_type:
            return True
        return task_type in (self.capabilities or [])

    # Credentials (stored securely, used for container env vars)
    credentials: dict[str, Any] = Field(default={}, sa_column=Column(JSONColumn))
    
    # Provider-specific config
    config: dict[str, Any] = Field(default={}, sa_column=Column(JSONColumn))
    # The `container_config` column is gone from the model: migration 089
    # folded its keys into `config` (config wins) and the container-worker
    # architecture it served was removed in acc86aa3. The physical column is
    # still in Postgres (see `_migration_089_fold_container_config_into_config`);
    # nothing reads or writes it.



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
    # Wall-clock seconds the generating job took. Promoted out of
    # `metadata_["job"]["duration_seconds"]` so the statistics aggregations can
    # SUM it as a real numeric column. Casting that JSON text to NUMERIC in
    # Postgres raises on any non-numeric value, which would take down the whole
    # statistics endpoint rather than one row.
    duration_seconds: float | None = Field(default=None)
    # The instant the asset counts towards for time-windowed analytics: the job's
    # own completion time when it recorded one, else the row's generated_at /
    # created_at. Resolving this in SQL meant every grouped query had to evaluate
    # a jsonb extraction just to filter, which re-parsed the whole document — so
    # a filtered range cost 3.4s where the unfiltered one cost 1.2s. As a column
    # the filter is an indexed timestamp comparison.
    job_completed_at: datetime | None = Field(default=None, index=True)
    # Generation settings promoted out of `metadata_` for the same reason, and
    # one step further: these are the columns the statistics endpoints GROUP BY.
    # Every `->>` against `metadata_` re-reads and re-parses the whole jsonb
    # document (~70 MB across this deployment), so grouping on the document cost
    # one full decompression per distribution. As columns the same aggregations
    # are columnar scans.
    #
    # These are a rollup of `metadata_`, never an independent source of truth:
    # `services/asset_reconciler.derive_stat_columns` is the only thing that
    # writes them, and `tests/test_statistics_aggregation.py` asserts they agree
    # with the document they came from.
    checkpoint_name: str | None = Field(default=None)
    sampler: str | None = Field(default=None)
    scheduler: str | None = Field(default=None)
    vae: str | None = Field(default=None)
    steps: int | None = Field(default=None)
    cfg: float | None = Field(default=None)
    seed: int | None = Field(default=None, sa_column=Column(BigInteger))
    metadata_version: str | None = Field(default=None)
    metadata_: dict | None = Field(default=None, sa_column=Column(JSONColumn), alias="metadata")
    generated_at: datetime | None = Field(default=None, index=True)  # image creation time (from PNG meta or mtime)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: datetime | None = Field(default=None, index=True)  # soft delete


class Session(SQLModel, table=True):
    """A generation session: a curatable group of related images.

    Two things create these and they are deliberately distinguished:

    * **Auto-detected** (`auto_detected=True`, `locked=False`) — written by
      `services/session_detector` from the cheap signals already promoted to
      columns: identical `seed`, identical `checkpoint_name`, and a short time
      gap. Recomputation is idempotent via `signature`, so a re-run produces the
      same session instead of a duplicate.
    * **User-curated** — a detected session the human accepted, renamed, split
      or merged. Any such edit sets `locked=True`, and the detector then never
      touches it again. Without that flag every recompute would silently undo
      curation, which is how people come to distrust auto-tagging.

    Membership is a real join table (`SessionAsset`) rather than a computed
    time range, because split and merge are the operations people actually need
    and both mutate membership. A split also has to survive the next recompute,
    which it only can if membership is stored.

    `signature` is the detection key, not a user-facing label. It is nullable so
    a hand-made session has none, and `unique` is deliberately NOT set on it:
    two sessions can legitimately share a signature after a split, and a
    database-level uniqueness constraint there would make the split fail.
    """
    __tablename__ = "sessions"
    __table_args__ = (
        # Recompute scans by signature to find an existing session for a
        # detected group.
        Index("idx_session_signature", "user_id", "signature"),
        # The scrubber and the gallery both list sessions newest-first.
        Index("idx_session_user_updated", "user_id", "updated_at"),
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(default="default_user", index=True)

    # Nullable: an auto-detected session with no better label falls back to a
    # generated one, but a user-made session may legitimately be unnamed.
    name: str | None = Field(default=None)
    description: str | None = Field(default=None)

    # Detection bookkeeping. See the class docstring.
    signature: str | None = Field(default=None)
    auto_detected: bool = Field(default=False, index=True)
    # Set by any user edit (rename, split, merge, manual add/remove). The
    # detector skips locked sessions entirely.
    locked: bool = Field(default=False)

    # Scope. `workspace` mirrors Asset.workspace ('main' | 'chat' | 'story');
    # null means the session spans workspaces, which only a manual merge should
    # produce. Character/story scoping is derived from the member assets rather
    # than stored, so it cannot go stale.
    workspace: str | None = Field(default=None, index=True)

    # Denormalised bounds, maintained on membership change. The scrubber orders
    # and seeks by these, and recomputing them from members on every read would
    # be a correlated aggregate per session.
    start_at: datetime | None = Field(default=None, index=True)
    end_at: datetime | None = Field(default=None, index=True)
    image_count: int = Field(default=0)

    thumbnail: str | None = Field(default=None)  # relative_path of a cover image

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: datetime | None = Field(default=None, index=True)  # soft delete

    assets: list["SessionAsset"] = Relationship(
        back_populates="session",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class SessionAsset(SQLModel, table=True):
    """Join row: which assets belong to which session.

    Keyed on `asset_id` (a real FK to `assets.id`) rather than a filename
    string. The older `collection_images` table stores a bare
    `image_filename`, which cannot be joined to `assets` in SQL and does not
    cascade; that is the mistake this deliberately does not repeat.
    """
    __tablename__ = "session_assets"
    __table_args__ = (
        UniqueConstraint("session_id", "asset_id", name="uq_session_asset"),
        # "which session is this image in?" — the facet-filter direction.
        Index("idx_session_asset_asset", "asset_id"),
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    session_id: str = Field(foreign_key="sessions.id", index=True)
    asset_id: str = Field(foreign_key="assets.id", index=True)
    added_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    session: Optional["Session"] = Relationship(back_populates="assets")
    asset: Optional["Asset"] = Relationship()


class AssetLora(SQLModel, table=True):
    """Which LoRA an image used, as a real row.

    Without this, "show me every image that used this LoRA" has to run a jsonb
    containment query against `assets.metadata_`, which the GIN index from
    migration 024 can serve at the asset level — but it cannot cross into
    `session_assets`, so "show me every SESSION that used this LoRA" would need a
    correlated subquery per session. A normalised row makes both directions an
    indexed join, which is what the facet filter needs.

    `model_id` is the internal `models_v2.id` when this project imported the
    LoRA, and NULL otherwise. `civitai_model_id` is the upstream identity and is
    present for essentially every reference, because it is recoverable from the
    image's embedded PNG metadata. Keeping both means the index still works
    before a model has ever been imported, which is the common case for a LoRA
    applied but not installed.

    `strength` is what that image actually used, which is not necessarily the
    LoRA's default — so it is stored per image rather than read off the model.
    """
    __tablename__ = "asset_loras"
    __table_args__ = (
        # Recomputing the index for an image must be idempotent: the same LoRA
        # referenced twice collapses to one row.
        UniqueConstraint("asset_id", "civitai_model_id", name="uq_asset_lora"),
        # "which images used this LoRA?" — the facet-filter direction.
        Index("idx_asset_lora_civitai", "civitai_model_id"),
        # "which installed model is this?" — for display and for the reverse join.
        Index("idx_asset_lora_model", "model_id"),
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    asset_id: str = Field(foreign_key="assets.id", index=True)
    model_id: str | None = Field(foreign_key="models_v2.id", default=None, index=True)
    civitai_model_id: int | None = Field(default=None, index=True)
    strength: float | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    asset: Optional["Asset"] = Relationship()


class AssetTag(SQLModel, table=True):
    """One tag on one image, with who claimed it and how strongly.

    Deliberately the same shape as `ModelTag`, for the same reason: a tag whose
    origin is not recorded is a tag some later writer destroys. The auto-tagger
    is idempotent and re-runnable, so it must be able to replace its own rows and
    nothing else, which means the table has to say which rows are its own. Two
    sources exist and no more:

    * `'auto'` — derived by `services/tag_service.auto_tag_asset` from the
      booru-style vocabulary of the LoRAs the image actually used (their CivitAI
      tags plus their `trainedWords`, see
      `services.asset_metadata_index.extract_tag_evidence`). It is re-derived on
      every pass, so a LoRA whose upstream tags change converges instead of
      accumulating stale rows.
    * `'user'` — typed by a human through the writer path in
      `services/tag_service.add_user_tag`. Never touched by the auto-tagger, and
      never deletable through the auto path.

    There is deliberately no `'civitai'` source: a CivitAI tag on an IMAGE is
    only ever inferred from the LoRA that carried it, so calling it civitai
    would claim provenance this project does not have. The real provenance
    (which LoRA, which CivitAI model) stays queryable on `asset_loras`.

    `confidence` is real evidence, not a decoration. An auto tag is a
    *propagation*, not an observation: a `trainedWords` entry is the literal
    token that switches the concept on in the model (strong), whereas a CivitAI
    tag is a human catalogue label that also applies to images made without the
    LoRA (weak). `extract_tag_evidence` scores the two apart, the UI can grey out
    the weak ones, and a later re-tagger has something to rank by. A `user` row
    stores NULL, because "the human said so" is not a number on a scale.

    NO separate vocabulary table. A `Tag` entity with a denormalised use-count
    buys exactly one thing — a pre-computed count — and costs a second write on
    every tag insert plus a counter that can drift. The count is a `GROUP BY`
    over this table (`services.tag_service.list_tag_vocabulary`), which is one
    query, and the project already stores tag strings in two other shapes
    (`model_tags.tag`, `locations.tags` as a GIN-indexed JSONB array) without a
    vocabulary table. One indexed string, one shape.
    """
    __tablename__ = "asset_tags"
    __table_args__ = (
        # Idempotence: re-running the auto-tagger for an image must not double
        # its rows, and a tag both a human and the tagger know about is stored
        # once (see `ModelTag` — same reasoning, same constraint).
        UniqueConstraint("asset_id", "tag", name="uq_asset_tag"),
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    # No `index=True` on either key: `uq_asset_tag` is (asset_id, tag), so its
    # leading column already serves every asset-scoped lookup this table does,
    # and `ix_asset_tags_tag` (from `tag: index=True` below) serves the tag
    # side. A second index on either column would be a byte-for-byte duplicate.
    # The tag index is plain btree; the prefix scan the vocabulary endpoint
    # needs is a THIRD, Postgres-only `varchar_pattern_ops` index created by
    # migration 073, because a default btree is unusable for `LIKE 'x%'` under
    # this database's `en_US.utf8` collation.
    asset_id: str = Field(foreign_key="assets.id")
    tag: str = Field(index=True)
    source: str = Field(default="auto")  # auto | user
    # Confidence of an auto-derived tag, 0..1. NULL for a user tag — see the
    # class docstring.
    confidence: float | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    asset: Optional["Asset"] = Relationship()


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
    Normalized from CivitAI tags array, or typed by a user.

    `source` records who owns the row. CivitAI's resync replaces its own tags
    wholesale, so without provenance a user-typed tag is indistinguishable from
    a scraped one and the next resync deletes it. The unique constraint stays on
    (model_id, tag): a tag both sources know about is stored once, owned by
    whichever writer got there first, and is never duplicated.
    """
    __tablename__ = "model_tags"
    __table_args__ = (
        UniqueConstraint('model_id', 'tag', name='uq_model_tag'),
        Index('idx_tag_search', 'tag'),
    )
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    model_id: str = Field(foreign_key="models_v2.id", index=True)
    tag: str = Field(index=True)
    source: str = Field(default="civitai")  # civitai | user
    
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
    # The World this voice belongs to. Nullable and owned from the voice side —
    # see `World` for why the arrays it replaces are gone.
    world_id: str | None = Field(foreign_key="worlds.id", default=None, index=True)
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
    # The World this character belongs to. See `World` for why membership is a
    # column here and not an id array on the world.
    world_id: str | None = Field(foreign_key="worlds.id", default=None, index=True)

    # --- SillyTavern character card provenance ---------------------------
    # Kept separate from the editable prompt fields so an imported card can be
    # exported again without losing the author, the card version, or any field
    # this app has no column for (see card_metadata).
    card_spec: str | None = Field(default=None, index=True)  # chara_card_v1 / v2 / v3
    card_spec_version: str | None = Field(default=None)  # 1.0 / 2.0 / 3.0
    creator: str | None = Field(default=None)  # card author, NOT creator_notes
    character_version: str | None = Field(default=None)  # author-side card version
    group_greetings: list[str] | None = Field(default=None, sa_column=Column(JSONColumn))
    # Residual card payload: every root/data/extensions/assets field that has no
    # column above, so import -> export is lossless.
    card_metadata: dict | None = Field(default=None, sa_column=Column(JSONColumn))
    # Lorebook materialized from an embedded data.character_book (V2/V3).
    # NOT the same thing as `lorebook_ids` below, even though both point at
    # `lorebooks` and the confusion is the whole reason this comment exists:
    #
    #   embedded_lorebook_id — a SillyTavern `data.character_book` that arrived
    #     INSIDE an imported card. It is an artifact of that card: it belongs to
    #     the card, it is round-tripped back out on export, and it is
    #     deliberately NOT editable here, because editing it would make the
    #     export claim to be a card it is not. Written by card import only, and
    #     the SillyTavern spec allows at most one per card — hence scalar.
    embedded_lorebook_id: str | None = Field(default=None, foreign_key="lorebooks.id", index=True)
    #
    #   lorebook_ids — the vault's OWN library books this character draws on.
    #     Authored here, attached here, edited here, and the only relationship
    #     that makes a lorebook follow a character into EVERY conversation with
    #     them rather than being re-selected per chat.
    #
    # A card that has an embedded book may also have `lorebook_ids`: importing
    # never sets them, and the two lists are independent.
    lorebook_ids: list[str] = Field(default=[], sa_column=Column(JSONColumn))

    avatar_path: str | None = Field(default=None)
    sort_order: int = Field(default=0, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("lorebook_ids")
    @classmethod
    def _validate_lorebook_ids(cls, value: list[str] | None) -> list[str]:
        """Every entry must be a lorebook id.

        Reject, not normalise. The list is consumed as a bare
        `LorebookEntry.lorebook_id IN (...)`, so a dict or an int inside it
        matches nothing: the character's facts silently stop loading and the
        only symptom is that the model has forgotten who they are — which is
        why this is worth a 422 rather than a shrug. The same reason
        `Provider._validate_capabilities` refuses a misspelt value rather than
        accepting a typo that filters the provider out of rotation.

        Whether an id RESOLVES to a real lorebook is a separate check and cannot
        live here — the entity has no session — so it belongs to the write path
        (`api/routes/world_vault/characters.py`, alongside the identical
        `additional_character_ids` check in `chats.py`).

        `None` is refused rather than folded into `[]`. The field is a
        non-nullable JSON list, so a NULL would be a third state that nothing
        downstream handles: "no books" and "never set" would read identically
        in the prompt and differently in every `or []` fallback. Empty is `[]`.
        """
        if value is None:
            raise ValueError("lorebook_ids must be a list of lorebook ids, not null")
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    f"lorebook_ids entries must be lorebook ids, got {item!r}"
                )
        return list(value)

    @validates("lorebook_ids")
    def _check_lorebook_ids(self, _key, value):
        """Enforce the same rule on the write path.

        The pydantic validator above does NOT run under `Character(**kwargs)`:
        SQLModel's `table=True` `__init__` goes through
        `sqlmodel_table_construct`, which never calls the pydantic validator.
        The `Provider` and `Job` validators in this file have the same property.
        A rule that only fires on one of the two paths is worse than no rule,
        because it reads as a guard.

        `@validates` is SQLAlchemy's own attribute-set hook, so it fires on
        `Character(lorebook_ids=...)` and on `character.lorebook_ids = ...` in
        `update_character`/`patch_character`, and is skipped on ORM load — a
        legacy row is read, not re-validated. Raising the domain
        `ValidationError` rather than a bare `ValueError` is what makes it a 422
        instead of a 500 when it fires inside a route.

        It normalises nothing, and that is not an oversight: `SQLModel.
        __setattr__` calls `set_attribute()` and then `super().__setattr__()`
        with the ORIGINAL value, so the hook's return value is overwritten. A
        claimed normalisation that never takes effect is worse than none.
        """
        try:
            return self._validate_lorebook_ids(value)
        except ValueError as exc:
            raise ValidationError(str(exc), field="lorebook_ids") from exc

    collections: list["Collection"] = Relationship(
        back_populates="character",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    # Deliberately NOT "delete-orphan": deleting a character must orphan its
    # chats, not destroy them.  scrub_entity_references() nulls
    # chat.character_id so the conversation survives and the chat shows up as
    # an unbound session.  With delete-orphan here the ORM deleted the Chat
    # rows (and, via Chat.messages, every message) right after the scrub, which
    # silently destroyed full chat history on every character delete.
    chats: list["Chat"] = Relationship(
        back_populates="character",
        sa_relationship_kwargs={"cascade": "save-update, merge"}
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
    # The world this chat belongs to. Nullable, so an existing chat is not
    # forced into one and the migration is a pure addition. This is the
    # ownership of record — `World.chat_ids` is a denormalised index for the
    # world page and the graph, and the two can legitimately disagree for a chat
    # that was added to a world's index without being moved into it.
    world_id: str | None = Field(foreign_key="worlds.id", default=None, index=True)
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
    # Per-chat agentic image budget: how many images one exchange may spawn.
    # Separate from the depth cap, because depth counts LLM hops and a hop is
    # cheap while an image is not. The depth cap used to be the only limit, so a
    # single reply could chain five paid image jobs.
    max_agentic_images: int | None = Field(default=None)
    # Per-chat narration budget. Its OWN column rather than a share of the image
    # one, because a narration is always a whole extra LLM completion and an
    # image is a side effect the user may not have wanted at all — so raising
    # the image cap must not silently lower the narration cap.
    max_agentic_narrations: int | None = Field(default=None)
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
    # Global persona-library link (None → per-chat persona strings only)
    persona_id: str | None = Field(default=None, foreign_key="personas.id", index=True)
    # SillyTavern-style Author's Note — injected as a system message N turns from the tail
    authors_note: str | None = Field(default=None, sa_column=Column(Text))
    authors_note_depth: int | None = Field(default=None)  # None → default depth 4

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
    # `exclude=True` keeps 384 floats out of every API response. The route
    # handlers return ORM rows, and `api/routes/world_vault/memories.py` declares
    # no `response_model` at all, so FastAPI fell through to `jsonable_encoder`
    # and serialised the whole vector: a 200-row page of memories is ~1.5 MB of
    # JSON the UI never reads, re-fetched and re-cached on every page.
    #
    # This is the only place a 384-float vector should be excluded, because it is
    # pydantic-level: the column, the ORM read, and the pgvector
    # `cosine_distance` predicates in `rag_pipeline` all go through SQLAlchemy
    # and are unaffected. Every writer in the codebase assigns
    # `mem.embedding = vector` as an attribute rather than reconstructing the row
    # from a dump, so nothing loses a vector on the way in.
    embedding: list[float] | None = Field(default=None, exclude=True, sa_column=Column(Vector(384)))
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
    # The World whose chats draw on this book automatically. See `World`.
    world_id: str | None = Field(foreign_key="worlds.id", default=None, index=True)
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
    category: str | None = Field(default=None, index=True)
    tags: list[str] = Field(default=[], sa_column=Column(JSONColumn))
    depth: int = Field(default=4)
    case_sensitive: bool = Field(default=False)
    selective_logic: str | None = Field(default=None)
    probability: int | None = Field(default=None)

    # 384 dimensions for all-MiniLM-L6-v2 (CPU optimized)
    # Excluded from serialisation for the same reason as `CharacterMemory.embedding`:
    # `lorebooks.py` declares `response_model=list[LorebookEntry]`, which does not
    # help because the field was *in* the response model, so every entry listing
    # shipped 384 floats per row.
    embedding: list[float] | None = Field(default=None, exclude=True, sa_column=Column(Vector(384)))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    lorebook: Optional["Lorebook"] = Relationship(back_populates="entries")

class Scenario(SQLModel, table=True):
    __tablename__ = "scenarios"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(index=True)
    description: str | None = Field(default=None, sa_column=Column(Text))
    prompt_template: str = Field(sa_column=Column(Text))
    default_checkpoint: str | None = Field(default=None)
    default_voice_profile: str | None = Field(default=None, sa_column=Column(Text))
    # The World this scenario is the fallback for. See `World`.
    world_id: str | None = Field(foreign_key="worlds.id", default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Persona(SQLModel, table=True):
    """Reusable user-persona template assignable to any chat (persona library)."""
    __tablename__ = "personas"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(index=True)
    description: str | None = Field(default=None, sa_column=Column(Text))
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
    scenario_id: str | None = Field(default=None, foreign_key="scenarios.id")  # base scenario
    # See `Chat.world_id`.
    world_id: str | None = Field(foreign_key="worlds.id", default=None, index=True)
    llm_model: str | None = Field(default=None)  # Per-story LLM model override
    memory: str | None = Field(default=None, sa_column=Column(Text))  # Global author's note / story memory
    # Who the reader character IS. A chat resolves persona from the library via
    # `chat_context_kwargs`, a story had nothing — so `Story.character_ids` gave
    # the model every other person in the scene and none of them was the one
    # typing `> I draw my blade`. The world, the cast and the narrator all knew
    # who they were; the protagonist was anonymous.
    persona_id: str | None = Field(default=None, foreign_key="personas.id", index=True)
    persona_name: str | None = Field(default=None)
    persona_description: str | None = Field(default=None, sa_column=Column(Text))
    # Story state
    is_archived: bool = Field(default=False)
    # Per-story agentic loop depth limit (None → use global MAX_AGENTIC_DEPTH)
    max_agentic_depth: int | None = Field(default=None)
    # Per-story agentic image budget. See `Chat.max_agentic_images`.
    max_agentic_images: int | None = Field(default=None)
    # Per-story narration budget. See `Chat.max_agentic_narrations`.
    max_agentic_narrations: int | None = Field(default=None)
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

class StoryBeat(SQLModel, table=True):
    """One beat of a chapter, as a row.

    Beats were a JSON array of dicts on `story_chapters.beats`. That was the
    start of the two-representations problem this module spent a long time
    undoing: `chapter.content` was a prose string, `chapter.beats` was a
    sequence, and `sync_chapter_prose` / `absorb_prose_edit` existed to keep the
    two from disagreeing about the same text. They did disagree, and every fix
    was another guard against the next way to disagree.

    The sequence is now rows. What that buys is not correctness on its own — the
    JSON column is still maintained, by one writer, as the render the API and the
    editor already speak — but two things the JSON could never do:

      * a beat is independently ADDRESSABLE, so a chapter no longer has to be
        selected whole. `build_chat_context_async` receives a chapter as one
        `{"role": "user", "content": ...}` message, so `prune_context` has
        nothing to trim INSIDE it and a 6,000-word chapter eats the budget
        regardless of `maxContextTokens`. Beats are rows, so a window can be
        selected by position.
      * a beat is a row, so the beat-level routes and the job handlers write one
        thing rather than splicing a list of dicts.

    `position` is the ordering, renumbered on reorder — the beats panel supports
    drag-to-move, so an ordering that cannot be renumbered would have to be
    encoded in a linked list and `parent_beat_id` already is one.
    """
    __tablename__ = "story_beats"
    __table_args__ = (Index('idx_beat_chapter_position', 'chapter_id', 'position'),)
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    chapter_id: str = Field(foreign_key="story_chapters.id", index=True)
    # Ordering within the chapter. Dense and renumbered on move, so the beats
    # panel's drag-to-reorder is one UPDATE per affected row rather than a
    # fractional-order scheme with its own compaction pass.
    position: int = Field(default=0)
    parent_beat_id: str | None = None
    # narration | user | system | tts | scene — the same values the beat
    # request models validate against.
    role: str = Field(default="narrator")
    content: str = Field(default="", sa_column=Column(Text))
    # The audio attachment for a TTS beat. A separate column rather than part of
    # `extra` because it is what `render_beats` must NOT render and what the
    # beats panel renders an <audio> for.
    audio_path: str | None = None
    # The provenance stamps. Two keys, not one, for the reason
    # `_handle_chat_tts` uses its own: a TTS job's stamp must not overwrite the
    # reply job's on the same row, or the beat would look unwritten for the
    # continuation it came from.
    source_job_id: str | None = None
    tts_source_job_id: str | None = None
    # The retry takes, as [{"text": ..., "source_job_id": ...}]. A JSON column
    # rather than rows because alternates are a property of ONE beat, are read
    # and written together with it, and are never queried across beats.
    # A FRESH JSON type, not the shared `JSONColumn`. `as_mutable()` associates
    # the listener with the TYPE instance, so reusing the shared one attaches
    # MutableList's coerce to every other column built from it — `extra` here
    # becomes a list column and rejects a dict with
    # `Attribute 'extra' does not accept objects of type <class 'dict'>`.
    # `StoryChapter.beats` carries the same comment for the same reason.
    alternates: list[dict[str, Any]] = Field(
        default=[], sa_column=Column(MutableList.as_mutable(JSON().with_variant(JSONB(), "postgresql")))
    )
    active_index: int = Field(default=0)
    # Everything else a beat carries: orchestrator_depth, `intermediate`.
    extra: dict[str, Any] = Field(default={}, sa_column=Column(JSONColumn))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StoryChapterRevision(SQLModel, table=True):
    """Immutable point-in-time snapshot of a chapter's prose AND its beat list.

    `beats` was added because a snapshot of only `content` could not be restored
    faithfully: `restore_chapter_revision` used to set `content` and leave
    `beats` untouched, so the chapter came back as prose the beat list did not
    describe. That is the same drift this column exists to prevent, reintroduced
    by the one route that could rewind state.

    Existing rows have no `beats` and render from `render_beats`, which returns
    `""` for an empty list — so `restore` on a legacy snapshot restores the prose
    and leaves the beats as they are, which is the behaviour it already had.
    """
    __tablename__ = "story_chapter_revisions"
    __table_args__ = (Index('idx_revision_chapter_id', 'chapter_id'),)
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    chapter_id: str = Field(foreign_key="story_chapters.id", index=True)
    story_id: str = Field(foreign_key="stories.id", index=True)
    content: str = Field(default="", sa_column=Column(Text))
    beats: list[dict[str, Any]] = Field(
        default=[], sa_column=Column(MutableList.as_mutable(JSON()))
    )
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
    # The World this place is in. See `World`.
    world_id: str | None = Field(foreign_key="worlds.id", default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class World(SQLModel, table=True):
    """A world: the thing the rest of the vault is organised around.

    Was `Campaign`, and the name is the point of the rename. The product already
    had three surfaces called "World" — World Timeline, World Graph, World Vault —
    with no world behind any of them, while `Campaign` was the only entity
    grouping anything and was referenced by nothing: no FK in either direction, no
    read outside its own dashboard, and no entry point from a chat or a story.
    The two names had to be reconciled, and "World" is the one the rest of the UI
    already assumed existed.

    Ownership is one column on each member, pointing here:

        Chat.world_id, Story.world_id, Character.world_id, Lorebook.world_id,
        Location.world_id, Scenario.world_id, VoiceModel.world_id

    It USED to be six JSON id arrays on this row, read by the world page and the
    prompt builder and kept in sync with `Chat.world_id`/`Story.world_id` by a
    hand-written module — two columns describing one relationship, which is the
    shape this codebase's worst bug class comes from. The arrays are gone
    (migration `090_world_membership_fks`): `world_id` is indexed, so
    `select(Chat).where(Chat.world_id == wid)` is the same indexed lookup the
    array bought, and nothing can desync because there is only one thing to
    write. Every direction goes through `services/world_ownership.py`.
    """
    __tablename__ = "worlds"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(index=True)
    description: str | None = Field(default=None, sa_column=Column(Text))
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

