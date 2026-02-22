# Download routes
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlmodel import Session
from pydantic import BaseModel

from api.deps import get_session, get_event_bus
from services.download_service import DownloadService
from core.events import EventBus

router = APIRouter(prefix="/api/downloads", tags=["downloads"])


class StartDownloadRequest(BaseModel):
    name: str
    url: str
    path: str
    provider_id: str
    metadata: Optional[Dict[str, Any]] = None


@router.get("")
async def list_downloads(session: Session = Depends(get_session)):
    """List active downloads."""
    service = DownloadService(session)
    return {"downloads": service.get_active_downloads()}


@router.post("")
async def start_download(
    request: StartDownloadRequest,
    session: Session = Depends(get_session)
):
    """Start a new download."""
    service = DownloadService(session)
    download = await service.start_download(
        name=request.name,
        url=request.url,
        path=request.path,
        provider_id=request.provider_id,
        metadata=request.metadata
    )
    return service._download_to_dict(download)


@router.get("/{download_id}")
async def get_download(
    download_id: str,
    session: Session = Depends(get_session)
):
    """Get download status."""
    service = DownloadService(session)
    download = service.get_download(download_id)
    if not download:
        raise HTTPException(status_code=404, detail="Download not found")
    return download


