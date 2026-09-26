"""Tests for GET /api/v2/world-vault/relationships pagination.

Two defects:
  * `voice_links` and `chat_location_links` took `.limit().offset()` over an
    UNORDERED join. Postgres gives no row order without ORDER BY, so
    `?offset=100` could repeat or skip rows. `char_chat_links` had already been
    given an explicit order; these two had not.
  * A prior audit found limit/offset applied to only one of the sub-queries, so
    `?limit=5` did not bound the response. Every direct windowed query is now
    asserted to honour it.

The JSON-derived sections (`character_stories`, `story_lorebooks`,
`story_locations`) are derived from the already-windowed `stories` query, so
they are bounded by construction; that is asserted too.
"""

from sqlmodel import Session

from core.entities import Character, Chat, Location, Story, VoiceModel

WINDOWED_SECTIONS = (
    "character_chats",
    "character_voices",
    "chat_locations",
)


def _seed_voices(session: Session, count: int) -> Character:
    char = Character(name="VoiceOwner")
    session.add(char)
    session.commit()
    session.refresh(char)
    for index in range(count):
        session.add(VoiceModel(name=f"voice-{index:02d}", character_id=char.id))
    session.commit()
    return char


def _seed_chats_with_locations(session: Session, count: int) -> list[str]:
    loc = Location(name="Mistvale", description="a town")
    session.add(loc)
    session.commit()
    session.refresh(loc)
    ids = []
    for index in range(count):
        chat = Chat(name=f"chat-{index:02d}", location_id=loc.id)
        session.add(chat)
        session.commit()
        session.refresh(chat)
        ids.append(chat.id)
    return ids


def _seed_chats_for_character(session: Session, char: Character, count: int) -> list[str]:
    ids = []
    for index in range(count):
        chat = Chat(name=f"cchat-{index:02d}", character_id=char.id)
        session.add(chat)
        session.commit()
        session.refresh(chat)
        ids.append(chat.id)
    return ids


def test_limit_is_honoured_by_every_windowed_section(client, session):
    _seed_voices(session, 12)
    _seed_chats_with_locations(session, 12)
    char = Character(name="ChatOwner")
    session.add(char)
    session.commit()
    session.refresh(char)
    _seed_chats_for_character(session, char, 12)

    resp = client.get("/api/v2/world-vault/relationships?limit=3&offset=0")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    for section in WINDOWED_SECTIONS:
        assert len(body[section]) <= 3, f"{section} returned {len(body[section])} rows for limit=3"


def test_derived_sections_are_bounded_by_the_windowed_story_query(client, session):
    """character_stories / story_lorebooks / story_locations are derived from the
    `stories` page, so `limit` bounds them without their own window."""
    for index in range(6):
        char = Character(name=f"S{index}")
        session.add(char)
        session.commit()
        session.refresh(char)
        session.add(Story(
            title=f"Story {index}",
            character_ids=[char.id],
            lorebook_ids=[],
            location_ids=[],
        ))
        session.commit()

    resp = client.get("/api/v2/world-vault/relationships?limit=2&offset=0")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["character_stories"]) <= 2
    assert len(body["story_lorebooks"]) <= 2
    assert len(body["story_locations"]) <= 2


def test_voice_pages_do_not_overlap_or_skip(client, session):
    """The unordered-window defect: page 2 could repeat page 1's rows."""
    _seed_voices(session, 10)

    page1 = client.get("/api/v2/world-vault/relationships?limit=4&offset=0").json()
    page2 = client.get("/api/v2/world-vault/relationships?limit=4&offset=4").json()
    page3 = client.get("/api/v2/world-vault/relationships?limit=4&offset=8").json()

    ids1 = [row[0] for row in page1["character_voices"]]
    ids2 = [row[0] for row in page2["character_voices"]]
    ids3 = [row[0] for row in page3["character_voices"]]

    assert len(ids1) == len(ids2) == 4
    assert len(ids3) == 2
    assert not set(ids1) & set(ids2)
    assert not set(ids2) & set(ids3)
    assert len(set(ids1) | set(ids2) | set(ids3)) == 10


def test_chat_location_pages_do_not_overlap_or_skip(client, session):
    _seed_chats_with_locations(session, 10)

    page1 = client.get("/api/v2/world-vault/relationships?limit=4&offset=0").json()
    page2 = client.get("/api/v2/world-vault/relationships?limit=4&offset=4").json()
    page3 = client.get("/api/v2/world-vault/relationships?limit=4&offset=8").json()

    ids1 = [row[0] for row in page1["chat_locations"]]
    ids2 = [row[0] for row in page2["chat_locations"]]
    ids3 = [row[0] for row in page3["chat_locations"]]

    assert len(ids1) == len(ids2) == 4
    assert len(ids3) == 2
    assert not set(ids1) & set(ids2)
    assert not set(ids2) & set(ids3)
    assert len(set(ids1) | set(ids2) | set(ids3)) == 10


def test_repeat_requests_return_the_same_page(client, session):
    """An unordered window is not even stable within one process."""
    _seed_voices(session, 8)
    _seed_chats_with_locations(session, 8)

    first = client.get("/api/v2/world-vault/relationships?limit=3&offset=3").json()
    second = client.get("/api/v2/world-vault/relationships?limit=3&offset=3").json()

    for section in WINDOWED_SECTIONS:
        assert first[section] == second[section], f"{section} is not deterministic"


def test_relationships_declares_an_order_on_every_offset_query():
    """Source-level guard: no `.offset(` may appear without a preceding ORDER BY."""
    import inspect
    import re

    from api.routes.world_vault import world_hub

    source = inspect.getsource(world_hub.get_relationships)
    # Walk the statement chains and check each one that offsets also orders.
    chains = re.findall(
        r"select\(.*?\)(?:(?!session\.exec|\n\s{4}\w).)*?\.offset\(offset\)",
        source,
        re.S,
    )
    assert chains, "no offset query found — the guard needs updating"
    for chain in chains:
        assert ".order_by(" in chain, f"unordered window:\n{chain}"


def test_per_section_caps_still_apply_above_the_requested_limit(client, session):
    """Each section keeps its own ceiling as an upper bound."""
    _seed_chats_with_locations(session, 130)

    resp = client.get("/api/v2/world-vault/relationships?limit=1000&offset=0")

    assert resp.status_code == 200, resp.text
    assert len(resp.json()["chat_locations"]) <= 100
