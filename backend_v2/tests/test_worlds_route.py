"""Route tests for World Vault worlds: CRUD, entity linkage round-trips,
and the world dashboard aggregation (Batch 2 feature)."""

from sqlmodel import Session

from core.entities import World, Character, Story, Chat, Location


def _seed_linkables(session: Session):
    char = Character(name="Aria")
    story = Story(title="The Long Road")
    chat = Chat(name="Aria's Chat", character_id=char.id)
    loc = Location(name="Mistvale")
    session.add(char)
    session.add(story)
    session.add(chat)
    session.add(loc)
    session.commit()
    for obj in (char, story, chat, loc):
        session.refresh(obj)
    return char, story, chat, loc


class TestWorldCRUD:
    def test_create_and_get_world(self, client, session):
        resp = client.post("/api/v2/worlds", json={"name": "Crimson Dawn"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "Crimson Dawn"
        assert body["character_ids"] == []
        assert body["id"]

        got = client.get(f"/api/v2/worlds/{body['id']}")
        assert got.status_code == 200
        assert got.json()["name"] == "Crimson Dawn"

    def test_create_with_entity_linkage(self, client, session):
        char, story, chat, loc = _seed_linkables(session)
        resp = client.post(
            "/api/v2/worlds",
            json={
                "name": "Linked",
                "description": "everything in one",
                "character_ids": [char.id],
                "story_ids": [story.id],
                "chat_ids": [chat.id],
                "location_ids": [loc.id],
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["character_ids"] == [char.id]
        assert body["story_ids"] == [story.id]
        assert body["chat_ids"] == [chat.id]
        assert body["location_ids"] == [loc.id]

    def test_update_world_partial(self, client, session):
        created = client.post("/api/v2/worlds", json={"name": "Before"}).json()
        resp = client.put(f"/api/v2/worlds/{created['id']}", json={"description": "after", "name": "After"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "After"
        assert resp.json()["description"] == "after"

    def test_delete_world(self, client, session):
        created = client.post("/api/v2/worlds", json={"name": "Gone"}).json()
        resp = client.delete(f"/api/v2/worlds/{created['id']}")
        assert resp.status_code == 200
        assert session.get(World, created["id"]) is None

    def test_missing_world_404(self, client):
        assert client.get("/api/v2/worlds/nope").status_code == 404
        assert client.put("/api/v2/worlds/nope", json={"name": "x"}).status_code == 404
        assert client.delete("/api/v2/worlds/nope").status_code == 404

    def test_create_requires_name(self, client):
        assert client.post("/api/v2/worlds", json={"description": "x"}).status_code == 422


class TestWorldDashboard:
    def test_dashboard_aggregates_linkages(self, client, session):
        char, story, chat, loc = _seed_linkables(session)
        world = client.post(
            "/api/v2/worlds",
            json={
                "name": "Camp",
                "character_ids": [char.id],
                "story_ids": [story.id],
                "chat_ids": [chat.id],
                "location_ids": [loc.id],
            },
        ).json()

        resp = client.get(f"/api/v2/worlds/{world['id']}/dashboard")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["world"]["name"] == "Camp"
        assert body["characters"] == [{"id": char.id, "name": "Aria"}]
        assert body["stories"] == [{"id": story.id, "title": "The Long Road"}]
        assert body["chats"] == [{"id": chat.id, "name": "Aria's Chat"}]
        assert body["locations"] == [{"id": loc.id, "name": "Mistvale"}]

    def test_dashboard_empty_linkages(self, client, session):
        world = client.post("/api/v2/worlds", json={"name": "Solo"}).json()
        resp = client.get(f"/api/v2/worlds/{world['id']}/dashboard")
        assert resp.status_code == 200
        body = resp.json()
        assert body["characters"] == []
        assert body["stories"] == []
        assert body["chats"] == []
        assert body["locations"] == []

    def test_dashboard_missing_world_404(self, client):
        assert client.get("/api/v2/worlds/nope/dashboard").status_code == 404