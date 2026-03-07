# Database setup with SQLModel
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool
from typing import Generator
from dataclasses import dataclass
import os

from config import settings
from infrastructure.logging import db_logger

logger = db_logger()


SCHEMA_MIGRATIONS_TABLE = "schema_migrations"


@dataclass(frozen=True)
class MigrationStep:
    """Single schema migration step tracked in the database."""

    version: str
    description: str
    apply_fn: callable


def _get_table_columns(conn, table_name: str) -> set[str]:
    """Return the current column names for a table."""
    from sqlalchemy import inspect

    inspector = inspect(conn)
    return {col['name'] for col in inspector.get_columns(table_name)}


def _verify_required_columns(conn, table_name: str, required_columns: set[str]) -> None:
    """Ensure a table contains all required columns after migrations run."""
    columns = _get_table_columns(conn, table_name)
    missing = sorted(required_columns - columns)
    if missing:
        raise RuntimeError(f"Schema verification failed for {table_name}: missing columns {', '.join(missing)}")


def _ensure_schema_migrations_table(conn) -> None:
    """Create the schema migration tracking table if it does not exist."""
    from sqlalchemy import text

    conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_MIGRATIONS_TABLE} (
            version TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.commit()


def _get_applied_migrations(conn) -> set[str]:
    """Return the set of migration versions already recorded."""
    from sqlalchemy import inspect, text

    inspector = inspect(conn)
    if SCHEMA_MIGRATIONS_TABLE not in inspector.get_table_names():
        return set()

    rows = conn.execute(text(f"SELECT version FROM {SCHEMA_MIGRATIONS_TABLE}")).all()
    return {row[0] for row in rows}


def _record_migration(conn, step: MigrationStep) -> None:
    """Record a successfully applied migration step."""
    from sqlalchemy import text

    conn.execute(
        text(
            f"INSERT INTO {SCHEMA_MIGRATIONS_TABLE} (version, description) VALUES (:version, :description)"
        ),
        {"version": step.version, "description": step.description},
    )
    conn.commit()


def _migration_add_job_timestamps(conn) -> bool:
    """Ensure jobs table includes started_at and completed_at columns."""
    from sqlalchemy import inspect, text

    inspector = inspect(conn)
    if "jobs" not in inspector.get_table_names():
        return False

    columns = {col['name'] for col in inspector.get_columns('jobs')}

    if 'started_at' not in columns:
        conn.execute(text('ALTER TABLE jobs ADD COLUMN started_at DATETIME'))
        conn.commit()
        logger.info("migration_column_added", table="jobs", column="started_at")

    if 'completed_at' not in columns:
        conn.execute(text('ALTER TABLE jobs ADD COLUMN completed_at DATETIME'))
        conn.commit()
        logger.info("migration_column_added", table="jobs", column="completed_at")

    _verify_required_columns(conn, 'jobs', {'started_at', 'completed_at'})
    return True


def _migration_setup_prompts_fts(conn) -> bool:
    """Create the prompts FTS table and synchronization triggers."""
    from sqlalchemy import inspect, text

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
    conn.commit()
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
        conn.commit()
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
    ]


def get_database_url() -> str:
    """Get database URL, ensuring data directory exists."""
    url = settings.database_url
    
    # If using SQLite, ensure directory exists
    if url.startswith("sqlite"):
        # Extract path from sqlite:///./data/comfy.db
        db_path = url.replace("sqlite:///", "")
        if db_path.startswith("./"):
            db_path = db_path[2:]
        
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
    
    return url


# Create engine with appropriate settings
database_url = get_database_url()

# Use NullPool for SQLite - connections are lightweight with WAL mode
# NullPool creates connections on-demand and closes them immediately after use
# This prevents connection pool exhaustion issues in async/concurrent environments
if database_url.startswith("sqlite"):
    from sqlalchemy.pool import NullPool
    
    engine = create_engine(
        database_url,
        connect_args={
            "check_same_thread": False,
            "timeout": 30  # 30 second timeout for locks
        },
        poolclass=NullPool,  # No pooling - each request gets a fresh connection
        echo=False,  # Set to True for SQL debugging
    )

    
    # Enable WAL mode for better concurrency (allows reads during writes)
    from sqlalchemy import event
    
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        # WAL mode allows readers to not block writers and vice versa
        cursor.execute("PRAGMA journal_mode=WAL")
        # Busy timeout: wait up to 30 seconds if database is locked
        cursor.execute("PRAGMA busy_timeout=30000")
        # Synchronous NORMAL is safe with WAL and faster
        cursor.execute("PRAGMA synchronous=NORMAL")
        # Enable foreign key constraints
        cursor.execute("PRAGMA foreign_keys=ON")
        
        # Performance optimizations
        cursor.execute("PRAGMA cache_size = -32000")      # 32MB cache (negative = KB)
        cursor.execute("PRAGMA temp_store = MEMORY")      # Use memory for temp tables
        cursor.execute("PRAGMA mmap_size = 268435456")    # 256MB memory-mapped I/O
        
        cursor.close()
        
