# FastAPI Main Application
import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)
import logging

# Import logging config early to suppress noisy loggers before they initialize
import infrastructure.logging  # noqa: F401

from config import (
    settings, 
    get_job_timeout,
    get_job_max_retries,
    get_job_retry_base_delay,
    get_job_retry_max_delay
)
from infrastructure.database import create_db_and_tables, get_session
from infrastructure.http_client import get_http_client, close_http_client, get_streaming_client
from infrastructure.scheduler import (
    start_scheduler, 
    stop_scheduler, 
    schedule_vacuum
)
from services.job_queue import job_queue
from services.job_service import JobService
from services.load_balancer import LoadBalancer
from services.provider_service import ProviderService
from core.entities import JobStatus, Provider
from core.exceptions import ComfyError, NotFoundError, ValidationError

# Import routers
from api.routes import jobs, providers, health, files, downloads, settings as settings_routes, statistics, generation
from api.routes import models_v2, prompts, collections
from api.routes import worker_ws, kaggle  # External worker support
from api.routes.websocket import socket_app, ws_manager, sio

# Structured logging - use structlog for consistent output
from infrastructure.logging import get_logger

# Logger for this module
logger = get_logger("main")


class ProviderCallError(Exception):
    """Raised when a provider call fails and may be retried."""
    def __init__(self, message: str, provider_id: str, is_retryable: bool = True):
        super().__init__(message)
        self.provider_id = provider_id
        self.is_retryable = is_retryable


class JobTimeoutError(Exception):
    """Raised when a job exceeds its timeout."""
    pass


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


async def _call_provider(
    worker_url: str,
    workflow: dict,
    job_id: str,
    job_service: JobService,
    total_nodes: int,
    timeout: float,
    use_snapshot: bool = False
) -> dict:
    """
    Call the provider worker with the workflow.
    Returns the final result on success, raises ProviderCallError on failure.
    
    This function is isolated to be wrapped with retry logic.
    """
    import httpx
    
    async with get_streaming_client(timeout=timeout) as client:
        try:
            async with client.stream(
                "POST",
                f"{worker_url}/inference",
                json={"workflow": workflow, "use_snapshot": use_snapshot, "job_id": job_id},
                timeout=timeout
            ) as response:

                if response.status_code == 200:
                    # Parse streaming NDJSON response
                    final_result = None
                    buffer = ""
                    executed_nodes = set()
                    
                    async for chunk in response.aiter_bytes():
                        buffer += chunk.decode('utf-8')
                        
                        # Process complete lines
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            if line.strip():
                                try:
                                    update = json.loads(line)
                                    status = update.get("status")
                                    
                                    if status == "progress":
                                        val = update.get("value", 0)
                                        max_val = update.get("max", 1)
                                        percent = int((val / max_val) * 100) if max_val > 0 else 0
                                        overall = int((len(executed_nodes) / total_nodes) * 100) if total_nodes > 0 else 0
                                        await job_service.update_job(
                                            job_id,
                                            progress=percent,
                                            overall_progress=overall,
                                            message=f"Rendering: {percent}%"
                                        )
                                    elif status == "executing":
                                        node_id = update.get("node")
                                        if node_id:
                                            executed_nodes.add(node_id)
                                        
                                        # Calculate progress based on executed nodes vs total
                                        overall = int((len(executed_nodes) / total_nodes) * 100) if total_nodes > 0 else 0
                                        await job_service.update_job(
                                            job_id, 
                                            overall_progress=overall,
                                            message=f"Executing node {len(executed_nodes)}/{total_nodes}..."
                                        )

                                    elif status == "execution_cached":
                                        nodes = update.get("nodes", [])
                                        for node in nodes:
                                            executed_nodes.add(node)
                                        
                                        overall = int((len(executed_nodes) / total_nodes) * 100) if total_nodes > 0 else 0
                                        await job_service.update_job(
                                            job_id,
                                            overall_progress=overall,
                                            message=f"Restored {len(nodes)} cached nodes..."
                                        )
                                        
                                    elif status == "queued":
                                        await job_service.update_job(
                                            job_id,
                                            message="Queued in ComfyUI..."
                                        )
                                        
                                    elif status == "success":
                                        final_result = update
                                        
                                    elif status == "error":
                                        raise ProviderCallError(
                                            update.get("message", "Unknown worker error"),
                                            provider_id="",
                                            is_retryable=False  # Application errors shouldn't be retried
                                        )
                                        
                                except json.JSONDecodeError as jde:
                                    logger.warning("job_parse_error", job_id=job_id, line_length=len(line), error=str(jde))
                    
                    if final_result:
                        return final_result
                    else:
                        raise ProviderCallError(
                            "No success response received from worker",
                            provider_id="",
                            is_retryable=True
                        )
                else:
                    error_text = await response.aread()
                    raise ProviderCallError(
                        f"Worker returned {response.status_code}: {error_text.decode()}",
                        provider_id="",
                        is_retryable=response.status_code >= 500  # Only retry server errors
                    )
                    
        except httpx.TimeoutException:
            raise JobTimeoutError(f"Job timed out after {timeout}s")
        except httpx.ConnectError as e:
            raise ProviderCallError(f"Failed to connect to worker: {e}", provider_id="", is_retryable=True)
        except httpx.HTTPError as e:
            raise ProviderCallError(f"HTTP error: {e}", provider_id="", is_retryable=True)


