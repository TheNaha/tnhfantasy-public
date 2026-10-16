"""Scrub cross-entity references when a World Vault entity is deleted.

Most associations are id arrays on the referencing row (`Story.character_ids`,
`Chat.active_lorebook_ids`) or bare id columns, not join tables. When an entity
is deleted, every referencing row must drop the dangling id or the vault leaks
stale references — ghost characters in stories, broken dashboard links.

World membership is the exception, and it is the one that used to leak: it was
six JSON id arrays on the `worlds` row, and only two of them (`chat_ids`,
`story_ids`) had a scrub branch here. Deleting a Character, Lorebook, Location,
Scenario or VoiceModel left its id in the array forever, and deleting a world
left every member pointing at a row that no longer existed. Membership is now
`<member>.world_id` on the member side, so both directions are one column:
`detach_entity` on member delete, `detach_world` on world delete, both in
`services.world_ownership.py`. Nothing here reaches into `worlds` at all.
"""

from sqlalchemy import Text, cast
from sqlmodel import Session, delete, select

from core.entities import (
    Asset,
    Character,
    Chat,
    GraphLayout,
    Lorebook,
    Location,
    Message,
    Scenario,
    Story,
    StoryBeat,
    StoryChapter,
    StoryChapterRevision,
    VoiceModel,
)
from core.sql_search import LIKE_ESCAPE_CHAR, like_contains


def _without(ids, entity_id):
    if not ids:
        return ids
    return [i for i in ids if i != entity_id]


def _scrub_json_array(session, model, field, entity_id):
    """Remove entity_id from JSON arrays using SQL-level filtering.

    Uses LIKE to find only rows that may contain the id, avoiding
    full-table scans on every delete. The pattern goes through the shared
    escaping helper: a raw `%`/`_` in the id would otherwise match unrelated
    JSON and strip the *wrong* id out of a Story's `character_ids`. Same
    helper `asset_metadata_index` and `tag_service` already use.
    """
    pattern = like_contains(f'"{entity_id}"')
    rows = session.exec(
        select(model).where(
            cast(getattr(model, field), Text).like(pattern, escape=LIKE_ESCAPE_CHAR)
        )
    ).all()
    for row in rows:
        setattr(row, field, _without(getattr(row, field), entity_id))


def _scrub_stories(session, field, entity_id):
    _scrub_json_array(session, Story, field, entity_id)


def _scrub_chats(session, field, entity_id):
    _scrub_json_array(session, Chat, field, entity_id)


def _detach_from_world(session, model, entity_id):
    """Clear the member's own `world_id` before it is deleted.

    The member is the row carrying the reference, so this is the entire scrub —
    there is no world-side array to clean up any more, which is the point. The
    write goes through `world_ownership.link_to_world` rather than a bare
    assignment, so there is exactly one place in the tree that writes
    `world_id`; `test_audit_2026_09_29b_p0` walks the AST to hold that.
    """
    from services.world_ownership import link_to_world

    row = session.get(model, entity_id)
    if row is None:
        return
    link_to_world(session, row, None)


def _drop_graph_node(session: Session, entity_id: str) -> None:
    """Remove a world-graph node for a deleted entity.

    Matched on `entity_id` alone, not `entity_id` + `entity_type`. The column
    exists and the API accepts it, but the only consumer keys on the id
    (`RelationshipGraph` builds its map with `map.set(n.entity_id, ...)`), so
    the type half of the row's unique constraint is write-only: two rows can
    share one entity under different types and the read picks arbitrarily.
    Matching on both would leave whichever spelling disagreed behind.
    """
    for layout in session.exec(select(GraphLayout).where(GraphLayout.entity_id == entity_id)).all():
        session.delete(layout)


