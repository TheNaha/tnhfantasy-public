"""Tests for POST /api/v2/providers/{id}/shutdown."""
from unittest.mock import AsyncMock, MagicMock, patch


class TestProviderShutdown:
    def test_shutdown_nonexistent_provider(self, client):
        response = client.post("/api/v2/providers/nonexistent/shutdown")
        assert response.status_code == 404

    def test_shutdown_direct_url_unsupported(self, client):
        client.post(
            "/api/v2/providers",
            json={
                "id": "test-direct-shutdown",
                "type": "direct_url",
                "credentials": {},
                "config": {"comfy_url": "http://127.0.0.1:8188"},
            },
        )
        response = client.post("/api/v2/providers/test-direct-shutdown/shutdown")
        assert response.status_code == 400
        data = response.json()
        assert "not supported" in data["error"].lower()

    def test_shutdown_modal_invalidates_cache(self, client):
        client.post(
            "/api/v2/providers",
            json={
                "id": "test-modal-shutdown",
                "type": "modal",
                "credentials": {"token_id": "tok", "token_secret": "secret"},
                "config": {"app_name": "test-app"},
            },
        )
        # Modal has no runtime scaledown API, so shutdown invalidates the
        # engine cache and returns success without calling out to Modal.
        response = client.post("/api/v2/providers/test-modal-shutdown/shutdown")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "shutting_down"
        assert data["transport"] == "modal"

    def test_shutdown_remote_calls_sidecar(self, client):
        client.post(
            "/api/v2/providers",
            json={
                "id": "test-remote-shutdown",
                "type": "remote_comfy",
                "credentials": {
                    "remote_agent_token": "agent-token",
                },
                "config": {
                    "comfy_url": "http://remote-server:8188",
                    "remote_agent_url": "http://remote-server:8001",
                },
            },
        )

        # Mock httpx.AsyncClient.post to avoid real network calls.
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "shutting_down",
            "llama_servers_stopped": 1,
        }

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch(
            "httpx.AsyncClient", return_value=mock_client
        ), patch(
            "services.engines.engine_factory.can_create_engine", return_value=True
        ), patch(
            "services.engines.engine_factory.get_engine"
        ) as mock_get_engine:
            mock_engine = MagicMock()
            mock_engine.agent_url = "http://remote-server:8001"
            mock_engine.agent_token = "agent-token"
            mock_get_engine.return_value = mock_engine

            response = client.post("/api/v2/providers/test-remote-shutdown/shutdown")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "shutting_down"
            assert data["transport"] == "remote"
            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert "/shutdown" in str(call_args)

    def test_shutdown_with_active_jobs_rejected(self, client):
        with patch(
            "api.routes.providers.lifecycle.SHUTDOWN_MAX_WAIT_SECONDS", 2
        ), patch(
            "api.routes.providers.lifecycle.SHUTDOWN_POLL_INTERVAL_SECONDS", 1
        ):
            client.post(
                "/api/v2/providers",
                json={
                    "id": "test-modal-jobs",
                    "type": "modal",
                    "credentials": {"token_id": "tok", "token_secret": "secret"},
                    "config": {"app_name": "test-app"},
                },
            )

            # Insert an active job for this provider
            from infrastructure.deps import get_session_sync
            from core.entities import Job, JobStatus

            session = get_session_sync()
            try:
                job = Job(
                    task_type="image",
                    status=JobStatus.GENERATING,
                    provider_id="test-modal-jobs",
                    workflow={},
                )
                session.add(job)
                session.commit()
            finally:
                session.close()

            response = client.post("/api/v2/providers/test-modal-jobs/shutdown")
            assert response.status_code == 400
            data = response.json()
            assert "active" in data["error"].lower() or "job" in data["error"].lower()
