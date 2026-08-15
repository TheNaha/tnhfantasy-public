"""Tests for World Vault Hub endpoints (entities, relationships, search)."""
import pytest

from core.entities import Character, Chat, Lorebook, Story


@pytest.fixture
def setup_entities(session):
    char = Character(name="HubChar", description="Test", personality="Friendly")
    session.add(char)
    session.commit()
    session.refresh(char)

    chat = Chat(title="HubChat")
    session.add(chat)
    session.commit()
    session.refresh(chat)

    lorebook = Lorebook(name="HubLorebook", description="Test lore")
    session.add(lorebook)
    session.commit()
    session.refresh(lorebook)

    story = Story(title="HubStory", description="Test story")
    session.add(story)
    session.commit()
    session.refresh(story)

    return char, chat, lorebook, story


def test_world_vault_entities(client, session, setup_entities):
    char, chat, lorebook, story = setup_entities
    response = client.get("/api/v2/world-vault/entities")
    assert response.status_code == 200
    data = response.json()
    assert "counts" in data
    assert data["counts"]["characters"] >= 1
    assert data["counts"]["stories"] >= 1


def test_world_vault_relationships(client, session, setup_entities):
    char, chat, lorebook, story = setup_entities
    response = client.get("/api/v2/world-vault/relationships")
    assert response.status_code == 200
    data = response.json()
    assert "character_chats" in data
    assert "character_stories" in data
    assert "story_lorebooks" in data


def test_world_vault_search(client, session, setup_entities):
    char, chat, lorebook, story = setup_entities
    response = client.get("/api/v2/world-vault/search?q=Hub")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert len(data["results"]) >= 1


def test_world_vault_search_with_types(client, session, setup_entities):
    char, chat, lorebook, story = setup_entities
    response = client.get("/api/v2/world-vault/search?q=Story&type=story")
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) >= 1
    assert all(r["type"] == "story" for r in data["results"])
