# Integration tests for World Vault routes (chats, characters, stories).

import pytest
from datetime import datetime, timezone

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
