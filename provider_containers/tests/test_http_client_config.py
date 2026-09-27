"""Item 13: `get_http_client(config)` built the singleton on the first call and
then ignored `config` on every later call.

`provider_core/http_client.py` was:

    def get_http_client(config: HttpClientConfig = None) -> SharedHttpClient:
        global _http_client
        if _http_client is None:
            _http_client = SharedHttpClient(config)
        return _http_client

So the first caller's timeout, pool size and retry count won process-wide, and
every later caller was handed a client configured for somebody else's workload
with no way to tell. `os.getenv`'s "absent means default" trap compounded it: a
caller passing `HttpClientConfig()` looked like it was asking for the defaults
and silently got the first caller's values instead.

Configuration is now explicit and separate from acquisition
(`configure_http_client` / `get_http_client`), so these pin the new shape.
"""

from __future__ import annotations

import inspect

import pytest

from provider_core import http_client as http_client_module
from provider_core.http_client import (
    HttpClientConfig, close_http_client, configure_http_client,
    get_http_client, http_client_config_from_env,
)


@pytest.fixture(autouse=True)
def _clean_singleton():
    """The module global is process-wide; every test here needs it absent."""
    original = http_client_module._http_client
    http_client_module._http_client = None
    yield
    http_client_module._http_client = original


class TestTheConfigIsNotSilentlyDiscarded:
    def test_get_http_client_takes_no_config_at_all(self):
        """The strongest form of the fix: the parameter that used to be ignored
        is gone, so no caller can believe it is being honoured."""
        import ast

        assert list(inspect.signature(get_http_client).parameters) == []
        fn = next(
            node
            for node in ast.walk(ast.parse(inspect.getsource(get_http_client)))
            if isinstance(node, ast.FunctionDef)
        )
        names = {
            node.id for node in ast.walk(fn) if isinstance(node, ast.Name)
        } | {
            node.attr for node in ast.walk(fn) if isinstance(node, ast.Attribute)
        }
        assert "config" not in names, "the body must not look at a config either"

    def test_configure_http_client_installs_the_config_it_was_given(self):
        client = configure_http_client(HttpClientConfig(timeout=99.0, max_connections=3))
        assert client.config.timeout == 99.0
        assert client.config.max_connections == 3
        assert get_http_client() is client

    def test_a_second_configure_replaces_rather_than_being_ignored(self):
        first = configure_http_client(HttpClientConfig(timeout=11.0))
        second = configure_http_client(HttpClientConfig(timeout=22.0))
        assert first is not second
        assert get_http_client().config.timeout == 22.0, (
            "the old code kept the first caller's config forever"
        )

    def test_get_http_client_is_stable_across_calls(self):
        assert get_http_client() is get_http_client()

    @pytest.mark.asyncio
    async def test_close_resets_it_so_the_next_get_reconfigures(self):
        first = configure_http_client(HttpClientConfig(timeout=11.0))
        await close_http_client()
        assert get_http_client() is not first


class TestTheConfigComesFromTheEnvironment:
    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        for name in (
            "PROVIDER_HTTP_TIMEOUT_SECONDS",
            "PROVIDER_HTTP_MAX_CONNECTIONS",
            "PROVIDER_HTTP_MAX_KEEPALIVE",
            "PROVIDER_HTTP_RETRY_ATTEMPTS",
            "PROVIDER_HTTP_RETRY_MIN_WAIT",
            "PROVIDER_HTTP_RETRY_MAX_WAIT",
        ):
            monkeypatch.delenv(name, raising=False)

    def test_defaults_match_the_dataclass(self):
        defaults = HttpClientConfig()
        assert http_client_config_from_env() == defaults

    def test_every_knob_is_read(self, monkeypatch):
        monkeypatch.setenv("PROVIDER_HTTP_TIMEOUT_SECONDS", "12.5")
        monkeypatch.setenv("PROVIDER_HTTP_MAX_CONNECTIONS", "42")
        monkeypatch.setenv("PROVIDER_HTTP_MAX_KEEPALIVE", "7")
        monkeypatch.setenv("PROVIDER_HTTP_RETRY_ATTEMPTS", "5")
        monkeypatch.setenv("PROVIDER_HTTP_RETRY_MIN_WAIT", "0.5")
        monkeypatch.setenv("PROVIDER_HTTP_RETRY_MAX_WAIT", "30")
        assert http_client_config_from_env() == HttpClientConfig(
            timeout=12.5,
            max_connections=42,
            max_keepalive_connections=7,
            retry_attempts=5,
            retry_min_wait=0.5,
            retry_max_wait=30.0,
        )

    @pytest.mark.parametrize(
        "name", ["PROVIDER_HTTP_TIMEOUT_SECONDS", "PROVIDER_HTTP_MAX_CONNECTIONS"]
    )
    def test_a_blank_or_unparseable_value_falls_back(self, monkeypatch, name):
        """`os.getenv`'s trap again: a bare `PROVIDER_HTTP_TIMEOUT_SECONDS=` in an
        env file is not "unset", and `float("")` is not a timeout."""
        for value in ("", "   ", "not-a-number"):
            monkeypatch.setenv(name, value)
            assert http_client_config_from_env() == HttpClientConfig()

    def test_the_worker_configures_the_client_at_startup(self):
        """Without this the env knobs are read by nobody, and the four
        `get_http_client()` call sites in the two workers are no more configured
        than they were before. The configure call now lives in the shared
        `build_lifespan`, so the workers are checked for *using* it."""
        from pathlib import Path

        provider_root = Path(__file__).resolve().parents[1]
        bootstrap = (provider_root / "provider_core/worker_bootstrap.py").read_text()
        assert "configure_http_client()" in bootstrap
        assert bootstrap.index("configure_http_client()") < bootstrap.index(
            "close_http_client()"
        ), "the client must be configured before anything can use it and before teardown"

        for module in ("image_worker/worker.py", "llm_worker/worker.py"):
            source = (provider_root / module).read_text()
            assert "build_lifespan(" in source, (
                f"{module} must use the shared lifespan, which is what configures "
                "the client"
            )

    def test_the_client_is_configured_before_the_lifespan_spawns_anything(self):
        """The ordering guarantee, asserted by running it instead of scraping it.

        A previous version of this test compared the line numbers of
        `configure_http_client()` and `get_http_client()` in each worker's source
        and required the first to come first. That was a proxy for the real
        invariant and it eventually demanded the wrong thing: a worker that
        passes `get_http_client()` into a deferred lambda is using the shared
        pool correctly, but the scrape could only see that the word appeared in
        the file — so the only way to satisfy it was to drop the call, leaving
        `auto_discovery_loop` to build a fresh `httpx.AsyncClient` on every
        60-second heartbeat.

        The real invariant is behavioural: once the lifespan has started, the
        shared client must already carry the environment-derived configuration.
        """
        import asyncio
        import importlib

        from provider_core import http_client as core_http

        for module in ("image_worker.worker", "llm_worker.worker"):
            worker = importlib.import_module(module)
            core_http._http_client = None
            try:
                async def _enter():
                    async with worker.app.router.lifespan_context(worker.app):
                        return core_http._http_client

                live = asyncio.run(_enter())
                assert live is not None, f"{module} configured no shared client"
                assert live.config == core_http.http_client_config_from_env(), (
                    f"{module}: the shared client is in use before it is configured, "
                    "so the env knobs are ignored process-wide"
                )
            finally:
                core_http._http_client = None
