import hmac
import ipaddress
import os
import re
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.entities import VALID_TASK_TYPES

from api.deps import get_provider_service
from infrastructure.providers.provider_registry import ProviderRegistry
from infrastructure.logging import get_logger
from services.provider_service import ProviderService

logger = get_logger("discovery_router")

router = APIRouter(prefix="/api/v2/providers", tags=["providers_discovery"])

class DiscoveryPayload(BaseModel):
    provider_id: str
    provider_type: str
    worker_type: str = "image"
    # What this container can actually run, beyond its worker_type. Optional, and
    # absent from every worker that predates it — the backend then treats the
    # provider as serving its `worker_type` alone, which is exactly what it did
    # before, so an older container registers unchanged.
    capabilities: list[str] | None = None
    status: str
    internal_url: str
    hostname: str

@router.post("/discovery")
async def handle_provider_discovery(
    payload: DiscoveryPayload,
    request: Request,
    service: ProviderService = Depends(get_provider_service)
):
    """
    Receive heartbeat/registration from self-discovering providers.
    
    Upserts the provider record in the database so that live provider
    containers are automatically registered. Providers that are never
    discovered are excluded from the active provider list.
    """
    discovery_token = os.getenv("COMFY_DISCOVERY_TOKEN", "").strip()
    if not discovery_token:
        # Fails closed. The previous form was `if discovery_token and ...`,
        # which meant an unset token allowed ANY container on the bridge
        # network to register an arbitrary provider_id pointing at any
        # RFC1918 address — an unauthenticated job-hijack and
        # internal-network-fetch primitive.
        logger.error(
            "discovery_token_not_configured",
            hint="set COMFY_DISCOVERY_TOKEN in .env; refusing unauthenticated provider registration",
        )
        raise HTTPException(
            status_code=503,
            detail="COMFY_DISCOVERY_TOKEN is not configured on the backend",
        )
    provided = request.headers.get("X-Discovery-Token", "")
    if not provided or not hmac.compare_digest(provided, discovery_token):
        raise HTTPException(status_code=401, detail="invalid discovery token")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", payload.provider_id):
        raise HTTPException(status_code=422, detail="invalid provider_id")
    # `tts` was missing here, so a TTS worker was rejected outright with a 422 on
    # its first heartbeat — it could never register at all. That is the same
    # closed set the load balancer and `VALID_TASK_TYPES` already had to learn
    # about `tts`, and the check was the one place that was not updated.
    if payload.worker_type not in VALID_TASK_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"invalid worker_type; expected one of {sorted(VALID_TASK_TYPES)}",
        )
    # Validated here as well as on the write path, because a discovery payload
    # arrives over the network from a container and a typo in it would otherwise
    # register a provider that is silently offered nothing.
    if payload.capabilities:
        unknown = sorted(set(payload.capabilities) - VALID_TASK_TYPES)
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"unknown capabilities {unknown}; expected a subset of {sorted(VALID_TASK_TYPES)}",
            )
    if not ProviderRegistry.is_registered(payload.provider_type):
        raise HTTPException(status_code=422, detail="unknown provider_type")
    parsed_url = urlparse(payload.internal_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
        raise HTTPException(status_code=422, detail="invalid provider URL")
    try:
        address = ipaddress.ip_address(parsed_url.hostname)
    except ValueError:
        address = None
    if address and (address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified):
        raise HTTPException(status_code=422, detail="provider URL is not allowed")
    allowed_hosts = {
        host.strip().lower()
        for host in os.getenv("COMFY_DISCOVERY_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    }
    if allowed_hosts and parsed_url.hostname.lower() not in allowed_hosts:
        raise HTTPException(status_code=422, detail="provider host is not allowed")

    logger.info("provider_discovered",
                provider_id=payload.provider_id,
                provider_type=payload.provider_type,
                url=payload.internal_url)

    await service.upsert_provider_from_discovery(
        provider_id=payload.provider_id,
        provider_type=payload.provider_type,
        worker_type=payload.worker_type,
        capabilities=payload.capabilities,
        internal_url=payload.internal_url,
    )

    return {"status": "registered", "provider_id": payload.provider_id}
