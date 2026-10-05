# Provider Repository - Data access layer for providers
#
# Provides typed CRUD operations for the `providers` and
# `load_balancing_config` tables.
#
# The repository is session-scoped – callers should create a new instance
# per request.  The LoadBalancingRepository is a separate class that manages
# the singleton load-balancing configuration row.
from typing import Any

from sqlmodel import Session, select

from core.entities import LoadBalancingConfig, Provider


class ProviderRepository:
    """Data access layer for Provider entities."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def create(self, provider_data: dict[str, Any]) -> Provider:
        """Create a new provider."""
        provider = Provider(**provider_data)
        self.session.add(provider)
        self.session.commit()
        self.session.refresh(provider)
        return provider
    
    def get(self, provider_id: str) -> Provider | None:
        """Get a provider by ID."""
        return self.session.get(Provider, provider_id)
    
    def get_all(self) -> list[Provider]:
        """Get all providers."""
        stmt = select(Provider)
        return list(self.session.exec(stmt).all())
    
    def get_enabled(self) -> list[Provider]:
        """Get all enabled providers."""
        stmt = select(Provider).where(Provider.enabled == True)
        return list(self.session.exec(stmt).all())
    
    def update(self, provider_id: str, updates: dict[str, Any]) -> Provider | None:
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
