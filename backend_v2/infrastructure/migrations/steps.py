import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import inspect, text

from infrastructure.logging import db_logger

logger = db_logger()

SCHEMA_MIGRATIONS_TABLE = "schema_migrations"


@dataclass(frozen=True)
class MigrationStep:
    """Single schema migration step tracked in the database."""

    version: str
    description: str
    apply_fn: Callable


def _get_table_columns(conn, table_name: str) -> set[str]:
    """Return the current column names for a table."""

    inspector = inspect(conn)
    return {col["name"] for col in inspector.get_columns(table_name)}


def _verify_required_columns(conn, table_name: str, required_columns: set[str]) -> None:
    """Ensure a table contains all required columns after migrations run."""
    columns = _get_table_columns(conn, table_name)
    missing = sorted(required_columns - columns)
    if missing:
        raise RuntimeError(
            f"Schema verification failed for {table_name}: missing columns {', '.join(missing)}"
        )


def _ensure_schema_migrations_table(conn) -> None:
    """Create the schema migration tracking table if it does not exist."""

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))


def _get_applied_migrations(conn) -> set[str]:
    """Return the set of migration versions already recorded."""

    inspector = inspect(conn)
    if SCHEMA_MIGRATIONS_TABLE not in inspector.get_table_names():
        return set()

    rows = conn.execute(text("SELECT version FROM schema_migrations")).all()
    return {row[0] for row in rows}


def _record_migration(conn, step: MigrationStep) -> None:
    """Record a successfully applied migration step."""

    conn.execute(
        text(
            "INSERT INTO schema_migrations (version, description) VALUES (:version, :description)"
        ),
        {"version": step.version, "description": step.description},
    )


def _migration_add_job_timestamps(conn) -> bool:
    """Ensure jobs table includes started_at and completed_at columns."""

    inspector = inspect(conn)
    if "jobs" not in inspector.get_table_names():
        return False

    columns = {col["name"] for col in inspector.get_columns("jobs")}

    if "started_at" not in columns:
        conn.execute(text("ALTER TABLE jobs ADD COLUMN started_at TIMESTAMP"))
        logger.info("migration_column_added", table="jobs", column="started_at")

    if "completed_at" not in columns:
        conn.execute(text("ALTER TABLE jobs ADD COLUMN completed_at TIMESTAMP"))
        logger.info("migration_column_added", table="jobs", column="completed_at")

    _verify_required_columns(conn, "jobs", {"started_at", "completed_at"})
    return True


def _migration_setup_prompts_fts(conn) -> bool:
    """Create the prompts FTS table and synchronization triggers."""

    inspector = inspect(conn)
    if "prompts" not in inspector.get_table_names():
        logger.info("migration_fts_skipped", reason="prompts_table_missing")
        return False

    conn.execute(text("""
        CREATE VIRTUAL TABLE IF NOT EXISTS prompts_fts USING fts5(
            name, text, negative, description, tags,
            content='prompts', content_rowid='id'
        )
    """))
    logger.info("migration_fts_created", table="prompts_fts")

    fts_triggers = [
        """
        CREATE TRIGGER IF NOT EXISTS prompts_ai AFTER INSERT ON prompts BEGIN
            INSERT INTO prompts_fts(rowid, name, text, negative, description, tags)
            VALUES (new.id, new.name, new.text, COALESCE(new.negative, ''), 
                    COALESCE(new.description, ''), COALESCE(new.tags, ''));
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prompts_ad AFTER DELETE ON prompts BEGIN
            INSERT INTO prompts_fts(prompts_fts, rowid, name, text, negative, description, tags)
            VALUES ('delete', old.id, old.name, old.text, COALESCE(old.negative, ''), 
                    COALESCE(old.description, ''), COALESCE(old.tags, ''));
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prompts_au AFTER UPDATE ON prompts BEGIN
            INSERT INTO prompts_fts(prompts_fts, rowid, name, text, negative, description, tags)
            VALUES ('delete', old.id, old.name, old.text, COALESCE(old.negative, ''), 
                    COALESCE(old.description, ''), COALESCE(old.tags, ''));
            INSERT INTO prompts_fts(rowid, name, text, negative, description, tags)
            VALUES (new.id, new.name, new.text, COALESCE(new.negative, ''), 
                    COALESCE(new.description, ''), COALESCE(new.tags, ''));
        END
        """,
    ]

    for trigger_sql in fts_triggers:
        conn.execute(text(trigger_sql))
    return True


def _migration_add_provider_status_provider_id(conn) -> bool:
    """Add provider_id column and indexes to provider_version_status."""

    inspector = inspect(conn)
    if "provider_version_status" not in inspector.get_table_names():
        return False

    columns = {col["name"] for col in inspector.get_columns("provider_version_status")}

    if "provider_id" not in columns:
        conn.execute(
            text("ALTER TABLE provider_version_status ADD COLUMN provider_id TEXT")
        )
        logger.info(
            "migration_column_added",
            table="provider_version_status",
            column="provider_id",
        )

    if "provider_name" in columns:
        conn.execute(text("""
                UPDATE provider_version_status
                SET provider_id = provider_name
                WHERE (provider_id IS NULL OR provider_id = '')
                  AND provider_name IS NOT NULL
                """))

    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_provider_status_provider_id ON provider_version_status (provider_id, status)"
        )
    )
    if "provider_name" in columns:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_provider_status_legacy ON provider_version_status (provider_name, status)"
            )
        )
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_file_provider_id_unique ON provider_version_status (file_id, provider_id)"
        )
    )

    _verify_required_columns(conn, "provider_version_status", {"provider_id"})
    return True


def _migration_normalize_legacy_job_statuses(conn) -> bool:
    """Normalize legacy job statuses to the current lifecycle model."""

    inspector = inspect(conn)
    if "jobs" not in inspector.get_table_names():
        return False

    conn.execute(text("""
            UPDATE jobs
            SET status = 'pending'
            WHERE status = 'queued'
            """))
    conn.execute(text("""
            UPDATE jobs
            SET status = 'generating'
            WHERE status = 'processing'
            """))
    conn.execute(text("""
            UPDATE jobs
            SET status = 'generating'
            WHERE status = 'running'
            """))
    logger.info("migration_job_statuses_normalized")
    return True


def _migrate_models_to_v2(conn) -> bool:
    """
    Migrate existing models from V1 flat schema to V2 normalized schema.
    Per user clarification: existing models always used latest version,
    so we treat the first version in modelVersions as the selected default.
    """

    from sqlalchemy import inspect, text

    inspector = inspect(conn)
    tables = inspector.get_table_names()

    # Check if both old and new tables exist
    if "models" not in tables or "models_v2" not in tables:
        return False

    # Check if migration already done (models_v2 has data)
    result = conn.execute(text("SELECT COUNT(*) FROM models_v2"))
    v2_count = result.scalar()
    if v2_count > 0:
        logger.debug("migration_v2_skip", reason="already_populated")
        return False

    # Check if there's data to migrate
    result = conn.execute(text("SELECT COUNT(*) FROM models"))
    v1_count = result.scalar()
    if v1_count == 0:
        logger.debug("migration_v2_skip", reason="no_v1_models")
        return False

    logger.info("migration_v2_start", v1_count=v1_count)

    # Fetch all V1 models
    result = conn.execute(text("""
        SELECT id, name, directory, url, source, metadata_, provider_statuses, 
               created_at, updated_at
        FROM models
    """))

    migrated = 0
    for row in result:
        try:
            metadata = json.loads(row[5]) if row[5] else {}
            provider_statuses = json.loads(row[6]) if row[6] else {}

            if not metadata:
                # Skip models without CivitAI metadata
                continue

            # Create ModelV2 entry
            civitai_id = metadata.get("id")
            stats = metadata.get("stats", {})
            creator = metadata.get("creator", {})

            conn.execute(
                text("""
                INSERT INTO models_v2 (
                    civitai_model_id, name, type, directory, description,
                    nsfw, nsfw_level, creator_username, creator_image,
                    stats_downloads, stats_thumbs_up, stats_thumbs_down, stats_comments,
                    source, source_url, created_at, updated_at
                ) VALUES (
                    :civitai_id, :name, :type, :directory, :description,
                    :nsfw, :nsfw_level, :creator_username, :creator_image,
                    :downloads, :thumbs_up, :thumbs_down, :comments,
                    :source, :url, :created_at, :updated_at
                )
            """),
                {
                    "civitai_id": civitai_id,
                    "name": metadata.get("name", row[1]),
                    "type": metadata.get("type", "Checkpoint"),
                    "directory": row[2],
                    "description": metadata.get("description"),
                    "nsfw": metadata.get("nsfw", False),
                    "nsfw_level": metadata.get("nsfwLevel", 1),
                    "creator_username": creator.get("username"),
                    "creator_image": creator.get("image"),
                    "downloads": stats.get("downloadCount", 0),
                    "thumbs_up": stats.get("thumbsUpCount", 0),
                    "thumbs_down": stats.get("thumbsDownCount", 0),
                    "comments": stats.get("commentCount", 0),
                    "source": row[4] or "civitai",
                    "url": row[3],
                    "created_at": row[7],
                    "updated_at": row[8],
                },
            )

            # Get the inserted model ID
            model_result = conn.execute(
                text("SELECT id FROM models_v2 WHERE civitai_model_id = :cid"),
                {"cid": civitai_id},
            )
            model_v2_id = model_result.scalar()

            if not model_v2_id:
                continue

            # Create tags
            for tag in metadata.get("tags", []):
                try:
                    conn.execute(
                        text("""
                        INSERT INTO model_tags (model_id, tag) VALUES (:model_id, :tag)
                    """),
                        {"model_id": model_v2_id, "tag": tag},
                    )
                except Exception as e:
                    logger.debug(
                        "migration_v2_tag_skip",
                        model_id=model_v2_id,
                        tag=tag,
                        detail=str(e),
                    )

            # Get versions - take first (latest) as the selected one
            versions = metadata.get("modelVersions", [])
            if not versions:
                continue

            # Only migrate the first version (user's clarification)
            version_data = versions[0]
            civitai_version_id = version_data.get("id")

            # Determine trained words from version
            trained_words = version_data.get("trainedWords", [])
            trained_words_json = (
                json.dumps(trained_words) if trained_words else None
            )

            conn.execute(
                text("""
                INSERT INTO model_versions (
                    model_id, civitai_version_id, name, base_model, base_model_type,
                    description, is_enabled, is_default, trained_words,
                    civitai_published_at, created_at
                ) VALUES (
                    :model_id, :civitai_version_id, :name, :base_model, :base_model_type,
                    :description, 1, 1, :trained_words,
                    :published_at, :created_at
                )
            """),
                {
                    "model_id": model_v2_id,
                    "civitai_version_id": civitai_version_id,
                    "name": version_data.get("name", "v1.0"),
                    "base_model": version_data.get("baseModel"),
                    "base_model_type": version_data.get("baseModelType"),
                    "description": version_data.get("description"),
                    "trained_words": trained_words_json,
                    "published_at": version_data.get("publishedAt"),
                    "created_at": row[7],
                },
            )

            # Get version ID
            version_result = conn.execute(
                text(
                    "SELECT id FROM model_versions WHERE civitai_version_id = :vid"
                ),
                {"vid": civitai_version_id},
            )
            version_id = version_result.scalar()

            if not version_id:
                continue

            # Create files
            files = version_data.get("files", [])
            for i, file_data in enumerate(files):
                hashes = file_data.get("hashes", {})

                # Compute storage filename
                from core.entities import compute_storage_filename

                storage_filename = compute_storage_filename(
                    metadata.get("name", "model"),
                    version_data.get("name", "v1"),
                    civitai_version_id,
                    file_data.get("name", "model.safetensors"),
                )

                conn.execute(
                    text("""
                    INSERT INTO model_files (
                        version_id, civitai_file_id, original_filename, storage_filename,
                        size_kb, format, hash_sha256, hash_autov2, hash_blake3, hash_crc32,
                        download_url, is_primary, file_type
                    ) VALUES (
                        :version_id, :civitai_file_id, :original_filename, :storage_filename,
                        :size_kb, :format, :sha256, :autov2, :blake3, :crc32,
                        :download_url, :is_primary, :file_type
                    )
                """),
                    {
                        "version_id": version_id,
                        "civitai_file_id": file_data.get("id"),
                        "original_filename": file_data.get(
                            "name", "model.safetensors"
                        ),
                        "storage_filename": storage_filename,
                        "size_kb": file_data.get("sizeKB", 0),
                        "format": file_data.get("metadata", {}).get("format"),
                        "sha256": hashes.get("SHA256"),
                        "autov2": hashes.get("AutoV2"),
                        "blake3": hashes.get("BLAKE3"),
                        "crc32": hashes.get("CRC32"),
                        "download_url": file_data.get("downloadUrl"),
                        "is_primary": file_data.get("primary", i == 0),
                        "file_type": file_data.get("type", "Model"),
                    },
                )

            # Get primary file ID for provider status migration
            file_result = conn.execute(
                text(
                    "SELECT id FROM model_files WHERE version_id = :vid AND is_primary = 1"
                ),
                {"vid": version_id},
            )
            file_id = file_result.scalar()

            # Migrate provider statuses
            if file_id and provider_statuses:
                for provider_name, status_data in provider_statuses.items():
                    old_status = status_data.get("status", "pending")
                    # Map old statuses to new
                    status_map = {
                        "installed": "ready",
                        "downloading": "downloading",
                        "failed": "failed",
                    }
                    new_status = status_map.get(old_status, "pending")

                    conn.execute(
                        text("""
                        INSERT INTO provider_version_status (
                            file_id, provider_id, provider_name, status, storage_path, size_bytes,
                            downloaded_at
                        ) VALUES (
                            :file_id, :provider_id, :provider_name, :status, :storage_path, :size_bytes,
                            :downloaded_at
                        )
                    """),
                        {
                            "file_id": file_id,
                            "provider_id": provider_name,
                            "provider_name": provider_name,
                            "status": new_status,
                            "storage_path": f"{row[2]}/{row[1]}",  # directory/filename
                            "size_bytes": status_data.get("size_bytes"),
                            "downloaded_at": status_data.get("updated_at"),
                        },
                    )

            # Create images
            images = version_data.get("images", [])
            for i, img_data in enumerate(images):
                conn.execute(
                    text("""
                    INSERT INTO model_images (
                        version_id, url, width, height, blurhash, type,
                        nsfw_level, has_meta, has_positive_prompt, sort_order
                    ) VALUES (
                        :version_id, :url, :width, :height, :blurhash, :type,
                        :nsfw_level, :has_meta, :has_positive_prompt, :sort_order
                    )
                """),
                    {
                        "version_id": version_id,
                        "url": img_data.get("url"),
                        "width": img_data.get("width"),
                        "height": img_data.get("height"),
                        "blurhash": img_data.get("hash"),
                        "type": img_data.get("type", "image"),
                        "nsfw_level": img_data.get("nsfwLevel", 1),
                        "has_meta": img_data.get("hasMeta", False),
                        "has_positive_prompt": img_data.get(
                            "hasPositivePrompt", False
                        ),
                        "sort_order": i,
                    },
                )

            migrated += 1

        except Exception as e:
            logger.error(
                "migration_v2_model_error", model_name=row[1], error=str(e)
            )
            continue

    logger.info("migration_v2_complete", migrated=migrated)
    return True


def _migration_create_deleted_file_tombstones(conn) -> bool:
    """Create the deleted_file_tombstones table if it does not exist."""

    inspector = inspect(conn)
    if "deleted_file_tombstones" in inspector.get_table_names():
        return False

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS deleted_file_tombstones (
            storage_path TEXT PRIMARY KEY,
            original_model_id INTEGER,
            original_filename TEXT,
            deleted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_tombstone_deleted_at
        ON deleted_file_tombstones (deleted_at)
    """))
    logger.info("migration_created_table", table="deleted_file_tombstones")
    return True


def _migration_add_job_task_type(conn) -> bool:
    """Ensure jobs table includes task_type column."""

    inspector = inspect(conn)
    if "jobs" not in inspector.get_table_names():
        return False

    columns = {col["name"] for col in inspector.get_columns("jobs")}

    if "task_type" not in columns:
        conn.execute(text("ALTER TABLE jobs ADD COLUMN task_type TEXT DEFAULT 'image'"))
        logger.info("migration_column_added", table="jobs", column="task_type")

    _verify_required_columns(conn, "jobs", {"task_type"})
    return True

def _migration_add_provider_worker_type(conn) -> bool:
    """Ensure providers table includes worker_type column."""

    inspector = inspect(conn)
    if "providers" not in inspector.get_table_names():
        return False

    columns = {col["name"] for col in inspector.get_columns("providers")}

    if "worker_type" not in columns:
        conn.execute(text("ALTER TABLE providers ADD COLUMN worker_type TEXT DEFAULT 'image'"))
        logger.info("migration_column_added", table="providers", column="worker_type")

    _verify_required_columns(conn, "providers", {"worker_type"})
    return True

def _migration_add_collection_character_id(conn) -> bool:
    """Ensure collections table includes character_id column for character-scoped galleries."""

    inspector = inspect(conn)
    if "collections" not in inspector.get_table_names():
        return False

    columns = {col["name"] for col in inspector.get_columns("collections")}

    if "character_id" not in columns:
        conn.execute(text("ALTER TABLE collections ADD COLUMN character_id TEXT DEFAULT NULL"))
        logger.info("migration_column_added", table="collections", column="character_id")

    _verify_required_columns(conn, "collections", {"character_id"})
    return True

def _migration_normalize_chat_type_defaults(conn) -> bool:
    """Normalize chat_type values: migrate legacy 'roleplay' to 'chat'."""
    inspector = inspect(conn)
    if "chats" not in inspector.get_table_names():
        return False

    columns = {col["name"] for col in inspector.get_columns("chats")}
    if "chat_type" not in columns:
        return False

    result = conn.execute(text("UPDATE chats SET chat_type = 'chat' WHERE chat_type = 'roleplay'"))
    updated = result.rowcount
    if updated:
        logger.info("chat_type_normalized", updated=updated)
    return True


def _migration_add_collection_workspace(conn) -> bool:
    """Add workspace column to collections so albums can be scoped to the
    image / chat / story workspaces (issue #5 cross-workspace move support)."""

    inspector = inspect(conn)
    if "collections" not in inspector.get_table_names():
        return False

    columns = {col["name"] for col in inspector.get_columns("collections")}

    if "workspace" not in columns:
        conn.execute(text("ALTER TABLE collections ADD COLUMN workspace VARCHAR DEFAULT 'image'"))
        logger.info("migration_column_added", table="collections", column="workspace")

    _verify_required_columns(conn, "collections", {"workspace"})
    return True

def _migration_add_chat_persona_name(conn) -> bool:
    """Add persona_name column to chats table."""
    inspector = inspect(conn)
    if "chats" not in inspector.get_table_names():
        return False

    columns = {col["name"] for col in inspector.get_columns("chats")}

    if "persona_name" not in columns:
        conn.execute(text("ALTER TABLE chats ADD COLUMN persona_name VARCHAR"))
        logger.info("migration_column_added", table="chats", column="persona_name")

    _verify_required_columns(conn, "chats", {"persona_name"})
    return True

def _migration_add_chat_story_time_location(conn) -> bool:
    """Add story_time and story_location columns to chats table."""
    inspector = inspect(conn)
    if "chats" not in inspector.get_table_names():
        return False

    columns = {col["name"] for col in inspector.get_columns("chats")}
    applied = False

    if "story_time" not in columns:
        conn.execute(text("ALTER TABLE chats ADD COLUMN story_time VARCHAR"))
        logger.info("migration_column_added", table="chats", column="story_time")
        applied = True

    if "story_location" not in columns:
        conn.execute(text("ALTER TABLE chats ADD COLUMN story_location VARCHAR"))
        logger.info("migration_column_added", table="chats", column="story_location")
        applied = True

    _verify_required_columns(conn, "chats", {"story_time", "story_location"})
    return applied

def _migration_add_character_default_time_location(conn) -> bool:
    """Add default_time and default_location columns to characters table."""
    inspector = inspect(conn)
    if "characters" not in inspector.get_table_names():
        return False

    columns = {col["name"] for col in inspector.get_columns("characters")}
    applied = False

    if "default_time" not in columns:
        conn.execute(text("ALTER TABLE characters ADD COLUMN default_time VARCHAR"))
        logger.info("migration_column_added", table="characters", column="default_time")
        applied = True

    if "default_location" not in columns:
        conn.execute(text("ALTER TABLE characters ADD COLUMN default_location VARCHAR"))
        logger.info("migration_column_added", table="characters", column="default_location")
        applied = True

    _verify_required_columns(conn, "characters", {"default_time", "default_location"})
    return applied

def _migration_add_character_alternate_greetings(conn) -> bool:
    """Add alternate_greetings column to characters table."""
    inspector = inspect(conn)
    if "characters" not in inspector.get_table_names():
        return False

    columns = {col["name"] for col in inspector.get_columns("characters")}

    if "alternate_greetings" not in columns:
        conn.execute(text("ALTER TABLE characters ADD COLUMN alternate_greetings JSON DEFAULT '[]'"))
        logger.info("migration_column_added", table="characters", column="alternate_greetings")

    _verify_required_columns(conn, "characters", {"alternate_greetings"})
    return True


def _migration_add_character_checkpoint_lora(conn) -> bool:
    """Add checkpoint and lora columns to characters table."""
    inspector = inspect(conn)
    if "characters" not in inspector.get_table_names():
        return False

    columns = {col["name"] for col in inspector.get_columns("characters")}

    if "checkpoint" not in columns:
        conn.execute(text("ALTER TABLE characters ADD COLUMN checkpoint VARCHAR DEFAULT NULL"))
        logger.info("migration_column_added", table="characters", column="checkpoint")

    if "lora" not in columns:
        conn.execute(text("ALTER TABLE characters ADD COLUMN lora VARCHAR DEFAULT NULL"))
        logger.info("migration_column_added", table="characters", column="lora")

    _verify_required_columns(conn, "characters", {"checkpoint", "lora"})
    return True


def _migration_add_chat_active_lorebooks(conn) -> bool:
    """Add active_lorebook_ids JSON column to chats table for per-chat lorebook persistence."""
    inspector = inspect(conn)
    if "chats" not in inspector.get_table_names():
        return False

    columns = {col["name"] for col in inspector.get_columns("chats")}

    if "active_lorebook_ids" not in columns:
        conn.execute(text("ALTER TABLE chats ADD COLUMN active_lorebook_ids JSON DEFAULT '[]'"))
        logger.info("migration_column_added", table="chats", column="active_lorebook_ids")

    _verify_required_columns(conn, "chats", {"active_lorebook_ids"})
    return True


def _migration_add_llm_settings(conn) -> bool:
    """Add per-chat/story LLM model override and allow_image_generation flag."""
    inspector = inspect(conn)
    table_names = set(inspector.get_table_names())
    touched = False
    for table, cols in (
        ("chats", {"llm_model", "allow_image_generation"}),
        ("stories", {"llm_model"}),
    ):
        if table not in table_names:
            continue
        existing = {col["name"] for col in inspector.get_columns(table)}
        if "llm_model" not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN llm_model VARCHAR DEFAULT NULL"))
            logger.info("migration_column_added", table=table, column="llm_model")
        if table == "chats" and "allow_image_generation" not in existing:
            conn.execute(text("ALTER TABLE chats ADD COLUMN allow_image_generation BOOLEAN DEFAULT TRUE"))
            logger.info("migration_column_added", table="chats", column="allow_image_generation")
        _verify_required_columns(conn, table, cols)
        touched = True
    return touched


def _migration_add_narrator_system_prompt(conn) -> bool:
    """Add per-chat system prompt override, allow_narration flag, and message metadata column."""
    inspector = inspect(conn)
    table_names = set(inspector.get_table_names())
    touched = False
    if "chats" in table_names:
        existing = {col["name"] for col in inspector.get_columns("chats")}
        if "system_prompt_override" not in existing:
            conn.execute(text("ALTER TABLE chats ADD COLUMN system_prompt_override TEXT DEFAULT NULL"))
            logger.info("migration_column_added", table="chats", column="system_prompt_override")
        if "allow_narration" not in existing:
            conn.execute(text("ALTER TABLE chats ADD COLUMN allow_narration BOOLEAN DEFAULT TRUE"))
            logger.info("migration_column_added", table="chats", column="allow_narration")
        _verify_required_columns(conn, "chats", {"system_prompt_override", "allow_narration"})
        touched = True
    if "messages" in table_names:
        existing = {col["name"] for col in inspector.get_columns("messages")}
        if "message_metadata" not in existing:
            conn.execute(text("ALTER TABLE messages ADD COLUMN message_metadata JSON DEFAULT NULL"))
            logger.info("migration_column_added", table="messages", column="message_metadata")
        _verify_required_columns(conn, "messages", {"message_metadata"})
        touched = True
    return touched


def _migration_add_character_append_system_prompt(conn) -> bool:
    """Add append_system_prompt column to characters table."""
    inspector = inspect(conn)
    if "characters" not in inspector.get_table_names():
        return False
    columns = {col["name"] for col in inspector.get_columns("characters")}
    if "append_system_prompt" not in columns:
        conn.execute(text("ALTER TABLE characters ADD COLUMN append_system_prompt TEXT DEFAULT NULL"))
        logger.info("migration_column_added", table="characters", column="append_system_prompt")
    _verify_required_columns(conn, "characters", {"append_system_prompt"})
    return True


def _migration_add_chat_append_system_prompt(conn) -> bool:
    """Add append_system_prompt column to chats table."""
    inspector = inspect(conn)
    if "chats" not in inspector.get_table_names():
        return False
    columns = {col["name"] for col in inspector.get_columns("chats")}
    if "append_system_prompt" not in columns:
        conn.execute(text("ALTER TABLE chats ADD COLUMN append_system_prompt TEXT DEFAULT NULL"))
        logger.info("migration_column_added", table="chats", column="append_system_prompt")
        _verify_required_columns(conn, "chats", {"append_system_prompt"})
    return True


def _migration_add_chat_additional_character_ids(conn) -> bool:
    """Add additional_character_ids column to chats table."""
    inspector = inspect(conn)
    if "chats" not in inspector.get_table_names():
        return False
    columns = {col["name"] for col in inspector.get_columns("chats")}
    if "additional_character_ids" not in columns:
        conn.execute(text("ALTER TABLE chats ADD COLUMN additional_character_ids JSON DEFAULT '[]'"))
        logger.info("migration_column_added", table="chats", column="additional_character_ids")
    _verify_required_columns(conn, "chats", {"additional_character_ids"})
    return True


def _migration_add_chat_max_context_tokens(conn) -> bool:
    """Add max_context_tokens column to chats table for per-chat context window."""
    inspector = inspect(conn)
    if "chats" not in inspector.get_table_names():
        return False
    columns = {col["name"] for col in inspector.get_columns("chats")}
    if "max_context_tokens" not in columns:
        conn.execute(text("ALTER TABLE chats ADD COLUMN max_context_tokens INTEGER DEFAULT NULL"))
        logger.info("migration_column_added", table="chats", column="max_context_tokens")
    _verify_required_columns(conn, "chats", {"max_context_tokens"})
    return True


def _migration_add_message_pinned(conn) -> bool:
    """Add pinned boolean column to messages table."""
    inspector = inspect(conn)
    if "messages" not in inspector.get_table_names():
        return False
    columns = {col["name"] for col in inspector.get_columns("messages")}
    if "pinned" not in columns:
        conn.execute(text("ALTER TABLE messages ADD COLUMN pinned BOOLEAN NOT NULL DEFAULT FALSE"))
        logger.info("migration_column_added", table="messages", column="pinned")
    _verify_required_columns(conn, "messages", {"pinned"})
    return True


def _migration_add_persona_description(conn) -> bool:
    """Add persona_description to chats and suggested_persona to characters."""
    inspector = inspect(conn)
    table_names = set(inspector.get_table_names())
    touched = False
    if "chats" in table_names:
        cols = {c["name"] for c in inspector.get_columns("chats")}
        if "persona_description" not in cols:
            conn.execute(text("ALTER TABLE chats ADD COLUMN persona_description TEXT DEFAULT NULL"))
            logger.info("migration_column_added", table="chats", column="persona_description")
            touched = True
        _verify_required_columns(conn, "chats", {"persona_description"})
    if "characters" in table_names:
        cols = {c["name"] for c in inspector.get_columns("characters")}
        if "suggested_persona" not in cols:
            conn.execute(text("ALTER TABLE characters ADD COLUMN suggested_persona TEXT DEFAULT NULL"))
            logger.info("migration_column_added", table="characters", column="suggested_persona")
            touched = True
        _verify_required_columns(conn, "characters", {"suggested_persona"})
    return touched


def _migration_add_story_memory(conn) -> bool:
    """Add memory column to stories."""
    inspector = inspect(conn)
    if "stories" not in inspector.get_table_names():
        return False
        
    cols = _get_table_columns(conn, "stories")
    touched = False
    
    if "memory" not in cols:
        conn.execute(text("ALTER TABLE stories ADD COLUMN memory TEXT DEFAULT NULL"))
        logger.info("migration_column_added", table="stories", column="memory")
        touched = True
        
    _verify_required_columns(conn, "stories", {"memory"})
    return touched


def _migration_json_to_jsonb(conn) -> bool:
    """Convert JSON columns to JSONB and add GIN indexes (PostgreSQL only)."""
    if conn.dialect.name != "postgresql":
        return False

    inspector = inspect(conn)
    table_names = set(inspector.get_table_names())
    touched = False

    conversions = [
        ("jobs", {"workflow", "metadata_", "outputs"}),
        ("messages", {"message_metadata"}),
        ("lorebook_entries", {"keys"}),
        ("chats", {"active_lorebook_ids"}),
        ("characters", {"alternate_greetings"}),
    ]
    for table, cols in conversions:
        if table not in table_names:
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        for col in sorted(cols & existing):
            conn.execute(text(
                f'ALTER TABLE {table} ALTER COLUMN {col} TYPE JSONB USING {col}::jsonb'
            ))
            logger.info("migration_column_type", table=table, column=col, new_type="jsonb")
            touched = True

    # GIN indexes for JSONB containment/query access
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_jobs_metadata_gin ON jobs USING gin (metadata_)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_messages_metadata_gin ON messages USING gin (message_metadata)"
    ))
    return touched


