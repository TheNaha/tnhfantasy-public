import asyncio
from fastapi import APIRouter, Depends
from core.exceptions import NotFoundError, ValidationError, ComfyError
from sqlmodel import Session, select
from api.deps import get_session
from services.model_civitai_sync import ModelCivitaiSyncService
from core.entities_v2 import ModelV2

router = APIRouter(prefix="", tags=["Models"])


def _get_models_needing_population(session: Session) -> list:
    auto_discovered = session.exec(
        select(ModelV2).where(ModelV2.description.like("%Auto-discovered%"))
    ).all()
    return [
        m for m in auto_discovered
        if m.civitai_model_id is None or (m.description and "Auto-discovered" in m.description)
    ]


@router.post("/{model_id}/autopopulate")
async def autopopulate_model_details(model_id: str, session: Session = Depends(get_session)):
    repo = ModelCivitaiSyncService(session)
    try:
        return await repo.autopopulate_model(model_id)
    except ValueError as e:
        raise NotFoundError("Model", model_id)
    except Exception as e:
        raise ValidationError(str(e))


@router.post("/autopopulate-all")
async def autopopulate_all_models(
    session: Session = Depends(get_session),
):
    models_to_process = _get_models_needing_population(session)

    if not models_to_process:
        return {
            "status": "no_models_to_populate",
            "message": "No auto-discovered models need autopopulation",
            "count": 0
        }

    async def process_models():
        results = {"success": 0, "failed": 0, "not_found": 0, "errors": []}
        for model in models_to_process:
            try:
                repo = ModelCivitaiSyncService(session)
                await repo.autopopulate_model(str(model.id))
                results["success"] += 1
            except ValueError:
                results["not_found"] += 1
            except Exception as exc:
                results["failed"] += 1
                results["errors"].append({"model_id": str(model.id), "error": str(exc)})
        return results

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
            raise ComfyError(str(e))
    else:
        asyncio.create_task(process_models())
        return {
            "status": "processing",
            "message": f"Started autopopulation of {len(models_to_process)} models in background",
            "count": len(models_to_process)
        }


@router.get("/autopopulate-status")
async def get_autopopulate_status(
    session: Session = Depends(get_session)
):
    needs_population = _get_models_needing_population(session)
    total = session.exec(
        select(ModelV2).where(ModelV2.description.like("%Auto-discovered%"))
    ).all()

    return {
        "total_auto_discovered": len(total),
        "needs_population": len(needs_population),
        "population_complete": len(total) - len(needs_population)
    }
