# FastAPI Main Application
#
# STARTUP SEQUENCE (lifespan function):
#   1. Initialize SQLite database and run schema migrations
#   2. Load load-balancer state from DB
#   3. Start the async job queue (worker pool)
#   4. Recover PENDING/RUNNING jobs from DB (handles server restarts)
#   5. Start background scheduler (periodic vacuum, reconciliation, etc.)
#   6. Mount Socket.IO ASGI sub-app on /socket.io for WebSocket upgrades
#
# REQUEST FLOW (simplified):
#   Client → POST /api/jobs → jobs.py → JobService.create_job → job_queue.enqueue
#     → Worker coroutine picks job → _process_job() → _call_provider()
#       → Modal/Beam worker HTTP/WS → images returned → ImageService.save()
#       → job.status = COMPLETED → WebSocket event → frontend gallery refresh
#
# RETRY STRATEGY (for provider calls):
#   Uses tenacity with exponential back-off (base 1 s, max 60 s).
#   Non-retryable errors (e.g. 400 Bad Request from provider) bypass retries.
import os
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI

# Import logging config early to suppress noisy loggers before they initialize
import infrastructure.logging  # noqa: F401

from api.app_setup import configure_app
from services.job_runner import execute_job
from api.lifecycle import (
    requeue_inflight_jobs_for_shutdown as _requeue_inflight_jobs_for_shutdown,
    shutdown_application,
    startup_application,
)
from services.provider_client import call_provider as _call_provider
from config import (
    get_job_timeout,
    get_job_max_retries,
    get_job_retry_base_delay,
    get_job_retry_max_delay
)
from api.deps import get_session_context
from services.job_queue import job_queue

# Import routers
from api.routes.websocket import ws_manager

# Structured logging - use structlog for consistent output
from infrastructure.logging import get_logger

# Logger for this module
logger = get_logger("main")


async def _process_image_background(image_path: str, job_id: str):
    """
    Process image in background (generate thumbnails + blurhash).
    Runs asynchronously after job is marked as completed.
    """
    try:
        from infrastructure.image_processor import process_image as img_process
        img_result = img_process(image_path, save_metadata=True)
        logger.debug("thumbnails_generated", job_id=job_id, 
                    thumbnails=list(img_result['thumbnails'].keys()))
        
        # Emit event that image processing is complete
        from core.events import emit_job_event, EventType
        await emit_job_event(EventType.JOB_PROGRESS, {
            "id": job_id,
            "message": "Thumbnails generated",
            "images_processed": True
        })
    except Exception as e:
        logger.warning("image_processing_failed", job_id=job_id, path=image_path, error=str(e))


async def process_job(job_id: str, preferred_provider_id: Optional[str] = None):
    """Thin wrapper that preserves stable patch points for tests and lifecycle wiring."""
    await execute_job(
        job_id,
        preferred_provider_id=preferred_provider_id,
        session_context_manager=get_session_context,
        call_provider_fn=_call_provider,
        process_image_background_fn=_process_image_background,
        get_timeout_fn=get_job_timeout,
        get_max_retries_fn=get_job_max_retries,
        get_retry_base_delay_fn=get_job_retry_base_delay,
        get_retry_max_delay_fn=get_job_retry_max_delay,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.
    Runs on startup and shutdown.
    """
    lifecycle_tasks = await startup_application(process_job, ws_manager)
    
    yield

    await shutdown_application(
        ws_manager,
        lifecycle_tasks["provider_monitor_task"],
        lifecycle_tasks["broadcast_task"],
    )


# Create FastAPI app
app = FastAPI(
    title="ComfyUI Modal Stack - Backend V2",
    description="Refactored backend with SQLite, event-driven SSE, and clean architecture",
    version="2.0.0",
    lifespan=lifespan,
)


configure_app(app)
