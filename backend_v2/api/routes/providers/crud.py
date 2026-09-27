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
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from api.deps import (
    get_container_manager,
    get_provider_service,
    get_provider_status_service,
    get_provider_worker_url,
    get_session,
)
from core.entities import Provider
from infrastructure.background_tasks import start_background_task
from infrastructure.http_client import get_http_client
from infrastructure.logging import api_logger
from services.provider_runtime import resolve_provider_runtime_async
from services.provider_service import ProviderService
from services.provider_status_service import invalidate_provider_status_caches

logger = api_logger()




router = APIRouter()


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================


class ProviderRequest(BaseModel):
    id: str
    type: str = "modal"
    worker_type: str | None = None
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
    worker_type: str | None = None
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


@router.post("/wake")
async def wake_providers(session: Session = Depends(get_session)):
    """Ping enabled provider containers to wake them up from cold start."""
    service = get_provider_service(session)
    providers = service.get_enabled_providers()
    active_providers = [provider for provider in providers if provider.container_config]
    
    if not active_providers:
        return {"status": "success", "message": "No active containerized providers to wake"}

    async def ping_containers():
        http_client = get_http_client()

        async def ping_worker(provider_id: str):
            try:
                await http_client.get(
                    f"{get_provider_worker_url(provider_id)}/health",
                    timeout=5.0,
                )
            except Exception as exc:
                logger.debug("worker_ping_failed", provider_id=provider_id, error=str(exc))

        await asyncio.gather(
            *(ping_worker(provider.id) for provider in active_providers),
            return_exceptions=True,
        )

    start_background_task(ping_containers(), task_name="wake_provider_containers")
    
    return {"status": "success", "message": f"Wake signal sent to {len(active_providers)} providers"}


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


def _infer_discovery_type(provider_id: str) -> tuple[str, str]:
    """Map a container-derived provider id to (provider_type, worker_type).

    Mirrors what the provider containers themselves heartbeat (see
    image_worker/worker.py and llm_worker/worker.py) so a detected row
    matches what discovery would eventually create.
    """
    if provider_id == "llm-local" or "llm" in provider_id:
        return "openai_compat", "llm"
    if provider_id.startswith("modal-"):
        return "modal", "image"
    if provider_id.startswith("beam-"):
        return "beam", "image"
    if provider_id == "direct-url":
        return "direct_url", "image"
    return "direct_url", "image"


@router.post("/detect")
async def detect_provider_containers(
    container_manager = Depends(get_container_manager),
    service: ProviderService = Depends(get_provider_service),
):
    """Register running provider containers that are not yet providers.

    Scans deployment-managed containers (label comfy-provider=true) and
    compose-managed `tnhcomfy-*` containers when a container runtime socket
    is available, upserting the missing ones via the same path discovery
    heartbeats use. When no socket is available (typical compose setup),
    container workers self-register through their heartbeat — this endpoint
    then reports what is already known.
    """
    container_runtime_available = container_manager is not None
    existing = {p.id for p in service.repo.get_all()}
    candidates: dict[str, str] = {}

    if container_manager:
        for entry in container_manager.list_containers():
            name = entry.get("name") or ""
            provider_id = entry.get("provider_id") or (
                name[len("tnhcomfy-"):] if name.startswith("tnhcomfy-") else None
            )
            if provider_id:
                candidates[provider_id] = name

        try:
            raw = container_manager.client.containers.list(all=False)
        except Exception as exc:
            logger.warning("detect_container_scan_failed", error=str(exc))
            raw = []
            container_runtime_available = False

        skip_prefixes = ("tnhcomfy-backend", "tnhcomfy-frontend", "tnhcomfy-db", "tnhcomfy-deploy-")
        for container in raw:
            name = container.name
            if not name.startswith("tnhcomfy-"):
                continue
            if name.startswith(skip_prefixes):
                continue
            provider_id = (container.labels or {}).get("provider-id") or name[len("tnhcomfy-"):]
            candidates[provider_id] = name

    created: list[str] = []
    for provider_id, container_name in sorted(candidates.items()):
        if provider_id in existing:
            continue
        provider_type, worker_type = _infer_discovery_type(provider_id)
        await service.upsert_provider_from_discovery(
            provider_id=provider_id,
            provider_type=provider_type,
            worker_type=worker_type,
            internal_url=f"http://{container_name}:8000",
        )
        created.append(provider_id)

    already = sorted(existing)
    logger.info("providers_detected", created=created, already=already,
                container_runtime_available=container_runtime_available)
    return {
        "created": created,
        "already": already,
        "container_runtime_available": container_runtime_available,
    }


@router.post("/{provider_id}/ping")
async def ping_provider(provider_id: str, session: Session = Depends(get_session)):
    """Ping a provider worker from the backend network and report latency.

    Browsers cannot resolve docker-internal worker hostnames (tnhcomfy-<id>),
    so the health probe is proxied through the backend instead of being
    fetched directly from the client.
    """
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
    if runtime.worker_url:
        base_url = runtime.worker_url.rstrip("/")
    elif provider.container_config:
        base_url = get_provider_worker_url(provider_id).rstrip("/")
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
    service = get_provider_service(session)
    provider = await service.create_provider(request.model_dump())
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
    provider = await service.update_provider(provider_id, updates)
    await _republish_known_provider_hosts()
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
    invalidate_provider_status_caches(provider_id)
    await _republish_known_provider_hosts()
    return {"status": "success"}


