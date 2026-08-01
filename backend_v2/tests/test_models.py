# Model API V2 tests

def test_list_models_empty(client):
    """Test listing models when empty."""
    response = client.get("/api/v2/models")
    assert response.status_code == 200
    data = response.json()
    assert "models" in data
    assert isinstance(data["models"], dict)
    assert len(data["models"]) == 0


def test_add_model(client, sample_model_v2_data):
    """Test adding a model."""
    response = client.post("/api/v2/models", json=sample_model_v2_data)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Model V2"
    assert data["civitai_model_id"] == 12345


def test_list_models(client, sample_model_v2_data):
    """Test listing models grouped by directory."""
    # Add a model
    client.post("/api/v2/models", json=sample_model_v2_data)
    
    # List models
    response = client.get("/api/v2/models")
    assert response.status_code == 200
    data = response.json()
    assert "models" in data

    # Checkpoints should be present (based on type "Checkpoint")
    assert "checkpoints" in data["models"]
    assert len(data["models"]["checkpoints"]) == 1
    assert data["models"]["checkpoints"][0]["name"] == "Test Model V2"


def test_list_all_models(client, sample_model_v2_data):
    """Test listing all models."""
    # Add a model
    client.post("/api/v2/models", json=sample_model_v2_data)
    
    # List all
    response = client.get("/api/v2/models/all")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Test Model V2"


def test_get_model(client, sample_model_v2_data):
    """Test getting a specific model."""
    # Add a model
    create_response = client.post("/api/v2/models", json=sample_model_v2_data)
    model_id = create_response.json()["id"]
    
    # Get it
    response = client.get(f"/api/v2/models/{model_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == model_id
    assert data["name"] == "Test Model V2"
    assert "versions" in data
    assert len(data["versions"]) == 1


def test_delete_model(client, sample_model_v2_data):
    """Test deleting a model."""
    # Add a model
    create_response = client.post("/api/v2/models", json=sample_model_v2_data)
    model_id = create_response.json()["id"]
    
    # Delete it
    response = client.delete(f"/api/v2/models/{model_id}")
    assert response.status_code == 200
    
    # Verify it's gone
    get_response = client.get(f"/api/v2/models/{model_id}")
    assert get_response.status_code == 404
