from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from api.deps import get_session
from core.entities import Provider
from core.exceptions import NotFoundError
from infrastructure.http_client import get_http_client
from infrastructure.logging import get_logger
from services.llm_config import resolve_default_provider, set_default_provider
from services.provider_runtime import resolve_provider_runtime_async

logger = get_logger("llm_config_route")
router = APIRouter()

class DefaultProviderResponse(BaseModel):
    provider_id: str
    model_id: str

@router.get("/default-provider", response_model=DefaultProviderResponse)
def get_default_provider(session: Session = Depends(get_session)):
    resolved = resolve_default_provider(session)
    if not resolved:
        raise NotFoundError("LLM provider", "default")
    return DefaultProviderResponse(provider_id=resolved[0], model_id=resolved[1])

class UpdateProviderRequest(BaseModel):
    provider_id: str
    model_id: str

@router.put("/default-provider")
def set_default_provider_endpoint(request: UpdateProviderRequest):
    set_default_provider(request.provider_id, request.model_id)
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
    except NotFoundError:
        return []

    provider = session.get(Provider, default.provider_id)
    if not provider:
        return []

    runtime = await resolve_provider_runtime_async(provider)
    if not runtime.worker_url:
        return []

    base_url = runtime.worker_url.rstrip("/")
    client = get_http_client()

    try:
        resp = await client.get(f"{base_url}/list-models", timeout=10.0)
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
    except Exception as exc:
        logger.debug("provider_model_fetch_failed", provider_id=provider.id, error=str(exc))

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
        select(Provider).where(Provider.worker_type == "llm")  # noqa: E712
    ).all()

    # Try to get default without raising
    default_id = None
    resolved = resolve_default_provider(session)
    if resolved:
        default_id = resolved[0]

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
        raise NotFoundError("LLM provider", provider_id)

    runtime = await resolve_provider_runtime_async(provider)
    if not runtime.worker_url:
        return {"healthy": False, "models": [], "error": "No worker URL configured for this provider"}

    base_url = runtime.worker_url.rstrip("/")
    models = []
    error = None
    healthy = False

    client = get_http_client()
    # Health check
    try:
        resp = await client.get(f"{base_url}/health", timeout=10.0)
        healthy = resp.status_code == 200
    except Exception as e:
        error = f"Health check failed: {e}"

    # Fetch models if healthy
    if healthy:
        try:
            resp = await client.get(f"{base_url}/list-models", timeout=10.0)
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
        except Exception as exc:
            logger.debug("llm_list_models_fetch_failed", url=base_url, error=str(exc))

    return {"healthy": healthy, "models": models, "error": error, "worker_url": base_url}
