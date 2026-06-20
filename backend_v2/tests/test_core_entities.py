import pytest
from datetime import datetime
from sqlmodel import SQLModel

from core.entities import (
    Job, JobStatus,
    Provider,
    LoadBalancingConfig,
    LoadBalancerState,
    Prompt,
    Collection,
    CollectionImage
)

# ============================================================================
# Job Tests
# ============================================================================

def test_job_defaults():
    """Test default values for Job entity."""
    job = Job()

    assert job.id is not None
    assert isinstance(job.id, str)
    assert job.status == JobStatus.PENDING
    assert isinstance(job.created_at, datetime)
    assert isinstance(job.updated_at, datetime)
    assert job.started_at is None
    assert job.completed_at is None
    assert job.workflow == {}
    assert job.metadata_ == {}
    assert job.outputs == []
    assert job.progress == 0.0
    assert job.overall_progress == 0.0
    assert job.message is None
    assert job.error is None
    assert job.provider_id is None
    assert job.queue_position is None


def test_job_status_enum():
    """Test JobStatus enum values."""
    assert JobStatus.PENDING == "pending"
    assert JobStatus.RUNNING == "running"
    assert JobStatus.POST_PROCESSING == "post-processing"
    assert JobStatus.COMPLETED == "completed"
    assert JobStatus.FAILED == "failed"
    assert JobStatus.CANCELLED == "cancelled"


def test_job_instantiation():
    """Test Job instantiation with values."""
    workflow_data = {"node": 1}
    metadata_data = {"seed": 123}
    job = Job(
        status=JobStatus.RUNNING,
        workflow=workflow_data,
        metadata_=metadata_data,
        provider_id="provider-1"
    )

    assert job.status == JobStatus.RUNNING
    assert job.workflow == workflow_data
    assert job.metadata_ == metadata_data
    assert job.provider_id == "provider-1"


# ============================================================================
# Provider Tests
# ============================================================================

def test_provider_defaults():
    """Test default values for Provider entity."""
    # Provider requires an ID
    provider = Provider(id="test-provider")

    assert provider.id == "test-provider"
    assert provider.type == "modal"
    assert provider.enabled is True
    assert provider.priority == 1
    assert provider.credentials == {}
    assert provider.config == {}
    assert provider.container_config is None



# ============================================================================
# LoadBalancingConfig Tests
# ============================================================================

def test_load_balancing_config_defaults():
    """Test default values for LoadBalancingConfig."""
    config = LoadBalancingConfig()

    assert config.id == 1
    assert config.strategy == "round-robin"
    assert config.fallback_enabled is True


# ============================================================================
# LoadBalancerState Tests
# ============================================================================

def test_load_balancer_state_defaults():
    """Test default values for LoadBalancerState."""
    state = LoadBalancerState()

    assert state.id == 1
    assert state.round_robin_index == 0
    assert state.provider_job_counts == {}
    assert state.provider_failures == {}
    assert isinstance(state.updated_at, datetime)


# ============================================================================
# Prompt Tests
# ============================================================================

def test_prompt_defaults():
    """Test default values for Prompt entity."""
    # Prompt requires name and text
    prompt = Prompt(name="test-prompt", text="test text")

    assert prompt.name == "test-prompt"
    assert prompt.text == "test text"
    assert prompt.negative is None
    assert prompt.category == "Custom"
    assert prompt.description is None
    assert prompt.tags == []
    assert prompt.favorite is False
    assert prompt.usage_count == 0
    assert prompt.settings is None
    assert isinstance(prompt.created_at, datetime)


# ============================================================================
# Collection Tests
# ============================================================================

def test_collection_defaults():
    """Test default values for Collection entity."""
    # Collection requires name
    collection = Collection(name="test-collection")

    assert collection.name == "test-collection"
    assert collection.color == "#3B82F6"
    assert collection.description is None
    assert collection.thumbnail is None
    assert isinstance(collection.created_at, datetime)


def test_collection_image_instantiation():
    """Test CollectionImage instantiation."""
    ci = CollectionImage(collection_id=1, image_filename="img.png")

    assert ci.collection_id == 1
    assert ci.image_filename == "img.png"
    assert isinstance(ci.added_at, datetime)
