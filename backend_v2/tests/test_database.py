"""Tests for infrastructure/database.py"""

import os
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import inspect, text
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


class TestDatabaseUrlPrecedence:
    """Which value wins, and is the loser reported.

    The finding: `get_database_url` said "an explicit `COMFY_DATABASE_URL` always
    wins" and then replaced any non-`postgresql` value with the DSN assembled
    from `POSTGRES_*` — which compose always sets. So the SQLite case, the only
    case the variable exists for, was thrown away, and the comment asserted the
    opposite of the code.

    Two branches, both asserted:

    * `POSTGRES_HOST` set and `COMFY_DATABASE_URL` not a `postgresql` URL ->
      Postgres wins (that is what the compose deployment means), and the
      discarded value is now **logged**, so it is no longer silent.
    * no `POSTGRES_HOST` -> `COMFY_DATABASE_URL` is used unchanged, which is the
      developer's local-SQLite path and the one the old code got right by
      accident.
    """

    @staticmethod
    def _env(**overrides):
        """A clean environment with only the POSTGRES_*/COMFY_* keys given."""
        base = {
            "COMFY_DATABASE_URL": "",
            "POSTGRES_HOST": "",
            "POSTGRES_PORT": "",
            "POSTGRES_USER": "",
            "POSTGRES_PASSWORD": "",
            "POSTGRES_DB": "",
        }
        base.update(overrides)
        return {k: v for k, v in base.items() if v != ""}

    def test_sqlite_url_survives_when_no_postgres_host(self):
        settings = MagicMock()
        settings.database_url = "sqlite:///./data/db/comfy.db"
        with patch.dict(os.environ, self._env(COMFY_DATABASE_URL="sqlite:///mine.db"), clear=False):
            for stale in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
                os.environ.pop(stale, None)
            with patch.object(db_module, "settings", settings):
                with patch("os.makedirs"):
                    assert db_module.get_database_url() == "sqlite:///mine.db"

    def test_postgres_env_wins_over_a_sqlite_url_and_says_so(self):
        settings = MagicMock()
        settings.database_url = "sqlite:///./data/db/comfy.db"
        env = self._env(
            COMFY_DATABASE_URL="sqlite:///./data/comfy.db",
            POSTGRES_HOST="db",
            POSTGRES_USER="comfy",
            POSTGRES_PASSWORD="comfy",
            POSTGRES_DB="comfy",
        )
        with patch.dict(os.environ, env, clear=False):
            with patch.object(db_module, "settings", settings):
                with patch.object(db_module.logger, "warning") as warned:
                    url = db_module.get_database_url()

        assert url == "postgresql://comfy:comfy@db:5432/comfy"
        # The point of the fix: the discard is reported, naming what was dropped.
        assert warned.call_count == 1
        assert "sqlite:///./data/comfy.db" in str(warned.call_args)

    def test_an_explicit_postgres_url_is_used_verbatim(self):
        """A `postgresql://` COMFY_DATABASE_URL was never in doubt; keep it pinned.

        This is the branch that must NOT consult POSTGRES_*: a managed instance
        reached by its own DSN has to win over the local `db` service.
        """
        settings = MagicMock()
        settings.database_url = "sqlite:///./data/db/comfy.db"
        env = self._env(
            COMFY_DATABASE_URL="postgresql://u:p@managed.example.com:5432/other",
            POSTGRES_HOST="db",
            POSTGRES_USER="comfy",
        )
        with patch.dict(os.environ, env, clear=False):
            with patch.object(db_module, "settings", settings):
                with patch.object(db_module.logger, "warning") as warned:
                    url = db_module.get_database_url()

        assert url == "postgresql://u:p@managed.example.com:5432/other"
        warned.assert_not_called()


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
            next(gen)

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
    def test_create_db_and_tables_runs(self, monkeypatch):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        monkeypatch.setattr(db_module, "engine", engine)
        monkeypatch.setattr(db_module, "database_url", "sqlite://")

        db_module.create_db_and_tables()

        assert "jobs" in inspect(engine).get_table_names()


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
        assert "acknowledged_at" in columns
        # Not the full version list. A hardcoded set of ~80 version strings breaks
        # every time a migration is added, which is a test that trains people to
        # update it by reflex rather than to read it — and the version table
        # already says what ran. What is worth asserting is that the steps this
        # test needs are among them.
        assert {
            "001_jobs_started_completed",
            "069_add_job_acknowledged_at",
            "075_index_asset_gallery_timestamp",
            "080_recreate_absent_indexes",
        } <= applied, f"expected migrations missing from {sorted(applied)}"

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
        with engine.connect() as conn:
            first_versions = [
                row[0]
                for row in conn.execute(
                    text("SELECT version FROM schema_migrations ORDER BY version")
                ).all()
            ]

        run_migrations(engine)
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT version FROM schema_migrations ORDER BY version")
            ).all()

        # The point is that a second run adds nothing, not that the list matches
        # a transcription of it. Compare against the first run's own output.
        after_second = [row[0] for row in rows]
        assert after_second == first_versions, (
            "a second run_migrations changed the recorded versions: "
            f"{set(after_second) ^ set(first_versions)}"
        )
        assert len(after_second) == len(set(after_second)), "duplicate version rows"

    def test_branching_migration_is_idempotent_with_existing_columns(self, tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path / 'branching.db'}")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE messages (id TEXT PRIMARY KEY, chat_id TEXT, parent_id TEXT, branch_id TEXT, branch_name VARCHAR(128))"))
            conn.execute(text("CREATE TABLE characters (id TEXT PRIMARY KEY, expressions JSON DEFAULT '{}', expressions_lora JSON DEFAULT '[]')"))

        from infrastructure.migrations.steps import _migration_042_add_branching_and_expressions

        with engine.begin() as conn:
            assert _migration_042_add_branching_and_expressions(conn) is True
            assert _migration_042_add_branching_and_expressions(conn) is True

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
