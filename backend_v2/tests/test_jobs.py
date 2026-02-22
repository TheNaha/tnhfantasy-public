# Job API tests
import pytest


def test_health_check(client):
    """Test health endpoint."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_create_job(client, sample_job_data):
    """Test job creation."""
    response = client.post("/api/jobs", json=sample_job_data)
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["status"] == "pending"
    assert data["metadata"]["prompt"] == "a beautiful landscape"


def test_list_jobs_empty(client):
    """Test listing jobs when empty."""
    response = client.get("/api/jobs")
    assert response.status_code == 200
    data = response.json()
    assert "jobs" in data
    assert "total" in data
    assert data["total"] == 0


def test_list_jobs_with_data(client, sample_job_data):
    """Test listing jobs with data."""
    # Create a job first
    client.post("/api/jobs", json=sample_job_data)
    
    response = client.get("/api/jobs")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["jobs"]) == 1


def test_get_job(client, sample_job_data):
    """Test getting a specific job."""
    # Create a job
    create_response = client.post("/api/jobs", json=sample_job_data)
    job_id = create_response.json()["id"]
    
    # Get it
    response = client.get(f"/api/jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == job_id


def test_get_job_not_found(client):
    """Test getting non-existent job."""
    response = client.get("/api/jobs/nonexistent-id")
    assert response.status_code == 404


def test_delete_job(client, sample_job_data):
    """Test deleting a job."""
    # Create a job
    create_response = client.post("/api/jobs", json=sample_job_data)
    job_id = create_response.json()["id"]
    
    # Delete it
    response = client.delete(f"/api/jobs/{job_id}")
    assert response.status_code == 200
    
    # Verify it's gone
    get_response = client.get(f"/api/jobs/{job_id}")
    assert get_response.status_code == 404


def test_clear_jobs(client, sample_job_data):
    """Test clearing all jobs."""
    # Create some jobs
    client.post("/api/jobs", json=sample_job_data)
    client.post("/api/jobs", json=sample_job_data)
    
    # Clear all
    response = client.post("/api/jobs/clear")
    assert response.status_code == 200
    data = response.json()
    assert data["deleted"] == 2
    
    # Verify empty
    list_response = client.get("/api/jobs")
    assert list_response.json()["total"] == 0