else:
    engine = create_engine(database_url, echo=False)


def create_db_and_tables() -> None:
    """Create all tables in the database."""
    # Import V1 entities to register them with SQLModel
    from core.entities import (
        Job, Provider, Model, Download, LoadBalancingConfig, LoadBalancerState,
        Prompt, Collection, CollectionImage
    )
    
    # Import V2 entities (normalized schema)
    from core.entities_v2 import (
        ModelV2, ModelVersion, ModelFile, ModelImage, 
        ProviderVersionStatus, ModelTag
    )
    
    SQLModel.metadata.create_all(engine)
    
    # Run migrations for existing databases
    _run_migrations()
    
    # Migrate old models to new schema (if needed)
    _migrate_models_to_v2()


def _run_migrations() -> None:
    """
    Run schema migrations for existing databases.
    Migration steps are tracked in a lightweight schema_migrations table.
    """
    from sqlalchemy import inspect
    
    with engine.connect() as conn:
        inspector = inspect(engine)
        
        # Check if jobs table exists
        if 'jobs' not in inspector.get_table_names():
            return

        _ensure_schema_migrations_table(conn)
        applied_versions = _get_applied_migrations(conn)

        for step in _get_schema_migration_steps():
            if step.version in applied_versions:
                continue

            applied = step.apply_fn(conn)
            if not applied:
                continue
            _record_migration(conn, step)
            logger.info("migration_applied", version=step.version, description=step.description)




def get_session() -> Generator[Session, None, None]:
    """
    Get a database session.
    
    Usage:
        with get_session() as session:
            ...
    
    Or as FastAPI dependency:
        def endpoint(session: Session = Depends(get_session)):
            ...
    """
    with Session(engine) as session:
        yield session


def get_session_sync() -> Session:
    """Get a session for synchronous code."""
    return Session(engine)


from contextlib import asynccontextmanager

@asynccontextmanager
async def get_session_context():
    """
    Async context manager for database sessions.
    
    Usage in async code:
        async with get_session_context() as session:
            ...
    """
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


