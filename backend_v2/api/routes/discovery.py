from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Optional

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
async def handle_provider_discovery(payload: DiscoveryPayload, request: Request):
    """
    Receive heartbeat/registration from self-discovering providers.
    """
    logger.info("provider_discovered", 
                provider_id=payload.provider_id, 
                provider_type=payload.provider_type, 
                url=payload.internal_url)
    
    # In a full implementation, this would upsert the provider into the database
    # and mark it as ONLINE in the ProviderStatusService.
    # For now, we log it, and the backend relies on internal DNS to reach it.
    
    return {"status": "registered", "provider_id": payload.provider_id}
