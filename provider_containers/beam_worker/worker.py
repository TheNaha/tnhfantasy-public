"""
Beam Provider Worker - HTTP Wrapper with Full Reconciliation
Routes requests to appropriate Beam endpoint (GPU for inference, CPU for storage).

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
    get_http_client,
)
from client import BeamProviderClient, PROVIDER_ID, BACKEND_URL, BEAM_GPU_URL, BEAM_STORAGE_URL, BEAM_GPU_TYPE

# Worker settings
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "5"))
VALIDATION_TIMEOUT_SECONDS = float(os.getenv("VALIDATION_TIMEOUT_SECONDS", "300"))
DOWNLOAD_TIMEOUT_SECONDS = float(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", "1800"))
WS_MAX_SIZE_MB = int(os.getenv("WS_MAX_SIZE_MB", "20"))
WS_OPEN_TIMEOUT = int(os.getenv("WS_OPEN_TIMEOUT", "120"))
RECONCILIATION_INTERVAL_SECONDS = int(os.getenv("RECONCILIATION_INTERVAL_SECONDS", "7200"))
RECONCILIATION_STARTUP_DELAY_SECONDS = int(os.getenv("RECONCILIATION_STARTUP_DELAY_SECONDS", "130"))
INFERENCE_TIMEOUT_SECONDS = float(os.getenv("INFERENCE_TIMEOUT_SECONDS", "3600"))

# Runtime config
runtime_config = {
    "max_concurrent_downloads": MAX_CONCURRENT_DOWNLOADS,
    "validation_timeout_seconds": VALIDATION_TIMEOUT_SECONDS,
    "download_timeout_seconds": DOWNLOAD_TIMEOUT_SECONDS,
    "ws_max_size_mb": WS_MAX_SIZE_MB,
    "ws_open_timeout": WS_OPEN_TIMEOUT,
    "reconciliation_interval_seconds": RECONCILIATION_INTERVAL_SECONDS,
    "reconciliation_startup_delay_seconds": RECONCILIATION_STARTUP_DELAY_SECONDS,
    "inference_timeout_seconds": INFERENCE_TIMEOUT_SECONDS,
}

_background_tasks: list[asyncio.Task] = []

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup and shutdown hooks for the worker."""
    # Ensure HTTP client is initialized
    get_http_client()
    
    log_startup_info(
        provider_id=PROVIDER_ID,
        provider_type="beam",
        backend_url=BACKEND_URL,
        extra_vars={
            "BEAM_GPU_URL": BEAM_GPU_URL,
            "BEAM_STORAGE_URL": BEAM_STORAGE_URL,
            "BEAM_GPU_TYPE": BEAM_GPU_TYPE,
        },
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
                provider_type="beam",
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

app = FastAPI(title="Beam Provider Worker", lifespan=lifespan)

# Attach unified provider routes
beam_client = BeamProviderClient(runtime_config=runtime_config)
attach_provider_routes(app, beam_client)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
