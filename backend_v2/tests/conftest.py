# Pytest configuration and fixtures

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from api.deps import get_session
from api.main import app
import infrastructure.database as _infra_db

# Need to import all models so SQLModel metadata is complete


@pytest.fixture(name="engine")
def engine_fixture():
    """Create in-memory SQLite engine for testing."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="session")
def session_fixture(engine):
    """Create database session for testing."""
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session):
    """Create test client with overridden database session."""
    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    _infra_db.get_session = get_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
    _infra_db.get_session = None


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