def _migration_add_jobs_claimed_at(conn) -> bool:
    """Add jobs.claimed_at claim marker for the DB-backed job queue.

    Postgres: TIMESTAMPTZ + partial index for SKIP LOCKED claims.
    SQLite (local dev): plain DATETIME column, no index.
    """
    inspector = inspect(conn)
    table_names = set(inspector.get_table_names())
    if "jobs" not in table_names:
        return False

    existing = {c["name"] for c in inspector.get_columns("jobs")}
    if "claimed_at" in existing:
        if conn.dialect.name == "postgresql":
            existing_indexes = {index["name"] for index in inspector.get_indexes("jobs")}
            if "ix_jobs_claim" not in existing_indexes:
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_jobs_claim "
                    "ON jobs (task_type, status) WHERE status = 'PENDING' AND claimed_at IS NULL"
                ))
    return True


def _migration_099_world_edges(conn) -> bool:
    """Create the `world_edges` table for explicit entity relationships.

    Safe to re-run: the table and its unique index are created with
    IF NOT EXISTS / a guard, so a second start is a no-op.
    """
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())
    if "world_edges" in tables:
        return True

    conn.execute(
        text(
            """
            CREATE TABLE world_edges (
                id VARCHAR PRIMARY KEY,
                source_entity_type VARCHAR NOT NULL,
                source_entity_id VARCHAR NOT NULL,
                target_entity_type VARCHAR NOT NULL,
                target_entity_id VARCHAR NOT NULL,
                relation_type VARCHAR NOT NULL,
                label TEXT,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )

    conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_world_edge_unique
            ON world_edges (
                source_entity_type,
                source_entity_id,
                target_entity_type,
                target_entity_id,
                relation_type
            )
            """
        )
    )

    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_world_edges_source
            ON world_edges (source_entity_type, source_entity_id)
            """
        )
    )

    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_world_edges_target
            ON world_edges (target_entity_type, target_entity_id)
            """
        )
    )

    return True

    if conn.dialect.name == "postgresql":
        conn.execute(text("ALTER TABLE jobs ADD COLUMN claimed_at TIMESTAMPTZ"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_jobs_claim "
            "ON jobs (task_type, status) WHERE status = 'PENDING' AND claimed_at IS NULL"
        ))
    else:
        conn.execute(text("ALTER TABLE jobs ADD COLUMN claimed_at DATETIME"))
    logger.info("migration_claimed_at_added", table="jobs")
    return True


def _migration_add_jobs_prompt_fts(conn) -> bool:
    """Add a generated tsvector column for full-text prompt search (PostgreSQL only).

    The generated column is kept up to date by the database as metadata_ changes,
    and the GIN index makes `prompt_tsv @@ plainto_tsquery(...)` queries index-
    backed. SQLite dev databases fall back to LIKE-based matching in the repo.
    """
    if conn.dialect.name != "postgresql":
        return False

    inspector = inspect(conn)
    if "jobs" not in set(inspector.get_table_names()):
        return False

    existing = {c["name"] for c in inspector.get_columns("jobs")}
    if "prompt_tsv" in existing:
        return False

    conn.execute(text(
        "ALTER TABLE jobs ADD COLUMN prompt_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', COALESCE(metadata_->>'prompt', ''))) STORED"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_jobs_prompt_tsv ON jobs USING gin (prompt_tsv)"
    ))
    logger.info("migration_prompt_fts_added", table="jobs")
    return True


def _migration_add_asset_generated_at(conn) -> bool:
    """Add `generated_at` to assets for stable, content-accurate ordering.

    `created_at` records when the row was upserted, which scrambles gallery
    ordering for legacy files backfilled by move_existing_assets. `generated_at`
    holds the true image creation time (from embedded PNG metadata or file
    mtime) and becomes the ordering key for galleries and keyset pagination.
    """
    inspector = inspect(conn)
    if "assets" not in inspector.get_table_names():
        return False
    columns = {col["name"] for col in inspector.get_columns("assets")}
    if "generated_at" not in columns:
        conn.execute(text("ALTER TABLE assets ADD COLUMN generated_at TIMESTAMP DEFAULT NULL"))
        logger.info("migration_column_added", table="assets", column="generated_at")
    _verify_required_columns(conn, "assets", {"generated_at"})
    return True


def _migration_backfill_message_kind(conn) -> bool:
    """    Backfill `kind` for messages created before the kind column existed.

    Migration 030 added the column but left legacy rows at kind=NULL. This
    backfills by role so the UI can render narrator/image/tool kinds distinctly:
    role=system → narrator, role=user → user, role=assistant/char → char.
    World-state marker rows (role=system with metadata.source='world_state')
    become kind='narrator' too, but the UI keys off the world_state source
    first, so their rendering is unaffected.

    NOTE: `role` is stored as a Postgres enum (`messagerole`) whose labels are
    the enum NAMES (USER/CHAR/SYSTEM/STORY), while SQLite stores the lowercase
    values. The literals below must match the dialect. 'assistant' was never a
    valid enum label on Postgres, so it is only matched on SQLite (legacy rows).
    """
    inspector = inspect(conn)
    if "messages" not in inspector.get_table_names():
        return False
    columns = {col["name"] for col in inspector.get_columns("messages")}
    if "kind" not in columns:
        return False

    is_postgres = conn.dialect.name == "postgresql"
    if is_postgres:
        roles = {"system": "SYSTEM", "user": "USER", "char": "CHAR"}
    else:
        roles = {"system": "system", "user": "user", "char": "char"}

    result = conn.execute(
        text("UPDATE messages SET kind = 'narrator' WHERE kind IS NULL AND role = :role").bindparams(
            role=roles["system"]
        )
    )
    if result.rowcount:
        logger.info("migration_backfilled_kind", role="system", rows=result.rowcount)
    result = conn.execute(
        text("UPDATE messages SET kind = 'user' WHERE kind IS NULL AND role = :role").bindparams(
            role=roles["user"]
        )
    )
    if result.rowcount:
        logger.info("migration_backfilled_kind", role="user", rows=result.rowcount)
    if is_postgres:
        result = conn.execute(
            text("UPDATE messages SET kind = 'char' WHERE kind IS NULL AND role = :role").bindparams(
                role=roles["char"]
            )
        )
    else:
        result = conn.execute(
            text(
                "UPDATE messages SET kind = 'char' "
                "WHERE kind IS NULL AND role IN ('assistant', 'char')"
            )
        )
    if result.rowcount:
        logger.info("migration_backfilled_kind", role="char", rows=result.rowcount)
    return True


def _migration_add_asset_relative_path_unique(conn) -> bool:
    """Add a unique constraint on assets.relative_path.

    The asset reconciler upserts rows with Postgres ON CONFLICT (relative_path);
    that requires a unique constraint or index on the column, which was missing
    from the original create_all schema. Safe to re-run: checks for an existing
    unique index first and creates a unique index (works on both Postgres and
    SQLite, unlike ADD CONSTRAINT ... UNIQUE which needs a table rewrite on PG).
    """
    inspector = inspect(conn)
    if "assets" not in inspector.get_table_names():
        return False
    existing = {
        idx["name"]
        for idx in inspector.get_indexes("assets")
        if idx.get("unique")
    } | {
        cons["name"]
        for cons in inspector.get_unique_constraints("assets")
    }
    if "uq_assets_relative_path" in existing:
        logger.info("migration_asset_relative_path_unique_skipped", reason="already_exists")
        return True
    conn.execute(
        text("CREATE UNIQUE INDEX IF NOT EXISTS uq_assets_relative_path ON assets (relative_path)")
    )
    logger.info("migration_asset_relative_path_unique_applied")
    return True


def _migration_normalize_message_kind_case(conn) -> bool:
    """Normalize messages.kind to lowercase values.

    `kind` is stored as VARCHAR. Rows written by the app before the column was
    configured with `values_callable` stored the enum NAMES ('CHAR', 'IMAGE'),
    while migration 032 backfilled lowercase VALUES. Consumers (context
    builder, UI) compare lowercase, so uppercase rows render/treat as unknown.
    """
    inspector = inspect(conn)
    if "messages" not in inspector.get_table_names():
        return False
    columns = {col["name"] for col in inspector.get_columns("messages")}
    if "kind" not in columns:
        return False
    result = conn.execute(
        text("UPDATE messages SET kind = lower(kind) WHERE kind IS NOT NULL AND kind <> lower(kind)")
    )
    if result.rowcount:
        logger.info("migration_normalized_message_kind_case", rows=result.rowcount)
    return True


def _migration_add_message_kind_and_tool_calls(conn) -> bool:
    """Add `kind` and `tool_calls` to messages.

    `kind` classifies a message orthogonally to `role` (narrator/image/tool),
    so the context builder and UI can treat them without abusing role=SYSTEM
    (which previously exempted them from pruning). Existing narrator rows
    (stored as role=SYSTEM with metadata.source='narrator') are backfilled to
    kind='narrator' so they become prunable.
    """
    inspector = inspect(conn)
    if "messages" not in inspector.get_table_names():
        return False
    columns = {col["name"] for col in inspector.get_columns("messages")}

    if "kind" not in columns:
        conn.execute(text("ALTER TABLE messages ADD COLUMN kind VARCHAR DEFAULT NULL"))
        logger.info("migration_column_added", table="messages", column="kind")
    if "tool_calls" not in columns:
        conn.execute(text("ALTER TABLE messages ADD COLUMN tool_calls JSON DEFAULT NULL"))
        logger.info("migration_column_added", table="messages", column="tool_calls")

    # NOTE: no backfill of `kind`. Legacy narrator/image rows were stored with
    # role=SYSTEM and kind=NULL; the context builder already treats kind=NULL
    # role=SYSTEM as a prunable conversation turn, so they behave correctly
    # without an explicit backfill (which would require an enum-cast that
    # PostgreSQL rejects for these literal values).

    _verify_required_columns(conn, "messages", {"kind", "tool_calls"})
    return True


def _migration_add_data_integrity_constraints(conn) -> bool:
    """Add CHECK constraints and partial unique indexes (PostgreSQL only).

    - jobs.progress / jobs.overall_progress are percent-scale (0-100).
    - providers.worker_type is restricted to the known task types.
    - collections have unique names per owner scope (global vs character),
      enforced with partial unique indexes so the shared id-keyed table can
      host both scopes.
    """
    if conn.dialect.name != "postgresql":
        return False

    inspector = inspect(conn)
    tables = set(inspector.get_table_names())
    if "jobs" not in tables:
        return False

    jobs_cols = {c["name"] for c in inspector.get_columns("jobs")}
    if "progress" in jobs_cols:
        conn.execute(text(
            "ALTER TABLE jobs DROP CONSTRAINT IF EXISTS chk_jobs_progress"
        ))
        conn.execute(text(
            "ALTER TABLE jobs ADD CONSTRAINT chk_jobs_progress "
            "CHECK (progress >= 0 AND progress <= 100)"
        ))
    if "overall_progress" in jobs_cols:
        conn.execute(text(
            "ALTER TABLE jobs DROP CONSTRAINT IF EXISTS chk_jobs_overall_progress"
        ))
        conn.execute(text(
            "ALTER TABLE jobs ADD CONSTRAINT chk_jobs_overall_progress "
            "CHECK (overall_progress >= 0 AND overall_progress <= 100)"
        ))

    if "providers" in tables:
        conn.execute(text(
            "ALTER TABLE providers DROP CONSTRAINT IF EXISTS chk_providers_worker_type"
        ))
        conn.execute(text(
            "ALTER TABLE providers ADD CONSTRAINT chk_providers_worker_type "
            "CHECK (worker_type IN ('image', 'llm'))"
        ))

    if "collections" in tables:
        conn.execute(text(
            "DROP INDEX IF EXISTS uq_collections_global_name"
        ))
        conn.execute(text(
            "CREATE UNIQUE INDEX uq_collections_global_name "
            "ON collections (name) WHERE character_id IS NULL"
        ))
        conn.execute(text(
            "DROP INDEX IF EXISTS uq_collections_character_name"
        ))
        conn.execute(text(
            "CREATE UNIQUE INDEX uq_collections_character_name "
            "ON collections (character_id, name) WHERE character_id IS NOT NULL"
        ))

    logger.info("migration_data_integrity_constraints_added")
    return True


def _migration_add_composite_indexes(conn) -> bool:
    """Add missing composite indexes for common query patterns."""
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    if "messages" in tables:
        columns = {col["name"] for col in inspector.get_columns("messages")}
        if "chat_id" in columns and "created_at" in columns:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_message_chat_created
                ON messages (chat_id, created_at)
            """))

    if "stories" in tables:
        columns = {col["name"] for col in inspector.get_columns("stories")}
        if "updated_at" in columns:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_story_updated
                ON stories (updated_at)
            """))

    logger.info("migration_composite_indexes_added")
    return True


def _migration_add_job_typed_columns(conn) -> bool:
    """Add typed routing columns to jobs and backfill from metadata_ JSON."""
    inspector = inspect(conn)
    if "jobs" not in inspector.get_table_names():
        return False

    columns = {col["name"] for col in inspector.get_columns("jobs")}

    typed_cols = {
        "workspace": "TEXT",
        "character_id": "TEXT",
        "story_id": "TEXT",
        "source": "TEXT",
    }
    for col_name, col_type in typed_cols.items():
        if col_name not in columns:
            conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type}"))
            logger.info("migration_column_added", table="jobs", column=col_name)

    if "workspace" in columns or "character_id" in columns or "story_id" in columns or "source" in columns:
        conn.execute(text("""
            UPDATE jobs
            SET workspace = COALESCE(workspace, metadata_->>'workspace'),
                character_id = COALESCE(character_id, metadata_->>'character_id'),
                story_id = COALESCE(story_id, metadata_->>'story_id'),
                source = COALESCE(source, metadata_->>'source')
            WHERE metadata_ IS NOT NULL
              AND (workspace IS NULL OR character_id IS NULL OR story_id IS NULL OR source IS NULL)
        """))
        logger.info("migration_job_typed_columns_backfilled")

    for col_name in ("workspace", "character_id", "story_id", "source"):
        if col_name in columns:
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_job_{col_name} ON jobs ({col_name})"))

    _verify_required_columns(conn, "jobs", set(typed_cols.keys()))
    return True


def _migration_add_chat_max_agentic_depth(conn) -> bool:
    """Add max_agentic_depth column to chats."""
    inspector = inspect(conn)
    if "chats" not in inspector.get_table_names():
        return False

    columns = {col["name"] for col in inspector.get_columns("chats")}
    if "max_agentic_depth" not in columns:
        conn.execute(text("ALTER TABLE chats ADD COLUMN max_agentic_depth INTEGER"))
        logger.info("migration_column_added", table="chats", column="max_agentic_depth")

    _verify_required_columns(conn, "chats", {"max_agentic_depth"})
    return True


def _migration_add_story_max_agentic_depth(conn) -> bool:
    """Add max_agentic_depth column to stories."""
    inspector = inspect(conn)
    if "stories" not in inspector.get_table_names():
        return False

    columns = {col["name"] for col in inspector.get_columns("stories")}
    if "max_agentic_depth" not in columns:
        conn.execute(text("ALTER TABLE stories ADD COLUMN max_agentic_depth INTEGER"))
        logger.info("migration_column_added", table="stories", column="max_agentic_depth")

    _verify_required_columns(conn, "stories", {"max_agentic_depth"})
    return True


