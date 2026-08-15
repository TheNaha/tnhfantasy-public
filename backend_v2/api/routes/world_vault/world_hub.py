"""
World Vault Hub — unified endpoints for browsing relationships and searching
across all entity types.
"""
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select, func
from sqlalchemy import cast, String

from api.deps import get_session
from core.entities import (
    Character, Chat, Lorebook, LorebookEntry, Message,
    Story, StoryChapter, Scenario, VoiceModel, CharacterMemory,
    Location, Campaign,
)
from core.exceptions import NotFoundError

router = APIRouter()


@router.get("/entities")
def get_entity_dashboard(session: Session = Depends(get_session)):
    """Return entity counts and recent activity for the World Vault Hub."""
    counts = {
        "characters": session.exec(select(func.count()).select_from(Character)).one(),
        "chats": session.exec(select(func.count()).select_from(Chat)).one(),
        "stories": session.exec(select(func.count()).select_from(Story)).one(),
        "lorebooks": session.exec(select(func.count()).select_from(Lorebook)).one(),
        "lorebook_entries": session.exec(select(func.count()).select_from(LorebookEntry)).one(),
        "scenarios": session.exec(select(func.count()).select_from(Scenario)).one(),
        "voices": session.exec(select(func.count()).select_from(VoiceModel)).one(),
        "memories": session.exec(select(func.count()).select_from(CharacterMemory)).one(),
        "locations": session.exec(select(func.count()).select_from(Location)).one(),
        "campaigns": session.exec(select(func.count()).select_from(Campaign)).one(),
    }

    # Recent activity: last 5 characters, chats, stories
    recent_chars = session.exec(
        select(Character).order_by(Character.created_at.desc()).limit(5)
    ).all()
    recent_chats = session.exec(
        select(Chat).order_by(Chat.created_at.desc()).limit(5)
    ).all()
    recent_stories = session.exec(
        select(Story).order_by(Story.created_at.desc()).limit(5)
    ).all()

    return {
        "counts": counts,
        "recent": {
            "characters": [
                {"id": c.id, "name": c.name, "created_at": c.created_at.isoformat() if c.created_at else None}
                for c in recent_chars
            ],
            "chats": [
                {"id": c.id, "name": c.name, "created_at": c.created_at.isoformat() if c.created_at else None}
                for c in recent_chats
            ],
            "stories": [
                {"id": s.id, "title": s.title, "created_at": s.created_at.isoformat() if s.created_at else None}
                for s in recent_stories
            ],
        },
    }


@router.get("/relationships")
def get_relationships(session: Session = Depends(get_session)):
    """Return entity relationship graph data."""
    # Character → Chats
    char_chat_links = [
        tuple(row) for row in session.exec(
            select(Character.id, Character.name, Chat.id, Chat.name)
            .join(Chat, Chat.character_id == Character.id)
            .limit(100)
        ).all()
    ]

    # Character → Stories (via character_ids JSON)
    char_story_links = []
    for char in session.exec(select(Character).limit(100)).all():
        stories = session.exec(
            select(Story).where(cast(Story.character_ids, String).contains(char.id))
        ).all()
        for s in stories:
            char_story_links.append({
                "character_id": char.id,
                "character_name": char.name,
                "story_id": s.id,
                "story_title": s.title,
            })

    # Story → Lorebooks (via lorebook_ids JSON)
    story_lorebook_links = []
    for story in session.exec(select(Story).limit(100)).all():
        lorebooks = session.exec(
            select(Lorebook).where(Lorebook.id.in_(story.lorebook_ids or []))
        ).all()
        for lb in lorebooks:
            story_lorebook_links.append({
                "story_id": story.id,
                "story_title": story.title,
                "lorebook_id": lb.id,
                "lorebook_name": lb.name,
            })

    # Character → VoiceModels
    voice_links = [
        tuple(row) for row in session.exec(
            select(VoiceModel.id, VoiceModel.name, Character.id, Character.name)
            .join(Character, Character.id == VoiceModel.character_id)
            .limit(50)
        ).all()
    ]

    # Story → Locations (via location_ids JSON)
    story_location_links = []
    for story in session.exec(select(Story).limit(100)).all():
        locations = session.exec(
            select(Location).where(Location.id.in_(story.location_ids or []))
        ).all()
        for loc in locations:
            story_location_links.append({
                "story_id": story.id,
                "story_title": story.title,
                "location_id": loc.id,
                "location_name": loc.name,
            })

    # Chat → Locations (via location_id FK)
    chat_location_links = [
        tuple(row) for row in session.exec(
            select(Chat.id, Chat.name, Location.id, Location.name)
            .join(Location, Location.id == Chat.location_id)
            .limit(100)
        ).all()
    ]

    return {
        "character_chats": char_chat_links,
        "character_stories": char_story_links,
        "story_lorebooks": story_lorebook_links,
        "character_voices": voice_links,
        "story_locations": story_location_links,
        "chat_locations": chat_location_links,
    }


@router.get("/search")
def search_entities(
    q: str = Query(..., min_length=2),
    type: str | None = Query(default=None, description="Filter by entity type: character, chat, story, lorebook, scenario, voice, memory"),
    session: Session = Depends(get_session),
):
    """Unified search across characters, chats, stories, lorebooks, scenarios, voices."""
    pattern = f"%{q}%"
    results = []

    def _add(entity_type, items, title_fn, subtitle_fn):
        if type and type != entity_type:
            return
        for item in items:
            results.append({
                "type": entity_type,
                "id": item.id,
                "title": title_fn(item),
                "subtitle": subtitle_fn(item),
            })

    # Characters (name + description + personality)
    _add("character", session.exec(
        select(Character).where(
            (func.lower(Character.name).like(func.lower(pattern)))
            | (func.lower(Character.description).like(func.lower(pattern)))
        ).limit(10)
    ).all(), lambda c: c.name, lambda c: c.description[:100] if c.description else "")

    # Stories (title + description)
    _add("story", session.exec(
        select(Story).where(
            (func.lower(Story.title).like(func.lower(pattern)))
            | (func.lower(Story.description).like(func.lower(pattern)))
        ).limit(10)
    ).all(), lambda s: s.title, lambda s: s.description[:100] if s.description else "")

    # Chats (name)
    _add("chat", session.exec(
        select(Chat).where(func.lower(Chat.name).like(func.lower(pattern))).limit(10)
    ).all(), lambda c: c.name, lambda c: f"{c.chat_type}")

    # Lorebooks (name)
    _add("lorebook", session.exec(
        select(Lorebook).where(func.lower(Lorebook.name).like(func.lower(pattern))).limit(10)
    ).all(), lambda l: l.name, lambda l: l.description[:100] if l.description else "")

    # Scenarios (name + prompt_template)
    _add("scenario", session.exec(
        select(Scenario).where(func.lower(Scenario.name).like(func.lower(pattern))).limit(10)
    ).all(), lambda s: s.name, lambda s: s.description[:100] if s.description else "")

    # Voices (name)
    _add("voice", session.exec(
        select(VoiceModel).where(func.lower(VoiceModel.name).like(func.lower(pattern))).limit(10)
    ).all(), lambda v: v.name, lambda v: v.description[:100] if v.description else "")

    # Memories (content)
    _add("memory", session.exec(
        select(CharacterMemory).where(func.lower(CharacterMemory.content).like(func.lower(pattern))).limit(10)
    ).all(),
       lambda m: (m.content[:80] + "…") if len(m.content) > 80 else m.content,
       lambda m: f"Tags: {', '.join(m.tags or [])}" if m.tags else "")

    return {"query": q, "results": results, "total": len(results)}
