"""Finding 4: `remote_comfy`'s `/health` probed nothing.

`image_worker/engines/remote_comfy/client.py:59-60` was

    async def get_health(self):
        return ok("Provider is running (remote comfy)", provider=PROVIDER_ID, ready=True)

No ComfyUI probe, no agent probe. The backend's `_check_provider_health`
(backend_v2/services/load_balancer.py:345) requires HTTP 200, so it counted this
provider as a usable target and dispatched paid jobs at it; the first job then
failed at `/prompt`, and because every httpx error in this file is marked
`retryable=True` (provider_core/responses.py) the balancer retried across every
other provider — spending money on requests that cannot succeed.

`direct_url` is the identical shape of bug and was already fixed, by doing a real
`GET /system_stats` with a short timeout. That is the fix, applied to the sibling
that shares the code path.
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from image_worker.engines.remote_comfy.client import (
    HEALTH_PROBE_TIMEOUT, RemoteComfyProviderClient,
)


def _client(monkeypatch, comfy_dead: bool = False, agent_dead: bool = False, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    client = RemoteComfyProviderClient(runtime_config={})

    # The agent URL is a module constant read at import time (like the sibling
    # engines' BEAM_STORAGE_URL etc), so setting the env var here is not enough —
    # the module attribute is what the code actually reads.
    import image_worker.engines.remote_comfy.client as module
    for key, value in env.items():
        if hasattr(module, key):
            monkeypatch.setattr(module, key, value)

    # The ComfyUI side is client._http (base_url = COMFYUI_URL).
    client._http = MagicMock()
    client._http.aclose = AsyncMock()
    if comfy_dead:
        import httpx
        client._http.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    else:
        client._http.get = AsyncMock(return_value=MagicMock(status_code=200))

    # The agent side goes through the shared provider_core client.
    agent_http = MagicMock()
    if agent_dead:
        import httpx
        agent_http.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    else:
        agent_http.get = AsyncMock(return_value=MagicMock(status_code=200))
    client._agent_http = agent_http
    module.get_http_client = lambda: agent_http
    return client


class TestHealthActuallyProbes:
    @pytest.mark.asyncio
    async def test_healthy_when_both_upstreams_answer(self, monkeypatch):
        client = _client(
            monkeypatch,
            COMFYUI_URL="http://comfy.rig:8188",
            REMOTE_AGENT_URL="http://agent.rig:8001",
        )
        try:
            payload = await client.get_health()
        finally:
            await client.close()

        assert payload["ready"] is True
        assert payload["status"] == "healthy"
        assert payload["comfy_reachable"] is True
        assert payload["agent_reachable"] is True

    @pytest.mark.asyncio
    async def test_a_dead_comfyui_makes_it_not_ready(self, monkeypatch):
        """The exact defect: hardcoded ready, with the upstream refusing."""
        from fastapi import HTTPException

        client = _client(monkeypatch, comfy_dead=True)
        try:
            with pytest.raises(HTTPException) as exc:
                await client.get_health()
        finally:
            await client.close()

        assert exc.value.status_code == 503
        assert exc.value.detail["ready"] is False
        assert "unreachable" in exc.value.detail["message"]
        assert exc.value.detail["comfy_reachable"] is False

    @pytest.mark.asyncio
    async def test_a_dead_agent_makes_it_not_ready(self, monkeypatch):
        """Inference runs through ComfyUI, but storage does not exist without the
        agent — a provider that cannot list or delete is not usable."""
        from fastapi import HTTPException

        client = _client(monkeypatch, agent_dead=True)
        try:
            with pytest.raises(HTTPException) as exc:
                await client.get_health()
        finally:
            await client.close()

        assert exc.value.status_code == 503
        assert exc.value.detail["ready"] is False
        assert exc.value.detail["agent_reachable"] is False

    @pytest.mark.asyncio
    async def test_both_dead_reports_both(self, monkeypatch):
        from fastapi import HTTPException

        client = _client(monkeypatch, comfy_dead=True, agent_dead=True)
        try:
            with pytest.raises(HTTPException) as exc:
                await client.get_health()
        finally:
            await client.close()

        message = exc.value.detail["message"]
        assert "ComfyUI" in message
        assert "agent" in message

    @pytest.mark.asyncio
    async def test_503_is_still_retryable(self, monkeypatch):
        """A dead rig comes back. A config fault does not; do not conflate them."""
        from fastapi import HTTPException
        from provider_core.responses import retryable_for_status

        client = _client(monkeypatch, comfy_dead=True)
        try:
            with pytest.raises(HTTPException) as exc:
                await client.get_health()
        finally:
            await client.close()

        assert retryable_for_status(exc.value.status_code, exc.value.detail) is True
        assert "retryable" not in exc.value.detail

    @pytest.mark.asyncio
    async def test_it_probes_system_stats_not_object_info(self, monkeypatch):
        """`/object_info` is a multi-megabyte node graph. `/system_stats` is a few
        hundred bytes and is always present."""
        client = _client(monkeypatch)
        try:
            await client.get_health()
        finally:
            await client.close()

        args, kwargs = client._http.get.call_args
        assert args[0] == "/system_stats"
        assert kwargs["timeout"] == HEALTH_PROBE_TIMEOUT

    @pytest.mark.asyncio
    async def test_it_also_probes_the_agent_health_route(self, monkeypatch):
        client = _client(monkeypatch, REMOTE_AGENT_URL="http://agent.rig:8001")
        try:
            await client.get_health()
        finally:
            await client.close()

        client._agent_http.get.assert_awaited_once()
        assert client._agent_http.get.call_args.args[0] == "http://agent.rig:8001/health"

    @pytest.mark.asyncio
    async def test_the_probes_run_concurrently(self, monkeypatch):
        """Two sequential probes would take 2x the timeout, and the dispatcher
        probes /health with a 2.0s budget (load_balancer.py:345)."""
        import time

        client = _client(monkeypatch)

        async def _slow(*_args, **_kwargs):
            await asyncio_sleep(0.2)
            return MagicMock(status_code=200)

        client._http.get = AsyncMock(side_effect=_slow)
        client._agent_http.get = AsyncMock(side_effect=_slow)

        try:
            started = time.monotonic()
            await client.get_health()
            elapsed = time.monotonic() - started
        finally:
            await client.close()

        assert elapsed < 0.35, f"probes appear serial (took {elapsed:.2f}s)"

    def test_the_probe_timeout_fits_the_dispatcher_budget(self):
        """backend_v2/services/load_balancer.py:345 and
        api/routes/providers/crud.py:167 probe /health with
        `_HTTP_HEALTH_PROBE_TIMEOUT_SECONDS = 2.0` and require HTTP 200. A probe
        slower than that reads as "no answer" and the provider is excluded from
        dispatch, so it has to be comfortably inside 2s."""
        assert 0 < HEALTH_PROBE_TIMEOUT < 2.0

    @pytest.mark.asyncio
    async def test_health_does_not_echo_the_rig_addresses(self, monkeypatch):
        """`/health` is unauthenticated, so the payload must not carry the LAN
        addresses the probes used; `/info` is authenticated and still does.

        The *request* obviously has to name the URLs — what must not escape is the
        response.
        """
        client = _client(
            monkeypatch,
            COMFYUI_URL="http://192.0.2.10:8188",
            REMOTE_AGENT_URL="http://192.0.2.11:8001",
        )
        try:
            payload = await client.get_health()
        finally:
            await client.close()

        serialised = json.dumps(payload)
        assert "192.0.2.10" not in serialised
        assert "192.0.2.11" not in serialised
        assert "comfy_url" in inspect.getsource(RemoteComfyProviderClient.get_info)


class TestTheServerlessEnginesStillDoNotProbe:
    """VISION #4: never ping a serverless deployment from a health check.

    `remote_comfy` and `direct_url` front a machine the user runs, so a probe is
    free. Modal and Beam do not: their /health is config-only, and a probe there
    costs money on every call. The fix must not have leaked into them.
    """

    @pytest.mark.asyncio
    async def test_modal_makes_no_call(self, monkeypatch):
        import image_worker.engines.modal.client as modal_client

        monkeypatch.setattr(modal_client, "MODAL_APP_NAME", "comfy-modal-stack")
        payload = await modal_client.ModalProviderClient(runtime_config={}).get_health()
        assert payload["ready"] is True

    @pytest.mark.asyncio
    async def test_beam_makes_no_call(self, monkeypatch):
        import image_worker.engines.beam.client as beam_client

        monkeypatch.setattr(beam_client, "BEAM_API_KEY", "k")
        monkeypatch.setattr(beam_client, "BEAM_GPU_URL", "wss://x")
        monkeypatch.setattr(beam_client, "BEAM_STORAGE_URL", "https://x")
        payload = await beam_client.BeamProviderClient(runtime_config={}).get_health()
        assert payload["ready"] is True


async def asyncio_sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
