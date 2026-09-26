# Pytest configuration and fixtures

import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from api.deps import get_session
from api.main import app
import infrastructure.database as _infra_db

# Disable provider health checks in tests (LoadBalancer defaults to enabled in prod)
os.environ.setdefault("COMFY_LB_HEALTH_CHECKS_ENABLED", "0")

# Need to import all models so SQLModel metadata is complete


@pytest.fixture(name="engine")
def engine_fixture():
    """Create in-memory SQLite engine for testing.

    Foreign-key enforcement is switched ON. SQLite ignores FKs by default, so
    without this the whole suite was blind to exactly the class of bug Postgres
    rejects at runtime — e.g. delete_character raising IntegrityError because
    voice_models.character_id still pointed at the deleted row. Enabling it here
    means a schema/reference mistake fails in CI instead of in production.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="session")
def session_fixture(engine):
    """Create database session for testing."""
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def _redirect_sync_sessions(engine):
    """Point every `get_session_sync()` caller at the test database.

    Service code opens its own session through `get_session_sync()` —
    statistics aggregation, reconciliation, the load balancer, file cleanup.
    Two things made that hard to contain:

    * the redirection used to live inside `client_fixture`, so a test that
      exercised such a service *without* requesting `client` ran against the
      developer's real `data/comfy.db` — it saw production rows, and a service
      that writes would have written them.
    * modules that do `from api.deps import get_session_sync` bind the function
      into their own namespace at import time, so rebinding the attribute on
      `api.deps` (or `infrastructure.database`) afterwards never reached them.
      `api/routes/files.py` is the case that surfaced it: its `_sync_session()`
      quietly used the on-disk database.

    So this rebinds the name in every already-imported module, not just on the
    two modules that define it.
    """
    def get_session_sync_override():
        return Session(engine)

    import api.deps as _api_deps

    original_infra = _infra_db.get_session_sync
    original_deps = _api_deps.get_session_sync
    known_originals = {id(original_infra), id(original_deps)}

    rebound: list[tuple[object, str, object]] = []
    for module in list(sys.modules.values()):
        if module is None:
            continue
        current = getattr(module, "get_session_sync", None)
        if current is not None and id(current) in known_originals:
            setattr(module, "get_session_sync", get_session_sync_override)
            rebound.append((module, current))

    _infra_db.get_session_sync = get_session_sync_override
    _api_deps.get_session_sync = get_session_sync_override
    try:
        yield
    finally:
        _infra_db.get_session_sync = original_infra
        _api_deps.get_session_sync = original_deps
        for module, original in rebound:
            module.get_session_sync = original


@pytest.fixture(name="client")
def client_fixture(session: Session, engine):
    """Create test client with overridden database session."""
    def get_session_override():
        return session

    def get_session_sync_override():
        return Session(engine)

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def sample_workflow():
    """Sample ComfyUI workflow for testing."""
    return {
        "nodes": {
            "1": {"class_type": "KSampler", "inputs": {}},
            "2": {"class_type": "VAEDecode", "inputs": {}},
        }
    }


@pytest.fixture
def sample_job_data(sample_workflow):
    """Sample job creation data."""
    return {
        "workflow": sample_workflow,
        "metadata": {
            "prompt": "a beautiful landscape",
            "seed": 12345,
            "width": 512,
            "height": 512
        }
    }


@pytest.fixture
def sample_provider_data():
    """Sample provider creation data."""
    return {
        "id": "test-provider",
        "type": "modal",
        "enabled": True,
        "priority": 1,
        "credentials": {"username": "test"},
        "config": {"app_name": "test-app"}
    }


@pytest.fixture
def sample_model_data():
    """Sample model creation data."""
    return {
        "name": "test-model.safetensors",
        "directory": "checkpoints",
        "url": "https://example.com/model.safetensors",
        "source": "custom",
        "metadata": {"size": 1000000}
    }


@pytest.fixture
def sample_model_v2_data():
    """Sample model V2 creation data."""
    return {
        "civitai_data": {
            "id": 12345,
            "name": "Test Model V2",
            "type": "Checkpoint",
            "nsfw": False,
            "creator": {"username": "testuser"},
            "description": "Test description",
            "stats": {"downloadCount": 100},
            "tags": ["anime", "style"],
            "modelVersions": [
                {
                    "id": 67890,
                    "name": "v1.0",
                    "baseModel": "SD 1.5",
                    "files": [
                        {
                            "name": "model.safetensors",
                            "sizeKB": 2048000,
                            "type": "Model",
                            "metadata": {"format": "SafeTensor", "size": "pruned", "fp": "fp16"},
                            "pickleScanMessage": "No Pickle imports",
                            "virusScanMessage": "No virus found",
                            "scannedAt": "2023-01-01T00:00:00.000Z",
                            "hashes": {"AutoV2": "1234567890"},
                            "downloadUrl": "https://civitai.com/api/download/models/67890",
                            "primary": True
                        }
                    ],
                    "images": []
                }
            ]
        },
        "selected_versions": [
            {"version_id": 67890, "is_default": True}
        ]
    }
