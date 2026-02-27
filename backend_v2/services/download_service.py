# Download Service - Manages model downloads with progress tracking
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime

from sqlmodel import Session

from core.entities import Download, Model, ModelStatus
from core.events import event_bus, Event, EventType, emit_download_event
from core.exceptions import NotFoundError, DownloadError
from infrastructure.repositories import ModelRepository
from infrastructure.logging import download_logger
from infrastructure.metrics import metrics

logger = download_logger()


class DownloadService:
    """
    Manages model downloads and tracks progress.
    Emits events for real-time UI updates.
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.model_repo = ModelRepository(session)
        
        # Active downloads (in-memory tracking)
        self._active_downloads: Dict[str, Download] = {}
    
    async def start_download(
        self,
        name: str,
        url: str,
        path: str,
        provider_id: str,
        metadata: Optional[Dict] = None
    ) -> Download:
        """
        Start a new download.
        
        Args:
            name: Display name
            url: Download URL
            path: Target path
            provider_id: Provider to download to
            metadata: Optional metadata
            
        Returns:
            Download object
        """
        import uuid
        
        download = Download(
            id=str(uuid.uuid4()),
            name=name,
            url=url,
            path=path,
            provider_id=provider_id,
            status="pending"
        )
        
        # Track in memory
        self._active_downloads[download.id] = download
        
        logger.info("download_started", download_id=download.id, name=name, provider_id=provider_id)
        metrics.track_download("started")
        metrics.set_active_downloads(len(self._active_downloads))
        
        # Emit start event
        await emit_download_event(
            EventType.DOWNLOAD_STARTED,
            self._download_to_dict(download)
        )
        
        return download
    
    async def update_progress(
        self,
        download_id: str,
        progress: float,
        speed: Optional[str] = None,
        downloaded_size: Optional[str] = None,
        total_size: Optional[str] = None,
        message: Optional[str] = None
    ) -> Optional[Download]:
        """Update download progress and emit event."""
        download = self._active_downloads.get(download_id)
        if not download:
            return None
        
        download.progress = progress
        download.status = "downloading"
        if speed:
            download.speed = speed
        if downloaded_size:
            download.downloaded_size = downloaded_size
        if total_size:
            download.total_size = total_size
        if message:
            download.message = message
        
        # Emit progress event
        await emit_download_event(
            EventType.DOWNLOAD_PROGRESS,
            self._download_to_dict(download)
        )
        
        return download
    
    async def complete_download(
        self,
        download_id: str,
        directory: str,
        source: str = "custom"
    ) -> Optional[Download]:
        """Mark download as complete and update model status."""
        download = self._active_downloads.get(download_id)
        if not download:
            logger.warning("download_complete_not_found", download_id=download_id)
            return None
        
        download.status = "completed"
        download.progress = 100.0
        
        logger.info("download_completed", download_id=download_id, name=download.name)
        metrics.track_download("completed")
        
        # Update model status in database
        model = self.model_repo.upsert(
            name=download.name,
            directory=directory,
            url=download.url,
            source=source
        )
        
        self.model_repo.update_provider_status(
            model_id=model.id,
            provider_id=download.provider_id,
            status=ModelStatus.INSTALLED
        )
        
        # Emit completion event
        await emit_download_event(
            EventType.DOWNLOAD_COMPLETED,
            self._download_to_dict(download)
        )
        
        # Remove from active downloads
        del self._active_downloads[download_id]
        metrics.set_active_downloads(len(self._active_downloads))
        
        return download
    
    async def fail_download(
        self,
        download_id: str,
        error: str
    ) -> Optional[Download]:
        """Mark download as failed."""
        download = self._active_downloads.get(download_id)
        if not download:
            logger.warning("download_fail_not_found", download_id=download_id)
            return None
        
        download.status = "failed"
        download.message = error
        
        logger.error("download_failed", download_id=download_id, name=download.name, error=error)
        metrics.track_download("failed")
        
        # Emit failure event
        await emit_download_event(
            EventType.DOWNLOAD_FAILED,
            self._download_to_dict(download)
        )
        
        # Remove from active downloads
        del self._active_downloads[download_id]
        metrics.set_active_downloads(len(self._active_downloads))
        
        return download
    
    def get_active_downloads(self) -> list:
        """Get all active downloads."""
        return [self._download_to_dict(d) for d in self._active_downloads.values()]
    
    def get_download(self, download_id: str) -> Optional[Dict]:
        """Get a specific download."""
        download = self._active_downloads.get(download_id)
        if download:
            return self._download_to_dict(download)
        return None
    
    def _download_to_dict(self, download: Download) -> Dict[str, Any]:
        """Convert download to dictionary."""
        return {
            "id": download.id,
            "name": download.name,
            "url": download.url,
            "path": download.path,
            "provider_id": download.provider_id,
            "status": download.status,
            "progress": download.progress,
            "speed": download.speed,
            "downloaded_size": download.downloaded_size,
            "total_size": download.total_size,
            "message": download.message,
            "created_at": download.created_at.isoformat() if download.created_at else None,
        }
