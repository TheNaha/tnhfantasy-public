"""
World Timeline — chronological aggregation of all events across entities.
"""
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select, or_, and_

from api.deps import get_session
from core.entities import Character, Chat, Message, Story, StoryChapter, CharacterMemory, Asset

router = APIRouter()


@router.get("/timeline")
def get_timeline(
    character_id: str | None = Query(default=None),
    story_id: str | None = Query(default=None),
    chat_id: str | None = Query(default=None),
    location: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    """Return a unified chronological timeline of events.
    
    Events include:
    - Messages (chat messages)
    - Chapter updates (story chapters)
    - Memory creation (character memories)
    - Image generation (assets)
    """
    events = []

    # Messages
    msg_query = select(Message).order_by(Message.created_at.desc()).limit(limit)
    if chat_id:
        msg_query = msg_query.where(Message.chat_id == chat_id)
    if character_id:
        msg_query = msg_query.join(Chat).where(Chat.character_id == character_id)
    if location:
        msg_query = msg_query.join(Chat).where(Chat.story_location == location)
    messages = session.exec(msg_query).all()
    for msg in messages:
        events.append({
            "type": "message",
            "id": msg.id,
            "timestamp": msg.created_at.isoformat() if msg.created_at else None,
            "title": f"Message in {msg.chat_id[:8]}...",
            "description": (msg.content or "")[:200],
            "character_id": msg.chat.character_id if msg.chat else None,
            "chat_id": msg.chat_id,
            "kind": msg.kind.value if msg.kind else None,
        })

    # Chapter updates
    chapter_query = select(StoryChapter).order_by(StoryChapter.updated_at.desc()).limit(limit)
    if story_id:
        chapter_query = chapter_query.where(StoryChapter.story_id == story_id)
    chapters = session.exec(chapter_query).all()
    for ch in chapters:
        events.append({
            "type": "chapter",
            "id": ch.id,
            "timestamp": ch.updated_at.isoformat() if ch.updated_at else None,
            "title": f"Chapter {ch.chapter_number}: {ch.title or 'Untitled'}",
            "description": (ch.content or "")[:200],
            "story_id": ch.story_id,
        })

    # Memories
    memory_query = select(CharacterMemory).order_by(CharacterMemory.created_at.desc()).limit(limit)
    if character_id:
        memory_query = memory_query.where(CharacterMemory.character_id == character_id)
    memories = session.exec(memory_query).all()
    for mem in memories:
        events.append({
            "type": "memory",
            "id": mem.id,
            "timestamp": mem.created_at.isoformat() if mem.created_at else None,
            "title": f"Memory for {mem.character_id[:8]}...",
            "description": (mem.content or "")[:200],
            "character_id": mem.character_id,
            "importance": mem.importance,
        })

    # Sort by timestamp descending
    events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)

    return {
        "events": events[:limit],
        "total": len(events),
        "limit": limit,
        "offset": offset,
    }
