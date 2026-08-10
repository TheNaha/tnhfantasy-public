"""
Unified Image Worker
This service receives HTTP requests and routes them to the appropriate engine 
based on the ENGINE environment variable.
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
from provider_core.http_client import get_http_client, close_http_client

ENGINE = os.getenv("ENGINE", "modal").lower()
PROVIDER_ID = os.getenv("PROVIDER_ID", f"{ENGINE}-worker")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# Worker settings
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "5"))
VALIDATION_TIMEOUT_SECONDS = float(os.getenv("VALIDATION_TIMEOUT_SECONDS", "300"))
RECONCILIATION_LIST_TIMEOUT_SECONDS = float(os.getenv("RECONCILIATION_LIST_TIMEOUT_SECONDS", "3600"))
RECONCILIATION_INTERVAL_SECONDS = int(os.getenv("RECONCILIATION_INTERVAL_SECONDS", "7200"))
RECONCILIATION_STARTUP_DELAY_SECONDS = int(os.getenv("RECONCILIATION_STARTUP_DELAY_SECONDS", "130"))
INFERENCE_TIMEOUT_SECONDS = float(os.getenv("INFERENCE_TIMEOUT_SECONDS", "3600"))

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
    log_startup_info(
        provider_id=PROVIDER_ID,
        provider_type=ENGINE,
        backend_url=BACKEND_URL,
        extra_vars={"ENGINE": ENGINE},
    )

    _background_tasks.append(
        asyncio.create_task(
            reconciliation_loop(
                PROVIDER_ID,
                BACKEND_URL,
                interval_seconds=runtime_config["reconciliation_interval_seconds"],
                startup_delay_seconds=runtime_config["reconciliation_startup_delay_seconds"],
                http_client=get_http_client(),
            )
        )
    )
    
    _background_tasks.append(
        asyncio.create_task(
            auto_discovery_loop(
                provider_id=PROVIDER_ID,
                provider_type=ENGINE,
                backend_url=BACKEND_URL,
                http_client=get_http_client(),
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
        if hasattr(client, "close"):
            try:
                await client.close()
            except Exception:
                pass
        await close_http_client()

app = FastAPI(title="Unified Image Worker", lifespan=lifespan)

if ENGINE == "modal":
    from image_worker.engines.modal.client import ModalProviderClient
    client = ModalProviderClient(runtime_config=runtime_config)
elif ENGINE == "beam":
    from image_worker.engines.beam.client import BeamProviderClient
    client = BeamProviderClient(runtime_config=runtime_config)
elif ENGINE == "direct_url":
    from image_worker.engines.direct_url.client import DirectUrlProviderClient
    client = DirectUrlProviderClient(runtime_config=runtime_config)
else:
    raise ValueError(f"Unknown ENGINE: {ENGINE}")

attach_provider_routes(app, client)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
