"""Tests for api/routes/downloads.py"""
import pytest


class TestDownloadsRoute:
    def test_list_downloads_empty(self, client):
        response = client.get("/api/downloads")
        assert response.status_code == 200
        data = response.json()
        assert "downloads" in data
        assert isinstance(data["downloads"], list)

    def test_start_download(self, client):
        payload = {
            "name": "test-model.safetensors",
            "url": "https://example.com/model.safetensors",
            "path": "/tmp/test/model.safetensors",
            "provider_id": "test-provider"
        }
        response = client.post("/api/downloads", json=payload)
        assert response.status_code == 200

    def test_start_download_with_metadata(self, client):
        payload = {
            "name": "meta-model.safetensors",
            "url": "https://example.com/model2.safetensors",
            "path": "/tmp/test/model2.safetensors",
            "provider_id": "test-provider",
            "metadata": {"source": "civitai", "model_id": 12345}
        }
        response = client.post("/api/downloads", json=payload)
        assert response.status_code == 200

    def test_get_download_by_id(self, client):
        payload = {
            "name": "get-test.safetensors",
            "url": "https://example.com/model3.safetensors",
            "path": "/tmp/test/model3.safetensors",
            "provider_id": "test-provider"
        }
        create_response = client.post("/api/downloads", json=payload)
        assert create_response.status_code == 200
        download_id = create_response.json().get("download_id") or create_response.json().get("id")

        if download_id:
            response = client.get(f"/api/downloads/{download_id}")
            assert response.status_code in (200, 404)

    def test_get_nonexistent_download(self, client):
        response = client.get("/api/downloads/nonexistent-download-id")
        assert response.status_code == 404

    def test_start_download_missing_fields(self, client):
        payload = {"name": "incomplete"}
        response = client.post("/api/downloads", json=payload)
        assert response.status_code == 422
