# Integration tests for World Vault routes (chats, characters, stories).

from unittest.mock import AsyncMock

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.deps import get_session
from core.entities import Chat, Character, Message, MessageRole, Story, StoryChapter
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session):
    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    import infrastructure.database as _infra_db
    original_get_session = _infra_db.get_session
    _infra_db.get_session = get_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
    _infra_db.get_session = original_get_session


class TestChatsRoute:
    def test_create_and_get_chat(self, client, session):
        response = client.post("/api/v2/chats", json={
            "name": "Test Chat",
            "chat_type": "chat",
            "persona_name": "User"
        })
        assert response.status_code == 200, response.text
        chat = response.json()
        chat_id = chat["id"]

        get_response = client.get(f"/api/v2/chats/{chat_id}")
        assert get_response.status_code == 200
        assert get_response.json()["name"] == "Test Chat"

    def test_list_chats(self, client, session):
        client.post("/api/v2/chats", json={"name": "Chat 1", "chat_type": "chat"})
        client.post("/api/v2/chats", json={"name": "Chat 2", "chat_type": "chat"})

        response = client.get("/api/v2/chats")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_update_chat(self, client, session):
        create = client.post("/api/v2/chats", json={"name": "Old Name", "chat_type": "chat"})
        chat_id = create.json()["id"]

        response = client.patch(f"/api/v2/chats/{chat_id}", json={"name": "New Name"})
        assert response.status_code == 200
        assert response.json()["name"] == "New Name"

    def test_delete_chat(self, client, session):
        create = client.post("/api/v2/chats", json={"name": "To Delete", "chat_type": "chat"})
        chat_id = create.json()["id"]

        response = client.delete(f"/api/v2/chats/{chat_id}")
        assert response.status_code == 200

        get_response = client.get(f"/api/v2/chats/{chat_id}")
        assert get_response.status_code == 404

    def test_send_message(self, client, session):
        create = client.post("/api/v2/chats", json={"name": "Msg Chat", "chat_type": "chat"})
        chat_id = create.json()["id"]

        response = client.post(f"/api/v2/chats/{chat_id}/messages", json={
            "role": "user",
            "content": "Hello"
        })
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["user_message_id"]
        assert data["job_id"]
        messages = client.get(f"/api/v2/chats/{chat_id}/messages").json()
        assert any(m["role"] == "user" and m["content"] == "Hello" for m in messages)

    def test_chat_with_character_greeting(self, client, session):
        character = Character(name="TestChar", first_mes="Greetings, traveler!")
        session.add(character)
        session.commit()
        session.refresh(character)

        response = client.post("/api/v2/chats", json={
            "name": "Char Chat",
            "chat_type": "chat",
            "character_id": character.id
        })
        assert response.status_code == 200, response.text
        chat_id = response.json()["id"]

        messages = client.get(f"/api/v2/chats/{chat_id}/messages").json()
        assert len(messages) == 1
        assert messages[0]["role"] == "char"
        assert "Greetings, traveler!" in messages[0]["content"]


class TestCharactersRoute:
    def test_create_and_get_character(self, client, session):
        response = client.post("/api/v2/characters", json={
            "name": "Test Character",
            "description": "A test character"
        })
        assert response.status_code == 200, response.text
        char = response.json()
        char_id = char["id"]

        get_response = client.get(f"/api/v2/characters/{char_id}")
        assert get_response.status_code == 200
        assert get_response.json()["name"] == "Test Character"

    def test_list_characters(self, client, session):
        client.post("/api/v2/characters", json={"name": "Char 1"})
        client.post("/api/v2/characters", json={"name": "Char 2"})

        response = client.get("/api/v2/characters")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_update_character(self, client, session):
        create = client.post("/api/v2/characters", json={"name": "Old Name"})
        char_id = create.json()["id"]

        response = client.patch(f"/api/v2/characters/{char_id}", json={"name": "New Name"})
        assert response.status_code == 200
        assert response.json()["name"] == "New Name"

    def test_delete_character(self, client, session):
        create = client.post("/api/v2/characters", json={"name": "To Delete"})
        char_id = create.json()["id"]

        response = client.delete(f"/api/v2/characters/{char_id}")
        assert response.status_code == 200

        get_response = client.get(f"/api/v2/characters/{char_id}")
        assert get_response.status_code == 404


