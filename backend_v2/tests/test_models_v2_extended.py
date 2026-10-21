"""Extended tests for api/routes/models_v2.py"""


class TestModelsV2Extended:
    """Extended tests for V2 models routes."""

    def test_list_all_models(self, client):
        """`GET /api/v2/models/all` returned a 1.5 MB dump of the whole model
        library to a caller that did not exist — four endpoints served the same
        payload and none had a frontend caller. It is gone; the scoped,
        paginated listing is what the UI reads."""
        response = client.get("/api/v2/models/all")
        assert response.status_code in (404, 405)

    def test_check_installed_not_found(self, client):
        response = client.get("/api/v2/models/check-installed/99999")
        assert response.status_code == 200
        data = response.json()
        assert data.get("model_installed") is False

    def test_check_installed_found(self, client, sample_model_v2_data):
        client.post("/api/v2/models", json=sample_model_v2_data)
        response = client.get("/api/v2/models/check-installed/12345")
        assert response.status_code == 200
        data = response.json()
        assert data.get("model_installed") is True

    def test_search_models_empty(self, client):
        response = client.get("/api/v2/models/search?q=nonexistent_xyz")
        assert response.status_code == 200
        assert response.json() == []

    def test_search_models_finds_match(self, client, sample_model_v2_data):
        client.post("/api/v2/models", json=sample_model_v2_data)
        response = client.get("/api/v2/models/search?q=Test+Model")
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_search_by_tag_empty(self, client):
        response = client.get("/api/v2/models/search/tag/nonexistent_tag")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_search_by_tag_found(self, client, sample_model_v2_data):
        client.post("/api/v2/models", json=sample_model_v2_data)
        response = client.get("/api/v2/models/search/tag/anime")
        assert response.status_code == 200

    def test_get_model_versions(self, client, sample_model_v2_data):
        create_resp = client.post("/api/v2/models", json=sample_model_v2_data)
        model_id = create_resp.json()["id"]
        response = client.get(f"/api/v2/models/{model_id}/versions")
        assert response.status_code == 200

    def test_list_models_by_directory(self, client, sample_model_v2_data):
        client.post("/api/v2/models", json=sample_model_v2_data)
        response = client.get("/api/v2/models/directory/checkpoints")
        assert response.status_code == 200

    def test_list_models_by_directory_empty(self, client):
        response = client.get("/api/v2/models/directory/nonexistent_dir")
        assert response.status_code == 200

    def test_get_model_cache(self, client):
        """`GET /cache` returned a 1.5 MB dump of the whole model library to a
        caller that did not exist — five endpoints served the same payload and
        none had a frontend caller. It is gone; the model list is what the UI
        reads, and it is scoped and paginated."""
        response = client.get("/api/v2/models/cache")
        assert response.status_code == 404

    def test_cleanup_orphans(self, client):
        response = client.post("/api/v2/models/maintenance/cleanup-orphans")
        assert response.status_code == 200

    def test_get_generation_info(self, client, sample_model_v2_data):
        create_resp = client.post("/api/v2/models", json=sample_model_v2_data)
        model_id = create_resp.json()["id"]
        response = client.get(f"/api/v2/models/{model_id}/generation-info")
        assert response.status_code in (200, 404)

    def test_model_resync(self, client, sample_model_v2_data):
        create_resp = client.post("/api/v2/models", json=sample_model_v2_data)
        model_id = create_resp.json()["id"]
        response = client.post(f"/api/v2/models/maintenance/{model_id}/resync")
        assert response.status_code in (200, 202, 500, 502)

    def test_set_default_version(self, client, sample_model_v2_data):
        create_resp = client.post("/api/v2/models", json=sample_model_v2_data)
        data = create_resp.json()
        model_id = data["id"]
        version_id = data["versions"][0]["id"]
        response = client.put(
            f"/api/v2/models/{model_id}/default-version",
            json={"version_id": version_id},
        )
        assert response.status_code == 200

    def test_batch_status_update_route_is_gone(self, client):
        """`POST /providers/batch-status-update` answered to a worker that no
        longer exists; `in_process_reconciliation` writes these statuses
        directly. It must stay deleted, or the two writers drift."""
        response = client.post(
            "/api/v2/models/providers/batch-status-update",
            json={"provider_id": "modal-primary", "updates": []},
        )
        assert response.status_code == 404

    def test_reset_provider_status(self, client):
        response = client.delete("/api/v2/models/providers/modal-primary/reset-status")
        assert response.status_code == 200


    def test_external_parse_civitai(self, client):
        response = client.post(
            "/api/v2/models/external/parse",
            json={"url": "https://civitai.com/models/12345"}
        )
        assert response.status_code in (200, 400, 422, 500, 502)

    def test_external_civitai_search(self, client):
        response = client.get("/api/v2/models/external/civitai?query=checkpoint")
        assert response.status_code in (200, 500, 502, 503)

    def test_external_hf_search(self, client):
        response = client.get("/api/v2/models/external/huggingface?query=diffusion")
        assert response.status_code in (200, 500, 502, 503)

    def test_delete_nonexistent_model(self, client):
        response = client.delete("/api/v2/models/99999")
        assert response.status_code == 404
