# Focused tests for chat ↔ lorebook activation (roleplay compatibility).
#
# Covers:
#   - create_chat / import_chat linking Character.embedded_lorebook_id into
#     the new chat's active_lorebook_ids
#   - chat_context_kwargs no longer letting a None lorebook_ids override
#     shadow chat.active_lorebook_ids
#   - constant (keyless) lorebook entries still reaching the system prompt when
#     semantic search returns nothing (RAG off, or no keyword match)

from types import SimpleNamespace

import pytest

from core.entities import Character, Chat, Lorebook, LorebookEntry, Message, MessageRole
from services import rag_pipeline
from services.context_builder import build_system_prompt_sections, chat_context_kwargs


# ── chat_context_kwargs: chat lorebooks must survive a None override ─────────


def test_chat_context_kwargs_none_override_keeps_chat_lorebooks(session):
    """A caller that passes lorebook_ids=None means "no opinion", not "none".

    The send-message route forwards its optional lorebook_ids field, which is
    None whenever the client omits it — the chat's own active lorebooks must
    still reach the prompt.
    """
    chat = Chat(active_lorebook_ids=["lb-1", "lb-2"])
    session.add(chat)
    session.commit()

    kwargs = chat_context_kwargs(chat, lorebook_ids=None)
    assert kwargs["lorebook_ids"] == ["lb-1", "lb-2"]


def test_chat_context_kwargs_explicit_empty_list_overrides(session):
    """An explicit [] is a deliberate clear and is still honoured."""
    chat = Chat(active_lorebook_ids=["lb-1"])
    session.add(chat)
    session.commit()

    assert chat_context_kwargs(chat, lorebook_ids=[])["lorebook_ids"] == []


def test_chat_context_kwargs_explicit_list_wins(session):
    chat = Chat(active_lorebook_ids=["lb-1"])
    session.add(chat)
    session.commit()

    assert chat_context_kwargs(chat, lorebook_ids=["lb-2"])["lorebook_ids"] == ["lb-2"]


# ── constant lorebook entries reach the prompt ───────────────────────────────


def _seed_lorebook(session, name="Card Lore") -> tuple[Lorebook, LorebookEntry]:
    lb = Lorebook(name=name)
    session.add(lb)
    session.commit()
    session.refresh(lb)
    entry = LorebookEntry(lorebook_id=lb.id, keys=[], content="The Docks run on tide-clock time.")
    session.add(entry)
    session.commit()
    return lb, entry


def test_sections_inject_constant_entries_when_search_returns_nothing(session, monkeypatch):
    lb, _ = _seed_lorebook(session)
    monkeypatch.setattr(rag_pipeline, "search_lorebook_entries", lambda *a, **k: [])

    sections = build_system_prompt_sections(session, lorebook_ids=[lb.id], persona_name="Kai")
    by_key = {s["key"]: s for s in sections}
    assert "lorebook" in by_key
    assert "tide-clock" in by_key["lorebook"]["content"]


def test_sections_skip_keyed_entries_when_search_returns_nothing(session, monkeypatch):
    """Keyword entries still need a match; only constant entries are forced in."""
    lb = Lorebook(name="Keyed Lore")
    session.add(lb)
    session.commit()
    session.refresh(lb)
    session.add(LorebookEntry(lorebook_id=lb.id, keys=["dragonslayer"], content="Only on dragonfire."))
    session.commit()
    monkeypatch.setattr(rag_pipeline, "search_lorebook_entries", lambda *a, **k: [])

    sections = build_system_prompt_sections(session, lorebook_ids=[lb.id], persona_name="Kai")
    assert "lorebook" not in {s["key"] for s in sections}


def test_chat_lorebook_context_reaches_sections_through_kwargs(session, monkeypatch):
    """End-to-end wiring: chat.active_lorebook_ids -> kwargs -> prompt sections."""
    lb, _ = _seed_lorebook(session, name="Embedded Book")
    char = Character(name="Aria")
    session.add(char)
    chat = Chat(character_id=char.id, persona_name="Vex", active_lorebook_ids=[lb.id])
    session.add(chat)
    session.commit()
    monkeypatch.setattr(rag_pipeline, "search_lorebook_entries", lambda *a, **k: [])

    kwargs = chat_context_kwargs(chat, session=session)
    sections = build_system_prompt_sections(session, **kwargs)
    assert "tide-clock" in "\n\n".join(s["content"] for s in sections)


