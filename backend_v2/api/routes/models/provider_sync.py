from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from api.deps import get_model_service_v2, get_session, model_logger

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
    result = await service.update_provider_file_status(
        file_id=file_id,
        provider_id=provider_id,
        status=request.status,
        storage_path=request.storage_path,
        size_bytes=request.size_bytes,
        error_message=request.error_message
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
    file_id: int | None = None  # Optional if storage_path provided
    status: str
    storage_path: str | None = None  # Can be used to lookup file_id
    size_bytes: int | None = None


class BatchUpdateRequest(BaseModel):
    """Batch status update from worker."""
    provider_name: str | None = None
    provider_id: str | None = None
    updates: list[BatchStatusUpdate]


@router.post("/providers/batch-status-update")
async def batch_update_status(
    request: BatchUpdateRequest,
    session: Session = Depends(get_session)
):
    """
    Batch update provider statuses.
    More efficient than individual calls during reconciliation.
    
    Supports two lookup modes:
    - By file_id (preferred, faster)
    - By storage_path (used when file_id unknown, e.g., reporting missing files)
    """
    from api.deps import get_model_repo_v2
    repo = get_model_repo_v2(session)
    service = get_model_service_v2(session)
    provider_key = request.provider_id or request.provider_name
    if not provider_key:
        raise ValidationError("provider_id or provider_name is required")
    
    paths = [u.storage_path for u in request.updates if u.file_id is None and u.storage_path]
    path_to_file_id = None
    
    if paths:
        path_to_file_id = repo.get_file_ids_by_storage_paths(paths)
    
    updated = 0
    failed = 0
    
    for update in request.updates:
        try:
            # Resolve file_id from storage_path if needed
            file_id = update.file_id
            if file_id is None and update.storage_path and path_to_file_id:
                file_id = path_to_file_id.get(update.storage_path)
            
            if file_id is None:
                failed += 1
                continue
            
            await service.update_provider_file_status(
                file_id=file_id,
                provider_id=provider_key,
                status=update.status,
                storage_path=update.storage_path,
                size_bytes=update.size_bytes
            )
            updated += 1
        except Exception:
            failed += 1
    
    return {"updated": updated, "failed": failed}


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
async def cleanup_orphaned_models(
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
    models: list[BatchSyncItem]


@router.post("/sync-progress/batch")
async def receive_batch_sync_progress(
    request: BatchSyncProgressRequest,
    session: Session = Depends(get_session)
):
    """
    Receive batch sync progress from worker.
    Updates multiple model statuses in a single request.
    """
    from api.deps import get_model_repo_v2
    repo = get_model_repo_v2(session)
    service = get_model_service_v2(session)
    
    # We can pass empty list to get all of them
    path_to_file_id = repo.get_file_ids_by_storage_paths([])
    file_id_by_key = {}
    for path, file_id in path_to_file_id.items():
        # path is models/directory/filename
        parts = path.split('/')
        if len(parts) >= 3:
            file_id_by_key[(parts[1], parts[2])] = file_id
    
    updated = 0
    failed = 0
    
    for item in request.models:
        try:
            file_id = file_id_by_key.get((item.directory, item.model_name))
            if file_id is None:
                failed += 1
                continue

            if item.status == "completed":
                await service.update_provider_file_status(
                    file_id=file_id,
                    provider_id=request.provider_id,
                    status="ready",
                    storage_path=f"models/{item.directory}/{item.model_name}",
                    size_bytes=item.size_bytes,
                )
                updated += 1
            elif item.status == "failed":
                await service.update_provider_file_status(
                    file_id=file_id,
                    provider_id=request.provider_id,
                    status="failed",
                    storage_path=f"models/{item.directory}/{item.model_name}",
                )
                updated += 1
            elif item.status == "pending":
                await service.update_provider_file_status(
                    file_id=file_id,
                    provider_id=request.provider_id,
                    status="pending",
                    storage_path=f"models/{item.directory}/{item.model_name}",
                )
                updated += 1
        except Exception:
            failed += 1
    
    return {
        "status": "ok",
        "updated": updated,
        "failed": failed
    }


