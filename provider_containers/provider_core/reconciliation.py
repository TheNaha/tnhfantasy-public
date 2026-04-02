"""
V2 Reconciliation helpers for provider workers.
Contains shared functions for reporting file status, batch updates,
event pushes, and the shared reconciliation orchestration used by workers.
"""

import asyncio
from typing import Awaitable, Callable, Dict, List, Optional, Any, Set
from datetime import datetime
import httpx

from .state import ReconciliationState

EVENT_PUSH_MAX_ATTEMPTS = 3
EVENT_PUSH_INITIAL_BACKOFF_SECONDS = 0.5
EVENT_PUSH_TIMEOUT_SECONDS = 5.0


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
    retry_attempts: int = EVENT_PUSH_MAX_ATTEMPTS,
    retry_backoff_seconds: float = EVENT_PUSH_INITIAL_BACKOFF_SECONDS,
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
    
    attempts = max(1, int(retry_attempts))

    for attempt in range(1, attempts + 1):
        try:
            if http_client:
                response = await http_client.post(url, json=payload, timeout=EVENT_PUSH_TIMEOUT_SECONDS)
            else:
                async with httpx.AsyncClient(timeout=EVENT_PUSH_TIMEOUT_SECONDS) as client:
                    response = await client.post(url, json=payload)

            status_code = getattr(response, "status_code", None)
            if status_code is not None and status_code >= 400:
                raise RuntimeError(f"HTTP {status_code}")

            return True
        except Exception as e:
            if attempt >= attempts:
                # Don't fail reconciliation if event push fails.
                print(
                    f"[Reconciliation] Warning: Failed to push event "
                    f"for provider {provider_id} after {attempts} attempts: {e}"
                )
                return False

            delay = max(0.0, retry_backoff_seconds) * (2 ** (attempt - 1))
            print(
                f"[Reconciliation] Warning: Event push attempt {attempt}/{attempts} "
                f"failed for provider {provider_id}: {e}. Retrying in {delay:.2f}s"
            )
            await asyncio.sleep(delay)

    return False


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


