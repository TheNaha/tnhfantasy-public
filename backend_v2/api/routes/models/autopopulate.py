import asyncio
from fastapi import APIRouter, Depends
from core.exceptions import NotFoundError, ValidationError, ComfyError
from sqlmodel import Session, select
from api.deps import get_session, get_model_repo_v2, get_model_civitai_sync_service
from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2
from services.model_civitai_sync import ModelCivitaiSyncService
from core.entities import ModelV2
from api.deps import get_session_context
from api.deps import get_logger

from pydantic import BaseModel
from typing import Optional

from api.routes.websocket import broadcast_to_all

logger = get_logger("autopopulate")
router = APIRouter(prefix="", tags=["Models"])

class AutopopulateRequest(BaseModel):
    civitai_id: Optional[int] = None

class BatchAutopopulateCandidatesRequest(BaseModel):
    model_ids: list[int]


def _get_models_needing_population(repo: ModelRepositoryV2) -> list:
    return repo.get_models_needing_population()

@router.get("/autopopulate-pending")
async def get_autopopulate_pending(repo: ModelRepositoryV2 = Depends(get_model_repo_v2)):
    """Return a list of models that need autopopulation."""
    models = _get_models_needing_population(repo)
    return {
        "pending": [
            {
                "id": str(m.id),
                "name": m.name,
                "type": m.type,
                "directory": m.directory
            } for m in models
        ],
        "count": len(models)
    }


@router.get("/{model_id}/autopopulate-candidates")
async def get_autopopulate_candidates(
    model_id: int,
    service: ModelCivitaiSyncService = Depends(get_model_civitai_sync_service)
):
    """Return scored CivitAI search candidates for an auto-discovered model.
    Used by the frontend AutopopulateSelector so users can pick the right match.
    """
    try:
        return await service.search_civitai_candidates(str(model_id))
    except ValueError as e:
        raise NotFoundError("Model", model_id)
    except Exception as e:
        raise ValidationError(str(e))


@router.post("/autopopulate-candidates/batch")
async def batch_get_autopopulate_candidates(
    request: BatchAutopopulateCandidatesRequest,
    service: ModelCivitaiSyncService = Depends(get_model_civitai_sync_service)
):
    """Batch fetch CivitAI search candidates for multiple models."""
    import asyncio
    semaphore = asyncio.Semaphore(3)
    
    async def fetch_one(model_id: int):
        async with semaphore:
            try:
                res = await service.search_civitai_candidates(str(model_id))
                return {"model_id": model_id, "data": res}
            except Exception as e:
                return {"model_id": model_id, "error": str(e)}

    tasks = [fetch_one(mid) for mid in request.model_ids]
    results = await asyncio.gather(*tasks)
    
    return {"results": results}


@router.get("/{model_id}/autopopulate-search")
async def search_autopopulate_candidates(
    model_id: int,
    query: str,
    types: Optional[str] = None,
    repo: ModelRepositoryV2 = Depends(get_model_repo_v2)
):
    """Manual CivitAI search for autopopulate. Formats results like candidates."""
    from api.deps import get_external_model_service
    
    # Verify model exists
    model = repo.get_model(model_id)
    if not model:
        raise NotFoundError("Model", model_id)
        
    external = get_external_model_service()
    search_kwargs = {"query": query, "limit": 20}
    if types:
        search_kwargs["types"] = types
        
    try:
        result = await external.search_civitai(**search_kwargs)
        
        candidates = []
        for item in result.get("items", []):
            candidates.append({
                "score": 0,
                "score_percent": 0,
                "match_label": "Manual search result",
                "civitai_model": item,
            })
            
        return {
            "model_id": str(model.id),
            "model_name": model.name,
            "candidates": candidates,
            "total_candidates": len(candidates),
            "source": "civitai",
        }
    except Exception as e:
        raise ValidationError(str(e))


@router.post("/{model_id}/autopopulate")
async def autopopulate_model_details(
    model_id: int, 
    request: Optional[AutopopulateRequest] = None,
    service: ModelCivitaiSyncService = Depends(get_model_civitai_sync_service)
):
    target_id = request.civitai_id if request else None
    try:
        return await service.autopopulate_model(model_id, target_civitai_id=target_id)
    except ValueError as e:
        raise NotFoundError("Model", model_id)
    except Exception as e:
        raise ValidationError(str(e))


@router.post("/autopopulate-all")
async def autopopulate_all_models(
    repo: ModelRepositoryV2 = Depends(get_model_repo_v2),
    session: Session = Depends(get_session)
):
    models_to_process = _get_models_needing_population(repo)

    if not models_to_process:
        return {
            "status": "no_models_to_populate",
            "message": "No auto-discovered models need autopopulation",
            "count": 0
        }

    async def process_models(session: Session):
        total = len(models_to_process)
        results = {"success": 0, "failed": 0, "not_found": 0, "errors": []}
        
        await broadcast_to_all("AUTOPOPULATE_PROGRESS", {
            "status": "started",
            "processed": 0,
            "total": total,
            "results": results,
            "current_model": "Starting..."
        })
        
        service = get_model_civitai_sync_service(session)
        for i, model in enumerate(models_to_process):
            try:
                await broadcast_to_all("AUTOPOPULATE_PROGRESS", {
                    "status": "processing",
                    "processed": i,
                    "total": total,
                    "results": results,
                    "current_model": model.name
                })
                
                await service.autopopulate_model(str(model.id))
                results["success"] += 1
            except ValueError:
                results["not_found"] += 1
            except Exception as exc:
                results["failed"] += 1
                results["errors"].append({"model_id": str(model.id), "error": str(exc)})
                
        await broadcast_to_all("AUTOPOPULATE_PROGRESS", {
            "status": "completed",
            "processed": total,
            "total": total,
            "results": results,
            "current_model": "Done"
        })
        return results

    if len(models_to_process) <= 5:
        try:
            results = await process_models(session)
            return {
                "status": "completed",
                "message": f"Processed {len(models_to_process)} models",
                "count": len(models_to_process),
                "results": results
            }
        except Exception as e:
            raise ComfyError(str(e))
    else:
        async def _background_autopopulate():
            async with get_session_context() as bg_session:
                try:
                    results = await process_models(bg_session)
                    logger.info("background_autopopulate_complete", count=len(models_to_process), results=results)
                except Exception as exc:
                    logger.error("background_autopopulate_failed", error=str(exc))

        asyncio.create_task(_background_autopopulate())
        return {
            "status": "processing",
            "message": f"Started autopopulation of {len(models_to_process)} models in background",
            "count": len(models_to_process)
        }


@router.get("/autopopulate-status")
async def get_autopopulate_status(
    repo: ModelRepositoryV2 = Depends(get_model_repo_v2)
):
    needs_population = _get_models_needing_population(repo)
    total = repo.get_auto_discovered_models()

    return {
        "total_auto_discovered": len(total),
        "needs_population": len(needs_population),
        "population_complete": len(total) - len(needs_population)
    }
