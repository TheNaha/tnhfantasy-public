"""The `retryable` flag must not tell the dispatcher to re-dispatch to a second
provider for a fault that cannot fix itself.

`provider_core/router.py` used to compute `retryable = exc.status_code >= 500`
for every error body. That made the 503 a provider answers when
COMFY_PROVIDER_TOKEN is unset look retryable, and the backend reads exactly
that field: `services/provider_client.py` does

    is_retryable = response.status_code >= 500
    if "retryable" in p: is_retryable = bool(p["retryable"])

then raises ProviderCallError(is_retryable=...), which fails the job over to
another provider. So a permanently misconfigured provider cost a second paid
dispatch, and the failure was recorded against the first provider.

These tests pin the classification at both layers: the pure helper, and the
router's error body as the backend's HTTP client sees it.
"""
from unittest.mock import MagicMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from provider_core.responses import config_fault_detail, retryable_for_status
from provider_core.router import attach_provider_routes

TOKEN = "retryability-test-token"


class TestRetryableForStatus:
    def test_4xx_is_never_retryable(self):
        for code in (400, 401, 403, 404, 409, 422):
            assert retryable_for_status(code) is False

    def test_transient_5xx_stays_retryable(self):
        """An unreachable upstream really is transient — do not over-correct."""
        for code in (500, 502, 503, 504):
            assert retryable_for_status(code) is True

    def test_config_fault_detail_forces_non_retryable(self):
        detail = config_fault_detail("COMFY_PROVIDER_TOKEN is not configured")
        assert detail["retryable"] is False
        assert detail["message"] == "COMFY_PROVIDER_TOKEN is not configured"
        assert retryable_for_status(503, detail) is False

    def test_config_fault_detail_carries_extra_keys(self):
        detail = config_fault_detail("nope", missing=["MODAL_APP_NAME"])
        assert detail["missing"] == ["MODAL_APP_NAME"]
        assert retryable_for_status(503, detail) is False

    def test_string_detail_ignores_the_marker(self):
        """A plain string detail cannot smuggle in a retryable flag."""
        assert retryable_for_status(503, "unhealthy") is True
        assert retryable_for_status(503, None) is True


def _app_with_health(status_code: int, detail):
    app = FastAPI()
    client = MagicMock()

    async def get_health():
        raise HTTPException(status_code=status_code, detail=detail)

    client.get_health = get_health
    attach_provider_routes(app, client)
    return TestClient(app, raise_server_exceptions=False)


class TestRouterRetryableBody:
    def test_unset_token_503_is_not_retryable(self, monkeypatch):
        """The efb2837 case: no COMFY_PROVIDER_TOKEN -> 503 on protected routes."""
        monkeypatch.delenv("COMFY_PROVIDER_TOKEN", raising=False)
        app = FastAPI()
        attach_provider_routes(app, MagicMock())
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/list-models")
        assert response.status_code == 503
        payload = response.json()
        assert payload["status"] == "error"
        assert payload["retryable"] is False, (
            "a 503 that will still be a 503 in an hour must not be advertised as "
            "retryable; the dispatcher would spend a second provider's money"
        )
        assert payload["code"] == 503

    def test_transient_503_is_still_retryable(self):
        client = _app_with_health(503, "ComfyUI server is unreachable")
        payload = client.get("/health").json()
        assert payload["retryable"] is True

    def test_config_fault_503_from_a_client_is_not_retryable(self):
        client = _app_with_health(503, config_fault_detail("missing keys", missing=["BEAM_API_KEY"]))
        payload = client.get("/health").json()
        assert payload["retryable"] is False
        assert "missing keys" in payload["message"]

    def test_inference_stream_carries_the_same_flag(self, monkeypatch):
        """The /inference NDJSON branch must classify identically."""
        monkeypatch.setenv("COMFY_PROVIDER_TOKEN", TOKEN)
        app = FastAPI()
        client = MagicMock()

        async def inference(_request):
            raise HTTPException(
                status_code=503, detail=config_fault_detail("provider is not configured")
            )

        client.inference = inference
        attach_provider_routes(app, client)
        http = TestClient(app, raise_server_exceptions=False)

        response = http.post(
            "/inference",
            json={"workflow": {"1": {}}},
            headers={"X-Provider-Token": TOKEN},
        )
        assert response.status_code == 503
        assert response.headers["content-type"].startswith("application/x-ndjson")
        import json

        payload = json.loads(response.text.strip())
        assert payload["status"] == "error"
        assert payload["retryable"] is False


class TestGeneralHandlerLogsTraceback:
    def test_unhandled_exception_logs_a_traceback(self, monkeypatch, caplog):
        """Without exc_info a crash in a handler leaves no traceback anywhere.

        That is how a `modal deploy` subprocess dying inside /deploy left no
        evidence at all.
        """
        import logging

        monkeypatch.setenv("COMFY_PROVIDER_TOKEN", TOKEN)
        app = FastAPI()
        client = MagicMock()

        def get_config():
            # /config is a sync route, so the failure has to come from a sync call.
            raise ValueError("kaboom")

        client.get_config = get_config
        attach_provider_routes(app, client)
        http = TestClient(app, raise_server_exceptions=False)

        with caplog.at_level(logging.ERROR):
            response = http.get("/config", headers={"X-Provider-Token": TOKEN})

        assert response.status_code == 500
        assert response.json()["retryable"] is True
        records = [r for r in caplog.records if "Unhandled exception" in r.getMessage()]
        assert records, "the generic handler logged nothing"
        assert records[0].exc_info is not None, "no traceback attached to the log record"
        assert "ValueError: kaboom" in caplog.text
