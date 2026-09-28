"""
TTS Worker

A provider container, in the same sense `image_worker` and `llm_worker` are: it
receives HTTP requests from the backend, self-registers by heartbeat so the
backend can route speech jobs to it, and forwards them to a Modal app.

It is a SEPARATE container from the image worker rather than a second app the
image worker forwards to, because the codebase's model is one provider = one
container, and because the image worker's `/health` only checks that
`MODAL_APP_NAME` is set — a shared container would report healthy for both apps
while being entirely blind to the TTS one. Separate containers mean separate
health, separate failure domains, and TTS can be deployed or removed without
touching the image path.

The Modal app it forwards to is also separate, and has its own image. That is
measured, not stylistic: the image worker's cold start is 57.66s on an L4, of
which ~44s is in-container and ~42s of that is ComfyUI's own boot — the heavy
`ultralytics` import and the enumeration of 531 model files on the /mnt/data
volume. The TTS image has neither, and keeps the container warm for 300s rather
than 40s, because it runs seconds of speech and a cold start would dominate.

The shared machinery — the engine registry, the runtime config builder, the
lifespan — lives in `provider_core.worker_bootstrap` for the same reason it does
for the other two workers: a duplicated `if ENGINE ==` ladder drifts.
"""

import os

from fastapi import FastAPI

from provider_core.background import (
    auto_discovery_loop,
    log_startup_info,
    reconciliation_loop,
)
from provider_core.http_client import get_http_client
from provider_core.router import attach_provider_routes
from provider_core.worker_bootstrap import (
    TTS_ENGINES,
    build_lifespan,
    build_runtime_config,
    select_client,
)

# `.strip()` and the `or` fallback, not `os.getenv(name, default)`: that default
# only applies when the variable is ABSENT, so a bare `ENGINE=` in an env file
# yields "" — which matches no branch and raises at IMPORT, before uvicorn binds.
ENGINE = (os.getenv("ENGINE") or "").strip().lower() or "modal"

# Not cosmetic: reconciliation and auto-discovery register discovered models
# under this, and `provider_container_name(provider.id)`
# (infrastructure/providers/runtime.py) is the name the backend looks for, so an
# empty value matches no container.
PROVIDER_ID = (os.getenv("PROVIDER_ID") or "").strip() or f"{ENGINE}-tts-worker"
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8002")

# The capability this container declares. A TTS provider is `worker_type="tts"`
# and serves ONLY speech.
#
# Not `["image", "tts"]`, and the reason matters: `Provider.serves()` is additive,
# so a provider always serves its own `worker_type` and `capabilities` only adds.
# A TTS container cannot run a checkpoint, so it must not be offered image work;
# that is achieved by `worker_type="tts"` rather than by narrowing the list,
# because narrowing is what a UI edit can do by accident.
WORKER_TYPE = "tts"
CAPABILITIES = ["tts"]

RECONCILIATION_INTERVAL_SECONDS = int(os.getenv("RECONCILIATION_INTERVAL_SECONDS", "7200"))
RECONCILIATION_STARTUP_DELAY_SECONDS = int(os.getenv("RECONCILIATION_STARTUP_DELAY_SECONDS", "130"))

valid_engines = ", ".join(sorted(TTS_ENGINES))

STORAGE_DIR = os.getenv("COMFY_MODELS_PATH", "/mnt/data/models")

runtime_config = build_runtime_config(
    provider_id=PROVIDER_ID,
    backend_url=BACKEND_URL,
    storage_dir=STORAGE_DIR,
    max_concurrent_downloads=int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "5")),
    validation_timeout_seconds=float(os.getenv("VALIDATION_TIMEOUT_SECONDS", "300")),
    reconciliation_list_timeout_seconds=float(
        os.getenv("RECONCILIATION_LIST_TIMEOUT_SECONDS", "300")
    ),
    # The TTS app's own timeout is MODAL_TTS_TIMEOUT (1800s), which is generous
    # relative to the image worker's 600s because a batched voice-design run and a
    # long narration batch both legitimately take minutes on a cold container.
    inference_timeout_seconds=float(os.getenv("MODAL_TTS_TIMEOUT", "1800")),
)

# Built before the app so a bad ENGINE still fails at import.
client = select_client(TTS_ENGINES, ENGINE, runtime_config)

app = FastAPI(
    title="TTS Worker",
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
            # Without this the loop sends the default `worker_type="image"`, and
            # the backend applies it unconditionally — so this provider would be
            # registered as an image worker and offered checkpoint jobs it cannot
            # run. This is the same defect the LLM worker had.
            worker_type=WORKER_TYPE,
            capabilities=CAPABILITIES,
            http_client=get_http_client(),
        ),
    ),
)

attach_provider_routes(app, client)

# No `if __name__ == "__main__":` block, for the same reason as the image
# worker: `tts_worker/Dockerfile` runs `python -m uvicorn tts_worker.worker:app`,
# which imports this module under its real name, so that block never ran and was a
# second, disagreeing owner of $PORT.

log_startup_info(
    PROVIDER_ID,
    ENGINE,
    BACKEND_URL,
    extra_vars={
        "WORKER_TYPE": WORKER_TYPE,
        "CAPABILITIES": ",".join(CAPABILITIES),
        "MAX_CONCURRENT_DOWNLOADS": runtime_config["max_concurrent_downloads"],
        "RECONCILIATION_INTERVAL_SECONDS": RECONCILIATION_INTERVAL_SECONDS,
        "RECONCILIATION_STARTUP_DELAY_SECONDS": RECONCILIATION_STARTUP_DELAY_SECONDS,
        "COMFY_MODELS_PATH": STORAGE_DIR,
        "VALID_ENGINES": valid_engines,
    },
)