# For testing - create in-memory database
def create_test_engine():
    """Create an in-memory SQLite engine for testing."""
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _migrate_models_to_v2() -> None:
    """
    Migrate existing models from V1 flat schema to V2 normalized schema.
    Per user clarification: existing models always used latest version,
    so we treat the first version in modelVersions as the selected default.
    """
    from sqlalchemy import text, inspect
    import json
    
    with engine.connect() as conn:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        # Check if both old and new tables exist
        if 'models' not in tables or 'models_v2' not in tables:
            return
        
        # Check if migration already done (models_v2 has data)
        result = conn.execute(text("SELECT COUNT(*) FROM models_v2"))
        v2_count = result.scalar()
        if v2_count > 0:
            logger.debug("migration_v2_skip", reason="already_populated")
            return
        
        # Check if there's data to migrate
        result = conn.execute(text("SELECT COUNT(*) FROM models"))
        v1_count = result.scalar()
        if v1_count == 0:
            logger.debug("migration_v2_skip", reason="no_v1_models")
            return
        
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
                
                conn.execute(text("""
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
                """), {
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
                    "updated_at": row[8]
                })
                
                # Get the inserted model ID
                model_result = conn.execute(text(
                    "SELECT id FROM models_v2 WHERE civitai_model_id = :cid"
                ), {"cid": civitai_id})
                model_v2_id = model_result.scalar()
                
                if not model_v2_id:
                    continue
                
                # Create tags
                for tag in metadata.get("tags", []):
                    try:
                        conn.execute(text("""
                            INSERT INTO model_tags (model_id, tag) VALUES (:model_id, :tag)
                        """), {"model_id": model_v2_id, "tag": tag})
                    except Exception as e:
                        logger.debug("migration_v2_tag_skip", model_id=model_v2_id, tag=tag, detail=str(e))
                
                # Get versions - take first (latest) as the selected one
                versions = metadata.get("modelVersions", [])
                if not versions:
                    continue
                
                # Only migrate the first version (user's clarification)
                version_data = versions[0]
                civitai_version_id = version_data.get("id")
                
                # Determine trained words from version
                trained_words = version_data.get("trainedWords", [])
                trained_words_json = json.dumps(trained_words) if trained_words else None
                
                conn.execute(text("""
                    INSERT INTO model_versions (
                        model_id, civitai_version_id, name, base_model, base_model_type,
                        description, is_enabled, is_default, trained_words,
                        civitai_published_at, created_at
                    ) VALUES (
                        :model_id, :civitai_version_id, :name, :base_model, :base_model_type,
                        :description, 1, 1, :trained_words,
                        :published_at, :created_at
                    )
                """), {
                    "model_id": model_v2_id,
                    "civitai_version_id": civitai_version_id,
                    "name": version_data.get("name", "v1.0"),
                    "base_model": version_data.get("baseModel"),
                    "base_model_type": version_data.get("baseModelType"),
                    "description": version_data.get("description"),
                    "trained_words": trained_words_json,
                    "published_at": version_data.get("publishedAt"),
                    "created_at": row[7]
                })
                
                # Get version ID
                version_result = conn.execute(text(
                    "SELECT id FROM model_versions WHERE civitai_version_id = :vid"
                ), {"vid": civitai_version_id})
                version_id = version_result.scalar()
                
                if not version_id:
                    continue
                
                # Create files
                files = version_data.get("files", [])
                for i, file_data in enumerate(files):
                    hashes = file_data.get("hashes", {})
                    
                    # Compute storage filename
                    from core.entities_v2 import compute_storage_filename
                    storage_filename = compute_storage_filename(
                        metadata.get("name", "model"),
                        version_data.get("name", "v1"),
                        civitai_version_id,
                        file_data.get("name", "model.safetensors")
                    )
                    
                    conn.execute(text("""
                        INSERT INTO model_files (
                            version_id, civitai_file_id, original_filename, storage_filename,
                            size_kb, format, hash_sha256, hash_autov2, hash_blake3, hash_crc32,
                            download_url, is_primary, file_type
                        ) VALUES (
                            :version_id, :civitai_file_id, :original_filename, :storage_filename,
                            :size_kb, :format, :sha256, :autov2, :blake3, :crc32,
                            :download_url, :is_primary, :file_type
                        )
                    """), {
                        "version_id": version_id,
                        "civitai_file_id": file_data.get("id"),
                        "original_filename": file_data.get("name", "model.safetensors"),
                        "storage_filename": storage_filename,
                        "size_kb": file_data.get("sizeKB", 0),
                        "format": file_data.get("metadata", {}).get("format"),
                        "sha256": hashes.get("SHA256"),
                        "autov2": hashes.get("AutoV2"),
                        "blake3": hashes.get("BLAKE3"),
                        "crc32": hashes.get("CRC32"),
                        "download_url": file_data.get("downloadUrl"),
                        "is_primary": file_data.get("primary", i == 0),
                        "file_type": file_data.get("type", "Model")
                    })
                
                # Get primary file ID for provider status migration
                file_result = conn.execute(text(
                    "SELECT id FROM model_files WHERE version_id = :vid AND is_primary = 1"
                ), {"vid": version_id})
                file_id = file_result.scalar()
                
                # Migrate provider statuses
                if file_id and provider_statuses:
                    for provider_name, status_data in provider_statuses.items():
                        old_status = status_data.get("status", "pending")
                        # Map old statuses to new
                        status_map = {"installed": "ready", "downloading": "downloading", "failed": "failed"}
                        new_status = status_map.get(old_status, "pending")
                        
                        conn.execute(text("""
                            INSERT INTO provider_version_status (
                                file_id, provider_name, status, storage_path, size_bytes,
                                downloaded_at
                            ) VALUES (
                                :file_id, :provider_name, :status, :storage_path, :size_bytes,
                                :downloaded_at
                            )
                        """), {
                            "file_id": file_id,
                            "provider_name": provider_name,
                            "status": new_status,
                            "storage_path": f"{row[2]}/{row[1]}",  # directory/filename
                            "size_bytes": status_data.get("size_bytes"),
                            "downloaded_at": status_data.get("updated_at")
                        })
                
                # Create images
                images = version_data.get("images", [])
                for i, img_data in enumerate(images):
                    conn.execute(text("""
                        INSERT INTO model_images (
                            version_id, url, width, height, blurhash, type,
                            nsfw_level, has_meta, has_positive_prompt, sort_order
                        ) VALUES (
                            :version_id, :url, :width, :height, :blurhash, :type,
                            :nsfw_level, :has_meta, :has_positive_prompt, :sort_order
                        )
                    """), {
                        "version_id": version_id,
                        "url": img_data.get("url"),
                        "width": img_data.get("width"),
                        "height": img_data.get("height"),
                        "blurhash": img_data.get("hash"),
                        "type": img_data.get("type", "image"),
                        "nsfw_level": img_data.get("nsfwLevel", 1),
                        "has_meta": img_data.get("hasMeta", False),
                        "has_positive_prompt": img_data.get("hasPositivePrompt", False),
                        "sort_order": i
                    })
                
                migrated += 1
                
            except Exception as e:
                logger.error("migration_v2_model_error", model_name=row[1], error=str(e))
                continue
        
        conn.commit()
        logger.info("migration_v2_complete", migrated=migrated)
