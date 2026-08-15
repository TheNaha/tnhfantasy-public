"""Tests for api/routes/generation.py"""

from core.entities import Provider
from infrastructure.request_dedup import clear_dedup_cache


class TestGenerationRoute:
    def test_generate_job(self, client, sample_workflow):
        payload = {"workflow": sample_workflow, "metadata": {"prompt": "a cat"}}
        response = client.post("/api/generate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "id" in data

    def test_generate_without_workflow(self, client):
        response = client.post("/api/generate", json={"metadata": {}})
        assert response.status_code == 400
        assert response.json()["code"] == "VALIDATION_ERROR"
        assert response.json()["field"] == "workflow"

    def test_generate_empty_payload(self, client):
        response = client.post("/api/generate", json={})
        assert response.status_code == 400
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

    def test_generate_batch_merges_per_workflow_metadata(self, client, sample_workflow):
        payload = {
            "workflows": [
                {**sample_workflow, "metadata": {"prompt": "first prompt", "seed": 11}},
                {**sample_workflow, "metadata": {"prompt": "second prompt"}},
            ],
            "metadata": {"prompt": "request-level prompt"}
        }
        response = client.post("/api/generate/batch", json=payload)
        assert response.status_code == 200
        jobs = response.json()["jobs"]
        assert jobs[0]["metadata"]["prompt"] == "first prompt"
        assert jobs[0]["metadata"]["seed"] == 11
        assert jobs[1]["metadata"]["prompt"] == "second prompt"
        assert jobs[0]["metadata"]["batch_index"] == 0
        assert jobs[1]["metadata"]["batch_index"] == 1

    def test_generate_batch_empty(self, client):
        response = client.post("/api/generate/batch", json={"workflows": []})
        assert response.status_code == 400
        assert response.json()["code"] == "VALIDATION_ERROR"
        assert response.json()["field"] == "workflows"

    def test_generate_batch_without_workflows(self, client):
        response = client.post("/api/generate/batch", json={})
        assert response.status_code == 400
        assert response.json()["code"] == "VALIDATION_ERROR"
        assert response.json()["field"] == "workflows"

    def test_generate_batch_single(self, client, sample_workflow):
        payload = {"workflows": [sample_workflow]}
        response = client.post("/api/generate/batch", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1

    def test_generate_and_jobs_routes_reject_missing_models_consistently(self, client):
        workflow = {
            "nodes": {
                "1": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {"ckpt_name": "missing-model.safetensors"},
                }
            }
        }
        payload = {"workflow": workflow, "metadata": {"prompt": "a cat"}}

        generate_response = client.post("/api/generate", json=payload)
        jobs_response = client.post("/api/jobs", json=payload)

        assert generate_response.status_code == 400
        assert jobs_response.status_code == 400
        assert generate_response.json()["error"] == jobs_response.json()["error"]

    def test_generate_and_jobs_routes_accept_same_workflow(self, client, sample_workflow):
        payload = {"workflow": sample_workflow, "metadata": {"prompt": "same contract"}}

        generate_response = client.post("/api/generate", json=payload)
        jobs_response = client.post("/api/jobs", json=payload)

        assert generate_response.status_code == 200
        assert jobs_response.status_code == 200

    def test_generate_idempotency_key_reuses_job(self, client, sample_workflow):
        clear_dedup_cache()
        payload = {"workflow": sample_workflow, "metadata": {"prompt": "idempotent generate"}}
        headers = {"Idempotency-Key": "generate-key-1"}

        first = client.post("/api/generate", json=payload, headers=headers)
        second = client.post("/api/generate", json=payload, headers=headers)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]

    def test_generate_batch_idempotency_key_reuses_batch(self, client, sample_workflow):
        clear_dedup_cache()
        payload = {
            "workflows": [sample_workflow, sample_workflow],
            "metadata": {"prompt": "idempotent batch"},
        }
        headers = {"Idempotency-Key": "generate-batch-key-1"}

        first = client.post("/api/generate/batch", json=payload, headers=headers)
        second = client.post("/api/generate/batch", json=payload, headers=headers)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["count"] == 2
        assert second.json()["count"] == 2
        assert first.json()["jobs"][0]["id"] == second.json()["jobs"][0]["id"]
        assert first.json()["jobs"][1]["id"] == second.json()["jobs"][1]["id"]


def test_generate_and_jobs_share_missing_model_validation(client, session):
    session.add(
        Provider(
            id="provider-1",
            type="modal",
            enabled=True,
            priority=1,
            credentials={},
            config={"app_name": "test"},
            container_config={"port": 8000},
        )
    )
    session.commit()

    workflow = {
        "nodes": {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "missing-model.safetensors"},
            }
        }
    }
    payload = {"workflow": workflow, "metadata": {"prompt": "missing model test"}}

    generate_response = client.post("/api/generate", json=payload)
    jobs_response = client.post("/api/jobs", json=payload)

    assert generate_response.status_code == 400
    assert jobs_response.status_code == 400
    assert generate_response.json()["error"] == jobs_response.json()["error"]
