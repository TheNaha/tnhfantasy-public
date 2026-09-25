# Health API tests

def test_health_check(client):
    """Test health endpoint."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "2.0.0"


def test_readiness_check(client):
    response = client.get("/api/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
