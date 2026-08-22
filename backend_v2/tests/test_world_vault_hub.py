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


def test_world_vault_relationships_dangling(client, session, setup_entities):
    """Dangling links (referencing deleted entities) are kept, not dropped."""
    char, chat, lorebook, story = setup_entities

    # Point the story at a character and lorebook that don't exist.
    story.character_ids = ["ghost-char"]
    story.lorebook_ids = ["ghost-lore"]
    story.location_ids = ["ghost-loc"]
    session.add(story)
    session.commit()

    response = client.get("/api/v2/world-vault/relationships")
    assert response.status_code == 200
    data = response.json()

    char_links = [l for l in data["character_stories"] if l["character_id"] == "ghost-char"]
    assert len(char_links) == 1
    assert char_links[0]["dangling"] is True
    assert char_links[0]["character_name"] is None

    lb_links = [l for l in data["story_lorebooks"] if l["lorebook_id"] == "ghost-lore"]
    assert len(lb_links) == 1
    assert lb_links[0]["dangling"] is True

    loc_links = [l for l in data["story_locations"] if l["location_id"] == "ghost-loc"]
    assert len(loc_links) == 1
    assert loc_links[0]["dangling"] is True

