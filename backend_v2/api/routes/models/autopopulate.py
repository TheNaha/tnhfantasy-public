from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlmodel import Session
from api.deps import get_session
from services.model_civitai_sync import ModelCivitaiSyncService
from services.external_model_service import ExternalModelService

router = APIRouter(prefix="", tags=["Models"])

@router.post("/{model_id}/autopopulate")
async def autopopulate_model_details(model_id: str, session: Session = Depends(get_session)):
    repo = ModelCivitaiSyncService(session)
    try:
        return await repo.autopopulate_model(model_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
