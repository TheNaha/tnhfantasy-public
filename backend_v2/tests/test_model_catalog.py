from fastapi.testclient import TestClient

from modal_llm.registry import load
from services.llm_config import get_active_models, set_active_models
from services.llm_router import refresh_router


class TestModelCatalogAndRegistry:
    def test_registry_catalog_serialization(self):
        reg = load()
        cat = reg.catalog()
        assert "artemis_31b" in cat
        artemis = cat["artemis_31b"]
        assert artemis["role"] == "rp"
        assert "download_url" in artemis
        assert "huggingface.co" in artemis["download_url"]
        assert artemis["gguf"] == "TheDrummer_Artemis-31B-v1.2-Q5_K_M.gguf"

    def test_distinct_primaries(self):
        reg = load()
        distinct = reg.distinct_primaries()
        assert len(distinct) >= 1
        assert any(d.id == reg.primary("rp").id for d in distinct)

    def test_active_models_storage_and_router_resolution(self, tmp_path, monkeypatch):
        fake_cfg = tmp_path / "llm_config.json"
        monkeypatch.setattr("services.llm_config._CONFIG_PATH", str(fake_cfg))
        refresh_router()

        # Defaults initially
        active = get_active_models()
        assert active["rp"] == "artemis_31b"

        # Update active models
        updated = set_active_models(active_rp="writers_31b_v2", active_util="artemis_31b")
        assert updated["rp"] == "writers_31b_v2"
        assert updated["util"] == "artemis_31b"

        router = refresh_router()
        desc = router.describe()
        assert desc["active"]["rp"] == "writers_31b_v2"
        assert desc["active"]["util"] == "artemis_31b"
        assert desc["shared_weights"] is False

        # When rp and util are the same
        set_active_models(active_rp="artemis_31b", active_util="artemis_31b")
        router = refresh_router()
        desc = router.describe()
        assert desc["shared_weights"] is True

    def test_catalog_api_endpoint(self, client: TestClient):
        resp = client.get("/api/v2/models/catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert "catalog" in data
        assert "roles" in data
        assert "active" in data
        assert "shared_weights" in data
        assert "artemis_31b" in data["catalog"]

    def test_set_active_models_endpoint(self, client: TestClient, tmp_path, monkeypatch):
        fake_cfg = tmp_path / "llm_config.json"
        monkeypatch.setattr("services.llm_config._CONFIG_PATH", str(fake_cfg))
        refresh_router()

        resp = client.put(
            "/api/v2/world-vault/llm/catalog/active",
            json={"active_rp": "writers_31b_v2", "active_util": "writers_31b_v2"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["active"]["rp"] == "writers_31b_v2"

        # Verify invalid model rejected with 422 / 400
        bad_resp = client.put(
            "/api/v2/world-vault/llm/catalog/active",
            json={"active_rp": "non_existent_model_xyz"},
        )
        assert bad_resp.status_code in (400, 422)
