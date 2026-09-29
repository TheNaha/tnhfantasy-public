"""Scrub cross-entity references when a World Vault entity is deleted.

Entities keep JSON-array associations (Story.character_ids, World.story_ids,
etc.) and a few bare id columns instead of FK-backed join tables. When an
entity is deleted, every referencing row must have the dangling id removed,
otherwise the vault leaks stale references (ghost characters in stories,
broken dashboard links, etc.).
"""
from sqlalchemy import Text, cast
from sqlmodel import Session, select

from core.entities import World, Character, Chat, Message, Story, VoiceModel


def _without(ids, entity_id):
    if not ids:
        return ids
    return [i for i in ids if i != entity_id]


def _scrub_json_array(session, model, field, entity_id):
    """Remove entity_id from JSON arrays using SQL-level filtering.

    Uses LIKE to find only rows that may contain the id, avoiding
    full-table scans on every delete.
    """
    pattern = f'%"{entity_id}"%'
    rows = session.exec(
        select(model).where(cast(getattr(model, field), Text).like(pattern))
    ).all()
    for row in rows:
        setattr(row, field, _without(getattr(row, field), entity_id))


def _scrub_stories(session, field, entity_id):
    _scrub_json_array(session, Story, field, entity_id)


def _scrub_chats(session, field, entity_id):
    _scrub_json_array(session, Chat, field, entity_id)


def _scrub_worlds(session, field, entity_id):
    _scrub_json_array(session, World, field, entity_id)


def scrub_entity_references(session: Session, kind: str, entity_id: str) -> None:
    """Remove `entity_id` from every reference to a deleted entity of `kind`."""
    if kind == "character":
        _scrub_stories(session, "character_ids", entity_id)
        _scrub_chats(session, "additional_character_ids", entity_id)
        _scrub_worlds(session, "character_ids", entity_id)
        for chat in session.exec(select(Chat).where(Chat.character_id == entity_id)).all():
            chat.character_id = None
        for msg in session.exec(select(Message).where(Message.character_id == entity_id)).all():
            msg.character_id = None
        # voice_models.character_id is a NOT-NULL-blocking FK with no ON DELETE
        # clause, so leaving it set made delete_character fail with an
        # IntegrityError.  Detach the voice models instead of deleting them.
        for voice in session.exec(select(VoiceModel).where(VoiceModel.character_id == entity_id)).all():
            voice.character_id = None
    elif kind == "lorebook":
        _scrub_stories(session, "lorebook_ids", entity_id)
        _scrub_chats(session, "active_lorebook_ids", entity_id)
        for character in session.exec(select(Character).where(Character.embedded_lorebook_id == entity_id)).all():
            character.embedded_lorebook_id = None
    elif kind == "voice":
        for character in session.exec(select(Character).where(Character.voice_model_id == entity_id)).all():
            character.voice_model_id = None
        for chat in session.exec(select(Chat).where(Chat.tts_voice_id == entity_id)).all():
            chat.tts_voice_id = None
    elif kind == "scenario":
        for story in session.exec(select(Story).where(Story.scenario_id == entity_id)).all():
            story.scenario_id = None
    elif kind == "persona":
        for chat in session.exec(select(Chat).where(Chat.persona_id == entity_id)).all():
            chat.persona_id = None
    elif kind == "world":
        # `Chat.world_id` / `Story.world_id` are the ownership of record and
        # `World.chat_ids` / `World.story_ids` are its denormalised index, so
        # deleting a world has to clear both directions. `delete_world` calls
        # `world_ownership.detach_world` for the FK columns; the index lives on
        # the row being deleted and goes with it.
        #
        # This branch did not exist when the module was written, because
        # nothing set `world_id` then — the World entity owned nothing, which is
        # the defect the whole feature was added to fix.
        for chat in session.exec(select(Chat).where(Chat.world_id == entity_id)).all():
            chat.world_id = None
        for story in session.exec(select(Story).where(Story.world_id == entity_id)).all():
            story.world_id = None
    elif kind == "story":
        _scrub_worlds(session, "story_ids", entity_id)
    elif kind == "chat":
        _scrub_worlds(session, "chat_ids", entity_id)
    elif kind == "location":
        _scrub_stories(session, "location_ids", entity_id)
        _scrub_worlds(session, "location_ids", entity_id)
        for chat in session.exec(select(Chat).where(Chat.location_id == entity_id)).all():
            chat.location_id = None
