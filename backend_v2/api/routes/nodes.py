from typing import Any

import httpx
from fastapi import APIRouter, Depends
from sqlmodel import Session

from api.deps import get_provider_service, get_session
from core.exceptions import (
    NotFoundError,
    ProviderError,
    ProviderTimeoutError,
    ValidationError,
)
from services.provider_runtime import resolve_provider_runtime

router = APIRouter(prefix="/api/nodes", tags=["nodes"])

@router.get("/object_info", response_model=dict[str, Any])
async def get_object_info(provider_id: str, session: Session = Depends(get_session)):
    """
    Fetch the node definition mapping (object_info) from a specific provider.
    This routes to the provider's CPU extraction endpoint.
    """
    service = get_provider_service(session)
    provider = service.get_provider(provider_id)
    if not provider:
        raise NotFoundError("Provider", provider_id)
        
    runtime = resolve_provider_runtime(provider)
    if not runtime.worker_url:
        raise ValidationError("Provider does not have a valid worker URL for extraction")
        
    try:
        # Increase timeout because CPU extraction spins up ComfyUI
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(f"{runtime.worker_url}/object-info")
            response.raise_for_status()
            return response.json()
    except httpx.TimeoutException:
        raise ProviderTimeoutError(provider_id, "Timeout while waiting for provider to extract node definitions")
    except Exception as e:
        raise ProviderError(provider_id, f"Failed to fetch object_info from provider: {e}")
