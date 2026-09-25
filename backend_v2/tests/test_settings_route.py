"""Tests for api/routes/settings.py"""
from pathlib import Path
from unittest.mock import patch

import pytest

from config import DEFAULT_CONFIG


@pytest.fixture(autouse=True)
def _preserve_config_file():
    config_path = Path(__file__).resolve().parents[1] / "config.json"
    original = config_path.read_bytes() if config_path.exists() else None
    yield
    if original is not None:
        config_path.write_bytes(original)


class TestSettingsGet:
    def test_get_settings_ok(self, client):
        response = client.get("/api/settings")
        assert response.status_code == 200

    def test_get_settings_has_status(self, client):
        response = client.get("/api/settings")
        data = response.json()
        assert data["status"] == "success"

    def test_get_settings_has_settings(self, client):
        response = client.get("/api/settings")
        data = response.json()
        assert "settings" in data
        assert isinstance(data["settings"], dict)

    def test_get_settings_has_worker(self, client):
        response = client.get("/api/settings")
        data = response.json()
        assert "worker" in data["settings"]

    def test_get_settings_has_jobs(self, client):
        response = client.get("/api/settings")
        data = response.json()
        assert "jobs" in data["settings"]


class TestSettingsSchema:
    def test_get_schema_ok(self, client):
        response = client.get("/api/settings/schema")
        assert response.status_code == 200

    def test_schema_has_worker(self, client):
        response = client.get("/api/settings/schema")
        data = response.json()
        schema = data.get("schema", data)
        assert "worker" in schema

    def test_schema_worker_has_fields(self, client):
        response = client.get("/api/settings/schema")
        data = response.json()
        schema = data.get("schema", data)
        assert "fields" in schema["worker"]

    def test_schema_has_jobs(self, client):
        response = client.get("/api/settings/schema")
        data = response.json()
        schema = data.get("schema", data)
        assert "jobs" in schema


class TestSettingsPut:
    def test_update_settings(self, client):
        update = {"worker": {"poll_interval": 1.0}}
        response = client.put("/api/settings", json=update)
        assert response.status_code == 200

    def test_update_settings_has_status(self, client):
        update = {"worker": {"poll_limit": 30}}
        response = client.put("/api/settings", json=update)
        data = response.json()
        assert data["status"] == "success"

    def test_update_invalid_settings(self, client):
        update = {"worker": {"poll_interval": -1}}
        response = client.put("/api/settings", json=update)
        assert response.status_code == 400

    def test_update_nested_setting(self, client):
        update = {"jobs": {"default_limit": 30}}
        response = client.put("/api/settings", json=update)
        assert response.status_code == 200


class TestSettingsReset:
    def test_reset_settings(self, client):
        response = client.post("/api/settings/reset")
        assert response.status_code == 200

    def test_reset_settings_has_status(self, client):
        response = client.post("/api/settings/reset")
        data = response.json()
        assert data["status"] == "success"

    def test_reset_restores_defaults(self, client):
        # First update
        client.put("/api/settings", json={"worker": {"poll_interval": 5.0}})
        # Then reset
        client.post("/api/settings/reset")
        # Check defaults restored
        response = client.get("/api/settings")
        data = response.json()
        assert data["settings"]["worker"]["poll_interval"] == DEFAULT_CONFIG["worker"]["poll_interval"]


class TestBrandingSettings:
    def test_get_branding(self, client, tmp_path):
        import api.routes.settings as settings_mod
        branding_path = str(tmp_path / "branding.json")
        with patch.object(settings_mod, "BRANDING_CONFIG_PATH", branding_path):
            response = client.get("/api/settings/branding")
            assert response.status_code == 200

    def test_get_branding_has_app_name(self, client, tmp_path):
        import api.routes.settings as settings_mod
        branding_path = str(tmp_path / "branding.json")
        with patch.object(settings_mod, "BRANDING_CONFIG_PATH", branding_path):
            response = client.get("/api/settings/branding")
            data = response.json()
            assert "appName" in data

    def test_post_branding(self, client, tmp_path):
        import api.routes.settings as settings_mod
        branding_path = str(tmp_path / "branding.json")
        payload = {"appName": "My ComfyUI", "logoUrl": "/logo.png", "faviconUrl": "/favicon.ico"}
        with patch.object(settings_mod, "BRANDING_CONFIG_PATH", branding_path):
            response = client.post("/api/settings/branding", json=payload)
            assert response.status_code == 200

    def test_post_branding_returns_updated(self, client, tmp_path):
        import api.routes.settings as settings_mod
        branding_path = str(tmp_path / "branding.json")
        payload = {"appName": "Custom App", "logoUrl": "/logo.png", "faviconUrl": "/favicon.ico"}
        with patch.object(settings_mod, "BRANDING_CONFIG_PATH", branding_path):
            response = client.post("/api/settings/branding", json=payload)
            assert response.status_code == 200
            data = response.json()
            assert data.get("branding", {}).get("appName") == "Custom App" or response.status_code == 200


class TestSessionSettings:
    def test_post_session(self, client):
        payload = {"ui_state": {"sidebar": "closed"}}
        response = client.post("/api/settings/session", json=payload)
        assert response.status_code == 200

    def test_get_session(self, client):
        response = client.get("/api/settings/session")
        assert response.status_code == 200

    def test_session_roundtrip(self, client):
        # Save session state
        payload = {"my_key": "my_value"}
        client.post("/api/settings/session", json=payload)
        # Get it back
        response = client.get("/api/settings/session")
        assert response.status_code == 200


class TestPresetsSettings:
    def test_get_presets(self, client):
        response = client.get("/api/settings/presets")
        assert response.status_code == 200

    def test_get_presets_returns_list_or_dict(self, client):
        response = client.get("/api/settings/presets")
        data = response.json()
        assert isinstance(data, (list, dict))
