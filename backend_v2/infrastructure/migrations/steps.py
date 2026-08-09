import json
from collections.abc import Callable
from dataclasses import dataclass

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
    ]
