"""
V2 Reconciliation helpers for provider workers.
Contains shared functions for reporting file status, batch updates, 
and pushing reconciliation events to the backend.
"""

import asyncio
from typing import Dict, List, Optional, Any, Set
from datetime import datetime
import httpx

from .state import ReconciliationState
from .models import MODEL_DIRECTORIES


def _chunked(items: List[Dict], chunk_size: int):
    """Yield item batches for large reconciliation updates."""
    for start in range(0, len(items), chunk_size):
        yield items[start:start + chunk_size]


async def report_file_status_v2(
    backend_url: str,
    provider_id: str,
    file_id: int,
    status: str,
    storage_path: str = None,
    size_bytes: int = None,
    error_message: str = None,
    http_client=None,
):
    """
    Report file download status using V2 API.
    
    Args:
        backend_url: Backend API base URL
        provider_id: Provider identifier
        file_id: Database file ID
        status: Status to report (pending, downloading, ready, failed)
        storage_path: Optional storage path after download
        size_bytes: Optional file size in bytes
        error_message: Optional error message for failed status
        http_client: Optional shared HTTP client
    """
    url = f"{backend_url}/api/v2/models/files/{file_id}/providers/{provider_id}/status"
    payload = {"status": status}
    
    if storage_path:
        payload["storage_path"] = storage_path
    if size_bytes:
        payload["size_bytes"] = size_bytes
    if error_message:
        payload["error_message"] = error_message
    
    try:
        if http_client:
            response = await http_client.put(url, json=payload)
        else:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.put(url, json=payload)
        
        if response.status_code != 200:
            print(f"[V2 Reconciliation] Warning: Failed to update status for file {file_id}: {response.status_code}")
    except Exception as e:
        print(f"[V2 Reconciliation] Warning: Error updating status for file {file_id}: {e}")


async def batch_update_file_status_v2(
    backend_url: str,
    provider_id: str,
    updates: List[Dict],
    http_client=None,
):
    """
    Batch update multiple file statuses using V2 API.
    
    Args:
        backend_url: Backend API base URL
        provider_id: Provider identifier
        updates: List of update dicts with file_id/storage_path and status
        http_client: Optional shared HTTP client
    """
    if not updates:
        return
    
    url = f"{backend_url}/api/v2/models/providers/batch-status-update"
    chunk_size = 500
    total_updated = 0
    total_failed = 0
    
    for batch in _chunked(updates, chunk_size):
        payload = {
            "provider_name": provider_id,
            "updates": batch,
        }
        
        try:
            if http_client:
                response = await http_client.post(url, json=payload, timeout=30.0)
            else:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(url, json=payload)
            
            if response.status_code == 200:
                result = response.json()
                updated = result.get("updated", 0)
                failed = result.get("failed", 0)
                total_updated += updated
                total_failed += failed
                print(f"[V2 Reconciliation] Batch update: {updated} updated, {failed} failed")
            else:
                total_failed += len(batch)
                print(f"[V2 Reconciliation] Warning: Batch update failed: {response.status_code}")
        except Exception as e:
            total_failed += len(batch)
            print(f"[V2 Reconciliation] Warning: Batch update error: {e}")
    
    if len(updates) > chunk_size:
        print(
            f"[V2 Reconciliation] Batch update complete: {total_updated} updated, {total_failed} failed across {len(updates)} updates"
        )


async def push_reconciliation_event(
    backend_url: str,
    provider_id: str,
    status: str,
    phase: str = None,
    stats: dict = None,
    current_download: dict = None,
    active_downloads: list = None,
    errors: list = None,
    message: str = None,
    http_client=None,
):
    """
    Push reconciliation event to backend for WebSocket broadcast.
    Called during reconciliation to send real-time updates to frontend.
    
    Args:
        backend_url: Backend API base URL
        provider_id: Provider identifier
        status: Current reconciliation status (idle, reconciling, completed, failed)
        phase: Current reconciliation phase (validating, fetching, downloading, deleting)
        stats: Optional statistics dict
        current_download: Optional current download info (legacy, use active_downloads)
        active_downloads: List of concurrent active downloads
        errors: Optional list of errors
        message: Optional status message
        http_client: Optional shared HTTP client
    """
    url = f"{backend_url}/api/providers/{provider_id}/reconciliation-event"
    payload = {
        "status": status,
        "phase": phase,
        "stats": stats,
        "current_download": current_download,
        "active_downloads": active_downloads or [],
        "errors": errors,
        "message": message,
    }
    
    try:
        if http_client:
            await http_client.post(url, json=payload, timeout=5.0)
        else:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(url, json=payload)
    except Exception as e:
        # Don't fail reconciliation if event push fails
        print(f"[Reconciliation] Warning: Failed to push event: {e}")


async def get_pending_downloads(
    backend_url: str,
    provider_id: str,
    http_client=None,
) -> List[Dict]:
    """
    Query pending downloads from V2 API.
    
    Returns:
        List of file info dicts pending download
    """
    url = f"{backend_url}/api/v2/models/providers/{provider_id}/pending-downloads"
    
    try:
        if http_client:
            response = await http_client.get(url, timeout=30.0)
        else:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
        
        if response.status_code == 200:
            data = response.json()
            return data.get("files", [])
        else:
            print(f"[V2 Reconciliation] V2 API returned {response.status_code}")
            return []
    except Exception as e:
        print(f"[V2 Reconciliation] Error fetching pending downloads: {e}")
        return []


async def get_all_expected_paths(
    backend_url: str,
    http_client=None,
) -> Set[str]:
    """
    Get all expected storage paths from V2 database.
    
    Returns:
        Set of expected storage paths
    """
    url = f"{backend_url}/api/v2/models/all-storage-paths"
    
    try:
        if http_client:
            response = await http_client.get(url, timeout=30.0)
        else:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
        
        if response.status_code == 200:
            data = response.json()
            return set(data.get("paths", []))
        else:
            print(f"[V2 Reconciliation] Warning: Could not get all paths: {response.status_code}")
            return set()
    except Exception as e:
        print(f"[V2 Reconciliation] Error fetching expected paths: {e}")
        return set()


def determine_download_token(url: str, hf_token: str, civitai_token: str) -> Optional[str]:
    """
    Determine which token to use for a download URL.
    
    Args:
        url: Download URL
        hf_token: HuggingFace token
        civitai_token: CivitAI token
        
    Returns:
        Appropriate token or None
    """
    if not url:
        return None
    if "huggingface.co" in url:
        return hf_token
    if "civitai.com" in url:
        return civitai_token
    return None


def calculate_safe_deletion_limit(total_files: int, orphaned_count: int) -> int:
    """
    Calculate safe deletion limit to prevent accidental mass deletion.
    
    Limits deletions to 50% of total files as a safety measure.
    
    Args:
        total_files: Total number of files in storage
        orphaned_count: Number of orphaned files found
        
    Returns:
        Maximum number of files to delete
    """
    max_deletions = total_files // 2
    if orphaned_count > max_deletions and max_deletions > 0:
        print(f"[V2 Reconciliation] ⚠️ SAFETY: {orphaned_count} orphans > 50% of files!")
        print(f"[V2 Reconciliation]    Limiting to {max_deletions} deletions max")
        return max_deletions
    return orphaned_count