class TestStoriesRoute:
    def test_create_and_get_story(self, client, session):
        response = client.post("/api/v2/stories", json={
            "title": "Test Story",
            "genre": "fantasy"
        })
        assert response.status_code == 200, response.text
        story = response.json()
        story_id = story["id"]

        get_response = client.get(f"/api/v2/stories/{story_id}")
        assert get_response.status_code == 200
        assert get_response.json()["title"] == "Test Story"

    def test_list_stories(self, client, session):
        client.post("/api/v2/stories", json={"title": "Story 1"})
        client.post("/api/v2/stories", json={"title": "Story 2"})

        response = client.get("/api/v2/stories")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_create_chapter(self, client, session):
        create = client.post("/api/v2/stories", json={"title": "Chapter Test"})
        story_id = create.json()["id"]

        response = client.post(f"/api/v2/stories/{story_id}/chapters", json={
            "title": "Chapter 1",
            "content": "Once upon a time..."
        })
        assert response.status_code == 200, response.text
        chapter = response.json()
        assert chapter["title"] == "Chapter 1"
        assert chapter["story_id"] == story_id

    def test_update_story(self, client, session):
        create = client.post("/api/v2/stories", json={"title": "Old Title"})
        story_id = create.json()["id"]

        response = client.put(f"/api/v2/stories/{story_id}", json={"title": "New Title"})
        assert response.status_code == 200
        assert response.json()["title"] == "New Title"

    def test_delete_story(self, client, session):
        create = client.post("/api/v2/stories", json={"title": "To Delete"})
        story_id = create.json()["id"]

        response = client.delete(f"/api/v2/stories/{story_id}")
        assert response.status_code == 200

        get_response = client.get(f"/api/v2/stories/{story_id}")
        assert get_response.status_code == 404

    def test_parse_story(self, client, session, monkeypatch):
        monkeypatch.setattr("services.llm_config.get_default_llm_model", lambda: "test-model")
        monkeypatch.setattr("services.job_queue.queue_manager.enqueue", AsyncMock(return_value=True))

        story = Story(title="Parse Test")
        session.add(story)
        session.commit()
        session.refresh(story)

        response = client.post("/api/v2/stories/parse", json={
            "story_id": story.id,
            "text": "Alice was a brave knight who lived in the Shire. The Ancient Lore spoke of great magic.",
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["job_id"]

        from core.entities import Job
        job = session.get(Job, body["job_id"])
        assert job.task_type == "llm"
        assert job.workflow["type"] == "story_parse"


class TestChatSearchAndExport:
    def test_list_chats_with_search(self, client, session):
        c1 = Chat(name="Alpha Chat", chat_type="chat")
        c2 = Chat(name="Beta Chat", chat_type="chat")
        c3 = Chat(name="Alpha Story", chat_type="story")
        session.add_all([c1, c2, c3])
        session.commit()

        resp = client.get("/api/v2/chats", params={"q": "Alpha"})
        assert resp.status_code == 200
        names = [c["name"] for c in resp.json()]
        assert "Alpha Chat" in names
        assert "Beta Chat" not in names

    def test_export_chat_returns_json(self, client, session):
        chat = Chat(name="Export Chat", chat_type="chat")
        session.add(chat)
        session.commit()
        session.refresh(chat)
        session.add(Message(chat_id=chat.id, role=MessageRole.USER, content="hello"))
        session.commit()

        resp = client.get(f"/api/v2/chats/{chat.id}/export")
        assert resp.status_code == 200
        body = resp.json()
        assert body["chat"]["name"] == "Export Chat"
        assert len(body["messages"]) == 1
        assert body["messages"][0]["content"] == "hello"
        assert body["meta"]["message_count"] == 1

    def test_export_chat_not_found(self, client, session):
        resp = client.get("/api/v2/chats/does-not-exist/export")
        assert resp.status_code == 404


class TestStoryExportAndReorder:
    def test_export_story_returns_json(self, client, session):
        story = Story(title="Export Story")
        session.add(story)
        session.commit()
        session.refresh(story)
        ch = StoryChapter(story_id=story.id, title="Ch1", content="Once upon a time", chapter_number=1)
        session.add(ch)
        session.commit()

        resp = client.get(f"/api/v2/stories/{story.id}/export")
        assert resp.status_code == 200
        body = resp.json()
        assert body["story"]["title"] == "Export Story"
        assert len(body["chapters"]) == 1
        assert body["chapters"][0]["content"] == "Once upon a time"
        assert body["meta"]["chapter_count"] == 1

    def test_reorder_chapters(self, client, session):
        story = Story(title="Reorder Story")
        session.add(story)
        session.commit()
        session.refresh(story)
        ch1 = StoryChapter(story_id=story.id, title="A", chapter_number=1)
        ch2 = StoryChapter(story_id=story.id, title="B", chapter_number=2)
        session.add_all([ch1, ch2])
        session.commit()
        session.refresh(ch1)
        session.refresh(ch2)

        resp = client.post(f"/api/v2/stories/{story.id}/chapters/reorder", json={"chapter_ids": [ch2.id, ch1.id]})
        assert resp.status_code == 200
        session.refresh(ch1)
        session.refresh(ch2)
        assert ch1.chapter_number == 2
        assert ch2.chapter_number == 1
