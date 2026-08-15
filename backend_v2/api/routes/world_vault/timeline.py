"""
World Timeline — chronological aggregation of all events across entities.
"""
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, func, select

from api.deps import get_session
from core.entities import Chat, Message, StoryChapter, CharacterMemory, Asset

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
    fetch_limit = limit + offset

    # Messages
    msg_count_query = select(func.count(Message.id))
    msg_query = select(Message).order_by(Message.created_at.desc()).limit(fetch_limit)
    if chat_id:
        msg_count_query = msg_count_query.where(Message.chat_id == chat_id)
        msg_query = msg_query.where(Message.chat_id == chat_id)
    if character_id or location:
        # Single join; both filters apply to the same chats table.
        msg_count_query = msg_count_query.join(Chat)
        msg_query = msg_query.join(Chat)
        if character_id:
            msg_count_query = msg_count_query.where(Chat.character_id == character_id)
            msg_query = msg_query.where(Chat.character_id == character_id)
        if location:
            msg_count_query = msg_count_query.where(Chat.story_location == location)
            msg_query = msg_query.where(Chat.story_location == location)
    total_messages = session.exec(msg_count_query).one()
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
    chapter_count_query = select(func.count(StoryChapter.id))
    chapter_query = select(StoryChapter).order_by(StoryChapter.updated_at.desc()).limit(fetch_limit)
    if story_id:
        chapter_count_query = chapter_count_query.where(StoryChapter.story_id == story_id)
        chapter_query = chapter_query.where(StoryChapter.story_id == story_id)
    total_chapters = session.exec(chapter_count_query).one()
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
    memory_count_query = select(func.count(CharacterMemory.id))
    memory_query = select(CharacterMemory).order_by(CharacterMemory.created_at.desc()).limit(fetch_limit)
    if character_id:
        memory_count_query = memory_count_query.where(CharacterMemory.character_id == character_id)
        memory_query = memory_query.where(CharacterMemory.character_id == character_id)
    total_memories = session.exec(memory_count_query).one()
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

    # Image generations (assets)
    asset_count_query = select(func.count(Asset.id))
    asset_query = select(Asset).order_by(Asset.created_at.desc()).limit(fetch_limit)
    if character_id:
        asset_count_query = asset_count_query.where(Asset.character_id == character_id)
        asset_query = asset_query.where(Asset.character_id == character_id)
    if story_id:
        asset_count_query = asset_count_query.where(Asset.story_id == story_id)
        asset_query = asset_query.where(Asset.story_id == story_id)
    total_assets = session.exec(asset_count_query).one()
    assets = session.exec(asset_query).all()
    for a in assets:
        created = a.generated_at or a.created_at
        prompt = (a.metadata_ or {}).get("prompt") if a.metadata_ else None
        events.append({
            "type": "asset",
            "id": a.id,
            "timestamp": created.isoformat() if created else None,
            "title": f"Image: {a.filename}",
            "description": (prompt or a.relative_path or "")[:200],
            "character_id": a.character_id,
            "story_id": a.story_id,
            "kind": "image",
        })

    # Sort by timestamp descending
    events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)

    total = total_messages + total_chapters + total_memories + total_assets
    return {
        "events": events[offset:offset + limit],
        "total": total,
        "limit": limit,
        "offset": offset,
    }