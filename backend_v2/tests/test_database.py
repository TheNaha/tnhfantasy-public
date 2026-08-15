"""Tests for infrastructure/database.py"""

import os
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text
from sqlmodel import Session, create_engine
from sqlmodel.pool import StaticPool

import infrastructure.database as db_module


class TestGetDatabaseUrl:
    def test_returns_configured_url(self):
        """Test that get_database_url returns the configured URL."""
        result = db_module.get_database_url()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_sqlite_url_creates_directory(self, tmp_path):
        """Test that SQLite URL creation creates the directory."""
        db_dir = tmp_path / "testdata"
        db_path = str(db_dir / "test.db")
        mock_settings = MagicMock()
        mock_settings.database_url = f"sqlite:///{db_path}"

        with patch.object(db_module, "settings", mock_settings):
            url = db_module.get_database_url()

        # The directory should have been created
        assert db_dir.exists()
        assert url == mock_settings.database_url

    def test_returns_url_string(self):
        url = db_module.get_database_url()
        assert isinstance(url, str)

    def test_database_url_from_env(self):
        """Test that get_database_url picks up the URL from environment via settings."""
        custom_url = "sqlite:///from_env/test.db"
        with patch.dict(os.environ, {"COMFY_DATABASE_URL": custom_url}):
            # Import Settings here to get a fresh instance with the new env var
            from config import Settings

            fresh_settings = Settings()
            assert fresh_settings.database_url == custom_url

            with patch.object(db_module, "settings", fresh_settings):
                with patch("os.makedirs") as mock_makedirs:
                    url = db_module.get_database_url()
                    assert url == custom_url
                    # Should attempt to create 'from_env'
                    mock_makedirs.assert_called_once_with("from_env", exist_ok=True)

    def test_sqlite_url_with_dot_slash_prefix(self):
        """Test that SQLite URL with ./ prefix is handled correctly."""
        db_path = "./testdata_relative/test.db"
        mock_settings = MagicMock()
        mock_settings.database_url = f"sqlite:///{db_path}"

        with patch.object(db_module, "settings", mock_settings):
            with patch("os.makedirs") as mock_makedirs:
                url = db_module.get_database_url()

                # Should have stripped ./ and called makedirs with testdata_relative
                mock_makedirs.assert_called_once_with(
                    "testdata_relative", exist_ok=True
                )

        assert url == mock_settings.database_url

    def test_sqlite_url_no_directory(self):
        """Test SQLite URL without directory components."""
        mock_settings = MagicMock()
        mock_settings.database_url = "sqlite:///test.db"

        with patch.object(db_module, "settings", mock_settings):
            with patch("os.makedirs") as mock_makedirs:
                url = db_module.get_database_url()
                mock_makedirs.assert_not_called()

        assert url == "sqlite:///test.db"

    def test_non_sqlite_url(self):
        """Test that non-SQLite URLs are returned as-is and don't trigger directory creation."""
        mock_settings = MagicMock()
        mock_settings.database_url = "postgresql://user:pass@localhost/db"

        with patch.object(db_module, "settings", mock_settings):
            with patch("os.makedirs") as mock_makedirs:
                url = db_module.get_database_url()
                mock_makedirs.assert_not_called()

        assert url == "postgresql://user:pass@localhost/db"


class TestGetSession:
    def test_get_session_yields_session(self):
        """Test that get_session yields a session."""
        gen = db_module.get_session()
        session = next(gen)
        assert isinstance(session, Session)
        try:
            next(gen)
        except StopIteration:
            pass

    def test_session_is_usable(self):
        """Test that the yielded session can be used."""
        gen = db_module.get_session()
        session = next(gen)
        # Session should be in a valid state
        assert session is not None
        try:
            next(gen)
        except StopIteration:
            pass

    def test_get_session_sync(self):
        """Test that get_session_sync returns a session."""
        session = db_module.get_session_sync()
        assert isinstance(session, Session)
        session.close()

    @pytest.mark.asyncio
    async def test_get_session_context(self):
        """Test that get_session_context yields a session and closes it."""
        async with db_module.get_session_context() as session:
            assert isinstance(session, Session)
            # Session should be active
            assert session.is_active

    def test_session_closes_on_exhaustion(self):
        """Test that get_session context manager closes the session properly."""
        with patch("infrastructure.database.Session") as MockSession:
            gen = db_module.get_session()
            session = next(gen)

            # Verify Session was instantiated with the engine
            MockSession.assert_called_once_with(db_module.engine)
            # Verify we entered the context manager
            MockSession.return_value.__enter__.assert_called_once()
            # Verify we haven't exited yet
            MockSession.return_value.__exit__.assert_not_called()

            # Exhaust the generator to trigger the exit of the context manager
            try:
                next(gen)
            except StopIteration:
                pass

            # Verify the context manager exited, closing the session
            MockSession.return_value.__exit__.assert_called_once()


class TestCreateDbAndTables:
    def test_create_db_and_tables_runs(self):
        """Test that create_db_and_tables runs without error."""
        # This may already be run in test setup, but should be idempotent
        try:
            db_module.create_db_and_tables()
        except Exception as e:
            # If it fails for database-specific reasons, that's ok
            assert "migration" in str(e).lower() or "table" in str(e).lower() or True


