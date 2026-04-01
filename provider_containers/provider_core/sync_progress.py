"""
Sync progress reporting with batching.
Batches progress updates and sends them periodically to reduce API calls.
"""

import asyncio
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class SyncUpdate:
    """A single sync progress update."""
    model_name: str
    directory: str
    status: str
    progress: float = 0.0
    message: Optional[str] = None
    size_bytes: Optional[int] = None


class SyncProgressReporter:
    """
    Batched sync progress reporter.
    
    Collects progress updates and sends them in batches every N seconds
    to reduce HTTP overhead.
    """
    
    def __init__(
        self,
        provider_id: str,
        backend_url: str,
        batch_interval: float = 5.0,
        http_client=None,
    ):
        self.provider_id = provider_id
        self.backend_url = backend_url
        self.batch_interval = batch_interval
        self._http_client = http_client
        
        self._pending_updates: List[Dict] = []
        self._last_batch_time: float = 0
        self._lock = asyncio.Lock()
    
    async def report(
        self,
        model_name: str,
        directory: str,
        status: str,
        progress: float = 0.0,
        message: Optional[str] = None,
        size_bytes: Optional[int] = None,
        flush: bool = False,
    ):
        """
        Queue a sync progress update.
        
        Args:
            model_name: Name of the model being synced
            directory: Target directory (e.g., "checkpoints", "loras")
            status: Current status (e.g., "downloading", "completed", "failed")
            progress: Progress percentage (0.0 to 1.0)
            message: Optional status message
            size_bytes: Optional file size
            flush: If True, immediately send all pending updates
        """
        # Strip "models/" prefix for consistency
        clean_directory = directory.replace("models/", "") if directory else directory
        
        async with self._lock:
            self._pending_updates.append({
                "model_name": model_name,
                "directory": clean_directory,
                "status": status,
                "progress": progress,
                "message": message,
                "size_bytes": size_bytes,
            })
        
        # Check if we should flush
        current_time = time.time()
        should_flush = flush or (
            current_time - self._last_batch_time >= self.batch_interval
            and len(self._pending_updates) > 0
        )
        
        if should_flush:
            await self.flush()
    
    async def flush(self):
        """Send all pending updates in a single batch request."""
        async with self._lock:
            if not self._pending_updates:
                return
            
            updates_to_send = self._pending_updates.copy()
            self._pending_updates = []
            self._last_batch_time = time.time()
        
        url = f"{self.backend_url}/api/v2/models/sync-progress/batch"
        payload = {
            "provider_id": self.provider_id,
            "models": updates_to_send,
        }
        
        try:
            if self._http_client:
                response = await self._http_client.post(url, json=payload)
                if response.status_code != 200:
                    print(f"[SyncProgress] Batch error {response.status_code}: {response.text}")
            else:
                import httpx
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(url, json=payload)
                    if response.status_code != 200:
                        print(f"[SyncProgress] Batch error {response.status_code}: {response.text}")
        except Exception as e:
            print(f"[SyncProgress] Batch failed: {e}")


# Convenience functions for backward compatibility
_default_reporter: Optional[SyncProgressReporter] = None


def init_sync_reporter(provider_id: str, backend_url: str) -> SyncProgressReporter:
    """Initialize the default sync progress reporter."""
    global _default_reporter
    _default_reporter = SyncProgressReporter(provider_id, backend_url)
    return _default_reporter


async def report_sync_progress(
    model_name: str,
    directory: str,
    status: str,
    progress: float = 0.0,
    message: Optional[str] = None,
    size_bytes: Optional[int] = None,
    flush: bool = False,
):
    """Report sync progress using the default reporter."""
    if _default_reporter:
        await _default_reporter.report(
            model_name=model_name,
            directory=directory,
            status=status,
            progress=progress,
            message=message,
            size_bytes=size_bytes,
            flush=flush,
        )


async def flush_sync_progress():
    """Flush pending updates from the default reporter."""
    if _default_reporter:
        await _default_reporter.flush()
