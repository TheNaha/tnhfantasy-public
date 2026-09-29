from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_session, get_world_repo
from infrastructure.repositories.world_repo import WorldRepository
from core.entities import World, Location, Character, Story, Chat
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


class WorldUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    character_ids: list[str] | None = None
    story_ids: list[str] | None = None
    chat_ids: list[str] | None = None
    location_ids: list[str] | None = None


@router.get("", response_model=list[World])
def list_worlds(session: Session = Depends(get_session), world_repo: WorldRepository = Depends(get_world_repo)):
    return world_repo.list()


@router.post("", response_model=World)
def create_world(world_in: WorldCreate, session: Session = Depends(get_session), world_repo: WorldRepository = Depends(get_world_repo)):
    world = World(
        name=world_in.name,
        description=world_in.description,
        character_ids=world_in.character_ids or [],
        story_ids=world_in.story_ids or [],
        chat_ids=world_in.chat_ids or [],
        location_ids=world_in.location_ids or [],
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
