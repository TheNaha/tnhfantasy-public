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
    """Return models available from the default LLM provider.

    Tries the OpenAI-compat `/v1/models` endpoint first (Ollama, LM Studio, etc.),
    falls back to listing providers as model identities if the endpoint fails.
    """
    try:
        default = get_default_provider(session)
    except HTTPException:
        return []

    provider = session.get(Provider, default.provider_id)
    if not provider:
        return []

    runtime = resolve_provider_runtime(provider)
    if not runtime.worker_url:
        return []

    base_url = runtime.worker_url.rstrip("/")

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Try OpenAI-compat /v1/models (Ollama, LM Studio, etc.)
        for path in ("/v1/models", "/api/tags", "/models"):
            try:
                resp = await client.get(f"{base_url}{path}")
                if resp.status_code == 200:
                    data = resp.json()
                    # OpenAI-compat: {"object": "list", "data": [...]}
                    if isinstance(data, dict) and "data" in data:
                        return [
                            {"id": m.get("id", m.get("name", "unknown")),
                             "name": m.get("id", m.get("name", "unknown"))}
                            for m in data["data"]
                        ]
                    # Ollama /api/tags: {"models": [{"name": "llama3:latest", ...}]}
                    if isinstance(data, dict) and "models" in data:
                        return [
                            {"id": m.get("name", m.get("model", "unknown")),
                             "name": m.get("name", m.get("model", "unknown"))}
                            for m in data["models"]
                        ]
                    # Bare list
                    if isinstance(data, list):
                        return [
                            {"id": m.get("id", m.get("name", "unknown")),
                             "name": m.get("id", m.get("name", "unknown"))}
                            for m in data
                        ]
            except Exception:
                continue

    # Fallback: return provider record itself as a selectable "model"
    return [{"id": "default", "name": f"{provider.id} (default)"}]

