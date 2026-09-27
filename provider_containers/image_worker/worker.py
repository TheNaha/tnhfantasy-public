"""
Unified Image Worker
This service receives HTTP requests and routes them to the appropriate engine
(Modal, Beam, Direct URL, or Remote ComfyUI) for image generation.

The engine registry, the runtime_config builder and the lifespan live in
`provider_core.worker_bootstrap`; this module supplies the image worker's
environment and its two loops. The 17-line `if ENGINE ==` ladder and the
lifespan copy that used to be here were duplicated in `llm_worker/worker.py` and
had drifted — see the module docstring of `provider_core.worker_bootstrap.py`.
"""

import os
from fastapi import FastAPI

from provider_core.router import attach_provider_routes
from provider_core.background import (
    auto_discovery_loop,
    log_startup_info,
    reconciliation_loop,
)
from provider_core.worker_bootstrap import (
    IMAGE_ENGINES,
    build_lifespan,
    build_runtime_config,
    select_client,
)

# Read environment configuration
# `.strip()` and the `or` fallback, not `os.getenv(name, default)`: that default
# only applies when the variable is ABSENT, so a bare `ENGINE=` in an env file
# yields "" — which matched no branch of the old ladder and raised at IMPORT,
# before uvicorn bound.
ENGINE = (os.getenv("ENGINE") or "").strip().lower() or "modal"

# Same reason as ENGINE above, and `provider_id` is not cosmetic: reconciliation
# and auto-discovery register discovered models under it, and
# `provider_container_name(provider.id)` (infrastructure/providers/runtime.py)
# is the name the backend looks for, so an empty value matches no container.
PROVIDER_ID = (os.getenv("PROVIDER_ID") or "").strip() or f"{ENGINE}-worker"
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8002")

# Reconciliation cadence. Module constants rather than runtime_config keys: they
# are read once here and handed to `reconciliation_loop`, not by the client.
RECONCILIATION_INTERVAL_SECONDS = int(os.getenv("RECONCILIATION_INTERVAL_SECONDS", "7200"))
RECONCILIATION_STARTUP_DELAY_SECONDS = int(os.getenv("RECONCILIATION_STARTUP_DELAY_SECONDS", "130"))

# Valid names come from IMAGE_ENGINES, so this list cannot drift from what
# select_client can actually build.
valid_engines = ", ".join(sorted(IMAGE_ENGINES))

STORAGE_DIR = os.getenv("COMFY_MODELS_PATH", "/models")

# Runtime config dict (consumed by provider_core.router + base_client).
# The same seven keys the LLM worker emits — see
# provider_core.worker_bootstrap.RUNTIME_CONFIG_KEYS. The two dicts used to
# disagree silently, because a missing key is a default rather than an error:
# the LLM worker never got `max_concurrent_downloads`, so base_client fell back
# to 2 for every LLM reconciliation.
runtime_config = build_runtime_config(
    provider_id=PROVIDER_ID,
    backend_url=BACKEND_URL,
    storage_dir=STORAGE_DIR,
    max_concurrent_downloads=int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "5")),
    validation_timeout_seconds=float(os.getenv("VALIDATION_TIMEOUT_SECONDS", "300")),
    reconciliation_list_timeout_seconds=float(
        os.getenv("RECONCILIATION_LIST_TIMEOUT_SECONDS", "300")
    ),
    inference_timeout_seconds=float(os.getenv("COMFYUI_TIMEOUT_SECONDS", "3600")),
)

# Built before the app so a bad ENGINE still fails at import, with the same
# message the ladder raised: several tests assert it.
client = select_client(IMAGE_ENGINES, ENGINE, runtime_config)

app = FastAPI(
    title="Unified Image Worker",
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
            storage_dir=STORAGE_DIR,
        ),
    ),
)

attach_provider_routes(app, client)

# No `if __name__ == "__main__":` uvicorn block: `image_worker/Dockerfile` runs
# `python -m uvicorn image_worker.worker:app`, which imports this module under its
# real name, so that block never ran. It was a second, disagreeing owner of
# $PORT — the Dockerfile's CMD was the live one, and it hardcoded 8000 while this
# read $PORT. The Dockerfile is the only owner now, and both its healthcheck and
# its CMD read the same ENV.

log_startup_info(
    PROVIDER_ID,
    ENGINE,
    BACKEND_URL,
    extra_vars={
        "MAX_CONCURRENT_DOWNLOADS": runtime_config["max_concurrent_downloads"],
        "RECONCILIATION_INTERVAL_SECONDS": RECONCILIATION_INTERVAL_SECONDS,
        "RECONCILIATION_STARTUP_DELAY_SECONDS": RECONCILIATION_STARTUP_DELAY_SECONDS,
        "COMFY_MODELS_PATH": STORAGE_DIR,
        "VALID_ENGINES": valid_engines,
    },
)