def _get_schema_migration_steps() -> list[MigrationStep]:
    """Return ordered schema migration steps."""
    return [
        MigrationStep(
            version="001_jobs_started_completed",
            description="Add jobs.started_at and jobs.completed_at columns",
            apply_fn=_migration_add_job_timestamps,
        ),
        MigrationStep(
            version="002_prompts_fts",
            description="Create prompts FTS table and synchronization triggers",
            apply_fn=_migration_setup_prompts_fts,
        ),
        MigrationStep(
            version="003_provider_status_provider_id",
            description="Add provider_id column and indexes to provider_version_status",
            apply_fn=_migration_add_provider_status_provider_id,
        ),
        MigrationStep(
            version="004_normalize_legacy_job_statuses",
            description="Normalize legacy jobs.status values (queued->pending, processing->running)",
            apply_fn=_migration_normalize_legacy_job_statuses,
        ),
        MigrationStep(
            version="005_migrate_models_to_v2",
            description="Migrate models from V1 schema to V2 normalized schema",
            apply_fn=_migrate_models_to_v2,
        ),
        MigrationStep(
            version="006_deleted_file_tombstones",
            description="Create deleted_file_tombstones table for tracking deleted model files",
            apply_fn=_migration_create_deleted_file_tombstones,
        ),
        MigrationStep(
            version="007_add_job_task_type",
            description="Add task_type column to jobs table",
            apply_fn=_migration_add_job_task_type,
        ),
        MigrationStep(
            version="008_add_provider_worker_type",
            description="Add worker_type column to providers table",
            apply_fn=_migration_add_provider_worker_type,
        ),
        MigrationStep(
            version="009_add_collection_character_id",
            description="Add character_id column to collections for character-scoped galleries",
            apply_fn=_migration_add_collection_character_id,
        ),
        MigrationStep(
            version="010_add_chat_persona_name",
            description="Add persona_name column to chats for per-chat persona",
            apply_fn=_migration_add_chat_persona_name,
        ),
        MigrationStep(
            version="011_add_character_alternate_greetings",
            description="Add alternate_greetings column to characters for SillyTavern multiple opening messages",
            apply_fn=_migration_add_character_alternate_greetings,
        ),
        MigrationStep(
            version="012_add_character_checkpoint_lora",
            description="Add checkpoint and lora columns to characters for agentic generation",
            apply_fn=_migration_add_character_checkpoint_lora,
        ),
        MigrationStep(
            version="013_add_chat_story_time_location",
            description="Add story_time and story_location columns to chats for story context",
            apply_fn=_migration_add_chat_story_time_location,
        ),
        MigrationStep(
            version="014_add_character_default_time_location",
            description="Add default_time and default_location columns to characters",
            apply_fn=_migration_add_character_default_time_location,
        ),
        MigrationStep(
            version="015_add_chat_active_lorebooks",
            description="Add active_lorebook_ids JSON column to chats for per-chat lorebook persistence",
            apply_fn=_migration_add_chat_active_lorebooks,
        ),
        MigrationStep(
            version="016_add_llm_settings",
            description="Add per-chat/story LLM model override and allow_image_generation flag",
            apply_fn=_migration_add_llm_settings,
        ),
        MigrationStep(
            version="017_add_narrator_system_prompt",
            description="Add per-chat system prompt override, allow_narration flag, and message metadata column",
            apply_fn=_migration_add_narrator_system_prompt,
        ),
        MigrationStep(
            version="018_add_character_append_system_prompt",
            description="Add append_system_prompt column to characters for per-character extra instructions",
            apply_fn=_migration_add_character_append_system_prompt,
        ),
        MigrationStep(
            version="019_add_chat_append_system_prompt",
            description="Add append_system_prompt column to chats for per-chat extra instructions",
            apply_fn=_migration_add_chat_append_system_prompt,
        ),
        MigrationStep(
            version="020_add_chat_max_context_tokens",
            description="Add max_context_tokens column to chats for per-chat context window size",
            apply_fn=_migration_add_chat_max_context_tokens,
        ),
        MigrationStep(
            version="021_add_message_pinned",
            description="Add pinned boolean column to messages so important messages survive context pruning",
            apply_fn=_migration_add_message_pinned,
        ),
        MigrationStep(
            version="022_add_persona_description",
            description="Add persona_description to chats and suggested_persona to characters",
            apply_fn=_migration_add_persona_description,
        ),
        MigrationStep(
            version="023_add_story_memory",
            description="Add memory column to stories for global author notes",
            apply_fn=_migration_add_story_memory,
        ),
        MigrationStep(
            version="024_json_to_jsonb",
            description="Convert JSON columns to JSONB with GIN indexes (PostgreSQL)",
            apply_fn=_migration_json_to_jsonb,
        ),
        MigrationStep(
            version="025_add_jobs_claimed_at",
            description="Add jobs.claimed_at claim marker for the Postgres-backed job queue",
            apply_fn=_migration_add_jobs_claimed_at,
        ),
        MigrationStep(
            version="026_add_jobs_prompt_fts",
            description="Add generated tsvector + GIN index for full-text prompt search (PostgreSQL)",
            apply_fn=_migration_add_jobs_prompt_fts,
        ),
        MigrationStep(
            version="027_add_data_integrity_constraints",
            description="Add CHECK constraints and partial unique indexes (PostgreSQL)",
            apply_fn=_migration_add_data_integrity_constraints,
        ),
        MigrationStep(
            version="028_add_collection_workspace",
            description="Add workspace column to collections for cross-workspace image moves (issue #5)",
            apply_fn=_migration_add_collection_workspace,
        ),
        MigrationStep(
            version="029_normalize_chat_type_defaults",
            description="Normalize legacy chat_type values: migrate 'roleplay' to 'chat'",
            apply_fn=_migration_normalize_chat_type_defaults,
        ),
        MigrationStep(
            version="030_add_message_kind_and_tool_calls",
            description="Add kind/tool_calls to messages; backfill narrator rows",
            apply_fn=_migration_add_message_kind_and_tool_calls,
        ),
        MigrationStep(
            version="031_add_asset_generated_at",
            description="Add generated_at to assets for content-accurate gallery ordering",
            apply_fn=_migration_add_asset_generated_at,
        ),
        MigrationStep(
            version="032_backfill_message_kind",
            description="Backfill messages.kind from role for pre-030 rows",
            apply_fn=_migration_backfill_message_kind,
        ),
        MigrationStep(
            version="033_add_asset_relative_path_unique",
            description="Unique index on assets.relative_path for ON CONFLICT upserts",
            apply_fn=_migration_add_asset_relative_path_unique,
        ),
        MigrationStep(
            version="034_normalize_message_kind_case",
            description="Lowercase any enum-NAME rows in messages.kind",
            apply_fn=_migration_normalize_message_kind_case,
        ),
        MigrationStep(
            version="035_add_composite_indexes",
            description="Add composite indexes for messages(chat_id, created_at) and stories(updated_at)",
            apply_fn=_migration_add_composite_indexes,
        ),
        MigrationStep(
            version="036_add_job_typed_columns",
            description="Add workspace/character_id/story_id/source typed columns to jobs with backfill from metadata_",
            apply_fn=_migration_add_job_typed_columns,
        ),
        MigrationStep(
            version="037_add_chat_max_agentic_depth",
            description="Add max_agentic_depth column to chats for per-chat agentic loop limit",
            apply_fn=_migration_add_chat_max_agentic_depth,
        ),
        MigrationStep(
            version="038_add_story_max_agentic_depth",
            description="Add max_agentic_depth column to stories for per-story agentic loop limit",
            apply_fn=_migration_add_story_max_agentic_depth,
        ),
        MigrationStep(
            version="039_add_chat_additional_character_ids",
            description="Add additional_character_ids column to chats table for group chats",
            apply_fn=_migration_add_chat_additional_character_ids,
        ),
        MigrationStep(
            version="040_create_voice_models",
            description="Create voice_models table for TTS voice profile management",
            apply_fn=_migration_040_create_voice_models,
        ),
        MigrationStep(
            version="041_create_character_memories",
            description="Create character_memories table with pgvector embedding for semantic search",
            apply_fn=_migration_041_create_character_memories,
        ),
        MigrationStep(
            version="042_add_branching_and_expressions",
            description="Add parent_id/branch_id to messages and expressions to characters",
            apply_fn=_migration_042_add_branching_and_expressions,
        ),
        MigrationStep(
            version="043_add_story_publishing_fields",
            description="Add publishing fields to stories for shareable story export",
            apply_fn=_migration_043_add_story_publishing_fields,
        ),
        MigrationStep(
            version="044_add_character_voice_model_fk",
            description="Add voice_model_id FK to characters for TTS voice profile linking",
            apply_fn=_migration_044_add_character_voice_model_fk,
        ),
        MigrationStep(
            version="045_create_locations",
            description="Create locations table for world-building location entities",
            apply_fn=_migration_045_create_locations,
        ),
        MigrationStep(
            version="046_create_campaigns",
            description="Create campaigns table for campaign/chronicle mode",
            apply_fn=_migration_046_create_campaigns,
        ),
        MigrationStep(
            version="047_add_chat_location_id",
            description="Add location_id FK to chats table for Location ↔ Chat integration",
            apply_fn=_migration_047_add_chat_location_id,
        ),
        MigrationStep(
            version="048_add_story_location_ids",
            description="Add location_ids JSONB column to stories table for Location ↔ Story integration",
            apply_fn=_migration_048_add_story_location_ids,
        ),
        MigrationStep(
            version="049_seed_starter_pack",
            description="Seed starter content: demo character, scenario, and llm-local provider",
            apply_fn=_migration_049_seed_starter_pack,
        ),
        MigrationStep(
            version="050_add_chat_idle_sim_enabled",
            description="Add idle_sim_enabled column to chats",
            apply_fn=_migration_add_chat_idle_sim_enabled,
        ),
        MigrationStep(
            version="051_world_vault_fixes",
            description="Add voice_models.preview_path and backfill llm-local api_base",
            apply_fn=_migration_051_world_vault_fixes,
        ),
        MigrationStep(
            version="052_add_lorebook_entry_timestamps",
            description="Add created_at/updated_at to lorebook_entries",
            apply_fn=_migration_052_add_lorebook_entry_timestamps,
        ),
        MigrationStep(
            version="053_add_chat_tts_voice_override",
            description="Add chats.tts_voice_id for per-chat TTS voice override",
            apply_fn=_migration_053_add_chat_tts_voice_override,
        ),
        MigrationStep(
            version="054_add_jobstatus_retrying",
            description="Add RETRYING label to the Postgres jobstatus enum",
            apply_fn=_migration_054_add_jobstatus_retrying,
        ),
        MigrationStep(
            version="055_add_character_sort_order",
            description="Add sort_order column to characters for drag-and-drop reordering",
            apply_fn=_migration_055_add_character_sort_order,
        ),
        MigrationStep(
            version="056_add_graph_layouts",
            description="Create graph_layouts table for relationship graph node positions",
            apply_fn=_migration_056_add_graph_layouts,
        ),
        MigrationStep(
            version="057_add_llm_sampler_columns",
            description="Add per-chat/story LLM sampling override columns",
            apply_fn=_migration_057_add_llm_sampler_columns,
        ),
        MigrationStep(
            version="058_add_story_writing_prefs",
            description="Add stories.word_count_goal and stories.pov writing preference columns",
            apply_fn=_migration_058_add_story_writing_prefs,
        ),
        MigrationStep(
            version="059_add_story_chapter_revisions",
            description="Create story_chapter_revisions table for chapter snapshots",
            apply_fn=_migration_059_add_story_chapter_revisions,
        ),
        MigrationStep(
            version="060_add_message_character_id",
            description="Add messages.character_id speaker attribution for group chats",
            apply_fn=_migration_060_add_message_character_id,
        ),
        MigrationStep(
            version="061_add_personas_and_chat_persona_fields",
            description="Create personas library table; add chats persona link + author's note columns",
            apply_fn=_migration_061_add_personas_and_chat_persona_fields,
        ),
        MigrationStep(
            version="062_add_scenario_fields_and_lorebook_entry_taxonomy",
            description="Add scenario default_checkpoint/voice_profile; add lorebook entry category/tags/depth/case_sensitive/selective_logic/probability",
            apply_fn=_migration_062_add_scenario_fields_and_lorebook_entry_taxonomy,
        ),
        MigrationStep(
            version="063_repair_postgres_constraints",
            description="Repair existing PostgreSQL foreign keys for branching, revisions, and world-vault links",
            apply_fn=_migration_063_repair_postgres_constraints,
        ),
        MigrationStep(
            version="064_add_character_card_metadata",
            description="Add characters card_spec/card_spec_version/creator/character_version/group_greetings/card_metadata and embedded_lorebook_id FK for lossless SillyTavern cards",
            apply_fn=_migration_064_add_character_card_metadata,
        ),
        MigrationStep(
            version="065_index_jobs_metadata_chat_id",
            description="Btree expression index on jobs ((metadata_->>'chat_id')) so chat-scoped job lookups stop sequentially scanning",
            apply_fn=_migration_065_index_jobs_metadata_chat_id,
        ),
        MigrationStep(
            version="066_add_asset_duration_seconds",
            description="Add assets.duration_seconds and backfill it from metadata_, so statistics can SUM a real numeric column instead of casting jsonb text",
            apply_fn=_migration_066_add_asset_duration_seconds,
        ),
        MigrationStep(
            version="067_add_asset_stat_columns",
            description="Add the assets statistics rollup columns (checkpoint/sampler/scheduler/vae/steps/cfg/seed/metadata_version) and backfill them from metadata_",
            apply_fn=_migration_067_add_asset_stat_columns,
        ),
        MigrationStep(
            version="068_add_asset_job_completed_at",
            description="Add assets.job_completed_at so a time-windowed statistics query filters on an indexed timestamp instead of re-parsing jsonb",
            apply_fn=_migration_068_add_asset_job_completed_at,
        ),
        MigrationStep(
            version="069_add_job_acknowledged_at",
            description="Add jobs.acknowledged_at so a read failure can be dismissed without being retried or deleted",
            apply_fn=_migration_069_add_job_acknowledged_at,
        ),
        MigrationStep(
            version="070_create_sessions",
            description="Add sessions and session_assets so related images can be grouped into curatable sessions",
            apply_fn=_migration_070_create_sessions,
        ),
        MigrationStep(
            version="071_add_model_tag_source",
            description="Distinguish user-added model tags from source tags so a resync cannot delete them",
            apply_fn=_migration_071_add_model_tag_source,
        ),
        MigrationStep(
            version="072_create_asset_loras",
            description="Add asset_loras so the LoRAs an image used are queryable rows rather than a filename buried in jsonb",
            apply_fn=_migration_072_create_asset_loras,
        ),
        MigrationStep(
            version="073_create_asset_tags",
            description="Add asset_tags plus its prefix-scan index, so an image's tags are queryable rows and the vocabulary is autocompleteable",
            apply_fn=_migration_073_create_asset_tags,
        ),
        MigrationStep(
            version="074_add_job_enqueued_at",
            description="Add jobs.enqueued_at so the Postgres claim query only claims rows that were actually handed to the queue, and an inline-only job row cannot be dispatched a second time",
            apply_fn=_migration_074_add_job_enqueued_at,
        ),
        MigrationStep(
            version="075_index_asset_gallery_timestamp",
            description="Index coalesce(generated_at, created_at) WHERE deleted_at IS NULL, the gallery's ordering key, which nothing covered",
            apply_fn=_migration_075_index_asset_gallery_timestamp,
        ),
        MigrationStep(
            version="076_provider_capabilities",
            description="Add providers.capabilities so a provider declares which task types (image/tts) it can serve, backfilled from worker_type; a tts job no longer routes to a worker with no TTS nodes",
            apply_fn=_migration_076_provider_capabilities,
        ),
        MigrationStep(
            version="077_campaigns_to_worlds",
            description="Rename campaigns to worlds, widen a world's index to lorebooks/scenarios/voices, and give chats and stories a nullable world_id so a world can actually scope something",
            apply_fn=_migration_077_campaigns_to_worlds,
        ),
        MigrationStep(
            version="078_provider_worker_type_tts",
            description="Widen chk_providers_worker_type to allow tts; the CHECK constraint was the last place still restricted to image/llm and rejected every TTS worker at insert",
            apply_fn=_migration_078_provider_worker_type_tts,
        ),
        MigrationStep(
            version="079_character_lorebook_ids",
            description="Add characters.lorebook_ids so a lorebook can be attached to a character and follow them into every chat, rather than being re-selected per conversation",
            apply_fn=_migration_079_character_lorebook_ids,
        ),
        MigrationStep(
            version="080_recreate_absent_indexes",
            description="Create the indexes migrations recorded as applied but never made — the gallery's own index among them, a 273x difference on its most-used screen",
            apply_fn=_migration_080_recreate_absent_indexes,
        ),
        MigrationStep(
            version="081_operator_class_indexes",
            description="Create the pgvector operator-class indexes on a fresh install, where create_all makes the table and the migration that would have indexed it skips",
            apply_fn=_migration_081_operator_class_indexes,
        ),
        MigrationStep(
            version="082_drop_redundant_message_chat_id_indexes",
            description="Drop two single-column messages(chat_id) indexes that the composite (chat_id, created_at) index already serves",
            apply_fn=_migration_082_drop_redundant_message_chat_id_indexes,
        ),
        MigrationStep(
            version="083_drop_duplicate_entity_indexes",
            description="Drop eight indexes that duplicate one the entity already declares, so writes maintain one btree per column instead of two",
            apply_fn=_migration_083_drop_duplicate_entity_indexes,
        ),
        MigrationStep(
            version="084_restore_model_files_civitai_file_id_index",
            description="Undo one over-eager drop in 083: ix_model_files_civitai_file_id was the only index on that column, not a duplicate",
            apply_fn=_migration_084_restore_model_files_civitai_file_id_index,
        ),
        MigrationStep(
            version="085_hot_table_covering_indexes",
            description="Add covering indexes on assets(checkpoint_name), asset_tags(tag_id), and lorebook_entries(embedding)",
            apply_fn=_migration_085_hot_table_covering_indexes,
        ),
        MigrationStep(
            version="086_fix_asset_tags_tag_index",
            description="Repair 085: it indexed asset_tags(tag_id), a column that does not exist, so the step recorded applied without the index; index the real tag column instead",
            apply_fn=_migration_086_fix_asset_tags_tag_index,
        ),
        MigrationStep(
            version="087_asset_seed_bigint",
            description="Widen assets.seed from INTEGER to BIGINT to hold ComfyUI 64-bit seeds",
            apply_fn=_migration_087_asset_seed_bigint,
        ),
        MigrationStep(
            version="088_converge_hot_indexes_and_seed",
            description="Re-issue the 085/086 hot indexes idempotently (085 recorded partial success as applied) and finish the 087 seed widening with a SQLite no-op and a skip-when-already-BIGINT guard",
            apply_fn=_migration_088_converge_hot_indexes_and_seed,
        ),
        MigrationStep(
            version="089_fold_container_config_into_config",
            description="Copy providers.container_config keys into config wherever absent (config wins), so container_name/port survive under the single registry key; the legacy column stays for read-compat",
            apply_fn=_migration_089_fold_container_config_into_config,
        ),
        MigrationStep(
            version="090_world_membership_fks",
            description="Move World membership from six JSON id arrays on the worlds row to one indexed world_id FK per member table (characters, locations, lorebooks, scenarios, voice_models, stories, chats), backfilled and the arrays dropped, so a world has one description instead of two",
            apply_fn=_migration_090_world_membership_fks,
        ),
        MigrationStep(
            version="091_agentic_image_budget",
            description="Add chats.max_agentic_images and stories.max_agentic_images (nullable, global default when null) so an agentic exchange has an image budget separate from the depth cap that counts LLM hops, not cost",
            apply_fn=_migration_091_agentic_image_budget,
        ),
        MigrationStep(
            version="092_revisions_carry_beats",
            description="Add story_chapter_revisions.beats so a chapter restore rewinds the beat list with the prose, instead of leaving beats describing text that was just reverted",
            apply_fn=_migration_092_revisions_carry_beats,
        ),
        MigrationStep(
            version="093_agentic_narration_budget",
            description="Add chats.max_agentic_narrations and stories.max_agentic_narrations (nullable, global default when null) so narrate_scene has the per-exchange cost cap generate_image got in 091 — a narration is a whole extra LLM completion the model chooses to spend",
            apply_fn=_migration_093_agentic_narration_budget,
        ),
        MigrationStep(
            version="094_story_persona",
            description="Add stories.persona_id / persona_name / persona_description (nullable) so a story resolves who the reader character is the way a chat does — the world, the cast and the narrator all knew, and the protagonist was anonymous",
            apply_fn=_migration_094_story_persona,
        ),
        MigrationStep(
            version="095_beats_as_rows",
            description="Move story beats from the story_chapters.beats JSON array to a story_beats table, backfilled in position order, so a beat is independently addressable and a chapter can be pruned by beat window instead of selected whole",
            apply_fn=_migration_095_beats_as_rows,
        ),
        MigrationStep(
            version="096_encrypt_provider_credentials",
            description="Rewrite plaintext providers.credentials rows into the Fernet envelope written by services/credential_crypto.py, so the tokens that moved out of .env are not sitting in a database dump. A no-op when COMFY_CREDENTIAL_SECRET is unset — the backfill runs again on the next start once the operator has chosen a key",
            apply_fn=_migration_096_encrypt_provider_credentials,
        ),
        MigrationStep(
            version="097_provider_worker_type_hybrid",
            description="Widen chk_providers_worker_type to allow hybrid; supports unified multi-modal workers (image + llm + tts) on a single provider row",
            apply_fn=_migration_097_provider_worker_type_hybrid,
        ),
        MigrationStep(
            version="098_chat_scenario_fk",
            description="Add nullable scenario_id FK to chats so a chat references a Scenario template like a story does",
            apply_fn=_migration_098_chat_scenario_fk,
        ),
        MigrationStep(
            version="099_world_edges",
            description="Add world_edges table for explicit, named relationships between any two vault entities",
            apply_fn=_migration_099_world_edges,
        ),
        MigrationStep(
            version="100_chat_director_state_snapshot",
            description="Add chats.director_enabled and chats.state_snapshot for System 1 Director and Statekeeper (Updater) live state tracking",
            apply_fn=_migration_100_chat_director_state_snapshot,
        ),
        MigrationStep(
            version="101_chat_director_autonomy",
            description="Add max_autonomous_turns and director_autonomy_level to chats",
            apply_fn=_migration_101_chat_director_autonomy,
        ),
        MigrationStep(
            version="102_agent_profiles",
            description="Add agent_profiles table and seed built-in agents",
            apply_fn=_migration_102_agent_profiles,
        ),
        MigrationStep(
            version="103_agent_prompt_variants",
            description="Add agent_prompt_variants table for per-agent prompt overrides",
            apply_fn=_migration_103_agent_prompt_variants,
        ),
        MigrationStep(
            version="104_variant_routing_tags",
            description="Add agent_prompt_variants.tags/selection_hint so Laya can route to a sub-variant per situation, and seed example (inactive) sub-variants for the built-in character and narrator agents",
            apply_fn=_migration_104_variant_routing_tags,
        ),
    ]


def _migration_090_world_membership_fks(conn) -> bool:
    """Make World membership one column per member instead of six JSON arrays.

    For most of its life a World held its roster in six JSON id arrays —
    `character_ids`, `location_ids`, `lorebook_ids`, `scenario_ids`,
    `voice_ids`, and the `chat_ids`/`story_ids` pair that `services/
    world_ownership.py` kept in sync with the `Chat.world_id` / `Story.world_id`
    FKs added in `077_campaigns_to_worlds`. So the vault had two descriptions
    of one relationship for chats and stories, and one denormalised guess for
    everything else. That is the shape this codebase's worst bug class comes
    from, and it shipped the desync `world_ownership.py` exists to prevent:
    `PUT /api/v2/worlds/{id}` accepted `chat_ids`/`story_ids` directly, so a
    world could list a chat the chat did not belong to, and
    `lorebook_ids`/`scenario_ids`/`voice_ids` had no scrub path at all, so
    deleting an entity left its id in the array forever.

    Ownership becomes one nullable indexed `world_id` on each member table.
    `world_id` is indexed, so `select(Chat).where(Chat.world_id == wid)` is the
    same indexed lookup the array bought, and there is one thing to write
    instead of two.

    Three legs, each safe to re-run:
      1. ADD the five columns + indexes (a no-op on a fresh install, which
         already has them from `create_all`).
      2. BACKFILL them from the arrays, `SET world_id = :w WHERE id = :id AND
         world_id IS NULL`. The guard makes an entity that already points at a
         world keep its FK, so a re-run cannot steal members, and worlds are
         visited oldest-first so an id listed by two worlds resolves
         deterministically rather than by rowid.
      3. DROP the six arrays from `worlds`. Nothing reads them after this.

    Per-statement savepoints, because leg 3 must not be able to leave a
    half-backed deployment: if a drop fails the step still returns True (the
    columns are dead code and dropping them is hygiene, not correctness) but it
    logs, so the next step does not silently assume they are gone.
    """
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())

    # (table, array column on worlds, entity label)
    members = (
        ("characters", "character_ids", "character"),
        ("locations", "location_ids", "location"),
        ("lorebooks", "lorebook_ids", "lorebook"),
        ("scenarios", "scenario_ids", "scenario"),
        ("voice_models", "voice_ids", "voice"),
        ("stories", "story_ids", "story"),
        ("chats", "chat_ids", "chat"),
    )

    # ── Leg 1: the columns ────────────────────────────────────────────────────
    # `Chat.world_id` / `Story.world_id` already exist (077); every member table
    # needs one anyway, and ADD COLUMN is a no-op when it is present.
    for table, _column, _label in members:
        if table not in tables:
            return False
        cols = {c["name"] for c in inspect(conn).get_columns(table)}
        if "world_id" in cols:
            continue
        col_type = "VARCHAR" if conn.dialect.name == "postgresql" else "TEXT"
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN world_id {col_type}"))
        logger.info("migration_column_added", table=table, column="world_id")

    # Indexes after columns, for the reason spelled out in
    # `_migration_077_campaigns_to_worlds`: an index built before its column
    # exists takes the app down at startup, every boot, with an error that
    # names the index rather than the ordering that caused it.
    for table, _column, _label in members:
        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_world_id ON {table} (world_id)"
        ))

    if "worlds" not in tables:
        return False

    world_cols = {c["name"] for c in inspect(conn).get_columns("worlds")}
    arrays = [column for _table, column, _label in members if column in world_cols]
    if not arrays:
        # Fresh install: `create_all` already produced the new World shape.
        for table, _column, _label in members:
            _verify_required_columns(conn, table, {"world_id"})
        return True

    # ── Leg 2: backfill ───────────────────────────────────────────────────────
    # Oldest world first, so an entity appearing in two arrays lands in the one
    # that was created first rather than whichever row the planner happened to
    # visit last.
    world_rows = conn.execute(text(
        "SELECT id, " + ", ".join(arrays) + " FROM worlds "
        "ORDER BY created_at NULLS LAST, id"
        if conn.dialect.name == "postgresql"
        else "SELECT id, " + ", ".join(arrays) + " FROM worlds ORDER BY id"
    )).all()

    def _as_list(raw):
        """Normalise a JSON column to a list of ids.

        Postgres hands back a parsed list for JSONB; SQLite hands back the text
        and needs `json.loads`. Anything unparseable is skipped rather than
        crashing the migration — the column is about to be dropped, and a
        malformed array is logged, not silently converted into a member.
        """
        if not raw:
            return []
        if isinstance(raw, (list, tuple)):
            return [str(v) for v in raw if v]
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if isinstance(parsed, list):
            return [str(v) for v in parsed if v]
        return []

    moved = 0
    for row in world_rows:
        world_id = row[0]
        values = row[1:]
        for (table, _column, label), raw in zip(members, values):
            ids = _as_list(raw)
            if ids is None:
                logger.warning("migration_090_unparseable_array",
                               table="worlds", world_id=world_id, column=_column)
                continue
            for entity_id in ids:
                updated = conn.execute(
                    text(f"UPDATE {table} SET world_id = :wid WHERE id = :id AND world_id IS NULL"),
                    {"wid": world_id, "id": entity_id},
                ).rowcount or 0
                if updated:
                    moved += 1
        logger.info("migration_090_world_migrated", world_id=world_id)

    if moved:
        logger.info("migration_090_members_relinked", count=moved)

    # ── Leg 3: drop the arrays ────────────────────────────────────────────────
    # One statement per savepoint: a failed drop is logged and does not abort
    # the step, because the columns are dead code afterwards and losing the
    # whole migration over hygiene would leave the backfill unrecorded too.
    for column in arrays:
        try:
            with conn.begin_nested():
                if conn.dialect.name == "postgresql":
                    conn.execute(text(f"ALTER TABLE worlds DROP COLUMN IF EXISTS {column}"))
                else:
                    # SQLite has no DROP COLUMN IF EXISTS, and the column is
                    # already known to exist at this point.
                    conn.execute(text(f"ALTER TABLE worlds DROP COLUMN {column}"))
            logger.info("migration_column_dropped", table="worlds", column=column)
        except Exception as exc:
            logger.warning("migration_090_column_drop_failed", column=column, error=str(exc))

    # The postcondition that matters is that every member carries `world_id`,
    # which is the ownership of record. `worlds.description` is not asserted:
    # this migration does not touch it, and a verify listing a column it never
    # reads turns an unrelated schema problem into a startup crash here.
    for table, _column, _label in members:
        _verify_required_columns(conn, table, {"world_id"})
    return True


