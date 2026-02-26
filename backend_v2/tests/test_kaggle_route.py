"""Tests for api/routes/kaggle.py"""
import pytest


class TestKaggleRoute:
    def test_get_worker_script(self, client):
        response = client.get("/api/kaggle/worker.py")
        assert response.status_code == 200

    def test_worker_script_is_python(self, client):
        response = client.get("/api/kaggle/worker.py")
        content = response.text
        assert "KaggleWorker" in content

    def test_worker_script_content_type(self, client):
        response = client.get("/api/kaggle/worker.py")
        assert "text/plain" in response.headers.get("content-type", "")

    def test_get_setup_code(self, client):
        response = client.get(
            "/api/kaggle/setup-code",
            params={
                "backend_url": "http://localhost:8000",
                "token": "test-token"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "cells" in data

    def test_get_setup_code_with_tailscale(self, client):
        response = client.get(
            "/api/kaggle/setup-code",
            params={
                "backend_url": "http://example.com",
                "token": "secret-token",
                "tailscale_authkey": "ts-auth-key"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "cells" in data
        # With tailscale, should have 2 cells
        assert len(data["cells"]) == 2

    def test_get_setup_code_without_tailscale(self, client):
        response = client.get(
            "/api/kaggle/setup-code",
            params={
                "backend_url": "http://example.com",
                "token": "secret-token"
            }
        )
        assert response.status_code == 200
        data = response.json()
        # Without tailscale, should have 1 cell
        assert len(data["cells"]) == 1

    def test_get_setup_code_backend_url_embedded(self, client):
        response = client.get(
            "/api/kaggle/setup-code",
            params={
                "backend_url": "http://my-backend.com",
                "token": "my-token"
            }
        )
        data = response.json()
        # Backend URL should appear in the code
        code = data["cells"][0]["code"]
        assert "http://my-backend.com" in code

    def test_get_setup_code_custom_provider_id(self, client):
        response = client.get(
            "/api/kaggle/setup-code",
            params={
                "backend_url": "http://example.com",
                "token": "token",
                "provider_id": "my-kaggle-provider"
            }
        )
        assert response.status_code == 200
        data = response.json()
        code = data["cells"][0]["code"]
        assert "my-kaggle-provider" in code

    def test_setup_code_missing_required_params(self, client):
        response = client.get("/api/kaggle/setup-code")
        assert response.status_code == 422
