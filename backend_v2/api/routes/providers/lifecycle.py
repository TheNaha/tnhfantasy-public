# Provider lifecycle routes: status, metrics, model management, setup, sync.
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends

from api.deps import (
    get_model_repo_v2,
    get_model_service_v2,
    get_provider_lifecycle_service,
    get_provider_service,
    get_provider_status_service,
)
from core.exceptions import ComfyError, NotFoundError, ProviderError, ValidationError
from infrastructure.http_client import get_http_client
from infrastructure.logging import api_logger
from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2
from services.model_service import ModelServiceV2
from services.provider_lifecycle_service import ProviderLifecycleService
from services.provider_service import ProviderService
from services.provider_status_service import (
    ProviderStatusService,
    invalidate_provider_status_caches,
)

from .crud import AddCustomProviderModelRequest

logger = api_logger()


router = APIRouter()


def _invalidate_provider_runtime_caches(provider_id: str | None = None) -> None:
    """Clear route-level and provider-status caches after runtime changes."""
    invalidate_provider_status_caches(provider_id)


@router.get("/status-cards")
async def get_provider_status_cards(
    service: ProviderService = Depends(get_provider_service),
    status_service: ProviderStatusService = Depends(get_provider_status_service)
):
    """Return canonical provider status payloads for all configured providers."""
    providers = await service.list_providers()
    cards = await status_service.build_provider_status_cards(providers)

    return {
        "status_cards": cards,
        "count": len(cards),
    }


@router.get("/{provider_id}/status-card")
async def get_provider_status_card(
    provider_id: str,
    status_service: ProviderStatusService = Depends(get_provider_status_service)
):
    """Return canonical provider status payload for a single provider."""
    return await status_service.build_provider_status_card(provider_id)


@router.get("/{provider_id}/live-metrics")
async def get_provider_live_metrics(
    provider_id: str,
    service: ProviderService = Depends(get_provider_service)
):
    """Fetch live metrics from the provider's in-process engine."""
    import time

    from services.provider_runtime import resolve_provider_runtime_async

    provider = await service.get_provider(provider_id)
    runtime = await resolve_provider_runtime_async(provider)

    if runtime.mode == "in_process":
        from services.engines.engine_factory import get_engine
        engine = get_engine(provider_id, provider)
        if engine is None:
            return {"status": "offline", "latency_ms": 0, "error": "No in-process engine available"}
        try:
            start_t = time.time()
            health = await engine.check_health()
            latency = int((time.time() - start_t) * 1000)
            info = {
                "provider_id": provider_id,
                "engine": getattr(engine, "__class__", {}).__name__ or "in_process",
                "healthy": bool(health.get("ready") or health.get("status") == "healthy"),
            }
            return {
                "status": "online" if info["healthy"] else "degraded",
                "latency_ms": latency,
                "info": info,
            }
        except Exception as exc:
            return {
                "status": "offline",
                "latency_ms": 0,
                "error": str(exc),
            }

    if not runtime.worker_url:
        return {"status": "offline", "latency_ms": 0, "error": "No worker URL configured"}

    try:
        http_client = get_http_client()
        start_t = time.time()
        res = await http_client.get(f"{runtime.worker_url}/info", timeout=5.0)
        res.raise_for_status()
        latency = int((time.time() - start_t) * 1000)
        info_data = res.json()

        return {
            "status": "online",
            "latency_ms": latency,
            "info": info_data,
        }
    except Exception as exc:
        return {
            "status": "offline",
            "latency_ms": 0,
            "error": str(exc),
        }


@router.get("/{provider_id}/modal-stats")
async def get_provider_modal_stats(
    provider_id: str,
    service: ProviderService = Depends(get_provider_service),
    status_service: ProviderStatusService = Depends(get_provider_status_service)
):
    """
    Get model counts directly from provider storage via the in-process engine.
    Cached for 30 seconds to reduce load.
    Works with both Modal and Beam providers.
    """
    # Get provider to verify it exists
    provider = await service.get_provider(provider_id)
    return await status_service.get_provider_storage_stats(provider_id, provider)


@router.get("/{provider_id}/sync-status")
async def get_provider_sync_status(
    provider_id: str,
    status_service: ProviderStatusService = Depends(get_provider_status_service)
):
    """Return V2-backed sync counts for a provider."""
    return await status_service.get_provider_sync_status(provider_id)


@router.get("/{provider_id}/models")
async def get_provider_models(
    provider_id: str,
    status: str | None = None,
    status_service: ProviderStatusService = Depends(get_provider_status_service)
):
    """Return provider models grouped by directory using the V2 schema."""
    sync_status = await get_provider_sync_status(provider_id, status_service)
    grouped: dict[str, list[dict[str, Any]]] = {}

    for model in sync_status["models"]:
        model_status = model["provider_status"]["status"]
        if status and model_status != status:
            continue
        grouped.setdefault(model["directory"], []).append(model)

    return {
        "provider": provider_id,
        "models": grouped,
    }


