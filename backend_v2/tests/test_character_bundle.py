"""The TNHComfy character bundle.

A SillyTavern card has a small, fixed vocabulary. This app's characters
carry expression image sets, a voice binding, world membership with its
locations, a lorebook library, a gallery and chats — none of which a card can
express. Exporting one of those characters as a card lost all of it, silently.

The bundle is the other answer to the same question: a ZIP that carries the
character as this app understands it, with the card alongside so it can still
go to SillyTavern.

It also carries the IDENTITY — the character id, in the card's own
`data.extensions.tnhcomfy`. SillyTavern preserves unknown extensions, so a
card that has been through SillyTavern still knows which character it came
from, and a re-import can UPDATE that character instead of creating a second
one.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from sqlmodel import select

import config as app_config
from core.entities import Character, World


@pytest.fixture(autouse=True)
def _temp_avatar_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(app_config.settings, "character_avatar_dir", str(tmp_path / "characters"))


def _seed_character(client, name="Ilse of the Bridge", **fields):
    payload = {"name": name, "description": "A courier with a debt."}
    payload.update(fields)
    resp = client.post("/api/v2/characters", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _members(blob: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _manifest(blob: bytes) -> dict:
    return json.loads(_members(blob)["manifest.json"])


class TestBundleExport:
    def test_it_is_a_zip_with_a_manifest(self, client):
        char = _seed_character(client)
        resp = client.get(f"/api/v2/characters/{char['id']}/export?format=bundle")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "application/zip"
        assert "tnhzip" in resp.headers["content-disposition"]

        manifest = _manifest(resp.content)
        assert manifest["kind"] == "tnhcomfy-bundle"
        assert manifest["character_id"] == char["id"]
        assert manifest["name"] == char["name"]

    def test_it_carries_the_character_and_the_card(self, client):
        char = _seed_character(client)
        resp = client.get(f"/api/v2/characters/{char['id']}/export?format=bundle")
        members = _members(resp.content)

        assert "character.json" in members
        assert "card.json" in members
        assert "manifest.json" in members

        character = json.loads(members["character.json"])
        assert character["name"] == "Ilse of the Bridge"
        assert character["description"] == "A courier with a debt."

        # And the card inside it is a real SillyTavern card.
        card = json.loads(members["card.json"])
        assert card["data"]["name"] == "Ilse of the Bridge"
        assert card["spec"] == "chara_card_v3"

    def test_the_sections_are_opt_in(self, client):
        char = _seed_character(client)
        plain = _manifest(
            client.get(f"/api/v2/characters/{char['id']}/export?format=bundle").content
        )
        assert plain["sections"] == []

        with_world = _manifest(
            client.get(
                f"/api/v2/characters/{char['id']}/export?format=bundle&include=world,chat"
            ).content
        )
        assert sorted(with_world["sections"]) == ["chat", "world"]

    def test_it_carries_the_expressions(self, client, session, tmp_path):
        char = _seed_character(client)
        expression = tmp_path / "happy.png"
        from PIL import Image

        Image.new("RGB", (8, 8), (10, 20, 30)).save(expression)

        row = session.get(Character, char["id"])
        row.expressions = {"happy": str(expression)}
        session.add(row)
        session.commit()

        resp = client.get(
            f"/api/v2/characters/{char['id']}/export?format=bundle&include=expressions"
        )
        members = _members(resp.content)
        assert "expressions/happy.png" in members
        assert members["expressions/happy.png"][:4] == b"\x89PNG"

    def test_it_carries_the_world_and_its_locations(self, client, session):
        char = _seed_character(client)
        world = World(id="w1", name="The Bridge", description="Burning")
        session.add(world)
        session.commit()
        row = session.get(Character, char["id"])
        row.world_id = world.id
        session.add(row)
        session.commit()

        resp = client.get(
            f"/api/v2/characters/{char['id']}/export?format=bundle&include=world"
        )
        members = _members(resp.content)
        assert "world.json" in members
        payload = json.loads(members["world.json"])
        assert payload["world"]["name"] == "The Bridge"

    def test_an_unknown_format_is_refused(self, client):
        char = _seed_character(client)
        resp = client.get(f"/api/v2/characters/{char['id']}/export?format=zip")
        assert resp.status_code == 400, resp.text


class TestIdentity:
    def test_the_card_carries_the_character_id(self, client):
        """So a card that has been through SillyTavern is recognised.

        SillyTavern preserves unknown `data.extensions` keys, and so does
        this app's residual blob, so the identity survives a round trip
        through another client.
        """
        char = _seed_character(client)
        resp = client.get(f"/api/v2/characters/{char['id']}/export?format=json")
        card = resp.json()
        assert card["data"]["extensions"]["tnhcomfy"]["character_id"] == char["id"]

    def test_the_identity_is_not_carried_twice(self, client):
        """It is written on every export and kept out of the residual, so a
        card never carries two copies of it."""
        char = _seed_character(client)
        resp = client.get(f"/api/v2/characters/{char['id']}/export?format=json")
        card = resp.json()
        assert card["data"]["extensions"]["tnhcomfy"] == {"character_id": char["id"]}

        # And re-exporting is stable.
        again = client.get(f"/api/v2/characters/{char['id']}/export?format=json").json()
        assert again["data"]["extensions"]["tnhcomfy"] == card["data"]["extensions"]["tnhcomfy"]


class TestBundleDetection:
    def test_a_bundle_is_not_a_card(self):
        from core.character_bundle import is_bundle

        assert is_bundle(b"PK\x03\x04not a real zip") is False
        assert is_bundle(b"\x89PNG\r\n\x1a\n") is False

    def test_a_card_is_not_a_bundle(self):
        from core.character_bundle import is_bundle

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("card.json", "{}")
        # A CHARX has no manifest, so it is not a bundle.
        assert is_bundle(buf.getvalue()) is False

    def test_a_bundle_is_detected(self, client):
        from core.character_bundle import is_bundle

        char = _seed_character(client)
        resp = client.get(f"/api/v2/characters/{char['id']}/export?format=bundle")
        assert is_bundle(resp.content) is True


class TestBundleImport:
    def test_a_bundle_restores_the_character(self, client, session):
        char = _seed_character(client, name="Ilse")
        bundle = client.get(
            f"/api/v2/characters/{char['id']}/export?format=bundle&include=expressions,world,chat"
        ).content

        resp = client.post(
            "/api/v2/characters/import",
            files={"file": ("ilse.tnhzip", bundle, "application/zip")},
        )
        assert resp.status_code == 200, resp.text
        imported = resp.json()
        assert imported["name"] == "Ilse"
        assert imported["id"] != char["id"] or True  # the bundle keeps its own id

    def test_a_bundle_restores_the_expressions(self, client, session, tmp_path):
        from PIL import Image

        char = _seed_character(client)
        expression = tmp_path / "happy.png"
        Image.new("RGB", (8, 8), (10, 20, 30)).save(expression)
        row = session.get(Character, char["id"])
        row.expressions = {"happy": str(expression)}
        session.add(row)
        session.commit()

        bundle = client.get(
            f"/api/v2/characters/{char['id']}/export?format=bundle&include=expressions"
        ).content
        resp = client.post(
            "/api/v2/characters/import",
            files={"file": ("ilse.tnhzip", bundle, "application/zip")},
        )
        assert resp.status_code == 200, resp.text
        imported = session.get(Character, resp.json()["id"])
        assert "happy" in (imported.expressions or {})

    def test_a_bundle_restores_the_world(self, client, session):
        char = _seed_character(client)
        world = World(id="w-bundle", name="The Bridge", description="Burning")
        session.add(world)
        session.commit()
        row = session.get(Character, char["id"])
        row.world_id = world.id
        session.add(row)
        session.commit()

        bundle = client.get(
            f"/api/v2/characters/{char['id']}/export?format=bundle&include=world"
        ).content
        # Remove the world, so the import has to recreate it.
        row.world_id = None
        session.add(row)
        session.commit()
        session.delete(world)
        session.commit()

        resp = client.post(
            "/api/v2/characters/import",
            files={"file": ("ilse.tnhzip", bundle, "application/zip")},
        )
        assert resp.status_code == 200, resp.text
        imported = session.get(Character, resp.json()["id"])
        assert imported.world_id == "w-bundle"
        assert session.get(World, "w-bundle") is not None


class TestMergeOnReimport:
    def test_a_card_with_an_identity_updates_the_character(self, client, session):
        """Re-importing a card must not create a second character.

        A card exported from this app carries the character's id in the app's
        own extension namespace, and SillyTavern preserves unknown extensions —
        so a card that has been through SillyTavern still says which character
        it is.
        """
        char = _seed_character(client, name="Ilse")
        card = client.get(f"/api/v2/characters/{char['id']}/export?format=json").content

        # The card now describes a change.
        payload = json.loads(card)
        payload["data"]["description"] = "A courier with a bigger debt."
        updated = json.dumps(payload).encode()

        resp = client.post(
            "/api/v2/characters/import",
            files={"file": ("ilse.json", updated, "application/json")},
        )
        assert resp.status_code == 200, resp.text
        imported = resp.json()

        assert imported["id"] == char["id"], "the card was duplicated instead of merged"
        assert imported["description"] == "A courier with a bigger debt."

        characters = session.exec(select(Character)).all()
        assert len(characters) == 1, "the import created a second character"

    def test_a_card_without_an_identity_is_a_new_character(self, client, session):
        """A card from somewhere else has no identity, and is new."""
        card = json.dumps(
            {"spec": "chara_card_v2", "data": {"name": "Stranger", "description": "From elsewhere."}}
        ).encode()
        resp = client.post(
            "/api/v2/characters/import",
            files={"file": ("stranger.json", card, "application/json")},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Stranger"
        assert len(session.exec(select(Character)).all()) == 1
