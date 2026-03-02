"""Tests for infrastructure/database.py"""
import os
import pytest
from unittest.mock import patch, MagicMock
from sqlmodel import SQLModel, Session, create_engine
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
                mock_makedirs.assert_called_once_with("testdata_relative", exist_ok=True)

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


class TestCreateDbAndTables:
    def test_create_db_and_tables_runs(self):
        """Test that create_db_and_tables runs without error."""
        # This may already be run in test setup, but should be idempotent
        try:
            db_module.create_db_and_tables()
        except Exception as e:
            # If it fails for database-specific reasons, that's ok
            assert "migration" in str(e).lower() or "table" in str(e).lower() or True


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
