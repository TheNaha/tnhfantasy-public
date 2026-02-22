# Model Service - Business logic for model management
from typing import Dict, Any, List, Optional
from datetime import datetime

from sqlmodel import Session

from core.entities import Model, ModelStatus
from core.exceptions import NotFoundError
from infrastructure.repositories import ModelRepository


class ModelService:
    """
    Handles model metadata and per-provider status tracking.
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.repo = ModelRepository(session)
    
    async def add_model(
        self,
        name: str,
        directory: str,
        url: Optional[str] = None,
        source: str = "custom",
        metadata: Optional[Dict] = None
    ) -> Model:
        """
        Add a new model or update existing.
        
        Args:
            name: Model filename
            directory: Model directory (checkpoints, loras, etc.)
            url: Download URL
            source: Source type (civitai, huggingface, custom)
            metadata: Additional metadata
            
        Returns:
            Created or updated model
        """
        return self.repo.upsert(
            name=name,
            directory=directory,
            url=url,
            source=source,
            metadata_=metadata or {}
        )
    
    async def get_model(self, model_id: int) -> Model:
        """Get a model by ID."""
        model = self.repo.get(model_id)
        if not model:
            raise NotFoundError("Model", str(model_id))
        return model
    
    async def get_model_by_name(self, name: str, directory: str) -> Optional[Model]:
        """Get a model by name and directory."""
        return self.repo.get_by_name_and_directory(name, directory)
    
    async def list_models(self) -> List[Dict[str, Any]]:
        """List all models."""
        models = self.repo.get_all()
        return [self._model_to_dict(m) for m in models]
    
    async def list_models_by_directory(self, directory: str) -> List[Dict[str, Any]]:
        """List models in a specific directory."""
        models = self.repo.get_by_directory(directory)
        return [self._model_to_dict(m) for m in models]
    
    async def get_models_grouped(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get all models grouped by directory."""
        grouped = self.repo.get_grouped_by_directory()
        return {
            directory: [self._model_to_dict(m) for m in models]
            for directory, models in grouped.items()
        }
    
    async def update_provider_status(
        self,
        name: str,
        directory: str,
        provider_id: str,
        status: ModelStatus,
        extra_data: Optional[Dict] = None
    ) -> Model:
        """
        Update the installation status of a model for a specific provider.
        
        Args:
            name: Model filename
            directory: Model directory
            provider_id: Provider ID
            status: New status
            extra_data: Additional status data (e.g., error message)
            
        Returns:
            Updated model
        """
        model = self.repo.get_by_name_and_directory(name, directory)
        if not model:
            # Auto-create model entry if it doesn't exist
            model = self.repo.upsert(name=name, directory=directory)
        
        result = self.repo.update_provider_status(
            model_id=model.id,
            provider_id=provider_id,
            status=status,
            extra_data=extra_data
        )
        
        # Emit event for real-time updates
        from core.events import event_bus, Event, EventType
        
        event_type = EventType.MODEL_SYNC_COMPLETED
        if status == ModelStatus.FAILED:
            event_type = EventType.MODEL_SYNC_FAILED
        elif status == ModelStatus.DOWNLOADING:
            event_type = EventType.MODEL_SYNC_PROGRESS
            
        import asyncio
        data = {
            "model_name": name,
            "directory": directory,
            "provider_id": provider_id,
            "status": status.value,
            "extra_data": extra_data
        }
        
        # simple fire-and-forget
        asyncio.create_task(event_bus.publish(Event(type=event_type, data=data)))
        
        return result
    
    async def delete_model(self, name: str, directory: str) -> bool:
        """Delete a model by name and directory."""
        return self.repo.delete_by_name_and_directory(name, directory)
    
    def get_full_cache(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get all model metadata (for reconciliation)."""
        grouped = self.repo.get_grouped_by_directory()
        return {
            directory: [self._model_to_dict(m) for m in models]
            for directory, models in grouped.items()
        }
    
    def _model_to_dict(self, model: Model) -> Dict[str, Any]:
        """Convert model to dictionary for API responses."""
        return {
            "id": model.id,
            "name": model.name,
            "directory": model.directory,
            "url": model.url,
            "source": model.source,
            "metadata": model.metadata_,
            "provider_statuses": model.provider_statuses,
            "created_at": model.created_at.isoformat() if model.created_at else None,
            "updated_at": model.updated_at.isoformat() if model.updated_at else None,
        }
