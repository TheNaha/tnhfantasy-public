"""Tests for api/routes/generation.py"""
import pytest


class TestGenerationRoute:
    def test_generate_job(self, client, sample_workflow):
        payload = {"workflow": sample_workflow, "metadata": {"prompt": "a cat"}}
        response = client.post("/api/generate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "id" in data

    def test_generate_without_workflow(self, client):
        response = client.post("/api/generate", json={"metadata": {}})
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"
        assert response.json()["field"] == "workflow"

    def test_generate_empty_payload(self, client):
        response = client.post("/api/generate", json={})
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"
        assert response.json()["field"] == "workflow"

    def test_generate_with_metadata(self, client, sample_workflow):
        payload = {
            "workflow": sample_workflow,
            "metadata": {
                "prompt": "landscape",
                "seed": 42,
                "width": 512,
                "height": 512,
                "steps": 20
            }
        }
        response = client.post("/api/generate", json=payload)
        assert response.status_code == 200

    def test_generate_batch(self, client, sample_workflow):
        payload = {
            "workflows": [sample_workflow, sample_workflow],
            "metadata": {"prompt": "batch test"}
        }
        response = client.post("/api/generate/batch", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "jobs" in data
        assert data["count"] == 2

    def test_generate_batch_empty(self, client):
        response = client.post("/api/generate/batch", json={"workflows": []})
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"
        assert response.json()["field"] == "workflows"

    def test_generate_batch_without_workflows(self, client):
        response = client.post("/api/generate/batch", json={})
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"
        assert response.json()["field"] == "workflows"

    def test_generate_batch_single(self, client, sample_workflow):
        payload = {"workflows": [sample_workflow]}
        response = client.post("/api/generate/batch", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