# ── persona / original macro expansion inside prompt sections ───────────────


def test_sections_expand_persona_and_original(session):
    char = Character(name="Aria", description="A cartographer who maps coastlines.")
    session.add(char)
    session.commit()

    sections = build_system_prompt_sections(
        session,
        character=char,
        persona_name="Vex",
        persona_description="A dockside runner",
        system_prompt_override="Stay cold. {{persona}} fears {{char}}.",
    )
    by_key = {s["key"]: s for s in sections}
    assert by_key["chat_prompt"]["content"] == "Stay cold. A dockside runner fears Aria."

    # {{original}} expands to the character prompt the override replaces.
    override_with_original = build_system_prompt_sections(
        session,
        character=char,
        system_prompt_override="Original was: {{original}}",
    )
    by_key2 = {s["key"]: s for s in override_with_original}
    assert "A cartographer who maps coastlines." in by_key2["chat_prompt"]["content"]


# ── create_chat / import_chat auto-link the character's embedded lorebook ────


class _StubCharacterRepo:
    def __init__(self, character):
        self._character = character

    def get(self, _character_id):
        return self._character


def _stub_character_repo(client, character):
    from api.deps import get_character_repo

    client.app.dependency_overrides[get_character_repo] = lambda: _StubCharacterRepo(character)
    return character


def test_create_chat_links_embedded_lorebook(client, session):
    char = SimpleNamespace(
        id="char-1",
        name="Aria",
        first_mes=None,
        description="Maps coastlines.",
        embedded_lorebook_id="lb-embedded",
    )
    _stub_character_repo(client, char)

    resp = client.post(
        "/api/v2/chats",
        json={"character_id": "char-1", "active_lorebook_ids": ["lb-manual"]},
    )
    assert resp.status_code == 200
    assert resp.json()["active_lorebook_ids"] == ["lb-manual", "lb-embedded"]


def test_create_chat_links_embedded_lorebook_without_requested_list(client, session):
    char = SimpleNamespace(
        id="char-1",
        name="Aria",
        first_mes=None,
        description="",
        embedded_lorebook_id="lb-embedded",
    )
    _stub_character_repo(client, char)

    resp = client.post("/api/v2/chats", json={"character_id": "char-1"})
    assert resp.status_code == 200
    assert resp.json()["active_lorebook_ids"] == ["lb-embedded"]


def test_create_chat_without_embedded_lorebook_column(client, session):
    """Cards imported before the column existed keep exactly what was asked."""
    char = SimpleNamespace(id="char-1", name="Aria", first_mes=None, description="")
    _stub_character_repo(client, char)

    resp = client.post("/api/v2/chats", json={"character_id": "char-1"})
    assert resp.status_code == 200
    assert resp.json()["active_lorebook_ids"] == []


def test_create_chat_expands_greeting_macros(client, session):
    char = SimpleNamespace(
        id="char-1",
        name="Aria",
        first_mes="Hi {{user}}, {{char}} left. {{pick::soon::later}}?",
        description="Maps coastlines.",
        embedded_lorebook_id="lb-embedded",
    )
    _stub_character_repo(client, char)

    resp = client.post("/api/v2/chats", json={"character_id": "char-1", "persona_name": "Vex"})
    assert resp.status_code == 200
    chat_id = resp.json()["id"]
    msgs = client.get(f"/api/v2/chats/{chat_id}/messages").json()
    assert len(msgs) == 1
    content = msgs[0]["content"]
    assert "Hi Vex, Aria left." in content
    assert content.endswith("soon?") or content.endswith("later?")


def test_import_chat_links_embedded_lorebook(client, session):
    char = SimpleNamespace(
        id="char-1",
        name="Aria",
        first_mes=None,
        description="",
        embedded_lorebook_id="lb-embedded",
    )
    _stub_character_repo(client, char)

    jsonl = "\n".join([
        '{"user_name": "Vex", "character_name": "Aria", "chat_metadata": {}}',
        '{"name": "Vex", "is_user": true, "mes": "Harbour?"}',
        '{"name": "Aria", "is_user": false, "mes": "Always."}',
    ])
    resp = client.post(
        "/api/v2/chats/import",
        data={"character_id": "char-1"},
        files={"file": ("chat.jsonl", jsonl.encode("utf-8"), "application/json")},
    )
    assert resp.status_code == 200
    assert resp.json()["active_lorebook_ids"] == ["lb-embedded"]


