"""Additional tests for api/routes/providers.py"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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
        response = client.post("/api/v2/providers", json=sample_provider_payload)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_provider_payload["id"]

    def test_list_providers_empty(self, client):
        response = client.get("/api/v2/providers")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert data["providers"] == []

    def test_list_providers_after_create(self, client, sample_provider_payload):
        client.post("/api/v2/providers", json=sample_provider_payload)
        response = client.get("/api/v2/providers")
        assert response.status_code == 200
        payload = response.json()
        assert len(payload["providers"]) >= 1

    def test_get_provider_by_id(self, client, sample_provider_payload):
        client.post("/api/v2/providers", json=sample_provider_payload)
        response = client.get(f"/api/v2/providers/{sample_provider_payload['id']}")
        assert response.status_code == 200
        assert response.json()["id"] == sample_provider_payload["id"]

    def test_get_nonexistent_provider(self, client):
        response = client.get("/api/v2/providers/nonexistent-provider")
        assert response.status_code == 404


class TestProvidersRouteUpdate:
    def test_update_provider(self, client, sample_provider_payload):
        client.post("/api/v2/providers", json=sample_provider_payload)
        response = client.put(
            f"/api/v2/providers/{sample_provider_payload['id']}",
            json={"enabled": False}
        )
        assert response.status_code == 200

    def test_patch_provider(self, client, sample_provider_payload):
        client.post("/api/v2/providers", json=sample_provider_payload)
        response = client.patch(
            f"/api/v2/providers/{sample_provider_payload['id']}",
            json={"priority": 5}
        )
        assert response.status_code in (200, 405)

    def test_delete_provider(self, client, sample_provider_payload):
        client.post("/api/v2/providers", json=sample_provider_payload)
        response = client.delete(f"/api/v2/providers/{sample_provider_payload['id']}")
        assert response.status_code == 200


class TestProvidersRouteModelCache:
    def test_get_model_cache_empty(self, client):
        response = client.get("/api/v2/providers/model-cache")
        assert response.status_code == 200

    def test_get_model_cache_by_directory(self, client):
        response = client.get("/api/v2/providers/model-cache/checkpoints")
        assert response.status_code == 200


class TestProvidersRouteLoadBalancing:
    def test_get_load_balancing_config(self, client):
        response = client.get("/api/v2/providers/config/load-balancing")
        assert response.status_code == 200

    def test_update_load_balancing_config(self, client):
        response = client.put(
            "/api/v2/providers/config/load-balancing",
            json={"strategy": "round-robin"}
        )
        assert response.status_code in (200, 422)

    def test_get_load_balancing_legacy(self, client):
        response = client.get("/api/v2/providers/load-balancing")
        assert response.status_code == 200

    def test_put_load_balancing_legacy(self, client):
        response = client.put(
            "/api/v2/providers/load-balancing",
            json={"strategy": "least-loaded"}
        )
        assert response.status_code in (200, 422)

    def test_get_load_balancer_stats(self, client):
        response = client.get("/api/v2/providers/load-balancer/stats")
        assert response.status_code == 200


class TestProvidersRouteContainers:
    def test_list_containers_no_manager(self, client):
        # Container worker layer removed: the endpoint is gone.
        response = client.get("/api/v2/providers/containers/list")
        assert response.status_code == 404

    def test_container_status_no_manager(self, client):
        response = client.get("/api/v2/providers/containers/status")
        assert response.status_code == 404


class TestProvidersRouteWake:
    def test_wake_no_providers(self, client):
        # Container wake removed: POST /wake is not a route (405 from /{id} POST).
        response = client.post("/api/v2/providers/wake")
        assert response.status_code in (404, 405)


class TestProvidersRouteCleanup:
    def test_cleanup_orphaned_statuses(self, client):
        response = client.post("/api/v2/providers/cleanup-orphaned-statuses")
        assert response.status_code in (200, 422)

    def test_cleanup_provider_state_alias(self, client):
        response = client.post("/api/v2/providers/state/cleanup")
        assert response.status_code in (200, 422)


class TestProvidersRouteReconcile:
    @pytest.fixture(autouse=True)
    def setup_provider(self, client):
        client.post("/api/v2/providers", json={"id": "test-provider", "type": "beam", "label": "Test", "credentials": {"api_key": "test-key"}, "config": {"gpu_url": "https://gpu.example.com", "storage_url": "https://storage.example.com"}})

    def test_reconcile_provider_not_found(self, client):
        response = client.post("/api/v2/providers/nonexistent/reconcile")
        assert response.status_code in (404, 500, 200)

    def test_reconciliation_status_not_found(self, client):
        response = client.get("/api/v2/providers/nonexistent/reconciliation-status")
        assert response.status_code in (404, 200)

    def test_reconciliation_event_not_found(self, client):
        response = client.post(
            "/api/v2/providers/nonexistent/reconciliation-event",
            json={"event_type": "test"}
        )
        assert response.status_code in (404, 200, 422)

    def test_reconcile_provider_conflict_when_already_running(self, client):
        client.post("/api/v2/providers", json={"id": "test-provider", "type": "beam", "label": "Test", "credentials": {"api_key": "test-key"}, "config": {"gpu_url": "https://gpu.example.com", "storage_url": "https://storage.example.com"}})
        
        from api.deps import get_provider_lifecycle_service
        from api.main import app
        
        lifecycle = MagicMock()
        lifecycle.trigger_reconciliation = AsyncMock(
            return_value={
                "status": "already_running",
                "provider_id": "test-provider",
                "message": "Reconciliation already in progress for this provider",
            }
        )
        app.dependency_overrides[get_provider_lifecycle_service] = lambda: lifecycle

        try:
            response = client.post("/api/v2/providers/test-provider/reconcile")
        finally:
            del app.dependency_overrides[get_provider_lifecycle_service]

        assert response.status_code == 400

    def test_reconciliation_event_persists_backend_state(self, client):
        mock_service = MagicMock()
        # Plain MagicMock, not AsyncMock: the route calls this through
        # `asyncio.to_thread` (it is a synchronous DB merge behind a decorative
        # `async def`), so it is invoked synchronously in a worker thread.
        mock_service.upsert_reconciliation_state = MagicMock(
            return_value={"provider_id": "test-provider", "status": "reconciling"}
        )

        with patch("api.routes.providers.reconciliation.get_provider_service", return_value=mock_service):
            response = client.post(
                "/api/v2/providers/test-provider/reconciliation-event",
                json={"status": "reconciling", "phase": "downloading", "stats": {}},
            )

        assert response.status_code == 200
        data = response.json()
        assert "reconciliation_state" in data
        assert data["reconciliation_state"]["status"] == "reconciling"

    def test_reconciliation_event_emits_provider_stats_update(self, client):
        mock_service = MagicMock()
        # Plain MagicMock, not AsyncMock: the route calls this through
        # `asyncio.to_thread` (it is a synchronous DB merge behind a decorative
        # `async def`), so it is invoked synchronously in a worker thread.
        mock_service.upsert_reconciliation_state = MagicMock(
            return_value={"provider_id": "test-provider", "status": "reconciling"}
        )

        with patch("api.routes.providers.reconciliation.get_provider_service", return_value=mock_service), \
             patch("api.routes.providers.reconciliation.emit_provider_stats", new=AsyncMock()) as emit_stats:
            response = client.post(
                "/api/v2/providers/test-provider/reconciliation-event",
                json={
                    "status": "reconciling",
                    "phase": "downloading",
                    "stats": {"total_models_in_storage": 9},
                },
            )

        assert response.status_code == 200
        emit_stats.assert_awaited_once_with("test-provider", {"total_models_in_storage": 9})

    def test_reconciliation_event_without_stats_does_not_send_stats_overwrite(self, client):
        from api.deps import get_provider_service
        from api.main import app
        mock_service = MagicMock()
        # Plain MagicMock, not AsyncMock: the route calls this through
        # `asyncio.to_thread` (it is a synchronous DB merge behind a decorative
        # `async def`), so it is invoked synchronously in a worker thread.
        mock_service.upsert_reconciliation_state = MagicMock(
            return_value={"provider_id": "test-provider", "status": "reconciling"}
        )

        app.dependency_overrides[get_provider_service] = lambda session=None: mock_service
        try:
            response = client.post(
                "/api/v2/providers/test-provider/reconciliation-event",
                json={
                    "status": "reconciling",
                    "phase": "validating",
                },
            )
        finally:
            del app.dependency_overrides[get_provider_service]

        assert response.status_code == 200
        upsert_args = mock_service.upsert_reconciliation_state.call_args.args
        assert upsert_args[0] == "test-provider"
        assert "stats" not in upsert_args[1]

    def test_reconciliation_event_without_stats_preserves_status_card_storage_totals(self, client):
        provider_id = "status-card-reconciliation-preserve"
        payload = {
            "id": provider_id,
            "type": "modal",
            "enabled": True,
            "priority": 1,
            "credentials": {"token_id": "tok_123", "token_secret": "secret_456"},
            "config": {},
        }
        create_response = client.post("/api/v2/providers", json=payload)
        assert create_response.status_code == 200

        first_event = client.post(
            f"/api/v2/providers/{provider_id}/reconciliation-event",
            json={
                "status": "reconciling",
                "phase": "downloading",
                "stats": {
                    "total_models_in_storage": 6,
                    "by_directory": {"checkpoints": 6},
                },
            },
        )
        assert first_event.status_code == 200

        first_card = client.get(f"/api/v2/providers/{provider_id}/status-card")
        assert first_card.status_code == 200
        assert first_card.json()["storage"]["total"] == 6

        second_event = client.post(
            f"/api/v2/providers/{provider_id}/reconciliation-event",
            json={
                "status": "reconciling",
                "phase": "validating",
            },
        )
        assert second_event.status_code == 200

        second_card = client.get(f"/api/v2/providers/{provider_id}/status-card")
        assert second_card.status_code == 200
        assert second_card.json()["storage"]["total"] == 6

    def test_deploy_provider_not_found(self, client):
        response = client.post("/api/v2/providers/nonexistent/deploy")
        assert response.status_code == 404

    def test_deploy_returns_conflict_when_already_running(self, client, monkeypatch):
        # Deploy route removed with the container worker layer.
        response = client.post("/api/v2/providers/test-provider/deploy")

        assert response.status_code == 404

    def test_get_provider_deploy_status_route(self, client):
        # Deploy-status route removed with the container worker layer.
        response = client.get("/api/v2/providers/deploy-status-provider/deploy-status")
        assert response.status_code == 404

    def test_get_provider_status_card_route(self, client):
        payload = {
            "id": "status-card-provider",
            "type": "modal",
            "enabled": True,
            "priority": 1,
            "credentials": {"token_id": "tok_123", "token_secret": "secret_456"},
            "config": {},
        }
        create_response = client.post("/api/v2/providers", json=payload)
        assert create_response.status_code == 200

        sync_payload = {
            "provider": "status-card-provider",
            "total_models": 3,
            "stats": {
                "installed": 2,
                "pending": 1,
                "downloading": 0,
                "failed": 0,
            },
            "models": [],
        }
        storage_payload = {
            "provider_id": "status-card-provider",
            "total": 2,
            "by_directory": {"checkpoints": 1, "loras": 1},
        }

        with patch(
            "services.provider_status_service.ProviderStatusService.get_provider_sync_stats",
            new=AsyncMock(return_value=sync_payload),
        ), \
             patch(
                 "services.provider_status_service.ProviderStatusService.get_provider_storage_stats",
                 new=AsyncMock(return_value=storage_payload),
             ):
            response = client.get("/api/v2/providers/status-card-provider/status-card")

        assert response.status_code == 200
        data = response.json()
        assert data["provider_id"] == "status-card-provider"
        assert data["model_sync"]["total_models"] == 3
        assert data["model_sync"]["total_models"] == 3
        assert data["storage"]["total"] == 2
        assert data["reconciliation"]["status"] in {"idle", "reconciling", "completed", "failed"}
        assert "diagnostics" in data

    def test_get_provider_status_cards_batch_route(self, client):
        provider_ids = ["status-cards-a", "status-cards-b"]
        for provider_id in provider_ids:
            payload = {
                "id": provider_id,
                "type": "modal",
                "enabled": True,
                "priority": 1,
                "credentials": {"token_id": "tok_123", "token_secret": "secret_456"},
                "config": {},
            }
            create_response = client.post("/api/v2/providers", json=payload)
            assert create_response.status_code == 200

        sync_payload = {
            "provider": "ignored",
            "total_models": 1,
            "stats": {
                "installed": 1,
                "pending": 0,
                "downloading": 0,
                "failed": 0,
            },
            "models": [],
        }
        storage_payload = {
            "provider_id": "ignored",
            "total": 1,
            "by_directory": {"checkpoints": 1},
        }

        with patch(
            "services.provider_status_service.ProviderStatusService.get_provider_sync_stats",
            new=AsyncMock(return_value=sync_payload),
        ), \
             patch(
                 "services.provider_status_service.ProviderStatusService.get_provider_storage_stats",
                 new=AsyncMock(return_value=storage_payload),
             ):
            response = client.get("/api/v2/providers/status-cards")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= len(provider_ids)
        for provider_id in provider_ids:
            assert provider_id in data["status_cards"]
        for provider_id in provider_ids:
            card = data["status_cards"][provider_id]
            assert card["provider_id"] == provider_id
            assert "model_sync" in card
            assert "storage" in card
            assert "diagnostics" in card

    def test_setup_provider_not_found(self, client):
        response = client.post(
            "/api/v2/providers/nonexistent/setup",
            json={"step": "init"}
        )
        assert response.status_code in (404, 500, 200, 422)


class TestProviderSchemasAndTestBench:
    def test_get_schemas_endpoint(self, client):
        response = client.get("/api/v2/providers/schemas")
        assert response.status_code == 200
        data = response.json()
        assert "engines" in data
        assert "categories" in data
        assert "modal" in data["engines"]
        assert "beam" in data["engines"]
        assert "direct_url" in data["engines"]
        assert "openai_compat" in data["engines"]
        assert "anthropic" in data["engines"]
        assert "google" in data["engines"]
        assert "modal_tts" in data["engines"]

        modal_schema = data["engines"]["modal"]
        assert modal_schema["category"] == "image"
        assert any(f["key"] == "token_id" for f in modal_schema["credentials"])
        assert any(f["key"] == "token_secret" for f in modal_schema["credentials"])

    def test_test_connection_missing_credentials(self, client):
        response = client.post(
            "/api/v2/providers/test-connection",
            json={"type": "modal", "credentials": {}, "config": {}}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["healthy"] is False
        assert "missing" in data["error"].lower()

    def test_test_connection_healthy_mock(self, client):
        with patch("services.engines.direct_comfy_engine.DirectComfyEngine.check_health", new=AsyncMock(return_value={"status": "healthy", "ready": True, "latency_ms": 12.5})):
            response = client.post(
                "/api/v2/providers/test-connection",
                json={
                    "type": "direct_url",
                    "credentials": {},
                    "config": {"comfy_url": "http://127.0.0.1:8188"}
                }
            )
            assert response.status_code == 200
            data = response.json()
            assert data["healthy"] is True
            assert data["status"] == "healthy"
            assert data["latency_ms"] == 12.5

    def test_discovered_models_endpoint(self, client):
        client.post("/api/v2/providers", json={"id": "test-direct-disc", "type": "direct_url", "credentials": {}, "config": {"comfy_url": "http://127.0.0.1:8188"}})
        with patch("services.engines.direct_comfy_engine.DirectComfyEngine.list_models", new=AsyncMock(return_value=[{"name": "v1-5-pruned.safetensors", "id": "v1-5-pruned.safetensors"}])):
            response = client.get("/api/v2/providers/test-direct-disc/models/discovered")
            assert response.status_code == 200
            data = response.json()
            assert data["provider_id"] == "test-direct-disc"
            assert data["count"] == 1
            assert data["models"][0]["name"] == "v1-5-pruned.safetensors"

    def test_diagnostics_endpoint(self, client):
        client.post("/api/v2/providers", json={"id": "test-direct-diag", "type": "direct_url", "credentials": {}, "config": {"comfy_url": "http://127.0.0.1:8188"}})
        with patch("services.engines.direct_comfy_engine.DirectComfyEngine.check_health", new=AsyncMock(return_value={"status": "healthy", "ready": True, "latency_ms": 15.0})):
            response = client.get("/api/v2/providers/test-direct-diag/diagnostics")
            assert response.status_code == 200
            data = response.json()
            assert data["provider_id"] == "test-direct-diag"
            assert data["healthy"] is True
            assert data["engine_name"] == "DirectComfyEngine"
            assert data["runtime_mode"] == "in_process"
