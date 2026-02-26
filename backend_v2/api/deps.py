# API Dependency Injection
#
# FastAPI uses these callables as dependencies (via `Depends(...)`).
# They provide request-scoped service instances so each HTTP request gets
# a fresh database session and the correct service objects.
#
# PATTERN:
#   Each route that needs database access declares:
#       session: Session = Depends(get_session)
#   Then creates services via:
#       service = get_job_service(session)
#
# The ContainerManager is a singleton because it holds a Docker/Podman client
# connection that is expensive to create on every request.
from functools import lru_cache
from typing import Generator, Optional

from sqlmodel import Session

from infrastructure.database import get_session as db_get_session, engine
from services.job_service import JobService
from services.provider_service import ProviderService
from services.model_service import ModelService
from core.events import event_bus, EventBus

# Singleton container manager (initialized lazily on first use)
_container_manager = None


def get_session() -> Generator[Session, None, None]:
    """Get database session for FastAPI dependency injection."""
    yield from db_get_session()


def get_event_bus() -> EventBus:
    """Get event bus singleton."""
    return event_bus


def get_job_service(session: Session) -> JobService:
    """Get job service instance."""
    return JobService(session)


def get_provider_service(session: Session) -> ProviderService:
    """Get provider service instance."""
    return ProviderService(session)


def get_model_service(session: Session) -> ModelService:
    """Get model service instance (V1 - legacy)."""
    return ModelService(session)


def get_model_service_v2(session: Session):
    """Get model service V2 instance."""
    from services.model_service_v2 import ModelServiceV2
    return ModelServiceV2(session)


def get_container_manager():
    """Get container manager singleton (lazy initialization)."""
    global _container_manager
    if _container_manager is None:
        try:
            from services.container_manager import ContainerManager
            _container_manager = ContainerManager()
        except Exception as e:
            print(f"Warning: Could not initialize container manager: {e}")
            return None
    return _container_manager

