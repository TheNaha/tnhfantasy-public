# Provider routes - Complete implementation with feature parity to backend_v1
#
# KEY ENDPOINTS:
#   GET    /api/v2/providers              – List all configured providers
#   POST   /api/v2/providers              – Register a new provider
#   GET    /api/v2/providers/{id}         – Get provider details
#   PATCH  /api/v2/providers/{id}         – Update provider config/credentials
#   DELETE /api/v2/providers/{id}         – Remove provider + cascade status records
#   GET    /api/v2/providers/load-balancing – Current LB strategy
#   PUT    /api/v2/providers/load-balancing – Update LB strategy
import asyncio
import time
import uuid
from types import SimpleNamespace
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from api.deps import (
    get_provider_service,
    get_provider_status_service,
    get_session,
)
from core.entities import CATEGORY_LLM, CATEGORY_TTS, Provider
from infrastructure.http_client import get_http_client
from infrastructure.logging import api_logger
from services.provider_runtime import resolve_provider_runtime_async
from services.engines.registry import (
    matrix_cells,
    ui_schemas,
    validate_provider_payload,
)
from services.provider_status_service import invalidate_provider_status_caches
from services.load_balancer import LoadBalancer

logger = api_logger()




router = APIRouter()


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================


# The task types a provider declares it can serve. Spelled `worker_type` +
# `declared_capabilities` rather than reusing the name `capabilities`, which on
# the read path is the unrelated UI action map (`container`, `deploy`, `setup`,
# ...) that the frontend has always consumed under that key.
WorkerType = Literal["image", "llm", "tts"]
DeclaredCapability = Literal["image", "llm", "tts"]


class ProviderRequest(BaseModel):
    id: str
    type: str = "modal"
    worker_type: WorkerType | None = None
    declared_capabilities: list[DeclaredCapability] | None = None
    enabled: bool = True
    priority: int = 1
    credentials: dict[str, Any] = {}
    runtime_config: dict[str, Any] | None = None
    deploy_config: dict[str, Any] | None = None
    # Legacy compatibility fields accepted on write only.
    config: dict[str, Any] = {}
    container_config: dict[str, Any] | None = None


class ProviderUpdateRequest(BaseModel):
    type: str | None = None
    worker_type: WorkerType | None = None
    declared_capabilities: list[DeclaredCapability] | None = None
    enabled: bool | None = None
    priority: int | None = None
    credentials: dict[str, Any] | None = None
    runtime_config: dict[str, Any] | None = None
    deploy_config: dict[str, Any] | None = None
    # Legacy compatibility fields accepted on write only.
    config: dict[str, Any] | None = None
    container_config: dict[str, Any] | None = None


class LoadBalancingConfigRequest(BaseModel):
    strategy: str | None = None
    fallback_enabled: bool | None = None


class AddCustomProviderModelRequest(BaseModel):
    directory: str
    model_data: dict[str, Any]
    provider_ids: list[str]


class TestConnectionRequest(BaseModel):
    id: str | None = None
    type: str
    credentials: dict[str, Any] = {}
    config: dict[str, Any] = {}


def _is_healthy_status(health: dict[str, Any]) -> bool:
    """Shared ready predicate for the connection test bench.

    Accepts both "healthy" (engines) and "ok" (ping_provider's container
    dialect): the bench used to disagree with ping about the same provider.
    """
    return bool(health.get("ready") or health.get("status") in ("healthy", "ok"))



# ============================================================================
# LOAD BALANCER CONFIG
# ============================================================================


@router.get("/config/load-balancing")
async def get_load_balancing_config(session: Session = Depends(get_session)):
    """Get load balancing configuration with stats."""
    service = get_provider_service(session)
    config = service.get_load_balancing_config()
    stats = await service.get_load_balancer_stats()
    return {
        "config": {
            "strategy": config.strategy,
            "fallback_enabled": config.fallback_enabled
        },
        "stats": stats
    }


@router.put("/config/load-balancing")
async def update_load_balancing_config(
    request: LoadBalancingConfigRequest,
    session: Session = Depends(get_session)
):
    """Update load balancing configuration."""
    service = get_provider_service(session)
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    config = await service.update_load_balancing_config(**updates)
    return {
        "status": "success",
        "strategy": config.strategy,
        "fallback_enabled": config.fallback_enabled
    }


@router.get("/load-balancer/stats")
async def get_load_balancer_stats(session: Session = Depends(get_session)):
    """Get load balancer statistics."""
    service = get_provider_service(session)
    stats = await service.get_load_balancer_stats()
    return stats


