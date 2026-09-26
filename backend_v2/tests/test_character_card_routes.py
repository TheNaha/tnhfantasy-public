"""Route tests for character card operations: clone, import (PNG card),
export (PNG card), avatar upload/serve, and response shapes (has_avatar)."""

import io
import json
import os

import pytest
from PIL import Image, PngImagePlugin
from sqlmodel import select

import config as app_config
from core.entities import Character, CharacterMemory, Collection


@pytest.fixture(autouse=True)
def _temp_avatar_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(app_config.settings, "character_avatar_dir", str(tmp_path / "characters"))


def _card_png(card_data: dict) -> bytes:
    """Build a PNG with a `chara` tEXt chunk carrying card JSON (as exported)."""
    buf = io.BytesIO()
    img = Image.new("RGB", (4, 4), (128, 128, 128))
    meta = PngImagePlugin.PngInfo()
    meta.add_text("chara", card_data if isinstance(card_data, str) else json.dumps(card_data))
    img.save(buf, format="PNG", pnginfo=meta)
    return buf.getvalue()


def _seed_char(client, name="Origin"):
    resp = client.post("/api/v2/characters", json={"name": name, "description": "original"})
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestCloneCharacter:
    def test_clone_keeps_new_id_and_suffix(self, client, session):
        char = _seed_char(client, name="Aria")
        resp = client.post(f"/api/v2/characters/{char['id']}/clone")
        assert resp.status_code == 200, resp.text
        clone = resp.json()
        assert clone["id"] != char["id"]
        assert clone["name"] == "Aria (Copy)"
        assert clone["description"] == "original"

    def test_clone_missing_404(self, client):
        assert client.post("/api/v2/characters/nope/clone").status_code == 404

    def test_clone_creates_gallery_collection(self, client, session):
        char = _seed_char(client, name="Gallery O")
        clone = client.post(f"/api/v2/characters/{char['id']}/clone").json()
        collections = session.exec(__import__("sqlmodel").select(Collection).where(Collection.character_id == clone["id"])).all()
        assert len(collections) == 1
        assert collections[0].name == "Gallery O (Copy)'s Gallery"


class TestImportCharacterCard:
    def test_import_rejects_non_png(self, client):
        resp = client.post("/api/v2/characters/import", files={"file": ("card.txt", b"not a png", "text/plain")})
        assert resp.status_code == 400

    def test_import_rejects_invalid_png_bytes(self, client):
        resp = client.post("/api/v2/characters/import", files={"file": ("card.png", b"\x00\x01notreallypng", "image/png")})
        assert resp.status_code == 400

    def test_import_requires_name_in_card(self, client):
        png = _card_png({"description": "no name here"})
        resp = client.post("/api/v2/characters/import", files={"file": ("card.png", png, "image/png")})
        assert resp.status_code == 400

    def test_import_happy_path_v1_flat_card(self, client, session):
        png = _card_png({"name": "Cardified", "description": "from a card", "personality": "brave"})
        resp = client.post("/api/v2/characters/import", files={"file": ("card.png", png, "image/png")})
        assert resp.status_code == 200, resp.text
        char = resp.json()
        assert char["name"] == "Cardified"
        assert char["personality"] == "brave"
        assert char["has_avatar"] is True
        avatar_dir = app_config.settings.character_avatar_dir
        assert os.path.exists(os.path.join(avatar_dir, char['id'], "avatar.png"))

    def test_import_v2_data_wrapper(self, client, session):
        png = _card_png({"spec": "chara_card_v2", "data": {"name": "Wrapped", "first_mes": "Hi!"}})
        resp = client.post("/api/v2/characters/import", files={"file": ("card.png", png, "image/png")})
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Wrapped"


class TestExportCharacter:
    def test_export_without_avatar_falls_back_to_1x1_png(self, client, session):
        char = _seed_char(client, name="NoAvatar")
        resp = client.get(f"/api/v2/characters/{char['id']}/export")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"
        img = Image.open(io.BytesIO(resp.content))
        assert "chara" in img.info

    def test_export_round_trips_card_fields(self, client, session):
        char = _seed_char(client, name="Exportable")
        avatar = io.BytesIO()
        Image.new("RGB", (8, 8), (10, 20, 30)).save(avatar, format="PNG")
        up = client.post(f"/api/v2/characters/{char['id']}/avatar", files={"file": ("a.png", avatar.getvalue(), "image/png")})
        assert up.status_code == 200
        assert up.json()["has_avatar"] is True

        resp = client.get(f"/api/v2/characters/{char['id']}/export")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        png_bytes = resp.content
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

        # Re-import the exported card: fields must survive the round trip.
        reimport = client.post("/api/v2/characters/import", files={"file": ("roundtrip.png", png_bytes, "image/png")})
        assert reimport.status_code == 200, reimport.text
        body = reimport.json()
        assert body["name"] == "Exportable"
        assert body["description"] == "original"

    def test_export_missing_404(self, client):
        assert client.get("/api/v2/characters/nope/export").status_code == 404


