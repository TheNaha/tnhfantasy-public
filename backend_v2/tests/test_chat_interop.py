"""SillyTavern JSONL export/import interop tests for chat routes.

Covers:
  - GET /chats/{id}/export?format=jsonl (ST-compatible NDJSON)
  - POST /chats/import (ST JSONL + internal JSON round-trip, validation errors)
"""

import json

from sqlmodel import Session, select

from core.entities import Chat, Character, Message, MessageKind, MessageRole


def _seed(session: Session) -> tuple[Chat, Character]:
    char = Character(name="Aria")
    session.add(char)
    session.commit()
    session.refresh(char)
    chat = Chat(name="Interop Chat", character_id=char.id, persona_name="Naha")
    session.add(chat)
    session.commit()
    session.refresh(chat)
    return chat, char


def _add(session: Session, chat: Chat, role: MessageRole, content: str, **kw) -> Message:
    msg = Message(chat_id=chat.id, role=role, content=content, **kw)
    session.add(msg)
    session.commit()
    session.refresh(msg)
    return msg


class TestExportJsonl:
    def test_jsonl_header_and_messages(self, client, session):
        chat, char = _seed(session)
        _add(session, chat, MessageRole.USER, "Hello there")
        _add(session, chat, MessageRole.CHAR, "Greetings, traveler.", character_id=char.id)

        resp = client.get(f"/api/v2/chats/{chat.id}/export", params={"format": "jsonl"})
        assert resp.status_code == 200
        assert "ndjson" in resp.headers["content-type"]
        lines = [json.loads(ln) for ln in resp.text.splitlines() if ln.strip()]
        header = lines[0]
        assert header["user_name"] == "Naha"
        assert header["character_name"] == "Aria"
        assert "chat_metadata" in header
        user_line, char_line = lines[1], lines[2]
        assert user_line["is_user"] is True and user_line["name"] == "Naha"
        assert user_line["mes"] == "Hello there"
        assert char_line["is_user"] is False and char_line["name"] == "Aria"
        assert char_line["mes"] == "Greetings, traveler."

    def test_jsonl_skips_world_state_and_images(self, client, session):
        chat, char = _seed(session)
        _add(
            session,
            chat,
            MessageRole.SYSTEM,
            "divider",
            kind=MessageKind.NARRATOR,
            message_metadata={"source": "world_state"},
        )
        _add(session, chat, MessageRole.CHAR, "", kind=MessageKind.IMAGE, image_path="x.png")

        resp = client.get(f"/api/v2/chats/{chat.id}/export", params={"format": "jsonl"})
        lines = [json.loads(ln) for ln in resp.text.splitlines() if ln.strip()]
        assert len(lines) == 1  # header only

    def test_default_format_still_json(self, client, session):
        chat, _ = _seed(session)
        resp = client.get(f"/api/v2/chats/{chat.id}/export")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["chat"]["name"] == "Interop Chat"
        assert isinstance(payload["messages"], list)


class TestImportStJsonl:
    def test_import_roundtrip(self, client, session):
        st = "\n".join(
            [
                json.dumps({"user_name": "Naha", "character_name": "Aria", "create_date": "2026-08-26", "chat_metadata": {}}),
                json.dumps({"name": "Naha", "is_user": True, "is_system": False, "send_date": "2026-08-26T10:00:00", "mes": "Hi Aria"}),
                json.dumps({"name": "Aria", "is_user": False, "is_system": False, "send_date": "2026-08-26T10:00:05", "mes": "Welcome back."}),
            ]
        )
        resp = client.post(
            "/api/v2/chats/import",
            files={"file": ("chat.jsonl", st.encode(), "application/x-ndjson")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["persona_name"] == "Naha"
        msgs = session.exec(
            select(Message).where(Message.chat_id == body["id"]).order_by(Message.created_at)
        ).all()
        assert [m.content for m in msgs] == ["Hi Aria", "Welcome back."]
        assert msgs[0].role == MessageRole.USER
        assert msgs[1].role == MessageRole.CHAR

    def test_import_attributes_secondary_character_by_name(self, client, session):
        other = Character(name="Borin")
        session.add(other)
        session.commit()
        session.refresh(other)
        st = "\n".join(
            [
                json.dumps({"user_name": "U", "character_name": "Aria", "chat_metadata": {}}),
                json.dumps({"name": "Borin", "is_user": False, "is_system": False, "send_date": "", "mes": "Hmph."}),
            ]
        )
        resp = client.post("/api/v2/chats/import", files={"file": ("c.jsonl", st.encode(), "application/x-ndjson")})
        assert resp.status_code == 200
        chat_id = resp.json()["id"]
        msg = session.exec(select(Message).where(Message.chat_id == chat_id)).one()
        assert msg.character_id == other.id

    def test_rejects_garbage(self, client, session):
        resp = client.post("/api/v2/chats/import", files={"file": ("x.jsonl", b"not json", "text/plain")})
        assert resp.status_code == 400

    def test_rejects_unknown_character(self, client, session):
        st = json.dumps({"user_name": "U", "character_name": "A", "chat_metadata": {}}) + "\n" + json.dumps(
            {"name": "A", "is_user": False, "is_system": False, "send_date": "", "mes": "x"}
        )
        resp = client.post(
            "/api/v2/chats/import",
            files={"file": ("c.jsonl", st.encode(), "application/x-ndjson")},
            data={"character_id": "nope"},
        )
        assert resp.status_code == 400


class TestImportInternalRoundTrip:
    def test_internal_json_roundtrip(self, client, session):
        chat, char = _seed(session)
        _add(session, chat, MessageRole.USER, "One")
        _add(session, chat, MessageRole.CHAR, "Two", character_id=char.id)

        exported = client.get(f"/api/v2/chats/{chat.id}/export").json()

        resp = client.post(
            "/api/v2/chats/import",
            files={"file": ("chat.json", json.dumps(exported).encode(), "application/json")},
        )
        assert resp.status_code == 200
        new_chat = resp.json()
        assert new_chat["id"] != chat.id
        assert new_chat["name"] == "Interop Chat"
        assert new_chat["persona_name"] == "Naha"
        msgs = session.exec(
            select(Message).where(Message.chat_id == new_chat["id"]).order_by(Message.created_at)
        ).all()
        assert [(m.role, m.content) for m in msgs] == [
            (MessageRole.USER, "One"),
            (MessageRole.CHAR, "Two"),
        ]
        assert msgs[1].character_id == char.id
