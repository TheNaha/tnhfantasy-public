# Provider Repository - Data access layer for providers
from sqlmodel import Session, select
from typing import Optional, List, Dict, Any

from core.entities import Provider, LoadBalancingConfig


class ProviderRepository:
    """Data access layer for Provider entities."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def create(self, provider_data: Dict[str, Any]) -> Provider:
        """Create a new provider."""
        provider = Provider(**provider_data)
        self.session.add(provider)
        self.session.commit()
        self.session.refresh(provider)
        return provider
    
    def get(self, provider_id: str) -> Optional[Provider]:
        """Get a provider by ID."""
        return self.session.get(Provider, provider_id)
    
    def get_all(self) -> List[Provider]:
        """Get all providers."""
        stmt = select(Provider)
        return list(self.session.exec(stmt).all())
    
    def get_enabled(self) -> List[Provider]:
        """Get all enabled providers."""
        stmt = select(Provider).where(Provider.enabled == True)
        return list(self.session.exec(stmt).all())
    
    def get_by_type(self, provider_type: str) -> List[Provider]:
        """Get providers by type."""
        stmt = select(Provider).where(Provider.type == provider_type)
        return list(self.session.exec(stmt).all())
    
    def update(self, provider_id: str, updates: Dict[str, Any]) -> Optional[Provider]:
        """Update a provider."""
        provider = self.get(provider_id)
        if not provider:
            return None
        
        for key, value in updates.items():
            if hasattr(provider, key):
                setattr(provider, key, value)
        
        self.session.commit()
        self.session.refresh(provider)
        return provider
    
    def delete(self, provider_id: str) -> bool:
        """Delete a provider."""
        provider = self.get(provider_id)
        if not provider:
            return False
        
        self.session.delete(provider)
        self.session.commit()
        return True
    
    def exists(self, provider_id: str) -> bool:
        """Check if a provider exists."""
        return self.get(provider_id) is not None


class LoadBalancingRepository:
    """Data access for load balancing configuration (singleton)."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def get(self) -> LoadBalancingConfig:
        """Get load balancing config, creating default if not exists."""
        config = self.session.get(LoadBalancingConfig, 1)
        if not config:
            config = LoadBalancingConfig(id=1)
            self.session.add(config)
            self.session.commit()
            self.session.refresh(config)
        return config
    
    def update(self, **kwargs) -> LoadBalancingConfig:
        """Update load balancing config."""
        config = self.get()
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        self.session.commit()
        self.session.refresh(config)
        return config
