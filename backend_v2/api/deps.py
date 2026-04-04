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
from contextlib import asynccontextmanager
from typing import AsyncIterator, Generator

from sqlmodel import Session

from infrastructure.database import (
    get_session as db_get_session,
    get_session_context as db_get_session_context,
    get_session_sync as db_get_session_sync,
)
from services.job_service import JobService
from services.provider_service import ProviderService
from services.external_model_service import ExternalModelService
from core.events import event_bus, EventBus
from infrastructure.logging import get_logger

logger = get_logger("api_deps")


def get_session() -> Generator[Session, None, None]:
    """Get database session for FastAPI dependency injection."""
    yield from db_get_session()


def get_session_sync() -> Session:
    """Get a synchronous session for non-request code paths."""
    return db_get_session_sync()


@asynccontextmanager
async def get_session_context() -> AsyncIterator[Session]:
    """Get an async context manager for internal async code paths."""
    async with db_get_session_context() as session:
        yield session


def get_event_bus() -> EventBus:
    """Get event bus singleton."""
    return event_bus


def get_job_service(session: Session) -> JobService:
    """Get job service instance."""
    return JobService(session)


def get_provider_service(session: Session) -> ProviderService:
    """Get provider service instance."""
    return ProviderService(session)


def get_model_service_v2(session: Session):
    """Get model service V2 instance."""
    from services.model_service_v2 import ModelServiceV2
    return ModelServiceV2(session)


def get_external_model_service() -> ExternalModelService:
    """Get external model service instance."""
    return ExternalModelService()


def get_container_manager():
    """Get container manager singleton (lazy initialization)."""
    try:
        from services.container_manager import get_container_manager as get_shared_container_manager
        return get_shared_container_manager()
    except Exception as e:
        logger.warning("container_manager_init_failed", error=str(e))
        return None
