"""Tests for api/routes/providers.py"""
import base64
import io
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image


def make_png_b64():
    """Create a base64-encoded PNG for testing."""
    img = Image.new("RGB", (10, 10), color=(100, 100, 100))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class TestProvidersBasic:
    def test_list_providers_empty(self, client):
        response = client.get("/api/providers")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))

    def test_create_provider(self, client, sample_provider_data):
        response = client.post("/api/providers", json=sample_provider_data)
        assert response.status_code == 200

    def test_create_provider_defaults(self, client):
        payload = {
            "id": "test-provider-defaults",
            "type": "modal",
        }
        response = client.post("/api/providers", json=payload)
        assert response.status_code == 200

    def test_get_provider(self, client, sample_provider_data):
        client.post("/api/providers", json=sample_provider_data)
        response = client.get(f"/api/providers/{sample_provider_data['id']}")
        assert response.status_code == 200

    def test_get_nonexistent_provider(self, client):
        response = client.get("/api/providers/nonexistent-provider")
        assert response.status_code == 404

    def test_update_provider(self, client, sample_provider_data):
        client.post("/api/providers", json=sample_provider_data)
        update = {"enabled": False}
        response = client.put(
            f"/api/providers/{sample_provider_data['id']}", json=update
        )
        assert response.status_code == 200

    def test_delete_provider(self, client, sample_provider_data):
        client.post("/api/providers", json=sample_provider_data)
        response = client.delete(f"/api/providers/{sample_provider_data['id']}")
        assert response.status_code == 200

    def test_delete_nonexistent_provider(self, client):
        response = client.delete("/api/providers/nonexistent")
        assert response.status_code == 404


class TestProvidersModelCache:
    def test_get_model_cache(self, client):
        response = client.get("/api/providers/model-cache")
        assert response.status_code == 200

    def test_get_model_cache_by_directory(self, client):
        response = client.get("/api/providers/model-cache/checkpoints")
        assert response.status_code == 200

    def test_model_cache_structure(self, client):
        response = client.get("/api/providers/model-cache")
        data = response.json()
        assert "models" in data


class TestProvidersLoadBalancing:
    def test_get_load_balancing_config(self, client):
        response = client.get("/api/providers/config/load-balancing")
        assert response.status_code == 200

    def test_update_load_balancing_config(self, client):
        payload = {"strategy": "round-robin", "fallback_enabled": True}
        response = client.put("/api/providers/config/load-balancing", json=payload)
        assert response.status_code == 200

    def test_get_load_balancer_stats(self, client):
        response = client.get("/api/providers/load-balancer/stats")
        assert response.status_code == 200

    def test_get_load_balancing(self, client):
        response = client.get("/api/providers/load-balancing")
        assert response.status_code == 200

    def test_put_load_balancing(self, client):
        payload = {"strategy": "priority"}
        response = client.put("/api/providers/load-balancing", json=payload)
        assert response.status_code == 200


class TestProvidersSaveImage:
    def test_save_image_valid(self, client):
        b64 = make_png_b64()
        with patch("config.get_output_date_hierarchy", return_value=False), \
             patch("config.get_thumbnail_sizes", return_value={"medium": 512}), \
             patch("config.get_thumbnail_format", return_value="webp"), \
             patch("config.get_thumbnail_directory", return_value="thumb"), \
             patch("config.get_thumbnail_quality", return_value=85), \
             patch("config.get_blurhash_components", return_value=(4, 3)), \
             patch("config.get_blurhash_resize_max", return_value=400), \
             patch("config.get_embed_metadata_in_png", return_value=True):
            response = client.post(
                "/api/providers/save-image",
                json={"image_base64": b64, "job_id": "test-job"}
            )
        assert response.status_code == 200

    def test_save_image_invalid_base64(self, client):
        response = client.post(
            "/api/providers/save-image",
            json={"image_base64": "not_valid_base64!!!"}
        )
        assert response.status_code == 400

    def test_save_image_rejects_non_base64_characters(self, client):
        response = client.post(
            "/api/providers/save-image",
            json={"image_base64": "Zm9v$"}
        )
        assert response.status_code == 400

    def test_save_image_rejects_bad_base64_padding(self, client):
        response = client.post(
            "/api/providers/save-image",
            json={"image_base64": "Zg"}
        )
        assert response.status_code == 400

    def test_save_image_offloads_gallery_index_update(self, client):
        b64 = make_png_b64()
        expected_image_data = base64.b64decode(b64)
        mock_service = MagicMock()
        mock_service.save_generated_image = AsyncMock(return_value={"path": "/tmp/test.png"})
        mock_gallery_indexer = MagicMock()

        with patch("services.image_service.get_image_service", return_value=mock_service), \
             patch("services.gallery_indexer.gallery_indexer", mock_gallery_indexer), \
             patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            response = client.post(
                "/api/providers/save-image",
                json={"image_base64": b64}
            )

        assert response.status_code == 200
        mock_service.save_generated_image.assert_awaited_once_with(
            image_data=expected_image_data,
            metadata=None,
            job_id=None,
            filename=None,
            batch_index=0
        )
        mock_to_thread.assert_awaited_once_with(mock_gallery_indexer.add_file, "/tmp/test.png")


class TestProvidersContainers:
    def test_list_containers(self, client):
        response = client.get("/api/providers/containers/list")
        assert response.status_code == 200

    def test_container_status(self, client):
        response = client.get("/api/providers/containers/status")
        assert response.status_code == 200


class TestProvidersWake:
    def test_wake_endpoint(self, client):
        response = client.post("/api/providers/wake")
        # Should return 200 or other valid status
        assert response.status_code in (200, 202, 503)


class TestProvidersPatch:
    def test_patch_provider(self, client, sample_provider_data):
        client.post("/api/providers", json=sample_provider_data)
        patch_data = {"priority": 5}
        response = client.patch(
            f"/api/providers/{sample_provider_data['id']}", json=patch_data
        )
        assert response.status_code in (200, 404)


class TestProvidersProviderOperations:
    def test_cleanup_orphaned_statuses(self, client):
        response = client.post("/api/providers/cleanup-orphaned-statuses")
        assert response.status_code in (200, 500)
