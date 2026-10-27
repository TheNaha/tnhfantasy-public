from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from api.deps import get_model_repo_v2, get_session
from infrastructure.logging import model_logger

logger = model_logger()

router = APIRouter()


# ============================================================================
# PROVIDER STATUS ENDPOINTS
# ============================================================================
#
# This file used to be the worker-facing half of model reconciliation: nine
# routes the containerized provider workers pulled inputs from and pushed
# progress back to. Those workers were deleted on 2026-10-09 and their inputs and
# outputs are now taken directly by `services/in_process_reconciliation.py`,
# which talks to the same services and repository without an HTTP hop.
#
# The deleted routes, and what replaced each:
#
#   GET  /register-discovered                     direct service call
#   GET  /providers/{id}/pending-downloads        direct service call
#   GET  /cache                                   in-process, no 1.5 MB dump
#   POST /providers/batch-status-update           per-file writes in the runner
#   POST /sync-progress                           emit_model_sync_event()
#   POST /sync-progress/batch                     emit_model_sync_event()
#   POST /cleanup-orphaned                        see below
#   GET  /{model_id}/provider-status              see below
#   PUT  /files/{fid}/providers/{pid}/status       see below
#
# `POST /cleanup-orphaned` and `GET /{model_id}/provider-status` and
# `PUT /files/{fid}/providers/{pid}/status` were also removed: each had zero
# callers anywhere in the repository, and the first is a destructive sweep with
# no confirmation parameter on an unauthenticated API. `reset-status` is the one
# survivor — the Providers page calls it.

@router.get("/sync-manifest")
@router.get("/providers/{provider_id}/sync-manifest")
def get_sync_manifest(
    provider_id: str | None = None,
    session: Session = Depends(get_session)
):
    """Catalog manifest of all active models and their storage paths.
    
    Can be used by remote agents, notebooks, or scripts to bulk-download
    missing library models directly to the provider storage without manual UI clicks.
    """
    model_repo = get_model_repo_v2(session)
    items = model_repo.get_sync_manifest(provider_id=provider_id)
    
    # Also fetch LLM catalog weights from registry
    llm_items = []
    try:
        from services.llm_router import get_router
        registry = get_router().registry
        for m in registry.catalog():
            if m.get("gguf") and m.get("repo"):
                llm_items.append({
                    "id": m.get("id"),
                    "name": m.get("name"),
                    "repo": m.get("repo"),
                    "filename": m.get("gguf"),
                    "volume_dir": m.get("volume_dir", "llm_models"),
                    "storage_path": f"{m.get('volume_dir', 'llm_models')}/{m.get('gguf')}",
                    "mmproj": m.get("mmproj"),
                    "mmproj_repo": m.get("mmproj_repo"),
                    "roles": m.get("roles", []),
                })
    except Exception as exc:
        logger.warning(f"Could not load LLM registry into sync manifest: {exc}")

    pending_count = sum(1 for i in items if i.get("needs_download"))
    return {
        "status": "success",
        "provider_id": provider_id,
        "total_models": len(items),
        "pending_downloads": pending_count,
        "models": items,
        "llm_models": llm_items,
    }


@router.delete("/providers/{provider_id}/reset-status")
def reset_provider_status(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """Reset all provider statuses for a provider.

    Forces a re-download of every file on the next reconciliation, which is what
    the Providers page's "Reset status" control asks for. Deliberately the only
    route left here: every other one in this file answered to a worker that no
    longer exists.
    """
    model_repo = get_model_repo_v2(session)
    count = model_repo.delete_all_statuses_for_provider(provider_id)

    return {
        "status": "success",
        "message": f"Reset {count} status entries for provider '{provider_id}'",
        "deleted_count": count
    }