def test_import_chat_no_duplicate_when_already_active(client, session):
    char = SimpleNamespace(
        id="char-1",
        name="Aria",
        first_mes=None,
        description="",
        embedded_lorebook_id="lb-embedded",
    )
    _stub_character_repo(client, char)

    payload = {
        "chat": {
            "name": "Exported",
            "character_id": "char-1",
            "active_lorebook_ids": ["lb-embedded", "lb-manual"],
        },
        "messages": [{"role": "user", "content": "Harbour?"}],
    }
    import json as _json

    resp = client.post(
        "/api/v2/chats/import",
        files={"file": ("chat.json", _json.dumps(payload).encode("utf-8"), "application/json")},
    )
    assert resp.status_code == 200
    assert resp.json()["active_lorebook_ids"] == ["lb-embedded", "lb-manual"]


@pytest.mark.parametrize("lorebook_ids", [None, []])
def test_linked_lorebook_survives_empty_request(lorebook_ids):
    from services.chat_utils import link_embedded_lorebook

    char = SimpleNamespace(embedded_lorebook_id="lb-embedded")
    assert link_embedded_lorebook(lorebook_ids, char) == ["lb-embedded"]


# ── same flow against real Character / Lorebook rows ────────────────────────
# Character.embedded_lorebook_id is set by the card-import path, so the chat
# link below exercises the actual persisted link rather than a stub.


def _seed_character_with_book(session, content="Brine tolls are paid at low tide.") -> tuple[Character, Lorebook]:
    lb, entry = _seed_lorebook(session, name="Aria's Book")
    entry.content = content
    char = Character(name="Aria", embedded_lorebook_id=lb.id)
    session.add(char)
    session.commit()
    session.refresh(char)
    return char, lb


def test_create_chat_links_persisted_embedded_lorebook(client, session, monkeypatch):
    char, lb = _seed_character_with_book(session)

    resp = client.post(
        "/api/v2/chats",
        json={"character_id": char.id, "active_lorebook_ids": ["lb-manual"]},
    )
    assert resp.status_code == 200
    chat_id = resp.json()["id"]
    chat = session.get(Chat, chat_id)
    assert chat.active_lorebook_ids == ["lb-manual", lb.id]

    # And the linked book is actually part of the assembled prompt context.
    monkeypatch.setattr(rag_pipeline, "search_lorebook_entries", lambda *a, **k: [])
    kwargs = chat_context_kwargs(chat, session=session)
    sections = build_system_prompt_sections(session, **kwargs)
    assert "Brine tolls" in "\n\n".join(s["content"] for s in sections)


def test_create_chat_reuses_existing_embedded_lorebook_id(client, session):
    char, lb = _seed_character_with_book(session)

    resp = client.post("/api/v2/chats", json={"character_id": char.id, "active_lorebook_ids": [lb.id]})
    assert resp.status_code == 200
    assert resp.json()["active_lorebook_ids"] == [lb.id]


def test_export_import_round_trip_preserves_active_lorebooks(client, session):
    char, lb = _seed_character_with_book(session)
    created = client.post(
        "/api/v2/chats",
        json={"character_id": char.id, "active_lorebook_ids": ["lb-manual"]},
    ).json()

    export = client.get(f"/api/v2/chats/{created['id']}/export", params={"format": "json"})
    assert export.status_code == 200
    assert export.json()["chat"]["active_lorebook_ids"] == ["lb-manual", lb.id]

    # The import route requires at least one message in the payload.
    session.add(Message(chat_id=created["id"], role=MessageRole.USER, content="Harbour?"))
    session.commit()
    export = client.get(f"/api/v2/chats/{created['id']}/export", params={"format": "json"})

    reimported = client.post(
        "/api/v2/chats/import",
        files={"file": ("chat.json", export.content, "application/json")},
    )
    assert reimported.status_code == 200
    assert reimported.json()["active_lorebook_ids"] == ["lb-manual", lb.id]
