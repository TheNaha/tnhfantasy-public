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
        assert active["rp"] in ("artemis_31b_q4", "artemis_31b")

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

        # When util is explicitly "same_as_rp"
        set_active_models(active_rp="sompoa_26b_a4b", active_util="same_as_rp")
        router = refresh_router()
        desc = router.describe()
        assert desc["shared_weights"] is True
        assert desc["active"]["rp"] == "sompoa_26b_a4b"
        assert desc["active"]["util"] == "same_as_rp"
        # Kind routing: util kind resolves to active rp model
        assert router.primary_for_kind("memory_extraction").id == "sompoa_26b_a4b"
        assert router.primary_for_kind("chat_reply").id == "sompoa_26b_a4b"

    def test_catalog_api_endpoint(self, client: TestClient):
        resp = client.get("/api/v2/models/catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert "catalog" in data
        assert "roles" in data
        assert "active" in data
        assert "shared_weights" in data
        assert "tokens" in data
        assert "hf_token" in data["tokens"]
        assert "civitai_token" in data["tokens"]
        assert "artemis_31b" in data["catalog"]
        assert "sompoa_26b_a4b" in data["catalog"]
        assert len(data["roles"]["rp"]["chain"]) >= 10
        assert len(data["roles"]["util"]["chain"]) >= 6

    def test_set_active_models_endpoint(self, client: TestClient, tmp_path, monkeypatch):
        fake_cfg = tmp_path / "llm_config.json"
        monkeypatch.setattr("services.llm_config._CONFIG_PATH", str(fake_cfg))
        refresh_router()

        resp = client.put(
            "/api/v2/llm/catalog/active",
            json={"active_rp": "writers_31b_v2", "active_util": "writers_31b_v2"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["active"]["rp"] == "writers_31b_v2"

        # Verify same_as_rp is accepted
        same_resp = client.put(
            "/api/v2/llm/catalog/active",
            json={"active_rp": "sompoa_26b_a4b", "active_util": "same_as_rp"},
        )
        assert same_resp.status_code == 200
        same_data = same_resp.json()
        assert same_data["status"] == "success"
        assert same_data["active"]["util"] == "same_as_rp"

        # Catalog endpoints report shared_weights=True
        cat_resp = client.get("/api/v2/llm/catalog")
        assert cat_resp.status_code == 200
        cat_data = cat_resp.json()
        assert cat_data["shared_weights"] is True
        assert cat_data["active"]["util"] == "same_as_rp"

        # Verify invalid model rejected with 422 / 400
        bad_resp = client.put(
            "/api/v2/llm/catalog/active",
            json={"active_rp": "non_existent_model_xyz"},
        )
        assert bad_resp.status_code in (400, 422)

    def test_checkpoint_recommendations_empty_db(self, client: TestClient):
        resp = client.get("/api/v2/models/catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert "checkpoint_recommendations" in data
        rec = data["checkpoint_recommendations"]
        assert "top_checkpoint_7d" in rec
        assert "recent_checkpoints_30d" in rec

    def test_checkpoint_recommendations_with_assets(self, session, client: TestClient):
        from datetime import datetime, timezone
        from core.entities import Asset, AssetKind, ModelFile, ModelV2, ModelVersion
        from services.checkpoint_recommendations import get_checkpoint_recommendations

        # Create model in DB
        mv2 = ModelV2(
            name="Chenkin NoobAI",
            type="Checkpoint",
            directory="checkpoints",
            civitai_model_id=99999,
        )
        session.add(mv2)
        session.flush()

        ver = ModelVersion(
            model_id=mv2.id,
            name="v777",
            civitai_version_id=2786084,
            base_model="Illustrious",
        )
        session.add(ver)
        session.flush()

        mfile = ModelFile(
            version_id=ver.id,
            original_filename="chenkin.safetensors",
            storage_filename="_janku_trained_chenkin_noobai__v777_2786084.safetensors",
            download_url="https://civitai.com/api/download/models/2786084",
            size_kb=6773248.0,
        )
        session.add(mfile)

        # Create assets
        now = datetime.now(timezone.utc)
        for i in range(5):
            asset = Asset(
                filename=f"img_{i}.png",
                relative_path=f"chat/img_{i}.png",
                kind=AssetKind.IMAGE,
                checkpoint_name="_janku_trained_chenkin_noobai__v777_2786084.safetensors",
                created_at=now,
            )
            session.add(asset)

        # Create another asset with flux
        flux_asset = Asset(
            filename="flux_img.png",
            relative_path="chat/flux_img.png",
            kind=AssetKind.IMAGE,
            checkpoint_name="flux1-dev-fp8.safetensors",
            created_at=now,
        )
        session.add(flux_asset)
        session.commit()

        rec = get_checkpoint_recommendations(session)
        assert rec["top_checkpoint_7d"] is not None
        assert rec["top_checkpoint_7d"]["filename"] == "_janku_trained_chenkin_noobai__v777_2786084.safetensors"
        assert rec["top_checkpoint_7d"]["civitai_version_id"] == 2786084
        assert rec["top_checkpoint_7d"]["civitai_model_id"] == 99999
        assert rec["top_checkpoint_7d"]["base_model"] == "Illustrious"
        assert rec["top_checkpoint_7d"]["is_flux"] is False
        assert rec["top_checkpoint_7d"]["count"] == 5

        # Check recent_checkpoints_30d
        recent = rec["recent_checkpoints_30d"]
        assert len(recent) >= 2
        flux_entry = next((r for r in recent if "flux" in r["filename"].lower()), None)
        assert flux_entry is not None
        assert flux_entry["is_flux"] is True

