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


class TestChatStoryCohesion:
    def test_export_chat_to_story(self, client, session):
        chat, char = _seed(session)
        _add(session, chat, MessageRole.USER, "Where are we heading?")
        _add(session, chat, MessageRole.CHAR, "To the Whispering Woods.", character_id=char.id)
        _add(
            session,
            chat,
            MessageRole.SYSTEM,
            "",
            message_metadata={"source": "world_state", "location": "Forest Gate", "time": "Dusk"},
        )

        resp = client.post(f"/api/v2/chats/{chat.id}/export-story")
        assert resp.status_code == 200
        data = resp.json()
        story_id = data["story_id"]
        assert data["title"] == "Interop Chat"

        # Verify story in DB
        from core.entities import Story, StoryChapter
        story = session.get(Story, story_id)
        assert story is not None
        assert char.id in story.character_ids
        assert story.persona_name == "Naha"

        chapters = session.exec(select(StoryChapter).where(StoryChapter.story_id == story_id)).all()
        assert len(chapters) == 1
        assert "Where are we heading?" in chapters[0].content
        assert "To the Whispering Woods." in chapters[0].content
        assert "Forest Gate" in chapters[0].content

    def test_start_chat_from_story(self, client, session):
        from core.entities import Story, StoryChapter
        char = Character(name="Lyra")
        session.add(char)
        session.commit()
        session.refresh(char)

        story = Story(
            title="The Silver Spire",
            character_ids=[char.id],
            persona_name="Traveler",
            description="A journey to the ancient spire.",
        )
        session.add(story)
        session.commit()
        session.refresh(story)

        chapter = StoryChapter(
            story_id=story.id,
            chapter_number=1,
            title="The Ascent",
            content="Rain beat relentlessly against the obsidian walls of the spire.",
        )
        session.add(chapter)
        session.commit()
        session.refresh(chapter)

        resp = client.post(f"/api/v2/stories/{story.id}/start-chat", json={"chapter_id": chapter.id})
        assert resp.status_code == 200
        chat_data = resp.json()
        assert "chat_id" in chat_data

        # Verify Chat in DB
        chat = session.get(Chat, chat_data["chat_id"])
        assert chat is not None
        assert chat.character_id == char.id
        assert chat.persona_name == "Traveler"
        assert "The Silver Spire" in chat.name

        # Verify seed message was created
        msgs = session.exec(select(Message).where(Message.chat_id == chat.id)).all()
        assert len(msgs) == 1
        assert msgs[0].role == MessageRole.SYSTEM
        assert "obsidian walls" in msgs[0].content

