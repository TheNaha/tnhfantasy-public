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


class TestBulkDelete:
    def test_bulk_delete_entries(self, client, session):
        lb = _seed_lorebook(session)
        ids = []
        for i in range(3):
            resp = client.post(
                f"/api/v2/lorebooks/{lb.id}/entries",
                json={"keys": [f"k{i}"], "content": f"Bulk content {i}"},
            )
            ids.append(resp.json()["id"])
        # One foreign id must be ignored silently.
        resp = client.post(
            f"/api/v2/lorebooks/{lb.id}/entries/bulk-delete",
            json={"entry_ids": ids + ["not-a-real-id"]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"deleted": 3}
        remaining = client.get(f"/api/v2/lorebooks/{lb.id}/entries").json()
        assert remaining == []

    def test_bulk_delete_missing_lorebook_404(self, client, session):
        resp = client.post(
            "/api/v2/lorebooks/nonexistent/entries/bulk-delete",
            json={"entry_ids": ["x"]},
        )
        assert resp.status_code == 404


class TestSillyTavernImportExport:
    ST_WORLDBOOK = {
        "name": "Imported Book",
        "entries": {
            "0": {"uid": 0, "key": ["dragon", "wyrm"], "content": "Dragons hoard gold.", "constant": False},
            "1": {"uid": 1, "key": ["sword"], "content": "The sword hums at night."},
            "2": {"uid": 2, "key": [], "content": ""},  # empty → skipped
        },
    }

    def test_import_st_worldbook_dict(self, client, session):
        lb = _seed_lorebook(session)
        resp = client.post(f"/api/v2/lorebooks/{lb.id}/import", json=self.ST_WORLDBOOK)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"imported": 2}
        entries = client.get(f"/api/v2/lorebooks/{lb.id}/entries").json()
        by_keys = {tuple(sorted(e["keys"])): e["content"] for e in entries}
        assert by_keys[("dragon", "wyrm")] == "Dragons hoard gold."
        assert by_keys[("sword",)] == "The sword hums at night."

    def test_import_st_entries_list_and_comma_string(self, client, session):
        lb = _seed_lorebook(session)
        payload = {"entries": [{"keys": "alpha, beta", "content": "List form."}]}
        resp = client.post(f"/api/v2/lorebooks/{lb.id}/import", json=payload)
        assert resp.status_code == 200, resp.text
        entry = client.get(f"/api/v2/lorebooks/{lb.id}/entries").json()[0]
        assert sorted(entry["keys"]) == ["alpha", "beta"]

    def test_import_rejects_empty_payload(self, client, session):
        lb = _seed_lorebook(session)
        resp = client.post(f"/api/v2/lorebooks/{lb.id}/import", json={"entries": {}})
        assert resp.status_code == 400

    def test_import_missing_lorebook_404(self, client):
        resp = client.post("/api/v2/lorebooks/nonexistent/import", json={"entries": []})
        assert resp.status_code == 404

    def test_export_round_trips_through_import(self, client, session):
        lb = _seed_lorebook(session)
        client.post(
            f"/api/v2/lorebooks/{lb.id}/entries",
            json={"keys": ["roundtrip"], "content": "Round trip content."},
        )
        resp = client.get(f"/api/v2/lorebooks/{lb.id}/export")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/json"
        assert "attachment" in resp.headers.get("content-disposition", "")

        exported = resp.json()
        assert exported["name"] == lb.name
        first = next(iter(exported["entries"].values()))
        assert first["key"] == ["roundtrip"]
        assert first["content"] == "Round trip content."

        # The exported file must be importable into a fresh book.
        other = _seed_lorebook(session)
        reimport = client.post(f"/api/v2/lorebooks/{other.id}/import", json=exported)
        assert reimport.status_code == 200, reimport.text
        assert reimport.json() == {"imported": 1}

    def test_export_missing_lorebook_404(self, client):
        assert client.get("/api/v2/lorebooks/nonexistent/export").status_code == 404