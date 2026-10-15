"""Route tests for World Vault worlds: CRUD, and the world dashboard.

Membership is one `world_id` column per member table, written by the member's
own route. It used to be six JSON id arrays accepted by this route on create
and PUT, which is why those tests read `<list>` back off the response: the only
way to see membership was through the world. Now it is read the other way round,
so the tests that matter assert the member, not the world.
"""

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
        assert body["id"]
        # No membership fields at all: a world has no roster of its own, and
        # accepting one here is what made the world and its members able to
        # disagree about who is in it.
        assert "character_ids" not in body
        assert "counts" not in body

        got = client.get(f"/api/v2/worlds/{body['id']}")
        assert got.status_code == 200
        assert got.json()["name"] == "Crimson Dawn"

    def test_create_with_entity_linkage(self, client, session):
        """A world is created empty; members are joined from the member side.

        This test used to POST all four id lists and read them straight back.
        That contract is gone on purpose: the arrays were a second description
        of a relationship the member tables own, and `PUT` could rewrite
        `chat_ids`/`story_ids` without touching the `world_id` FKs that own
        them. A roster is now declared by each member's own `world_id`.
        """
        resp = client.post(
            "/api/v2/worlds",
            json={"name": "Linked", "description": "everything in one"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "Linked"
        assert "character_ids" not in body

    def test_membership_is_declared_from_the_member_side(self, client, session):
        """Setting `world_id` on a member is what puts it in a world."""
        char, story, chat, loc = _seed_linkables(session)
        world = client.post("/api/v2/worlds", json={"name": "Joined"}).json()

        # Character: the member's own PUT.
        resp = client.put(f"/api/v2/characters/{char.id}", json={"world_id": world["id"]})
        assert resp.status_code == 200, resp.text
        assert client.get(f"/api/v2/worlds/{world['id']}/dashboard").json()["characters"] == [
            {"id": char.id, "name": "Aria"}
        ]

        listed = client.get("/api/v2/worlds").json()
        mine = next(w for w in listed if w["id"] == world["id"])
        assert mine["counts"]["Character"] == 1

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
        """The dashboard resolves membership through the FKs, in both directions.

        The story and chat side is asserted through their own routes (which own
        `world_id`), the location side directly on the session, because the
        point of the test is that the world sees whoever points at it — not how
        each member's route spells the write.
        """
        char, story, chat, loc = _seed_linkables(session)
        world = client.post("/api/v2/worlds", json={"name": "Camp"}).json()

        assert client.put(f"/api/v2/characters/{char.id}", json={"world_id": world["id"]}).status_code == 200
        char.world_id = world["id"]
        session.add(char)
        session.commit()
        story.world_id = world["id"]
        session.add(story)
        session.commit()
        chat.world_id = world["id"]
        session.add(chat)
        session.commit()
        loc.world_id = world["id"]
        session.add(loc)
        session.commit()

        resp = client.get(f"/api/v2/worlds/{world['id']}/dashboard")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["world"]["name"] == "Camp"
        assert body["characters"] == [{"id": char.id, "name": "Aria"}]
        assert body["stories"] == [{"id": story.id, "title": "The Long Road"}]
        assert body["chats"] == [{"id": chat.id, "name": "Aria's Chat"}]
        assert body["locations"] == [{"id": loc.id, "name": "Mistvale"}]
        assert body["lorebooks"] == []
        assert body["scenarios"] == []
        assert body["voices"] == []

    def test_dashboard_empty_linkages(self, client, session):
        world = client.post("/api/v2/worlds", json={"name": "Solo"}).json()
        resp = client.get(f"/api/v2/worlds/{world['id']}/dashboard")
        assert resp.status_code == 200
        body = resp.json()
        assert body["characters"] == []
        assert body["stories"] == []
        assert body["chats"] == []
        assert body["locations"] == []
        assert body["lorebooks"] == []
        assert body["scenarios"] == []
        assert body["voices"] == []

    def test_dashboard_missing_world_404(self, client):
        assert client.get("/api/v2/worlds/nope/dashboard").status_code == 404