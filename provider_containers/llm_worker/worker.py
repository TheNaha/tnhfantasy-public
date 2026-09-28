"""
Unified LLM Worker
This service receives HTTP requests and routes them to the appropriate LLM engine.

The engine registry, the runtime_config builder and the lifespan live in
`provider_core.worker_bootstrap`; this module supplies the LLM worker's
environment and its two loops. The client-selection ladder and the lifespan were
duplicated from `image_worker/worker.py` and had drifted: the two
`runtime_config` dicts declared different keys (so `max_concurrent_downloads`
never reached this worker and `base_client` used its default of 2 for every
reconciliation), and this copy of the teardown had no `except Exception: pass`
around `client.close()`, so a raising close skipped the rest of shutdown.
"""

import os
from fastapi import FastAPI

from provider_core.http_client import get_http_client
from provider_core.router import attach_provider_routes
from provider_core.background import (
    auto_discovery_loop,
    log_startup_info,
    reconciliation_loop,
)
from provider_core.worker_bootstrap import (
    LLM_ENGINES,
    build_lifespan,
    build_runtime_config,
    select_client,
)

# Read environment configuration
# `.strip()` and the `or` fallback, for the same reason as image_worker/worker.py:
# a bare `ENGINE=` or `PROVIDER_ID=` in an env file yields "", and an empty
# provider_id registers this worker's models under no provider at all.
# `os.environ.get`'s default only applies when the variable is ABSENT, so the
# default has to be applied by hand here.
ENGINE = (os.environ.get("ENGINE") or "openai_compat").strip().lower() or "openai_compat"
PROVIDER_ID = (os.environ.get("PROVIDER_ID") or "").strip() or "local-dev"
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8002")

# Same names and defaults as image_worker/worker.py, read from the same env knobs.
RECONCILIATION_INTERVAL_SECONDS = int(os.environ.get("RECONCILIATION_INTERVAL_SECONDS", "7200"))
RECONCILIATION_STARTUP_DELAY_SECONDS = int(os.environ.get("RECONCILIATION_STARTUP_DELAY_SECONDS", "130"))

# Valid names come from LLM_ENGINES, so this list cannot drift from what
# select_client can actually build.
valid_engines = ", ".join(sorted(LLM_ENGINES))

STORAGE_DIR = "/data"

# The same seven keys the image worker emits. This dict used to carry only
# provider_id/backend_url/storage_dir, so `max_concurrent_downloads` silently
# fell back to base_client's default of 2 for every LLM reconciliation, and the
# three timeout knobs were never read on this side at all.
runtime_config = build_runtime_config(
    provider_id=PROVIDER_ID,
    backend_url=BACKEND_URL,
    storage_dir=STORAGE_DIR,
    max_concurrent_downloads=int(os.environ.get("MAX_CONCURRENT_DOWNLOADS", "5")),
    validation_timeout_seconds=float(os.environ.get("VALIDATION_TIMEOUT_SECONDS", "300")),
    reconciliation_list_timeout_seconds=float(
        os.environ.get("RECONCILIATION_LIST_TIMEOUT_SECONDS", "300")
    ),
    inference_timeout_seconds=float(os.environ.get("COMFYUI_TIMEOUT_SECONDS", "3600")),
)

client = select_client(LLM_ENGINES, ENGINE, runtime_config)

app = FastAPI(
    title="Unified LLM Worker",
    lifespan=build_lifespan(
        client,
        reconciliation=lambda: reconciliation_loop(
            provider_id=PROVIDER_ID,
            backend_url=BACKEND_URL,
            interval_seconds=RECONCILIATION_INTERVAL_SECONDS,
            startup_delay_seconds=RECONCILIATION_STARTUP_DELAY_SECONDS,
        ),
        auto_discovery=lambda: auto_discovery_loop(
            provider_id=PROVIDER_ID,
            provider_type=ENGINE,
            backend_url=BACKEND_URL,
            # Without this the loop sends the default `worker_type="image"`
            # (background.py:83), and the backend applies it UNCONDITIONALLY:
            # `provider_service` writes `worker_type` on every heartbeat whose
            # value differs. So this provider's row flipped `llm -> image` every
            # 60 seconds, which removed it from the LLM sections of Settings and
            # Providers, made it eligible for IMAGE dispatch — where it is handed
            # `{"messages": []}` and returns a paid 400 — and then flipped back
            # 60 seconds later. The image worker passes `"image"` explicitly for
            # the same reason.
            worker_type="llm",
            # The shared, pooled client. Without it the loop falls back to
            # building an `httpx.AsyncClient` per heartbeat, which is the
            # fallback inside `auto_discovery_loop` and the reason the shared
            # client exists.
            http_client=get_http_client(),
        ),
    ),
)

attach_provider_routes(app, client)

log_startup_info(
    PROVIDER_ID,
    ENGINE,
    BACKEND_URL,
    extra_vars={
        "MAX_CONCURRENT_DOWNLOADS": runtime_config["max_concurrent_downloads"],
        "RECONCILIATION_INTERVAL_SECONDS": RECONCILIATION_INTERVAL_SECONDS,
        "RECONCILIATION_STARTUP_DELAY_SECONDS": RECONCILIATION_STARTUP_DELAY_SECONDS,
        "STORAGE_DIR": STORAGE_DIR,
        "VALID_ENGINES": valid_engines,
    },
)
