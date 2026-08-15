"""Route tests for World Vault campaigns: CRUD, entity linkage round-trips,
and the campaign dashboard aggregation (Batch 2 feature)."""

from sqlmodel import Session

from core.entities import Campaign, Character, Story, Chat, Location


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


class TestCampaignCRUD:
    def test_create_and_get_campaign(self, client, session):
        resp = client.post("/api/v2/campaigns", json={"name": "Crimson Dawn"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "Crimson Dawn"
        assert body["character_ids"] == []
        assert body["id"]

        got = client.get(f"/api/v2/campaigns/{body['id']}")
        assert got.status_code == 200
        assert got.json()["name"] == "Crimson Dawn"

    def test_create_with_entity_linkage(self, client, session):
        char, story, chat, loc = _seed_linkables(session)
        resp = client.post(
            "/api/v2/campaigns",
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

    def test_update_campaign_partial(self, client, session):
        created = client.post("/api/v2/campaigns", json={"name": "Before"}).json()
        resp = client.put(f"/api/v2/campaigns/{created['id']}", json={"description": "after", "name": "After"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "After"
        assert resp.json()["description"] == "after"

    def test_delete_campaign(self, client, session):
        created = client.post("/api/v2/campaigns", json={"name": "Gone"}).json()
        resp = client.delete(f"/api/v2/campaigns/{created['id']}")
        assert resp.status_code == 200
        assert session.get(Campaign, created["id"]) is None

    def test_missing_campaign_404(self, client):
        assert client.get("/api/v2/campaigns/nope").status_code == 404
        assert client.put("/api/v2/campaigns/nope", json={"name": "x"}).status_code == 404
        assert client.delete("/api/v2/campaigns/nope").status_code == 404

    def test_create_requires_name(self, client):
        assert client.post("/api/v2/campaigns", json={"description": "x"}).status_code == 422


class TestCampaignDashboard:
    def test_dashboard_aggregates_linkages(self, client, session):
        char, story, chat, loc = _seed_linkables(session)
        campaign = client.post(
            "/api/v2/campaigns",
            json={
                "name": "Camp",
                "character_ids": [char.id],
                "story_ids": [story.id],
                "chat_ids": [chat.id],
                "location_ids": [loc.id],
            },
        ).json()

        resp = client.get(f"/api/v2/campaigns/{campaign['id']}/dashboard")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["campaign"]["name"] == "Camp"
        assert body["characters"] == [{"id": char.id, "name": "Aria"}]
        assert body["stories"] == [{"id": story.id, "title": "The Long Road"}]
        assert body["chats"] == [{"id": chat.id, "name": "Aria's Chat"}]
        assert body["locations"] == [{"id": loc.id, "name": "Mistvale"}]

    def test_dashboard_empty_linkages(self, client, session):
        campaign = client.post("/api/v2/campaigns", json={"name": "Solo"}).json()
        resp = client.get(f"/api/v2/campaigns/{campaign['id']}/dashboard")
        assert resp.status_code == 200
        body = resp.json()
        assert body["characters"] == []
        assert body["stories"] == []
        assert body["chats"] == []
        assert body["locations"] == []

    def test_dashboard_missing_campaign_404(self, client):
        assert client.get("/api/v2/campaigns/nope/dashboard").status_code == 404