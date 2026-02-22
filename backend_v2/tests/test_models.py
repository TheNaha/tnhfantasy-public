# Model API tests
import pytest


def test_list_models_empty(client):
    """Test listing models when empty."""
    response = client.get("/api/models")
    assert response.status_code == 200
    data = response.json()
    assert "models" in data


def test_add_model(client, sample_model_data):
    """Test adding a model."""
    response = client.post("/api/models", json=sample_model_data)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "test-model.safetensors"
    assert data["directory"] == "checkpoints"


def test_list_models_by_directory(client, sample_model_data):
    """Test listing models by directory."""
    # Add a model
    client.post("/api/models", json=sample_model_data)
    
    # List by directory
    response = client.get("/api/models/directory/checkpoints")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1


def test_get_model_cache(client, sample_model_data):
    """Test getting model cache."""
    # Add a model
    client.post("/api/models", json=sample_model_data)
    
    # Get cache
    response = client.get("/api/models/cache")
    assert response.status_code == 200
    data = response.json()
    assert "models" in data


def test_update_provider_status(client, sample_model_data):
    """Test updating model provider status."""
    # Add a model
    client.post("/api/models", json=sample_model_data)
    
    # Update status
    response = client.put(
        "/api/models/checkpoints/test-model.safetensors/providers/modal-test/status",
        json={"status": "installed"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "modal-test" in data["provider_statuses"]
    assert data["provider_statuses"]["modal-test"]["status"] == "installed"


def test_delete_model(client, sample_model_data):
    """Test deleting a model."""
    # Add a model
    client.post("/api/models", json=sample_model_data)
    
    # Delete
    response = client.delete("/api/models/checkpoints/test-model.safetensors")
    assert response.status_code == 200
    
    # Verify it's removed
    list_response = client.get("/api/models/directory/checkpoints")
    assert len(list_response.json()) == 0
