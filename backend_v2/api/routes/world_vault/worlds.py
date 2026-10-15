from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_session, get_world_repo
from infrastructure.repositories.world_repo import WorldRepository
from core.entities import Character, Chat, Location, Lorebook, Scenario, Story, VoiceModel, World
from core.exceptions import NotFoundError
from services.world_ownership import MEMBER_TABLES, detach_world, members_of
from sqlalchemy import func
from sqlmodel import Session, select

router = APIRouter()


class WorldCreate(BaseModel):
    name: str
    description: str | None = None


class WorldUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


@router.get("")
def list_worlds(session: Session = Depends(get_session), world_repo: WorldRepository = Depends(get_world_repo)):
    """Every world, each carrying the size of its roster.

    The counts replace the id arrays this route used to return verbatim.
    `world_id` on each member is the ownership of record, so "what is in this
    world" is a GROUP BY over the member tables rather than a column on the
    world row. The world page's badges and the "Added to every reply" line in
    `WorldLinkRow` read these.

    One grouped scan per member table, not one per world: seven indexed queries
    regardless of how many worlds exist. The arrays this replaces cost a single
    row read, but they had to be kept in step by hand, which is why they are
    gone.
    """
    worlds = world_repo.list()
    counts = {w.id: {label: 0 for _model, label in MEMBER_TABLES} for w in worlds}
    for model, label in MEMBER_TABLES:
        rows = session.exec(
            select(model.world_id, func.count(model.id)).where(model.world_id.is_not(None)).group_by(model.world_id)
        ).all()
        for world_id, total in rows:
            if world_id in counts:
                counts[world_id][label] = int(total)
    return [{**w.model_dump(), "counts": counts[w.id]} for w in worlds]


@router.get("/{world_id}")
def get_world(world_id: str, session: Session = Depends(get_session), world_repo: WorldRepository = Depends(get_world_repo)):
    world = world_repo.get(world_id)
    if not world:
        raise NotFoundError("World", world_id)
    return world


@router.post("", response_model=World)
def create_world(world_in: WorldCreate, session: Session = Depends(get_session), world_repo: WorldRepository = Depends(get_world_repo)):
    """Create an empty world.

    A world has no members on creation — a Character, Lorebook, Location,
    Scenario or VoiceModel is put IN one by setting its own `world_id` through
    `services.world_ownership.link_to_world`. There is deliberately no way to
    pass a roster here: the membership arrays this route used to accept were the
    half of the two-columns-one-relationship bug that had no sync path at all,
    and `PUT` could overwrite `chat_ids`/`story_ids` without touching the FKs
    that own them.
    """
    world = World(
        name=world_in.name,
        description=world_in.description,
    )
    world.created_at = datetime.now(timezone.utc)
    world.updated_at = world.created_at
    session.add(world)
    session.commit()
    session.refresh(world)
    return world


@router.put("/{world_id}", response_model=World)
def update_world(world_id: str, update_data: WorldUpdate, session: Session = Depends(get_session), world_repo: WorldRepository = Depends(get_world_repo)):
    """Rename or redescribe a world. Membership is not editable here.

    Same rule as create: a member's world is `member.world_id`, written by the
    member's own route through `link_to_world`. Editing it from the world side
    is what let the old index and the FKs disagree.
    """
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
    # `world_id` has no ON DELETE clause on any member table, so deleting the
    # world without clearing them left members pointing at a row that no longer
    # existed — including the lorebooks and locations that are merged into every
    # prompt built for a chat that lives in that world.
    detach_world(session, world_id)
    session.delete(world)
    session.commit()
    return {"message": "World deleted"}


@router.get("/{world_id}/dashboard")
def get_world_dashboard(world_id: str, session: Session = Depends(get_session), world_repo: WorldRepository = Depends(get_world_repo)):
    """What is in this world, resolved through the FKs.

    The old version joined the six id arrays against the tables. It now reads
    `world_id` on each member, which is the same indexed lookup and cannot
    desync from the roster the world page shows.
    """
    world = world_repo.get(world_id)
    if not world:
        raise NotFoundError("World", world_id)

    characters = members_of(session, world_id, Character)
    stories = members_of(session, world_id, Story)
    chats = members_of(session, world_id, Chat)
    locations = members_of(session, world_id, Location)
    lorebooks = members_of(session, world_id, Lorebook)
    scenarios = members_of(session, world_id, Scenario)
    voices = members_of(session, world_id, VoiceModel)

    return {
        "world": world,
        "characters": [{"id": c.id, "name": c.name} for c in characters],
        "stories": [{"id": s.id, "title": s.title} for s in stories],
        "chats": [{"id": c.id, "name": c.name} for c in chats],
        "locations": [{"id": l.id, "name": l.name} for l in locations],
        "lorebooks": [{"id": l.id, "name": l.name} for l in lorebooks],
        "scenarios": [{"id": s.id, "name": s.name} for s in scenarios],
        "voices": [{"id": v.id, "name": v.name} for v in voices],
    }
