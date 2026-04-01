from unittest.mock import patch


def _workflow_with_checkpoint(name="missing-model.safetensors"):
    return {
        "nodes": {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": name},
            }
        }
    }


def test_jobs_and_generate_accept_the_same_routable_workflow(client, sample_job_data):
    jobs_response = client.post("/api/jobs", json=sample_job_data)
    generate_response = client.post("/api/generate", json=sample_job_data)

    assert jobs_response.status_code == 200
    assert generate_response.status_code == 200
    assert jobs_response.json()["status"] == "pending"
    assert generate_response.json()["status"] == "pending"


def test_jobs_and_generate_reject_the_same_unroutable_workflow(client):
    payload = {
        "workflow": _workflow_with_checkpoint(),
        "metadata": {"prompt": "test"},
    }

    with patch("services.job_submission_service.ModelAvailabilityService.check_availability") as check_availability:
        check_availability.return_value.valid = False
        check_availability.return_value.eligible_providers = []
        check_availability.return_value.missing_models = {
            "provider-a": {"checkpoints": ["missing-model.safetensors"]}
        }
        check_availability.return_value.global_missing = {
            "checkpoints": ["missing-model.safetensors"]
        }
        check_availability.return_value.can_trigger_download = True

        jobs_response = client.post("/api/jobs", json=payload)
        generate_response = client.post("/api/generate", json=payload)

    assert jobs_response.status_code == 400
    assert generate_response.status_code == 400
    assert jobs_response.json()["detail"] == generate_response.json()["detail"]
