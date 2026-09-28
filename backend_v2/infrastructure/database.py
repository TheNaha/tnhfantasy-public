# Database setup with SQLModel
import os
from collections.abc import Generator
from contextlib import asynccontextmanager
from urllib.parse import quote

from sqlmodel import Session, SQLModel, create_engine

from config import settings
from infrastructure.logging import db_logger
from infrastructure.migrations import run_migrations

logger = db_logger()


def _positive_int_env(name: str, default: int) -> int:
    """Read a positive int from the environment, falling back to `default`."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


# Explicit pool sizing for the Postgres path.
#
# Left unconfigured, SQLAlchemy's non-SQLite default is
# QueuePool(pool_size=5, max_overflow=10, pool_timeout=30) — a hard ceiling of
# 15 connections. That ceiling is easy to hit here because this app checks out
# connections from a thread pool as well as from request handlers: every
# `asyncio.to_thread(_something_sync)` helper, every LoadBalancer state
# persist, and every provider health probe opens its own session, and those run
# concurrently with the request-scoped sessions that are still held across
# long awaits. A gallery page firing 50 thumbnail requests plus a couple of
# in-flight chat requests used to exhaust the pool and 500 everything else after
# a 30s wait.
#
# The size is deliberately well above the concurrent-request count: the extra
# headroom is for to_thread DB helpers, which check out of this same pool, and
# for blocking-DB-in-async call sites. Override per deployment with
# COMFY_DB_POOL_SIZE / COMFY_DB_MAX_OVERFLOW / COMFY_DB_POOL_TIMEOUT.
DB_POOL_SIZE = _positive_int_env("COMFY_DB_POOL_SIZE", 30)
DB_MAX_OVERFLOW = _positive_int_env("COMFY_DB_MAX_OVERFLOW", 30)
DB_POOL_TIMEOUT = _positive_int_env("COMFY_DB_POOL_TIMEOUT", 30)
# Recycle below the usual 1h/infra limit so a long-lived pool never hands out a
# connection the far side has already dropped.
DB_POOL_RECYCLE = _positive_int_env("COMFY_DB_POOL_RECYCLE", 1800)


def _database_url_from_postgres_env() -> str | None:
    """Assemble a Postgres DSN from discrete `POSTGRES_*` variables.

    `docker-compose.yml` used to interpolate the DSN itself:

        COMFY_DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}

    A URL userinfo section cannot contain `@ : / #` unescaped, and
    `.env.example` tells the operator to pick their own password — so any of
    those four characters produced a DSN that fails to parse, the backend never
    passed its healthcheck, and every service with
    `depends_on: {backend_v2: {condition: service_healthy}}` (the frontend and
    all five providers) silently never started. Compose cannot percent-encode an
    interpolated value, so the assembly has to happen here.

    Returns `None` when `POSTGRES_HOST` is unset, which is how a SQLite or
    remote-Postgres deployment stays unaffected.
    """
    host = os.environ.get("POSTGRES_HOST")
    if not host:
        return None
    user = os.environ.get("POSTGRES_USER", "comfy")
    password = os.environ.get("POSTGRES_PASSWORD", "comfy")
    port = os.environ.get("POSTGRES_PORT", "5432")
    name = os.environ.get("POSTGRES_DB", "comfy")
    userinfo = quote(user, safe="")
    if password:
        userinfo = f"{userinfo}:{quote(password, safe='')}"
    # Only the userinfo is percent-encoded. SQLAlchemy's URL parser does not
    # decode the path, so encoding the database name would hand it a literal
    # `my%20db`; a name with a space in it is a misconfiguration, not a case to
    # silently transform into a different name.
    return f"postgresql://{userinfo}@{host}:{port}/{name}"


def get_database_url() -> str:
    """Get database URL, ensuring data directory exists."""
    # An explicit `COMFY_DATABASE_URL` always wins: that is how a developer
    # points at a local SQLite file or a managed instance.
    url = os.environ.get("COMFY_DATABASE_URL") or settings.database_url

    if not url.startswith("postgresql"):
        url = _database_url_from_postgres_env() or url

    # If using SQLite, ensure directory exists
    if url.startswith("sqlite"):
        # Extract path from sqlite:///./data/comfy.db
        db_path = url.replace("sqlite:///", "")
        db_path = db_path.removeprefix("./")

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
    engine = create_engine(
        database_url,
        echo=False,
        pool_size=DB_POOL_SIZE,
        max_overflow=DB_MAX_OVERFLOW,
        pool_timeout=DB_POOL_TIMEOUT,
        pool_recycle=DB_POOL_RECYCLE,
        pool_pre_ping=True,
    )


def _enable_pgvector_extension() -> None:
    """Enable pgvector extension for PostgreSQL databases."""
    if not database_url.startswith("postgresql"):
        return
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        logger.info("pgvector_extension_enabled")
    except Exception as exc:
        logger.error("pgvector_extension_failed", error=str(exc))


def create_db_and_tables() -> None:
    """Create all tables in the database."""
    # Import V1 entities to register them with SQLModel
    # Import V2 entities (normalized schema)
    # Import World Vault entities

    # Enable pgvector before creating tables (required for Vector columns)
    _enable_pgvector_extension()

    SQLModel.metadata.create_all(engine)

    # Run migrations for existing databases
    run_migrations(engine)


def _vacuum_sync() -> None:
    """The VACUUM itself. Blocking by nature — see `vacuum_database`."""
    from sqlalchemy import text

    if database_url.startswith("sqlite"):
        with engine.connect() as conn:
            conn.execute(text("VACUUM"))
            conn.commit()
    else:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("VACUUM (ANALYZE)"))


async def vacuum_database() -> None:
    """Run database maintenance using the configured dialect.

    Offloaded to a worker thread. `VACUUM (ANALYZE)` on a large Postgres database
    holds a connection and does real I/O for as long as it needs, and this runs
    from the daily APScheduler job — on an `AsyncIOScheduler`, the coroutine runs
    on the event loop, so the vacuum ran with the whole application stalled
    behind it.
    """
    import asyncio

    logger.info("vacuum_start")
    try:
        await asyncio.to_thread(_vacuum_sync)
        logger.info("vacuum_complete")
    except Exception as exc:
        logger.error("vacuum_failed", error=str(exc))


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
