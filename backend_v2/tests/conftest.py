# Pytest configuration and fixtures
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from api.main import app
from api.deps import get_session
import infrastructure.database as _db_module
from core.entities import Job, Provider, Model


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

    # Override both the api.deps and infrastructure.database get_session
    # because some routes (prompts, collections) import directly from infrastructure.database
    app.dependency_overrides[get_session] = get_session_override
    app.dependency_overrides[_db_module.get_session] = get_session_override
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
