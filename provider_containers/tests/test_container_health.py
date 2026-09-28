"""Finding 6: a provider's container health depended on a third-party ComfyUI.

The chain, as reported:

  * `docker-compose.yml`'s healthcheck called `python3 -c "urllib.request.urlopen(
    'http://localhost:8000/health')"`.
  * `image_worker/engines/direct_url/client.py:get_health` answers **503** unless a
    live `GET {COMFYUI_URL}/system_stats` returns 200.
  * `urlopen` raises `HTTPError` on 503 -> non-zero exit -> 5 consecutive failures ->
    UNHEALTHY.

Compose does not `depends_on` that ComfyUI, does not `extra_hosts` it, and the
address lives only in the untracked `.env.direct-url` pointing at a remote host on a
non-default port. So a provider worker being unable to reach its backend turned the
worker CONTAINER red and cascaded, even though the worker was serving perfectly
well and the upstream signal is exactly what the operator and the dispatcher need.

The fix splits the two questions:

  * `/live` — is this process serving HTTP? No upstream probe. This is what the
    container healthcheck (compose and both Dockerfiles) calls.
  * `/health` — is the provider usable, upstream included? Unchanged in spirit, and
    still what the backend's `_check_provider_health` and
    `api/routes/providers/crud.py` probe.

Nothing here needs a running container: the assertions are about the route
definitions, the Dockerfiles' healthcheck commands, and compose's.
"""

from __future__ import annotations

import pathlib

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from provider_core.router import attach_provider_routes


class _StubClient:
    """A client whose get_health is expensive and whose get_storage_stats is not."""

    def __init__(self, healthy: bool = True):
        self.provider_id = "test-provider"
        self._healthy = healthy
        self.health_calls = 0

    async def get_health(self):
        self.health_calls += 1
        if self._healthy:
            return {"status": "healthy", "provider_id": "test-provider", "ready": True}
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail={"message": "upstream is unreachable", "ready": False})

    def get_reconciliation_status(self):
        return {}

    def get_config(self):
        return {}

    def update_config(self, new_config):
        return {"status": "updated"}


def _app(client) -> FastAPI:
    app = FastAPI()
    attach_provider_routes(app, client)
    return app


class TestLiveIsASeparateRoute:
    @pytest.mark.asyncio
    async def test_live_answers_200_when_the_upstream_is_dead(self):
        """The whole point: the container healthcheck must not go red because a
        ComfyUI this compose file does not manage is unreachable."""
        client = _StubClient(healthy=False)
        async with AsyncClient(transport=ASGITransport(app=_app(client)), base_url="http://w") as http:
            response = await http.get("/live")

        assert response.status_code == 200
        assert response.json()["status"] == "alive"

    @pytest.mark.asyncio
    async def test_live_does_not_call_get_health(self):
        client = _StubClient()
        async with AsyncClient(transport=ASGITransport(app=_app(client)), base_url="http://w") as http:
            await http.get("/live")
        assert client.health_calls == 0, (
            "/live must answer from the process, not by asking the engine — asking "
            "the engine IS the probe that makes the container healthcheck cascade"
        )

    @pytest.mark.asyncio
    async def test_health_still_reports_the_upstream(self):
        """The richer signal stays where the dispatcher reads it."""
        client = _StubClient(healthy=False)
        async with AsyncClient(transport=ASGITransport(app=_app(client)), base_url="http://w") as http:
            response = await http.get("/health")

        assert response.status_code == 503
        assert "unreachable" in response.json()["message"]
        assert client.health_calls == 1

    @pytest.mark.asyncio
    async def test_live_is_unauthenticated(self):
        """The healthcheck sends no headers, and PROVIDER_WORKER_TOKEN gates
        everything else. A gated /live would make every container unhealthy."""
        client = _StubClient()
        app = _app(client)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://w") as http:
            # No X-Provider-Token. The router would 503 for a missing token.
            response = await http.get("/live")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_live_still_answers_when_the_token_is_unset(self, monkeypatch):
        monkeypatch.delenv("PROVIDER_WORKER_TOKEN", raising=False)
        client = _StubClient()
        async with AsyncClient(transport=ASGITransport(app=_app(client)), base_url="http://w") as http:
            assert (await http.get("/live")).status_code == 200
            # And a protected route still fails closed, as it must.
            assert (await http.get("/config")).status_code == 503