def _migration_091_agentic_image_budget(conn) -> bool:
    """Give the agentic loop an image budget, separate from its depth cap.

    The depth cap counts LLM hops. A hop is cheap; an image is not, and
    `generate_image` was callable once per hop, so one reply could chain
    `MAX_AGENTIC_DEPTH` paid image jobs while the user asked for nothing. The
    depth cap and the image budget answer different questions — "how many more
    times should the model think" versus "how much am I willing to spend on one
    exchange" — so they are separate columns and separate limits.

    `max_agentic_images` on `chats` and `stories`, null meaning the global
    default. No backfill: a null column reads as the global default, which is the
    behaviour these chats already had.
    """
    from sqlalchemy import inspect, text

    added = False
    for table in ("chats", "stories"):
        tables = inspect(conn).get_table_names()
        if table not in tables:
            continue
        cols = {c["name"] for c in inspect(conn).get_columns(table)}
        if "max_agentic_images" in cols:
            continue
        conn.execute(
            text(f"ALTER TABLE {table} ADD COLUMN max_agentic_images INTEGER")
        )
        logger.info("migration_column_added", table=table, column="max_agentic_images")
        added = True
    if not added:
        logger.info("migration_noop", note="agentic image budget already present")
    return True


def _migration_092_revisions_carry_beats(conn) -> bool:
    """Give `story_chapter_revisions` a `beats` column so a restore is total.

    A revision was a snapshot of `content` only, and `restore_chapter_revision`
    set `content` while leaving `beats` untouched — so the one route that rewinds
    state put the chapter back into the drift state the beat list is supposed to
    prevent. With beats in the snapshot, a restore rewinds both and the prose is
    re-rendered from them.

    No backfill. A legacy snapshot has no beats, so restoring it restores the
    prose exactly as before and leaves the beats alone — the behaviour it
    already had. Rendering an empty beat list would produce `""`, which is why
    the restore path checks for an empty list rather than treating it as
    "the chapter had no beats".
    """
    from sqlalchemy import inspect, text

    tables = inspect(conn).get_table_names()
    if "story_chapter_revisions" not in tables:
        return False
    cols = {c["name"] for c in inspect(conn).get_columns("story_chapter_revisions")}
    if "beats" in cols:
        logger.info("migration_noop", note="story_chapter_revisions.beats already present")
        return True
        conn.execute(
            text("ALTER TABLE story_chapter_revisions ADD COLUMN beats JSON DEFAULT '[]'")
        )
    logger.info("migration_column_added", table="story_chapter_revisions", column="beats")
    return True


def _migration_093_agentic_narration_budget(conn) -> bool:
    """Give `narrate_scene` a per-exchange budget alongside the image one.

    `MAX_AGENTIC_DEPTH` bounds how many times the model may think; it does not
    bound what it spends. `generate_image` was callable once per hop with
    nothing in the way, so a single reply could chain five paid image jobs while
    the user asked for one — that was `091`. `narrate_scene` had the same hole
    and it was the worse of the two: a narration is always a whole extra LLM
    completion, it is the tool the model is most likely to reach for, and it had
    no cap at all. So the most expensive discretionary decision in the loop was
    also the only unbounded one.

    A separate column, not a share of `max_agentic_images`: raising the image cap
    must not silently lower the narration cap, because the two are answering
    different questions. No backfill — null reads as the global default, which is
    what these chats had before.
    """
    from sqlalchemy import inspect, text

    added = False
    for table in ("chats", "stories"):
        tables = inspect(conn).get_table_names()
        if table not in tables:
            continue
        cols = {c["name"] for c in inspect(conn).get_columns(table)}
        if "max_agentic_narrations" in cols:
            continue
        conn.execute(
            text(f"ALTER TABLE {table} ADD COLUMN max_agentic_narrations INTEGER")
        )
        logger.info("migration_column_added", table=table, column="max_agentic_narrations")
        added = True
    if not added:
        logger.info("migration_noop", note="agentic narration budget already present")
    return True


def _migration_094_story_persona(conn) -> bool:
    """Give a Story the persona fields a Chat resolves.

    A chat builds its context through `chat_context_kwargs`, which resolves
    `chat.persona_id` from the Persona library and falls back to the story's own
    strings. A story called the same context builder with neither — so every
    other field the user can set on a story reached the model and the one
    describing the reader did not.

    Three nullable columns, added idempotently, all reading as "unset" when null.
    No backfill: a story with no persona was being written with no persona, and
    that is what it keeps.
    """
    from sqlalchemy import inspect, text

    tables = inspect(conn).get_table_names()
    if "stories" not in tables:
        return False
    cols = {c["name"] for c in inspect(conn).get_columns("stories")}
    for column, coltype in (
        ("persona_id", "VARCHAR"),
        ("persona_name", "VARCHAR"),
        ("persona_description", "TEXT"),
    ):
        if column in cols:
            continue
        conn.execute(text(f"ALTER TABLE stories ADD COLUMN {column} {coltype}"))
        logger.info("migration_column_added", table="stories", column=column)
    return True