# Alias paths for frontend compatibility
@router.get("/load-balancing")
async def get_load_balancing_alias(session: Session = Depends(get_session)):
    """Alias for /config/load-balancing."""
    return await get_load_balancing_config(session)


@router.put("/load-balancing")
async def update_load_balancing_alias(
    request: LoadBalancingConfigRequest,
    session: Session = Depends(get_session)
):
    """Alias for /config/load-balancing."""
    return await update_load_balancing_config(request, session)



# ============================================================================
# PROVIDER CRUD ENDPOINTS
# ============================================================================


async def _republish_known_provider_hosts() -> None:
    """Re-read the provider table after a write, so the token attachment is not stale.

    The set of hosts that count as "one of our providers" is published to
    `infrastructure.http_client` and read from the request path without touching
    the database — a blocking read inside `build_request()` is impossible to
    avoid, because `build_request` is synchronous and runs on the event loop. A
    provider create/update/delete changes the answer, so this is the invalidation
    point that the published cache is missing. Offloaded, and a failure is
    logged rather than raised: the loader publishes `None` on failure, which the
    request path already treats as "attach the token anyway".
    """
    from infrastructure.http_client import load_known_provider_hosts

    try:
        await asyncio.to_thread(load_known_provider_hosts, force=True)
    except Exception as exc:  # pragma: no cover - the loader handles its own failures
        logger.warning("provider_host_republish_failed", error=str(exc))


@router.post("/{provider_id}/ping")
async def ping_provider(provider_id: str, session: Session = Depends(get_session)):
    """Probe a provider's in-process engine and report latency."""
    provider = session.get(Provider, provider_id)
    if not provider:
        return {
            "healthy": False,
            "worker_url": None,
            "latency_ms": None,
            "error": "Provider not found",
        }

    base_url = None
    runtime = await resolve_provider_runtime_async(provider)
    if runtime.mode == "in_process":
        from services.engines.engine_factory import get_engine

        engine = get_engine(provider_id, provider)
        if engine:
            try:
                # Bounded: an engine whose upstream hangs must answer
                # unhealthy, not hang ping.
                health = await asyncio.wait_for(engine.check_health(), timeout=10.0)
            except Exception as exc:
                return {
                    "healthy": False,
                    "worker_url": "in_process",
                    "latency_ms": 0,
                    "error": str(exc),
                }
            # "ok" counts: llm_config.test_llm_provider treats healthy/ok/ready
            # as healthy, and engines report both vocabularies.
            is_healthy = bool(
                health.get("ready") or health.get("status") in ("healthy", "ok")
            )
            return {
                "healthy": is_healthy,
                "worker_url": "in_process",
                "latency_ms": health.get("latency_ms", 0),
                "error": None if is_healthy else health.get("error"),
            }

    if runtime.worker_url:
        base_url = runtime.worker_url.rstrip("/")
    if not base_url:
        return {
            "healthy": False,
            "worker_url": None,
            "latency_ms": None,
            "error": "No worker URL configured for this provider",
        }

    client = get_http_client()
    started = time.monotonic()
    try:
        resp = await client.get(f"{base_url}/health", timeout=10.0)
    except Exception as e:
        latency_ms = int((time.monotonic() - started) * 1000)
        return {
            "healthy": False,
            "worker_url": base_url,
            "latency_ms": latency_ms,
            "error": f"Health check failed: {e}",
        }
    latency_ms = int((time.monotonic() - started) * 1000)
    return {
        "healthy": resp.status_code == 200,
        "worker_url": base_url,
        "latency_ms": latency_ms,
        "error": None if resp.status_code == 200 else f"Health check failed: HTTP {resp.status_code}",
    }


# ============================================================================
# ENGINE SCHEMAS & INTERACTIVE TEST BENCH
# ============================================================================

# Canonical provider UI schemas (single source of truth):
# services/engines/registry.py ENGINE_SPECS. This alias preserves the
# `crud.ENGINE_SCHEMAS` import path used by routes and tests.
ENGINE_SCHEMAS: dict[str, dict[str, Any]] = ui_schemas()


