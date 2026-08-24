"""Tests for Character Memory CRUD and semantic search endpoints."""
import pytest

from core.entities import Character, CharacterMemory


@pytest.fixture
def character(session):
    char = Character(name="MemoryCharacter", description="test")
    session.add(char)
    session.commit()
    session.refresh(char)
    return char


@pytest.fixture
def memory_1(session, character):
    mem = CharacterMemory(
        character_id=character.id,
        content="The castle was built in the 14th century.",
        tags=["history", "castle"],
        importance=8,
    )
    session.add(mem)
    session.commit()
    session.refresh(mem)
    return mem


@pytest.fixture
def memory_2(session, character):
    mem = CharacterMemory(
        character_id=character.id,
        content="The secret passage is behind the tapestry.",
        tags=["secret", "hidden"],
        importance=9,
    )
    session.add(mem)
    session.commit()
    session.refresh(mem)
    return mem


def test_create_memory(client, session, character):
    response = client.post("/api/v2/memories", json={
        "character_id": character.id,
        "content": "A dragon lives in the mountain.",
        "tags": ["dragon", "mountain"],
        "importance": 8,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["content"] == "A dragon lives in the mountain."
    assert data["character_id"] == character.id
    assert data["importance"] == 8


def test_list_memories(client, session, character, memory_1, memory_2):
    response = client.get(f"/api/v2/memories?character_id={character.id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


def test_list_memories_no_character(client, session, character, memory_1):
    response = client.get("/api/v2/memories")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


def test_get_memory(client, session, memory_1):
    response = client.get(f"/api/v2/memories/{memory_1.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["content"] == memory_1.content
    assert "history" in data["tags"]


def test_get_memory_not_found(client):
    response = client.get("/api/v2/memories/nonexistent-id")
    assert response.status_code == 404


def test_update_memory(client, session, memory_1):
    response = client.put(f"/api/v2/memories/{memory_1.id}", json={
        "content": "Updated memory content",
        "tags": ["updated", "history"],
        "importance": 5,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["content"] == "Updated memory content"
    assert "updated" in data["tags"]


def test_delete_memory(client, session, memory_1):
    response = client.delete(f"/api/v2/memories/{memory_1.id}")
    assert response.status_code == 200
    response = client.get(f"/api/v2/memories/{memory_1.id}")
    assert response.status_code == 404


def test_memory_search_semantic(client, session, character, memory_1, memory_2):
    response = client.get(f"/api/v2/memories/search/semantic?character_id={character.id}&query=castle")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1


def test_character_memories_list(client, session, character, memory_1, memory_2):
    response = client.get(f"/api/v2/memories/character/{character.id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(m["character_id"] == character.id for m in data)
