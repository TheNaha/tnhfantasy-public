"""The worker lifespan wiring, exercised rather than assumed.

596 provider tests passed while every provider container crash-looped on
startup with `TypeError: auto_discovery_loop() got an unexpected keyword
argument 'storage_dir'`. Nothing here mocked anything, so the defect was
invisible: the tests covered the loops and the bootstrap in isolation, and
never once called the factory each worker hands to `build_lifespan`.

That is the whole class — an argument the loop does not accept, an argument
dropped so a fallback silently takes over. Both are invisible to a unit test
that constructs its own arguments. These tests construct the workers'.

Nothing here starts a server or touches the network: the loops are replaced by
recorders, and the only thing under test is the *shape* of the call each worker
makes, which is precisely what was wrong.
"""
import asyncio
import inspect
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from provider_core.background import auto_discovery_loop, reconciliation_loop  # noqa: E402


def _call_factories(monkeypatch, module_globals):
    """Invoke each worker's loop factory and record the kwargs it passes.

    The factory is a lambda in the worker's module namespace, so it closes over
    that namespace's `auto_discovery_loop` / `reconciliation_loop`. Rebinding
    them in the module dict is what the lambda resolves at call time, which is
    how we intercept without changing production code.
    """
    recorded = {}

    def _recorder(name):
        def _fn(**kwargs):
            recorded[name] = kwargs
            return asyncio.sleep(0)
        return _fn

    for name in ("auto_discovery_loop", "reconciliation_loop"):
        module_globals[name] = _recorder(name)
    return recorded


@pytest.mark.parametrize("worker_module", ["image_worker.worker", "llm_worker.worker"])
def test_worker_loop_factories_pass_only_real_parameters(worker_module, monkeypatch):
    """Every keyword a worker passes must be a parameter the loop declares.

    This is the test that would have caught the crash. The defect was a
    `storage_dir=` argument that `auto_discovery_loop` has never accepted, so
    every provider died in its own lifespan before uvicorn bound.
    """
    monkeypatch.setenv("ENGINE", "modal")
    monkeypatch.setenv("PROVIDER_ID", "probe-provider")
    monkeypatch.setenv("BACKEND_URL", "http://backend_v2:8002")
    monkeypatch.setenv("COMFY_PROVIDER_TOKEN", "token")

    module = __import__(worker_module, fromlist=["*"])
    recorded = _call_factories(monkeypatch, vars(module))
    lifespan = module.app.router.lifespan_context

    async def _enter():
        async with lifespan(module.app):
            pass

    asyncio.run(_enter())

    assert recorded, "no loop factory was called; the lifespan wiring changed shape"
    assert set(recorded) == {"auto_discovery_loop", "reconciliation_loop"}

    for name, kwargs in recorded.items():
        loop = {"auto_discovery_loop": auto_discovery_loop, "reconciliation_loop": reconciliation_loop}[name]
        accepted = set(inspect.signature(loop).parameters)
        unexpected = set(kwargs) - accepted
        assert not unexpected, (
            f"{worker_module} passes {sorted(unexpected)} to {name}(), which accepts "
            f"{sorted(accepted)}. Every provider container crash-loops on startup with "
            f"TypeError."
        )


@pytest.mark.parametrize("worker_module", ["image_worker.worker", "llm_worker.worker"])
def test_auto_discovery_receives_the_shared_http_client(worker_module, monkeypatch):
    """`http_client` must be passed, not left to the fallback.

    `auto_discovery_loop(http_client=None)` builds a fresh `httpx.AsyncClient`
    on every 60-second heartbeat. That is the documented fallback and it works —
    which is what makes the regression easy to miss: no error, no warning, just
    a connection pool thrown away every minute. The shared client exists
    precisely so this does not happen.
    """
    monkeypatch.setenv("ENGINE", "modal")
    monkeypatch.setenv("PROVIDER_ID", "probe-provider")
    monkeypatch.setenv("BACKEND_URL", "http://backend_v2:8002")
    monkeypatch.setenv("COMFY_PROVIDER_TOKEN", "token")

    module = __import__(worker_module, fromlist=["*"])
    recorded = _call_factories(monkeypatch, vars(module))
    lifespan = module.app.router.lifespan_context

    async def _enter():
        async with lifespan(module.app):
            pass

    asyncio.run(_enter())

    assert "http_client" in recorded["auto_discovery_loop"], (
        "auto_discovery_loop was called without an http_client, so it rebuilds an "
        "httpx.AsyncClient on every heartbeat instead of using the shared pool"
    )
    assert recorded["auto_discovery_loop"]["http_client"] is not None


@pytest.mark.parametrize("worker_module", ["image_worker.worker", "llm_worker.worker"])
def test_both_loops_are_started_and_the_lifespan_exits_cleanly(worker_module, monkeypatch):
    """Startup spawns both loops; shutdown cancels and joins them.

    The teardown is what the two duplicated lifespans disagreed about, so it
    gets the same treatment as startup: called, and asserted on, rather than
    reasoned about.
    """
    monkeypatch.setenv("ENGINE", "modal")
    monkeypatch.setenv("PROVIDER_ID", "probe-provider")
    monkeypatch.setenv("BACKEND_URL", "http://backend_v2:8002")
    monkeypatch.setenv("COMFY_PROVIDER_TOKEN", "token")

    module = __import__(worker_module, fromlist=["*"])
    _call_factories(monkeypatch, vars(module))
    lifespan = module.app.router.lifespan_context

    async def _enter():
        async with lifespan(module.app):
            # Yield point reached: both loops were spawned without raising.
            await asyncio.sleep(0)

    asyncio.run(_enter())  # must return, not raise


def test_engine_registry_covers_every_engine_the_backend_can_emit():
    """A missing engine is an import-time crash, and an extra one is a name
    the backend can never select."""
    from provider_core.worker_bootstrap import IMAGE_ENGINES, LLM_ENGINES

    backend_engines = {"modal", "beam", "direct_url", "remote_comfy"}
    llm_engines = {"openai_compat", "anthropic", "google", "modal"}

    assert set(IMAGE_ENGINES) == backend_engines
    assert set(LLM_ENGINES) == llm_engines

    for name, registry in (("image", IMAGE_ENGINES), ("llm", LLM_ENGINES)):
        for engine, target in registry.items():
            module_path = target["module"]
            class_name = target["class_name"]
            assert module_path and class_name, f"{name} engine {engine} is incomplete"
            assert os.path.exists(
                Path(__file__).resolve().parents[1] / (module_path.replace(".", "/") + ".py")
            ), f"{name} engine {engine} points at {module_path}, which does not exist"
            # And the class it names must actually be there: a typo is an
            # AttributeError at worker import, which crash-loops the container
            # with a message that never names the engine.
            import importlib

            assert hasattr(
                importlib.import_module(module_path), class_name
            ), f"{name} engine {engine} names {class_name}, which {module_path} does not define"
