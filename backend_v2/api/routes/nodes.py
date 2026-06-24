import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from typing import Dict, Any

from api.deps import get_session
from infrastructure.repositories.provider_repo import ProviderRepository
from services.provider_runtime import resolve_provider_runtime

router = APIRouter(prefix="/api/nodes", tags=["nodes"])

@router.get("/object_info", response_model=Dict[str, Any])
async def get_object_info(provider_id: str, session: Session = Depends(get_session)):
    """
    Fetch the node definition mapping (object_info) from a specific provider.
    This routes to the provider's CPU extraction endpoint.
    """
    repo = ProviderRepository(session)
    provider = repo.get_by_id(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
        
    runtime = resolve_provider_runtime(provider)
    if not runtime.worker_url:
        raise HTTPException(status_code=400, detail="Provider does not have a valid worker URL for extraction")
        
    try:
        # Increase timeout because CPU extraction spins up ComfyUI
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(f"{runtime.worker_url}/object-info")
            response.raise_for_status()
            return response.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timeout while waiting for provider to extract node definitions")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch object_info from provider: {e}")
