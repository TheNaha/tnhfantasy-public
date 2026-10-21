"""Regression tests for audit-2026-10-21 findings 5 and 6: the SillyTavern
lorebook round trip dropped the state of every entry, and the entry's state
could not be edited at all.

Finding 5: the import read only `key`/`keys`/`comment`/`content`, and the
export HARDCODED `"keysecondary": []`, `"selective": True`,
`"selectiveLogic": 0`, `"disable": False`. So a book imported from
SillyTavern came back with its disabled entries ENABLED, its selective
entries stripped of their secondary keys, and its probabilities discarded.

Finding 6: `EntryUpdate` declared only `keys` and `content`, so `enabled`,
`secondary_keys`, `case_sensitive`, `selective_logic`, `probability`,
`depth`, `category` and `tags` were unreachable through the API. A user who
imported a book with a disabled entry could never re-enable it.
"""

from __future__ import annotations

import uuid

from core.entities import Lorebook

ST_BOOK = {
    "name": "Book",
    "entries": {
        "0": {
            "uid": 0,
            "key": ["dragon"],
            "keysecondary": ["wyrm"],
            "comment": "Dragons",
            "content": "Dragons hoard gold.",
            "constant": False,
            "disable": True,
            "caseSensitive": True,
            "selectiveLogic": 1,
            "probability": 40,
            "depth": 2,
        },
        "1": {
            "uid": 1,
            "key": ["sword"],
            "content": "The sword hums at night.",
            "constant": True,
        },
    },
}


def _seed_lorebook(session) -> Lorebook:
    lb = Lorebook(name=f"Lorebook {uuid.uuid4().hex[:8]}", description="test")
    session.add(lb)
    session.commit()
    session.refresh(lb)
    return lb


def _by_content(entries: list[dict]) -> dict[str, dict]:
    return {e["content"]: e for e in entries}


class TestTheImportKeepsTheEntryState:
    def test_a_disabled_entry_stays_disabled(self, client, session):
        lb = _seed_lorebook(session)
        resp = client.post(f"/api/v2/lorebooks/{lb.id}/import", json=ST_BOOK)
        assert resp.status_code == 200, resp.text

        entries = client.get(f"/api/v2/lorebooks/{lb.id}/entries").json()
        dragon = _by_content(entries)["Dragons hoard gold."]
        assert dragon["enabled"] is False

    def test_the_secondary_keys_survive(self, client, session):
        lb = _seed_lorebook(session)
        client.post(f"/api/v2/lorebooks/{lb.id}/import", json=ST_BOOK)

        entries = client.get(f"/api/v2/lorebooks/{lb.id}/entries").json()
        dragon = _by_content(entries)["Dragons hoard gold."]
        assert dragon["secondary_keys"] == ["wyrm"]

    def test_the_remaining_state_survives(self, client, session):
        lb = _seed_lorebook(session)
        client.post(f"/api/v2/lorebooks/{lb.id}/import", json=ST_BOOK)

        entries = client.get(f"/api/v2/lorebooks/{lb.id}/entries").json()
        dragon = _by_content(entries)["Dragons hoard gold."]
        assert dragon["case_sensitive"] is True
        assert dragon["selective_logic"] == "1"
        assert dragon["probability"] == 40
        assert dragon["depth"] == 2
        assert dragon["category"] == "Dragons"

    def test_a_constant_entry_becomes_keyless(self, client, session):
        """`constant: true` is this vault's always-on entry: no keys."""
        lb = _seed_lorebook(session)
        client.post(f"/api/v2/lorebooks/{lb.id}/import", json=ST_BOOK)

        entries = client.get(f"/api/v2/lorebooks/{lb.id}/entries").json()
        sword = _by_content(entries)["The sword hums at night."]
        assert sword["keys"] == []
        assert sword["enabled"] is True

    def test_an_explicit_enabled_flag_is_honoured(self, client, session):
        lb = _seed_lorebook(session)
        payload = {
            "entries": {
                "0": {"key": ["a"], "content": "A.", "enabled": False},
                "1": {"key": ["b"], "content": "B.", "enabled": True},
            }
        }
        client.post(f"/api/v2/lorebooks/{lb.id}/import", json=payload)

        entries = client.get(f"/api/v2/lorebooks/{lb.id}/entries").json()
        by_content = _by_content(entries)
        assert by_content["A."]["enabled"] is False
        assert by_content["B."]["enabled"] is True


class TestTheExportEmitsTheRealValues:
    def _imported_book(self, client, session) -> Lorebook:
        lb = _seed_lorebook(session)
        resp = client.post(f"/api/v2/lorebooks/{lb.id}/import", json=ST_BOOK)
        assert resp.status_code == 200, resp.text
        return lb

    def test_the_disabled_flag_is_not_hardcoded_to_false(self, client, session):
        lb = self._imported_book(client, session)

        exported = client.get(f"/api/v2/lorebooks/{lb.id}/export").json()
        entries = {e["content"]: e for e in exported["entries"].values()}
        assert entries["Dragons hoard gold."]["disable"] is True
        assert entries["The sword hums at night."]["disable"] is False

    def test_the_secondary_keys_are_not_hardcoded_to_empty(self, client, session):
        lb = self._imported_book(client, session)

        exported = client.get(f"/api/v2/lorebooks/{lb.id}/export").json()
        entries = {e["content"]: e for e in exported["entries"].values()}
        assert entries["Dragons hoard gold."]["keysecondary"] == ["wyrm"]
        assert entries["Dragons hoard gold."]["selective"] is True
        # An entry with no secondary keys is not selective.
        assert entries["The sword hums at night."]["selective"] is False

    def test_the_selective_logic_is_not_hardcoded_to_zero(self, client, session):
        lb = self._imported_book(client, session)

        exported = client.get(f"/api/v2/lorebooks/{lb.id}/export").json()
        entries = {e["content"]: e for e in exported["entries"].values()}
        assert int(entries["Dragons hoard gold."]["selectiveLogic"]) == 1

    def test_the_probability_and_the_depth_are_emitted(self, client, session):
        lb = self._imported_book(client, session)

        exported = client.get(f"/api/v2/lorebooks/{lb.id}/export").json()
        entries = {e["content"]: e for e in exported["entries"].values()}
        assert entries["Dragons hoard gold."]["probability"] == 40
        assert entries["Dragons hoard gold."]["depth"] == 2
        assert entries["Dragons hoard gold."]["caseSensitive"] is True


