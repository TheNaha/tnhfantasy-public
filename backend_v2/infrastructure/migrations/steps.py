import json
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
        return False

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
    ]


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
                        credentials, config, container_config
                    ) VALUES (
                        :id, :type, :worker_type, :enabled, :priority,
                        :credentials, :config, :container_config
                    )
                """),
                {
                    "id": "llm-local",
                    "type": "openai_compat",
                    "worker_type": "llm",
                    "enabled": False,
                    "priority": 1,
                    "credentials": json.dumps({}),
                    "config": json.dumps({"seeded": True, "discovered": True, "api_base": "http://localhost:11434/v1"}),
                    "container_config": json.dumps({"container_name": "tnhcomfy-llm-local"}),
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
