"""Scrub cross-entity references when a World Vault entity is deleted.

Entities keep JSON-array associations (Story.character_ids, Campaign.story_ids,
etc.) and a few bare id columns instead of FK-backed join tables. When an
entity is deleted, every referencing row must have the dangling id removed,
otherwise the vault leaks stale references (ghost characters in stories,
broken dashboard links, etc.).
"""
from sqlmodel import Session, select

from core.entities import Campaign, Character, Chat, Message, Story


def _without(ids, entity_id):
    if not ids:
        return ids
    return [i for i in ids if i != entity_id]


def _scrub_stories(session, field, entity_id):
    for row in session.exec(select(Story)).all():
        if entity_id in getattr(row, field):
            setattr(row, field, _without(getattr(row, field), entity_id))


def _scrub_chats(session, field, entity_id):
    for row in session.exec(select(Chat)).all():
        if entity_id in getattr(row, field):
            setattr(row, field, _without(getattr(row, field), entity_id))


def _scrub_campaigns(session, field, entity_id):
    for row in session.exec(select(Campaign)).all():
        if entity_id in getattr(row, field):
            setattr(row, field, _without(getattr(row, field), entity_id))


def scrub_entity_references(session: Session, kind: str, entity_id: str) -> None:
    """Remove `entity_id` from every reference to a deleted entity of `kind`."""
    if kind == "character":
        _scrub_stories(session, "character_ids", entity_id)
        _scrub_chats(session, "additional_character_ids", entity_id)
        _scrub_campaigns(session, "character_ids", entity_id)
        for chat in session.exec(select(Chat).where(Chat.character_id == entity_id)).all():
            chat.character_id = None
        for msg in session.exec(select(Message).where(Message.character_id == entity_id)).all():
            msg.character_id = None
    elif kind == "lorebook":
        _scrub_stories(session, "lorebook_ids", entity_id)
        _scrub_chats(session, "active_lorebook_ids", entity_id)
    elif kind == "voice":
        for character in session.exec(select(Character).where(Character.voice_model_id == entity_id)).all():
            character.voice_model_id = None
    elif kind == "scenario":
        for story in session.exec(select(Story).where(Story.scenario_id == entity_id)).all():
            story.scenario_id = None
    elif kind == "story":
        _scrub_campaigns(session, "story_ids", entity_id)
    elif kind == "chat":
        _scrub_campaigns(session, "chat_ids", entity_id)
    elif kind == "location":
        _scrub_campaigns(session, "location_ids", entity_id)