class TestTheRoundTrip:
    def test_import_export_import_keeps_the_state(self, client, session):
        lb = _seed_lorebook(session)
        client.post(f"/api/v2/lorebooks/{lb.id}/import", json=ST_BOOK)

        exported = client.get(f"/api/v2/lorebooks/{lb.id}/export").json()

        other = _seed_lorebook(session)
        resp = client.post(f"/api/v2/lorebooks/{other.id}/import", json=exported)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"imported": 2}

        entries = client.get(f"/api/v2/lorebooks/{other.id}/entries").json()
        dragon = _by_content(entries)["Dragons hoard gold."]
        assert dragon["enabled"] is False
        assert dragon["secondary_keys"] == ["wyrm"]
        assert dragon["case_sensitive"] is True
        assert dragon["selective_logic"] == "1"
        assert dragon["probability"] == 40
        assert dragon["depth"] == 2
        assert dragon["category"] == "Dragons"
        assert dragon["keys"] == ["dragon"]

    def test_the_exported_payload_is_stable(self, client, session):
        """Exporting twice gives the same thing, and re-importing it does
        not change the state either time."""
        lb = _seed_lorebook(session)
        client.post(f"/api/v2/lorebooks/{lb.id}/import", json=ST_BOOK)

        first = client.get(f"/api/v2/lorebooks/{lb.id}/export").json()
        other = _seed_lorebook(session)
        client.post(f"/api/v2/lorebooks/{other.id}/import", json=first)
        second = client.get(f"/api/v2/lorebooks/{other.id}/export").json()

        def _state(payload):
            return {
                e["content"]: (
                    e["disable"],
                    e["keysecondary"],
                    e["selective"],
                    e["selectiveLogic"],
                    e["probability"],
                    e["depth"],
                    e["key"],
                )
                for e in payload["entries"].values()
            }

        assert _state(first) == _state(second)


class TestTheEntryStateIsEditable:
    def test_every_state_field_can_be_written(self, client, session):
        lb = _seed_lorebook(session)
        entry_id = client.post(
            f"/api/v2/lorebooks/{lb.id}/entries",
            json={"keys": ["a"], "content": "Original"},
        ).json()["id"]

        resp = client.put(
            f"/api/v2/lorebooks/{lb.id}/entries/{entry_id}",
            json={
                "enabled": False,
                "secondary_keys": ["b"],
                "case_sensitive": True,
                "selective_logic": "1",
                "probability": 25,
                "depth": 3,
                "category": "Category",
                "tags": ["one", "two"],
            },
        )
        assert resp.status_code == 200, resp.text

        entry = resp.json()
        assert entry["enabled"] is False
        assert entry["secondary_keys"] == ["b"]
        assert entry["case_sensitive"] is True
        assert entry["selective_logic"] == "1"
        assert entry["probability"] == 25
        assert entry["depth"] == 3
        assert entry["category"] == "Category"
        assert entry["tags"] == ["one", "two"]

    def test_a_disabled_entry_can_be_re_enabled(self, client, session):
        """The user-facing consequence of the import keeping `disabled`."""
        lb = _seed_lorebook(session)
        client.post(f"/api/v2/lorebooks/{lb.id}/import", json=ST_BOOK)
        entries = client.get(f"/api/v2/lorebooks/{lb.id}/entries").json()
        entry = _by_content(entries)["Dragons hoard gold."]

        resp = client.put(
            f"/api/v2/lorebooks/{lb.id}/entries/{entry['id']}",
            json={"enabled": True},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["enabled"] is True

    def test_the_keys_and_the_content_are_still_editable(self, client, session):
        """The fields that worked before must keep working."""
        lb = _seed_lorebook(session)
        entry_id = client.post(
            f"/api/v2/lorebooks/{lb.id}/entries",
            json={"keys": ["a"], "content": "Original"},
        ).json()["id"]

        resp = client.put(
            f"/api/v2/lorebooks/{lb.id}/entries/{entry_id}",
            json={"keys": ["x", "y"], "content": "Changed"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["keys"] == ["x", "y"]
        assert resp.json()["content"] == "Changed"

    def test_the_request_model_declares_every_field(self):
        from api.routes.world_vault.lorebooks import EntryUpdate

        fields = EntryUpdate.model_fields
        for name in (
            "keys",
            "content",
            "enabled",
            "secondary_keys",
            "case_sensitive",
            "selective_logic",
            "probability",
            "depth",
            "category",
            "tags",
        ):
            assert name in fields, f"{name} is unreachable through the API"