@router.delete("/{provider_id}/models")
async def remove_model_from_provider(
    provider_id: str,
    directory: str,
    filename: str,
    service: ModelServiceV2 = Depends(get_model_service_v2),
    provider_service: ProviderService = Depends(get_provider_service)
):
    """Delete a model file from one provider and mark it pending again in V2."""
    normalized_directory = directory.replace("models/", "", 1)
    file = service.repo.get_file_by_storage_path(normalized_directory, filename)
    if not file:
        raise NotFoundError("Resource", "Model file not found")

    provider = await provider_service.get_provider(provider_id)

    storage_path = f"models/{normalized_directory}/{filename}"

    from services.provider_runtime import resolve_provider_runtime_async
    runtime = await resolve_provider_runtime_async(provider)
    if getattr(runtime, "mode", "") == "in_process":
        from services.engines.engine_factory import get_engine

        engine = get_engine(provider_id, provider)
        if engine is None:
            logger.warning("provider_model_delete_no_engine", provider_id=provider_id, path=storage_path)
        else:
            try:
                await engine.delete_file(storage_path)
            except Exception as exc:
                logger.warning("provider_model_delete_failed", provider_id=provider_id, path=storage_path, error=str(exc))
    else:
        logger.warning(
            "provider_model_delete_no_engine",
            provider_id=provider_id,
            path=storage_path,
            mode=getattr(runtime, "mode", ""),
        )

    await asyncio.to_thread(
        service.update_provider_file_status,
        file_id=file.id,
        provider_id=provider_id,
        status="pending",
        storage_path=storage_path,
        size_bytes=None,
        error_message=None,
    )

    return {
        "status": "success",
        "provider_id": provider_id,
        "directory": f"models/{normalized_directory}",
        "filename": filename,
    }


@router.post("/models/custom")
async def add_custom_model_to_providers(
    request: AddCustomProviderModelRequest,
    service: ModelServiceV2 = Depends(get_model_service_v2)
):
    """Create a V2 custom model entry and trigger downloads for the selected providers."""
    model_name = request.model_data.get("name", "").strip()
    model_url = request.model_data.get("url", "").strip()
    model_type = request.model_data.get("type")

    if not model_name or not model_url:
        raise ValidationError("Model name and URL are required")

    result = await service.add_custom_model(
        name=model_name,
        directory=request.directory,
        download_url=model_url,
        provider_ids=request.provider_ids,
        model_type=model_type,
    )
    return {
        "status": "success",
        "model": result,
        "provider_ids": request.provider_ids,
    }



# ============================================================================
# PROVIDER SETUP ENDPOINT
# ============================================================================


@router.post("/{provider_id}/models/sync")
async def trigger_provider_sync(
    provider_id: str,
    lifecycle: ProviderLifecycleService = Depends(get_provider_lifecycle_service)
):
    """Trigger a reconciliation sync for a provider."""
    return await lifecycle.sync_provider_models(provider_id)


@router.post("/{provider_id}/setup")
async def setup_provider(
    provider_id: str,
    lifecycle: ProviderLifecycleService = Depends(get_provider_lifecycle_service)
):
    """Run the engine's setup_models to initialize remote storage."""
    try:
        return await lifecycle.setup_provider(provider_id)
    except ProviderError as exc:
        detail = str(exc)
        raise ComfyError(detail) from exc
    except ValueError as exc:
        raise ComfyError(f"Failed to run provider setup: {exc!s}") from exc



# ============================================================================
# PROVIDER STATUS CLEANUP
# ============================================================================


@router.post("/cleanup-orphaned-statuses")
async def cleanup_orphaned_provider_statuses(
    service: ProviderService = Depends(get_provider_service),
    model_repo: ModelRepositoryV2 = Depends(get_model_repo_v2)
):
    """
    Clean up ProviderVersionStatus records for providers that no longer exist.
    This fixes the desync between model status indicators and actual provider list.

    Should be run once after deleting providers to clean up orphaned status entries
    from before the cascade delete feature was added.
    """
    # Get list of active provider IDs
    providers = await service.list_providers()
    active_provider_ids = [p["id"] for p in providers]

    # Clean up orphaned statuses
    result = model_repo.cleanup_orphaned_provider_statuses(active_provider_ids)
    stale_reset_count = model_repo.reset_stale_downloading_statuses(
        stale_before=datetime.now(timezone.utc) - timedelta(minutes=120),
        provider_names=active_provider_ids,
    )
    _invalidate_provider_runtime_caches()

    return {
        "status": "success",
        "message": f"Cleaned up {result['deleted_count']} orphaned status entries and reset {stale_reset_count} stale downloads",
        "deleted_count": result["deleted_count"],
        "orphaned_providers": result["orphaned_providers"],
        "active_providers": active_provider_ids,
        "orphaned_statuses_removed": result["deleted_count"],
        "stale_downloading_reset": stale_reset_count,
        "affected_provider_ids": sorted(set(active_provider_ids + result["orphaned_providers"])),
    }


@router.post("/state/cleanup")
async def cleanup_provider_state(
    service: ProviderService = Depends(get_provider_service),
    model_repo: ModelRepositoryV2 = Depends(get_model_repo_v2)
):
    """Explicit maintenance action for provider state hygiene."""
    return await cleanup_orphaned_provider_statuses(service, model_repo)
