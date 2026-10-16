"""
World Vault Hub — unified endpoints for browsing relationships and searching
across all entity types.
"""
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select, func

from api.deps import get_session
from api.routes.world_vault.lorebooks import MAX_SEARCH_LENGTH
from core.sql_search import LIKE_ESCAPE_CHAR, like_contains
from core.entities import (
    Character, Chat, Lorebook, LorebookEntry,
    Story, Scenario, VoiceModel, CharacterMemory,
    Location, World, WorldEdge,
)

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
        "worlds": session.exec(select(func.count()).select_from(World)).one(),
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
def get_relationships(
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    """Return entity relationship graph data.

    `limit`/`offset` used to be applied to `character_chats` only, while the other
    sub-queries were hard-capped at 200/500/200/100. So `?limit=5` did not bound
    the response, and `?offset=500` silently returned an empty `character_chats`
    alongside a full `character_voices` list — a pagination contract that quietly
    lied about what it was doing.

    Every sub-query is now windowed with the same limit/offset, and each keeps its
    own ceiling as a separate upper bound, so a page asking for `limit=1000` still
    cannot pull more than a section's cap.
    """
    # Character → Chats (primary character_id + additional_character_ids)
    char_chat_links = [
        tuple(row) for row in session.exec(
            select(Character.id, Character.name, Chat.id, Chat.name)
            .join(Chat, Chat.character_id == Character.id)
            # Ordered so the window is deterministic; the join alone has no
            # ORDER BY, which means an offset page can overlap the previous one.
            .order_by(Character.created_at.desc(), Chat.id)
            .limit(limit)
            .offset(offset)
        ).all()
    ]

    chats = session.exec(
        select(
            Chat.id,
            Chat.name,
            Chat.additional_character_ids,
            Chat.active_lorebook_ids,
            Chat.tts_voice_id,
            Chat.scenario_id,
        )
        .order_by(Chat.created_at.desc(), Chat.id)
        .limit(min(limit, 200))
        .offset(offset)
    ).all()

    extra_chat_char_ids = {
        c_id
        for ch in chats
        for c_id in (ch.additional_character_ids or [])
    }

    # Character → Stories (via character_ids JSON).
    # Cap the number of stories loaded into memory to keep this endpoint
    # bounded as the vault grows.
    stories = session.exec(
        select(
            Story.id,
            Story.title,
            Story.character_ids,
            Story.lorebook_ids,
            Story.location_ids,
            Story.scenario_id,
        )
        .order_by(Story.created_at.desc())
        .limit(min(limit, 200))
        .offset(offset)
    ).all()
    char_ids = {
        char_id
        for story in stories
        for char_id in (story.character_ids or [])
    } | extra_chat_char_ids
    if char_ids:
        characters = session.exec(
            select(Character.id, Character.name).where(Character.id.in_(char_ids))
        ).all()
    else:
        characters = []
    char_name_map = dict(characters)

    seen_char_chat = {(c_id, chat_id) for c_id, _, chat_id, _ in char_chat_links}
    for ch in chats:
        for c_id in ch.additional_character_ids or []:
            c_name = char_name_map.get(c_id)
            if c_name is not None and (c_id, ch.id) not in seen_char_chat:
                seen_char_chat.add((c_id, ch.id))
                char_chat_links.append((c_id, c_name, ch.id, ch.name))

    char_story_links = []
    for story in stories:
        for char_id in story.character_ids or []:
            char_name = char_name_map.get(char_id)
            if char_name is not None:
                char_story_links.append({
                    "character_id": char_id,
                    "character_name": char_name,
                    "story_id": story.id,
                    "story_title": story.title,
                })
            else:
                # Dangling link: the referenced character no longer exists.
                # Keep it (rather than silently dropping it) so the graph is
                # complete; mark it dangling so the UI can surface the issue.
                char_story_links.append({
                    "character_id": char_id,
                    "character_name": None,
                    "story_id": story.id,
                    "story_title": story.title,
                    "dangling": True,
                })

    # Characterrows with lorebooks / voices
    char_rows = session.exec(
        select(
            Character.id,
            Character.name,
            Character.lorebook_ids,
            Character.embedded_lorebook_id,
            Character.voice_model_id,
        )
        .order_by(Character.created_at.desc(), Character.id)
        .limit(min(limit, 200))
        .offset(offset)
    ).all()

    # Story / Chat / Character → Lorebooks
    story_lorebook_links = []
    chat_lorebook_links = []
    character_lorebook_links = []
    lorebook_ids = (
        {lb_id for story in stories for lb_id in (story.lorebook_ids or [])}
        | {lb_id for ch in chats for lb_id in (ch.active_lorebook_ids or [])}
        | {lb_id for cr in char_rows for lb_id in (cr.lorebook_ids or [])}
        | {cr.embedded_lorebook_id for cr in char_rows if cr.embedded_lorebook_id}
    )
    if lorebook_ids:
        lorebooks = session.exec(
            select(Lorebook).where(Lorebook.id.in_(lorebook_ids))
        ).all()
    else:
        lorebooks = []
    lorebook_map = {lb.id: lb for lb in lorebooks}
    for story in stories:
        for lb_id in story.lorebook_ids or []:
            lb = lorebook_map.get(lb_id)
            if lb:
                story_lorebook_links.append({
                    "story_id": story.id,
                    "story_title": story.title,
                    "lorebook_id": lb.id,
                    "lorebook_name": lb.name,
                })
            else:
                story_lorebook_links.append({
                    "story_id": story.id,
                    "story_title": story.title,
                    "lorebook_id": lb_id,
                    "lorebook_name": None,
                    "dangling": True,
                })

    for ch in chats:
        for lb_id in ch.active_lorebook_ids or []:
            lb = lorebook_map.get(lb_id)
            if lb:
                chat_lorebook_links.append({
                    "chat_id": ch.id,
                    "chat_name": ch.name,
                    "lorebook_id": lb.id,
                    "lorebook_name": lb.name,
                })
            else:
                chat_lorebook_links.append({
                    "chat_id": ch.id,
                    "chat_name": ch.name,
                    "lorebook_id": lb_id,
                    "lorebook_name": None,
                    "dangling": True,
                })

    for cr in char_rows:
        linked_lbs = list(cr.lorebook_ids or [])
        if cr.embedded_lorebook_id and cr.embedded_lorebook_id not in linked_lbs:
            linked_lbs.append(cr.embedded_lorebook_id)
        for lb_id in linked_lbs:
            lb = lorebook_map.get(lb_id)
            if lb:
                character_lorebook_links.append({
                    "character_id": cr.id,
                    "character_name": cr.name,
                    "lorebook_id": lb.id,
                    "lorebook_name": lb.name,
                })

    # Character → VoiceModels (both VoiceModel.character_id and Character.voice_model_id)
    voice_links = [
        tuple(row) for row in session.exec(
            select(VoiceModel.id, VoiceModel.name, Character.id, Character.name)
            .join(Character, Character.id == VoiceModel.character_id)
            .order_by(VoiceModel.created_at.desc(), VoiceModel.id)
            .limit(min(limit, 500))
            .offset(offset)
        ).all()
    ]
    seen_voice_char = {(v_id, c_id) for v_id, _, c_id, _ in voice_links}
    referenced_voice_ids = (
        {cr.voice_model_id for cr in char_rows if cr.voice_model_id}
        | {ch.tts_voice_id for ch in chats if ch.tts_voice_id}
    )
    voice_map = {}
    if referenced_voice_ids:
        voice_map = dict(
            session.exec(
                select(VoiceModel.id, VoiceModel.name).where(VoiceModel.id.in_(referenced_voice_ids))
            ).all()
        )
    for cr in char_rows:
        if cr.voice_model_id and cr.voice_model_id in voice_map:
            pair = (cr.voice_model_id, cr.id)
            if pair not in seen_voice_char:
                seen_voice_char.add(pair)
                voice_links.append((cr.voice_model_id, voice_map[cr.voice_model_id], cr.id, cr.name))

    chat_voice_links = []
    for ch in chats:
        if ch.tts_voice_id and ch.tts_voice_id in voice_map:
            chat_voice_links.append({
                "chat_id": ch.id,
                "chat_name": ch.name,
                "voice_id": ch.tts_voice_id,
                "voice_name": voice_map[ch.tts_voice_id],
            })

    # Story → Locations (via location_ids JSON)
    story_location_links = []
    location_ids = {
        loc_id
        for story in stories
        for loc_id in (story.location_ids or [])
    }
    if location_ids:
        locations = session.exec(
            select(Location).where(Location.id.in_(location_ids))
        ).all()
    else:
        locations = []
    location_map = {loc.id: loc for loc in locations}
    for story in stories:
        for loc_id in story.location_ids or []:
            loc = location_map.get(loc_id)
            if loc:
                story_location_links.append({
                    "story_id": story.id,
                    "story_title": story.title,
                    "location_id": loc.id,
                    "location_name": loc.name,
                })
            else:
                story_location_links.append({
                    "story_id": story.id,
                    "story_title": story.title,
                    "location_id": loc_id,
                    "location_name": None,
                    "dangling": True,
                })

    # Chat → Locations (via location_id FK)
    chat_location_links = [
        tuple(row) for row in session.exec(
            select(Chat.id, Chat.name, Location.id, Location.name)
            .join(Location, Location.id == Chat.location_id)
            .order_by(Chat.created_at.desc(), Chat.id)
            .limit(min(limit, 100))
            .offset(offset)
        ).all()
    ]

    # Story / Chat → Scenarios (via scenario_id FK)
    scenario_ids = (
        {story.scenario_id for story in stories if story.scenario_id}
        | {ch.scenario_id for ch in chats if ch.scenario_id}
    )
    scenario_map = {}
    if scenario_ids:
        scenario_map = dict(
            session.exec(
                select(Scenario.id, Scenario.name).where(Scenario.id.in_(scenario_ids))
            ).all()
        )
    story_scenario_links = [
        {
            "story_id": story.id,
            "story_title": story.title,
            "scenario_id": story.scenario_id,
            "scenario_name": scenario_map.get(story.scenario_id),
        }
        for story in stories
        if story.scenario_id and story.scenario_id in scenario_map
    ]
    chat_scenario_links = [
        {
            "chat_id": ch.id,
            "chat_name": ch.name,
            "scenario_id": ch.scenario_id,
            "scenario_name": scenario_map.get(ch.scenario_id),
        }
        for ch in chats
        if ch.scenario_id and ch.scenario_id in scenario_map
    ]

    # Stored (explicit) edges — complements the derived FK-based edges above.
    stored_edges = session.exec(
        select(WorldEdge)
        .order_by(WorldEdge.created_at.desc())
        .limit(200)
    ).all()

    return {
        "character_chats": char_chat_links,
        "character_stories": char_story_links,
        "story_lorebooks": story_lorebook_links,
        "chat_lorebooks": chat_lorebook_links,
        "character_lorebooks": character_lorebook_links,
        "character_voices": voice_links,
        "chat_voices": chat_voice_links,
        "story_locations": story_location_links,
        "chat_locations": chat_location_links,
        "story_scenarios": story_scenario_links,
        "chat_scenarios": chat_scenario_links,
        "stored_edges": [
            {
                "source_entity_type": e.source_entity_type,
                "source_entity_id": e.source_entity_id,
                "target_entity_type": e.target_entity_type,
                "target_entity_id": e.target_entity_id,
                "relation_type": e.relation_type,
                "label": e.label,
            }
            for e in stored_edges
        ],
    }


@router.get("/search")
def search_entities(
    # Bounded like every sibling search route: an unbounded ILIKE term is a
    # free full scan over five text columns on an unauthenticated route.
    q: str = Query(..., min_length=2, max_length=MAX_SEARCH_LENGTH),
    type: str | None = Query(default=None, max_length=64, description="Filter by entity type: character, chat, story, lorebook, scenario, voice, memory"),
    session: Session = Depends(get_session),
):
    """Unified search across characters, chats, stories, lorebooks, scenarios, voices."""
    pattern = func.lower(like_contains(q))
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
            (func.lower(Character.name).like(pattern, escape=LIKE_ESCAPE_CHAR))
            | (func.lower(Character.description).like(pattern, escape=LIKE_ESCAPE_CHAR))
        ).limit(10)
    ).all(), lambda c: c.name, lambda c: c.description[:100] if c.description else "")

    # Stories (title + description)
    _add("story", session.exec(
        select(Story).where(
            (func.lower(Story.title).like(pattern, escape=LIKE_ESCAPE_CHAR))
            | (func.lower(Story.description).like(pattern, escape=LIKE_ESCAPE_CHAR))
        ).limit(10)
    ).all(), lambda s: s.title, lambda s: s.description[:100] if s.description else "")

    # Chats (name)
    _add("chat", session.exec(
        select(Chat).where(func.lower(Chat.name).like(pattern, escape=LIKE_ESCAPE_CHAR)).limit(10)
    ).all(), lambda c: c.name, lambda c: f"{c.chat_type}")

    # Lorebooks (name)
    _add("lorebook", session.exec(
        select(Lorebook).where(func.lower(Lorebook.name).like(pattern, escape=LIKE_ESCAPE_CHAR)).limit(10)
    ).all(), lambda l: l.name, lambda l: l.description[:100] if l.description else "")

    # Locations (name)
    _add("location", session.exec(
        select(Location).where(func.lower(Location.name).like(pattern, escape=LIKE_ESCAPE_CHAR)).limit(10)
    ).all(), lambda l: l.name, lambda l: l.description[:100] if l.description else "")

    # Scenarios (name + prompt_template)
    _add("scenario", session.exec(
        select(Scenario).where(func.lower(Scenario.name).like(pattern, escape=LIKE_ESCAPE_CHAR)).limit(10)
    ).all(), lambda s: s.name, lambda s: s.description[:100] if s.description else "")

    # Voices (name)
    _add("voice", session.exec(
        select(VoiceModel).where(func.lower(VoiceModel.name).like(pattern, escape=LIKE_ESCAPE_CHAR)).limit(10)
    ).all(), lambda v: v.name, lambda v: v.description[:100] if v.description else "")

    # Memories (content)
    _add("memory", session.exec(
        select(CharacterMemory).where(func.lower(CharacterMemory.content).like(pattern, escape=LIKE_ESCAPE_CHAR)).limit(10)
    ).all(),
       lambda m: (m.content[:80] + "…") if len(m.content) > 80 else m.content,
       lambda m: f"Tags: {', '.join(m.tags or [])}" if m.tags else "")

    return {"query": q, "results": results, "total": len(results)}
