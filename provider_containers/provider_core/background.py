"""
Background task utilities for provider workers.
Includes reconciliation loop and startup helpers.
"""

import asyncio
import os
import socket
import traceback
from typing import Any, Callable, Coroutine, Optional, Set
from .logging import get_logger

logger = get_logger("provider_core.background")

# Upper bound on concurrently retained fire-and-forget tasks per worker.
#
# `asyncio.create_task` alone keeps NO reference: the task stays alive only
# because the event loop holds a weak reference to it, so the loop is free to
# collect a multi-GB download mid-flight and its only outcome is a logger.error
# in `done`. Retaining the task fixes the collection; the bound keeps the
# retaining set from becoming its own leak if a caller queues work faster than
# it drains.
try:
    MAX_BACKGROUND_TASKS = max(1, int(os.getenv("PROVIDER_MAX_BACKGROUND_TASKS", "16")))
except ValueError:
    MAX_BACKGROUND_TASKS = 16


class BackgroundTaskLimitExceeded(RuntimeError):
    """Raised instead of spawning when too many background tasks are in flight."""


def spawn_background_task(
    coro: Coroutine[Any, Any, Any],
    *,
    tasks: Set[asyncio.Task],
    name: str,
    max_pending: int = MAX_BACKGROUND_TASKS,
    on_done: Optional[Callable[[asyncio.Task], None]] = None,
) -> asyncio.Task:
    """Create a task, retain it in ``tasks``, and release it when it finishes.

    The one correct fire-and-forget shape in this repo; every caller should use
    it rather than a bare ``create_task``. ``tasks`` is the owning set — pass a
    long-lived one (a client instance) so the reference outlives the request.

    Raises :class:`BackgroundTaskLimitExceeded` (without scheduling ``coro``,
    which the caller must then close) when ``tasks`` is already at
    ``max_pending``.
    """
    if len(tasks) >= max_pending:
        coro.close()
        raise BackgroundTaskLimitExceeded(
            f"refusing to start background task {name!r}: {len(tasks)} already in flight "
            f"(max_pending={max_pending})"
        )

    task = asyncio.create_task(coro, name=name)
    tasks.add(task)

    def _release(finished: asyncio.Task) -> None:
        tasks.discard(finished)
        if on_done is not None:
            on_done(finished)
        if finished.cancelled():
            logger.warning(f"Background task cancelled: {name}")
            return
        exc = finished.exception()
        if exc is not None:
            logger.error(f"Background task failed: {name}: {exc}", exc_info=exc)

    task.add_done_callback(_release)
    return task



async def auto_discovery_loop(
    provider_id: str,
    provider_type: str,
    backend_url: str,
    interval_seconds: int = 60,
    http_client=None,
    worker_type: str = "image",
    capabilities: list[str] | None = None,
):
    """
    Background task to register this provider with the backend.
    Sends a heartbeat to self-discover and maintain availability.
    """
    import httpx
    
    if not provider_id:
        logger.warning("[Auto-Discovery] PROVIDER_ID not set, skipping discovery loop")
        return
        
    logger.info(f"[Auto-Discovery] Starting loop for provider: {provider_id} ({provider_type})")
    discovery_url = f"{backend_url}/api/v2/providers/discovery"
    
    # Try to determine internal hostname or IP for the backend to reach us
    hostname = socket.gethostname()
    port = os.getenv("PORT", "8000")
    internal_url = f"http://{hostname}:{port}"
    
    while True:
        try:
            payload = {
                "provider_id": provider_id,
                "provider_type": provider_type,
                "worker_type": worker_type,
                "status": "online",
                "internal_url": internal_url,
                "hostname": hostname,
                # What this container can actually run, beyond its worker_type.
                # Optional and sent only when set, so an older backend
                # ignores it and an older worker omits it. `worker_type` alone
                # cannot express "a ComfyUI container that speaks rather than
                # draws", which is what this is.
                "capabilities": list(capabilities) if capabilities else None,
            }
            
            discovery_headers = {}
            discovery_token = os.getenv("COMFY_PROVIDER_TOKEN", "").strip()
            if discovery_token:
                discovery_headers["X-Provider-Token"] = discovery_token
            if http_client:
                response = await http_client.post(discovery_url, json=payload, headers=discovery_headers, timeout=30.0)
            else:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(discovery_url, json=payload, headers=discovery_headers)
                    
            if response.status_code in (200, 201):
                pass # Silent success
            else:
                logger.error(f"[Auto-Discovery] Failed to register. Status: {response.status_code}, Body: {response.text[:500]}")
        except Exception as e:
            etype = type(e).__name__
            if etype in ("ReadTimeout", "ConnectTimeout", "PoolTimeout"):
                logger.warning(f"[Auto-Discovery] Transient timeout connecting to backend: {etype}: {e}")
            else:
                logger.error(f"[Auto-Discovery] Error connecting to backend: {etype}: {e}\n{traceback.format_exc()}")
            
        await asyncio.sleep(interval_seconds)