class TestAvatar:
    def test_upload_avatar_sets_has_avatar(self, client, session):
        char = _seed_char(client, name="Pictured")
        avatar = io.BytesIO()
        Image.new("RGB", (16, 16), (255, 0, 0)).save(avatar, format="PNG")
        resp = client.post(f"/api/v2/characters/{char['id']}/avatar", files={"file": ("a.png", avatar.getvalue(), "image/png")})
        assert resp.status_code == 200
        assert resp.json()["has_avatar"] is True

        # List/get now report has_avatar.
        listing = client.get("/api/v2/characters").json()
        match = next(c for c in listing if c["id"] == char["id"])
        assert match["has_avatar"] is True

    def test_get_avatar_returns_png(self, client, session):
        char = _seed_char(client, name="Avatared")
        avatar = io.BytesIO()
        Image.new("RGB", (8, 8), (0, 255, 0)).save(avatar, format="PNG")
        client.post(f"/api/v2/characters/{char['id']}/avatar", files={"file": ("a.png", avatar.getvalue(), "image/png")})
        resp = client.get(f"/api/v2/characters/{char['id']}/avatar")
        assert resp.status_code == 200
        assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"

    def test_get_avatar_missing_404(self, client, session):
        char = _seed_char(client, name="NoPic")
        assert client.get(f"/api/v2/characters/{char['id']}/avatar").status_code == 404

    def test_upload_avatar_missing_character_404(self, client):
        resp = client.post("/api/v2/characters/nope/avatar", files={"file": ("a.png", b"x", "image/png")})
        assert resp.status_code == 404

class TestDeleteCharacterCascadesMemories:
    """Regression: deleting a Character must cascade-delete its
    CharacterMemory rows. Without `cascade="all, delete-orphan"` on the
    Character.memories relationship, SQLAlchemy issues an UPDATE that sets
    character_memories.character_id = NULL, violating the NOT NULL FK
    constraint (500 IntegrityError on Postgres; same on SQLite)."""

    def test_delete_removes_child_memories(self, client, session):
        char = _seed_char(client, name="Remembered")
        for i in range(3):
            session.add(CharacterMemory(character_id=char["id"], content=f"memory {i}"))
        session.commit()
        assert session.exec(select(CharacterMemory).where(CharacterMemory.character_id == char["id"])).all().__len__() == 3

        resp = client.delete(f"/api/v2/characters/{char['id']}")
        assert resp.status_code == 200, resp.text
        assert session.get(Character, char["id"]) is None
        remaining = session.exec(select(CharacterMemory).where(CharacterMemory.character_id == char["id"])).all()
        assert remaining == []


class TestCharacterExpressions:
    def test_get_expressions_empty_defaults(self, client):
        char = _seed_char(client, name="Plain")
        resp = client.get(f"/api/v2/characters/{char['id']}/expressions")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"expressions": {}, "expressions_lora": []}

    def test_get_expressions_round_trips_patch(self, client):
        char = _seed_char(client, name="Expressive")
        patch = {
            "expressions": {"happy": "happy expression", "sad": "sad expression"},
            "expressions_lora": ["lora-a.safetensors"],
        }
        resp = client.patch(f"/api/v2/characters/{char['id']}", json=patch)
        assert resp.status_code == 200, resp.text

        resp = client.get(f"/api/v2/characters/{char['id']}/expressions")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["expressions"] == patch["expressions"]
        assert body["expressions_lora"] == patch["expressions_lora"]

    def test_get_expressions_missing_404(self, client):
        assert client.get("/api/v2/characters/nope/expressions").status_code == 404

class TestDeleteCharacterPreservesChats:
    """Deleting a character must ORPHAN its chats, not destroy them.

    `Character.chats` used to carry `cascade="all, delete-orphan"`, so the
    ORM deleted the Chat rows right after scrub_entity_references() nulled
    chat.character_id — and, via `Chat.messages` cascading again, every message
    with them. The scrub was silently defeated and a character delete wiped full
    chat history. `Character.memories` must still cascade (see
    TestDeleteCharacterCascadesMemories).
    """

    def test_chats_and_messages_survive(self, client, session):
        from core.entities import Chat, Message

        char = _seed_char(client, name="Chatty")
        chat = Chat(character_id=char["id"], name="Session One")
        session.add(chat)
        session.commit()
        session.refresh(chat)
        session.add(Message(chat_id=chat.id, role="user", content="do not lose me"))
        session.commit()

        # Load the relationship before the delete, the way any request that
        # touches character.chats would. With `delete-orphan` the collection is
        # then live at flush time and the chats (and, via Chat.messages, every
        # message) are deleted with the parent.
        character = session.get(Character, char["id"])
        assert len(character.chats) == 1, "relationship did not load; test would be vacuous"

        resp = client.delete(f"/api/v2/characters/{char['id']}")
        assert resp.status_code == 200, resp.text

        assert session.get(Character, char["id"]) is None
        session.expire_all()
        surviving = session.get(Chat, chat.id)
        assert surviving is not None, "chat was cascade-deleted with the character"
        assert surviving.character_id is None
        assert session.exec(
            select(Message).where(Message.chat_id == chat.id)
        ).all() != []

    def test_linked_voice_model_is_detached_not_fatal(self, client, session):
        """voice_models.character_id is an FK with no ON DELETE clause."""
        from core.entities import VoiceModel

        char = _seed_char(client, name="Voiced")
        voice = VoiceModel(name="v1", character_id=char["id"])
        session.add(voice)
        session.commit()
        voice_id = voice.id

        resp = client.delete(f"/api/v2/characters/{char['id']}")
        assert resp.status_code == 200, resp.text

        session.expire_all()
        detached = session.get(VoiceModel, voice_id)
        assert detached is not None, "voice model was deleted with the character"
        assert detached.character_id is None
