"""Route tests for World Vault locations: CRUD, search, and the
/search-vs-/{location_id} shadowing regression (search must be matched first).
"""

from sqlmodel import Session, select

from core.entities import Location


def _loc_count(session: Session) -> int:
    return len(session.exec(select(Location)).all())


class TestLocationCRUD:
    def test_create_and_get_location(self, client, session):
        resp = client.post(
            "/api/v2/locations",
            json={
                "name": "Mistvale",
                "description": "A foggy valley",
                "atmosphere": "gloomy",
                "tags": ["forest"],
                "map_x": 12.5,
                "map_y": 45.0,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "Mistvale"
        assert body["atmosphere"] == "gloomy"
        assert body["tags"] == ["forest"]
        assert body["id"]
        assert body["map_x"] == 12.5
        assert body["map_y"] == 45.0

        got = client.get(f"/api/v2/locations/{body['id']}")
        assert got.status_code == 200
        assert got.json()["name"] == "Mistvale"
        assert got.json()["map_x"] == 12.5
        assert got.json()["map_y"] == 45.0

    def test_list_locations_ordered(self, client, session):
        client.post("/api/v2/locations", json={"name": "Zion"})
        client.post("/api/v2/locations", json={"name": "Aurora"})
        resp = client.get("/api/v2/locations")
        assert resp.status_code == 200
        names = [loc["name"] for loc in resp.json()]
        assert names == ["Aurora", "Zion"]

    def test_update_location_put(self, client, session):
        created = client.post("/api/v2/locations", json={"name": "Old Name"}).json()
        resp = client.put(f"/api/v2/locations/{created['id']}", json={"name": "New Name", "description": "x"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    def test_patch_location_partial(self, client, session):
        created = client.post("/api/v2/locations", json={"name": "Keep", "description": "drop me"}).json()
        resp = client.patch(f"/api/v2/locations/{created['id']}", json={"description": None})
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Keep"
        assert body["description"] is None

    def test_patch_location_null_name_is_422(self, client, session):
        created = client.post("/api/v2/locations", json={"name": "Keep"}).json()
        resp = client.patch(f"/api/v2/locations/{created['id']}", json={"name": None})
        assert resp.status_code == 422
        assert session.get(Location, created["id"]).name == "Keep"

    def test_delete_location(self, client, session):
        created = client.post("/api/v2/locations", json={"name": "Doomed"}).json()
        resp = client.delete(f"/api/v2/locations/{created['id']}")
        assert resp.status_code == 200
        assert session.get(Location, created["id"]) is None

    def test_get_missing_location_404(self, client):
        assert client.get("/api/v2/locations/nope").status_code == 404
        assert client.put("/api/v2/locations/nope", json={"name": "x"}).status_code == 404
        assert client.patch("/api/v2/locations/nope", json={"name": "x"}).status_code == 404
        assert client.delete("/api/v2/locations/nope").status_code == 404

    def test_create_requires_name(self, client):
        resp = client.post("/api/v2/locations", json={"description": "no name"})
        assert resp.status_code == 422


class TestLocationSearch:
    def test_search_matches_name(self, client, session):
        client.post("/api/v2/locations", json={"name": "The Whispering Woods"})
        client.post("/api/v2/locations", json={"name": "Iron Deserts"})
        resp = client.get("/api/v2/locations/search", params={"q": "whisper"})
        assert resp.status_code == 200, resp.text
        names = [loc["name"] for loc in resp.json()]
        assert names == ["The Whispering Woods"]

    def test_search_matches_description(self, client, session):
        client.post("/api/v2/locations", json={"name": "Plateau", "description": "home of the sunlit temple"})
        resp = client.get("/api/v2/locations/search", params={"q": "sunlit"})
        assert resp.status_code == 200
        assert [loc["name"] for loc in resp.json()] == ["Plateau"]

    def test_search_no_matches_empty(self, client, session):
        client.post("/api/v2/locations", json={"name": "Town"})
        resp = client.get("/api/v2/locations/search", params={"q": "zzzz"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_search_requires_q(self, client):
        assert client.get("/api/v2/locations/search").status_code == 422

    def test_search_not_shadowed_by_id_route(self, client, session):
        # Regression: /search must resolve to the search handler, not the
        # /{location_id} path parameter (Batch 1 fix).
        client.post("/api/v2/locations", json={"name": "Searchable Cove"})
        resp = client.get("/api/v2/locations/search", params={"q": "cove"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) == 1