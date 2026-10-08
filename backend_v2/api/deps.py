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
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager

from fastapi import Depends, Request
from sqlmodel import Session

from core.events import EventBus, event_bus
from infrastructure.deps import get_session_context as _infra_get_session_context, get_session_sync as _infra_get_session_sync
from infrastructure.database import (
    get_session as db_get_session,
)
from infrastructure.logging import get_logger

logger = get_logger("api_deps")


def get_session() -> Generator[Session, None, None]:
    """Get database session for FastAPI dependency injection."""
    yield from db_get_session()


def get_session_sync() -> Session:
    """Get a synchronous session for non-request code paths."""
    return _infra_get_session_sync()


@asynccontextmanager
async def get_session_context() -> AsyncIterator[Session]:
    """Get an async context manager for internal async code paths."""
    async with _infra_get_session_context() as session:
        yield session


def get_event_bus() -> EventBus:
    """Get event bus singleton."""
    return event_bus


def get_job_service(session: Session = Depends(get_session)):
    """Get job service instance."""
    from services.job_service import JobService
    return JobService(session)


def get_provider_service(session: Session = Depends(get_session)):
    """Get provider service instance."""
    from services.provider_service import ProviderService
    return ProviderService(session)


def get_model_repo_v2(session: Session = Depends(get_session)):
    """Get model repo V2 instance."""
    from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2
    return ModelRepositoryV2(session)


def get_model_service_v2(session: Session = Depends(get_session)):
    """Get model service V2 instance."""
    from services.model_service import ModelServiceV2
    return ModelServiceV2(session)


def get_external_model_service():
    """Get external model service instance."""
    from services.external_model_service import ExternalModelService
    return ExternalModelService()


def get_job_submission_service(session: Session = Depends(get_session)):
    from services.job_submission_service import JobSubmissionService
    return JobSubmissionService(session)


def get_provider_lifecycle_service(
    session: Session = Depends(get_session)
):
    from services.provider_lifecycle_service import ProviderLifecycleService
    from services.provider_status_service import invalidate_provider_status_caches
    return ProviderLifecycleService(
        session,
        invalidate_caches=invalidate_provider_status_caches,
    )


def get_provider_status_service(session: Session = Depends(get_session)):
    from services.provider_status_service import ProviderStatusService
    return ProviderStatusService(session)


def get_model_civitai_sync_service(session: Session = Depends(get_session)):
    from services.model_civitai_sync import ModelCivitaiSyncService
    return ModelCivitaiSyncService(session)


def get_collection_repo(session: Session = Depends(get_session)):
    from infrastructure.repositories.collection_repo import CollectionRepository
    return CollectionRepository(session)


def get_prompt_repo(session: Session = Depends(get_session)):
    from infrastructure.repositories.prompt_repo import PromptRepository
    return PromptRepository(session)


def get_character_repo(session: Session = Depends(get_session)):
    from infrastructure.repositories.character_repo import CharacterRepository
    return CharacterRepository(session)


def get_chat_repo(session: Session = Depends(get_session)):
    from infrastructure.repositories.chat_repo import ChatRepository
    return ChatRepository(session)


def get_message_repo(session: Session = Depends(get_session)):
    from infrastructure.repositories.message_repo import MessageRepository
    return MessageRepository(session)


def get_story_repo(session: Session = Depends(get_session)):
    from infrastructure.repositories.story_repo import StoryRepository
    return StoryRepository(session)


def get_story_chapter_repo(session: Session = Depends(get_session)):
    from infrastructure.repositories.story_chapter_repo import StoryChapterRepository
    return StoryChapterRepository(session)


def get_story_revision_repo(session: Session = Depends(get_session)):
    from infrastructure.repositories.story_revision_repo import StoryChapterRevisionRepository
    return StoryChapterRevisionRepository(session)


def get_lorebook_repo(session: Session = Depends(get_session)):
    from infrastructure.repositories.lorebook_repo import LorebookRepository
    return LorebookRepository(session)


def get_lorebook_entry_repo(session: Session = Depends(get_session)):
    from infrastructure.repositories.lorebook_entry_repo import LorebookEntryRepository
    return LorebookEntryRepository(session)


def get_character_memory_repo(session: Session = Depends(get_session)):
    from infrastructure.repositories.character_memory_repo import CharacterMemoryRepository
    return CharacterMemoryRepository(session)


def get_location_repo(session: Session = Depends(get_session)):
    from infrastructure.repositories.location_repo import LocationRepository
    return LocationRepository(session)


def get_voice_model_repo(session: Session = Depends(get_session)):
    from infrastructure.repositories.voice_model_repo import VoiceModelRepository
    return VoiceModelRepository(session)


def get_world_repo(session: Session = Depends(get_session)):
    from infrastructure.repositories.world_repo import WorldRepository
    return WorldRepository(session)


def get_scenario_repo(session: Session = Depends(get_session)):
    from infrastructure.repositories.scenario_repo import ScenarioRepository
    return ScenarioRepository(session)


def get_persona_repo(session: Session = Depends(get_session)):
    from infrastructure.repositories.persona_repo import PersonaRepository
    return PersonaRepository(session)


def get_embedding_service():
    from services.embedding_service import get_embedding_service as get_service
    return get_service()


def get_queue_manager():
    from services.job_queue import queue_manager
    return queue_manager