async def process_job(job_id: str, preferred_provider_id: Optional[str] = None):
    """
    Process a job by sending it to a provider.
    This is the callback used by job_queue.
    
    Features:
    - Automatic retry with exponential backoff on transient failures
    - Timeout handling to prevent stuck jobs
    - Fallback to alternative providers on repeated failures
    - HTTP connection pooling for efficiency
    """
    session = next(get_session())
    try:
        job_service = JobService(session)
        provider_service = ProviderService(session)
        
        # Get load balancing strategy from config
        lb_config = provider_service.get_load_balancing_config()
        strategy = lb_config.strategy if lb_config else "round-robin"
        load_balancer = LoadBalancer(session, strategy=strategy)
        
        # Get the job
        try:
            job = await job_service.get_job(job_id)
        except NotFoundError:
            logger.warning("job_not_found", job_id=job_id)
            return
        
        # Skip if not pending
        if job.status != JobStatus.PENDING:
            logger.debug("job_not_pending", job_id=job_id, status=job.status)
            return
        
        # Get configuration
        timeout = get_job_timeout()
        max_retries = get_job_max_retries()
        base_delay = get_job_retry_base_delay()
        max_delay = get_job_retry_max_delay()
        
        # Track providers we've exhausted (failed all retries)
        exhausted_providers = set()
        current_provider = None
        retry_count = 0  # Retries for current provider
        
        while True:
            # Get a new provider only if we don't have one or current one is exhausted
            if current_provider is None or current_provider.id in exhausted_providers:
                # Get provider from load balancer, excluding exhausted ones
                provider = load_balancer.get_next_provider(preferred_provider_id)
                
                # Skip exhausted providers
                while provider and provider.id in exhausted_providers:
                    provider = load_balancer.get_fallback_provider(provider.id)
                
                if not provider:
                    # No more providers to try
                    if not exhausted_providers:
                        logger.warning("no_providers", job_id=job_id)
                        await job_service.update_job(
                            job_id,
                            status=JobStatus.FAILED,
                            error="No available providers"
                        )
                    else:
                        logger.warning("providers_exhausted", job_id=job_id, tried=list(exhausted_providers))
                        await job_service.update_job(
                            job_id,
                            status=JobStatus.FAILED,
                            error=f"All providers failed: {', '.join(exhausted_providers)}"
                        )
                    return
                
                current_provider = provider
                retry_count = 0  # Reset retry count for new provider
            
            attempt = retry_count + 1
            logger.info("job_processing", job_id=job_id, provider=current_provider.id, attempt=attempt, max_attempts=max_retries + 1)
            
            # Update job status to running
            await job_service.update_job(
                job_id,
                status=JobStatus.RUNNING,
                provider_id=current_provider.id,
                message=f"Starting on {current_provider.id}..."
            )
            
            # Get worker URL from container config
            container_config = current_provider.container_config or {}
            if not container_config:
                await job_service.update_job(
                    job_id,
                    status=JobStatus.FAILED,
                    error=f"Provider {current_provider.id} has no container config"
                )
                return
            
            container_name = f"comfy-provider-{current_provider.id}"
            worker_url = f"http://{container_name}:8000"
            total_nodes = len(job.workflow) if isinstance(job.workflow, dict) else 0
            
            # Get memory snapshot setting from provider config
            # This value is persisted in Provider.config JSON field (modifiable via UI)
            # Default: False (disabled) unless explicitly enabled per-provider
            provider_config = current_provider.config or {}
            use_snapshot = provider_config.get("enable_memory_snapshot", False)
            
            try:
                # Call provider with timeout
                final_result = await asyncio.wait_for(
                    _call_provider(
                        worker_url=worker_url,
                        workflow=job.workflow,
                        job_id=job_id,
                        job_service=job_service,
                        total_nodes=total_nodes,
                        timeout=timeout,
                        use_snapshot=use_snapshot
                    ),
                    timeout=timeout + 10  # Extra buffer for cleanup
                )

                
                # Success! Process the result
                images = final_result.get("images", [])
                outputs = []
                
                # Use image processor to determine output path logic (date-based hierarchy)
                # This ensures consistent directory structure across the app
                from infrastructure.image_processor import get_output_path, save_image_with_metadata
                
                # Default output directory
                base_output_dir = "/app/output"
                
                # Get the target date-based directory using the processor
                # If subfolder is provided by worker (which shouldn't happen with standard flow but good for safety), 
                # we respect it, otherwise we use the date-based path from image_processor logic
                # Note: valid ComfyUI workers might return subfolders if they originated from a specific LoadImage directory
                # but typically for SaveImage, ComfyUI handles the path. 
                # Our image_processor.get_output_path handles the hierarchy logic.
                final_output_dir = get_output_path(base_output_dir)

                for img in images:
                    filename = img.get("filename", "output.png")
                    subfolder = img.get("subfolder", "")
                    
                    # Handle base64 encoded images from worker
                    if img.get("_base64_encoded") and img.get("data"):
                        import base64
                        from PIL import Image
                        import io
                        
                        image_data = base64.b64decode(img["data"])
                        
                        # Respect subfolder if provided (unlikely now based on plan, but robust)
                        if subfolder:
                            target_dir = os.path.join(base_output_dir, subfolder)
                            os.makedirs(target_dir, exist_ok=True)
                        else:
                            target_dir = final_output_dir
                        
                        output_path = os.path.join(target_dir, filename)
                        
                        # Prepare metadata for embedding
                        full_metadata = {
                            "job_id": job_id,
                            "filename": filename,
                            "provider": current_provider.id
                        }
                        if job.metadata_:
                            # Add relevant job metadata
                            for key in ["prompt", "negativePrompt", "seed", "steps", "cfg", "sampler", "scheduler", "width", "height", "checkpoint", "loras", "workflow"]:
                                if key in job.metadata_:
                                    full_metadata[key] = job.metadata_[key]
                        
                        # Save image WITH embedded metadata
                        try:
                            img_obj = Image.open(io.BytesIO(image_data))
                            save_image_with_metadata(img_obj, output_path, full_metadata)
                            logger.debug("image_saved_with_metadata", path=output_path, bytes=len(image_data))
                        except Exception as e:
                            logger.error(f"Failed to save image with metadata: {e}, falling back to raw write")
                            with open(output_path, 'wb') as f:
                                f.write(image_data)
                        
                        # Calculate relative subfolder for the API response
                        # The frontend expects 'subfolder' to be relative to the root output dir
                        # e.g. "2025/01/01"
                        rel_subfolder = os.path.relpath(target_dir, base_output_dir).replace("\\", "/")
                        if rel_subfolder == ".": rel_subfolder = ""

                        output = {
                            "type": "image",
                            "filename": filename,
                            "subfolder": rel_subfolder,
                            "path": output_path
                        }
                    else:
                        output = {
                            "type": "image",
                            "filename": filename,
                            "subfolder": subfolder
                        }
                    
                    outputs.append(output)
                
                # Mark job as completed FIRST (don't wait for image processing)
                await job_service.update_job(
                    job_id,
                    status=JobStatus.COMPLETED,
                    outputs=outputs,
                    progress=100,
                    overall_progress=100
                )
                
                load_balancer.report_success(current_provider.id)
                load_balancer.release_job(current_provider.id)  # Release job slot for least-connections
                logger.info("job_completed", job_id=job_id, outputs=len(outputs))
                
                # Process images in background (thumbnails + blurhash)
                # This doesn't block job completion - runs asynchronously
                for output in outputs:
                    if output.get("path") and output.get("type") == "image":
                        asyncio.create_task(
                            _process_image_background(output["path"], job_id)
                        )
                return  # Success!
                
            except JobTimeoutError as e:
                logger.warning("job_timeout", job_id=job_id, provider=current_provider.id)
                load_balancer.report_failure(current_provider.id)
                retry_count += 1
                
                if retry_count <= max_retries:
                    # Calculate backoff delay and retry same provider
                    delay = min(base_delay * (2 ** (retry_count - 1)), max_delay)
                    logger.info("job_retry", job_id=job_id, delay=delay, attempt=retry_count, provider=current_provider.id)
                    await job_service.update_job(
                        job_id,
                        status=JobStatus.PENDING,
                        message=f"Retrying after timeout (attempt {retry_count + 1})..."
                    )
                    await asyncio.sleep(delay)
                    continue  # Retry same provider
                else:
                    # Max retries exhausted for this provider, try fallback
                    logger.warning("provider_max_retries", job_id=job_id, provider=current_provider.id, retries=retry_count)
                    load_balancer.release_job(current_provider.id)
                    exhausted_providers.add(current_provider.id)
                    continue  # Try next provider
                    
            except ProviderCallError as e:
                logger.warning("provider_error", job_id=job_id, error=str(e))
                load_balancer.report_failure(current_provider.id)
                retry_count += 1
                
                if e.is_retryable and retry_count <= max_retries:
                    delay = min(base_delay * (2 ** (retry_count - 1)), max_delay)
                    logger.info("job_retry", job_id=job_id, delay=delay, attempt=retry_count, provider=current_provider.id)
                    await job_service.update_job(
                        job_id,
                        status=JobStatus.PENDING,
                        message=f"Retrying after error (attempt {retry_count + 1})..."
                    )
                    await asyncio.sleep(delay)
                    continue  # Retry same provider
                else:
                    # Non-retryable error or max retries exhausted
                    load_balancer.release_job(current_provider.id)
                    exhausted_providers.add(current_provider.id)
                    
                    if not e.is_retryable:
                        # Non-retryable error, fail immediately if no other providers
                        logger.warning("provider_non_retryable", job_id=job_id, provider=current_provider.id, error=str(e))
                    
                    continue  # Try next provider (if any)
                    
            except asyncio.TimeoutError:
                logger.error("job_timeout_exceeded", job_id=job_id, timeout=timeout)
                load_balancer.report_failure(current_provider.id)
                load_balancer.release_job(current_provider.id)
                exhausted_providers.add(current_provider.id)
                continue  # Try next provider
                
    except Exception as e:
        logger.error("job_processing_error", job_id=job_id, error=str(e), exc_info=True)
        
        try:
            job_service = JobService(session)
            await job_service.update_job(
                job_id,
                status=JobStatus.FAILED,
                error=str(e)
            )
        except Exception as update_error:
            logger.error("job_update_failed", job_id=job_id, error=str(update_error))
    finally:
        session.close()


