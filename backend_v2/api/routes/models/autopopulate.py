from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlmodel import Session
from api.deps import get_session
from services.model_civitai_sync import ModelCivitaiSyncService
from services.external_model_service import ExternalModelService
from sqlmodel import select
from core.entities_v2 import ModelV2

router = APIRouter(prefix="", tags=["Models"])

@router.post("/{model_id}/autopopulate")
async def autopopulate_model_details(model_id: str, session: Session = Depends(get_session)):
    repo = ModelCivitaiSyncService(session)
    try:
        return await repo.autopopulate_model(model_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/autopopulate-all")
async def autopopulate_all_models(
    session: Session = Depends(get_session),
    background_tasks: BackgroundTasks = None
):
    """
    Autopopulate metadata for all models that were auto-discovered and are missing details.
    Returns immediately with a job ID for tracking progress.
    """
    # Find all models that need autopopulation (auto-discovered without full metadata)
    auto_discovered = session.exec(
        select(ModelV2).where(
            ModelV2.description.like("%Auto-discovered%")
        )
    ).all()

    # Filter to only those without civitai_id or with auto-discovered description
    models_to_process = []
    for model in auto_discovered:
        needs_population = (
            model.civitai_model_id is None or
            (model.description and "Auto-discovered" in model.description)
        )
        if needs_population:
            models_to_process.append(model)

    if not models_to_process:
        return {
            "status": "no_models_to_populate",
            "message": "No auto-discovered models need autopopulation",
            "count": 0
        }

    # Process in background to avoid timeout
    async def process_models():
        results = {"success": 0, "failed": 0, "not_found": 0, "errors": []}
        repo = ModelCivitaiSyncService(session)
        external = ExternalModelService()

        for model in models_to_process:
            try:
                # Search CivitAI for this model
                search_result = await external.search_civitai(model.name, limit=5)
                items = search_result.get("items", [])

                if not items:
                    results["not_found"] += 1
                    continue

                # Try to find a good match
                best_match = None
                for item in items:
                    item_name = item.get("name", "").lower()
                    model_name = model.name.lower()
                    # Check for name similarity
                    if model_name in item_name or item_name in model_name:
                        best_match = item
                        break

                if not best_match:
                    best_match = items[0]  # Use first result if no good match

                # Update model with CivitAI data
                model.civitai_model_id = best_match.get("id")
                if model.description and "Auto-discovered" in model.description:
                    model.description = best_match.get("description", model.description)
                model.nsfw = best_match.get("nsfw", model.nsfw)

                session.add(model)
                session.commit()
                results["success"] += 1

            except Exception as exc:
                results["failed"] += 1
                results["errors"].append({"model_id": model.id, "error": str(exc)})

        return results

    # For small batches, process synchronously
    if len(models_to_process) <= 5:
        try:
            results = await process_models()
            return {
                "status": "completed",
                "message": f"Processed {len(models_to_process)} models",
                "count": len(models_to_process),
                "results": results
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        # For larger batches, process in background
        background_tasks.add_task(process_models)
        return {
            "status": "processing",
            "message": f"Started autopopulation of {len(models_to_process)} models in background",
            "count": len(models_to_process)
        }


@router.get("/autopopulate-status")
async def get_autopopulate_status(
    session: Session = Depends(get_session)
):
    """Get count of models that need autopopulation."""
    auto_discovered = session.exec(
        select(ModelV2).where(
            ModelV2.description.like("%Auto-discovered%")
        )
    ).all()

    needs_population = [
        m for m in auto_discovered
        if m.civitai_model_id is None or (m.description and "Auto-discovered" in m.description)
    ]

    return {
        "total_auto_discovered": len(auto_discovered),
        "needs_population": len(needs_population),
        "population_complete": len(auto_discovered) - len(needs_population)
    }