class TestTheHealthchecksCallLive:
    """The Dockerfiles and compose, statically. No container is started."""

    @pytest.mark.parametrize(
        "dockerfile",
        ["image_worker/Dockerfile", "llm_worker/Dockerfile"],
    )
    def test_the_baked_healthcheck_uses_live_and_respects_port(self, dockerfile):
        path = pathlib.Path(__file__).resolve().parents[1] / dockerfile
        text = path.read_text()

        healthcheck = text.split("HEALTHCHECK", 1)[1]
        assert "/live" in healthcheck, f"{dockerfile} healthcheck must call /live"
        assert "8000/health" not in healthcheck, (
            f"{dockerfile} healthcheck still points at /health, so a provider whose "
            "upstream is down is UNHEALTHY and cascades"
        )
        # `$PORT`, not a literal. `image_worker/worker.py:115` and the llm twin
        # read the port from `$PORT`, and compose sets PORT per service, so a
        # hardcoded 8000 made any provider on another port permanently unhealthy
        # with no compose-level override.
        assert "os.environ.get('PORT', '8000')" in healthcheck, (
            f"{dockerfile} healthcheck hardcodes the port"
        )
        assert "'http://localhost:8000/live'" not in healthcheck

    def test_compose_provider_healthchecks_call_live(self):
        """Read-only. Every provider service's healthcheck, statically."""
        compose = (
            pathlib.Path(__file__).resolve().parents[2] / "docker-compose.yml"
        ).read_text()

        live_call = "urlopen('http://localhost:%s/live' % os.environ.get('PORT', '8000'))"

        # 5 live provider services: 3 modal, llm-local, direct-url.
        uncommented = "\n".join(
            line for line in compose.splitlines() if not line.lstrip().startswith("#")
        )
        # Six now: the five original providers plus `provider-tts-modal-hp196`.
        # Counted rather than named because the point of the test is that EVERY
        # active provider healthchecks on /live, so a new provider without one
        # fails here — which is exactly what happened when the TTS service was
        # added and the count was not updated.
        assert uncommented.count(live_call) == 6, (
            f"expected 5 active provider healthchecks on /live, "
            f"found {uncommented.count(live_call)}"
        )
        assert "8000/health" not in uncommented, (
            "an active provider healthcheck still probes /health"
        )

        # The commented-out provider-remote-comfy block must match the live ones,
        # or uncommenting it as documented reintroduces the cascade.
        commented_healthchecks = [
            line for line in compose.splitlines()
            if line.lstrip().startswith("#") and live_call in line
        ]
        assert len(commented_healthchecks) == 1, (
            "the commented-out provider-remote-comfy healthcheck should also be on /live"
        )

    def test_the_direct_url_healthcheck_has_a_coherent_budget(self):
        """Finding 6b: the 10s budget could not contain a 5s socket probe plus
        interpreter startup. With /live there is no socket probe at all, so 10s is
        now generous — and the 5s upstream probe moved off the container health
        entirely, to /health, where the dispatcher's 2s budget governs it."""
        compose = (
            pathlib.Path(__file__).resolve().parents[2] / "docker-compose.yml"
        ).read_text()

        direct_url_block = compose.split("provider-direct-url:", 1)[1].split("\n  #", 1)[0]
        assert "timeout: 10s" in direct_url_block

        from image_worker.engines.direct_url.client import HEALTH_PROBE_TIMEOUT

        assert HEALTH_PROBE_TIMEOUT < 2.0, (
            "the upstream probe must fit inside the dispatcher's 2.0s /health budget"
        )


