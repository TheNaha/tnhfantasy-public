"""The World ↔ member relationship, in both directions, in one place.

A `World` owns Characters, Lorebooks, Locations, Scenarios, VoiceModels, Stories
and Chats. Ownership is a nullable `world_id` on each member table — seven
columns, each pointing at `worlds.id`.

It used to be six JSON id arrays on the `worlds` row, read by the world page and
the prompt builder, plus the two `world_id` FKs that
`_migration_077_campaigns_to_worlds` had added for chats and stories. So the
same relationship was described twice for chats and stories, and once (as a
guess) for everything else. Two columns describing one relationship is the shape
that produced this codebase's worst bug class, and it shipped the desync:
`PUT /api/v2/worlds/{id}` accepted `chat_ids` and `story_ids` directly while the
FK side that syncs them went through here, so a world could list a chat the chat
did not belong to; and `lorebook_ids`, `scenario_ids` and `voice_ids` had no
scrub path at all, so deleting an entity left its id in the array forever.

Migration `090_world_membership_fks` collapsed all of it onto `world_id`. The
rule now is the same one that applied to the FK pair and it holds for every
member: a caller that wants to move something between worlds writes
`member.world_id` through `link_to_world`, and a caller that wants to know
what a world contains reads `members_of`. Nothing else in the tree assigns
`world_id` or filters on it — the entity is the only writer, the FK is the only
reader, and there is nothing to desync because there is only one thing to
write.
"""

from collections.abc import Sequence
from datetime import datetime

from sqlmodel import Session, select

from core.entities import (
    Chat,
    Character,
    Lorebook,
    Location,
    Scenario,
    Story,
    VoiceModel,
    World,
)
from core.exceptions import NotFoundError

# Every member table and the label a NotFoundError uses for it. The tuple order
# is the order `detach_world` and `members_of` visit tables in, and it is the
# order the migration backfilled in — deliberately the same, so the two cannot
# disagree about which entity a world "already had".
MEMBER_TABLES: tuple[tuple[type, str], ...] = (
    (Character, "Character"),
    (Lorebook, "Lorebook"),
    (Location, "Location"),
    (Scenario, "Scenario"),
    (VoiceModel, "VoiceModel"),
    (Story, "Story"),
    (Chat, "Chat"),
)


def link_to_world(session: Session, entity, world_id: str | None) -> None:
    """Point `entity` at `world_id`. `None` detaches, leaving it in no world.

    One function for every member type, because the write is one column
    assignment and there is no index to keep in step any more. Detaching is a
    real operation rather than a no-op: the previous world's roster is derived
    from the FK, so clearing it is all that is needed — but it must actually
    happen, or the world keeps showing a member it does not own.
    """
    entity.world_id = world_id or None
    session.add(entity)


def require_world(session: Session, world_id: str | None) -> World | None:
    """Resolve a requested world, or `None` when none was requested.

    Raises rather than silently dropping an unknown id: an entity that looks
    like it belongs to a world but does not is exactly the state the World
    feature used to ship.
    """
    if not world_id:
        return None
    world = session.get(World, world_id)
    if world is None:
        raise NotFoundError("World", world_id)
    return world


def members_of(
    session: Session, world_id: str, model: type
) -> Sequence:
    """The world's members of one type, in the direction the FK means.

    An indexed lookup on `world_id`, not a scan of the world's old id array.
    Ordering is by the entity's own `name`/`title`/`id` where one exists so the
    world page and the prompt builder see the same order.
    """
    return list(session.exec(select(model).where(model.world_id == world_id)).all())


def detach_world(session: Session, world_id: str) -> None:
    """Clear every reference to a world that is about to be deleted.

    `world_id` has no ON DELETE clause on any member table, so deleting the
    world without this left members pointing at a row that no longer existed —
    including the lorebooks and locations that the prompt builder merges into
    every prompt built for a chat in that world.

    Covers all seven member tables, not just chats and stories: that is the whole
    point of the FK form. `scrub_entity_references` delegates here rather than
    repeating the loops, and entity deletes go through `detach_entity`, which is
    the mirror of this function.
    """
    for model, _label in MEMBER_TABLES:
        for entity in session.exec(
            select(model).where(model.world_id == world_id)
        ).all():
            entity.world_id = None
            session.add(entity)


def detach_entity(session: Session, entity) -> None:
    """The mirror of `detach_world`, for a single member being deleted.

    Called from `scrub_entity_references` before an entity is removed. Clears
    the entity's own `world_id` so the world it belonged to stops counting it —
    the reason this exists is that the old arrays kept the id after the entity
    was gone, in all three columns that had no scrub branch.
    """
    entity.world_id = None
    session.add(entity)


def apply_world_id(session: Session, entity, update_data: dict) -> None:
    """Apply a member's `world_id` from an update payload, or leave it alone.

    The distinction this preserves is "field absent" versus "field is null".
    A member's route dumps with `exclude_unset=True`, so an absent `world_id`
    is not in the dict at all and a partial update cannot detach a member from
    its world by accident — the same reason `chats.py` keeps a `_WORLD_ID_UNSET`
    sentinel for its own full-replacement PUT. An explicit `null` detaches.

    `require_world` first, so a typo'd world id is a 404 rather than a stored FK
    pointing at a row that does not exist. That is what the old world-side
    arrays could not do: `PUT /api/v2/worlds/{id}` accepted any string.
    """
    if "world_id" not in update_data:
        return
    world_id = update_data.get("world_id")
    require_world(session, world_id)
    link_to_world(session, entity, world_id)


def world_scenario(session: Session, world_id: str) -> Scenario | None:
    """The world's fallback scenario, or None.

    A world's scenarios are `Scenario.world_id == world_id` — a set with no
    stored order, unlike the array this replaces which had one. Ordering by
    `created_at, id` makes the pick deterministic, which is what the array's
    order was doing implicitly: two scenarios in one world must not swap
    depending on which row the planner visits first.
    """
    rows = session.exec(
        select(Scenario).where(Scenario.world_id == world_id)
    ).all()
    ordered = sorted(
        rows,
        key=lambda s: (s.created_at or datetime.min, s.id),
    )
    return ordered[0] if ordered else None
