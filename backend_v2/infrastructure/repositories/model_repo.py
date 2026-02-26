# Model Repository - Data access layer for models
#
# Provides typed CRUD operations for the `models` table (V1 flat schema).
# For the normalized V2 schema (models_v2, model_versions, model_files,
# provider_version_status) see `model_repo_v2.py`.
#
# The repository is session-scoped – callers should create a new instance
# per request using the FastAPI dependency in `api/deps.py`.
from sqlmodel import Session, select, col, and_
from typing import Optional, List, Dict, Any
from datetime import datetime

from core.entities import Model, ModelStatus


class ModelRepository:
    """Data access layer for Model entities."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def create(self, model_data: Dict[str, Any]) -> Model:
        """Create a new model."""
        model = Model(**model_data)
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        return model
    
    def get(self, model_id: int) -> Optional[Model]:
        """Get a model by ID."""
        return self.session.get(Model, model_id)
    
    def get_by_name_and_directory(self, name: str, directory: str) -> Optional[Model]:
        """Get a model by name and directory (unique combo)."""
        stmt = select(Model).where(
            and_(Model.name == name, Model.directory == directory)
        )
        return self.session.exec(stmt).first()
    
    def get_all(self) -> List[Model]:
        """Get all models."""
        stmt = select(Model).order_by(col(Model.updated_at).desc())
        return list(self.session.exec(stmt).all())
    
    def get_by_directory(self, directory: str) -> List[Model]:
        """Get models in a specific directory."""
        stmt = select(Model).where(Model.directory == directory)
        return list(self.session.exec(stmt).all())
    
    def get_by_source(self, source: str) -> List[Model]:
        """Get models from a specific source."""
        stmt = select(Model).where(Model.source == source)
        return list(self.session.exec(stmt).all())
    
    def update(self, model_id: int, **kwargs) -> Optional[Model]:
        """Update a model."""
        model = self.get(model_id)
        if not model:
            return None
        
        for key, value in kwargs.items():
            if hasattr(model, key):
                setattr(model, key, value)
        
        model.updated_at = datetime.utcnow()
        self.session.commit()
        self.session.refresh(model)
        return model
    
    def update_provider_status(
        self, 
        model_id: int, 
        provider_id: str, 
        status: ModelStatus,
        extra_data: Optional[Dict] = None
    ) -> Optional[Model]:
        """Update the status of a model for a specific provider."""
        model = self.get(model_id)
        if not model:
            return None
        
        # Update provider_statuses dict
        statuses = model.provider_statuses.copy() if model.provider_statuses else {}
        statuses[provider_id] = {
            "status": status.value,
            "updated_at": datetime.utcnow().isoformat(),
            **(extra_data or {})
        }
        model.provider_statuses = statuses
        model.updated_at = datetime.utcnow()
        
        self.session.commit()
        self.session.refresh(model)
        return model
    
    def delete(self, model_id: int) -> bool:
        """Delete a model."""
        model = self.get(model_id)
        if not model:
            return False
        
        self.session.delete(model)
        self.session.commit()
        return True
    
    def delete_by_name_and_directory(self, name: str, directory: str) -> bool:
        """Delete a model by name and directory."""
        model = self.get_by_name_and_directory(name, directory)
        if not model:
            return False
        
        self.session.delete(model)
        self.session.commit()
        return True
    
    def upsert(self, name: str, directory: str, **kwargs) -> Model:
        """Insert or update a model by name and directory."""
        model = self.get_by_name_and_directory(name, directory)
        
        if model:
            # Update existing
            for key, value in kwargs.items():
                if hasattr(model, key):
                    setattr(model, key, value)
            model.updated_at = datetime.utcnow()
        else:
            # Create new
            model = Model(name=name, directory=directory, **kwargs)
            self.session.add(model)
        
        self.session.commit()
        self.session.refresh(model)
        return model
    
    def get_grouped_by_directory(self) -> Dict[str, List[Model]]:
        """Get all models grouped by directory."""
        models = self.get_all()
        result: Dict[str, List[Model]] = {}
        for model in models:
            result.setdefault(model.directory, []).append(model)
        return result
