"""
Database migrations engine wrapper.
"""

from infrastructure.migrations.steps import (
    MigrationStep,
    _ensure_schema_migrations_table,
    _get_applied_migrations,
    _get_schema_migration_steps,
    _record_migration,
    logger,
)


def run_migrations(engine) -> None:
    """
    Run schema migrations for existing databases.
    Each migration is executed inside its own transaction boundary.
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
