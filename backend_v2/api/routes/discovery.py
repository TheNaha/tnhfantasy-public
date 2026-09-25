import ipaddress
import os
import re
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

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
    if discovery_token and request.headers.get("X-Discovery-Token", "") != discovery_token:
        raise HTTPException(status_code=401, detail="invalid discovery token")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", payload.provider_id):
        raise HTTPException(status_code=422, detail="invalid provider_id")
    if payload.worker_type not in {"image", "llm"}:
        raise HTTPException(status_code=422, detail="invalid worker_type")
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
        internal_url=payload.internal_url,
    )

    return {"status": "registered", "provider_id": payload.provider_id}