@router.get("/schemas")
def get_provider_schemas():
    """Return declarative schemas and field definitions for supported provider engines.

    Built per request from the registry (not the import-time ENGINE_SCHEMAS
    alias, which exists only for the `crud.ENGINE_SCHEMAS` import path used
    by routes and tests): the dict is small and a stale import would serve a
    previous registry after an edit.
    """
    # Both axes plus the matrix, so the provider modal renders the same
    # category x transport grid the registry declares — including the cells
    # with no engine, which the frontend shows as unavailable rather than as
    # choices nobody thought to make.
    return {
        "engines": ui_schemas(),
        "categories": [
            {"id": "image", "label": "Image Generation", "icon": "image"},
            {"id": "llm", "label": "Language Models (LLM)", "icon": "message-square"},
            {"id": "tts", "label": "Voice & Audio (TTS)", "icon": "mic"},
        ],
        "transports": [
            {"id": "modal", "label": "Modal (serverless)", "icon": "cloud"},
            {"id": "beam", "label": "Beam.cloud (serverless)", "icon": "cloud-lightning"},
            {"id": "remote", "label": "Self-hosted container", "icon": "server"},
            {"id": "direct", "label": "Direct API endpoint", "icon": "plug"},
        ],
        "matrix": matrix_cells(),
    }


def _merged_save_config(*dicts: dict[str, Any] | None) -> dict[str, Any]:
    """Merge legacy + current config keys into one dict for validation.

    Providers have been written with `config`, `runtime_config`, and
    `container_config` over time; validation must see the union so a URL
    stored under any legacy key still satisfies its schema field.
    """
    merged: dict[str, Any] = {}
    for part in dicts:
        if part:
            merged.update(part)
    return merged


def _raise_for_save_errors(
    provider_type: str,
    credentials: dict[str, Any] | None,
    config: dict[str, Any] | None,
) -> None:
    errors = validate_provider_payload(provider_type, credentials or {}, config or {})
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})


@router.post("/test-connection")
async def test_provider_connection(request: TestConnectionRequest):
    """Test connection and authentication for an engine configuration without saving."""
    from services.engines.engine_factory import can_create_engine, get_engine, invalidate_engine

    schema = ENGINE_SCHEMAS.get(request.type)
    worker_type = schema.get("worker_type", "image") if schema else "image"
    # uuid4: two rapid clicks on Test must never share a factory-cache key.
    temp_id = f"__test_conn_{uuid.uuid4().hex}__"
    mock_provider = SimpleNamespace(
        id=temp_id,
        type=request.type,
        worker_type=worker_type,
        capabilities=[worker_type],
        credentials=request.credentials,
        config=request.config,
    )

    if not can_create_engine(mock_provider):
        return {
            "healthy": False,
            "status": "unhealthy",
            "ready": False,
            "latency_ms": None,
            "error": "Required credentials or configuration missing for this engine",
        }

    try:
        engine = get_engine(temp_id, mock_provider)
        if not engine:
            return {
                "healthy": False,
                "status": "unhealthy",
                "ready": False,
                "latency_ms": None,
                "error": "Failed to initialize engine",
            }

        health = await asyncio.wait_for(engine.check_health(), timeout=15.0)
        is_healthy = _is_healthy_status(health)
        return {
            "healthy": is_healthy,
            "status": health.get("status", "healthy" if is_healthy else "unhealthy"),
            "ready": is_healthy,
            "latency_ms": health.get("latency_ms"),
            "details": health,
            "error": health.get("error"),
        }
    except Exception as exc:
        return {
            "healthy": False,
            "status": "unhealthy",
            "ready": False,
            "latency_ms": None,
            "error": str(exc),
        }
    finally:
        invalidate_engine(temp_id)


@router.post("/{provider_id}/test")
async def test_existing_provider(provider_id: str, session: Session = Depends(get_session)):
    """Test connection and health of an existing registered provider."""
    provider = session.get(Provider, provider_id)
    if not provider:
        return {"healthy": False, "status": "not_found", "error": f"Provider '{provider_id}' not found"}

    from services.engines.engine_factory import can_create_engine, get_engine

    if can_create_engine(provider):
        engine = get_engine(provider_id, provider)
        if engine:
            try:
                health = await asyncio.wait_for(engine.check_health(), timeout=15.0)
                # Deliberately NOT invalidated: this engine was built from the
                # live DB row, so caching it warms dispatch; update/delete
                # already invalidate on write. Only __test_conn_* temp ids
                # must be evicted (handled in /test-connection's finally).
                is_healthy = _is_healthy_status(health)
                return {
                    "healthy": is_healthy,
                    "status": health.get("status", "healthy" if is_healthy else "unhealthy"),
                    "ready": is_healthy,
                    "latency_ms": health.get("latency_ms"),
                    "details": health,
                    "error": health.get("error"),
                }
            except Exception as exc:
                return {
                    "healthy": False,
                    "status": "unhealthy",
                    "ready": False,
                    "latency_ms": None,
                    "error": str(exc),
                }

    # Fallback to ping_provider
    return await ping_provider(provider_id, session)


