"""The dead API surface removed on 2026-10-21.

Nine routes, two of them duplicated whole features, all with zero callers:

    GET  /api/v2/models/                     four implementations of the same
    GET  /api/v2/models/all                  1.53 MB model dump, byte-identical
    GET  /api/v2/providers/model-cache       between two of them
    GET  /api/v2/providers/model-cache/{dir}
    GET  /api/v2/providers/status-cards
    GET  /api/v2/providers/{id}/status-card
    GET  /api/v2/providers/load-balancer/stats   aliases of the canonical
    GET  /api/v2/providers/load-balancing        `/config/load-balancing` pair
    PUT  /api/v2/providers/load-balancing
    GET  /api/v2/gallery                     a second URL for `GET /api/files`
    GET  /api/workers/connected
    GET  /api/workers/{provider_id}/status
    POST /api/v2/voices/speak                duplicates
                                              `POST /api/v2/voices/{id}/preview`

Every test here asserts the route is GONE. Restoring any one of them makes
the matching test fail, because the route answers again.

The last class is the other half of the contract: the routes that replaced
the deleted ones still work. A removal that broke its replacement would
satisfy every assertion above and still be a regression.
"""

import pytest

GONE = (404, 405)


class TestModelListingDumpIsGone:
    """Four routes, one payload, no callers."""

    def test_get_models_collection_is_gone(self, client):
        # The POST on the same path stays — it is the CivitAI import the
        # model manager uses.
        assert client.get("/api/v2/models/").status_code in GONE

    def test_get_models_all_is_gone(self, client):
        assert client.get("/api/v2/models/all").status_code in GONE

    def test_get_provider_model_cache_is_gone(self, client):
        assert client.get("/api/v2/providers/model-cache").status_code in GONE

    def test_get_provider_model_cache_by_directory_is_gone(self, client):
        assert client.get("/api/v2/providers/model-cache/checkpoints").status_code in GONE

    def test_the_model_import_post_still_works(self, client, sample_model_v2_data):
        response = client.post("/api/v2/models", json=sample_model_v2_data)
        assert response.status_code == 200
        assert response.json()["name"] == "Test Model V2"


class TestProviderStatusCardsAreGone:
    """The frontend reads `GET /api/v2/providers/`, not these."""

    def test_status_cards_collection_is_gone(self, client):
        assert client.get("/api/v2/providers/status-cards").status_code in GONE

    def test_status_card_for_one_provider_is_gone(self, client):
        assert client.get("/api/v2/providers/some-provider/status-card").status_code in GONE

    def test_the_provider_record_still_carries_the_payload(self, client, sample_provider_data):
        created = client.post("/api/v2/providers", json=sample_provider_data)
        assert created.status_code == 200

        record = client.get(f"/api/v2/providers/{sample_provider_data['id']}")
        assert record.status_code == 200
        body = record.json()
        # The same sections the status card used to serve.
        for section in ("model_sync", "storage", "diagnostics", "reconciliation_state"):
            assert section in body


class TestLoadBalancerAliasesAreGone:
    """`/config/load-balancing` is canonical; the other three were aliases."""

    def test_load_balancer_stats_alias_is_gone(self, client):
        assert client.get("/api/v2/providers/load-balancer/stats").status_code in GONE

    def test_load_balancing_get_alias_is_gone(self, client):
        assert client.get("/api/v2/providers/load-balancing").status_code in GONE

    def test_load_balancing_put_alias_is_gone(self, client):
        response = client.put("/api/v2/providers/load-balancing", json={"strategy": "priority"})
        assert response.status_code in GONE

    def test_the_canonical_pair_still_works(self, client):
        assert client.get("/api/v2/providers/config/load-balancing").status_code == 200

        updated = client.put(
            "/api/v2/providers/config/load-balancing",
            json={"strategy": "round-robin", "fallback_enabled": True},
        )
        assert updated.status_code == 200
        assert updated.json()["fallback_enabled"] is True


class TestGalleryAliasIsGone:
    """`GET /api/v2/gallery` was a second URL for `GET /api/files`."""

    def test_v2_gallery_is_gone(self, client):
        assert client.get("/api/v2/gallery").status_code in GONE

    def test_the_gallery_listing_still_works(self, client):
        assert client.get("/api/files").status_code == 200


class TestWorkerStatusRoutesAreGone:
    def test_connected_workers_is_gone(self, client):
        assert client.get("/api/workers/connected").status_code in GONE

    def test_worker_status_is_gone(self, client):
        assert client.get("/api/workers/some-provider/status").status_code in GONE


class TestVoiceSpeakDuplicateIsGone:
    def test_speak_is_gone(self, client):
        response = client.post("/api/v2/voices/speak", json={"text": "hello"})
        assert response.status_code in GONE

    def test_the_voice_preview_route_still_exists(self, client):
        spec = client.app.openapi()
        assert "/api/v2/voices/{voice_id}/preview" in spec["paths"]
        assert "post" in spec["paths"]["/api/v2/voices/{voice_id}/preview"]


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v2/models/all"),
        ("get", "/api/v2/models/"),
        ("get", "/api/v2/providers/model-cache"),
        ("get", "/api/v2/providers/model-cache/checkpoints"),
        ("get", "/api/v2/providers/status-cards"),
        ("get", "/api/v2/providers/p/status-card"),
        ("get", "/api/v2/providers/load-balancer/stats"),
        ("get", "/api/v2/providers/load-balancing"),
        ("put", "/api/v2/providers/load-balancing"),
        ("get", "/api/v2/gallery"),
        ("get", "/api/workers/connected"),
        ("get", "/api/workers/p/status"),
        ("post", "/api/v2/voices/speak"),
    ],
)
def test_none_of_them_are_in_the_openapi_document(client, method, path):
    """The spec is the second surface: a route that is gone from the app but
    still in the document is a route the next generator writes back."""
    spec = client.app.openapi()
    if path in spec["paths"]:
        assert method not in spec["paths"][path], f"{method.upper()} {path} is still documented"
