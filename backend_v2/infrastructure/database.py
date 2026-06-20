# Database setup with SQLModel
import os
from contextlib import asynccontextmanager
from typing import Generator

from sqlmodel import Session, SQLModel, create_engine

from config import settings
from infrastructure.logging import db_logger
from infrastructure.migrations import run_migrations

logger = db_logger()


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
            "timeout": 30,  # 30 second timeout for locks
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
        cursor.execute("PRAGMA cache_size = -32000")  # 32MB cache (negative = KB)
        cursor.execute("PRAGMA temp_store = MEMORY")  # Use memory for temp tables
        cursor.execute("PRAGMA mmap_size = 268435456")  # 256MB memory-mapped I/O

        cursor.close()

else:
    engine = create_engine(database_url, echo=False)


def create_db_and_tables() -> None:
    """Create all tables in the database."""
    # Import V1 entities to register them with SQLModel
    from core.entities import (Collection, CollectionImage, Job,
                               LoadBalancerState, LoadBalancingConfig,
                               Prompt, Provider)
    # Import V2 entities (normalized schema)
    from core.entities_v2 import (ModelFile, ModelImage, ModelTag, ModelV2,
                                  ModelVersion, ProviderVersionStatus, DeletedFileTombstone)

    SQLModel.metadata.create_all(engine)

    # Run migrations for existing databases
    run_migrations(engine)


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
    from sqlalchemy.pool import StaticPool
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