async def run_reconciliation_for_all_providers():
    """
    Trigger reconciliation for all enabled containerized providers.
    Called periodically by the scheduler.
    """
    logger.info("reconciliation_periodic")
    
    # Get providers from database
    session = next(get_session())
    try:
        service = ProviderService(session)
        providers_list = await service.list_providers()
        
        # Use pooled HTTP client for efficiency
        http_client = get_http_client()
        
        for provider in providers_list:
            if not provider.get("enabled", True):
                continue
            
            container_config = provider.get("container_config")
            if not container_config:
                continue  # Skip non-containerized providers
            
            provider_id = provider.get("id")
            container_name = f"comfy-provider-{provider_id}"
            worker_url = f"http://{container_name}:8000"
            
            try:
                response = await http_client.post(
                    f"{worker_url}/reconcile",
                    timeout=5.0
                )
                if response.status_code == 200:
                    logger.info("reconciliation_triggered", provider=provider_id)
                else:
                    logger.warning("reconciliation_failed", provider=provider_id, status=response.status_code)
            except Exception as e:
                logger.debug("reconciliation_unreachable", provider=provider_id, error=str(e))
    finally:
        session.close()


async def vacuum_database():
    """
    Run SQLite VACUUM to reclaim disk space and optimize performance.
    Called daily by the scheduler.
    """
    from sqlalchemy import text
    from infrastructure.database import engine
    
    logger.info("vacuum_start")
    try:
        # VACUUM needs to run outside a transaction
        with engine.connect() as conn:
            conn.execute(text("VACUUM"))
            conn.commit()
        logger.info("vacuum_complete")
    except Exception as e:
        logger.error("vacuum_failed", error=str(e))


