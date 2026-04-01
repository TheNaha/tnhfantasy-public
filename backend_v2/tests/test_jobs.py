# Job API tests
import pytest
from infrastructure.request_dedup import clear_dedup_cache


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
    # Clear deduplication cache to avoid stale results from previous tests
    clear_dedup_cache()

    # Create a job first
    create_response = client.post("/api/jobs", json=sample_job_data)
    assert create_response.status_code == 200, f"Create job failed: {create_response.text}"

    # Clear cache again just to be safe (though POST doesn't use it, create might affect list)
    clear_dedup_cache()
    
    response = client.get("/api/jobs")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1, f"Expected 1 job, got {data['total']}. Response: {data}"
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
    response = client.delete("/api/jobs")
    assert response.status_code == 200
    data = response.json()
    assert data["deleted"] == 2
    
    # Clear cache before verifying
    clear_dedup_cache()

    # Verify empty
    list_response = client.get("/api/jobs")
    assert list_response.json()["total"] == 0


def test_create_job_idempotency_key_reuses_existing_result(client, sample_job_data):
    """Providing the same Idempotency-Key should not create duplicate jobs."""
    clear_dedup_cache()

    headers = {"Idempotency-Key": "job-create-key-1"}
    first = client.post("/api/jobs", json=sample_job_data, headers=headers)
    second = client.post("/api/jobs", json=sample_job_data, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    clear_dedup_cache()
    listed = client.get("/api/jobs")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


def test_create_job_without_idempotency_key_creates_distinct_jobs(client, sample_job_data):
    """Without Idempotency-Key, repeated submits should still create separate jobs."""
    clear_dedup_cache()

    first = client.post("/api/jobs", json=sample_job_data)
    second = client.post("/api/jobs", json=sample_job_data)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] != second.json()["id"]

    clear_dedup_cache()
    listed = client.get("/api/jobs")
    assert listed.status_code == 200
    assert listed.json()["total"] == 2
