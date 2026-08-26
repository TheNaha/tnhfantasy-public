# Personas library + author's note tests
import pytest

from core.entities import Chat, Persona
from services.context_builder import build_chat_context, chat_context_kwargs


@pytest.fixture
def persona(client):
    resp = client.post("/api/v2/personas", json={"name": "Aria", "description": "A wandering mage"})
    assert resp.status_code == 200
    return resp.json()


class TestPersonasCrud:
    def test_list_empty(self, client):
        assert client.get("/api/v2/personas").json() == []

    def test_create_and_get(self, client, persona):
        got = client.get(f"/api/v2/personas/{persona['id']}")
        assert got.status_code == 200
        assert got.json()["name"] == "Aria"
        assert got.json()["description"] == "A wandering mage"

    def test_create_blank_name_rejected(self, client):
        assert client.post("/api/v2/personas", json={"name": "   "}).status_code in (400, 422)

    def test_update(self, client, persona):
        resp = client.put(
            f"/api/v2/personas/{persona['id']}",
            json={"name": "Aria the Elder", "description": None},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Aria the Elder"
        assert body["description"] is None

    def test_delete(self, client, persona):
        assert client.delete(f"/api/v2/personas/{persona['id']}").status_code == 200
        assert client.get(f"/api/v2/personas/{persona['id']}").status_code == 404

    def test_get_unknown_404(self, client):
        assert client.get("/api/v2/personas/nope").status_code == 404


class TestChatPersonaLink:
    def test_create_chat_with_persona_id_validates(self, client, persona):
        resp = client.post("/api/v2/chats", json={"name": "c", "persona_id": persona["id"]})
        assert resp.status_code == 200
        assert resp.json()["persona_id"] == persona["id"]

    def test_create_chat_unknown_persona_404(self, client):
        assert client.post("/api/v2/chats", json={"name": "c", "persona_id": "ghost"}).status_code == 404

    def test_patch_sets_and_clears_link(self, client, persona):
        chat = client.post("/api/v2/chats", json={"name": "c"}).json()
        resp = client.patch(f"/api/v2/chats/{chat['id']}", json={"persona_id": persona["id"]})
        assert resp.status_code == 200 and resp.json()["persona_id"] == persona["id"]
        resp = client.patch(f"/api/v2/chats/{chat['id']}", json={"persona_id": None})
        assert resp.status_code == 200 and resp.json()["persona_id"] is None

    def test_delete_persona_scrubs_chat_links(self, client, session, persona):
        chat_resp = client.post("/api/v2/chats", json={"name": "linked", "persona_id": persona["id"]})
        assert chat_resp.status_code == 200
        assert client.delete(f"/api/v2/personas/{persona['id']}").status_code == 200
        session.expire_all()
        row = session.get(Chat, chat_resp.json()["id"])
        assert row.persona_id is None


class TestAuthorsNoteEndpoints:
    def test_patch_note_and_depth_roundtrip(self, client):
        chat = client.post("/api/v2/chats", json={"name": "c"}).json()
        resp = client.patch(
            f"/api/v2/chats/{chat['id']}",
            json={"authors_note": "Keep tension high", "authors_note_depth": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["authors_note"] == "Keep tension high"
        assert body["authors_note_depth"] == 2
        # Clearing works too
        cleared = client.patch(f"/api/v2/chats/{chat['id']}", json={"authors_note": None}).json()
        assert cleared["authors_note"] is None

    def test_patch_depth_bounds(self, client):
        chat = client.post("/api/v2/chats", json={"name": "c"}).json()
        bad = client.patch(f"/api/v2/chats/{chat['id']}", json={"authors_note_depth": 999})
        assert bad.status_code == 400


class TestAuthorsNoteInjection:
    def _msgs(self, n):
        role_cycle = ["user", "assistant"]
        return [{"role": role_cycle[i % 2], "content": f"m{i}"} for i in range(n)]

    def test_note_absent_without_authors_note(self):
        _, ctx = build_chat_context(None, self._msgs(6))
        assert not any("[Author's Note]" in m["content"] for m in ctx)

    def test_default_depth_four(self):
        _, ctx = build_chat_context(None, self._msgs(8), authors_note="stay terse")
        note_idx = next(i for i, m in enumerate(ctx) if "[Author's Note]" in m["content"])
        # system prompt (1) + note inserted 4 from tail → len-5 index
        assert note_idx == len(ctx) - 1 - 4
        assert "stay terse" in ctx[note_idx]["content"]

    def test_zero_depth_pins_to_end(self):
        msgs = self._msgs(5)
        _, ctx = build_chat_context(None, msgs, authors_note="final word", authors_note_depth=0)
        assert ctx[-1]["role"] == "system"
        assert "[Author's Note]" in ctx[-1]["content"]

    def test_depth_larger_than_history_clamps_to_front(self):
        _, ctx = build_chat_context(None, self._msgs(3), authors_note="early", authors_note_depth=50)
        assert "[Author's Note]" in ctx[1]["content"]

    def test_survives_tight_prune_budget(self):
        # Even a tiny token budget must keep the note (injected post-prune).
        _, ctx = build_chat_context(
            None, self._msgs(30), authors_note="must survive", max_context_tokens=60,
        )
        assert any("must survive" in m["content"] for m in ctx)


class TestPersonaResolutionInKwargs:
    def test_library_persona_fills_unset_fields(self, session):
        persona = Persona(name="Kai", description="cyber-rat")
        session.add(persona)
        session.commit()
        session.refresh(persona)
        chat = Chat(name="t", persona_id=persona.id)
        session.add(chat)
        session.commit()
        session.refresh(chat)

        kw = chat_context_kwargs(chat, session=session)
        assert kw["persona_name"] == "Kai"
        assert kw["persona_description"] == "cyber-rat"

    def test_per_chat_strings_win_individually(self, session):
        persona = Persona(name="Kai", description="cyber-rat")
        session.add(persona)
        session.commit()
        session.refresh(persona)
        chat = Chat(name="t", persona_id=persona.id, persona_name="Override")
        session.add(chat)
        session.commit()
        session.refresh(chat)

        kw = chat_context_kwargs(chat, session=session)
        assert kw["persona_name"] == "Override"
        assert kw["persona_description"] == "cyber-rat"

    def test_no_session_skips_resolution(self, session):
        persona = Persona(name="Kai", description=None)
        session.add(persona)
        session.commit()
        session.refresh(persona)
        chat = Chat(name="t", persona_id=persona.id)
        session.add(chat)
        session.commit()
        session.refresh(chat)

        kw = chat_context_kwargs(chat)
        assert kw["persona_name"] is None

    def test_kwargs_map_authors_note(self):
        chat = Chat(name="t", authors_note="hi", authors_note_depth=7)
        kw = chat_context_kwargs(chat)
        assert kw["authors_note"] == "hi"
        assert kw["authors_note_depth"] == 7
