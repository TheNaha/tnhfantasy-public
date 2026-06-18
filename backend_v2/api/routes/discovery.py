from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlmodel import Session
from typing import Optional

from api.deps import get_session
from services.provider_service import ProviderService
from infrastructure.logging import get_logger

logger = get_logger("discovery_router")

router = APIRouter(prefix="/api/v2/providers", tags=["providers_discovery"])

class DiscoveryPayload(BaseModel):
    provider_id: str
    provider_type: str
    status: str
    internal_url: str
    hostname: str

@router.post("/discovery")
async def handle_provider_discovery(
    payload: DiscoveryPayload,
    request: Request,
    session: Session = Depends(get_session),
):
    """
    Receive heartbeat/registration from self-discovering providers.
    
    Upserts the provider record in the database so that live provider
    containers are automatically registered. Providers that are never
    discovered are excluded from the active provider list.
    """
    logger.info("provider_discovered",
                provider_id=payload.provider_id,
                provider_type=payload.provider_type,
                url=payload.internal_url)

    service = ProviderService(session)
    await service.upsert_provider_from_discovery(
        provider_id=payload.provider_id,
        provider_type=payload.provider_type,
        internal_url=payload.internal_url,
    )

    return {"status": "registered", "provider_id": payload.provider_id}
