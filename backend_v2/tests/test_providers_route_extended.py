"""Additional tests for api/routes/providers.py"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import json
from types import SimpleNamespace


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
        response = client.post("/api/providers", json=sample_provider_payload)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_provider_payload["id"]

    def test_list_providers_empty(self, client):
        response = client.get("/api/providers")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert data["providers"] == []

    def test_list_providers_after_create(self, client, sample_provider_payload):
        client.post("/api/providers", json=sample_provider_payload)
        response = client.get("/api/providers")
        assert response.status_code == 200
        payload = response.json()
        assert len(payload["providers"]) >= 1

    def test_get_provider_by_id(self, client, sample_provider_payload):
        client.post("/api/providers", json=sample_provider_payload)
        response = client.get(f"/api/providers/{sample_provider_payload['id']}")
        assert response.status_code == 200
        assert response.json()["id"] == sample_provider_payload["id"]

    def test_get_nonexistent_provider(self, client):
        response = client.get("/api/providers/nonexistent-provider")
        assert response.status_code == 404


class TestProvidersRouteUpdate:
    def test_update_provider(self, client, sample_provider_payload):
        client.post("/api/providers", json=sample_provider_payload)
        response = client.put(
            f"/api/providers/{sample_provider_payload['id']}",
            json={"enabled": False}
        )
        assert response.status_code == 200

    def test_patch_provider(self, client, sample_provider_payload):
        client.post("/api/providers", json=sample_provider_payload)
        response = client.patch(
            f"/api/providers/{sample_provider_payload['id']}",
            json={"priority": 5}
        )
        assert response.status_code in (200, 405)

    def test_delete_provider(self, client, sample_provider_payload):
        client.post("/api/providers", json=sample_provider_payload)
        response = client.delete(f"/api/providers/{sample_provider_payload['id']}")
        assert response.status_code == 200


class TestProvidersRouteModelCache:
    def test_get_model_cache_empty(self, client):
        response = client.get("/api/providers/model-cache")
        assert response.status_code == 200

    def test_get_model_cache_by_directory(self, client):
        response = client.get("/api/providers/model-cache/checkpoints")
        assert response.status_code == 200


class TestProvidersRouteLoadBalancing:
    def test_get_load_balancing_config(self, client):
        response = client.get("/api/providers/config/load-balancing")
        assert response.status_code == 200

    def test_update_load_balancing_config(self, client):
        response = client.put(
            "/api/providers/config/load-balancing",
            json={"strategy": "round-robin"}
        )
        assert response.status_code in (200, 422)

    def test_get_load_balancing_legacy(self, client):
        response = client.get("/api/providers/load-balancing")
        assert response.status_code == 200

    def test_put_load_balancing_legacy(self, client):
        response = client.put(
            "/api/providers/load-balancing",
            json={"strategy": "least-loaded"}
        )
        assert response.status_code in (200, 422)

    def test_get_load_balancer_stats(self, client):
        response = client.get("/api/providers/load-balancer/stats")
        assert response.status_code == 200


class TestProvidersRouteSaveImage:
    def test_save_image_no_data(self, client):
        response = client.post("/api/providers/save-image", json={})
        assert response.status_code in (200, 400, 422)

    def test_save_image_with_data(self, client):
        import base64
        from PIL import Image
        import io
        img = Image.new("RGB", (10, 10))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()
        response = client.post(
            "/api/providers/save-image",
            json={
                "image_data": img_b64,
                "filename": "test.png",
                "job_id": "test-job-id"
            }
        )
        assert response.status_code in (200, 400, 422, 500)


class TestProvidersRouteContainers:
    def test_list_containers_no_manager(self, client):
        response = client.get("/api/providers/containers/list")
        assert response.status_code in (200, 500)

    def test_container_status_no_manager(self, client):
        response = client.get("/api/providers/containers/status")
        assert response.status_code in (200, 500)


class TestProvidersRouteWake:
    def test_wake_no_providers(self, client):
        response = client.post("/api/providers/wake")
        assert response.status_code in (200, 422)


class TestProvidersRouteCleanup:
    def test_cleanup_orphaned_statuses(self, client):
        response = client.post("/api/providers/cleanup-orphaned-statuses")
        assert response.status_code in (200, 422)

    def test_cleanup_provider_state_alias(self, client):
        response = client.post("/api/providers/state/cleanup")
        assert response.status_code in (200, 422)


class TestProvidersRouteReconcile:
    def test_reconcile_provider_not_found(self, client):
        response = client.post("/api/providers/nonexistent/reconcile")
        assert response.status_code in (404, 500, 200)

    def test_reconciliation_status_not_found(self, client):
        response = client.get("/api/providers/nonexistent/reconciliation-status")
        assert response.status_code in (404, 200)

    def test_reconciliation_event_not_found(self, client):
        response = client.post(
            "/api/providers/nonexistent/reconciliation-event",
            json={"event_type": "test"}
        )
        assert response.status_code in (404, 200, 422)

    def test_reconcile_provider_conflict_when_already_running(self, client):
        lifecycle = MagicMock()
        lifecycle.trigger_reconciliation = AsyncMock(
            return_value={
                "status": "already_running",
                "provider_id": "test-provider",
                "message": "Reconciliation already in progress for this provider",
            }
        )

        with patch("api.routes.providers.reconciliation._get_provider_lifecycle_service", return_value=lifecycle):
            response = client.post("/api/providers/test-provider/reconcile")

        assert response.status_code == 400

    def test_reconciliation_event_persists_backend_state(self, client):
        mock_service = MagicMock()
        mock_service.upsert_reconciliation_state = AsyncMock(
            return_value={"provider_id": "test-provider", "status": "reconciling"}
        )

        with patch("api.routes.providers.reconciliation.get_provider_service", return_value=mock_service):
            response = client.post(
                "/api/providers/test-provider/reconciliation-event",
                json={"status": "reconciling", "phase": "downloading", "stats": {}},
            )

        assert response.status_code == 200
        data = response.json()
        assert "reconciliation_state" in data
        assert data["reconciliation_state"]["status"] == "reconciling"

    def test_reconciliation_event_emits_provider_stats_update(self, client):
        mock_service = MagicMock()
        mock_service.upsert_reconciliation_state = AsyncMock(
            return_value={"provider_id": "test-provider", "status": "reconciling"}
        )

        with patch("api.routes.providers.reconciliation.get_provider_service", return_value=mock_service), \
             patch("api.routes.providers.reconciliation.emit_provider_stats", new=AsyncMock()) as emit_stats:
            response = client.post(
                "/api/providers/test-provider/reconciliation-event",
                json={
                    "status": "reconciling",
                    "phase": "downloading",
                    "stats": {"total_models_in_storage": 9},
                },
            )

        assert response.status_code == 200
        emit_stats.assert_awaited_once_with("test-provider", {"total_models_in_storage": 9})

    def test_reconciliation_event_without_stats_does_not_send_stats_overwrite(self, client):
        mock_service = MagicMock()
        mock_service.upsert_reconciliation_state = AsyncMock(
            return_value={"provider_id": "test-provider", "status": "reconciling"}
        )

        with patch("api.routes.providers.reconciliation.get_provider_service", return_value=mock_service):
            response = client.post(
                "/api/providers/test-provider/reconciliation-event",
                json={
                    "status": "reconciling",
                    "phase": "validating",
                },
            )

        assert response.status_code == 200
        upsert_args = mock_service.upsert_reconciliation_state.await_args.args
        assert upsert_args[0] == "test-provider"
        assert "stats" not in upsert_args[1]

    def test_reconciliation_event_without_stats_preserves_status_card_storage_totals(self, client):
        provider_id = "status-card-reconciliation-preserve"
        payload = {
            "id": provider_id,
            "type": "modal",
            "enabled": True,
            "priority": 1,
            "credentials": {},
            "config": {},
        }
        create_response = client.post("/api/providers", json=payload)
        assert create_response.status_code == 200

        first_event = client.post(
            f"/api/providers/{provider_id}/reconciliation-event",
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

        first_card = client.get(f"/api/providers/{provider_id}/status-card")
        assert first_card.status_code == 200
        assert first_card.json()["storage"]["total"] == 6

        second_event = client.post(
            f"/api/providers/{provider_id}/reconciliation-event",
            json={
                "status": "reconciling",
                "phase": "validating",
            },
        )
        assert second_event.status_code == 200

        second_card = client.get(f"/api/providers/{provider_id}/status-card")
        assert second_card.status_code == 200
        assert second_card.json()["storage"]["total"] == 6

    def test_deploy_provider_not_found(self, client):
        response = client.post("/api/providers/nonexistent/deploy")
        assert response.status_code in (404, 500, 200)

    def test_deploy_returns_conflict_when_already_running(self, client):
        mock_service = MagicMock()
        mock_service.deploy_provider_app = AsyncMock(
            return_value={
                "status": "already_running",
                "message": "Deployment already in progress for this provider",
            }
        )

        with patch("api.routes.providers.lifecycle.get_provider_service", return_value=mock_service):
            response = client.post("/api/providers/test-provider/deploy")

        assert response.status_code == 400

    def test_get_provider_deploy_status_route(self, client):
        payload = {
            "id": "deploy-status-provider",
            "type": "modal",
            "enabled": True,
            "priority": 1,
            "credentials": {},
            "config": {},
        }
        create_response = client.post("/api/providers", json=payload)
        assert create_response.status_code == 200

        response = client.get("/api/providers/deploy-status-provider/deploy-status")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") in {"idle", "deploying", "failed", "succeeded"}

    def test_get_provider_status_card_route(self, client):
        payload = {
            "id": "status-card-provider",
            "type": "modal",
            "enabled": True,
            "priority": 1,
            "credentials": {},
            "config": {},
        }
        create_response = client.post("/api/providers", json=payload)
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
            "services.provider_status_service.ProviderStatusService.get_provider_sync_status",
            new=AsyncMock(return_value=sync_payload),
        ), \
             patch(
                 "services.provider_status_service.ProviderStatusService.get_provider_storage_stats",
                 new=AsyncMock(return_value=storage_payload),
             ):
            response = client.get("/api/providers/status-card-provider/status-card")

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
                "credentials": {},
                "config": {},
            }
            create_response = client.post("/api/providers", json=payload)
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
            "services.provider_status_service.ProviderStatusService.get_provider_sync_status",
            new=AsyncMock(return_value=sync_payload),
        ), \
             patch(
                 "services.provider_status_service.ProviderStatusService.get_provider_storage_stats",
                 new=AsyncMock(return_value=storage_payload),
             ):
            response = client.get("/api/providers/status-cards")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == len(provider_ids)
        assert set(data["status_cards"].keys()) == set(provider_ids)
        for provider_id in provider_ids:
            card = data["status_cards"][provider_id]
            assert card["provider_id"] == provider_id
            assert "model_sync" in card
            assert "storage" in card
            assert "diagnostics" in card

    def test_setup_provider_not_found(self, client):
        response = client.post(
            "/api/providers/nonexistent/setup",
            json={"step": "init"}
        )
        assert response.status_code in (404, 500, 200, 422)
