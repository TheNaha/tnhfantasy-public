"""
Modal Provider Worker - HTTP Wrapper
This service receives HTTP requests and calls Modal functions using containerized credentials.

Refactored to use shared provider_core package for common functionality.
"""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

import sys
sys.path.insert(0, "/app")

from provider_core import (
    attach_provider_routes,
    log_startup_info,
    reconciliation_loop,
    auto_discovery_loop,
)
from client import ModalProviderClient, PROVIDER_ID, BACKEND_URL, MODAL_USERNAME, MODAL_APP_NAME

# Worker settings
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "5"))
VALIDATION_TIMEOUT_SECONDS = float(os.getenv("VALIDATION_TIMEOUT_SECONDS", "300"))
RECONCILIATION_LIST_TIMEOUT_SECONDS = float(os.getenv("RECONCILIATION_LIST_TIMEOUT_SECONDS", "45"))
RECONCILIATION_INTERVAL_SECONDS = int(os.getenv("RECONCILIATION_INTERVAL_SECONDS", "7200"))
RECONCILIATION_STARTUP_DELAY_SECONDS = int(os.getenv("RECONCILIATION_STARTUP_DELAY_SECONDS", "130"))
INFERENCE_TIMEOUT_SECONDS = float(os.getenv("INFERENCE_TIMEOUT_SECONDS", "3600"))

# Runtime config
runtime_config = {
    "max_concurrent_downloads": MAX_CONCURRENT_DOWNLOADS,
    "validation_timeout_seconds": VALIDATION_TIMEOUT_SECONDS,
    "reconciliation_list_timeout_seconds": RECONCILIATION_LIST_TIMEOUT_SECONDS,
    "reconciliation_interval_seconds": RECONCILIATION_INTERVAL_SECONDS,
    "reconciliation_startup_delay_seconds": RECONCILIATION_STARTUP_DELAY_SECONDS,
    "inference_timeout_seconds": INFERENCE_TIMEOUT_SECONDS,
}

_background_tasks: list[asyncio.Task] = []

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup and shutdown hooks for the worker."""
    log_startup_info(
        provider_id=PROVIDER_ID,
        provider_type="modal",
        backend_url=BACKEND_URL,
        extra_vars={"MODAL_USERNAME": MODAL_USERNAME, "MODAL_APP_NAME": MODAL_APP_NAME},
    )

    _background_tasks.append(
        asyncio.create_task(
            reconciliation_loop(
                PROVIDER_ID,
                BACKEND_URL,
                interval_seconds=int(runtime_config.get("reconciliation_interval_seconds") or RECONCILIATION_INTERVAL_SECONDS),
                startup_delay_seconds=int(runtime_config.get("reconciliation_startup_delay_seconds") or RECONCILIATION_STARTUP_DELAY_SECONDS),
            )
        )
    )
    
    _background_tasks.append(
        asyncio.create_task(
            auto_discovery_loop(
                provider_id=PROVIDER_ID,
                provider_type="modal",
                backend_url=BACKEND_URL,
            )
        )
    )

    try:
        yield
    finally:
        for task in _background_tasks:
            task.cancel()
        if _background_tasks:
            await asyncio.gather(*_background_tasks, return_exceptions=True)
        _background_tasks.clear()

app = FastAPI(title="Modal Provider Worker", lifespan=lifespan)

# Attach unified provider routes
modal_client = ModalProviderClient(runtime_config=runtime_config)
attach_provider_routes(app, modal_client)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