@router.get("/{provider_id}/models/discovered")
async def get_provider_discovered_models(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """Query live upstream models/voices exposed directly by the provider engine."""
    provider = session.get(Provider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")

    from services.engines.engine_factory import can_create_engine, get_engine
    if not can_create_engine(provider):
        return {"provider_id": provider_id, "models": [], "count": 0, "error": "Provider not configured for in-process engine"}

    engine = get_engine(provider_id, provider)
    if not engine:
        return {"provider_id": provider_id, "models": [], "count": 0, "error": "Could not instantiate engine"}

    try:
        models = []
        # Route on the provider's CATEGORY, not on a list of type names. A list
        # of type names is how `remote_tts` / `beam_tts` / `direct_tts` would fall
        # through to the image branch and return a checkpoint listing as a voice
        # catalogue. `modal_llm` was in the LLM list below until it stopped being
        # a type at all; category has no such duplicate.
        category = provider.category
        if category == CATEGORY_TTS:
            # Kokoro / TTS voice catalogue (static: the TTS engine exposes no
            # live voice-listing endpoint, so in-process returns [].).
            default_voices = [
                {"name": "af_bella", "id": "af_bella", "type": "voice", "gender": "female", "accent": "American"},
                {"name": "af_sarah", "id": "af_sarah", "type": "voice", "gender": "female", "accent": "American"},
                {"name": "am_adam", "id": "am_adam", "type": "voice", "gender": "male", "accent": "American"},
                {"name": "am_michael", "id": "am_michael", "type": "voice", "gender": "male", "accent": "American"},
                {"name": "bf_emma", "id": "bf_emma", "type": "voice", "gender": "female", "accent": "British"},
                {"name": "bf_isabella", "id": "bf_isabella", "type": "voice", "gender": "female", "accent": "British"},
                {"name": "bm_george", "id": "bm_george", "type": "voice", "gender": "male", "accent": "British"},
                {"name": "bm_lewis", "id": "bm_lewis", "type": "voice", "gender": "male", "accent": "British"},
            ]
            models = default_voices
        elif category == CATEGORY_LLM:
            models = await asyncio.wait_for(engine.list_models(), timeout=12.0)
        else:
            checkpoints = await asyncio.wait_for(engine.list_models("checkpoints"), timeout=15.0)
            models = checkpoints

        return {
            "provider_id": provider_id,
            "type": provider.type,
            "models": models,
            "count": len(models),
            "source": "catalogue" if category == CATEGORY_TTS else "live",
        }
    except Exception as exc:
        logger.warning("provider_discovered_models_failed", provider_id=provider_id, error=str(exc))
        return {
            "provider_id": provider_id,
            "type": provider.type,
            "models": [],
            "count": 0,
            "error": str(exc),
        }


@router.get("/{provider_id}/diagnostics")
async def get_provider_diagnostics(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """Fetch deep real-time diagnostics, health probing, and system telemetry."""
    provider = session.get(Provider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")

    from services.engines.engine_factory import can_create_engine, get_engine
    from services.provider_runtime import resolve_provider_runtime_async

    runtime = await resolve_provider_runtime_async(provider)
    engine_constructible = can_create_engine(provider)

    t0 = time.monotonic()
    health_result: dict[str, Any] = {}
    engine_name = "None"

    if engine_constructible:
        engine = get_engine(provider_id, provider)
        if engine:
            engine_name = engine.__class__.__name__
            try:
                health_result = await asyncio.wait_for(engine.check_health(), timeout=15.0)
            except Exception as exc:
                health_result = {"status": "unhealthy", "ready": False, "error": str(exc)}

    latency_ms = health_result.get("latency_ms") or round((time.monotonic() - t0) * 1000, 2)
    is_healthy = bool(health_result.get("ready") or health_result.get("status") == "healthy")

    return {
        "provider_id": provider_id,
        "type": provider.type,
        "worker_type": provider.worker_type,
        "enabled": provider.enabled,
        "priority": provider.priority,
        "runtime_mode": getattr(runtime, "mode", "in_process"),
        "engine_name": engine_name,
        "healthy": is_healthy,
        "status": "healthy" if is_healthy else "unhealthy",
        "latency_ms": latency_ms,
        "telemetry": health_result,
        "capabilities": provider.capabilities or [provider.worker_type or "image"],
        "timestamp": time.time(),
    }


@router.get("/")
async def list_providers(session: Session = Depends(get_session)):
    """List all providers."""
    service = get_provider_service(session)
    providers = await service.list_providers()
    status_service = get_provider_status_service(session)
    records = await status_service.build_provider_records(providers)
    return {"providers": records, "count": len(records)}


@router.post("/")
async def create_provider(
    request: ProviderRequest,
    session: Session = Depends(get_session)
):
    """Create a new provider."""
    _raise_for_save_errors(
        request.type,
        request.credentials,
        _merged_save_config(request.config, request.runtime_config, request.container_config),
    )
    service = get_provider_service(session)
    payload = request.model_dump()
    # The wire field is `declared_capabilities`; the service's normalizer and
    # the DB column both call it `capabilities`. Renamed here rather than in
    # the service so the one place that owns the vocabulary is this one.
    payload["capabilities"] = payload.pop("declared_capabilities", None)
    provider = await service.create_provider(payload)
    await _republish_known_provider_hosts()
    status_service = get_provider_status_service(session)
    return await status_service.build_provider_record(provider.id, provider=provider)


@router.get("/{provider_id}")
async def get_provider(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """Get a provider by ID."""
    status_service = get_provider_status_service(session)
    return await status_service.build_provider_record(provider_id)


@router.put("/{provider_id}")
async def update_provider(
    provider_id: str,
    request: ProviderUpdateRequest,
    session: Session = Depends(get_session)
):
    """Update a provider."""
    service = get_provider_service(session)
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if any(k in updates for k in ("type", "credentials", "config", "runtime_config", "container_config")):
        existing = session.get(Provider, provider_id)
        if existing is not None:
            _raise_for_save_errors(
                updates.get("type", existing.type),
                updates.get("credentials", existing.credentials or {}),
                _merged_save_config(
                    (existing.config or {}),
                    updates.get("config"),
                    updates.get("runtime_config"),
                    updates.get("container_config"),
                ),
            )
    service = get_provider_service(session)
    if "declared_capabilities" in updates:
        updates["capabilities"] = updates.pop("declared_capabilities")
    provider = await service.update_provider(provider_id, updates)
    await _republish_known_provider_hosts()
    # Credentials/config may have rotated: drop the cached in-process engine
    # (and its health verdict) so the next use rebuilds from the new values.
    from services.engines.engine_factory import invalidate_engine
    invalidate_engine(provider_id)
    invalidate_provider_status_caches(provider_id)
    # `enabled` decides which providers the balancer will route to at all, so
    # a toggle changes the answer `resolve_checkpoint` and
    # `get_available_checkpoint` cache for up to 30 s. Both caches are
    # cleared through the one invalidation entry point.
    if "enabled" in updates or "capabilities" in updates:
        LoadBalancer.invalidate_model_availability_cache(provider_id=provider_id)
    status_service = get_provider_status_service(session)
    return await status_service.build_provider_record(provider.id, provider=provider)


# PATCH alias for frontend compatibility
@router.patch("/{provider_id}")
async def patch_provider(
    provider_id: str,
    request: ProviderUpdateRequest,
    session: Session = Depends(get_session)
):
    """Update a provider (PATCH alias)."""
    return await update_provider(provider_id, request, session)


@router.post("/{provider_id}/worker-token")
async def mint_provider_worker_token(provider_id: str, session: Session = Depends(get_session)):
    """Mint (or rotate) the external-worker token for a provider.

    The `/ws/worker/{provider_id}` WebSocket authenticates against
    `config.worker_token`, and nothing could produce that key — so the check could
    only ever fail, no worker could register, and the `external_worker` runtime
    mode was unreachable. This is the missing producer.

    The token is returned in this response and is not readable again: minting
    again rotates it, which is also how a leaked token is invalidated.
    """
    service = get_provider_service(session)
    token = await service.mint_worker_token(provider_id)
    return {"provider_id": provider_id, "worker_token": token}


@router.delete("/{provider_id}/worker-token")
async def revoke_provider_worker_token(provider_id: str, session: Session = Depends(get_session)):
    """Revoke the external-worker token, disabling the mode for this provider."""
    service = get_provider_service(session)
    revoked = await service.revoke_worker_token(provider_id)
    return {"provider_id": provider_id, "revoked": revoked}


@router.delete("/{provider_id}")
async def delete_provider(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """Delete a provider."""
    service = get_provider_service(session)
    await service.delete_provider(provider_id)
    from services.engines.engine_factory import invalidate_engine
    invalidate_engine(provider_id)
    invalidate_provider_status_caches(provider_id)
    await _republish_known_provider_hosts()
    return {"status": "success"}


