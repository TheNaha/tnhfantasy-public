"""Engine registries and the shared worker lifespan.

`image_worker/worker.py` and `llm_worker/worker.py` each had the same 17-line
`if ENGINE ==` client-selection ladder, and the two had drifted: their
`runtime_config` dicts declared different keys, so the LLM worker never received
`max_concurrent_downloads` and `provider_core/base_client.py` fell back to its
default of 2 instead of the configured 5 for every LLM reconciliation. The two
lifespans had drifted the same way — the LLM copy lacked the `except Exception:
pass` around `client.close()`, so a raising `close()` turned a clean SIGTERM into
a traceback and skipped the remaining teardown — and both used bare
`asyncio.create_task` instead of `spawn_background_task`, so neither applied the
`MAX_BACKGROUND_TASKS` bound that function exists to enforce.

One registry and one lifespan, so the next engine is one entry rather than two
copies, and a fix lands on both workers at once.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, Optional, Set

from .background import spawn_background_task
from .http_client import close_http_client, configure_http_client
from .logging import get_logger

logger = get_logger("provider_core.worker_bootstrap")


# ── Engine registries ────────────────────────────────────────────────────────
#
# `module` / `class_name` are resolved lazily by `select_client`, so importing
# this module does not import every engine: `image_worker.worker` must not need
# beta9, and importing it under an unknown ENGINE must still raise the same
# "Valid values:" error the two ladders used to raise.
#
# `pass_provider_id` records the one shape difference: the four LLM clients take
# `provider_id` as a positional argument, the four image clients read it out of
# `runtime_config`. Stated per entry rather than sniffed from a signature, so a
# new engine's constructor is a decision in this file.

IMAGE_ENGINES: Dict[str, Dict[str, Any]] = {
    "modal": {"module": "image_worker.engines.modal.client", "class_name": "ModalProviderClient"},
    "beam": {"module": "image_worker.engines.beam.client", "class_name": "BeamProviderClient"},
    "direct_url": {
        "module": "image_worker.engines.direct_url.client",
        "class_name": "DirectUrlProviderClient",
    },
    "remote_comfy": {
        "module": "image_worker.engines.remote_comfy.client",
        "class_name": "RemoteComfyProviderClient",
    },
}

# Text-to-speech engines.
#
# Modal only, deliberately. A TTS worker is a separate provider CONTAINER —
# built from `tts_worker/Dockerfile`, registered by self-discovery, with its own
# health and its own Modal app — because the image worker's `/health` only checks
# that `MODAL_APP_NAME` is set, so a shared container would report healthy for
# both apps while being entirely blind to the TTS one. Separate containers mean
# separate health, separate failure domains, and TTS can be deployed or removed
# without touching the image path.
#
# The image worker's client was briefly taught to route `tts` to a second app
# instead. That was wrong on the codebase's own model — one provider is one
# container — and is reverted.
#
# Beam / direct_url / remote_comfy are absent because none of them can run a
# ComfyUI graph on a machine you do not control, which is what a TTS model
# needs. Adding one later is one entry here plus a client module.
TTS_ENGINES: Dict[str, Dict[str, Any]] = {
    "modal": {
        "module": "tts_worker.engines.modal.client",
        "class_name": "ModalTTSProviderClient",
    },
}

LLM_ENGINES: Dict[str, Dict[str, Any]] = {
    "openai_compat": {
        "module": "llm_worker.engines.openai_compat.client",
        "class_name": "OpenAICompatProviderClient",
        "pass_provider_id": True,
    },
    "anthropic": {
        "module": "llm_worker.engines.anthropic.client",
        "class_name": "AnthropicProviderClient",
        "pass_provider_id": True,
    },
    "google": {
        "module": "llm_worker.engines.google.client",
        "class_name": "GoogleProviderClient",
        "pass_provider_id": True,
    },
    "modal": {
        "module": "llm_worker.engines.modal.client",
        "class_name": "VLLMModalProviderClient",
        "pass_provider_id": True,
    },
}

# The same seven keys for every engine, in both workers. `provider_core.router`
# reads the first two; `base_client` reads `max_concurrent_downloads` (which it
# defaulted to 2, so an LLM worker's 5 was silently never applied);
# `base_client.validate_all_models` reads the three timeouts. The reconciliation
# interval/delay are module constants in both workers and are passed to
# `reconciliation_loop` separately, because they are not client config.
RUNTIME_CONFIG_KEYS = (
    "provider_id",
    "backend_url",
    "storage_dir",
    "max_concurrent_downloads",
    "validation_timeout_seconds",
    "reconciliation_list_timeout_seconds",
    "inference_timeout_seconds",
)


def build_runtime_config(
    *,
    provider_id: str,
    backend_url: str,
    storage_dir: str,
    max_concurrent_downloads: int,
    validation_timeout_seconds: float,
    reconciliation_list_timeout_seconds: float,
    inference_timeout_seconds: float,
) -> Dict[str, Any]:
    """The one runtime_config builder both workers use.

    Emitting the same seven keys unconditionally is the whole point: the drift
    this replaces was silent, because a missing key is a default, not an error.
    """
    return {
        "provider_id": provider_id,
        "backend_url": backend_url,
        "storage_dir": storage_dir,
        "max_concurrent_downloads": max_concurrent_downloads,
        "validation_timeout_seconds": validation_timeout_seconds,
        "reconciliation_list_timeout_seconds": reconciliation_list_timeout_seconds,
        "inference_timeout_seconds": inference_timeout_seconds,
    }


def select_client(engines: Dict[str, Dict[str, Any]], engine: str, runtime_config: Dict[str, Any]):
    """Build the client for `engine`, or raise naming the valid values.

    A bad ENGINE must still fail loudly: the old ladders raised
    `ValueError(f"Unknown ENGINE: {ENGINE!r}. Valid values: ...")`, and several
    tests depend on that message.
    """
    import importlib

    entry = engines.get(engine)
    if entry is None:
        raise ValueError(
            f"Unknown ENGINE: {engine!r}. Valid values: {', '.join(sorted(engines))}."
        )
    module = importlib.import_module(entry["module"])
    kwargs: Dict[str, Any] = {"runtime_config": runtime_config}
    if entry.get("pass_provider_id"):
        kwargs["provider_id"] = runtime_config.get("provider_id", "")
    return getattr(module, entry["class_name"])(**kwargs)


# ── The shared lifespan ──────────────────────────────────────────────────────


def build_lifespan(
    client: Any,
    *,
    reconciliation: Optional[Callable[..., Any]] = None,
    auto_discovery: Optional[Callable[..., Any]] = None,
) -> Any:
    """The one worker lifespan: configure the shared client, start both loops,
    tear both down in reverse.

    The teardown is where the two copies had drifted. The LLM one had no
    `except Exception: pass` around `client.close()`, so a `close()` that raised
    (and both Modal clients now can — they cancel in-flight reads) turned a clean
    SIGTERM into a traceback and skipped the loop cancellations that follow, which
    is the opposite of what shutdown wants.

    Both loops go through `spawn_background_task`, which retains the task (a bare
    `create_task` keeps only a weak reference, so the loop may collect a running
    task) and applies the `MAX_BACKGROUND_TASKS` bound neither worker applied.
    """
    tasks: Set[asyncio.Task] = set()

    @asynccontextmanager
    async def lifespan(_app):
        # Explicit, before the first get_http_client(): the shared client is a
        # process-wide singleton and `get_http_client` takes no config on purpose
        # (it used to accept one and ignore it after the first caller).
        configure_http_client()

        if reconciliation is not None:
            spawn_background_task(reconciliation(), tasks=tasks, name="reconciliation_loop")
        if auto_discovery is not None:
            spawn_background_task(auto_discovery(), tasks=tasks, name="auto_discovery_loop")

        logger.info(
            "[%s] Worker started (client=%s)",
            getattr(client, "provider_id", "?"),
            type(client).__name__,
        )
        yield

        # Every step isolated: a failure in teardown must not strand the steps
        # below it. `spawn_background_task` discards each task from the set as it
        # finishes, so cancelling the remaining set is the whole teardown.
        pending = tuple(tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        tasks.clear()

        try:
            await client.close()
        except Exception:
            # Swallow. The next step (releasing the shared pool) matters more than
            # a client's own complaint during shutdown, and an unhandled
            # exception here skips everything after it.
            pass

        try:
            await close_http_client()
        except Exception:
            pass

    return lifespan