class TestTheLlmImageIsNotRoot:
    """Finding 26: `llm_worker/Dockerfile` had no `USER`.

    `image_worker/Dockerfile` had `USER worker`; the LLM image ran as root and only
    compose's `user: "1000:1000"` prevented it. That matters more now because the
    LLM image is the one whose `/deploy` shells out to `modal deploy`
    (llm_worker/engines/modal/client.py).
    """

    @pytest.mark.parametrize(
        "dockerfile", ["image_worker/Dockerfile", "llm_worker/Dockerfile"]
    )
    def test_both_images_drop_to_an_unprivileged_user(self, dockerfile):
        text = (
            pathlib.Path(__file__).resolve().parents[1] / dockerfile
        ).read_text()
        assert "USER worker" in text, f"{dockerfile} runs as root"
        # USER must come after the COPY, or the copied tree is still root-owned.
        assert text.index("USER worker") > text.rindex("COPY "), (
            f"{dockerfile} switches user before its last COPY"
        )

    def test_both_images_create_the_same_user(self):
        for dockerfile in ("image_worker/Dockerfile", "llm_worker/Dockerfile"):
            text = (
                pathlib.Path(__file__).resolve().parents[1] / dockerfile
            ).read_text()
            assert "useradd -r -u 1000" in text, (
                f"{dockerfile} must use the same uid as the image twin so the shared "
                "./data bind mount stays writable"
            )


class TestEmptyEngineIsUnsetNotFatal:
    """Finding 25: `ENGINE=` set-but-empty crashed the worker at import.

    `os.getenv("ENGINE", "modal").lower()` yields `""` for a bare `ENGINE=`, which
    matches no branch, so it reached `raise ValueError(f"Unknown ENGINE: {ENGINE}")`
    at IMPORT — before uvicorn bound, and with a message that did not name the
    valid values.
    """

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("", "modal"),            # image worker default
            ("   ", "modal"),         # whitespace-only
            ("MODAL", "modal"),       # case
            ("  beam  ", "beam"),     # padding
            ("direct_url", "direct_url"),
        ],
    )
    def test_the_image_worker_reads_the_engine_value(self, value, expected, monkeypatch):
        monkeypatch.setenv("ENGINE", value)
        import importlib

        import image_worker.worker as worker

        try:
            reloaded = importlib.reload(worker)
            assert reloaded.ENGINE == expected
        except ValueError as exc:
            # Only acceptable for a genuinely unknown value, and then the message
            # must name the valid ones.
            assert expected not in ("", "modal", "beam", "direct_url", "remote_comfy")
            assert "Valid values" in str(exc), f"unhelpful error: {exc}"
            assert "modal" in str(exc) and "direct_url" in str(exc)
        finally:
            monkeypatch.setenv("ENGINE", "modal")
            importlib.reload(worker)

    @pytest.mark.parametrize("registry_name", ["IMAGE_ENGINES", "LLM_ENGINES"])
    def test_an_unknown_engine_names_the_valid_values(self, registry_name):
        """The raise moved into `provider_core.worker_bootstrap.select_client`
        (item 21) — the message it produces is the same one, and it is built from
        the registry so the list cannot drift from what can actually be built."""
        from provider_core import worker_bootstrap

        engines = getattr(worker_bootstrap, registry_name)
        with pytest.raises(ValueError) as exc:
            worker_bootstrap.select_client(engines, "definitely-not-an-engine", {})

        message = str(exc.value)
        assert "Valid values" in message, message
        for engine in engines:
            assert engine in message, f"the error must name {engine!r}"
        assert "definitely-not-an-engine" in message

    def test_the_worker_no_longer_owns_the_engine_list(self):
        """It is a registry now: `select_client` raises, so a stale second list
        would only be a second thing to forget."""
        import pathlib

        text = (
            pathlib.Path(__file__).resolve().parents[1] / "image_worker/worker.py"
        ).read_text()
        assert "elif ENGINE ==" not in text, "the client-selection ladder is gone"
        assert "select_client(IMAGE_ENGINES" in text