async def monitor_provider_changes():
    """
    Monitor provider status changes and resize worker pool accordingly.
    Running as a background task.
    """
    from core.events import event_bus, EventType
    from infrastructure.database import get_session_sync
    from infrastructure.repositories import ProviderRepository
    
    logger.info("provider_monitor_start")
    
    # Subscribe to provider status events
    subscription = event_bus.subscribe("provider")
    
    try:
        async for event in subscription:
            if event.type == EventType.PROVIDER_STATUS:
                # Provider status changed (created, updated, deleted)
                # Re-calculate enabled providers
                try:
                    logger.info("provider_status_changed", data=event.data)
                    
                    # Run DB op in thread pool to avoid blocking async loop
                    # (since we're using sync session/repo here for simplicity)
                    def count_enabled_providers():
                        session = get_session_sync()
                        try:
                            repo = ProviderRepository(session)
                            return len(repo.get_enabled())
                        finally:
                            session.close()
                    
                    # Offload DB call
                    enabled_count = await asyncio.to_thread(count_enabled_providers)
                    
                    # Resize worker pool (1 worker per enabled provider)
                    target_workers = max(1, enabled_count)
                    
                    # Only resize if changed
                    if target_workers != job_queue.max_workers:
                        await job_queue.resize(target_workers)
                        
                except Exception as e:
                    logger.error("provider_monitor_error", error=str(e))
    except asyncio.CancelledError:
        logger.info("provider_monitor_stop")
    except Exception as e:
        logger.error("provider_monitor_fatal", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.
    Runs on startup and shutdown.
    """
    # Startup
    logger.info("startup_init", phase="database")
    create_db_and_tables()
    
    logger.info("startup_init", phase="job_processor")
    job_queue.set_processor(process_job)
    
    logger.info("startup_init", phase="gallery_indexer")
    try:
        from services.gallery_indexer import gallery_indexer
        gallery_indexer.start()
    except Exception as e:
        logger.warning("gallery_indexer_not_started", error=str(e))
    
    # Get the number of enabled providers to set worker count dynamically
    # Each provider can only process one job at a time
    logger.info("startup_init", phase="worker_pool")
    try:
        from infrastructure.repositories import ProviderRepository
        from infrastructure.database import get_session_sync
        session = get_session_sync()
        provider_repo = ProviderRepository(session)
        enabled_providers = provider_repo.get_enabled()
        num_workers = max(1, len(enabled_providers))  # At least 1 worker
        job_queue.max_workers = num_workers
        session.close()
        logger.info("worker_pool_configured", providers=len(enabled_providers), workers=num_workers)
    except Exception as e:
        logger.warning("worker_pool_error", error=str(e))
    
    logger.info("startup_init", phase="job_queue")
    await job_queue.start()
    
    # Start provider monitor for auto-scaling
    logger.info("startup_init", phase="provider_monitor")
    provider_monitor_task = asyncio.create_task(monitor_provider_changes())
    
    # Recover pending/stuck jobs from database
    logger.info("startup_init", phase="job_recovery")
    try:
        from infrastructure.database import get_session_sync
        recovery_session = get_session_sync()
        recovery_job_service = JobService(recovery_session)
        recovered, failed = await job_queue.recover_pending_jobs(recovery_job_service)
        recovery_session.close()
    except Exception as e:
        logger.warning("job_recovery_failed", error=str(e))
    
    logger.info("startup_init", phase="scheduler")
    start_scheduler()
    
    # Note: Reconciliation is handled by each worker's own background loop
    # Workers reconcile every 2 hours autonomously
    
    # Schedule daily database vacuum for performance
    schedule_vacuum(
        vacuum_database,
        interval_seconds=86400  # Daily
    )
    
    # Auto-start enabled provider containers
    logger.info("startup_init", phase="containers")
    try:
        from services.container_manager import ContainerManager
        from infrastructure.database import get_session_sync
        from infrastructure.repositories import ProviderRepository
        
        session = get_session_sync()
        try:
            provider_repo = ProviderRepository(session)
            providers = provider_repo.get_all()
            container_manager = ContainerManager()
            
            for provider in providers:
                # Only auto-start if enabled AND has container config
                if provider.enabled and provider.container_config:
                    try:
                        logger.info("container_starting", provider=provider.id)
                        # Get port from container config, default to 8000
                        port = provider.container_config.get('port', 8000)
                        
                        # Build env vars using provider registry (provider-agnostic)
                        from infrastructure.providers import ProviderRegistry
                        env_vars = ProviderRegistry.build_container_env(provider)
                        
                        container_manager.start_container(
                            provider_id=provider.id,
                            provider_type=provider.type,
                            port=port,
                            env_vars=env_vars if env_vars else None
                        )
                        logger.info("container_started", provider=provider.id)
                    except Exception as e:
                        logger.warning("container_start_failed", provider=provider.id, error=str(e))
        finally:
            session.close()
    except Exception as e:
        logger.warning("container_autostart_failed", error=str(e))
    
    # Start WebSocket broadcast listener
    logger.info("startup_init", phase="websocket")
    broadcast_task = asyncio.create_task(ws_manager.start_broadcasting())
    
    logger.info("startup_complete")
    
    yield
    
    # Stop WebSocket broadcaster
    logger.info("shutdown", phase="websocket")
    await ws_manager.stop_broadcasting()
    broadcast_task.cancel()
    try:
        await broadcast_task
    except asyncio.CancelledError:
        pass
        
    # Stop provider monitor
    logger.info("shutdown", phase="provider_monitor")
    provider_monitor_task.cancel()
    try:
        await provider_monitor_task
    except asyncio.CancelledError:
        pass
    
    # Shutdown
    logger.info("shutdown", phase="scheduler")
    stop_scheduler()
    
    logger.info("shutdown", phase="job_queue")
    await job_queue.stop()
    
    logger.info("shutdown", phase="http_client")
    await close_http_client()
    
    logger.info("shutdown_complete")


# Create FastAPI app
app = FastAPI(
    title="ComfyUI Modal Stack - Backend V2",
    description="Refactored backend with SQLite, event-driven SSE, and clean architecture",
    version="2.0.0",
    lifespan=lifespan,
)


# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip compression
app.add_middleware(
    GZipMiddleware,
    minimum_size=settings.gzip_minimum_size
)


# Request logging middleware
import time
from uuid import uuid4
from infrastructure.logging import api_logger

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests with timing and request ID for tracing."""
    request_id = str(uuid4())[:8]
    start_time = time.time()
    
    # Execute request
    response = await call_next(request)
    
    # Calculate duration
    duration_ms = round((time.time() - start_time) * 1000, 2)
    
    # Skip logging for noisy endpoints
    path = request.url.path
    skip_paths = ["/health", "/api/files/events"]
    
    if not any(path.startswith(skip) for skip in skip_paths):
        logger = api_logger()
        logger.info(
            "http_request",
            request_id=request_id,
            method=request.method,
            path=path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
    
    # Add request ID to response headers for tracing
    response.headers["X-Request-ID"] = request_id
    return response

# Exception handlers
@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError):
    return JSONResponse(
        status_code=404,
        content={"error": exc.message, "code": exc.code}
    )


@app.exception_handler(ValidationError)
async def validation_handler(request: Request, exc: ValidationError):
    return JSONResponse(
        status_code=400,
        content={"error": exc.message, "code": exc.code, "field": exc.field}
    )


@app.exception_handler(ComfyError)
async def comfy_error_handler(request: Request, exc: ComfyError):
    return JSONResponse(
        status_code=500,
        content={"error": exc.message, "code": exc.code}
    )


# Include routers
app.include_router(health.router)
app.include_router(jobs.router)
app.include_router(providers.router)
# NOTE: V1 models.router removed - all endpoints migrated to models_v2
app.include_router(files.router)
app.include_router(downloads.router)
app.include_router(settings_routes.router)
app.include_router(statistics.router)
app.include_router(generation.router)
app.include_router(models_v2.router)  # V2 version-aware model API
app.include_router(prompts.router)  # Prompt library API with FTS5 search
app.include_router(collections.router)  # Image collections API
app.include_router(worker_ws.router)  # External worker WebSocket
app.include_router(kaggle.router)  # Kaggle worker script serving

# Mount Socket.IO WebSocket app
# This handles /socket.io/* routes for WebSocket connections
app.mount("/socket.io", socket_app)


# Root redirect
@app.get("/")
async def root():
    return {"message": "ComfyUI Modal Stack Backend V2", "version": "2.0.0"}
