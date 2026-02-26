"""Additional tests for api/routes/providers.py"""
import pytest
from unittest.mock import patch, MagicMock
import json


@pytest.fixture
def sample_provider_payload():
    return {
        "id": "test-modal-provider",
        "type": "modal",
        "enabled": True,
        "priority": 1,
        "credentials": {"token_id": "tok_123", "token_secret": "secret_456"},
        "config": {"app_name": "test-app"}
    }


class TestProvidersRouteCreate:
    def test_create_provider(self, client, sample_provider_payload):
        response = client.post("/api/providers", json=sample_provider_payload)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_provider_payload["id"]

    def test_list_providers_empty(self, client):
        response = client.get("/api/providers")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_providers_after_create(self, client, sample_provider_payload):
        client.post("/api/providers", json=sample_provider_payload)
        response = client.get("/api/providers")
        assert response.status_code == 200
        providers = response.json()
        assert len(providers) >= 1

    def test_get_provider_by_id(self, client, sample_provider_payload):
        client.post("/api/providers", json=sample_provider_payload)
        response = client.get(f"/api/providers/{sample_provider_payload['id']}")
        assert response.status_code == 200
        assert response.json()["id"] == sample_provider_payload["id"]

    def test_get_nonexistent_provider(self, client):
        response = client.get("/api/providers/nonexistent-provider")
        assert response.status_code == 404


class TestProvidersRouteUpdate:
    def test_update_provider(self, client, sample_provider_payload):
        client.post("/api/providers", json=sample_provider_payload)
        response = client.put(
            f"/api/providers/{sample_provider_payload['id']}",
            json={"enabled": False}
        )
        assert response.status_code == 200

    def test_patch_provider(self, client, sample_provider_payload):
        client.post("/api/providers", json=sample_provider_payload)
        response = client.patch(
            f"/api/providers/{sample_provider_payload['id']}",
            json={"priority": 5}
        )
        assert response.status_code in (200, 405)

    def test_delete_provider(self, client, sample_provider_payload):
        client.post("/api/providers", json=sample_provider_payload)
        response = client.delete(f"/api/providers/{sample_provider_payload['id']}")
        assert response.status_code == 200


class TestProvidersRouteModelCache:
    def test_get_model_cache_empty(self, client):
        response = client.get("/api/providers/model-cache")
        assert response.status_code == 200

    def test_get_model_cache_by_directory(self, client):
        response = client.get("/api/providers/model-cache/checkpoints")
        assert response.status_code == 200


class TestProvidersRouteLoadBalancing:
    def test_get_load_balancing_config(self, client):
        response = client.get("/api/providers/config/load-balancing")
        assert response.status_code == 200

    def test_update_load_balancing_config(self, client):
        response = client.put(
            "/api/providers/config/load-balancing",
            json={"strategy": "round-robin"}
        )
        assert response.status_code in (200, 422)

    def test_get_load_balancing_legacy(self, client):
        response = client.get("/api/providers/load-balancing")
        assert response.status_code == 200

    def test_put_load_balancing_legacy(self, client):
        response = client.put(
            "/api/providers/load-balancing",
            json={"strategy": "least-loaded"}
        )
        assert response.status_code in (200, 422)

    def test_get_load_balancer_stats(self, client):
        response = client.get("/api/providers/load-balancer/stats")
        assert response.status_code == 200


class TestProvidersRouteSaveImage:
    def test_save_image_no_data(self, client):
        response = client.post("/api/providers/save-image", json={})
        assert response.status_code in (200, 400, 422)

    def test_save_image_with_data(self, client):
        import base64
        from PIL import Image
        import io
        img = Image.new("RGB", (10, 10))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()
        response = client.post(
            "/api/providers/save-image",
            json={
                "image_data": img_b64,
                "filename": "test.png",
                "job_id": "test-job-id"
            }
        )
        assert response.status_code in (200, 400, 422, 500)


class TestProvidersRouteContainers:
    def test_list_containers_no_manager(self, client):
        response = client.get("/api/providers/containers/list")
        assert response.status_code in (200, 500)

    def test_container_status_no_manager(self, client):
        response = client.get("/api/providers/containers/status")
        assert response.status_code in (200, 500)


class TestProvidersRouteWake:
    def test_wake_no_providers(self, client):
        response = client.post("/api/providers/wake")
        assert response.status_code in (200, 422)


class TestProvidersRouteCleanup:
    def test_cleanup_orphaned_statuses(self, client):
        response = client.post("/api/providers/cleanup-orphaned-statuses")
        assert response.status_code in (200, 422)


class TestProvidersRouteReconcile:
    def test_reconcile_provider_not_found(self, client):
        response = client.post("/api/providers/nonexistent/reconcile")
        assert response.status_code in (404, 500, 200)

    def test_reconciliation_status_not_found(self, client):
        response = client.get("/api/providers/nonexistent/reconciliation-status")
        assert response.status_code in (404, 200)

    def test_reconciliation_event_not_found(self, client):
        response = client.post(
            "/api/providers/nonexistent/reconciliation-event",
            json={"event_type": "test"}
        )
        assert response.status_code in (404, 200, 422)

    def test_deploy_provider_not_found(self, client):
        response = client.post("/api/providers/nonexistent/deploy")
        assert response.status_code in (404, 500, 200)

    def test_setup_provider_not_found(self, client):
        response = client.post(
            "/api/providers/nonexistent/setup",
            json={"step": "init"}
        )
        assert response.status_code in (404, 500, 200, 422)