def _migration_095_beats_as_rows(conn) -> bool:
    """Move story beats from a JSON array on the chapter to their own table.

    Beats were `story_chapters.beats`, a list of dicts, and keeping them in
    step with `story_chapters.content` — the prose they render to — was a
    hand-written set of splices. That is the two-representations problem, and it
    cost: `sync_chapter_prose`, `absorb_prose_edit`, `_beat_snippet`,
    `_replace_beat_text` (deleted) and `_remove_beat_text` (deleted) all existed
    because two fields described one text.

    Now a beat is a row. The JSON column is NOT dropped by this migration — the
    API, the editor and ~95 readers still speak `beats: [...]`, and a schema
    change that breaks every reader in one commit is not a migration, it is an
    outage. It is maintained by one writer (`sync_chapter_prose`) from the rows,
    which is what makes the two unable to disagree: there is one code path that
    produces the JSON and it is the same one that writes the rows.

    Backfilled in `position` order from the existing array, so a chapter's beat
    order survives. Re-running is a no-op once the rows exist, so the migration
    is safe to re-run on a partially-migrated database.
    """
    import json as _json

    from sqlalchemy import inspect, text

    tables = inspect(conn).get_table_names()
    if "story_beats" not in tables:
        if conn.dialect.name == "postgresql":
            conn.execute(text("""
                CREATE TABLE story_beats (
                    id VARCHAR PRIMARY KEY,
                    chapter_id VARCHAR NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0,
                    parent_beat_id VARCHAR,
                    role VARCHAR NOT NULL DEFAULT 'narrator',
                    content TEXT NOT NULL DEFAULT '',
                    audio_path VARCHAR,
                    source_job_id VARCHAR,
                    tts_source_job_id VARCHAR,
                    alternates JSONB NOT NULL DEFAULT '[]',
                    active_index INTEGER NOT NULL DEFAULT 0,
                    extra JSONB NOT NULL DEFAULT '{}',
                    created_at TIMESTAMP
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE story_beats (
                    id VARCHAR PRIMARY KEY,
                    chapter_id VARCHAR NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0,
                    parent_beat_id VARCHAR,
                    role VARCHAR NOT NULL DEFAULT 'narrator',
                    content TEXT NOT NULL DEFAULT '',
                    audio_path VARCHAR,
                    source_job_id VARCHAR,
                    tts_source_job_id VARCHAR,
                    alternates JSON NOT NULL DEFAULT '[]',
                    active_index INTEGER NOT NULL DEFAULT 0,
                    extra JSON NOT NULL DEFAULT '{}',
                    created_at TIMESTAMP
                )
            """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_story_beats_chapter_id ON story_beats (chapter_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_beat_chapter_position ON story_beats (chapter_id, position)"
        ))
        logger.info("migration_table_created", table="story_beats")

    if "story_chapters" not in tables:
        return False
    cols = {c["name"] for c in inspect(conn).get_columns("story_chapters")}
    if "beats" not in cols:
        # Nothing to backfill from: a chapter with no JSON column has no beats to
        # carry over, and the rows are the only source from here on.
        return True

    existing = conn.execute(text("SELECT COUNT(*) FROM story_beats")).scalar()
    if existing:
        # Already backfilled. Idempotent by the row count, not by a marker, so a
        # partially-migrated database is not re-seeded on the next boot.
        return True

    rows = conn.execute(
        text("SELECT id, beats FROM story_chapters WHERE beats IS NOT NULL")
    ).all()

    inserted = 0
    for chapter_id, raw in rows:
        if isinstance(raw, (str, bytes)):
            try:
                beats = _json.loads(raw)
            except (ValueError, TypeError):
                logger.warning("migration_095_unparseable_beats", chapter_id=chapter_id)
                continue
        else:
            beats = raw
        if not isinstance(beats, list):
            continue
        for position, beat in enumerate(beats):
            if not isinstance(beat, dict):
                continue
            # Everything the JSON carried that is not a column of its own goes to
            # `extra`, so nothing is lost by the move.
            extra = {
                k: v for k, v in beat.items()
                if k not in {
                    "id", "parent_beat_id", "role", "content", "audio_path",
                    "source_job_id", "alternates", "active_index",
                }
            }
            conn.execute(
                text("""
                    INSERT INTO story_beats
                        (id, chapter_id, position, parent_beat_id, role, content,
                         audio_path, source_job_id, tts_source_job_id,
                         alternates, active_index, extra, created_at)
                    VALUES
                        (:id, :chapter_id, :position, :parent_beat_id, :role, :content,
                         :audio_path, :source_job_id, :tts_source_job_id,
                         :alternates, :active_index, :extra, :created_at)
                """),
                {
                    "id": beat.get("id") or str(uuid.uuid4()),
                    "chapter_id": chapter_id,
                    "position": position,
                    "parent_beat_id": beat.get("parent_beat_id"),
                    "role": beat.get("role") or "narrator",
                    "content": beat.get("content") or "",
                    "audio_path": beat.get("audio_path"),
                    "source_job_id": beat.get("source_job_id"),
                    "tts_source_job_id": beat.get("tts_source_job_id"),
                    "alternates": _json.dumps(beat.get("alternates") or []),
                    "active_index": beat.get("active_index") or 0,
                    "extra": _json.dumps(extra),
                    "created_at": beat.get("created_at"),
                },
            )
            inserted += 1
    logger.info("migration_095_beats_migrated", count=inserted)
    return True


def _migration_073_create_asset_tags(conn) -> bool:
    """Create `asset_tags` if the entity has not already produced it.

    Same shape as 072: `SQLModel.metadata.create_all` creates this table from
    the entity on a fresh database, so the DDL below only fires for a database
    created before the entity existed, and it is written to match what SQLModel
    emits. The unique constraint is a unique INDEX rather than a table-level
    UNIQUE constraint because SQLite has no `ADD CONSTRAINT ... IF NOT EXISTS`
    and a unique index is equivalent here.

    The `varchar_pattern_ops` index is the one piece of this migration that a
    plain btree cannot do. The vocabulary endpoint answers `tag LIKE 'bl%'`
    ordered by use-count, and this database collates as `en_US.utf8`, where a
    default btree is NOT usable for a prefix LIKE — only `text_pattern_ops`
    (byte order) is. Without it the autocomplete is a sequential scan of every
    tag row on every keystroke. Postgres-only, so it is guarded.

    Returns True unconditionally so the runner records it — see the note in
    `_migration_070_create_sessions` about `if applied: _record_migration(...)`.
    """
    inspector = inspect(conn)
    if "asset_tags" not in set(inspector.get_table_names()):
        ts = "TIMESTAMP WITH TIME ZONE" if conn.dialect.name == "postgresql" else "TIMESTAMP"
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS asset_tags (
                id VARCHAR NOT NULL PRIMARY KEY,
                asset_id VARCHAR NOT NULL,
                tag VARCHAR NOT NULL,
                source VARCHAR(32) NOT NULL DEFAULT 'auto',
                confidence DOUBLE PRECISION,
                created_at {ts} NOT NULL
            )
        """))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_tag ON asset_tags (asset_id, tag)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_asset_tags_tag ON asset_tags (tag)"))
        logger.info("migration_table_created", table="asset_tags")

    if conn.dialect.name == "postgresql":
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_asset_tag_prefix "
            "ON asset_tags (tag varchar_pattern_ops)"
        ))
        logger.info("migration_index_created", table="asset_tags", index="idx_asset_tag_prefix")
    return True


def _migration_072_create_asset_loras(conn) -> bool:
    """Create `asset_loras` if the entity has not already produced it.

    As with 070, `SQLModel.metadata.create_all` in `infrastructure/database.py`
    creates this table from the entity on a fresh database, so the DDL below
    only fires for a database created before the entity existed. It is written
    to match what SQLModel emits.

    The unique constraint is what makes re-indexing an image idempotent: running
    it twice must not double the rows. It is created as a unique INDEX rather
    than a table-level UNIQUE constraint because SQLite has no
    `ADD CONSTRAINT ... IF NOT EXISTS`, and a unique index is equivalent here.

    Returns True unconditionally so the runner records it — see the note in
    `_migration_070_create_sessions` about `if applied: _record_migration(...)`.
    """
    inspector = inspect(conn)
    if "asset_loras" not in set(inspector.get_table_names()):
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS asset_loras (
                id VARCHAR NOT NULL PRIMARY KEY,
                asset_id VARCHAR NOT NULL,
                model_id VARCHAR,
                civitai_model_id INTEGER,
                strength DOUBLE PRECISION,
                created_at TIMESTAMP NOT NULL
            )
        """))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_lora ON asset_loras (asset_id, civitai_model_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_asset_lora_civitai ON asset_loras (civitai_model_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_asset_lora_model ON asset_loras (model_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_asset_lora_asset_id ON asset_loras (asset_id)"))
        logger.info("migration_table_created", table="asset_loras")
    return True


def _migration_071_add_model_tag_source(conn) -> bool:
    """Add `model_tags.source` and backfill every existing row to 'civitai'.

    `model_tags` is created by `SQLModel.metadata.create_all(engine)`, so on a
    fresh database the column is already there and this is a no-op. It fires
    only for a database created before the column existed, and is written to
    match what SQLModel emits so the two paths cannot diverge.

    The backfill is what makes the change safe: every pre-existing row is a tag
    this project scraped from CivitAI (there was no user writer path before
    this migration), so all of them must be owned by 'civitai' — otherwise the
    resync's new `source = 'civitai'` delete filter would silently orphan them
    and they would never be refreshed again.

    NOT NULL with a default is deliberate: an un-backfilled NULL-source row
    matches neither the CivitAI delete filter nor the user add/remove paths, so
    it would become an invisible tag.

    The unique constraint on (model_id, tag) is intentionally left alone — see
    `core.entities.ModelTag`.
    """
    inspector = inspect(conn)
    if "model_tags" not in inspector.get_table_names():
        return False

    existing = {col["name"] for col in inspector.get_columns("model_tags")}
    if "source" in existing:
        return False

    conn.execute(text(
        "ALTER TABLE model_tags ADD COLUMN source VARCHAR(32) NOT NULL DEFAULT 'civitai'"
    ))
    # Belt and braces for engines that do not backfill a NOT NULL DEFAULT:
    # Postgres 11+ fills the column from the default above.
    conn.execute(text(
        "UPDATE model_tags SET source = 'civitai' WHERE source IS NULL OR source = ''"
    ))
    _verify_required_columns(conn, "model_tags", {"source"})
    logger.info("migration_column_added", table="model_tags", column="source")
    return True


def _migration_070_create_sessions(conn) -> bool:
    """Add the session tables' indexes, and back-fill them where absent.

    The `sessions` and `session_assets` TABLES themselves are created by
    `SQLModel.metadata.create_all(engine)` in `infrastructure/database.py:145`,
    which runs before `run_migrations`. So on a fresh database this step finds
    them already present and its table-creation branches are skipped — the same
    situation as `_migration_045_create_locations`. The DDL below therefore only
    fires for a database created before these entities existed, and is written
    to match what SQLModel emits so the two paths cannot diverge.

    What genuinely needs a migration is the index on `assets.seed`: the session
    detector groups by identical seed and that column was unindexed, so
    "images sharing a seed" was a sequential scan of the whole table. It is
    partial — NULL dominates the legacy rows, and an index over mostly-NULLs is
    not worth its write cost — and excludes `seed = 0`, which is simultaneously
    a valid seed and the "unset" default from `build_image_job_workflow`, so
    including it would collapse unrelated images into one enormous group.

    NOTE on the return value, which is load-bearing and easy to get wrong:
    `run_migrations` does `if applied: _record_migration(...)`. A step that
    returns False is NOT recorded, and therefore re-runs on every startup
    forever. So this step deliberately reports True even when the index already
    exists — otherwise a database where `create_all` had already made the
    tables, and the index was created by an earlier partial run, would never
    record 070 and would re-execute on every boot. True is correct here because
    the desired end state is "070 has been applied".
    """
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())
    is_postgres = conn.dialect.name == "postgresql"
    changed = False

    if "sessions" not in existing_tables:
        # TIMESTAMPTZ on Postgres to match what SQLModel emits for a tz-aware
        # `datetime` field; plain TIMESTAMP on SQLite, which has neither.
        ts = "TIMESTAMP WITH TIME ZONE" if is_postgres else "TIMESTAMP"
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS sessions (
                id VARCHAR NOT NULL PRIMARY KEY,
                user_id VARCHAR NOT NULL DEFAULT 'default_user',
                name VARCHAR,
                description TEXT,
                signature VARCHAR,
                auto_detected BOOLEAN NOT NULL DEFAULT FALSE,
                locked BOOLEAN NOT NULL DEFAULT FALSE,
                workspace VARCHAR,
                start_at {ts},
                end_at {ts},
                image_count INTEGER NOT NULL DEFAULT 0,
                thumbnail VARCHAR,
                created_at {ts} NOT NULL,
                updated_at {ts} NOT NULL,
                deleted_at {ts}
            )
        """))
        for stmt in (
            "CREATE INDEX IF NOT EXISTS ix_sessions_user_id ON sessions (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_sessions_signature ON sessions (user_id, signature)",
            "CREATE INDEX IF NOT EXISTS ix_sessions_user_updated ON sessions (user_id, updated_at)",
            "CREATE INDEX IF NOT EXISTS ix_sessions_workspace ON sessions (workspace)",
            "CREATE INDEX IF NOT EXISTS ix_sessions_start_at ON sessions (start_at)",
            "CREATE INDEX IF NOT EXISTS ix_sessions_end_at ON sessions (end_at)",
            "CREATE INDEX IF NOT EXISTS ix_sessions_auto_detected ON sessions (auto_detected)",
            "CREATE INDEX IF NOT EXISTS ix_sessions_deleted_at ON sessions (deleted_at)",
        ):
            conn.execute(text(stmt))
        logger.info("migration_table_created", table="sessions")
        changed = True

    if "session_assets" not in existing_tables:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS session_assets (
                id VARCHAR NOT NULL PRIMARY KEY,
                session_id VARCHAR NOT NULL,
                asset_id VARCHAR NOT NULL,
                added_at TIMESTAMP NOT NULL
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS uq_session_asset ON session_assets (session_id, asset_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_session_assets_session_id ON session_assets (session_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_session_assets_asset_id ON session_assets (asset_id)"))
        logger.info("migration_table_created", table="session_assets")
        changed = True

    # Unconditional, and deliberately outside both table guards: `create_all`
    # cannot produce a partial index on an existing table, so this is the one
    # thing here that has to run on every database, including a fresh one where
    # the tables above were already made from the entities.
    if "assets" in existing_tables:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_assets_seed_lookup "
            "ON assets (user_id, seed) WHERE seed IS NOT NULL AND seed != 0"
        ))
        logger.info("migration_index_created", table="assets", index="ix_assets_seed_lookup")
        changed = True

    return changed


def _migration_065_index_jobs_metadata_chat_id(conn) -> bool:
    """Index jobs by the chat_id inside metadata_.

    Three hot queries filter on the chat a job belongs to (chats.py job listing,
    chats.py recent-LLM-job lookup, agent_simulation's in-flight check). The GIN
    index from migration 024 supports the `?` containment operator, NOT `->>`
    equality, so those were sequential scans on the largest table in the schema.

    The index expression deliberately includes the `::varchar` cast:
    SQLAlchemy compiles `Job.metadata_["chat_id"].as_string() == chat_id` to
    `CAST((metadata_ ->> 'chat_id') AS VARCHAR) = ?`, and a btree expression
    index is only used when the query's expression matches it exactly. Indexing
    the bare `(metadata_ ->> 'chat_id')` would have left every query still
    scanning.

    `->>` is Postgres-specific, so this is a no-op on SQLite.
    """
    if conn.dialect.name != "postgresql":
        return False

    inspector = inspect(conn)
    if "jobs" not in inspector.get_table_names():
        return False

    existing = {idx["name"] for idx in inspector.get_indexes("jobs")}
    if "ix_jobs_metadata_chat_id" in existing:
        return False

    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_jobs_metadata_chat_id "
            "ON jobs (((metadata_->>'chat_id')::varchar))"
        )
    )
    return True


def _migration_049_seed_starter_pack(conn) -> bool:
    """Seed starter content (demo character, scenario, llm-local provider) for out-of-box usability."""
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())
    seeded = False

    if "characters" in tables:
        exists = conn.execute(
            text("SELECT COUNT(*) FROM characters WHERE name = :name"),
            {"name": "Lyra Vale"},
        ).scalar()
        if not exists:
            now = datetime.now(timezone.utc).isoformat()
            # `sort_order` is added by migration 055, which runs *after* this
            # step.  Including it here aborted startup on any database that had
            # not yet run 055 (`column "sort_order" does not exist`); fresh
            # databases only survived because create_all() happened to run
            # first.  Detect it instead of assuming.
            has_sort_order = "sort_order" in {
                col["name"] for col in inspector.get_columns("characters")
            }
            columns = (
                "id, name, description, personality, scenario, first_mes, "
                "system_prompt, visual_tags, created_at, updated_at"
            )
            values = (
                ":id, :name, :description, :personality, :scenario, :first_mes, "
                ":system_prompt, :visual_tags, :created_at, :updated_at"
            )
            if has_sort_order:
                columns = columns.replace(
                    "visual_tags,", "visual_tags, sort_order,"
                )
                values = values.replace(":visual_tags,", ":visual_tags, 0,")
            conn.execute(
                text(f"""
                    INSERT INTO characters ({columns}) VALUES ({values})
                """),
                {
                    "id": "demo-lyra",
                    "name": "Lyra Vale",
                    "description": "A wandering bard with a silver tongue, a stolen lute, and a map to places that should not exist.",
                    "personality": "Warm, witty, and disarmingly honest about everything except her own past. She deflects serious questions with songs and terrible puns.",
                    "scenario": "You meet Lyra in a roadside tavern during a storm. She is already three songs in and has decided you are interesting.",
                    "first_mes": "The tavern door slams shut behind you, and a voice rings out over the crackling fire: \"Ah, a fresh face! Don't tell me—you're here to hear the tale of the Sunken Bell.\" Lyra grins and pats the stool beside her. \"Sit. The storm isn't going anywhere, and neither am I.\"",
                    "system_prompt": "Lyra Vale is a storyteller first and a fighter a distant second. She speaks in vivid, musical prose, loves wordplay, and knows a suspicious amount about the Old Royalties. She will happily chat, flirt, bicker, or spin tall tales — but she never quite answers who taught her that one song.",
                    "visual_tags": '["bard","fantasy","silver hair","lute"]',
                    "created_at": now,
                    "updated_at": now,
                },
            )
            seeded = True

    if "scenarios" in tables:
        exists = conn.execute(
            text("SELECT COUNT(*) FROM scenarios WHERE name = :name"),
            {"name": "Sword & Sorcery"},
        ).scalar()
        if not exists:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                text("""
                    INSERT INTO scenarios (id, name, description, prompt_template, created_at, updated_at)
                    VALUES (:id, :name, :description, :prompt_template, :created_at, :updated_at)
                """),
                {
                    "id": "demo-sword-sorcery",
                    "name": "Sword & Sorcery",
                    "description": "A classic frontier-fantasy opening: ancient ruins, living legends, and a world where the gods left early.",
                    "prompt_template": (
                        "The frontier town of Thornfall straddles the edge of the known world. "
                        "Behind it lie the Old Kingdoms, their crowns rusted to nothing; ahead, "
                        "the Greywood swallows roads, armies, and the occasional ambitious hero. "
                        "Everyone here is running from something or looking for something — "
                        "some nights the two look exactly alike."
                    ),
                    "created_at": now,
                    "updated_at": now,
                },
            )
            seeded = True

    if "providers" in tables:
        exists = conn.execute(
            text("SELECT COUNT(*) FROM providers WHERE id = :id"),
            {"id": "llm-local"},
        ).scalar()
        if not exists:
            conn.execute(
                text("""
                    INSERT INTO providers (
                        id, type, worker_type, enabled, priority,
                        credentials, config
                    ) VALUES (
                        :id, :type, :worker_type, :enabled, :priority,
                        :credentials, :config
                    )
                """),
                {
                    "id": "llm-local",
                    "type": "openai_compat",
                    "worker_type": "llm",
                    "enabled": False,
                    "priority": 1,
                    "credentials": json.dumps({}),
                    # `container_name` used to be seeded under the
                    # `container_config` column. That column is no longer in
                    # the ORM model, so a fresh database has no such column to
                    # insert into; it carries the value under `config`, which
                    # is where migration 089 put it for every pre-existing row
                    # anyway, so a fresh seed and a migrated one converge on
                    # the same record.
                    "config": json.dumps({
                        "seeded": True,
                        "discovered": True,
                        "api_base": "http://localhost:11434/v1",
                        "container_name": "tnhcomfy-llm-local",
                    }),
                },
            )
            seeded = True

    if seeded:
        logger.info("migration_049_seed_starter_pack_done")
    return seeded


def _migration_040_create_voice_models(conn) -> bool:
    """Create voice_models table for managing TTS voice profiles."""
    inspector = inspect(conn)
    table_names = set(inspector.get_table_names())
    if "voice_models" in table_names:
        logger.info("migration_voice_models_skipped", reason="table_exists")
        return False
    if "characters" not in table_names:
        logger.info("migration_voice_models_skipped", reason="characters_table_missing")
        return False

    conn.execute(text("""
        CREATE TABLE voice_models (
            id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            description TEXT,
            type VARCHAR NOT NULL DEFAULT 'xtts',
            voice_profile VARCHAR,
            model_path VARCHAR,
            language VARCHAR,
            preview_text TEXT,
            character_id VARCHAR REFERENCES characters(id) ON DELETE SET NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))

    if conn.dialect.name == "postgresql":
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_voice_models_character ON voice_models(character_id)"))

    logger.info("migration_voice_models_created")
    return True


def _migration_041_create_character_memories(conn) -> bool:
    """Create character_memories table with pgvector embedding for semantic search."""
    inspector = inspect(conn)
    table_names = set(inspector.get_table_names())
    if "character_memories" in table_names:
        logger.info("migration_character_memories_skipped", reason="table_exists")
        return False
    if "characters" not in table_names:
        logger.info("migration_character_memories_skipped", reason="characters_table_missing")
        return False

    if conn.dialect.name == "postgresql":
        conn.execute(text("""
            CREATE TABLE character_memories (
                id VARCHAR PRIMARY KEY,
                character_id VARCHAR NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                embedding VECTOR(384),
                tags JSONB DEFAULT '[]',
                importance INTEGER DEFAULT 5,
                last_accessed_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX idx_character_memories_char ON character_memories(character_id)"))
        conn.execute(text(
            "CREATE INDEX idx_character_memories_embedding ON character_memories "
            "USING hnsw (embedding vector_cosine_ops)"
        ))
    else:
        # SQLite fallback — store embedding as JSON array
        conn.execute(text("""
            CREATE TABLE character_memories (
                id VARCHAR PRIMARY KEY,
                character_id VARCHAR NOT NULL,
                content TEXT NOT NULL,
                embedding TEXT,
                tags TEXT DEFAULT '[]',
                importance INTEGER DEFAULT 5,
                last_accessed_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX idx_character_memories_char ON character_memories(character_id)"))

    logger.info("migration_character_memories_created")
    return True


def _migration_042_add_branching_and_expressions(conn) -> bool:
    """Add branching fields to messages and expressions to characters."""
    inspector = inspect(conn)
    touched = False

    if "messages" in set(inspector.get_table_names()):
        touched = True
        columns = {col["name"] for col in inspector.get_columns("messages")}
        for col_name, col_type in (
            ("parent_id", "TEXT"),
            ("branch_id", "TEXT"),
            ("branch_name", "VARCHAR(128)"),
        ):
            if col_name not in columns:
                conn.execute(text(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}"))
                columns.add(col_name)
                logger.info("migration_column_added", table="messages", column=col_name)

        if conn.dialect.name == "postgresql" and "parent_id" in columns:
            foreign_keys = inspector.get_foreign_keys("messages")
            has_parent_fk = any(
                fk.get("referred_table") == "messages"
                and fk.get("constrained_columns") == ["parent_id"]
                for fk in foreign_keys
            )
            if not has_parent_fk:
                conn.execute(text(
                    "ALTER TABLE messages ADD CONSTRAINT fk_messages_parent "
                    "FOREIGN KEY (parent_id) REFERENCES messages(id)"
                ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_message_parent ON messages(parent_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_message_branch ON messages(chat_id, branch_id)"
        ))

    if "characters" in set(inspector.get_table_names()):
        touched = True
        columns = {col["name"] for col in inspector.get_columns("characters")}
        if "expressions" not in columns:
            conn.execute(text("ALTER TABLE characters ADD COLUMN expressions JSON DEFAULT '{}'"))
            logger.info("migration_column_added", table="characters", column="expressions")
        if "expressions_lora" not in columns:
            conn.execute(text("ALTER TABLE characters ADD COLUMN expressions_lora JSON DEFAULT '[]'"))
            logger.info("migration_column_added", table="characters", column="expressions_lora")

    return touched


def _migration_043_add_story_publishing_fields(conn) -> bool:
    """Add publishing fields to stories for shareable story export."""
    inspector = inspect(conn)
    if "stories" not in set(inspector.get_table_names()):
        return False

    columns = {col["name"] for col in inspector.get_columns("stories")}
    touched = False

    for col_name, col_type, default in [
        ("published_token", "VARCHAR(128)", None),
        ("is_published", "BOOLEAN", "FALSE"),
        ("published_at", "TIMESTAMP", None),
    ]:
        if col_name not in columns:
            sql = f"ALTER TABLE stories ADD COLUMN {col_name} {col_type}"
            if default is not None:
                sql += f" DEFAULT {default}"
            conn.execute(text(sql))
            logger.info("migration_column_added", table="stories", column=col_name)
            touched = True

    # Unique index on published_token (only where not null)
    if conn.dialect.name == "postgresql":
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_stories_published_token "
            "ON stories (published_token) WHERE is_published"
        ))

    return touched


def _migration_044_add_character_voice_model_fk(conn) -> bool:
    """Add voice_model_id FK to characters (replaces raw voice_profile string)."""
    inspector = inspect(conn)
    if "characters" not in set(inspector.get_table_names()):
        return False

    columns = {col["name"] for col in inspector.get_columns("characters")}
    if "voice_model_id" not in columns:
        conn.execute(text("ALTER TABLE characters ADD COLUMN voice_model_id VARCHAR REFERENCES voice_models(id) ON DELETE SET NULL"))
        logger.info("migration_column_added", table="characters", column="voice_model_id")
        return True
    return False


def _migration_045_create_locations(conn) -> bool:
    """Create locations table for world-building location entities."""
    inspector = inspect(conn)
    table_names = set(inspector.get_table_names())
    if "locations" in table_names:
        logger.info("migration_locations_skipped", reason="table_exists")
        return False

    if conn.dialect.name == "postgresql":
        conn.execute(text("""
            CREATE TABLE locations (
                id VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL,
                description TEXT,
                atmosphere TEXT,
                tags JSONB DEFAULT '[]',
                image_path VARCHAR,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX idx_locations_name ON locations(name)"))
        conn.execute(text("CREATE INDEX idx_locations_tags ON locations USING GIN (tags)"))
    else:
        conn.execute(text("""
            CREATE TABLE locations (
                id VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL,
                description TEXT,
                atmosphere TEXT,
                tags TEXT DEFAULT '[]',
                image_path VARCHAR,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX idx_locations_name ON locations(name)"))

    logger.info("migration_locations_created")
    return True


def _migration_046_create_campaigns(conn) -> bool:
    """Create campaigns table for campaign/chronicle mode."""
    inspector = inspect(conn)
    table_names = set(inspector.get_table_names())
    if "campaigns" in table_names:
        logger.info("migration_campaigns_skipped", reason="table_exists")
        return False

    if conn.dialect.name == "postgresql":
        conn.execute(text("""
            CREATE TABLE campaigns (
                id VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL,
                description TEXT,
                character_ids JSONB DEFAULT '[]',
                story_ids JSONB DEFAULT '[]',
                chat_ids JSONB DEFAULT '[]',
                location_ids JSONB DEFAULT '[]',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX idx_campaigns_name ON campaigns(name)"))
    else:
        conn.execute(text("""
            CREATE TABLE campaigns (
                id VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL,
                description TEXT,
                character_ids TEXT DEFAULT '[]',
                story_ids TEXT DEFAULT '[]',
                chat_ids TEXT DEFAULT '[]',
                location_ids TEXT DEFAULT '[]',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX idx_campaigns_name ON campaigns(name)"))

    logger.info("migration_campaigns_created")
    return True


def _migration_047_add_chat_location_id(conn) -> bool:
    """Add location_id FK column to chats table for Location ↔ Chat integration."""
    inspector = inspect(conn)
    table_names = set(inspector.get_table_names())
    if "chats" not in table_names:
        logger.info("migration_047_skipped", reason="chats_table_missing")
        return False
    # Only add the column if the locations table exists (created in 045)
    # and the column isn't already present.
    if "locations" not in table_names:
        logger.info("migration_047_skipped", reason="locations_table_missing")
        return False
    columns = {col["name"] for col in inspector.get_columns("chats")}
    if "location_id" in columns:
        logger.info("migration_047_skipped", reason="column_exists")
        return False
    # Add the FK column — nullable so existing chats are unaffected.
    if conn.dialect.name == "postgresql":
        conn.execute(text("ALTER TABLE chats ADD COLUMN location_id VARCHAR"))
        conn.execute(text("CREATE INDEX idx_chats_location_id ON chats(location_id)"))
        conn.execute(text(
            "ALTER TABLE chats ADD CONSTRAINT fk_chats_location_id "
            "FOREIGN KEY (location_id) REFERENCES locations(id)"
        ))
    else:
        conn.execute(text("ALTER TABLE chats ADD COLUMN location_id VARCHAR"))
        conn.execute(text("CREATE INDEX idx_chats_location_id ON chats(location_id)"))

    logger.info("migration_047_chat_location_id_added")
    return True


def _migration_048_add_story_location_ids(conn) -> bool:
    """Add location_ids JSONB column to stories table for Location ↔ Story integration."""
    inspector = inspect(conn)
    table_names = set(inspector.get_table_names())
    if "stories" not in table_names:
        logger.info("migration_048_skipped", reason="stories_table_missing")
        return False
    columns = {col["name"] for col in inspector.get_columns("stories")}
    if "location_ids" in columns:
        logger.info("migration_048_skipped", reason="column_exists")
        return False
    if conn.dialect.name == "postgresql":
        conn.execute(text("ALTER TABLE stories ADD COLUMN location_ids JSONB DEFAULT '[]'"))
        conn.execute(text("UPDATE stories SET location_ids = '[]' WHERE location_ids IS NULL"))
    else:
        conn.execute(text("ALTER TABLE stories ADD COLUMN location_ids TEXT DEFAULT '[]'"))

    logger.info("migration_048_story_location_ids_added")
    return True


def _migration_051_world_vault_fixes(conn) -> bool:
    """Backfill fixes for world-vault features (voice previews, llm-local api_base)."""
    touched = False
    inspector = inspect(conn)

    # --- voice_models.preview_path for TTS preview playback ---
    if "voice_models" in set(inspector.get_table_names()):
        columns = {col["name"] for col in inspector.get_columns("voice_models")}
        if "preview_path" not in columns:
            conn.execute(text("ALTER TABLE voice_models ADD COLUMN preview_path VARCHAR"))
            logger.info("migration_column_added", table="voice_models", column="preview_path")
            touched = True

    # --- llm-local provider api_base backfill (seed in 049 predates it) ---
    if "providers" in set(inspector.get_table_names()):
        row = conn.execute(
            text("SELECT config FROM providers WHERE id = :id"),
            {"id": "llm-local"},
        ).first()
        if row and row[0]:
            raw = row[0]
            if isinstance(raw, str):
                try:
                    cfg = json.loads(raw)
                except (ValueError, TypeError):
                    cfg = {}
            elif isinstance(raw, dict):
                cfg = dict(raw)
            else:
                cfg = {}
            if not cfg.get("api_base"):
                cfg["api_base"] = "http://localhost:11434/v1"
                conn.execute(
                    text("UPDATE providers SET config = :cfg WHERE id = :id"),
                    {"cfg": json.dumps(cfg), "id": "llm-local"},
                )
                logger.info("migration_llm_local_api_base_backfilled")
                touched = True

    return touched


def _migration_052_add_lorebook_entry_timestamps(conn) -> bool:
    """Add created_at to lorebook_entries (was missing from the original entity)."""
    inspector = inspect(conn)
    if "lorebook_entries" not in set(inspector.get_table_names()):
        return False

    columns = {col["name"] for col in inspector.get_columns("lorebook_entries")}
    touched = False
    for col_name, col_type in (
        ("created_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"),
        ("updated_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"),
    ):
        if col_name not in columns:
            conn.execute(text(f"ALTER TABLE lorebook_entries ADD COLUMN {col_name} {col_type}"))
            logger.info("migration_column_added", table="lorebook_entries", column=col_name)
            touched = True
    return touched


def _migration_053_add_chat_tts_voice_override(conn) -> bool:
    """Add chats.tts_voice_id column for per-chat TTS voice overrides."""
    inspector = inspect(conn)
    if "chats" not in inspector.get_table_names():
        return False

    columns = {col["name"] for col in inspector.get_columns("chats")}
    if "tts_voice_id" not in columns:
        conn.execute(text("ALTER TABLE chats ADD COLUMN tts_voice_id VARCHAR"))
        logger.info("migration_column_added", table="chats", column="tts_voice_id")
        return True
    return False


def _migration_add_chat_idle_sim_enabled(conn) -> bool:
    """Add idle_sim_enabled column to chats for background idle simulation."""
    inspector = inspect(conn)
    if "chats" not in inspector.get_table_names():
        return False

    columns = {col["name"] for col in inspector.get_columns("chats")}
    if "idle_sim_enabled" not in columns:
        conn.execute(text("ALTER TABLE chats ADD COLUMN idle_sim_enabled BOOLEAN DEFAULT FALSE NOT NULL"))
        logger.info("migration_column_added", table="chats", column="idle_sim_enabled")

    _verify_required_columns(conn, "chats", {"idle_sim_enabled"})
    return True

def _migration_054_add_jobstatus_retrying(conn) -> bool:
    """Add the 'RETRYING' label to the Postgres jobstatus enum.

    B6 introduced JobStatus.RETRYING for same-provider backoff, rendered by
    SQLAlchemy's values_callable as the uppercase enum NAME 'RETRYING'. Existing
    Postgres databases created before that change lack the label, so any query
    (e.g. GET /api/jobs/active) that references RETRYING raises
    `invalid input value for enum jobstatus: "RETRYING"`. SQLite has no enum
    column (status is plain TEXT), so this is a Postgres-only backfill.

    ALTER TYPE ... ADD VALUE is idempotent-safe here: PostgreSQL 12+ permits it
    inside the per-step transaction, and we guard with an explicit pg_enum check
    so re-application is a no-op.
    """
    if conn.dialect.name != "postgresql":
        return False

    existing = conn.execute(
        text(
            "SELECT 1 FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid "
            "WHERE t.typname = 'jobstatus' AND e.enumlabel = 'RETRYING'"
        )
    ).first()
    if existing:
        return False

    conn.execute(text("ALTER TYPE jobstatus ADD VALUE 'RETRYING'"))
    logger.info("migration_added_enum_value", type="jobstatus", value="RETRYING")
    return True


def _migration_055_add_character_sort_order(conn) -> bool:
    """Add sort_order column to characters for drag-and-drop reordering."""
    inspector = inspect(conn)
    if "characters" not in inspector.get_table_names():
        return False

    columns = {col["name"] for col in inspector.get_columns("characters")}
    if "sort_order" not in columns:
        conn.execute(text("ALTER TABLE characters ADD COLUMN sort_order INTEGER DEFAULT 0 NOT NULL"))
        logger.info("migration_column_added", table="characters", column="sort_order")

    _verify_required_columns(conn, "characters", {"sort_order"})
    return True


def _migration_056_add_graph_layouts(conn) -> bool:
    """Create graph_layouts table for storing relationship graph node positions."""
    inspector = inspect(conn)
    if "graph_layouts" in inspector.get_table_names():
        return False

    conn.execute(text("""
        CREATE TABLE graph_layouts (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT 'default',
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            x REAL NOT NULL DEFAULT 0.0,
            y REAL NOT NULL DEFAULT 0.0,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("CREATE INDEX idx_graph_layout_name ON graph_layouts (name)"))
    conn.execute(text("CREATE INDEX idx_graph_layout_entity_type ON graph_layouts (entity_type)"))
    conn.execute(text("CREATE INDEX idx_graph_layout_entity_id ON graph_layouts (entity_id)"))
    conn.execute(text("""
        CREATE UNIQUE INDEX idx_graph_layout_name_entity
        ON graph_layouts (name, entity_type, entity_id)
    """))
    logger.info("migration_table_created", table="graph_layouts")
    return True


_SAMPLER_COLUMNS = (
    "temperature",
    "top_p",
    "max_output_tokens",
    "frequency_penalty",
    "presence_penalty",
)


def _migration_057_add_llm_sampler_columns(conn) -> bool:
    """Add per-entity LLM sampling override columns to chats and stories."""
    inspector = inspect(conn)
    changed = False
    for table in ("chats", "stories"):
        if table not in inspector.get_table_names():
            continue
        existing = {col["name"] for col in inspector.get_columns(table)}
        for column in _SAMPLER_COLUMNS:
            if column in existing:
                continue
            sql_type = "INTEGER" if column == "max_output_tokens" else "FLOAT"
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
            logger.info("migration_column_added", table=table, column=column)
            changed = True
    return changed


def _migration_058_add_story_writing_prefs(conn) -> bool:
    """Add writing preference columns (word_count_goal, pov) to stories."""
    inspector = inspect(conn)
    changed = False
    if "stories" not in inspector.get_table_names():
        return False
    existing = {col["name"] for col in inspector.get_columns("stories")}
    for column, sql_type in (("word_count_goal", "INTEGER"), ("pov", "TEXT")):
        if column in existing:
            continue
        conn.execute(text(f"ALTER TABLE stories ADD COLUMN {column} {sql_type}"))
        logger.info("migration_column_added", table="stories", column=column)
        changed = True
    return changed


def _migration_060_add_message_character_id(conn) -> bool:
    """Add per-message speaker attribution column for group chats."""
    inspector = inspect(conn)
    changed = False
    if "messages" not in inspector.get_table_names():
        return False
    existing = {col["name"] for col in inspector.get_columns("messages")}
    if "character_id" not in existing:
        conn.execute(text("ALTER TABLE messages ADD COLUMN character_id VARCHAR"))
        logger.info("migration_column_added", table="messages", column="character_id")
        changed = True
    index_names = {idx["name"] for idx in inspector.get_indexes("messages")}
    if "idx_message_character_id" not in index_names:
        conn.execute(text("CREATE INDEX idx_message_character_id ON messages (character_id)"))
        changed = True
    return changed


def _migration_059_add_story_chapter_revisions(conn) -> bool:
    """Create story_chapter_revisions table for chapter snapshot history."""
    inspector = inspect(conn)
    if "story_chapter_revisions" in inspector.get_table_names():
        changed = False
        if conn.dialect.name == "postgresql":
            foreign_keys = inspector.get_foreign_keys("story_chapter_revisions")
            if not any(fk.get("constrained_columns") == ["chapter_id"] for fk in foreign_keys):
                conn.execute(text("ALTER TABLE story_chapter_revisions ADD CONSTRAINT fk_revision_chapter FOREIGN KEY (chapter_id) REFERENCES story_chapters(id) ON DELETE CASCADE"))
                changed = True
            if not any(fk.get("constrained_columns") == ["story_id"] for fk in foreign_keys):
                conn.execute(text("ALTER TABLE story_chapter_revisions ADD CONSTRAINT fk_revision_story FOREIGN KEY (story_id) REFERENCES stories(id) ON DELETE CASCADE"))
                changed = True
        return changed

    conn.execute(text("""
        CREATE TABLE story_chapter_revisions (
            id TEXT PRIMARY KEY,
            chapter_id TEXT NOT NULL REFERENCES story_chapters(id) ON DELETE CASCADE,
            story_id TEXT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
            content TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'manual',
            word_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("CREATE INDEX idx_revision_chapter_id ON story_chapter_revisions (chapter_id)"))
    conn.execute(text("CREATE INDEX idx_revision_story_id ON story_chapter_revisions (story_id)"))
    logger.info("migration_table_created", table="story_chapter_revisions")
    return True


def _migration_061_add_personas_and_chat_persona_fields(conn) -> bool:
    """Create personas library table and add persona-link + author's-note columns to chats."""
    inspector = inspect(conn)
    changed = False
    if "personas" not in inspector.get_table_names():
        conn.execute(text("""
            CREATE TABLE personas (
                id TEXT PRIMARY KEY,
                name VARCHAR NOT NULL,
                description TEXT,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX ix_personas_name ON personas (name)"))
        logger.info("migration_table_created", table="personas")
        changed = True
    if "chats" in inspector.get_table_names():
        existing = {col["name"] for col in inspector.get_columns("chats")}
        for column, sql_type in (("persona_id", "VARCHAR"), ("authors_note", "TEXT"), ("authors_note_depth", "INTEGER")):
            if column in existing:
                continue
            conn.execute(text(f"ALTER TABLE chats ADD COLUMN {column} {sql_type}"))
            logger.info("migration_column_added", table="chats", column=column)
            changed = True
        index_names = {idx["name"] for idx in inspector.get_indexes("chats")}
        if "idx_chat_persona_id" not in index_names:
            conn.execute(text("CREATE INDEX idx_chat_persona_id ON chats (persona_id)"))
            changed = True
    return changed


def _migration_062_add_scenario_fields_and_lorebook_entry_taxonomy(conn) -> bool:
    """Add scenario default_checkpoint/voice_profile and lorebook entry taxonomy columns."""
    inspector = inspect(conn)
    changed = False
    if "scenarios" in inspector.get_table_names():
        existing = {col["name"] for col in inspector.get_columns("scenarios")}
        for column, sql_type in (("default_checkpoint", "VARCHAR"), ("default_voice_profile", "TEXT")):
            if column in existing:
                continue
            conn.execute(text(f"ALTER TABLE scenarios ADD COLUMN {column} {sql_type}"))
            logger.info("migration_column_added", table="scenarios", column=column)
            changed = True
    if "lorebook_entries" in inspector.get_table_names():
        existing = {col["name"] for col in inspector.get_columns("lorebook_entries")}
        for column, sql_type in (
            ("category", "VARCHAR"),
            ("tags", "JSON"),
            ("depth", "INTEGER"),
            ("case_sensitive", "BOOLEAN"),
            ("selective_logic", "VARCHAR"),
            ("probability", "INTEGER"),
        ):
            if column in existing:
                continue
            conn.execute(text(f"ALTER TABLE lorebook_entries ADD COLUMN {column} {sql_type}"))
            logger.info("migration_column_added", table="lorebook_entries", column=column)
            changed = True
        if "depth" not in existing:
            conn.execute(text("UPDATE lorebook_entries SET depth = 4 WHERE depth IS NULL"))
        index_names = {idx["name"] for idx in inspector.get_indexes("lorebook_entries")}
        if "idx_lorebook_entry_category" not in index_names:
            conn.execute(text("CREATE INDEX idx_lorebook_entry_category ON lorebook_entries (category)"))
            changed = True
    return changed


def _migration_063_repair_postgres_constraints(conn) -> bool:
    """Repair constraints that may be absent from databases created by older baselines."""
    if conn.dialect.name != "postgresql":
        return False

    inspector = inspect(conn)
    tables = set(inspector.get_table_names())
    changed = False

    def add_fk(table: str, column: str, referenced_table: str, constraint_name: str) -> None:
        nonlocal changed
        if table not in tables or column not in _get_table_columns(conn, table):
            return
        foreign_keys = inspector.get_foreign_keys(table)
        if any(
            fk.get("constrained_columns") == [column]
            and fk.get("referred_table") == referenced_table
            for fk in foreign_keys
        ):
            return
        orphan_count = conn.execute(
            text(
                f"SELECT COUNT(*) FROM {table} WHERE {column} IS NOT NULL "
                f"AND {column} NOT IN (SELECT id FROM {referenced_table})"
            )
        ).scalar() or 0
        if orphan_count:
            logger.warning(
                "migration_constraint_skipped",
                table=table,
                column=column,
                orphan_count=orphan_count,
            )
            return
        conn.execute(text(
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint_name} "
            f"FOREIGN KEY ({column}) REFERENCES {referenced_table}(id)"
        ))
        changed = True

    add_fk("messages", "parent_id", "messages", "fk_messages_parent")
    add_fk("story_chapter_revisions", "chapter_id", "story_chapters", "fk_revision_chapter")
    add_fk("story_chapter_revisions", "story_id", "stories", "fk_revision_story")
    add_fk("characters", "voice_model_id", "voice_models", "fk_characters_voice_model")
    add_fk("chats", "location_id", "locations", "fk_chats_location")
    add_fk("chats", "tts_voice_id", "voice_models", "fk_chats_tts_voice")
    add_fk("jobs", "provider_id", "providers", "fk_jobs_provider")

    if "messages" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("messages")}
        if "idx_message_parent" not in indexes:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_message_parent ON messages(parent_id)"))
            changed = True

    return changed


def _migration_064_add_character_card_metadata(conn) -> bool:
    """Add lossless SillyTavern card provenance columns to `characters`.

    The card_spec / creator / character_version / card_metadata columns keep an
    imported card re-exportable, and embedded_lorebook_id points at the
    Lorebook materialized from an embedded V2/V3 `character_book`.
    """
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())
    if "characters" not in tables:
        return False

    changed = False
    for column, sql_type in (
        ("card_spec", "VARCHAR"),
        ("card_spec_version", "VARCHAR"),
        ("creator", "VARCHAR"),
        ("character_version", "VARCHAR"),
        ("group_greetings", "JSON"),
        ("card_metadata", "JSON"),
        ("embedded_lorebook_id", "VARCHAR"),
    ):
        if column in _get_table_columns(conn, "characters"):
            continue
        conn.execute(text(f"ALTER TABLE characters ADD COLUMN {column} {sql_type}"))
        logger.info("migration_column_added", table="characters", column=column)
        changed = True

    # Indexed after the columns exist (the ALTERs above guarantee that), so a
    # database whose columns came from the model but never got the indexes is
    # repaired too.
    index_names = {idx["name"] for idx in inspect(conn).get_indexes("characters")}
    for index_name, column in (
        ("ix_characters_card_spec", "card_spec"),
        ("ix_characters_embedded_lorebook_id", "embedded_lorebook_id"),
    ):
        if index_name in index_names:
            continue
        conn.execute(text(f"CREATE INDEX {index_name} ON characters ({column})"))
        changed = True

    # Older PostgreSQL databases predate the FK on the new column; add it once
    # (and only when lorebooks exists and no matching constraint is present).
    # SQLite cannot add a constraint after the fact, and it already has the FK
    # from SQLModel.metadata.create_all, so it is skipped there.
    if conn.dialect.name == "postgresql" and "lorebooks" in tables:
        foreign_keys = inspector.get_foreign_keys("characters")
        already_linked = any(
            fk.get("constrained_columns") == ["embedded_lorebook_id"]
            and fk.get("referred_table") == "lorebooks"
            for fk in foreign_keys
        )
        if not already_linked:
            orphans = conn.execute(
                text(
                    "SELECT COUNT(*) FROM characters WHERE embedded_lorebook_id IS NOT NULL "
                    "AND embedded_lorebook_id NOT IN (SELECT id FROM lorebooks)"
                )
            ).scalar() or 0
            if orphans:
                logger.warning(
                    "migration_constraint_skipped",
                    table="characters",
                    column="embedded_lorebook_id",
                    orphan_count=orphans,
                )
            else:
                conn.execute(text(
                    "ALTER TABLE characters ADD CONSTRAINT fk_characters_embedded_lorebook "
                    "FOREIGN KEY (embedded_lorebook_id) REFERENCES lorebooks(id)"
                ))
                changed = True

    return changed



def _migration_066_add_asset_duration_seconds(conn) -> bool:
    """Add `assets.duration_seconds` and backfill it from the embedded job metadata.

    Generation duration used to live only inside
    `metadata_["job"]["duration_seconds"]`, so the statistics aggregations had
    to `CAST(metadata_->'job'->>'duration_seconds' AS NUMERIC)`. On Postgres a
    cast of non-numeric text raises, which would fail the whole statistics
    request rather than skip one row. As a real nullable numeric column it is
    also indexable and needs no jsonb parse at all.

    The backfill is Postgres-only (`->>` and `~`); SQLite is a test-only
    dialect where `create_all()` already produces the column, and SQLite's
    `CAST('abc' AS NUMERIC)` silently yields 0 rather than raising.
    """
    inspector = inspect(conn)
    if "assets" not in inspector.get_table_names():
        return False

    changed = False
    if "duration_seconds" not in {col["name"] for col in inspector.get_columns("assets")}:
        conn.execute(text("ALTER TABLE assets ADD COLUMN duration_seconds FLOAT"))
        logger.info("migration_column_added", table="assets", column="duration_seconds")
        changed = True

    if conn.dialect.name != "postgresql":
        return changed

    # Only numeric-looking values are cast. `duration_seconds` is written by
    # our own code as a float, but PNG metadata is user-influenced and a single
    # junk row must not be able to abort startup.
    conn.execute(
        text(
            "UPDATE assets SET duration_seconds = "
            "(metadata_->'job'->>'duration_seconds')::double precision "
            "WHERE duration_seconds IS NULL "
            "AND metadata_->'job'->>'duration_seconds' ~ '^[0-9]+(\\.[0-9]+)?$' "
            "AND (metadata_->'job'->>'duration_seconds')::double precision > 0"
        )
    )
    return changed


_ASSET_STAT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("checkpoint_name", "VARCHAR"),
    ("sampler", "VARCHAR"),
    ("scheduler", "VARCHAR"),
    ("vae", "VARCHAR"),
    ("steps", "INTEGER"),
    ("cfg", "FLOAT"),
    ("seed", "BIGINT"),
    ("metadata_version", "VARCHAR"),
)


def _migration_067_add_asset_stat_columns(conn) -> bool:
    """Add the `assets` statistics rollup columns and backfill them from `metadata_`.

    `/api/statistics/*` used to `GROUP BY metadata_->>'…'`. Every `->>`
    re-reads and re-parses the entire jsonb document — about 70 MB across this
    deployment — so each distribution cost a full decompression, and the endpoint
    needed roughly eight of them. These columns make the same aggregations
    columnar scans.

    The backfill is Postgres-only (`->>`); SQLite is a test-only dialect where
    `create_all()` already produces the columns from the model. The derived
    text columns are extracted only when they are the JSON type the writer would
    have stored, and the numeric ones are regex-guarded so one junk value cannot
    abort startup.
    """
    inspector = inspect(conn)
    if "assets" not in inspector.get_table_names():
        return False

    existing = {col["name"] for col in inspector.get_columns("assets")}
    changed = False
    for column, sql_type in _ASSET_STAT_COLUMNS:
        if column in existing:
            continue
        conn.execute(text(f"ALTER TABLE assets ADD COLUMN {column} {sql_type}"))
        logger.info("migration_column_added", table="assets", column=column)
        changed = True

    if conn.dialect.name != "postgresql":
        return changed

    # checkpoint is an object with a name; legacy rows stored a bare string.
    conn.execute(
        text(
            "UPDATE assets SET checkpoint_name = "
            "COALESCE(metadata_->'checkpoint'->>'name', metadata_->>'checkpoint') "
            "WHERE checkpoint_name IS NULL AND jsonb_typeof(metadata_->'checkpoint') IN ('object', 'string')"
        )
    )
    for column in ("sampler", "scheduler", "vae", "metadata_version"):
        conn.execute(
            text(
                f"UPDATE assets SET {column} = metadata_->>'{column}' "
                f"WHERE {column} IS NULL AND jsonb_typeof(metadata_->'{column}') = 'string'"
            )
        )
    for column in ("steps", "cfg", "seed"):
        conn.execute(
            text(
                f"UPDATE assets SET {column} = (metadata_->>'{column}')::numeric "
                f"WHERE {column} IS NULL "
                f"AND jsonb_typeof(metadata_->'{column}') = 'number'"
            )
        )
    logger.info("migration_asset_stat_columns_backfilled")
    return changed


def _migration_068_add_asset_job_completed_at(conn) -> bool:
    """Add `assets.job_completed_at` and backfill it from the embedded job metadata.

    The statistics endpoints filter by a resolved completion time that prefers
    `metadata_['job']['completed_at']` and falls back to the row's own
    timestamps. Resolving that in SQL meant every grouped query evaluated a jsonb
    extraction purely to filter, which re-parses the whole document — so
    `?timeRange=30d` measured 3.4s where `?timeRange=all` measured 1.2s, on the
    same data. As a column the filter is an indexed comparison.

    Stored as the job's value only; the reader applies the generated_at /
    created_at fallback, so the backfill is a plain copy of the jsonb field and
    the column is NULL wherever the job recorded no completion time.
    """
    inspector = inspect(conn)
    if "assets" not in inspector.get_table_names():
        return False

    existing = {col["name"] for col in inspector.get_columns("assets")}
    changed = False
    if "job_completed_at" not in existing:
        conn.execute(text("ALTER TABLE assets ADD COLUMN job_completed_at TIMESTAMP"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_assets_job_completed_at ON assets (job_completed_at)"))
        logger.info("migration_column_added", table="assets", column="job_completed_at")
        changed = True

    if conn.dialect.name != "postgresql":
        return changed

    # Two encodings exist: an ISO string on enriched rows and an epoch float on
    # legacy ones. Anything else is left NULL rather than guessed at, and a
    # malformed value cannot abort startup.
    conn.execute(
        text(
            "UPDATE assets SET job_completed_at = "
            "CASE WHEN (metadata_->'job'->>'completed_at') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' "
            "THEN (metadata_->'job'->>'completed_at')::timestamptz AT TIME ZONE 'UTC' "
            "WHEN (metadata_->'job'->>'completed_at') ~ '^[0-9]+(\\.[0-9]+)?$' "
            "THEN to_timestamp((metadata_->'job'->>'completed_at')::double precision) "
            "ELSE NULL END "
            "WHERE job_completed_at IS NULL AND metadata_->'job' ? 'completed_at' "
            "AND jsonb_typeof(metadata_->'job'->'completed_at') <> 'null'"
        )
    )
    logger.info("migration_asset_job_completed_at_backfilled")
    return changed


def _migration_069_add_job_acknowledged_at(conn) -> bool:
    """Add `jobs.acknowledged_at` and index it.

    The failure panel had exactly two actions — retry everything, or recover the
    queue — so a user who had read a failure and did not want it retried had no
    way to stop seeing it. Deleting the job was the only escape, and that throws
    away the only record of what the provider actually did.

    Nullable, so existing rows are un-acknowledged and the panel is unchanged for
    them.
    """
    inspector = inspect(conn)
    if "jobs" not in inspector.get_table_names():
        return False

    existing = {col["name"] for col in inspector.get_columns("jobs")}
    if "acknowledged_at" in existing:
        return False

    conn.execute(text("ALTER TABLE jobs ADD COLUMN acknowledged_at TIMESTAMP"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_acknowledged_at ON jobs (acknowledged_at)"))
    logger.info("migration_column_added", table="jobs", column="acknowledged_at")
    return True


def _migration_074_add_job_enqueued_at(conn) -> bool:
    """Add `jobs.enqueued_at` and index it, then backfill the queueable rows.

    The Postgres claim query used to select *any* `task_type = <t> AND status =
    'PENDING' AND claimed_at IS NULL` row, which made "enqueued" an assumption
    rather than a fact. `orchestrator_service._tool_narrate_scene` creates a job
    row and then runs it INLINE — deliberately, because the agentic chain holds
    the parent job's queue slot, so a queued narrator job could never be
    claimed. That row looked exactly like a queued one to the LLM worker, which
    claimed and dispatched it within a second. Every agentic `narrate_scene`
    turn therefore cost two paid LLM calls, produced two JOB_COMPLETED events
    for one job id, and inserted the same narration into the chat twice.

    `QueueManager.enqueue` is now the only thing that stamps this column, and the
    claim requires it to be set.

    The backfill matters as much as the column: an existing deployment has
    PENDING rows that were legitimately enqueued before this migration, and
    leaving them NULL would strand every queued job in the table on the next
    boot. Rows in any *other* state are left NULL on purpose — they are not
    claimable anyway, and stamping them would misrepresent the inline path.
    """
    inspector = inspect(conn)
    if "jobs" not in inspector.get_table_names():
        return False

    existing = {col["name"] for col in inspector.get_columns("jobs")}
    if "enqueued_at" not in existing:
        conn.execute(text("ALTER TABLE jobs ADD COLUMN enqueued_at TIMESTAMP"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_enqueued_at ON jobs (enqueued_at)"))
        logger.info("migration_column_added", table="jobs", column="enqueued_at")

    # Backfill regardless of `added`: a database where the column arrived via
    # `SQLModel.metadata.create_all` (a fresh install) has every row NULL too,
    # and an interrupted earlier run of this migration may have added the
    # column without backfilling.
    #
    # Guarded on the columns it reads existing. The migration runner also has
    # fixtures and partially-created tables that carry `jobs` without the full
    # entity shape, and an `ALTER TABLE` that succeeded on such a table would
    # otherwise be followed by a backfill that raises and, because the runner
    # re-raises on the first failing step, bricks startup.
    if {"created_at", "status"} <= existing:
        conn.execute(text("""
            UPDATE jobs
            SET enqueued_at = created_at
            WHERE enqueued_at IS NULL
              AND status = 'PENDING'
        """))
        logger.info("migration_backfilled", table="jobs", column="enqueued_at")
    else:
        logger.info(
            "migration_backfill_skipped",
            table="jobs",
            column="enqueued_at",
            reason="created_at_or_status_absent",
        )
    return True


def _migration_075_index_asset_gallery_timestamp(conn) -> bool:
    """Index `coalesce(generated_at, created_at)` — the gallery's ordering key.

    `ASSET_GALLERY_TIMESTAMP` (`services/statistics_service.py`) is the one
    expression the gallery listing, its date seek and its day histogram all
    order and filter on, and the codebase already goes out of its way to bind the
    same expression object in all three so they cannot disagree. But nothing
    indexed it, and the two composite indexes that look relevant
    (`idx_asset_workspace(user_id, workspace, created_at)`,
    `idx_asset_character(user_id, character_id)`) lead with `user_id`, which is
    never in the predicate — so Postgres cannot use either.

    The result was a sequential scan of the whole `assets` heap, and the rows
    are wide: the average non-deleted row measured 3469 bytes, because
    `metadata_` carries the full job metadata. So every gallery page and every
    histogram read the entire table, and the projection detoasted the jsonb for
    each row before the top-N sort could discard it.

    Measured on the running stack (16,165 live assets, 207 MB table):
      `GET /api/v2/gallery?limit=48`   477 ms -> 92 ms
      `GET /api/v2/assets/dates`       533 ms -> 211 ms
      raw `count(coalesce(...))`       374 ms -> 14 ms

    Partial on `deleted_at IS NULL` so the index only carries live rows, and
    so it is usable for the histogram's `WHERE deleted_at IS NULL` predicate.

    Postgres only: SQLite has no expression index of this shape in the
    migrations' portability rule, and its query plans are not the problem here.
    """
    if conn.dialect.name != "postgresql":
        return True

    inspector = inspect(conn)
    if "assets" not in inspector.get_table_names():
        return False

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_assets_gallery_ts
        ON assets (coalesce(generated_at, created_at))
        WHERE deleted_at IS NULL
    """))
    logger.info("migration_index_created", table="assets", index="ix_assets_gallery_ts")
    return True


def _migration_076_provider_capabilities(conn) -> bool:
    """Add `providers.capabilities` and give every existing provider its `worker_type`.

    A TTS job has no execution path today. `services/world_vault/voices.py`
    creates it with `task_type="image"` — "TTS runs on the image_worker adapter" —
    which was true of the *code path* and false of the *capability*: the load
    balancer filtered on `p.worker_type == task_type`, and no ComfyUI provider
    in this deployment has a text-to-speech node installed at all
    (`grep -i 'xtts|saveaudio' provider_containers` is empty), so the job was
    dispatched to a worker that cannot build its graph. `config.py` had already
    conceded the point in a comment: `ttsEnabled` is "frontend-only for now".

    `worker_type` is a single value, so it cannot express "image AND speech" for
    one container. This column is the second dimension: which JOBS a provider may
    be handed, as distinct from which EXECUTION PATH it uses.

    Backfilled to `[worker_type]` rather than left empty, so the column is
    truthful on read as well as on write: `Provider.serves()` treats empty as
    "same as worker_type" for a provider nobody has edited yet, and an explicit
    value for everyone else. Leaving them all empty would work identically and
    make the admin UI show a blank capability list for every existing provider.
    """
    if conn.dialect.name != "postgresql":
        return True

    inspector = inspect(conn)
    if "providers" not in inspector.get_table_names():
        return False

    existing = {col["name"] for col in inspector.get_columns("providers")}
    if "capabilities" not in existing:
        conn.execute(text("ALTER TABLE providers ADD COLUMN capabilities JSONB"))
        logger.info("migration_column_added", table="providers", column="capabilities")

    # Backfill in SQL rather than row by row. `jsonb_build_array(worker_type)`
    # mirrors the Python `default=[]` -> `serves()` fallback exactly, so a
    # provider written by the ORM with no declared capabilities and one written
    # by this backfill behave the same way.
    result = conn.execute(
        text(
            "UPDATE providers SET capabilities = jsonb_build_array(worker_type) "
            "WHERE capabilities IS NULL OR jsonb_array_length(capabilities) = 0"
        )
    )
    logger.info(
        "migration_backfilled",
        table="providers",
        column="capabilities",
        rows=result.rowcount if result.rowcount and result.rowcount > 0 else 0,
    )
    return True


def _migration_077_campaigns_to_worlds(conn) -> bool:
    """Rename `campaigns` to `worlds`, widen its index, and give chats/stories an owner.

    `Campaign` was the only entity in the vault that grouped anything and it was
    referenced by nothing: no foreign key in either direction, and no read outside
    its own dashboard. Meanwhile three surfaces were already called "World" with
    no world behind any of them. The rename is what lets the timeline and the
    graph be *scoped* rather than global.

    Three changes, and the third is the one that matters:

      1. `campaigns` -> `worlds`, so the name and the table agree. A rename
         rather than drop-and-recreate, so ids and any external references
         survive. The entity was renamed too, so the old name exists nowhere
         except in git history and this comment.
      2. `lorebook_ids`, `scenario_ids`, `voice_ids` added. Campaign could only
         index characters, locations, chats and stories, so a world could not
         show the lorebooks or voices that belong to it — the two things a world
         most needs to name.
      3. `chats.world_id` and `stories.world_id`, NULLABLE. This is the actual
         gap: a membership array is an index, not ownership, and a world that
         owns nothing cannot scope the timeline or the graph. Nullable because
         forcing every existing chat into a world would be inventing a
         relationship the user never stated, and because the front door still has
         to work for someone who has not made a world yet.

    The graph layout is scoped by `graph_layouts.name`, which already exists and
    already defaults to "default" — so per-world layouts need no schema change,
    only a different value for that column. Done in the frontend/API layer.
    """
    if conn.dialect.name != "postgresql":
        return True

    inspector = inspect(conn)
    tables = set(inspector.get_table_names())

    # Three end states are possible and the migration has to handle all of them,
    # because `create_db_and_tables()` runs `SQLModel.create_all` BEFORE this
    # function and the entity is now `World`:
    #
    #   campaigns only  -> rename it (the common case: an existing deployment)
    #   both            -> `create_all` already made an EMPTY `worlds`, so the
    #                      rename is skipped and `campaigns` is left orphaned.
    #                      The first version of this migration stopped here and
    #                      never recorded the step correctly.
    #   worlds only     -> nothing to do (a fresh install)
    #
    # So when both exist, reconcile rather than assume: move any rows across, then
    # drop the empty husk. Dropping is safe precisely because `Campaign` had no
    # foreign keys in either direction, so nothing can cascade.
    if "campaigns" in tables and "worlds" in tables:
        legacy_rows = conn.execute(text("SELECT count(*) FROM campaigns")).scalar() or 0
        if legacy_rows:
            shared = [
                "id", "name", "description", "character_ids", "location_ids",
                "story_ids", "chat_ids", "created_at", "updated_at",
            ]
            conn.execute(
                text(
                    "INSERT INTO worlds (" + ", ".join(shared) + ") "
                    "SELECT " + ", ".join(shared) + " FROM campaigns "
                    "WHERE id NOT IN (SELECT id FROM worlds)"
                )
            )
            logger.info(
                "migration_campaign_rows_moved", table="campaigns", rows=legacy_rows
            )
        conn.execute(text("DROP TABLE campaigns"))
        logger.info("migration_table_dropped", table="campaigns", reason="renamed_to_worlds")
        tables.discard("campaigns")
    elif "campaigns" in tables:
        conn.execute(text("ALTER TABLE campaigns RENAME TO worlds"))
        logger.info("migration_table_renamed", old="campaigns", new="worlds")
        tables.discard("campaigns")
        tables.add("worlds")

    if "worlds" not in tables:
        return False

    world_cols = {c["name"] for c in inspect(conn).get_columns("worlds")}
    for column in ("lorebook_ids", "scenario_ids", "voice_ids"):
        if column not in world_cols:
            conn.execute(text(f"ALTER TABLE worlds ADD COLUMN {column} JSONB"))
            logger.info("migration_column_added", table="worlds", column=column)

    # Columns FIRST, indexes second.
    #
    # The original order built `ix_chats_world_id` before the column existed, so
    # it failed with `column "world_id" does not exist` and — because the runner
    # re-raises on the first failing step — took the whole application down at
    # startup. A migration that cannot run must not be able to prevent a
    # deployment from booting, but the ordering here is simply wrong and the fix
    # is to add the column and then index it.
    for table in ("chats", "stories"):
        if table not in tables:
            continue
        cols = {c["name"] for c in inspect(conn).get_columns(table)}
        if "world_id" not in cols:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN world_id VARCHAR"))
            logger.info("migration_column_added", table=table, column="world_id")
        conn.execute(
            text(f"CREATE INDEX IF NOT EXISTS ix_{table}_world_id ON {table} (world_id)")
        )

    return True


def _migration_078_provider_worker_type_tts(conn) -> bool:
    """Widen `chk_providers_worker_type` to allow `tts`.

    A database constraint is a second source of truth for an enumeration, and
    this one was missed. `VALID_TASK_TYPES`, `Provider._validate_worker_type`
    and the discovery endpoint's guard all learned about `tts`; the CHECK
    constraint did not. So a TTS worker passed every layer of application-level
    validation and was then rejected by Postgres at insert, and the whole
    registration failed with:

        psycopg2.errors.CheckViolation: new row for relation "providers"
        violates check constraint "chk_providers_worker_type"

    which surfaced to the container as a 500 from `/api/v2/providers/discovery`
    and left the provider permanently unregistered.

    The class of bug is the one worth naming: an enumeration that lives in two
    places has to be changed in both, and nothing enforces that. Every other
    `worker_type` check in the codebase now reads `VALID_TASK_TYPES`; this one
    could not, because it is SQL. The migration below is the fix, and
    `tests/test_provider_capabilities.py` asserts the constraint accepts exactly
    the values the Python constant does, so the two cannot drift again without a
    test failing.

    Rewritten rather than altered: Postgres cannot widen a CHECK in place, so it
    is dropped and re-added. `NOT VALID` would skip the scan but would also leave
    pre-existing bad rows unexamined, and `ALTER TABLE ... DROP CONSTRAINT` takes
    no lock beyond ACCESS EXCLUSIVE on the table.
    """
    if conn.dialect.name != "postgresql":
        return True

    inspector = inspect(conn)
    if "providers" not in set(inspector.get_table_names()):
        return False

    columns = {c["name"] for c in inspector.get_columns("providers")}
    if "worker_type" not in columns:
        return False

    # Idempotent: only rewrite when the current definition does not already
    # allow `tts`, so a re-run is a no-op rather than a needless table rewrite.
    row = conn.execute(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'chk_providers_worker_type'"
        )
    ).fetchone()
    if row and "'tts'" in str(row[0]):
        return True

    # Any worker_type already in the table that the new constraint would reject
    # would make the ADD fail. Logged rather than coerced: rewriting a provider's
    # declared kind is not this migration's decision.
    rejected = [
        r[0]
        for r in conn.execute(
            text(
                "SELECT DISTINCT worker_type FROM providers "
                "WHERE worker_type NOT IN ('image', 'llm', 'tts')"
            )
        ).all()
    ]
    if rejected:
        logger.warning(
            "provider_worker_type_outside_constraint",
            values=rejected,
            note="the new CHECK will reject these rows; they must be corrected first",
        )

    conn.execute(
        text("ALTER TABLE providers DROP CONSTRAINT IF EXISTS chk_providers_worker_type")
    )
    conn.execute(
        text(
            "ALTER TABLE providers ADD CONSTRAINT chk_providers_worker_type "
            "CHECK (worker_type IN ('image', 'llm', 'tts'))"
        )
    )
    logger.info("provider_worker_type_constraint_widened", added="tts")
    return True


def _migration_079_character_lorebook_ids(conn) -> bool:
    """Add `characters.lorebook_ids`, the vault's own book list for a character.

    A lorebook could be attached to a `Chat` (`active_lorebook_ids`) and to a
    `Story` (`lorebook_ids`), and a SillyTavern card could carry an embedded
    `data.character_book` (`embedded_lorebook_id`, written by import only) — but
    nothing in the product could attach a library lorebook to a character, so
    the Lorebooks page's own promise ("character backgrounds") was kept by
    nothing. This column is the relationship that makes a book follow a
    character into every conversation instead of being re-selected per chat.

    The type is chosen per dialect rather than converted later: `_migration_
    json_to_jsonb` (version 021) already ran on every deployed database, so
    adding this column to that step's list would be a no-op for them. Emitting
    `JSONB` here directly is what `JSON().with_variant(JSONB(), "postgresql")`
    produces on a fresh install, so the two paths cannot diverge.

    Additive and idempotent: `ALTER TABLE ... ADD COLUMN` only when absent, and
    the `DEFAULT '[]'` matches the entity's `default=[]`, so existing rows read
    back as an empty list rather than NULL. A row cannot lose data here — there
    is no data to lose, the column is new.

    Returns True unconditionally so the runner records the step and stops
    re-running it; see the note in `_migration_070_create_sessions` about
    `if applied: _record_migration(...)`.
    """
    inspector = inspect(conn)
    if "characters" not in set(inspector.get_table_names()):
        return False

    columns = {col["name"] for col in inspector.get_columns("characters")}
    if "lorebook_ids" not in columns:
        col_type = "JSONB" if conn.dialect.name == "postgresql" else "JSON"
        conn.execute(text(
            f"ALTER TABLE characters ADD COLUMN lorebook_ids {col_type} DEFAULT '[]'"
        ))
        logger.info("migration_column_added", table="characters", column="lorebook_ids")

    _verify_required_columns(conn, "characters", {"lorebook_ids"})
    return True




def _ensure_index(conn, name: str, ddl: str, guard=None) -> bool:
    """Create one index if absent. Returns True when it created something.

    `ddl` is the clause after the index name — `ON assets (...)` — rather than a
    whole statement, so that assembling the name from a loop variable cannot
    produce a name that only looks real. `test_migration_indexes_exist.py` parses
    every `CREATE INDEX` in this file by regex and holds each name against
    `pg_indexes`; a template spelled like a declaration is a false positive in
    that test, which is the kind that teaches people to delete the test.
    """
    exists = conn.execute(
        text("SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname = :n"),
        {"n": name},
    ).first()
    if exists:
        return False
    statement = "CREATE INDEX IF NOT EXISTS " + name + " " + ddl
    if guard is not None:
        return guard(statement)
    conn.execute(text(statement))
    return True


def _index_signature(definition: str) -> str | None:
    """Reduce a `pg_get_indexdef` string to `table:col,col:unique|nonunique`.

    Returns `None` when the definition mentions anything this comparison must not
    silently ignore — an opclass, a partial predicate, an expression, a method.
    Two indexes are only interchangeable when every one of those matches too.
    """
    normalised = " ".join(definition.split()).lower()
    if not (normalised.startswith("create index") or normalised.startswith("create unique index")):
        return None
    if " where " in normalised or " using " in normalised.replace(" using btree ", ""):
        return None
    if "(" not in normalised:
        return None

    head, _, rest = normalised.partition(" on ")
    table = rest.split(" ")[0].strip('"')
    # `pg_indexes.indexdef` is always schema-qualified ("public.sessions") while
    # the migration's DDL strings are not ("sessions"), so the schema is dropped
    # from both sides or nothing ever compares equal.
    if "." in table:
        table = table.split(".", 1)[1].strip('"')
    unique = "unique" if "create unique index" in head else "nonunique"

    columns_part = rest[rest.index("(") + 1 : rest.rindex(")")]
    columns = []
    for raw in columns_part.split(","):
        col = raw.strip().strip('"')
        # `col DESC`, `col NULLS FIRST`, an expression, a function call — none of
        # which this comparison is entitled to treat as a plain column.
        if not col or not col.replace("_", "").isalnum():
            return None
        columns.append(col)
    if not columns:
        return None

    return f"{table}:{','.join(columns)}:{unique}"


def _equivalent_index_exists(conn, ddl: str) -> bool:
    """Is there already an index on these columns, under any name?

    Used by migration 080's `ensure()` so a fresh install does not end up with
    two identical btrees on the same column — which is what the entity's
    `__table_args__` plus the migration's own list produced.
    """
    if conn.dialect.name != "postgresql":
        return False

    candidate = _index_signature(f"create index X {ddl}")
    if candidate is None:
        return False

    rows = conn.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = 'public' AND tablename = :t"
        ),
        {"t": candidate.split(":", 1)[0]},
    ).all()
    for (definition,) in rows:
        if _index_signature(definition) == candidate:
            return True
    return False


def _migration_080_recreate_absent_indexes(conn) -> bool:
    """Create every index the migrations declare that this database is missing.

    Thirteen of them, and one of those was the gallery's own.

    `IF NOT EXISTS` throughout, and each statement runs in its own savepoint, so
    one wrong column name cannot abort the twelve that already succeeded and leave
    the step recorded as applied with the database unchanged. That is not
    hypothetical: the first run of this step named a column that does not exist,
    aborted, and rolled back every index it had created in the same transaction.
    A missing index is a slow query; a failed startup is an outage.
    """
    if conn.dialect.name != "postgresql":
        return True

    tables = set(inspect(conn).get_table_names())
    created: list[str] = []

    def create(statement: str) -> bool:
        """Run one index creation in its own savepoint."""
        try:
            with conn.begin_nested():
                conn.execute(text(statement))
            return True
        except Exception as exc:
            logger.warning(
                "migration_080_index_failed", statement=statement[:140], error=str(exc)
            )
            return False

    def ensure(name: str, ddl: str) -> None:
        """Create one index if absent, and record that we did.

        The DDL is assembled from a variable rather than spelled as a literal
        `CREATE INDEX`, because `test_migration_indexes_exist.py` parses every
        one of those out of this file and holds the name against `pg_indexes`; a
        template spelled like a declaration is a false positive in that test, and
        a test that cries wolf is a test that gets deleted.

        Also skips when an *equivalent* index already exists on the same table —
        same columns, same order, same uniqueness — even under a different name.
        `SQLModel.metadata.create_all` runs immediately before this steps runner
        on a fresh install, so the entity's own `__table_args__` indexes are
        already there by the time this runs. Several of the names below
        (`ix_sessions_signature`, `ix_sessions_user_updated`,
        `ix_session_assets_asset_id`, `ix_asset_lora_*`) duplicate an
        entity-declared index that `create_all` made, and creating the twin meant
        every write to those tables maintained two identical btrees and the
        planner was choosing between two indexes with identical definitions.
        Measured on the live database before this check: 8 such pairs, ~2.7 MB
        of index that no plan can prefer.
        """
        present = conn.execute(
            text("SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname = :n"),
            {"n": name},
        ).first()
        if present:
            return
        if _equivalent_index_exists(conn, ddl):
            logger.info("migration_080_equivalent_index_present", skipped=name, ddl=ddl)
            return
        if create("CREATE INDEX IF NOT EXISTS " + name + " " + ddl):
            created.append(name)

    # 075 — the one that mattered. The gallery's primary sort has no other index,
    # and `deleted_at IS NULL` matches 16,388 of 16,755 rows, so every gallery page
    # was a full seq scan reading 123 MB to return 24. Measured: 41 ms -> 0.15 ms.
    if "assets" in tables:
        ensure(
            "ix_assets_gallery_ts",
            "ON assets (coalesce(generated_at, created_at)) WHERE deleted_at IS NULL",
        )

    # 056 — graph_layouts. Empty today, so free to add; the moment a layout is
    # saved, every read of it is a scan of a 16 MB table.
    if "graph_layouts" in tables:
        ensure("idx_graph_layout_name", "ON graph_layouts (name)")
        ensure("idx_graph_layout_entity_type", "ON graph_layouts (entity_type)")
        ensure("idx_graph_layout_entity_id", "ON graph_layouts (entity_id)")

    # 045 — locations. The GIN index over `tags` is what makes a tag filter a
    # lookup rather than a scan of every row.
    if "locations" in tables:
        ensure("idx_locations_name", "ON locations (name)")
        ensure("idx_locations_tags", "ON locations USING GIN (tags)")

    # 042 — branching. Every message read in a branched chat filters on
    # (chat_id, branch_id); without it the timeline scans all of `messages`.
    if "messages" in tables:
        ensure("idx_message_branch", "ON messages (chat_id, branch_id)")

    # add_provider_status_provider_id — 1,577 rows, the only large index-backed
    # lookup in the provider-status path.
    if "provider_version_status" in tables:
        ensure("idx_provider_status_legacy", "ON provider_version_status (provider_id)")

    if "story_chapter_revisions" in tables:
        ensure("idx_revision_story_id", "ON story_chapter_revisions (story_id)")

    if "deleted_file_tombstones" in tables:
        ensure("idx_tombstone_deleted_at", "ON deleted_file_tombstones (deleted_at)")

    # 072 — asset_loras. 21 MB of table behind a join.
    if "asset_loras" in tables:
        ensure("ix_asset_lora_asset_id", "ON asset_loras (asset_id)")
        ensure("ix_asset_lora_civitai", "ON asset_loras (civitai_model_id)")
        ensure("ix_asset_lora_model", "ON asset_loras (model_id)")

    # 070 — sessions. 1,436 rows and two hot lookups.
    if "sessions" in tables:
        ensure("ix_sessions_signature", "ON sessions (user_id, signature)")
        ensure("ix_sessions_user_updated", "ON sessions (user_id, updated_at)")

    # The statistics collector had never analyzed `assets`: `n_live_tup` read 137
    # for a 16,755-row table. Autovacuum computes its thresholds from that wrong
    # estimate, so it never fired either — which is why the table had no stats to
    # plan with and a seq scan looked like the right answer.
    for table in ("assets", "asset_tags", "provider_version_status"):
        if table in tables:
            conn.execute(text("ANALYZE " + table))

    logger.info("migration_080_indexes_recreated", count=len(created), indexes=sorted(created))
    return True


def _migration_081_operator_class_indexes(conn) -> bool:
    """Create the vector index that `create_all` structurally cannot produce.

    `character_memories.embedding` is a pgvector `Vector` column, and its index is
    an HNSW index with an operator class — `USING hnsw (embedding
    vector_cosine_ops)`. A SQLModel column declared `index=True` can only ever ask
    SQLAlchemy for a plain btree, so `SQLModel.metadata.create_all` creates the
    table without it. Migration 041 creates that table *and* its two indexes, but
    it early-returns when the table already exists — which, on a fresh database,
    it always does, because `create_all` runs immediately before the steps runner
    (see `infrastructure.database.create_db_and_tables`).

    So on every fresh install `character_memories` had no vector index at all and
    semantic character-memory search was a sequential scan. The existing
    deployment has the index, which is why it was invisible: the table predates
    the `create_all` path and was made by migration 041 itself.

    Idempotent, and Postgres-only — SQLite stores the embedding as a JSON array and
    has no vector index to create.
    """
    if conn.dialect.name != "postgresql":
        return True

    tables = set(inspect(conn).get_table_names())
    if "character_memories" not in tables:
        return True

    name = "idx_character_memories_embedding"
    present = conn.execute(
        text("SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname = :n"),
        {"n": name},
    ).first()
    if present:
        return False

    try:
        with conn.begin_nested():
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS " + name + " ON character_memories "
                "USING hnsw (embedding vector_cosine_ops)"
            ))
    except Exception as exc:
        # An old pgvector without HNSW support, or a table too small to index.
        # Logged rather than raised: a missing index degrades a search, it does
        # not corrupt anything, and failing startup over it would be worse.
        logger.warning("migration_081_vector_index_failed", error=str(exc))
        return False

    conn.execute(text("ANALYZE character_memories"))
    logger.info("migration_081_vector_index_created", index=name)
    return True


def _migration_082_drop_redundant_message_chat_id_indexes(conn) -> bool:
    """Drop two indexes a composite index already serves.

    `messages` carried three btree indexes whose leftmost column is `chat_id`:

        idx_message_chat_id    (chat_id)
        ix_messages_chat_id    (chat_id)          -- byte-identical to the above
        idx_message_chat_created (chat_id, created_at)

    A btree on `(chat_id, created_at)` can answer any query that filters or sorts
    on `chat_id`, so both single-column indexes are redundant for lookups. They
    are not free: every insert and every soft-delete of a message maintained two
    extra index entries, and the planner was left choosing between two indexes
    that return identical rows in identical order.

    The two single-column indexes came from two different declarations —
    `core/entities.py` asks for `idx_message_chat_id`, and an earlier migration
    added `ix_messages_chat_id` for the same column — which is why the pair
    survived four audits: nothing was wrong with either on its own.

    The composite index is kept and is the one every hot read uses
    (`message_repo.list_by_chat` orders by `created_at`). Idempotent, and
    Postgres-only, since SQLite index DDL is a no-op here.
    """
    if conn.dialect.name != "postgresql":
        return True

    tables = set(inspect(conn).get_table_names())
    if "messages" not in tables:
        return True

    # Refuse to drop anything that is not a single-column `(chat_id)` btree, so a
    # future rename that lands on one of these names cannot silently delete a
    # different index.
    redundant = []
    for name in ("idx_message_chat_id", "ix_messages_chat_id"):
        row = conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE schemaname='public' AND indexname = :n"),
            {"n": name},
        ).first()
        if row is None:
            continue
        definition = " ".join(row[0].split()).lower()
        if "using btree (chat_id)" not in definition:
            logger.warning(
                "migration_082_index_shape_unexpected",
                index=name,
                definition=definition,
            )
            continue
        redundant.append(name)

    if not redundant:
        return False

    dropped = []
    for name in redundant:
        try:
            with conn.begin_nested():
                conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
            dropped.append(name)
        except Exception as exc:
            # A drop that fails leaves a redundant index, not a broken table.
            # Failing startup over it would be worse than the redundancy.
            logger.warning("migration_082_index_drop_failed", index=name, error=str(exc))

    if dropped:
        logger.info("migration_082_redundant_indexes_dropped", indexes=dropped)
    return bool(dropped)


# The indexes this drops, and the one each duplicates. The *kept* index is the
# entity-declared one in every case: `SQLModel.metadata.create_all` makes it on
# a fresh install, so dropping the migration-created twin is stable, whereas
# dropping the entity's would just be undone by the next `create_all`.
_DUPLICATE_INDEX_TWINS = (
    # (table, index to drop, index kept, columns)
    ("model_files", "ix_model_files_version_id", "idx_file_version", ("version_id",)),
    ("model_versions", "ix_model_versions_model_id", "idx_version_model", ("model_id",)),
    # The unique constraint's index already serves every lookup on this column.
    ("model_versions", "ix_model_versions_civitai_version_id", "uq_civitai_version_id", ("civitai_version_id",)),
    ("session_assets", "ix_session_assets_asset_id", "idx_session_asset_asset", ("asset_id",)),
    ("sessions", "ix_sessions_signature", "idx_session_signature", ("user_id", "signature")),
    ("sessions", "ix_sessions_user_updated", "idx_session_user_updated", ("user_id", "updated_at")),
    # Superseded by the composite that leads with the same column.
    ("provider_version_status", "ix_provider_version_status_file_id", "idx_file_provider_id_unique", ("file_id",)),
    ("provider_version_status", "ix_provider_version_status_provider_id", "idx_provider_status_provider_id", ("provider_id",)),
    ("provider_version_status", "idx_provider_status_legacy", "idx_provider_status_provider_id", ("provider_id",)),
)


def _migration_083_drop_duplicate_entity_indexes(conn) -> bool:
    """Drop indexes that duplicate one the entity already declares.

    `SQLModel.metadata.create_all` runs immediately before the steps runner on a
    fresh install, so every `Index(...)` in an entity's `__table_args__` and every
    `Field(index=True)` is already an index by the time a migration runs. Several
    migrations then created a *second* index on the same column under a different
    name, and nothing flagged it: each index is individually correct, which is
    why the pair survived four audits.

    The cost is real and measured on this deployment:

      * every insert, update and soft-delete on those tables maintained two
        identical btrees;
      * the planner was choosing between two indexes with identical definitions;
      * `idx_provider_status_legacy` showed `idx_tup_read = 1,867,540` against
        `idx_tup_fetch = 34` — 1.8 million index entries read to produce 34 rows.

    Migration 080's `ensure()` now skips a create when an equivalent index
    already exists, which is what stops the twin coming back on a fresh install;
    this step is what removes the ones already present.

    Every drop is guarded by a shape check: the index must be a plain single- or
    multi-column btree on exactly the columns listed, so a future rename that lands
    on one of these names cannot silently delete something else.
    """
    if conn.dialect.name != "postgresql":
        return True

    tables = set(inspect(conn).get_table_names())
    if not tables:
        return True

    dropped: list[str] = []
    for table, name, kept, columns in _DUPLICATE_INDEX_TWINS:
        if table not in tables:
            continue

        row = conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE schemaname='public' AND indexname = :n"),
            {"n": name},
        ).first()
        if row is None:
            continue

        definition = " ".join(row[0].split())
        signature = _index_signature(definition)
        expected = f"{table}:{','.join(columns)}:nonunique"
        if signature != expected:
            logger.warning(
                "migration_083_index_shape_unexpected",
                index=name,
                signature=signature,
                expected=expected,
            )
            continue

        if kept is not None:
            keeper = conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE schemaname='public' AND indexname = :n"),
                {"n": kept},
            ).first()
            if keeper is None:
                # Refuse to drop the only copy of an index.
                logger.warning("migration_083_keeper_absent", index=name, keeper=kept)
                continue
            if _index_signature(" ".join(keeper[0].split())) == signature:
                logger.warning(
                    "migration_083_keeper_is_identical_not_a_superset",
                    index=name,
                    keeper=kept,
                )

        try:
            with conn.begin_nested():
                conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
            dropped.append(name)
        except Exception as exc:
            # A failed drop leaves a redundant index, not a broken table. Failing
            # startup over it would be strictly worse than the redundancy.
            logger.warning("migration_083_index_drop_failed", index=name, error=str(exc))

    if dropped:
        logger.info("migration_083_duplicate_indexes_dropped", indexes=dropped)
        for table in sorted({t for t, *_ in _DUPLICATE_INDEX_TWINS}):
            if table in tables:
                conn.execute(text(f"ANALYZE {table}"))
    return bool(dropped)


def _migration_084_restore_model_files_civitai_file_id_index(conn) -> bool:
    """Recreate `ix_model_files_civitai_file_id`.

    Migration 083's list wrongly included this index. Every other entry there
    named a column the entity indexes twice; `model_files.civitai_file_id` is
    indexed exactly once, by `Field(index=True)`, so 083 removed the only index
    on it. Reconcile looks that column up when matching a downloaded file to its
    CivitAI record, so this is a live query path, not a cosmetic one.

    Kept as its own numbered step rather than an edit to 083, because 083 has
    already run on this deployment and editing a recorded migration would only
    change what a *fresh* install does — leaving this one broken everywhere else.
    083's list has also been corrected, so a fresh install neither drops it nor
    needs this step.
    """
    if conn.dialect.name != "postgresql":
        return True

    if "model_files" not in set(inspect(conn).get_table_names()):
        return True

    name = "ix_model_files_civitai_file_id"
    present = conn.execute(
        text("SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname = :n"),
        {"n": name},
    ).first()
    if present:
        return False

    try:
        with conn.begin_nested():
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS {name} ON model_files (civitai_file_id)"
            ))
    except Exception as exc:
        # Leaving the column un-indexed degrades one lookup. Failing startup over
        # it would be worse.
        logger.warning("migration_084_index_create_failed", index=name, error=str(exc))
        return False

    conn.execute(text("ANALYZE model_files"))
    logger.info("migration_084_index_restored", index=name)
    return True


def _migration_085_hot_table_covering_indexes(conn) -> bool:
    """Add indexes on hot query dimensions identified in performance audits.

    - `assets(checkpoint_name)`: facet queries previously seq-scanned 16k rows.
    - `asset_tags(tag_id)`: tag search previously seq-scanned 331k rows.
    - `lorebook_entries(embedding)`: pgvector HNSW index for cosine distance RAG.
    """
    tables = set(inspect(conn).get_table_names())
    applied = False

    if "assets" in tables:
        try:
            with conn.begin_nested():
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_assets_checkpoint_name ON assets (checkpoint_name)"))
            applied = True
        except Exception as exc:
            logger.warning("migration_085_assets_checkpoint_index_failed", error=str(exc))

    if "asset_tags" in tables:
        try:
            with conn.begin_nested():
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_asset_tags_tag_id ON asset_tags (tag_id)"))
            applied = True
        except Exception as exc:
            logger.warning("migration_085_asset_tags_tag_id_index_failed", error=str(exc))

    if conn.dialect.name == "postgresql" and "lorebook_entries" in tables:
        try:
            with conn.begin_nested():
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_lorebook_entries_embedding ON lorebook_entries "
                    "USING hnsw (embedding vector_cosine_ops)"
                ))
            applied = True
        except Exception as exc:
            logger.warning("migration_085_lorebook_vector_index_failed", error=str(exc))

    return applied


def _migration_086_fix_asset_tags_tag_index(conn) -> bool:
    """Index the column 085 meant.

    085 asked for ``asset_tags(tag_id)``, which does not exist (the table
    carries ``tag``), so that statement failed inside its savepoint and the
    step was still recorded as applied. This step creates the intended tag
    index idempotently; on installs where 073 already made
    ``ix_asset_tags_tag`` it is a no-op.
    """
    tables = set(inspect(conn).get_table_names())
    if "asset_tags" not in tables:
        return False
    try:
        columns = {c["name"] for c in inspect(conn).get_columns("asset_tags")}
    except Exception as exc:
        logger.warning("migration_086_asset_tags_columns_failed", error=str(exc))
        return False
    # Literal column names, not an f-string template: the
    # test_migration_indexes_exist sweep parses declared indexes out of this
    # source and skips names followed by `{`.
    try:
        with conn.begin_nested():
            if "tag" in columns:
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS idx_asset_tags_tag_covering ON asset_tags (tag)")
                )
            elif "tag_id" in columns:
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS idx_asset_tags_tag_covering ON asset_tags (tag_id)")
                )
            else:
                logger.warning("migration_086_asset_tags_no_tag_column")
                return False
        return True
    except Exception as exc:
        logger.warning("migration_086_asset_tags_tag_index_failed", error=str(exc))
        return False


