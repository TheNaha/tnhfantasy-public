"""Tests for World Vault Hub endpoints (entities, relationships, search, graph layout)."""
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


def test_graph_layout_get_empty(client, session):
    """Getting a layout with no saved positions returns empty list."""
    response = client.get("/api/v2/world-vault/graph-layout")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "default"
    assert data["nodes"] == []


def test_graph_layout_save_and_get(client, session):
    """Saving positions persists them and they can be retrieved."""
    payload = {
        "nodes": [
            {"entity_type": "character", "entity_id": "char-1", "x": 100.0, "y": 200.0},
            {"entity_type": "story", "entity_id": "story-1", "x": 300.0, "y": 400.0},
        ]
    }
    response = client.put("/api/v2/world-vault/graph-layout", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["saved"] == 2

    response = client.get("/api/v2/world-vault/graph-layout")
    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) == 2
    char_node = next(n for n in data["nodes"] if n["entity_id"] == "char-1")
    assert char_node["x"] == 100.0
    assert char_node["y"] == 200.0


def test_graph_layout_save_replaces_existing(client, session):
    """Saving a layout replaces all previous positions for that name."""
    payload1 = {"nodes": [{"entity_type": "character", "entity_id": "char-1", "x": 100.0, "y": 200.0}]}
    client.put("/api/v2/world-vault/graph-layout", json=payload1)

    payload2 = {"nodes": [{"entity_type": "story", "entity_id": "story-1", "x": 500.0, "y": 600.0}]}
    client.put("/api/v2/world-vault/graph-layout", json=payload2)

    response = client.get("/api/v2/world-vault/graph-layout")
    data = response.json()
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["entity_id"] == "story-1"


def test_graph_layout_delete(client, session):
    """Deleting a layout removes all its positions."""
    payload = {"nodes": [{"entity_type": "character", "entity_id": "char-1", "x": 100.0, "y": 200.0}]}
    client.put("/api/v2/world-vault/graph-layout", json=payload)

    response = client.delete("/api/v2/world-vault/graph-layout")
    assert response.status_code == 200
    data = response.json()
    assert data["deleted"] == 1

    response = client.get("/api/v2/world-vault/graph-layout")
    data = response.json()
    assert data["nodes"] == []


def test_graph_layout_custom_name(client, session):
    """Layouts can be saved with custom names."""
    payload = {"nodes": [{"entity_type": "character", "entity_id": "char-1", "x": 50.0, "y": 60.0}]}
    response = client.put("/api/v2/world-vault/graph-layout/?name=custom", json=payload)
    assert response.status_code == 200

    response = client.get("/api/v2/world-vault/graph-layout/?name=custom")
    data = response.json()
    assert data["name"] == "custom"
    assert len(data["nodes"]) == 1