async def run_reconciliation_v2(
    *,
    provider_id: str,
    backend_url: str,
    reconciliation_state: ReconciliationState,
    max_concurrent_downloads: int,
    hf_token: str,
    civitai_token: str,
    storage_label: str,
    validate_existing: Callable[[bool], Awaitable[Dict[str, Any]]],
    list_existing_files: Callable[[], Awaitable[Set[str]]],
    download_file: Callable[[str, str, Optional[str]], Awaitable[Any]],
    delete_file: Callable[[str], Awaitable[Any]],
) -> None:
    """Run the shared V2 reconciliation flow with provider-specific callbacks."""
    reconciliation_state.start_reconciliation()
    print(f"[V2 Reconciliation] Starting version-aware reconciliation for {provider_id}")

    async def push_state(phase: str, message: str = None, active_downloads: list = None):
        reconciliation_state.set_phase(phase)
        reconciliation_state.set_message(message)
        reconciliation_state.set_active_downloads(active_downloads or [])
        await push_reconciliation_event(
            backend_url=backend_url,
            provider_id=provider_id,
            status=reconciliation_state.get_status(),
            phase=phase,
            stats=reconciliation_state.get_stats(),
            current_download=reconciliation_state.get_current_download(),
            active_downloads=active_downloads,
            errors=reconciliation_state.get_errors(),
            message=message,
        )

    print("[V2 Reconciliation] Step 0: Validating existing models...")
    await push_state("validating", "Checking for invalid or partial downloads...")

    try:
        validation_result = await validate_existing(True)
        invalid_count = validation_result.get("total_invalid", 0)
        partial_count = validation_result.get("total_partial", 0)
        reconciliation_state.set_invalid_cleaned(invalid_count + partial_count)

        if invalid_count > 0 or partial_count > 0:
            print(f"[V2 Reconciliation] ✓ Cleaned up {invalid_count} invalid + {partial_count} partial files")
        else:
            print("[V2 Reconciliation] ✓ All existing models are valid")
    except Exception as exc:
        print(f"[V2 Reconciliation] ⚠ Validation step failed: {exc}")

    try:
        print("[V2 Reconciliation] Step 1: Querying pending downloads...")
        await push_state("fetching", "Querying pending downloads from backend...")

        pending_downloads = await get_pending_downloads(backend_url, provider_id)
        print(f"[V2 Reconciliation] Found {len(pending_downloads)} files pending download")

        print("[V2 Reconciliation] Step 2: Getting all expected storage paths...")
        all_expected_paths = await get_all_expected_paths(backend_url)
        print(f"[V2 Reconciliation] {len(all_expected_paths)} total expected paths in database")

        print(f"[V2 Reconciliation] Step 3: Checking existing files on {storage_label}...")
        await push_state("fetching", f"Checking existing files on {storage_label} storage...")

        existing_files = set(await list_existing_files())
        reconciliation_state.set_total_models(len(existing_files))
        print(f"[V2 Reconciliation] Found {len(existing_files)} existing files on {storage_label}")

        missing_files = all_expected_paths - existing_files
        if missing_files:
            print(f"[V2 Reconciliation] ⚠ {len(missing_files)} files missing from {storage_label}")
            missing_updates = [{"storage_path": path, "status": "pending"} for path in sorted(missing_files)]
            await batch_update_file_status_v2(backend_url, provider_id, missing_updates)
            pending_downloads = await get_pending_downloads(backend_url, provider_id)
            print(f"[V2 Reconciliation] Found {len(pending_downloads)} files now pending")

        downloads_needed = []
        already_ready = []
        for file_info in pending_downloads:
            storage_path = file_info.get("storage_path", "")
            if storage_path in existing_files:
                already_ready.append({
                    "file_id": file_info["file_id"],
                    "status": "ready",
                    "storage_path": storage_path,
                })
            else:
                downloads_needed.append(file_info)

        if already_ready:
            print(f"[V2 Reconciliation] Updating {len(already_ready)} already-existing files as ready...")
            await batch_update_file_status_v2(backend_url, provider_id, already_ready)

        reconciliation_state.set_download_queue(downloads_needed)
        reconciliation_state.set_missing_reported(len(missing_files) if missing_files else 0)
        print(f"[V2 Reconciliation] {len(downloads_needed)} files need downloading, {len(already_ready)} already ready")

        print(f"[V2 Reconciliation] Step 4: Processing downloads ({max_concurrent_downloads} concurrent)...")
        semaphore = asyncio.Semaphore(max_concurrent_downloads)
        total_downloads = len(downloads_needed)
        active_downloads_list = []
        active_downloads_lock = asyncio.Lock()

        async def download_single(file_info: dict, index: int):
            file_id = file_info["file_id"]
            model_name = file_info.get("model_name", "Unknown")
            version_name = file_info.get("version_name", "v1")
            storage_path = file_info["storage_path"]
            download_url = file_info["download_url"]
            display_name = f"{model_name} ({version_name})"

            download_info = {
                "name": display_name,
                "file_id": file_id,
                "progress": 0.0,
                "index": index + 1,
                "total": total_downloads,
            }

            async with semaphore:
                async with active_downloads_lock:
                    active_downloads_list.append(download_info)

                reconciliation_state.set_current_download(download_info)
                await push_state("downloading", f"Downloading {display_name}...", active_downloads_list.copy())

                print(f"[V2 Reconciliation] [{index + 1}/{total_downloads}] ⬇ Starting: {display_name}")
                await report_file_status_v2(backend_url, provider_id, file_id, "downloading")

                try:
                    token = determine_download_token(download_url, hf_token, civitai_token)
                    await download_file(download_url, storage_path, token)

                    reconciliation_state.increment_downloads_completed()
                    stats = reconciliation_state.get_stats()
                    print(f"[V2 Reconciliation] [{stats['downloads_completed']}/{total_downloads}] ✓ Completed: {display_name}")

                    await report_file_status_v2(
                        backend_url,
                        provider_id,
                        file_id,
                        "ready",
                        storage_path=storage_path,
                        size_bytes=int(file_info.get("size_kb", 0) * 1024),
                    )
                except Exception as exc:
                    reconciliation_state.increment_downloads_failed()
                    reconciliation_state.add_error(f"{display_name}: {str(exc)}")
                    print(f"[V2 Reconciliation] ✗ Failed: {display_name}: {exc}")
                    await report_file_status_v2(
                        backend_url,
                        provider_id,
                        file_id,
                        "failed",
                        error_message=str(exc),
                    )
                finally:
                    async with active_downloads_lock:
                        active_downloads_list[:] = [
                            download for download in active_downloads_list if download["file_id"] != file_id
                        ]
                    await push_state("downloading", None, active_downloads_list.copy())

        if downloads_needed:
            await push_state("downloading", f"Downloading {total_downloads} files ({max_concurrent_downloads} concurrent)...")
            tasks = [download_single(file_info, index) for index, file_info in enumerate(downloads_needed)]
            await asyncio.gather(*tasks, return_exceptions=True)

        reconciliation_state.set_current_download(None)

        print("[V2 Reconciliation] Step 5: Checking for orphaned files...")
        await push_state("deleting", "Checking for orphaned files...")

        if not all_expected_paths:
            print("[V2 Reconciliation] ⚠️ SAFETY: No expected paths - skipping deletion!")
        else:
            orphaned_files = [path for path in existing_files if path not in all_expected_paths]
            max_deletions = calculate_safe_deletion_limit(len(existing_files), len(orphaned_files))
            orphaned_files = orphaned_files[:max_deletions]

            if orphaned_files:
                print(f"[V2 Reconciliation] Found {len(orphaned_files)} orphaned files to delete")
                for orphan_path in orphaned_files:
                    try:
                        deleted = await delete_file(orphan_path)
                        if deleted is False:
                            print(f"[V2 Reconciliation] ✗ Failed to delete {orphan_path}")
                            continue
                        reconciliation_state.increment_deletions_completed()
                        print(f"[V2 Reconciliation] ✓ Deleted: {orphan_path}")
                    except Exception as exc:
                        print(f"[V2 Reconciliation] ✗ Failed to delete {orphan_path}: {exc}")
            else:
                print("[V2 Reconciliation] No orphaned files to delete")

        reconciliation_state.complete_reconciliation(success=True)
        stats = reconciliation_state.get_stats()
        print(
            f"[V2 Reconciliation] Complete! {stats['downloads_completed']} downloads, "
            f"{stats['downloads_failed']} failed, {stats['deletions_completed']} deleted"
        )
        await push_state("completed", "Reconciliation complete!")

    except Exception as exc:
        print(f"[V2 Reconciliation] Fatal error: {exc}")
        import traceback
        traceback.print_exc()
        reconciliation_state.add_error(f"Fatal error: {str(exc)}")
        reconciliation_state.complete_reconciliation(success=False)
        await push_state("failed", f"Reconciliation failed: {str(exc)}")