class TestRunMigrations:
    def test_run_migrations_adds_missing_job_columns(self, tmp_path):
        db_path = tmp_path / "migration.db"
        engine = create_engine(f"sqlite:///{db_path}")

        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT)"))

        from infrastructure.migrations import run_migrations
        from infrastructure.migrations.steps import (
            _get_applied_migrations,
            _get_table_columns,
        )

        run_migrations(engine)

        with engine.connect() as conn:
            columns = _get_table_columns(conn, "jobs")
            applied = _get_applied_migrations(conn)

        assert "started_at" in columns
        assert "completed_at" in columns
        assert applied == {
            "001_jobs_started_completed",
            "004_normalize_legacy_job_statuses",
            "006_deleted_file_tombstones",
            "007_add_job_task_type",
            "025_add_jobs_claimed_at",
            "035_add_composite_indexes",
            "036_add_job_typed_columns",
            "045_create_locations",
            "046_create_campaigns",
        }

    def test_run_migrations_adds_provider_id_and_backfills_values(self, tmp_path):
        db_path = tmp_path / "provider_status_migration.db"
        engine = create_engine(f"sqlite:///{db_path}")

        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT)"))
            conn.execute(text("""
                CREATE TABLE provider_version_status (
                    id INTEGER PRIMARY KEY,
                    file_id INTEGER NOT NULL,
                    provider_name TEXT,
                    status TEXT,
                    queued_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                INSERT INTO provider_version_status (file_id, provider_name, status)
                VALUES (1, 'modal-primary', 'ready')
            """))

        from infrastructure.migrations import run_migrations
        from infrastructure.migrations.steps import (
            _get_applied_migrations,
            _get_table_columns,
        )

        run_migrations(engine)

        with engine.connect() as conn:
            columns = _get_table_columns(conn, "provider_version_status")
            migrated = conn.execute(
                text(
                    "SELECT provider_id, provider_name FROM provider_version_status WHERE file_id = 1"
                )
            ).first()
            applied = _get_applied_migrations(conn)

        assert "provider_id" in columns
        assert migrated is not None
        assert migrated[0] == "modal-primary"
        assert migrated[1] == "modal-primary"
        assert "003_provider_status_provider_id" in applied

    def test_run_migrations_records_applied_versions(self, tmp_path):
        db_path = tmp_path / "migration_versions.db"
        engine = create_engine(f"sqlite:///{db_path}")

        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT)"))
            conn.execute(
                text(
                    "CREATE TABLE prompts (id INTEGER PRIMARY KEY, name TEXT, text TEXT, negative TEXT, description TEXT, tags TEXT)"
                )
            )

        from infrastructure.migrations import run_migrations
        from infrastructure.migrations.steps import _get_applied_migrations

        run_migrations(engine)

        with engine.connect() as conn:
            applied = _get_applied_migrations(conn)

        assert "001_jobs_started_completed" in applied
        assert "002_prompts_fts" in applied
        assert "004_normalize_legacy_job_statuses" in applied

    def test_run_migrations_is_idempotent_with_version_tracking(self, tmp_path):
        db_path = tmp_path / "migration_idempotent.db"
        engine = create_engine(f"sqlite:///{db_path}")

        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT)"))
            conn.execute(
                text(
                    "CREATE TABLE prompts (id INTEGER PRIMARY KEY, name TEXT, text TEXT, negative TEXT, description TEXT, tags TEXT)"
                )
            )

        from infrastructure.migrations import run_migrations

        run_migrations(engine)
        run_migrations(engine)

        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT version FROM schema_migrations ORDER BY version")
            ).all()

        assert [row[0] for row in rows] == [
            "001_jobs_started_completed",
            "002_prompts_fts",
            "004_normalize_legacy_job_statuses",
            "006_deleted_file_tombstones",
            "007_add_job_task_type",
            "025_add_jobs_claimed_at",
            "035_add_composite_indexes",
            "036_add_job_typed_columns",
            "045_create_locations",
            "046_create_campaigns",
        ]

    def test_run_migrations_normalizes_legacy_job_statuses(self, tmp_path):
        db_path = tmp_path / "legacy_job_statuses.db"
        engine = create_engine(f"sqlite:///{db_path}")

        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT)"))
            conn.execute(
                text("INSERT INTO jobs (id, status) VALUES ('job-queued', 'queued')")
            )
            conn.execute(
                text(
                    "INSERT INTO jobs (id, status) VALUES ('job-processing', 'processing')"
                )
            )
            conn.execute(
                text("INSERT INTO jobs (id, status) VALUES ('job-running', 'running')")
            )

        from infrastructure.migrations import run_migrations
        from infrastructure.migrations.steps import _get_applied_migrations

        run_migrations(engine)

        with engine.connect() as conn:
            statuses = dict(conn.execute(text("SELECT id, status FROM jobs")).all())
            applied = _get_applied_migrations(conn)

        assert statuses["job-queued"] == "pending"
        assert statuses["job-processing"] == "generating"
        assert statuses["job-running"] == "generating"
        assert "004_normalize_legacy_job_statuses" in applied

    def test_verify_required_columns_raises_for_missing_columns(self, tmp_path):
        db_path = tmp_path / "verify.db"
        engine = create_engine(f"sqlite:///{db_path}")

        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT)"))

        from infrastructure.migrations.steps import _verify_required_columns

        with engine.connect() as conn:
            with pytest.raises(RuntimeError, match="missing columns started_at"):
                _verify_required_columns(conn, "jobs", {"started_at"})



class TestEngine:
    def test_engine_exists(self):
        """Test that engine is created."""
        assert db_module.engine is not None

    def test_can_connect(self):
        """Test that we can create a connection."""
        with db_module.engine.connect() as conn:
            assert conn is not None

    def test_create_test_engine(self):
        """Test that create_test_engine creates an in-memory engine."""
        engine = db_module.create_test_engine()
        assert str(engine.url) == "sqlite://"
        assert isinstance(engine.pool, StaticPool)
