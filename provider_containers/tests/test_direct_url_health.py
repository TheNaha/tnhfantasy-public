"""`direct_url`'s `/health` used to lie.

`client.py:107-111` returned `{"status": "healthy", "ready": True}` without
touching the network, so the Dockerfile HEALTHCHECK and the compose healthcheck
both passed and `docker compose ps` reported the provider healthy while its
ComfyUI server was unreachable. The backend's own `/health` probes
(services/load_balancer.py:340, api/routes/providers/crud.py:303,
services/provider_deploy_service.py:527) counted it as a usable target, so paid
jobs were dispatched at a provider that could not run them.

The other engines must keep their "never probe" behaviour: VISION #4 forbids
pinging a serverless deployment from a health check because the probe costs
money.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from image_worker.engines.direct_url.client import (
    HEALTH_PROBE_TIMEOUT, DirectUrlProviderClient,
)


def _client(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    client = DirectUrlProviderClient(runtime_config={})
    client._http = MagicMock()
    client._http.aclose = AsyncMock()
    return client


class TestHealthProbesTheUpstream:
    @pytest.mark.asyncio
    async def test_healthy_when_comfy_answers(self, monkeypatch):
        client = _client(monkeypatch, COMFYUI_URL="http://comfy.lan:8188")
        response = MagicMock(status_code=200)
        client._http.get = AsyncMock(return_value=response)
        try:
            payload = await client.get_health()
        finally:
            await client.close()

        client._http.get.assert_awaited_once()
        args, kwargs = client._http.get.call_args
        assert args[0] == "/system_stats", (
            "/object_info is a multi-megabyte node graph; /system_stats is the "
            "small always-present liveness endpoint"
        )
        assert kwargs["timeout"] == HEALTH_PROBE_TIMEOUT
        assert payload["status"] == "healthy"
        assert payload["ready"] is True
        assert payload["comfy_reachable"] is True

    @pytest.mark.asyncio
    async def test_503_when_the_upstream_is_dead(self, monkeypatch):
        from fastapi import HTTPException

        client = _client(monkeypatch, COMFYUI_URL="http://comfy.lan:8188")
        client._http.get = AsyncMock(side_effect=__import__("httpx").ConnectError("refused"))
        try:
            with pytest.raises(HTTPException) as exc:
                await client.get_health()
        finally:
            await client.close()

        assert exc.value.status_code == 503
        assert "unreachable" in exc.value.detail["message"]
        assert exc.value.detail["ready"] is False
        assert "retryable" not in exc.value.detail, (
            "a dead ComfyUI is transient, so the router must keep classifying a "
            "plain 503 as retryable"
        )

    @pytest.mark.asyncio
    async def test_503_on_a_bad_status(self, monkeypatch):
        from fastapi import HTTPException

        client = _client(monkeypatch, COMFYUI_URL="http://comfy.lan:8188")
        response = MagicMock(status_code=500)
        response.raise_for_status.side_effect = RuntimeError("500 boom")
        client._http.get = AsyncMock(return_value=response)
        try:
            with pytest.raises(HTTPException) as exc:
                await client.get_health()
        finally:
            await client.close()
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_the_timeout_fits_the_dispatcher_budget(self, monkeypatch):
        """The budget that matters is the DISPATCHER's, not the healthcheck's.

        The compose and Dockerfile healthchecks now call `/live`, which does not
        touch the upstream, so their 10s window is not this number's problem. What
        constrains it is `backend_v2/services/load_balancer.py:345` and
        `api/routes/providers/crud.py:167`, which probe `/health` with
        `_HTTP_HEALTH_PROBE_TIMEOUT_SECONDS = 2.0` and require HTTP 200 — a probe
        slower than that reads as "no answer" and the provider is excluded from
        dispatch.

        The previous assertion was `< 8`, justified by the old 10s healthcheck
        budget. That justification is gone, and the assertion is tightened to the
        budget that actually applies.
        """
        client = _client(monkeypatch)
        try:
            assert 0 < HEALTH_PROBE_TIMEOUT < 2.0
        finally:
            await client.close()

    def test_health_does_not_leak_the_lan_url(self, monkeypatch):
        """`/health` must stay unauthenticated, so it must not carry the
        upstream address; `/info` is authenticated and still does."""
        import inspect

        source = inspect.getsource(DirectUrlProviderClient.get_health)
        assert "self.comfy_url" not in source
        assert "comfy_url" in inspect.getsource(DirectUrlProviderClient.get_info)


class TestServerlessEnginesDoNotProbe:
    """VISION #4: never ping a serverless deployment from a health check."""

    @pytest.mark.asyncio
    async def test_modal_health_makes_no_call(self, monkeypatch):
        import image_worker.engines.modal.client as modal_client

        # These engines read their configuration at import time, so the module
        # constants are what has to be patched.
        monkeypatch.setattr(modal_client, "MODAL_APP_NAME", "comfy-modal-stack")
        client = modal_client.ModalProviderClient(runtime_config={})
        payload = await client.get_health()
        assert payload["ready"] is True

    @pytest.mark.asyncio
    async def test_beam_health_makes_no_call(self, monkeypatch):
        import image_worker.engines.beam.client as beam_client

        monkeypatch.setattr(beam_client, "BEAM_API_KEY", "k")
        monkeypatch.setattr(beam_client, "BEAM_GPU_URL", "wss://x")
        monkeypatch.setattr(beam_client, "BEAM_STORAGE_URL", "https://x")
        client = beam_client.BeamProviderClient(runtime_config={})
        payload = await client.get_health()
        assert payload["ready"] is True

    @pytest.mark.asyncio
    async def test_modal_missing_config_is_not_retryable(self, monkeypatch):
        from fastapi import HTTPException

        import image_worker.engines.modal.client as modal_client
        from provider_core.responses import retryable_for_status

        monkeypatch.setattr(modal_client, "MODAL_APP_NAME", "")
        client = modal_client.ModalProviderClient(runtime_config={})
        with pytest.raises(HTTPException) as exc:
            await client.get_health()
        assert exc.value.status_code == 503
        assert retryable_for_status(503, exc.value.detail) is False

    @pytest.mark.asyncio
    async def test_beam_missing_config_is_not_retryable(self, monkeypatch):
        from fastapi import HTTPException

        import image_worker.engines.beam.client as beam_client
        from provider_core.responses import retryable_for_status

        monkeypatch.setattr(beam_client, "BEAM_API_KEY", "")
        monkeypatch.setattr(beam_client, "BEAM_GPU_URL", "")
        monkeypatch.setattr(beam_client, "BEAM_STORAGE_URL", "")
        client = beam_client.BeamProviderClient(runtime_config={})
        with pytest.raises(HTTPException) as exc:
            await client.get_health()
        assert exc.value.status_code == 503
        assert retryable_for_status(503, exc.value.detail) is False
