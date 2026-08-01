import json
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from api.deps import get_session
from core.entities import Provider
from services.provider_runtime import resolve_provider_runtime

router = APIRouter()

CONFIG_PATH = "/data/llm_config.json"

class DefaultProviderResponse(BaseModel):
    provider_id: str
    model_id: str

@router.get("/default-provider", response_model=DefaultProviderResponse)
def get_default_provider(session: Session = Depends(get_session)):
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            data = json.load(f)
            if "provider_id" in data and "model_id" in data:
                return DefaultProviderResponse(provider_id=data["provider_id"], model_id=data["model_id"])
                
    providers = session.exec(select(Provider).where(Provider.worker_type == "llm", Provider.enabled == True)).all()
    if not providers:
        raise HTTPException(status_code=404, detail="No LLM providers available")
        
    if len(providers) == 1:
        selected = providers[0]
    else:
        selected = next((p for p in providers if p.type == "direct_url" or "local" in p.id.lower()), providers[0])
        
    return DefaultProviderResponse(provider_id=selected.id, model_id="default")

class UpdateProviderRequest(BaseModel):
    provider_id: str
    model_id: str

@router.put("/default-provider")
def set_default_provider(request: UpdateProviderRequest):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(request.model_dump(), f)
    return {"status": "success"}

@router.get("/available-models")
async def get_available_models(session: Session = Depends(get_session)):
    default = get_default_provider(session)
    provider = session.get(Provider, default.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Default provider not found")
        
    runtime = resolve_provider_runtime(provider)
    if not runtime.worker_url:
        return []

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{runtime.worker_url}/models")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
        
    return [{"id": "default", "name": "Default Model"}]
