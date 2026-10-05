"""Which World a Chat or a Story belongs to.

`Chat.world_id` and `Story.world_id` are the ownership of record (the
migration's own docstring says so), and `World.chat_ids` / `World.story_ids`
are a denormalised membership index the world page and the graph read. Two
columns describing one relationship is the shape that produced this codebase's
worst bug class, so both are written here and nowhere else: a caller that
sets one without the other leaves the world page and the timeline disagreeing
with the chat itself.

`a338abc0` added both columns and nothing wrote them — no route exposed the
field, no service set it, and the whole World entity was the same
"owns nothing" shape the Campaign rename was meant to leave behind.
"""

from sqlalchemy.orm import Session
from sqlmodel import select

from core.entities import Chat, Story, World
from core.exceptions import NotFoundError


def _membership_index(current: list[str] | None, entity_id: str, member: bool) -> list[str]:
    """The world's id list with `entity_id` added or removed, order-stable."""
    ids = list(current or [])
    if member and entity_id not in ids:
        ids.append(entity_id)
    elif not member and entity_id in ids:
        ids = [i for i in ids if i != entity_id]
    return ids


def link_chat_to_world(session: Session, chat: Chat, world_id: str | None) -> None:
    """Point `chat` at `world_id`, keeping the world's index consistent.

    `world_id=None` detaches. Detaching is a real operation rather than a
    no-op because the previous world still lists the chat, and a world that
    lists a chat the chat does not belong to is the one-sided write this
    module exists to prevent.
    """
    previous_id = chat.world_id
    chat.world_id = world_id or None

    worlds = {w.id: w for w in _resolve_worlds(session, previous_id, world_id)}
    for world_id_, world in worlds.items():
        world.chat_ids = _membership_index(
            world.chat_ids, chat.id, member=(world_id_ == chat.world_id)
        )
        session.add(world)


def link_story_to_world(session: Session, story: Story, world_id: str | None) -> None:
    """`link_chat_to_world` for a story. See that function for the rationale."""
    previous_id = story.world_id
    story.world_id = world_id or None

    worlds = {w.id: w for w in _resolve_worlds(session, previous_id, world_id)}
    for world_id_, world in worlds.items():
        world.story_ids = _membership_index(
            world.story_ids, story.id, member=(world_id_ == story.world_id)
        )
        session.add(world)


def _resolve_worlds(session: Session, *world_ids: str | None):
    seen: set[str] = set()
    for world_id in world_ids:
        if not world_id or world_id in seen:
            continue
        seen.add(world_id)
        world = session.get(World, world_id)
        if world is None:
            continue
        yield world


def require_world(session: Session, world_id: str | None) -> World | None:
    """Resolve a requested world, or `None` when none was requested.

    Raises rather than silently dropping an unknown id: a chat that looks like
    it belongs to a world but does not is exactly the state this codebase
    shipped for the whole World feature.
    """
    if not world_id:
        return None
    world = session.get(World, world_id)
    if world is None:
        raise NotFoundError("World", world_id)
    return world


def detach_world(session: Session, world_id: str) -> None:
    """Clear every owner reference to a world that is about to be deleted.

    `delete_world` calls this before the delete. Without it, `Chat.world_id` and
    `Story.world_id` are the only references in the vault with no scrub path.

    `scrub_entity_references` also has a `kind == "world"` branch, and it calls
    this function rather than repeating the two loops — it was written as a
    second, byte-equivalent copy.
    """
    for chat in session.exec(select(Chat).where(Chat.world_id == world_id)).all():
        chat.world_id = None
        session.add(chat)
    for story in session.exec(select(Story).where(Story.world_id == world_id)).all():
        story.world_id = None
        session.add(story)
