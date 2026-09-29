"""
World Timeline — chronological aggregation of all events across entities.
"""
from fastapi import APIRouter, Depends, Query

from core.exceptions import ValidationError
from sqlalchemy import and_, or_
from sqlmodel import Session, func, select

from api.deps import get_session
from core.entities import Asset, Chat, CharacterMemory, Message, Story, StoryChapter

# The four sources are merged and then sorted, so a page of the merged timeline
# needs up to `limit + offset` rows from EACH of them — the multiplier that
# makes an uncapped `offset` four times as expensive as it looks.
MAX_TIMELINE_OFFSET = 10_000
MAX_TIMELINE_FETCH = 5_000

# What a client may put in `?types=`, mapped to the `type` the events below
# actually carry.
#
# `image` and `asset` name the same stream. The Activity page sends `image`
# (`showImages ? 'message,chapter,memory,image' : ...`) and the validation
# message above only ever advertised `image`, but the events are emitted with
# `type: "asset"` — so the filter at the end matched nothing and the "show
# images" toggle silently did nothing at all.
EVENT_TYPE_ALIASES = {
    "message": "message",
    "chapter": "chapter",
    "memory": "memory",
    "image": "asset",
    "asset": "asset",
}

router = APIRouter()


@router.get("/timeline")
def get_timeline(
    character_id: str | None = Query(default=None),
    story_id: str | None = Query(default=None),
    chat_id: str | None = Query(default=None),
    location: str | None = Query(default=None),
    world_id: str | None = Query(default=None),
    types: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0, le=MAX_TIMELINE_OFFSET),
    session: Session = Depends(get_session),
):
    """Return a unified chronological feed of activity.

    NOT a world timeline. It has no world, no world_id, and no notion of one —
    it merges four unrelated streams by timestamp:
      - Messages (chat messages)
      - Chapter updates (story chapters)
      - Memory creation (character memories)
      - Image generation (assets)

    The name was the problem. Called "World Timeline" and described as "see how a
    world changes over time", it read as authored chronology — canon, the order
    things happened in the fiction. It is the opposite: a log of what YOU did, and
    `assets` is ~99% of it. Measured on the live deployment, 16,529 events, and
    page 1 was 200 consecutive image generations with one narrative event in
    sight. A user looking for lore chronology found their own message log.

    `types` exists because of that asymmetry. `?types=message,chapter,memory`
    returns the narrative streams alone, which is what anyone opening this page
    actually wanted. Image generation already has a page of its own — the
    Gallery, which is where clicking an image event already sent them.
    """
    wanted: set[str] | None = None
    if types:
        wanted = {t.strip() for t in types.split(",") if t.strip()}
        unknown = wanted - set(EVENT_TYPE_ALIASES)
        if unknown:
            # ValidationError, not ValueError: a bare ValueError escapes the
            # handler as a 500, so a typo in a query parameter read as a server
            # fault rather than a bad request.
            raise ValidationError(
                f"unknown event type(s) {sorted(unknown)}; valid types are "
                "message, chapter, memory, image"
            )
        wanted = {EVENT_TYPE_ALIASES[t] for t in wanted}

    events = []
    # `offset` was uncapped, and this is applied to FOUR independent queries
    # below (messages, chapters, memories, assets), so
    # `?limit=500&offset=1000000` asked each of them for 1,000,500 rows. The
    # offset cap is the fix that makes the multiply harmless; the hard ceiling
    # is a second belt in case the cap and the arithmetic ever drift apart.
    fetch_limit = min(limit + offset, MAX_TIMELINE_FETCH)

    # Messages
    #
    # Two separate defects in this one loop:
    #
    # 1. N+1. It read `msg.chat.character_id`, and Message.chat is a plain
    #    lazy="select" relationship. The query was `select(Message)` with at
    #    most a bare `.join(Chat)` and never `contains_eager`, so every one of
    #    the up-to-(limit+offset) rows fired its own SELECT — 600 extra round
    #    trips on a `?limit=500&offset=100` request. The chat is now selected
    #    explicitly in the same statement, so one round trip covers the page.
    #
    # 2. Wrong attribution. It reported the CHAT's primary character for every
    #    message, so a `?character_id=X` timeline labelled every message in that
    #    chat as X — including narrator turns and the other members of a group
    #    chat. `Message.character_id` is the SPEAKING character (indexed, added
    #    by migration 060) and is what should be reported, with the chat's
    #    primary character only as the fallback for messages that have none.
    msg_count_query = select(func.count(Message.id))
    msg_query = (
        select(Message, Chat)
        .outerjoin(Chat, Chat.id == Message.chat_id)
        .order_by(Message.created_at.desc())
        .limit(fetch_limit)
    )
    if chat_id:
        msg_count_query = msg_count_query.where(Message.chat_id == chat_id)
        msg_query = msg_query.where(Message.chat_id == chat_id)
    if world_id:
        # The World is the one scoping relationship in this system, and this
        # endpoint had no notion of one — its own docstring said so. Messages
        # scope by the owning chat's world, chapters by the story's.
        # The count query selects from `messages` only, so it needs its own
        # join; without it the WHERE references an unrelated FROM element and
        # SQLAlchemy warns about (and Postgres executes) a cartesian product.
        msg_count_query = msg_count_query.join(Chat).where(Chat.world_id == world_id)
        msg_query = msg_query.where(Chat.world_id == world_id)
    if character_id or location:
        # The filters below are on Chat. The main query already joins Chat, but
        # the count query does not select it, so it needs its own join —
        # without it the WHERE references an unrelated FROM element and
        # SQLAlchemy warns about (and Postgres executes) a cartesian product.
        msg_count_query = msg_count_query.join(Chat)
        if character_id:
            # On `Message.character_id` — who spoke — not `Chat.character_id`,
            # which is the chat's *primary* character. The old form returned
            # every line of every group chat a character was in, including the
            # other characters' replies, and excluded any chat where the
            # character was a secondary member. The event payload has always
            # reported the speaker, so the filter now agrees with the thing it
            # filters.
            #
            # The `IS NULL` arm is the same fallback the event payload already
            # applies (`chat_character_id` below): a message with no recorded
            # speaker belongs to whoever the chat is about. Without it, a
            # character filter would return nothing at all for any message
            # written before speaker attribution existed.
            msg_count_query = msg_count_query.where(
                or_(
                    Message.character_id == character_id,
                    and_(Message.character_id.is_(None), Chat.character_id == character_id),
                )
            )
            msg_query = msg_query.where(
                or_(
                    Message.character_id == character_id,
                    and_(Message.character_id.is_(None), Chat.character_id == character_id),
                )
            )
        if location:
            msg_count_query = msg_count_query.where(Chat.story_location == location)
            msg_query = msg_query.where(Chat.story_location == location)
    total_messages = session.exec(msg_count_query).one()
    message_rows = session.exec(msg_query).all()
    for msg, chat in message_rows:
        chat_character_id = chat.character_id if chat else None
        events.append({
            "type": "message",
            "id": msg.id,
            "timestamp": msg.created_at.isoformat() if msg.created_at else None,
            "title": f"Message in {msg.chat_id[:8]}...",
            "description": (msg.content or "")[:200],
            # The speaker, not the chat's primary character. Falls back to the
            # chat's primary character for narrator/user/system turns, which is
            # what the old (wrong) value always was.
            "character_id": msg.character_id or chat_character_id,
            "chat_id": msg.chat_id,
            "kind": msg.kind.value if msg.kind else None,
        })

    # Chapter updates
    chapter_count_query = select(func.count(StoryChapter.id))
    chapter_query = select(StoryChapter).order_by(StoryChapter.updated_at.desc()).limit(fetch_limit)
    if story_id:
        chapter_count_query = chapter_count_query.where(StoryChapter.story_id == story_id)
        chapter_query = chapter_query.where(StoryChapter.story_id == story_id)
    if world_id:
        # Chapters carry no world of their own — the story owns it.
        chapter_count_query = chapter_count_query.join(Story).where(Story.world_id == world_id)
        chapter_query = chapter_query.join(Story).where(Story.world_id == world_id)
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
    #
    # Narrowed columns, for the same reason the gallery was: `assets` is ~99% of
    # this feed and ~3.4 kB per row, almost all of it in the `metadata_` jsonb.
    # `select(Asset)` materialised every column of up to `fetch_limit` (5000) rows
    # on the event loop to build a title, a 200-character description and two ids.
    # Only the columns the event below is built from are selected; the count query
    # beside it already worked this way.
    asset_count_query = select(func.count(Asset.id))
    asset_query = (
        select(
            Asset.id,
            Asset.filename,
            Asset.relative_path,
            Asset.character_id,
            Asset.story_id,
            Asset.generated_at,
            Asset.created_at,
            Asset.metadata_["prompt"].as_string(),
        )
        .order_by(Asset.created_at.desc())
        .limit(fetch_limit)
    )
    if character_id:
        asset_count_query = asset_count_query.where(Asset.character_id == character_id)
        asset_query = asset_query.where(Asset.character_id == character_id)
    if story_id:
        asset_count_query = asset_count_query.where(Asset.story_id == story_id)
        asset_query = asset_query.where(Asset.story_id == story_id)
    total_assets = session.exec(asset_count_query).one()
    for a_id, a_filename, a_relative_path, a_character_id, a_story_id, a_generated_at, a_created_at, a_prompt in session.exec(asset_query).all():
        created = a_generated_at or a_created_at
        events.append({
            "type": "asset",
            "id": a_id,
            "timestamp": created.isoformat() if created else None,
            "title": f"Image: {a_filename}",
            "description": (a_prompt or a_relative_path or "")[:200],
            "character_id": a_character_id,
            "story_id": a_story_id,
            "kind": "image",
        })

    # Applied here rather than by skipping each stream's query.
    #
    # One place, and it cannot be forgotten when a stream is added: the four
    # collectors append into the same `events` list with their own `type`, so
    # filtering once at the end is both correct and impossible to get wrong by
    # omission. Skipping the queries instead would be faster but needs a guard
    # beside each of them, and the day someone adds a fifth stream without one it
    # silently ignores the filter.
    if wanted is not None:
        events = [e for e in events if e.get("type") in wanted]

    # Sort by timestamp descending
    events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)

    total = total_messages + total_chapters + total_memories + total_assets
    return {
        "events": events[offset:offset + limit],
        "total": total,
        "limit": limit,
        "offset": offset,
    }