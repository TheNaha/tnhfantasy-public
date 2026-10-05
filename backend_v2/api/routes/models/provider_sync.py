from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session

from api.deps import get_model_service_v2, get_session
from core.exceptions import ValidationError
from core.upload_validation import MAX_BATCH_ITEMS, require_batch_size
from infrastructure.logging import model_logger

from .schemas import UpdateProviderStatusRequest

logger = model_logger()

router = APIRouter()


# ============================================================================
# PROVIDER STATUS ENDPOINTS
# ============================================================================

@router.get("/{model_id}/provider-status")
async def get_provider_statuses(
    model_id: str,
    session: Session = Depends(get_session)
):
    """Get provider download statuses for a model."""
    service = get_model_service_v2(session)
    return await service.get_model_provider_statuses(model_id)


@router.put("/files/{file_id}/providers/{provider_id}/status")
async def update_file_provider_status(
    file_id: str,
    provider_id: str,
    request: UpdateProviderStatusRequest,
    session: Session = Depends(get_session)
):
    """Update provider status for a specific file."""
    service = get_model_service_v2(session)
    # The status write is a synchronous upsert + commit and the handler has to
    # stay `async def` (it awaits the WebSocket emit below), so the write goes
    # through `asyncio.to_thread` instead of running on the event loop.
    result = await asyncio.to_thread(
        service.update_provider_file_status,
        file_id=file_id,
        provider_id=provider_id,
        status=request.status,
        storage_path=request.storage_path,
        size_bytes=request.size_bytes,
        error_message=request.error_message,
    )

    # Emit WebSocket event to replace polling
    from core.events import emit_model_status_update
    await emit_model_status_update(
        provider_id=provider_id,
        file_id=file_id,
        status=request.status,
        extra={"storage_path": request.storage_path, "size_bytes": request.size_bytes}
    )

    return result


class RegisterDiscoveredRequest(BaseModel):
    provider_id: str
    files: list[dict[str, Any]]


@router.post("/register-discovered")
async def register_discovered_models(
    request: RegisterDiscoveredRequest,
    session: Session = Depends(get_session)
):
    """Register files discovered on a provider's storage as database models.
    
    Called by workers during reconciliation when files exist on provider
    storage but have no corresponding database entries. Creates ModelV2,
    ModelVersion, ModelFile, and ProviderVersionStatus entries so the
    files are recognized as installed models on subsequent reconciliation runs.
    """
    service = get_model_service_v2(session)
    return await service.register_discovered_files(
        provider_id=request.provider_id,
        files=request.files,
    )


# ============================================================================
# RECONCILIATION ENDPOINTS
# ============================================================================

