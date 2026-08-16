"""Route tests for World Vault lorebooks: CRUD + entry CRUD/search.

Regression coverage: `create_entry` and `search_entries` previously used
`lorebook_repo` without a Depends parameter (NameError 500 once the repo
layer landed) — every route in this file must return 2xx/4xx, never 500.
"""

import uuid

from core.entities import Lorebook


def _seed_lorebook(session) -> Lorebook:
    lb = Lorebook(name=f"Lorebook {uuid.uuid4().hex[:8]}", description="test")
    session.add(lb)
    session.commit()
    session.refresh(lb)
    return lb


class TestLorebookCrud:
    def test_create_lorebook(self, client, session):
        resp = client.post("/api/v2/lorebooks", json={"name": "Kingdom Lore", "description": "Lore of the kingdom"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["name"] == "Kingdom Lore"
        assert session.get(Lorebook, data["id"]) is not None

    def test_list_lorebooks(self, client, session):
        lb = _seed_lorebook(session)
        resp = client.get("/api/v2/lorebooks")
        assert resp.status_code == 200
        assert any(item["id"] == lb.id for item in resp.json())

    def test_delete_lorebook(self, client, session):
        lb = _seed_lorebook(session)
        resp = client.delete(f"/api/v2/lorebooks/{lb.id}")
        assert resp.status_code == 200, resp.text
        assert session.get(Lorebook, lb.id) is None

    def test_update_lorebook(self, client, session):
        lb = _seed_lorebook(session)
        resp = client.put(f"/api/v2/lorebooks/{lb.id}", json={"description": "updated"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["description"] == "updated"


class TestLorebookEntries:
    def test_create_entry(self, client, session):
        lb = _seed_lorebook(session)
        resp = client.post(
            f"/api/v2/lorebooks/{lb.id}/entries",
            json={"keys": ["crystal_sword"], "content": "The Crystal Sword rests in the Cave of Echoes."},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["lorebook_id"] == lb.id
        assert data["keys"] == ["crystal_sword"]

    def test_create_entry_missing_lorebook_404(self, client, session):
        resp = client.post(
            "/api/v2/lorebooks/nonexistent/entries",
            json={"keys": ["k"], "content": "c"},
        )
        assert resp.status_code == 404

    def test_list_entries(self, client, session):
        lb = _seed_lorebook(session)
        resp = client.post(
            f"/api/v2/lorebooks/{lb.id}/entries",
            json={"keys": ["key_a"], "content": "Entry A"},
        )
        entry_id = resp.json()["id"]
        resp = client.get(f"/api/v2/lorebooks/{lb.id}/entries")
        assert resp.status_code == 200, resp.text
        assert any(item["id"] == entry_id for item in resp.json())

    def test_search_entries(self, client, session):
        lb = _seed_lorebook(session)
        client.post(
            f"/api/v2/lorebooks/{lb.id}/entries",
            json={"keys": ["dragon"], "content": "The dragon slumbers beneath the mountain."},
        )
        resp = client.get(f"/api/v2/lorebooks/{lb.id}/search", params={"q": "dragon"})
        assert resp.status_code == 200, resp.text
        assert len(resp.json()) >= 1

    def test_search_entries_missing_lorebook_404(self, client, session):
        resp = client.get("/api/v2/lorebooks/nonexistent/search", params={"q": "x"})
        assert resp.status_code == 404

    def test_update_entry(self, client, session):
        lb = _seed_lorebook(session)
        resp = client.post(
            f"/api/v2/lorebooks/{lb.id}/entries",
            json={"keys": ["a"], "content": "Original content"},
        )
        entry_id = resp.json()["id"]
        resp = client.put(
            f"/api/v2/lorebooks/{lb.id}/entries/{entry_id}",
            json={"content": "Updated content"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["content"] == "Updated content"

    def test_delete_entry(self, client, session):
        lb = _seed_lorebook(session)
        resp = client.post(
            f"/api/v2/lorebooks/{lb.id}/entries",
            json={"keys": ["a"], "content": "To be deleted"},
        )
        entry_id = resp.json()["id"]
        resp = client.delete(f"/api/v2/lorebooks/{lb.id}/entries/{entry_id}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["message"] == "Entry deleted"

    def test_delete_entry_missing_lorebook_404(self, client, session):
        resp = client.delete("/api/v2/lorebooks/nonexistent/entries/x")
        assert resp.status_code == 404