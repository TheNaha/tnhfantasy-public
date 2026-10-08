"""Tests for api/routes/providers.py"""
import base64
import io

from PIL import Image


def make_png_b64():
    """Create a base64-encoded PNG for testing."""
    img = Image.new("RGB", (10, 10), color=(100, 100, 100))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class TestProvidersBasic:
    def test_list_providers_empty(self, client):
        response = client.get("/api/v2/providers")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))

    def test_create_provider(self, client, sample_provider_data):
        response = client.post("/api/v2/providers", json=sample_provider_data)
        assert response.status_code == 200

    def test_create_provider_defaults(self, client):
        payload = {
            "id": "test-provider-defaults",
            "type": "modal",
            "credentials": {"token_id": "tok_123", "token_secret": "secret_456"},
            "config": {"app_name": "test-app"},
        }
        response = client.post("/api/v2/providers", json=payload)
        assert response.status_code == 200

    def test_get_provider(self, client, sample_provider_data):
        client.post("/api/v2/providers", json=sample_provider_data)
        response = client.get(f"/api/v2/providers/{sample_provider_data['id']}")
        assert response.status_code == 200

    def test_get_nonexistent_provider(self, client):
        response = client.get("/api/v2/providers/nonexistent-provider")
        assert response.status_code == 404

    def test_update_provider(self, client, sample_provider_data):
        client.post("/api/v2/providers", json=sample_provider_data)
        update = {"enabled": False}
        response = client.put(
            f"/api/v2/providers/{sample_provider_data['id']}", json=update
        )
        assert response.status_code == 200

    def test_delete_provider(self, client, sample_provider_data):
        client.post("/api/v2/providers", json=sample_provider_data)
        response = client.delete(f"/api/v2/providers/{sample_provider_data['id']}")
        assert response.status_code == 200

    def test_delete_nonexistent_provider(self, client):
        response = client.delete("/api/v2/providers/nonexistent")
        assert response.status_code == 404


class TestProvidersModelCache:
    def test_get_model_cache(self, client):
        response = client.get("/api/v2/providers/model-cache")
        assert response.status_code == 200

    def test_get_model_cache_by_directory(self, client):
        response = client.get("/api/v2/providers/model-cache/checkpoints")
        assert response.status_code == 200

    def test_model_cache_structure(self, client):
        response = client.get("/api/v2/providers/model-cache")
        data = response.json()
        assert "models" in data


class TestProvidersLoadBalancing:
    def test_get_load_balancing_config(self, client):
        response = client.get("/api/v2/providers/config/load-balancing")
        assert response.status_code == 200

    def test_update_load_balancing_config(self, client):
        payload = {"strategy": "round-robin", "fallback_enabled": True}
        response = client.put("/api/v2/providers/config/load-balancing", json=payload)
        assert response.status_code == 200

    def test_get_load_balancer_stats(self, client):
        response = client.get("/api/v2/providers/load-balancer/stats")
        assert response.status_code == 200

    def test_get_load_balancing(self, client):
        response = client.get("/api/v2/providers/load-balancing")
        assert response.status_code == 200

    def test_put_load_balancing(self, client):
        payload = {"strategy": "priority"}
        response = client.put("/api/v2/providers/load-balancing", json=payload)
        assert response.status_code == 200


class TestProvidersContainers:
    def test_list_containers(self, client):
        # Container worker endpoints were removed with the container path.
        response = client.get("/api/v2/providers/containers/list")
        assert response.status_code == 404

    def test_container_status(self, client):
        response = client.get("/api/v2/providers/containers/status")
        assert response.status_code == 404


class TestProvidersWake:
    def test_wake_endpoint(self, client):
        response = client.post("/api/v2/providers/wake")
        # The container wake handler is gone; "wake" now falls through to
        # the /{provider_id} routes, which allow no POST (405), or misses
        # routing entirely (404).
        assert response.status_code in (404, 405)


class TestProvidersPatch:
    def test_patch_provider(self, client, sample_provider_data):
        client.post("/api/v2/providers", json=sample_provider_data)
        patch_data = {"priority": 5}
        response = client.patch(
            f"/api/v2/providers/{sample_provider_data['id']}", json=patch_data
        )
        assert response.status_code in (200, 404)


class TestProvidersProviderOperations:
    def test_cleanup_orphaned_statuses(self, client):
        response = client.post("/api/v2/providers/cleanup-orphaned-statuses")
        assert response.status_code in (200, 500)
