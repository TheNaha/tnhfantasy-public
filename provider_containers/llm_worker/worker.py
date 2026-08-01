import os
import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager

from provider_core.router import attach_provider_routes
from provider_core.logging import get_logger

# Configure logging
logger = get_logger("provider_core.llm_worker")

# Read environment configuration
PROVIDER_ID = os.environ.get("PROVIDER_ID", "local-dev")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8002")
ENGINE = os.environ.get("ENGINE", "openai_compat")

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
    raise ValueError(f"Unknown ENGINE: {ENGINE}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup
    from provider_core.background import auto_discovery_loop
    import asyncio

    logger.info(f"Starting LLM Worker (engine={ENGINE}, provider={PROVIDER_ID})")

    # Start auto-discovery for this provider
    if PROVIDER_ID:
        asyncio.create_task(
            auto_discovery_loop(
                provider_id=PROVIDER_ID,
                provider_type="llm",
                backend_url=BACKEND_URL,
                interval_seconds=60,
            )
        )

    yield
    # Teardown
    logger.info("Shutting down LLM Worker")
    if hasattr(client, "close"):
        await client.close()


app = FastAPI(title="Unified LLM Worker", lifespan=lifespan)

# Register routes using the shared provider router
attach_provider_routes(app, client)
