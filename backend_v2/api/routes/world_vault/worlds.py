from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_session, get_world_repo
from infrastructure.repositories.world_repo import WorldRepository
from core.entities import (
    Chat,
    Character,
    Location,
    Lorebook,
    Scenario,
    Story,
    VoiceModel,
    World,
)
from core.exceptions import NotFoundError
from services.world_ownership import detach_world
from sqlmodel import Session, select

router = APIRouter()


class WorldCreate(BaseModel):
    name: str
    description: str | None = None
    character_ids: list[str] | None = None
    story_ids: list[str] | None = None
    chat_ids: list[str] | None = None
    location_ids: list[str] | None = None
    # The World's *membership*, as opposed to the `character_ids` / `chat_ids` /
    # `story_ids` index that `services/world_ownership.py` keeps in sync
    # automatically. These three had no writer at all — the columns existed
    # from the migration that created the World entity and nothing could ever
    # set them — so a World's lorebooks, scenarios and voices were unreachable
    # even after the World began contributing to the prompt.
    lorebook_ids: list[str] | None = None
    scenario_ids: list[str] | None = None
    voice_ids: list[str] | None = None


class WorldUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    character_ids: list[str] | None = None
    story_ids: list[str] | None = None
    chat_ids: list[str] | None = None
    location_ids: list[str] | None = None
    lorebook_ids: list[str] | None = None
    scenario_ids: list[str] | None = None
    voice_ids: list[str] | None = None


def _verify_members(session, character_ids, location_ids, lorebook_ids, scenario_ids, voice_ids) -> None:
    """Reject a World membership that does not resolve.

    A dangling id is not a harmless mistake: the World's lorebooks and
    locations are merged into every prompt built for a chat in it, so an id
    that resolves to nothing becomes a per-turn lookup that quietly finds
    nothing, and the World looks configured while contributing nothing.
    """
    for entity_ids, entity, label in (
        (character_ids, Character, "Character"),
        (location_ids, Location, "Location"),
        (lorebook_ids, Lorebook, "Lorebook"),
        (scenario_ids, Scenario, "Scenario"),
        (voice_ids, VoiceModel, "VoiceModel"),
    ):
        for entity_id in entity_ids or []:
            if session.get(entity, entity_id) is None:
                raise NotFoundError(label, entity_id)


@router.get("", response_model=list[World])
def list_worlds(session: Session = Depends(get_session), world_repo: WorldRepository = Depends(get_world_repo)):
    return world_repo.list()


@router.post("", response_model=World)
def create_world(world_in: WorldCreate, session: Session = Depends(get_session), world_repo: WorldRepository = Depends(get_world_repo)):
    _verify_members(session, world_in.character_ids, world_in.location_ids,
                    world_in.lorebook_ids, world_in.scenario_ids, world_in.voice_ids)
    world = World(
        name=world_in.name,
        description=world_in.description,
        character_ids=world_in.character_ids or [],
        story_ids=world_in.story_ids or [],
        chat_ids=world_in.chat_ids or [],
        location_ids=world_in.location_ids or [],
        lorebook_ids=world_in.lorebook_ids or [],
        scenario_ids=world_in.scenario_ids or [],
        voice_ids=world_in.voice_ids or [],
    )
    world.created_at = datetime.now(timezone.utc)
    world.updated_at = world.created_at
    session.add(world)
    session.commit()
    session.refresh(world)
    return world


@router.get("/{world_id}", response_model=World)
def get_world(world_id: str, session: Session = Depends(get_session), world_repo: WorldRepository = Depends(get_world_repo)):
    world = world_repo.get(world_id)
    if not world:
        raise NotFoundError("World", world_id)
    return world


@router.put("/{world_id}", response_model=World)
def update_world(world_id: str, update_data: WorldUpdate, session: Session = Depends(get_session), world_repo: WorldRepository = Depends(get_world_repo)):
    world = world_repo.get(world_id)
    if not world:
        raise NotFoundError("World", world_id)

    update_dict = update_data.model_dump(exclude_unset=True)
    _verify_members(session, update_dict.get("character_ids"), update_dict.get("location_ids"),
                    update_dict.get("lorebook_ids"), update_dict.get("scenario_ids"),
                    update_dict.get("voice_ids"))
    for key, value in update_dict.items():
        setattr(world, key, value)

    world.updated_at = datetime.now(timezone.utc)
    session.add(world)
    session.commit()
    session.refresh(world)
    return world


@router.delete("/{world_id}")
def delete_world(world_id: str, session: Session = Depends(get_session), world_repo: WorldRepository = Depends(get_world_repo)):
    world = world_repo.get(world_id)
    if not world:
        raise NotFoundError("World", world_id)
    # `Chat.world_id` and `Story.world_id` are the ownership of record and have
    # no ON DELETE clause, so deleting the world without clearing them left
    # chats and stories pointing at a row that no longer existed. The world's
    # own `chat_ids` / `story_ids` index goes with the row.
    detach_world(session, world_id)
    session.delete(world)
    session.commit()
    return {"message": "World deleted"}


@router.get("/{world_id}/dashboard")
def get_world_dashboard(world_id: str, session: Session = Depends(get_session), world_repo: WorldRepository = Depends(get_world_repo)):
    world = world_repo.get(world_id)
    if not world:
        raise NotFoundError("World", world_id)

    characters = session.exec(select(Character).where(Character.id.in_(world.character_ids or []))).all()
    stories = session.exec(select(Story).where(Story.id.in_(world.story_ids or []))).all()
    chats = session.exec(select(Chat).where(Chat.id.in_(world.chat_ids or []))).all()
    locations = session.exec(select(Location).where(Location.id.in_(world.location_ids or []))).all()

    return {
        "world": world,
        "characters": [{"id": c.id, "name": c.name} for c in characters],
        "stories": [{"id": s.id, "title": s.title} for s in stories],
        "chats": [{"id": c.id, "name": c.name} for c in chats],
        "locations": [{"id": l.id, "name": l.name} for l in locations],
    }
