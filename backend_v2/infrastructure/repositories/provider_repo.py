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
from services.credential_crypto import (
    decrypt_credentials,
    encrypt_credentials,
    is_encrypted,
)


class ProviderRepository:
    """Data access layer for Provider entities.

    THE ENCRYPTION BOUNDARY. `Provider.credentials` is encrypted at rest
    (`services/credential_crypto.py`), and this class is the only place that
    knows it. Everything above it — `provider_service`, `load_balancer`,
    `engine_factory.can_create_engine`, the status services — receives and
    passes around a plaintext credential bag, exactly as it did before the
    column was encrypted. That is deliberate: encrypting inside the engines, or
    inside a route handler, would mean ~40 call sites each having to remember,
    and the one that forgets returns `EngineAuthError` hours later.

    Encrypt on write, decrypt on read, so the database holds ciphertext and the
    rest of the codebase holds plaintext. `decrypt_credentials` raises rather
    than returning `{}` when the key is wrong — a provider with an unreadable
    token is not the same thing as a provider with no token, and collapsing the
    two turns a rotated key into an unexplained 401 from Modal.
    """

    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _decrypt_in_place(provider: Provider | None) -> Provider | None:
        """Swap an envelope on a loaded row for the bag inside it.

        SQLAlchemy identity-maps the object, so mutating it after load affects
        every other reference to that row in this session. Mutating a *loaded*
        attribute does not mark the column dirty, which is what we want: reading
        must not silently rewrite the row, and must not cost a write per query.
        """
        if provider is None or not isinstance(provider.credentials, dict):
            return provider
        if not is_encrypted(provider.credentials):
            return provider
        provider.__dict__["credentials"] = decrypt_credentials(provider.credentials)
        return provider

    @staticmethod
    def _encrypt_for_write(updates: dict[str, Any]) -> dict[str, Any]:
        """Wrap `credentials` in an envelope on its way to the column."""
        if "credentials" not in updates:
            return updates
        wrapped = dict(updates)
        wrapped["credentials"] = encrypt_credentials(wrapped["credentials"] or {})
        return wrapped

    def create(self, provider_data: dict[str, Any]) -> Provider:
        """Create a new provider."""
        provider = Provider(**self._encrypt_for_write(provider_data))
        self.session.add(provider)
        self.session.commit()
        self.session.refresh(provider)
        self._decrypt_in_place(provider)
        return provider

    def get(self, provider_id: str) -> Provider | None:
        """Get a provider by ID."""
        return self._decrypt_in_place(self.session.get(Provider, provider_id))

    get_by_id = get

    def get_all(self) -> list[Provider]:
        """Get all providers."""
        stmt = select(Provider)
        return [
            self._decrypt_in_place(p) for p in self.session.exec(stmt).all()
        ]

    def get_enabled(self) -> list[Provider]:
        """Get all enabled providers."""
        stmt = select(Provider).where(Provider.enabled == True)
        return [
            self._decrypt_in_place(p) for p in self.session.exec(stmt).all()
        ]

    def get_raw(self, provider_id: str) -> Provider | None:
        """The row as stored — ciphertext intact, NOT decrypted.

        For the maintenance paths that must not be able to read a token in order
        to work: the credential-presence API, the encryption backfill, and the
        "is this still plaintext?" check. Anything that only needs to know
        whether a key is *set* should use this rather than decrypting and then
        careful not to look at the value.
        """
        return self.session.get(Provider, provider_id)

    def update(self, provider_id: str, updates: dict[str, Any]) -> Provider | None:
        """Update a provider."""
        provider = self.get(provider_id)
        if not provider:
            return None

        for key, value in self._encrypt_for_write(updates).items():
            if hasattr(provider, key):
                setattr(provider, key, value)

        self.session.commit()
        self.session.refresh(provider)
        self._decrypt_in_place(provider)
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