@router.get("/providers/{provider_id}/pending-downloads")
def get_pending_downloads(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """
    Get files pending download for a provider.
    Used by worker for reconciliation.
    """
    service = get_model_service_v2(session)
    pending = service.get_pending_downloads(provider_id)
    return {"files": pending}


@router.get("/cache")
def get_model_cache(session: Session = Depends(get_session)):
    """Get full model cache for reconciliation."""
    service = get_model_service_v2(session)
    return {"models": service.get_full_cache()}


# ============================================================================
# BATCH UPDATES (for worker efficiency)
# ============================================================================

class BatchStatusUpdate(BaseModel):
    """Single item in batch status update."""
    file_id: str | None = None  # Optional if storage_path provided
    status: str
    storage_path: str | None = None  # Can be used to lookup file_id
    size_bytes: int | None = None


class BatchUpdateRequest(BaseModel):
    """Batch status update from worker."""
    provider_name: str | None = None
    provider_id: str | None = None
    # Bounded at the model layer as well as in the handler: `require_batch_size`
    # in the handler is the guard that runs before any per-item work, and this
    # is what stops a 1e6-element body from being parsed and validated at all.
    updates: list[BatchStatusUpdate] = Field(max_length=MAX_BATCH_ITEMS)


def _apply_batch_status_updates(
    session: Session,
    provider_key: str,
    updates: list[BatchStatusUpdate],
) -> tuple[int, int, dict[str, int]]:
    """Worker-thread body for `POST /providers/batch-status-update`.

    Every statement here is synchronous SQLModel work — a path lookup, then one
    upsert + commit per item — and it used to run inline on the event loop, once
    per item, inside an `async def`. Workers send 500-row chunks concurrently,
    so at the batch cap this was MAX_BATCH_ITEMS blocking commits serialised
    against every other request on the loop.

    Returns `(updated, failed, status_counts)`.
    """
    from api.deps import get_model_repo_v2

    repo = get_model_repo_v2(session)
    service = get_model_service_v2(session)

    paths = [u.storage_path for u in updates if u.file_id is None and u.storage_path]
    path_to_file_id = repo.get_file_ids_by_storage_paths(paths) if paths else None

    updated = 0
    failed = 0
    status_counts: dict[str, int] = {}
    for update in updates:
        file_id = update.file_id
        try:
            # Resolve file_id from storage_path if needed
            if file_id is None and update.storage_path and path_to_file_id:
                file_id = path_to_file_id.get(update.storage_path)

            if file_id is None:
                failed += 1
                continue

            service.update_provider_file_status(
                file_id=file_id,
                provider_id=provider_key,
                status=update.status,
                storage_path=update.storage_path,
                size_bytes=update.size_bytes
            )
            status_counts[update.status] = status_counts.get(update.status, 0) + 1
            updated += 1
        except Exception as e:
            failed += 1
            logger.error(f"Batch status update failed for file_id {file_id}: {e}")

    return updated, failed, status_counts


@router.post("/providers/batch-status-update")
async def batch_update_status(
    request: BatchUpdateRequest,
    session: Session = Depends(get_session)
):
    """
    Batch update provider statuses.
    More efficient than individual calls during reconciliation.
    Emits a single aggregate WebSocket event after all updates.

    A partial batch answers 200 with `status: "partial"` and `degraded: true`,
    not 200 with a bare failure count. The precedent is `api/routes/files.py`,
    where a partial best-effort fan-out answers 200 with an explicit status
    (`sync_status: "sync_failed"`) and a *different result shape* answers 200
    with `source`/`degraded` set, so a caller can tell "partly done" from "done"
    from "not done". Raising here instead would be wrong for this endpoint's
    one production caller: `provider_core.reconciliation.batch_update_file_status_v2`
    counts any non-200 as a whole-chunk failure (`return 0, len(batch)`) and
    does not retry, so a raise would discard the record of the rows that *did*
    land and report the entire chunk as lost.
    """
    from core.events import emit_model_status_update

    provider_key = request.provider_id or request.provider_name
    if not provider_key:
        raise ValidationError("provider_id or provider_name is required")

    # Bound the batch before any per-item work happens, the same way
    # `api/routes/files.py` and `api/routes/generation.py` do.
    require_batch_size(request.updates, MAX_BATCH_ITEMS, field="updates")

    updated, failed, status_counts = await asyncio.to_thread(
        _apply_batch_status_updates, session, provider_key, request.updates
    )

    if updated > 0:
        await emit_model_status_update(
            provider_id=provider_key,
            file_id=0,
            status="batch_updated",
            extra={"updated": updated, "failed": failed, "status_counts": status_counts}
        )

    if failed:
        return {
            "status": "partial",
            "degraded": True,
            "updated": updated,
            "failed": failed,
            "status_counts": status_counts,
        }
    return {"status": "ok", "updated": updated, "failed": failed, "status_counts": status_counts}


@router.delete("/providers/{provider_id}/reset-status")
def reset_provider_status(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """
    Reset all provider statuses for a provider.
    This will force re-download of ALL files on next reconciliation.
    Use with caution!
    """
    from api.deps import get_model_repo_v2

    model_repo = get_model_repo_v2(session)
    count = model_repo.delete_all_statuses_for_provider(provider_id)
    
    return {
        "status": "success",
        "message": f"Reset {count} status entries for provider '{provider_id}'",
        "deleted_count": count
    }


# ============================================================================
# REVERSE RECONCILIATION
# ============================================================================

@router.post("/cleanup-orphaned")
def cleanup_orphaned_models(
    session: Session = Depends(get_session)
):
    """Remove models whose files have no active provider status.
    
    This is the reverse reconciliation direction: models whose files
    exist in the database but are no longer present on any provider
    (all statuses are 'failed' or missing) are cleaned up.
    """
    from api.deps import get_model_repo_v2
    model_repo = get_model_repo_v2(session)
    deleted = model_repo.cleanup_orphaned_models()
    return {"deleted": deleted}


# ============================================================================
# SYNC PROGRESS - Worker reports download progress
# ============================================================================

class SyncProgressRequest(BaseModel):
    """Progress report from worker during model sync."""
    provider_id: str
    model_name: str
    directory: str
    progress: float  # 0-100
    status: str  # downloading, completed, failed
    message: str | None = None
    size_bytes: int | None = None


@router.post("/sync-progress")
async def receive_sync_progress(
    request: SyncProgressRequest,
    session: Session = Depends(get_session)
):
    """
    Receive sync progress from worker.
    Worker calls this endpoint to report download progress.
    Backend emits WebSocket event to frontend.
    """
    from api.deps import get_event_bus
    from core.events import Event, EventType
    
    event_bus = get_event_bus()
    
    # Determine event type based on status
    if request.status == "downloading":
        event_type = EventType.MODEL_SYNC_PROGRESS
    elif request.status == "completed":
        event_type = EventType.MODEL_SYNC_COMPLETED
    elif request.status == "failed":
        event_type = EventType.MODEL_SYNC_FAILED
    else:
        event_type = EventType.MODEL_SYNC_STARTED
    
    # Emit event for WebSocket subscribers
    event = Event(
        type=event_type,
        data={
            "provider_id": request.provider_id,
            "model_name": request.model_name,
            "directory": request.directory,
            "progress": request.progress,
            "status": request.status,
            "message": request.message,
            "size_bytes": request.size_bytes
        }
    )
    await event_bus.publish(event)
    
    return {"status": "ok"}


class BatchSyncItem(BaseModel):
    """Single item in batch sync request."""
    model_name: str
    directory: str
    status: str  # completed, pending, failed
    size_bytes: int | None = None


class BatchSyncProgressRequest(BaseModel):
    """Batch sync progress from worker - updates multiple models at once."""
    provider_id: str
    models: list[BatchSyncItem] = Field(max_length=MAX_BATCH_ITEMS)


def _apply_batch_sync_progress(
    session: Session,
    provider_id: str,
    items: list[BatchSyncItem],
    storage_paths: list[str],
) -> tuple[int, int]:
    """Worker-thread body for `POST /sync-progress/batch`.

    `storage_paths` is the request's own list of `models/<dir>/<name>` paths.
    It used to be a deliberately empty list, with the comment "we can pass
    empty list to get all of them" — but `get_file_ids_by_storage_paths([])`
    adds no `WHERE` clause at all
    (`infrastructure/repositories/model_repo_v2.py:1349`), so every one of these
    requests materialised the entire model library through a two-join
    `select(ModelFile, ModelVersion, ModelV2).all()`, built a Python dict from
    it, and split every path on `/` — per request, on the event loop. Passing
    the request's own paths makes the `IN` filter engage.

    Returns `(updated, failed)`.
    """
    from api.deps import get_model_repo_v2

    repo = get_model_repo_v2(session)
    service = get_model_service_v2(session)

    path_to_file_id = repo.get_file_ids_by_storage_paths(storage_paths)
    file_id_by_key = {}
    for path, file_id in path_to_file_id.items():
        # path is models/directory/filename
        parts = path.split('/')
        if len(parts) >= 3:
            file_id_by_key[(parts[1], parts[2])] = file_id

    updated = 0
    failed = 0

    for item in items:
        try:
            file_id = file_id_by_key.get((item.directory, item.model_name))
            if file_id is None:
                failed += 1
                continue

            # Status mapping, and `size_bytes` only on the completed branch, are
            # both preserved from the pre-thread inline version: the worker only
            # ever reported a size for a finished download.
            status, reported_size = {
                "completed": ("ready", item.size_bytes),
                "failed": ("failed", None),
                "pending": ("pending", None),
            }.get(item.status, (None, None))
            if status is None:
                continue

            service.update_provider_file_status(
                file_id=file_id,
                provider_id=provider_id,
                status=status,
                storage_path=f"models/{item.directory}/{item.model_name}",
                size_bytes=reported_size,
            )
            updated += 1
        except Exception:
            failed += 1

    return updated, failed


@router.post("/sync-progress/batch")
async def receive_batch_sync_progress(
    request: BatchSyncProgressRequest,
    session: Session = Depends(get_session)
):
    """
    Receive batch sync progress from worker.
    Updates multiple model statuses in a single request.
    """
    require_batch_size(request.models, MAX_BATCH_ITEMS, field="models")

    storage_paths = [
        f"models/{item.directory}/{item.model_name}" for item in request.models
    ]
    updated, failed = await asyncio.to_thread(
        _apply_batch_sync_progress, session, request.provider_id, request.models, storage_paths
    )

    return {
        "status": "ok",
        "updated": updated,
        "failed": failed,
    }


