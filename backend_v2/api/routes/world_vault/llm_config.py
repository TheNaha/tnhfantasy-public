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
    # Check for an explicit user-set override first
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                data = json.load(f)
                if "provider_id" in data and "model_id" in data:
                    # Verify the stored provider still exists in DB
                    provider_in_db = session.get(Provider, data["provider_id"])
                    if provider_in_db and provider_in_db.enabled and provider_in_db.worker_type == "llm":
                        return DefaultProviderResponse(provider_id=data["provider_id"], model_id=data["model_id"])
        except Exception:
            pass
                
    # Auto-select from DB: prefer direct_url/local providers over others
    providers = session.exec(
        select(Provider).where(Provider.worker_type == "llm", Provider.enabled == True)
    ).all()
    
    if not providers:
        raise HTTPException(status_code=404, detail="No LLM providers available")
        
    # Priority: explicitly local/direct_url type first, then first available
    selected = (
        next((p for p in providers if p.type in ("direct_url", "openai_compat") or "local" in p.id.lower()), None)
        or providers[0]
    )
        
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

    Queries the provider worker's `/list-models` endpoint, which proxies the
    upstream model list per engine (OpenAI-compat `/models`, Anthropic, Gemini)
    with engine-specific fallbacks.
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
        try:
            resp = await client.get(f"{base_url}/list-models")
            if resp.status_code == 200:
                data = resp.json()
                files = []
                if isinstance(data, dict):
                    files = data.get("files") or data.get("models") or []
                    if isinstance(files, dict):
                        files = files.get("files", [])
                if isinstance(files, list):
                    models = []
                    for m in files:
                        if isinstance(m, str):
                            models.append({"id": m, "name": m})
                        elif isinstance(m, dict):
                            model_id = m.get("id") or m.get("path") or m.get("name")
                            if model_id:
                                models.append({"id": model_id, "name": m.get("name") or model_id})
                    if models:
                        return models
        except Exception:
            pass

    # Fallback: return provider record itself as a selectable "model"
    return [{"id": "default", "name": f"{provider.id} (default)"}]


class LLMProviderInfo(BaseModel):
    provider_id: str
    provider_type: str
    enabled: bool
    is_default: bool


@router.get("/providers", response_model=list[LLMProviderInfo])
def list_llm_providers(session: Session = Depends(get_session)):
    """List all registered LLM providers."""
    providers = session.exec(
        select(Provider).where(Provider.worker_type == "llm")
    ).all()

    # Try to get default without raising
    try:
        default = get_default_provider(session)
        default_id = default.provider_id
    except HTTPException:
        default_id = None

    return [
        LLMProviderInfo(
            provider_id=p.id,
            provider_type=p.type,
            enabled=p.enabled,
            is_default=p.id == default_id,
        )
        for p in providers
    ]


@router.post("/providers/{provider_id}/test")
async def test_llm_provider(provider_id: str, session: Session = Depends(get_session)):
    """Test connectivity to an LLM provider worker. Returns health status and available models."""
    provider = session.get(Provider, provider_id)
    if not provider or provider.worker_type != "llm":
        raise HTTPException(status_code=404, detail="LLM provider not found")

    runtime = resolve_provider_runtime(provider)
    if not runtime.worker_url:
        return {"healthy": False, "models": [], "error": "No worker URL configured for this provider"}

    base_url = runtime.worker_url.rstrip("/")
    models = []
    error = None
    healthy = False

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Health check
        try:
            resp = await client.get(f"{base_url}/health")
            healthy = resp.status_code == 200
        except Exception as e:
            error = f"Health check failed: {e}"

        # Fetch models if healthy
        if healthy:
            try:
                resp = await client.get(f"{base_url}/list-models")
                if resp.status_code == 200:
                    data = resp.json()
                    files = data.get("files", []) if isinstance(data, dict) else []
                    if isinstance(files, list):
                        models = [
                            m.get("id") or m.get("path") or m.get("name", "?")
                            for m in files if isinstance(m, dict)
                        ]
                        if not models:
                            models = [m for m in files if isinstance(m, str)]
            except Exception:
                pass

    return {"healthy": healthy, "models": models, "error": error, "worker_url": base_url}