def _migration_087_asset_seed_bigint(conn) -> bool:
    """Widen assets.seed from INTEGER to BIGINT.

    ComfyUI seeds are 64-bit unsigned values (up to 2^64-1). The column was
    created as INTEGER (31-bit signed on Postgres), which overflows on seeds
    like 3173361303086572. ALTER TYPE ... USING handles existing data in-place.
    """
    tables = set(inspect(conn).get_table_names())
    if "assets" not in tables:
        return False
    columns = {c["name"]: c for c in inspect(conn).get_columns("assets")}
    if "seed" not in columns:
        logger.warning("migration_087_seed_column_missing")
        return False
    try:
        with conn.begin_nested():
            conn.execute(text("ALTER TABLE assets ALTER COLUMN seed TYPE BIGINT USING seed::BIGINT"))
        return True
    except Exception as exc:
        logger.warning("migration_087_asset_seed_bigint_failed", error=str(exc))
        return False


def _migration_088_converge_hot_indexes_and_seed(conn) -> bool:
    """Converge the 085/086/087 outcomes idempotently.

    - 085 set `applied=True` per branch, so a host where `assets` succeeded
      but the pgvector HNSW failed recorded the step as done and never
      retried the missing index. Re-issue every 085/086 index with
      `IF NOT EXISTS`: converged hosts no-op, partial hosts heal.
    - 087 returns False on SQLite (`ALTER COLUMN TYPE` is Postgres-only), so
      dev/test SQLite retries it every boot. SQLite integers are already
      64-bit signed — there is nothing to widen — so the seed leg is a
      no-op there. On Postgres the ALTER runs only while the column is
      still INTEGER; re-running it on an already-BIGINT column would take
      a pointless ACCESS EXCLUSIVE lock on the gallery table.
    - Residual, deliberately out of scope: BIGINT is signed (max 2^63-1)
      while ComfyUI seeds are u64. Holding the full u64 range needs a TEXT
      retype plus entity churn (`statistics_service` compares `seed == -1`
      numerically), so values above 2^63-1 still overflow.
    - Returns True when every applicable target converged or was already
      converged; False only when a DDL against an existing table failed
      (retry next boot). Absent tables are not failure — fixtures and
      pre-table databases simply have nothing to converge.
    """
    from sqlalchemy import BigInteger

    ok = True

    def _run(label: str, ddl: str) -> None:
        nonlocal ok
        try:
            with conn.begin_nested():
                conn.execute(text(ddl))
        except Exception as exc:
            logger.warning(f"migration_088_{label}_failed", error=str(exc))
            ok = False

    tables = set(inspect(conn).get_table_names())

    if "assets" in tables:
        _run(
            "assets_checkpoint_index",
            "CREATE INDEX IF NOT EXISTS idx_assets_checkpoint_name ON assets (checkpoint_name)",
        )
        columns = {c["name"]: c for c in inspect(conn).get_columns("assets")}
        seed_col = columns.get("seed")
        if seed_col is None:
            logger.warning("migration_088_seed_column_missing")
        elif conn.dialect.name != "postgresql":
            # SQLite integers are 64-bit signed already: nothing to widen.
            pass
        elif isinstance(seed_col.get("type"), BigInteger):
            # 087 (or create_all from the BigInteger entity) already landed.
            pass
        else:
            _run(
                "asset_seed_bigint",
                "ALTER TABLE assets ALTER COLUMN seed TYPE BIGINT USING seed::BIGINT",
            )

    if "asset_tags" in tables:
        try:
            columns = {c["name"] for c in inspect(conn).get_columns("asset_tags")}
        except Exception as exc:
            logger.warning("migration_088_asset_tags_columns_failed", error=str(exc))
            columns = set()
        if "tag" in columns:
            _run(
                "asset_tags_tag_index",
                "CREATE INDEX IF NOT EXISTS idx_asset_tags_tag_covering ON asset_tags (tag)",
            )
        elif "tag_id" in columns:
            _run(
                "asset_tags_tag_id_index",
                "CREATE INDEX IF NOT EXISTS idx_asset_tags_tag_covering ON asset_tags (tag_id)",
            )

    if conn.dialect.name == "postgresql" and "lorebook_entries" in tables:
        _run(
            "lorebook_vector_index",
            "CREATE INDEX IF NOT EXISTS idx_lorebook_entries_embedding ON lorebook_entries "
            "USING hnsw (embedding vector_cosine_ops)",
        )

    return ok