async def reconciliation_loop(
    provider_id: str,
    backend_url: str,
    interval_seconds: int = 7200,  # 2 hours
    startup_delay_seconds: int = 7200, # Do not run immediately on startup to save compute
    http_client=None,
):
    """
    Background task to trigger reconciliation periodically.
    
    Args:
        provider_id: Provider identifier
        backend_url: Backend API base URL
        interval_seconds: Seconds between reconciliation attempts (default: 2 hours)
        startup_delay_seconds: Initial delay before first reconciliation
        http_client: Optional shared HTTP client
    """
    import httpx
    
    if not provider_id:
        logger.warning("[Worker Reconciliation] PROVIDER_ID not set, skipping reconciliation loop")
        return
    
    logger.info(f"[Worker Reconciliation] Starting loop for provider: {provider_id}")
    logger.info(f"[Worker Reconciliation] Backend URL: {backend_url}")
    
    await asyncio.sleep(startup_delay_seconds)
    
    while True:
        try:
            reconcile_url = f"{backend_url}/api/v2/providers/{provider_id}/reconcile?force=true"
            logger.info("[Worker Reconciliation] Attempting to reconcile (force override)...")
            
            if http_client:
                response = await http_client.post(reconcile_url, timeout=30.0)
            else:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(reconcile_url)
            
            status = response.status_code
            logger.info(f"[Worker Reconciliation] Response status: {status}")
            
            if status == 200:
                result = response.json()
                if isinstance(result, dict) and result.get("status") == "already_running":
                    logger.info("[Worker Reconciliation] ℹ Reconciliation already running; skipping duplicate trigger")
                else:
                    logger.info(f"[Worker Reconciliation] ✓ Success: {result}")
            elif status == 409:
                # Backend lock says reconciliation is already in progress.
                logger.info("[Worker Reconciliation] ℹ Reconciliation already in progress (backend lock)")
            else:
                logger.error(f"[Worker Reconciliation] ✗ Failed: {status}")
        
        except Exception as e:
            logger.error(f"[Worker Reconciliation] ✗ Error: {type(e).__name__}: {e}")
        
        logger.info(f"[Worker Reconciliation] Waiting {interval_seconds // 3600}h until next reconciliation...")
        await asyncio.sleep(interval_seconds)


def log_startup_info(
    provider_id: str,
    provider_type: str,
    backend_url: str,
    extra_vars: dict = None,
):
    """
    Log startup information for the worker.
    
    Args:
        provider_id: Provider identifier
        provider_type: Type of provider (modal, beam)
        backend_url: Backend API URL
        extra_vars: Additional environment variables to log
    """
    hf_token = os.getenv("HF_TOKEN", "")
    civitai_token = os.getenv("CIVITAI_TOKEN", "")
    
    logger.info("[Worker] Starting up...")
    logger.info(f"[Worker] PROVIDER_ID: {provider_id}")
    logger.info(f"[Worker] PROVIDER_TYPE: {provider_type}")
    logger.info(f"[Worker] BACKEND_URL: {backend_url}")
    logger.info(f"[Worker] HF_TOKEN: {'✓ Set' if hf_token else '✗ Not set'}")
    logger.info(f"[Worker] CIVITAI_TOKEN: {'✓ Set' if civitai_token else '✗ Not set'}")
    
    if extra_vars:
        for key, value in extra_vars.items():
            if value:
                # Mask sensitive values
                if "TOKEN" in key.upper() or "SECRET" in key.upper() or "KEY" in key.upper():
                    logger.info(f"[Worker] {key}: ✓ Set")
                else:
                    logger.info(f"[Worker] {key}: {value}")
            else:
                logger.info(f"[Worker] {key}: ✗ Not set")
    
    logger.info("[Worker] Startup complete")


class JobCancellationTracker:
    """
    Track cancelled and active jobs for graceful cancellation.
    
    Thread-safe tracking of job states for cancellation support.
    """
    
    def __init__(self):
        self._cancelled_jobs: set = set()
        self._active_jobs: dict = {}
        self._lock = asyncio.Lock()
    
    async def start_job(self, job_id: str):
        """Mark a job as active."""
        if job_id:
            async with self._lock:
                self._active_jobs[job_id] = True
    
    async def end_job(self, job_id: str):
        """Mark a job as completed and clean up."""
        if job_id:
            async with self._lock:
                self._active_jobs.pop(job_id, None)
                self._cancelled_jobs.discard(job_id)
    
    async def cancel_job(self, job_id: str) -> bool:
        """
        Request cancellation of a job.
        
        Returns:
            True if job was active and cancelled, False if not found
        """
        async with self._lock:
            if job_id in self._active_jobs:
                self._cancelled_jobs.add(job_id)
                return True
            return False
    
    async def is_cancelled(self, job_id: str) -> bool:
        """Check if a job has been cancelled."""
        if not job_id:
            return False
        async with self._lock:
            return job_id in self._cancelled_jobs
    
    async def is_active(self, job_id: str) -> bool:
        """Check if a job is currently active."""
        if not job_id:
            return False
        async with self._lock:
            return job_id in self._active_jobs


# Global job tracker
_job_tracker: Optional[JobCancellationTracker] = None


def get_job_tracker() -> JobCancellationTracker:
    """Get or create the global job tracker."""
    global _job_tracker
    if _job_tracker is None:
        _job_tracker = JobCancellationTracker()
    return _job_tracker
