"""
Background task utilities for provider workers.
Includes reconciliation loop and startup helpers.
"""

import asyncio
import os
import platform
import socket
import traceback
from typing import Callable, Awaitable, Optional
from .logging import get_logger

logger = get_logger("provider_core.background")


async def auto_discovery_loop(
    provider_id: str,
    provider_type: str,
    backend_url: str,
    interval_seconds: int = 60,
    http_client=None,
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
                "status": "online",
                "internal_url": internal_url,
                "hostname": hostname
            }
            
            if http_client:
                response = await http_client.post(discovery_url, json=payload, timeout=10.0)
            else:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(discovery_url, json=payload)
                    
            if response.status_code in (200, 201):
                pass # Silent success
            else:
                logger.error(f"[Auto-Discovery] Failed to register. Status: {response.status_code}, Body: {response.text[:500]}")
        except Exception as e:
            logger.error(f"[Auto-Discovery] Error connecting to backend: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            
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
            reconcile_url = f"{backend_url}/api/providers/{provider_id}/reconcile"
            logger.info(f"[Worker Reconciliation] Attempting to reconcile...")
            
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
    
    logger.info(f"[Worker] Starting up...")
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
    
    logger.info(f"[Worker] Startup complete")


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
