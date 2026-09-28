"""
Database migrations engine wrapper.
"""

from sqlalchemy import text

from infrastructure.migrations.steps import (  # noqa: F401
    MigrationStep,
    _ensure_schema_migrations_table,
    _get_applied_migrations,
    _get_schema_migration_steps,
    _record_migration,
    logger,
)

# Advisory-lock key for the migration run. Any 64-bit constant, as long as it is
# stable and unique to this purpose.
_MIGRATION_LOCK_KEY = 8_926_411_773_004_155_001

# How long to wait for another process to finish migrating before giving up.
# Migrations take tens of seconds on a populated volume, so this is generous;
# the failure mode on timeout is a clear error rather than corruption.
_MIGRATION_LOCK_TIMEOUT_SECONDS = 300


def run_migrations(engine) -> None:
    """
    Run schema migrations for existing databases.
    Each migration is executed inside its own transaction boundary.

    Serialised across processes with a Postgres advisory lock.

    This is not a hypothetical. `create_db_and_tables()` runs `create_all` plus
    every migration step synchronously during startup, and nothing stopped two
    processes doing it at once: a `--scale backend_v2=2`, a second replica, or a
    blue/green cut all reach that code together. The failure is not a duplicate
    version row — the `_record_migration` insert is only reached after the
    step's own transaction commits, so the window is a step running twice
    concurrently. `ALTER TABLE ADD COLUMN` twice raises, which surfaces as a
    startup crash; a `CREATE INDEX` twice is idempotent and silently doubles the
    work; a backfill runs twice, which is slow and can double-count anything it
    accumulates. So the symptom ranges from a crash to silent slowness, none of
    which points at the real cause.

    The lock makes concurrent startup correct and is a no-op at one process,
    which is the current deployment. It is also the prerequisite for running
    more than one uvicorn worker: see `docs/audit-2026-09-29.md`.
    """
    from sqlalchemy import inspect

    is_postgres = engine.dialect.name == "postgresql"

    with engine.connect() as conn:
        inspector = inspect(engine)

        # Check if jobs table exists
        if "jobs" not in inspector.get_table_names():
            return

        # Rollback any autobegun transaction from inspection to start clean
        if conn.in_transaction():
            conn.rollback()

        # Serialise against other processes. `pg_advisory_lock` is
        # session-scoped, so it must be taken on THIS connection and released
        # before the connection returns to the pool — otherwise the lock is held
        # by whichever pooled session the connection later becomes, and the next
        # process blocks forever. Every path out of the `try` releases it.
        if is_postgres:
            if conn.in_transaction():
                conn.rollback()
            logger.info(
                "migration_lock_acquiring",
                timeout_seconds=_MIGRATION_LOCK_TIMEOUT_SECONDS,
            )
            # Called EXACTLY once. `pg_try_advisory_lock` is re-entrant per
            # session: each successful call increments a counter, and each
            # `pg_advisory_unlock` decrements one. Calling it twice and unlocking
            # once leaves the lock held on a connection that is about to go back
            # to the pool, where the next process would block until timeout.
            acquired = conn.execute(
                text("SELECT pg_try_advisory_lock(:key)"),
                {"key": _MIGRATION_LOCK_KEY},
            ).scalar()
            if not acquired:
                # Fall back to a blocking wait with a timeout, so a rolling
                # restart serialises rather than failing.
                conn.execute(
                    text("SET lock_timeout = :timeout"),
                    {"timeout": f"{_MIGRATION_LOCK_TIMEOUT_SECONDS}s"},
                )
                conn.execute(
                    text("SELECT pg_advisory_lock(:key)"),
                    {"key": _MIGRATION_LOCK_KEY},
                )
            if conn.in_transaction():
                conn.commit()

        try:
            _run_migrations_locked(conn, is_postgres)
        finally:
            if is_postgres:
                try:
                    if conn.in_transaction():
                        conn.rollback()
                    conn.execute(
                        text("SELECT pg_advisory_unlock(:key)"),
                        {"key": _MIGRATION_LOCK_KEY},
                    )
                    if conn.in_transaction():
                        conn.commit()
                except Exception as exc:  # pragma: no cover - lock hygiene
                    # The connection is returned to the pool at the end of the
                    # `with` block. A lock left held there blocks the next
                    # process indefinitely, so this is worth logging loudly even
                    # though nothing useful can be done about it here.
                    logger.error("migration_lock_release_failed", error=str(exc))


def _run_migrations_locked(conn, is_postgres: bool) -> None:
    """Apply every unapplied step. Caller must hold the advisory lock."""
    from sqlalchemy import inspect

    # Ensure migrations table is present, wrapped in a transaction block
    trans = conn.begin()
    try:
        _ensure_schema_migrations_table(conn)
        trans.commit()
    except Exception as e:
        trans.rollback()
        raise RuntimeError(f"Failed to ensure migrations table: {e}") from e

    # Get applied migrations (this autobegins a transaction)
    applied_versions = _get_applied_migrations(conn)

    # Rollback the read transaction to allow explicit begin() in loop
    if conn.in_transaction():
        conn.rollback()

    for step in _get_schema_migration_steps():
        if step.version in applied_versions:
            continue

        # Skip SQLite-specific and legacy enum migrations on PostgreSQL
        if is_postgres and step.version in ("002_prompts_fts", "004_normalize_legacy_job_statuses"):
            continue

        trans = conn.begin()
        try:
            applied = step.apply_fn(conn)
            if applied:
                _record_migration(conn, step)
            trans.commit()
            if applied:
                logger.info(
                    "migration_applied",
                    version=step.version,
                    description=step.description,
                )
        except Exception as e:
            trans.rollback()
            raise RuntimeError(
                f"Migration step {step.version} failed: {e}"
            ) from e