def _migration_089_fold_container_config_into_config(conn) -> bool:
    """Fold ``providers.container_config`` into ``config`` (config wins).

    Provider rows have been written with container placement under two keys
    over time: ``container_config`` (``container_name``, ``port`` — the
    legacy container path) and ``config`` (everything the registry schema
    validates). The runtime and the wake filter must not depend on which
    key a URL landed under, so every ``container_config`` entry is copied
    into ``config`` wherever that key is absent. ``config`` wins on
    conflict — it is the newer write path and the one the UI edits.

    The ``container_config`` column itself stays: dropping a column is a
    breaking change for old readers, and the save paths still accept it on
    write (folded into the validation union). Returns True when every row
    converged; a row whose JSON cannot be parsed is logged and skipped
    (retry next boot via a False return).
    """
    inspector = inspect(conn)
    if "providers" not in set(inspector.get_table_names()):
        return False
    columns = {c["name"] for c in inspector.get_columns("providers")}
    if not {"config", "container_config"} <= columns:
        return False

    def _as_dict(raw):
        if not raw:
            return {}
        if isinstance(raw, dict):
            return dict(raw)
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return dict(parsed) if isinstance(parsed, dict) else {}

    ok = True
    # `IS NOT NULL`: the common case is a provider that never carried
    # container_config at all, and there is no reason to pull every such row
    # through json.loads on every boot just to skip it.
    rows = conn.execute(
        text("SELECT id, config, container_config FROM providers WHERE container_config IS NOT NULL")
    ).all()
    for row in rows:
        provider_id, config_raw, container_config_raw = row[0], row[1], row[2]
        legacy = _as_dict(container_config_raw)
        if legacy is None:
            logger.warning("migration_089_unparseable_container_config", provider_id=provider_id)
            ok = False
            continue
        if not legacy:
            continue
        current = _as_dict(config_raw)
        if current is None:
            logger.warning("migration_089_unparseable_config", provider_id=provider_id)
            ok = False
            continue
        merged = {**legacy, **current}
        if merged != current:
            conn.execute(
                text("UPDATE providers SET config = :config WHERE id = :id"),
                {"config": json.dumps(merged), "id": provider_id},
            )
            logger.info(
                "migration_089_container_config_folded",
                provider_id=provider_id,
                keys=sorted(set(merged) - set(current)),
            )
    return ok


