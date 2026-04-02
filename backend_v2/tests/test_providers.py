# Provider API tests
import pytest


def test_list_providers_empty(client):
    """Test listing providers when empty."""
    response = client.get("/api/providers")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert data["providers"] == []


def test_create_provider(client, sample_provider_data):
    """Test creating a provider."""
    response = client.post("/api/providers", json=sample_provider_data)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "test-provider"
    assert data["type"] == "modal"
    assert data["enabled"] == True
    assert "credentials" not in data
    assert data["credential_summary"]["configured_fields"] == ["username"]


def test_get_provider(client, sample_provider_data):
    """Test getting a provider."""
    # Create first
    client.post("/api/providers", json=sample_provider_data)
    
    # Get it
    response = client.get("/api/providers/test-provider")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "test-provider"


def test_get_provider_not_found(client):
    """Test getting non-existent provider."""
    response = client.get("/api/providers/nonexistent")
    assert response.status_code == 404


def test_update_provider(client, sample_provider_data):
    """Test updating a provider."""
    # Create first
    client.post("/api/providers", json=sample_provider_data)
    
    # Update
    response = client.put("/api/providers/test-provider", json={"enabled": False})
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] == False


def test_delete_provider(client, sample_provider_data):
    """Test deleting a provider."""
    # Create first
    client.post("/api/providers", json=sample_provider_data)
    
    # Delete
    response = client.delete("/api/providers/test-provider")
    assert response.status_code == 200
    
    # Verify gone
    get_response = client.get("/api/providers/test-provider")
    assert get_response.status_code == 404


def test_load_balancing_config(client):
    """Test load balancing config endpoints."""
    # Get default config
    response = client.get("/api/providers/config/load-balancing")
    assert response.status_code == 200
    data = response.json()
    assert "config" in data
    assert "strategy" in data["config"]
    
    # Update config
    update_response = client.put(
        "/api/providers/config/load-balancing",
        json={"strategy": "random"}
    )
    assert update_response.status_code == 200
    # Assuming update response returns just the config or the full object
    # If it returns the config object:
    update_data = update_response.json()
    if "config" in update_data:
        assert update_data["config"]["strategy"] == "random"
    else:
        assert update_data["strategy"] == "random"