def scrub_entity_references(session: Session, kind: str, entity_id: str) -> None:
    """Remove `entity_id` from every reference to a deleted entity of `kind`.

    An unknown `kind` is a silent no-op, which is itself a trap: both delete
    routes below pass `"chat"` and `"story"`, and before those branches existed
    the whole `if/elif` chain fell through for them. Nothing raised, nothing
    logged, and the vault quietly accumulated dangling rows — so this asserts
    on the unknown case instead of ignoring it.
    """
    if kind == "character":
        _scrub_stories(session, "character_ids", entity_id)
        _scrub_chats(session, "additional_character_ids", entity_id)
        for chat in session.exec(select(Chat).where(Chat.character_id == entity_id)).all():
            chat.character_id = None
        for msg in session.exec(select(Message).where(Message.character_id == entity_id)).all():
            msg.character_id = None
        # voice_models.character_id is a NOT-NULL-blocking FK with no ON DELETE
        # clause, so leaving it set made delete_character fail with an
        # IntegrityError.  Detach the voice models instead of deleting them.
        for voice in session.exec(select(VoiceModel).where(VoiceModel.character_id == entity_id)).all():
            voice.character_id = None
        _detach_from_world(session, Character, entity_id)
        _drop_graph_node(session, entity_id)
    elif kind == "lorebook":
        _scrub_stories(session, "lorebook_ids", entity_id)
        _scrub_chats(session, "active_lorebook_ids", entity_id)
        for character in session.exec(select(Character).where(Character.embedded_lorebook_id == entity_id)).all():
            character.embedded_lorebook_id = None
        # `Character.lorebook_ids` is the character's own link to the vault's
        # library, distinct from `embedded_lorebook_id` — the SillyTavern
        # `character_book` that arrived inside an imported card and is
        # round-tripped on export. Only the explicit link is scrubbed. It is
        # read on every prompt build, so a dangling id would be a per-turn
        # lookup that silently finds nothing rather than a visible error.
        #
        # `_scrub_json_array` rather than `select(Character)`: this loop loaded
        # every character row in the vault to test one JSON array, on the delete
        # path, three lines below the helper that already does this correctly.
        _scrub_json_array(session, Character, "lorebook_ids", entity_id)
        _detach_from_world(session, Lorebook, entity_id)
        _drop_graph_node(session, entity_id)
    elif kind == "voice":
        for character in session.exec(select(Character).where(Character.voice_model_id == entity_id)).all():
            character.voice_model_id = None
        for chat in session.exec(select(Chat).where(Chat.tts_voice_id == entity_id)).all():
            chat.tts_voice_id = None
        _detach_from_world(session, VoiceModel, entity_id)
        _drop_graph_node(session, entity_id)
    elif kind == "scenario":
        for story in session.exec(select(Story).where(Story.scenario_id == entity_id)).all():
            story.scenario_id = None
        for chat in session.exec(select(Chat).where(Chat.scenario_id == entity_id)).all():
            chat.scenario_id = None
        _detach_from_world(session, Scenario, entity_id)
        _drop_graph_node(session, entity_id)
    elif kind == "persona":
        for chat in session.exec(select(Chat).where(Chat.persona_id == entity_id)).all():
            chat.persona_id = None
        for story in session.exec(select(Story).where(Story.persona_id == entity_id)).all():
            story.persona_id = None
        _drop_graph_node(session, entity_id)
    elif kind == "world":
        # Delegates rather than repeating. Covers all seven member tables —
        # deleting a world used to leave Character, Lorebook, Location,
        # Scenario and VoiceModel rows pointing at a world that no longer
        # existed, because the arrays on the `worlds` row died with it and
        # nothing on the member side moved.
        from services.world_ownership import detach_world

        detach_world(session, entity_id)
        _drop_graph_node(session, entity_id)
    elif kind == "location":
        _scrub_stories(session, "location_ids", entity_id)
        for chat in session.exec(select(Chat).where(Chat.location_id == entity_id)).all():
            chat.location_id = None
        _detach_from_world(session, Location, entity_id)
        _drop_graph_node(session, entity_id)
    elif kind == "chat":
        # Direct SQL DELETE and a flush, ahead of the route's `session.delete(chat)`.
        # The ORM unit of work is free to issue the chat DELETE before the
        # message DELETEs, and then `messages_chat_id_fkey` rejects the whole
        # transaction. It has to happen here rather than in the route because
        # this is the only place that knows the whole reference set, and the
        # route's hand-rolled copy of it had already drifted — it could not see
        # the graph layout node below.
        session.exec(delete(Message).where(Message.chat_id == entity_id))
        session.flush()
        _drop_graph_node(session, entity_id)
    elif kind == "story":
        # Everything here cascades by hand because the schema does not:
        # `story_beats.chapter_id` and `story_chapter_revisions.story_id` are
        # bare VARCHAR columns with no foreign key and no ON DELETE, so
        # deleting chapters leaves their rows behind with nothing to complain.
        # Beats were the worse of the two — invisible, unbounded, and a chapter
        # id that could later be regenerated onto unrelated content.
        chapter_ids = list(
            session.exec(select(StoryChapter.id).where(StoryChapter.story_id == entity_id)).all()
        )
        if chapter_ids:
            session.exec(delete(StoryBeat).where(StoryBeat.chapter_id.in_(chapter_ids)))
            session.exec(delete(StoryChapterRevision).where(StoryChapterRevision.chapter_id.in_(chapter_ids)))
        session.flush()
        # The images themselves stay. `Asset.story_id` is a bare column with no
        # FK, and an orphaned gallery entry is worse than an untagged one, so
        # the tag is dropped and the picture survives.
        for asset in session.exec(select(Asset).where(Asset.story_id == entity_id)).all():
            asset.story_id = None
        _drop_graph_node(session, entity_id)
    else:
        raise ValueError(f"scrub_entity_references: unknown entity kind {kind!r}")
