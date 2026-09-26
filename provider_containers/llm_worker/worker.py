import os
from fastapi import FastAPI
from contextlib import asynccontextmanager

from provider_core.router import attach_provider_routes
from provider_core.logging import get_logger

# Configure logging
logger = get_logger("provider_core.llm_worker")

# Read environment configuration
PROVIDER_ID = os.environ.get("PROVIDER_ID", "local-dev")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8002")
# `.strip()` for the same reason as image_worker/worker.py: a bare `ENGINE=` in an
# env file yields "", which matched no branch below and raised at IMPORT, before
# uvicorn bound. Unset or whitespace-only takes the default.
ENGINE = (os.environ.get("ENGINE") or "openai_compat").strip().lower() or "openai_compat"

# Same names and defaults as image_worker/worker.py, read from the same env knobs.
RECONCILIATION_INTERVAL_SECONDS = int(os.environ.get("RECONCILIATION_INTERVAL_SECONDS", "7200"))
RECONCILIATION_STARTUP_DELAY_SECONDS = int(os.environ.get("RECONCILIATION_STARTUP_DELAY_SECONDS", "130"))

# Runtime config dict (the image_worker pattern)
runtime_config = {
    "provider_id": PROVIDER_ID,
    "backend_url": BACKEND_URL,
    "storage_dir": "/data",
}

# Initialize appropriate engine client
if ENGINE == "openai_compat":
    from llm_worker.engines.openai_compat.client import OpenAICompatProviderClient
    client = OpenAICompatProviderClient(provider_id=PROVIDER_ID, runtime_config=runtime_config)
elif ENGINE == "anthropic":
    from llm_worker.engines.anthropic.client import AnthropicProviderClient
    client = AnthropicProviderClient(provider_id=PROVIDER_ID, runtime_config=runtime_config)
elif ENGINE == "google":
    from llm_worker.engines.google.client import GoogleProviderClient
    client = GoogleProviderClient(provider_id=PROVIDER_ID, runtime_config=runtime_config)
elif ENGINE == "modal":
    from llm_worker.engines.modal.client import VLLMModalProviderClient
    client = VLLMModalProviderClient(provider_id=PROVIDER_ID, runtime_config=runtime_config)
else:
    raise ValueError(
        f"Unknown ENGINE: {ENGINE!r}. "
        f"Valid values: openai_compat, anthropic, google, modal."
    )


_background_tasks: list = []

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup
    from provider_core.background import auto_discovery_loop, reconciliation_loop
    from provider_core.http_client import get_http_client, close_http_client
    import asyncio

    logger.info(f"Starting LLM Worker (engine={ENGINE}, provider={PROVIDER_ID})")

    # Start auto-discovery for this provider
    if PROVIDER_ID:
        _background_tasks.append(
            asyncio.create_task(
                auto_discovery_loop(
                    provider_id=PROVIDER_ID,
                    provider_type="modal_llm" if ENGINE == "modal" else ENGINE,
                    backend_url=BACKEND_URL,
                    interval_seconds=60,
                    worker_type="llm",
                    http_client=get_http_client(),
                )
            )
        )

        # Reconciliation, which this worker was missing. image_worker/worker.py
        # starts one in its lifespan; the LLM twin only ever started
        # auto_discovery_loop, so a `modal` LLM provider — the only engine with
        # storage, and the only one whose client implements
        # run_reconciliation with download/list/validate/delete callbacks — was
        # never asked to reconcile at all. Its volume drifted out of the database
        # silently, with no error anywhere: the loop is the only thing that
        # triggers it, and nothing triggered it.
        _background_tasks.append(
            asyncio.create_task(
                reconciliation_loop(
                    PROVIDER_ID,
                    BACKEND_URL,
                    interval_seconds=RECONCILIATION_INTERVAL_SECONDS,
                    startup_delay_seconds=RECONCILIATION_STARTUP_DELAY_SECONDS,
                    http_client=get_http_client(),
                )
            )
        )

    try:
        yield
    finally:
        # Teardown
        logger.info("Shutting down LLM Worker")
        for task in _background_tasks:
            task.cancel()
        if _background_tasks:
            await asyncio.gather(*_background_tasks, return_exceptions=True)
        _background_tasks.clear()
        if hasattr(client, "close"):
            await client.close()
        await close_http_client()


app = FastAPI(title="Unified LLM Worker", lifespan=lifespan)

# Register routes using the shared provider router
attach_provider_routes(app, client)
