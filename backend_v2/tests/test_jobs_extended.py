"""Extended tests for api/routes/jobs.py"""
import pytest


class TestJobsRouteExtended:
    def test_validate_workflow(self, client, sample_workflow):
        response = client.post("/api/jobs/validate", json={"workflow": sample_workflow})
        assert response.status_code == 200

    def test_validate_invalid_workflow(self, client):
        response = client.post("/api/jobs/validate", json={"workflow": {}})
        assert response.status_code in (200, 400)

    def test_list_jobs_empty(self, client):
        response = client.get("/api/jobs")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))

    def test_list_jobs_after_create(self, client, sample_job_data):
        client.post("/api/generate", json=sample_job_data)
        response = client.get("/api/jobs")
        assert response.status_code == 200

    def test_get_job_queue(self, client):
        response = client.get("/api/jobs/queue")
        assert response.status_code == 200

    def test_get_jobs_stats_summary(self, client):
        response = client.get("/api/jobs/stats/summary")
        assert response.status_code == 200

    def test_get_job_by_id(self, client, sample_job_data):
        create_response = client.post("/api/generate", json=sample_job_data)
        job_id = create_response.json()["id"]
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == job_id

    def test_get_nonexistent_job(self, client):
        response = client.get("/api/jobs/nonexistent-id")
        assert response.status_code == 404

    def test_retry_job(self, client, sample_job_data):
        create_response = client.post("/api/generate", json=sample_job_data)
        job_id = create_response.json()["id"]
        response = client.post(f"/api/jobs/{job_id}/retry")
        assert response.status_code in (200, 400, 422)

    def test_delete_job(self, client, sample_job_data):
        create_response = client.post("/api/generate", json=sample_job_data)
        job_id = create_response.json()["id"]
        response = client.delete(f"/api/jobs/{job_id}")
        assert response.status_code in (200, 204)

    def test_delete_nonexistent_job(self, client):
        response = client.delete("/api/jobs/nonexistent-id")
        assert response.status_code in (200, 404)

    def test_clear_jobs(self, client):
        response = client.post("/api/jobs/clear")
        assert response.status_code == 200

    def test_delete_all_jobs(self, client):
        response = client.delete("/api/jobs")
        assert response.status_code in (200, 204)

    def test_create_multiple_jobs_and_list(self, client, sample_job_data):
        client.post("/api/generate", json=sample_job_data)
        client.post("/api/generate", json=sample_job_data)
        response = client.get("/api/jobs")
        assert response.status_code == 200