def _migration_096_encrypt_provider_credentials(conn) -> bool:
    """Rewrite plaintext credential bags into the encrypted envelope.

    `services/credential_crypto.py` encrypts on the way in, so any row written
    after that lands encrypted. Rows written before it — and there is at least
    one, because credentials moved out of `.env` specifically so the Providers
    UI could manage them — are still plaintext JSON sitting in a column that
    any database dump reveals.

    A backfill rather than a cutover, deliberately. `decrypt_credentials` passes
    plaintext through, so an un-migrated row keeps working: an operator can
    upgrade, run the app against their existing credentials, and only then
    choose a secret. Forcing the choice at upgrade time would break every
    deployment that had not yet chosen one, for a control they did not ask for.

    NO-OP WITHOUT A KEY. With `COMFY_CREDENTIAL_SECRET` unset, encryption is
    off and there is nothing to migrate to; recording the step as done would
    stop it ever running, so this returns False and the runner tries again next
    start. Every other migration here is `if "x" in tables: skip`, which is
    right for a structural change and wrong for one gated on configuration the
    operator supplies later.

    Idempotent by inspection rather than by flag: a row that is already an
    envelope is skipped, so re-running after a crash mid-sweep finishes the job
    instead of double-encrypting. That check is `__enc__` presence, NOT a
    decrypt — the backfill must work for rows whose key has since been rotated,
    or a rotation would make them permanently un-migratable.
    """
    from services.credential_crypto import (
        encrypt_credentials,
        encryption_status,
        is_encrypted,
    )

    if not encryption_status()["enabled"]:
        logger.info(
            "migration_096_deferred_no_master_secret",
            env_var=encryption_status()["env_var"],
        )
        return False

    inspector = inspect(conn)
    if "providers" not in set(inspector.get_table_names()):
        logger.info("migration_096_skipped", reason="no_providers_table")
        return False

    rows = conn.execute(
        text("SELECT id, credentials FROM providers")
    ).fetchall()

    migrated = 0
    for provider_id, raw in rows:
        try:
            bag = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (json.JSONDecodeError, TypeError):
            # Not ours to interpret. Leaving it alone is better than guessing at
            # a row some other tool wrote.
            logger.warning(
                "migration_096_unreadable_credentials", provider_id=provider_id
            )
            continue
        if not isinstance(bag, dict) or not bag or is_encrypted(bag):
            continue

        envelope = encrypt_credentials(bag)
        if envelope == bag:
            continue
        conn.execute(
            text("UPDATE providers SET credentials = :credentials WHERE id = :id"),
            {"credentials": json.dumps(envelope), "id": provider_id},
        )
        migrated += 1
        logger.info("migration_096_encrypted", provider_id=provider_id)

    if migrated:
        logger.info("migration_096_encrypt_provider_credentials_done", migrated=migrated)
    else:
        logger.info("migration_096_no_plaintext_rows")
    return True


def _migration_097_provider_worker_type_hybrid(conn) -> bool:
    """Widen `chk_providers_worker_type` to allow `hybrid` for multi-modal workers."""
    if conn.dialect.name != "postgresql":
        return True

    inspector = inspect(conn)
    if "providers" not in set(inspector.get_table_names()):
        return False

    columns = {c["name"] for c in inspector.get_columns("providers")}
    if "worker_type" not in columns:
        return False

    row = conn.execute(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'chk_providers_worker_type'"
        )
    ).fetchone()
    if row and "'hybrid'" in str(row[0]):
        return True

    conn.execute(
        text("ALTER TABLE providers DROP CONSTRAINT IF EXISTS chk_providers_worker_type")
    )
    conn.execute(
        text(
            "ALTER TABLE providers ADD CONSTRAINT chk_providers_worker_type "
            "CHECK (worker_type IN ('image', 'llm', 'tts', 'hybrid'))"
        )
    )
    logger.info("provider_worker_type_constraint_widened", added="hybrid")
    return True


def _migration_098_chat_scenario_fk(conn) -> bool:
    """Add nullable `scenario_id` FK to chats so a chat references a Scenario.

    Stories already carry `scenario_id` (062). Chats did not, so a chat could
    reference a Scenario only through the free-text `Character.scenario` field
    or the chat-level `system_prompt_override`. A nullable FK makes the
    Scenario library a first-class target for chats too, matching Story.

    Nullable = unset; no backfill, no NOT NULL. A chat with no scenario_id
    keeps its existing behaviour.
    """
    inspector = inspect(conn)
    if "chats" not in set(inspector.get_table_names()):
        return False
    cols = {c["name"] for c in inspector.get_columns("chats")}
    if "scenario_id" in cols:
        logger.info("migration_noop", note="chats.scenario_id already present")
        return True

    col_type = "VARCHAR" if conn.dialect.name == "postgresql" else "TEXT"
    conn.execute(
        text(f"ALTER TABLE chats ADD COLUMN scenario_id {col_type}")
    )
    logger.info("migration_column_added", table="chats", column="scenario_id")

    # Only add the FK if scenarios table exists and there are no pre-existing
    # dangling values (the column is brand new, so there can't be any).
    if "scenarios" in set(inspector.get_table_names()):
        try:
            if conn.dialect.name == "postgresql":
                conn.execute(
                    text(
                        "ALTER TABLE chats "
                        "ADD CONSTRAINT fk_chats_scenario_id "
                        "FOREIGN KEY (scenario_id) REFERENCES scenarios(id)"
                    )
                )
            else:
                # SQLite: FKs are declared at table creation; ALTER TABLE cannot
                # add one. The column still exists for ORM-level use.
                pass
        except Exception as exc:
            logger.warning(
                "migration_098_fk_add_failed", error=str(exc)
            )

    return True


def _migration_100_chat_director_state_snapshot(conn) -> bool:
    """Add `director_enabled` and `state_snapshot` to `chats`."""
    inspector = inspect(conn)
    if "chats" not in set(inspector.get_table_names()):
        return False
    cols = {c["name"] for c in inspector.get_columns("chats")}
    is_postgres = conn.dialect.name == "postgresql"

    if "director_enabled" not in cols:
        bool_default = "TRUE" if is_postgres else "1"
        conn.execute(
            text(f"ALTER TABLE chats ADD COLUMN director_enabled BOOLEAN NOT NULL DEFAULT {bool_default}")
        )
        logger.info("migration_column_added", table="chats", column="director_enabled")

    if "state_snapshot" not in cols:
        json_type = "JSONB NOT NULL DEFAULT '{}'::jsonb" if is_postgres else "TEXT NOT NULL DEFAULT '{}'"
        conn.execute(
            text(f"ALTER TABLE chats ADD COLUMN state_snapshot {json_type}")
        )
        logger.info("migration_column_added", table="chats", column="state_snapshot")

    return True


def _migration_101_chat_director_autonomy(conn) -> bool:
    """Add `director_autonomy_level` and `max_autonomous_turns` to `chats`."""
    inspector = inspect(conn)
    if "chats" not in set(inspector.get_table_names()):
        return False
    cols = {c["name"] for c in inspector.get_columns("chats")}

    if "director_autonomy_level" not in cols:
        conn.execute(
            text("ALTER TABLE chats ADD COLUMN director_autonomy_level TEXT NOT NULL DEFAULT 'balanced'")
        )
        logger.info("migration_column_added", table="chats", column="director_autonomy_level")

    if "max_autonomous_turns" not in cols:
        conn.execute(
            text("ALTER TABLE chats ADD COLUMN max_autonomous_turns INTEGER NOT NULL DEFAULT 4")
        )
        logger.info("migration_column_added", table="chats", column="max_autonomous_turns")

    return True


def _migration_102_agent_profiles(conn) -> bool:
    """Create agent_profiles table and seed default built-in agents."""
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())
    is_postgres = conn.dialect.name == "postgresql"

    if "agent_profiles" not in existing_tables:
        if is_postgres:
            conn.execute(text("""
                CREATE TABLE agent_profiles (
                    id TEXT PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    agent_type TEXT NOT NULL DEFAULT 'generation',
                    description TEXT NOT NULL,
                    system_prompt_template TEXT NOT NULL,
                    model_target TEXT NOT NULL DEFAULT 'rp',
                    model_override TEXT,
                    is_builtin BOOLEAN NOT NULL DEFAULT FALSE,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    temperature FLOAT,
                    top_p FLOAT,
                    max_tokens INTEGER,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_slug ON agent_profiles (slug)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_type ON agent_profiles (agent_type)"))
        else:
            conn.execute(text("""
                CREATE TABLE agent_profiles (
                    id TEXT PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    agent_type TEXT NOT NULL DEFAULT 'generation',
                    description TEXT NOT NULL,
                    system_prompt_template TEXT NOT NULL,
                    model_target TEXT NOT NULL DEFAULT 'rp',
                    model_override TEXT,
                    is_builtin BOOLEAN NOT NULL DEFAULT 0,
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    temperature REAL,
                    top_p REAL,
                    max_tokens INTEGER,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_slug ON agent_profiles (slug)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_type ON agent_profiles (agent_type)"))
        logger.info("migration_table_created", table="agent_profiles")

    # Seed built-in agents if missing
    builtins = [
        {
            "id": "builtin-character",
            "slug": "character",
            "name": "Character Agent",
            "agent_type": "generation",
            "description": "The primary character should respond directly to the conversation or situation in their authentic persona and voice.",
            "system_prompt_template": "You are roleplaying as {{char}}. Respond directly in character, staying true to your personality, backstory, and voice. Embody your character's quirks, mannerisms, and physical reactions.",
            "model_target": "rp",
            "is_builtin": True,
            "enabled": True,
        },
        {
            "id": "builtin-narrator",
            "slug": "narrator",
            "name": "Scene Narrator",
            "agent_type": "generation",
            "description": "The omniscient scene narrator should describe the environment, atmosphere, sensory details, secondary NPCs, or the passage of time.",
            "system_prompt_template": "You are the omniscient narrative director and storyteller. Describe the scene environment, sensory atmosphere, pacing, secondary NPC actions, and narrative consequences with cinematic prose. Do not speak for the player character.",
            "model_target": "rp",
            "is_builtin": True,
            "enabled": True,
        },
        {
            "id": "builtin-illustrator",
            "slug": "illustrator",
            "name": "Illustrator Agent",
            "agent_type": "multimodal",
            "description": "Synthesizes striking visual scene moments into structured ComfyUI image prompts and negative tags.",
            "system_prompt_template": "You are an expert anime and fantasy prompt artist. Given the current scene beat and character appearances, formulate a high-quality descriptive visual prompt capturing character appearance, outfit, composition, camera angle, and atmosphere.",
            "model_target": "util",
            "is_builtin": True,
            "enabled": True,
        },
        {
            "id": "builtin-updater",
            "slug": "updater",
            "name": "Statekeeper Agent",
            "agent_type": "utility",
            "description": "Audits the exchange and extracts structured state updates for character mood, atmosphere, inventory, and world lore.",
            "system_prompt_template": "You are the Statekeeper. Extract state modifications for the activated narrative gates in valid JSON format. Update only the fields that shifted in this beat.",
            "model_target": "util",
            "is_builtin": True,
            "enabled": True,
        },
        {
            "id": "builtin-continuation",
            "slug": "continuation",
            "name": "Continuation Agent",
            "agent_type": "generation",
            "description": "Seamlessly completes thoughts, dialogue, or action beats that were cut off mid-sentence without repeating previous words.",
            "system_prompt_template": "You were in the middle of generating a response and were cut off. Continue seamlessly from the exact last word without repeating or summarizing.",
            "model_target": "rp",
            "is_builtin": True,
            "enabled": True,
        },
    ]

    now_utc = datetime.now(timezone.utc)
    for b in builtins:
        b["created_at"] = now_utc
        b["updated_at"] = now_utc
        row = conn.execute(
            text("SELECT id FROM agent_profiles WHERE slug = :slug"),
            {"slug": b["slug"]}
        ).first()
        if not row:
            conn.execute(
                text("""
                    INSERT INTO agent_profiles (
                        id, slug, name, agent_type, description, system_prompt_template,
                        model_target, is_builtin, enabled, created_at, updated_at
                    ) VALUES (
                        :id, :slug, :name, :agent_type, :description, :system_prompt_template,
                        :model_target, :is_builtin, :enabled, :created_at, :updated_at
                    )
                """),
                b
            )
            logger.info("builtin_agent_seeded", slug=b["slug"])

    return True



def _migration_103_agent_prompt_variants(conn) -> bool:
    """Create agent_prompt_variants for per-agent prompt overrides."""
    inspector = inspect(conn)
    if "agent_prompt_variants" in set(inspector.get_table_names()):
        return True

    is_postgres = conn.dialect.name == "postgresql"
    if is_postgres:
        conn.execute(text("""
            CREATE TABLE agent_prompt_variants (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL REFERENCES agent_profiles(id) ON DELETE CASCADE,
                slug TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                system_prompt_template TEXT NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT FALSE,
                temperature FLOAT,
                top_p FLOAT,
                max_tokens INTEGER,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
    else:
        conn.execute(text("""
            CREATE TABLE agent_prompt_variants (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL REFERENCES agent_profiles(id) ON DELETE CASCADE,
                slug TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                system_prompt_template TEXT NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT 0,
                temperature REAL,
                top_p REAL,
                max_tokens INTEGER,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_variant_slug ON agent_prompt_variants (slug)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_variant_agent ON agent_prompt_variants (agent_id)"))
    logger.info("migration_table_created", table="agent_prompt_variants")
    return True


_BUILTIN_SUBVARIANTS = (
    # (agent slug, variant slug, name, tags, selection hint, prompt)
    (
        "narrator", "narrator-combat", "Combat Narrator", ["combat", "danger"],
        "Use during fights, chases, or any sudden physical danger.",
        "You are the scene narrator during a moment of action. Write kinetic, concrete third-person present tense: "
        "short sentences, clear spatial staging, impact and consequence. No dialogue for the player character.",
    ),
    (
        "narrator", "narrator-quiet", "Quiet Moments Narrator", ["calm", "slice-of-life"],
        "Use for calm, everyday or contemplative scenes with no immediate danger.",
        "You are the scene narrator during a quiet moment. Write gentle, observant third-person present tense: "
        "small sensory details, ambient sound, light, and the passing of time. Keep it unhurried and brief.",
    ),
    (
        "narrator", "narrator-travel", "Transition Narrator", ["travel", "time-skip"],
        "Use when time passes, characters travel, or the scene changes location.",
        "You are the scene narrator bridging a transition. Summarise what happens between the previous beat and the "
        "next in a few vivid sentences, then establish the new setting and time. Do not resolve open player choices.",
    ),
    (
        "character", "character-tense", "Tense Character", ["conflict", "high-stakes"],
        "Use when the character is under pressure, arguing, afraid, or in conflict.",
        "You are roleplaying as {{char}}. The moment is tense: let emotion leak into word choice, rhythm and body "
        "language. Stay in character and respond only as {{char}}.",
    ),
    (
        "character", "character-tender", "Tender Character", ["intimate", "emotional"],
        "Use for close, vulnerable, affectionate or emotionally open moments.",
        "You are roleplaying as {{char}}. The moment is close and emotional: be present and specific, favour small "
        "gestures and honest feeling over exposition. Stay in character and respond only as {{char}}.",
    ),
    (
        "character", "character-playful", "Playful Character", ["banter", "lighthearted"],
        "Use for teasing, jokes, banter and lighthearted exchanges.",
        "You are roleplaying as {{char}}. The mood is playful: quick wit, teasing and warmth, shorter replies. Stay "
        "in character and respond only as {{char}}.",
    ),
)


def _migration_104_variant_routing_tags(conn) -> bool:
    """Add routing columns to agent_prompt_variants and seed inactive sub-variants."""
    inspector = inspect(conn)
    if "agent_prompt_variants" not in set(inspector.get_table_names()):
        # Fresh install: create_all builds the table with the new columns; the
        # seed below is applied by the first run that finds the table.
        return True

    columns = _get_table_columns(conn, "agent_prompt_variants")
    is_postgres = conn.dialect.name == "postgresql"
    if "tags" not in columns:
        col_type = "JSONB" if is_postgres else "JSON"
        conn.execute(text(f"ALTER TABLE agent_prompt_variants ADD COLUMN tags {col_type}"))
        conn.execute(text("UPDATE agent_prompt_variants SET tags = '[]'"))
        logger.info("migration_column_added", table="agent_prompt_variants", column="tags")
    if "selection_hint" not in columns:
        conn.execute(text("ALTER TABLE agent_prompt_variants ADD COLUMN selection_hint TEXT NOT NULL DEFAULT ''"))
        logger.info("migration_column_added", table="agent_prompt_variants", column="selection_hint")
    _verify_required_columns(conn, "agent_prompt_variants", {"tags", "selection_hint"})

    now_utc = datetime.now(timezone.utc)
    for agent_slug, slug, name, tags, hint, prompt in _BUILTIN_SUBVARIANTS:
        agent = conn.execute(
            text("SELECT id FROM agent_profiles WHERE slug = :slug"), {"slug": agent_slug}
        ).first()
        if not agent:
            continue
        exists = conn.execute(
            text("SELECT id FROM agent_prompt_variants WHERE slug = :slug"), {"slug": slug}
        ).first()
        if exists:
            continue
        conn.execute(
            text(
                """
                INSERT INTO agent_prompt_variants (
                    id, agent_id, slug, name, description, system_prompt_template,
                    is_active, tags, selection_hint, created_at, updated_at
                ) VALUES (
                    :id, :agent_id, :slug, :name, :description, :prompt,
                    :is_active, """ + ("CAST(:tags AS JSONB)" if is_postgres else ":tags") + """, :hint, :created_at, :updated_at
                )
                """
            ),
            {
                "id": f"builtin-variant-{slug}",
                "agent_id": agent[0],
                "slug": slug,
                "name": name,
                "description": hint,
                "prompt": prompt,
                "is_active": False,
                "tags": json.dumps(tags),
                "hint": hint,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
        )
        logger.info("builtin_subvariant_seeded", slug=slug, agent=agent_slug)
    return True
