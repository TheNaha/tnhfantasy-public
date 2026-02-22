"""
Background task utilities for provider workers.
Includes reconciliation loop and startup helpers.
"""

import asyncio
import os
from typing import Callable, Awaitable, Optional


async def reconciliation_loop(
    provider_id: str,
    backend_url: str,
    interval_seconds: int = 7200,  # 2 hours
    startup_delay_seconds: int = 130,
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
        print("[Worker Reconciliation] PROVIDER_ID not set, skipping reconciliation loop")
        return
    
    print(f"[Worker Reconciliation] Starting loop for provider: {provider_id}")
    print(f"[Worker Reconciliation] Backend URL: {backend_url}")
    
    await asyncio.sleep(startup_delay_seconds)
    
    while True:
        try:
            reconcile_url = f"{backend_url}/api/providers/{provider_id}/reconcile"
            print(f"[Worker Reconciliation] Attempting to reconcile...")
            
            if http_client:
                response = await http_client.post(reconcile_url, timeout=30.0)
            else:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(reconcile_url)
            
            status = response.status_code
            print(f"[Worker Reconciliation] Response status: {status}")
            
            if status == 200:
                result = response.json()
                print(f"[Worker Reconciliation] ✓ Success: {result}")
            else:
                print(f"[Worker Reconciliation] ✗ Failed: {status}")
        
        except Exception as e:
            print(f"[Worker Reconciliation] ✗ Error: {type(e).__name__}: {e}")
        
        print(f"[Worker Reconciliation] Waiting {interval_seconds // 3600}h until next reconciliation...")
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
    
    print(f"[Worker] Starting up...")
    print(f"[Worker] PROVIDER_ID: {provider_id}")
    print(f"[Worker] PROVIDER_TYPE: {provider_type}")
    print(f"[Worker] BACKEND_URL: {backend_url}")
    print(f"[Worker] HF_TOKEN: {'✓ Set' if hf_token else '✗ Not set'}")
    print(f"[Worker] CIVITAI_TOKEN: {'✓ Set' if civitai_token else '✗ Not set'}")
    
    if extra_vars:
        for key, value in extra_vars.items():
            if value:
                # Mask sensitive values
                if "TOKEN" in key.upper() or "SECRET" in key.upper() or "KEY" in key.upper():
                    print(f"[Worker] {key}: ✓ Set")
                else:
                    print(f"[Worker] {key}: {value}")
            else:
                print(f"[Worker] {key}: ✗ Not set")
    
    print(f"[Worker] Startup complete")


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
