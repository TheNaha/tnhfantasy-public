import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from api.deps import get_session
from core.entities import Provider
from core.exceptions import NotFoundError, ValidationError
from infrastructure.http_client import get_http_client
from infrastructure.logging import get_logger
from services.llm_config import resolve_default_provider, set_default_provider
from services.provider_runtime import resolve_provider_runtime_async

logger = get_logger("llm_config_route")
router = APIRouter()

class DefaultProviderResponse(BaseModel):
    provider_id: str
    model_id: str


class UpdateActiveModelsRequest(BaseModel):
    active_rp: str | None = None
    active_util: str | None = None
    active_image: str | None = None


@router.get("/catalog")
def get_model_catalog():
    """Return the complete model catalog, roles, active selections, and download specifications."""
    from services.llm_config import get_active_models
    from services.llm_router import get_router

    router_inst = get_router()
    registry = router_inst.registry
    active = get_active_models(registry)
    rp_active = active.get("rp") or registry.primary("rp").id
    util_active = active.get("util") or registry.primary("util").id

    return {
        "catalog": registry.catalog(),
        "roles": {
            role: {
                "active": active.get(role) or registry.primary(role).id,
                "primary": registry.primary(role).id,
                "chain": [m.id for m in registry.enabled_for(role)],
            }
            for role in sorted(registry.fallback)
        },
        "active": {
            "rp": rp_active,
            "util": util_active,
            "image": active.get("image", ""),
        },
        "shared_weights": rp_active == util_active,
    }


@router.put("/catalog/active")
def set_active_models_endpoint(request: UpdateActiveModelsRequest):
    """Update active rp, util, and image models."""
    from services.llm_config import set_active_models
    from services.llm_router import get_router, refresh_router

    registry = get_router().registry
    if request.active_rp and request.active_rp not in registry.models:
        raise ValidationError(f"Model '{request.active_rp}' not found in registry")
    if request.active_util and request.active_util not in registry.models:
        raise ValidationError(f"Model '{request.active_util}' not found in registry")

    active = set_active_models(
        active_rp=request.active_rp,
        active_util=request.active_util,
        active_image=request.active_image,
    )
    refresh_router()
    return {"status": "success", "active": active}


@router.get("/default-provider", response_model=DefaultProviderResponse | None)
def get_default_provider(session: Session = Depends(get_session)):
    """Return the resolved default LLM provider/model, or `null` if there is none.

    "No LLM provider is configured yet" is a normal state, not a missing
    resource, so it answers 200 with a null body. This used to raise
    `NotFoundError("LLM provider", "default")` — "default" is a placeholder, not
    a provider id, so the response was the nonsense message
    `LLM provider 'default' not found`. On a fresh install with no LLM provider
    enabled that 404 fired on every page load of /chat, /story and /roleplay,
    and the frontend had to special-case it
    (frontend_v2/src/hooks/useLLMProviderStatus.js:29-33).

    200 + `null` satisfies that hook without the special case: it reads the
    JSON and treats a falsy value as "no default".
    """
    resolved = resolve_default_provider(session)
    if not resolved:
        return None
    return DefaultProviderResponse(provider_id=resolved[0], model_id=resolved[1])

@router.get("/routing")
def get_llm_routing():
    """Describe the rp/util model router.

    The two-role split exists because an rp model is chosen for prose and a util
    model for structure, and neither does the other's job. This is what makes
    that legible: which model each role resolves to, the fallback chain behind
    it, and which job kinds belong to which role.

    Without it the split is invisible — a user cannot tell why a chat reply comes
    from one model and a memory extraction from another, nor that editing
    `modal_llm/models.json` is how it changes.
    """
    from services.llm_router import get_router

    return get_router().describe()


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
    # The route awaits the worker, so the two session reads move to a thread.
    provider = await asyncio.to_thread(_default_provider_row, session)
    if not provider:
        return []

    runtime = await resolve_provider_runtime_async(provider)
    if runtime.mode == "in_process":
        try:
            from services.engines.engine_factory import get_engine

            engine = get_engine(provider.id, provider)
            if engine is not None:
                files = await engine.list_models("")
                models = []
                for m in files or []:
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
        return [{"id": "default", "name": f"{provider.id} (default)"}]

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


def _default_provider_row(session: Session) -> Provider | None:
    """The default LLM provider row, or None.

    Synchronous on purpose: the callers await the provider worker, so they
    cannot be plain `def` routes and these queries would run on the event loop.
    """
    resolved = resolve_default_provider(session)
    if not resolved:
        return None
    return session.get(Provider, resolved[0])


class LLMProviderInfo(BaseModel):
    provider_id: str
    provider_type: str
    enabled: bool
    is_default: bool


@router.get("/providers", response_model=list[LLMProviderInfo])
def list_llm_providers(session: Session = Depends(get_session)):
    """List all registered LLM providers."""
    providers = session.exec(
        select(Provider).where(Provider.worker_type.in_(["llm", "hybrid"]))  # noqa: E712
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
    # The route awaits the worker, so the provider lookup moves to a thread.
    provider = await asyncio.to_thread(_llm_provider_row, session, provider_id)

    runtime = await resolve_provider_runtime_async(provider)
    if runtime.mode == "in_process":
        models = []
        error = None
        healthy = False
        try:
            from services.engines.engine_factory import get_engine

            engine = get_engine(provider.id, provider)
            if engine is None:
                return {"healthy": False, "models": [], "error": "No in-process engine available for this provider"}
            health = await engine.check_health()
            healthy = health.get("status") in ("healthy", "ok") or bool(health.get("ready", False))
            try:
                files = await engine.list_models("")
                for m in files or []:
                    if isinstance(m, dict):
                        models.append(m.get("id") or m.get("path") or m.get("name", "?"))
                    elif isinstance(m, str):
                        models.append(m)
            except Exception as exc:
                logger.debug("llm_list_models_fetch_failed", provider_id=provider.id, error=str(exc))
        except Exception as e:
            error = f"Health check failed: {e}"
        return {"healthy": healthy, "models": models, "error": error, "worker_url": None}

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


def _llm_provider_row(session: Session, provider_id: str) -> Provider:
    """The LLM provider row, or 404.

    Synchronous on purpose: the caller awaits the provider worker, so it cannot
    be a plain `def` route and this lookup would run on the event loop.
    """
    provider = session.get(Provider, provider_id)
    if not provider or (provider.worker_type not in ("llm", "hybrid") and not (hasattr(provider, "serves") and provider.serves("llm"))):
        raise NotFoundError("LLM provider", provider_id)
    return provider
