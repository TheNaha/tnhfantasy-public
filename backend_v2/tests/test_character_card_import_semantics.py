"""What a card import actually DOES with the things it carries.

The card codec is byte-lossless: anything with no column is preserved in
`card_metadata` and written back on export. That is a good property and it
was sold as more than it was - the import report hardcoded `lost_fields: []`
and the UI turned that into "Fully compatible. All reported card data was
imported", while several SillyTavern features were preserved and never
executed.

These tests pin the behaviour, not the promises:

* a dangling `voice_model_id` used to crash the whole import with a 500;
* a `constant: true` lorebook entry became KEY-GATED, so it stopped
  firing at all;
* an `enabled: false` entry activated anyway;
* the card's `data.tags` (character metadata) landed in `visual_tags` (the
  image-generation tag list) and polluted the character's own prompts;
* `extensions.suggested_persona` was read from nowhere and preserved
  nowhere, so it was destroyed;
* a CHARX import reported itself as "json";
* and the report could not say which features were inert.
"""

import io
import json

import pytest
from PIL import Image, PngImagePlugin
from sqlmodel import select

import config as app_config
from core.entities import Character, LorebookEntry, VoiceModel


@pytest.fixture(autouse=True)
def _temp_avatar_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(app_config.settings, "character_avatar_dir", str(tmp_path / "characters"))


def _card_png(card: dict) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (4, 4), (128, 128, 128))
    meta = PngImagePlugin.PngInfo()
    meta.add_text("chara", base64_of(json.dumps(card)))
    img.save(buf, format="PNG", pnginfo=meta)
    return buf.getvalue()


def base64_of(text: str) -> str:
    import base64

    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _card(**overrides) -> dict:
    card = {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": {
            "name": "Ilse of the Bridge",
            "description": "A courier with a debt.",
            "personality": "Blunt, tired, honest.",
            "scenario": "The bridge burns behind her.",
            "first_mes": "You made it. Barely.",
        },
    }
    data = card["data"]
    data.update(overrides)
    return card


def _import(client, card: dict):
    resp = client.post(
        "/api/v2/characters/import",
        files={"file": ("card.png", _card_png(card), "image/png")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestDanglingVoiceModel:
    def test_a_card_naming_an_unknown_voice_model_still_imports(self, client, session):
        """It used to be a 500 that lost the whole character.

        `extensions.voice_model_id` was written straight into a foreign key.
        A card from another vault names a voice model this vault does not
        have, and the INSERT failed.
        """
        body = _import(
            client,
            _card(extensions={"voice_model_id": "does-not-exist"}),
        )

        char = session.get(Character, body["id"])
        assert char is not None, "the character was lost to a foreign key violation"
        assert char.voice_model_id is None

    def test_the_dropped_voice_model_is_reported(self, client):
        body = _import(
            client,
            _card(extensions={"voice_model_id": "does-not-exist"}),
        )
        lost = body["compatibility"]["lost_fields"]
        assert len(lost) == 1
        assert "voice_model_id" in lost[0]["field"]

    def test_a_voice_model_that_exists_is_kept(self, client, session):
        voice = VoiceModel(
            id="vm-1",
            name="Ilse",
            provider="local",
            model_path="/models/ilse.gguf",
            enabled=True,
        )
        session.add(voice)
        session.commit()

        body = _import(client, _card(extensions={"voice_model_id": "vm-1"}))
        char = session.get(Character, body["id"])
        assert char.voice_model_id == "vm-1"
        assert body["compatibility"]["lost_fields"] == []


class TestLorebookEntrySemantics:
    def _import_book(self, client, session, entry: dict):
        card = _card(
            character_book={
                "name": "Bridge lore",
                "entries": [entry],
            }
        )
        _import(client, card)
        entries = session.exec(select(LorebookEntry)).all()
        assert len(entries) == 1
        return entries[0]

    def test_a_constant_entry_is_always_on(self, client, session):
        """ST's `constant: true` means "always on", and it has keys.

        This vault's always-on test is a KEYLESS entry, so the flag was
        dropped on import and the entry became keyword-gated - it stopped
        firing unless the user happened to type one of its keys.
        """
        entry = self._import_book(
            client,
            session,
            {
                "keys": ["bridge"],
                "content": "The bridge is iron.",
                "constant": True,
                "enabled": True,
            },
        )
        assert entry.keys == [], "a constant entry must be always-on, and that means keyless"

    def test_a_disabled_entry_does_not_activate(self, client, session):
        """`enabled: false` was dropped on import, so it activated anyway."""
        entry = self._import_book(
            client,
            session,
            {
                "keys": ["bridge"],
                "content": "The bridge is iron.",
                "enabled": False,
            },
        )
        assert entry.enabled is False

        from services.rag_pipeline import entry_matches_keys

        assert entry_matches_keys(entry, "the bridge is iron") is False

    def test_a_disabled_keyless_entry_does_not_activate(self, client, session):
        """Even an always-on entry can be switched off."""
        entry = self._import_book(
            client,
            session,
            {"keys": [], "content": "Always true fact.", "enabled": False},
        )
        assert entry.enabled is False

        from services.rag_pipeline import entry_matches_keys

        assert entry_matches_keys(entry, "anything at all") is False

    def test_a_selective_entry_needs_a_secondary_key(self, client, session):
        entry = self._import_book(
            client,
            session,
            {
                "keys": ["bridge"],
                "secondary_keys": ["iron"],
                "content": "The bridge is iron.",
                "selective": True,
            },
        )
        assert entry.secondary_keys == ["iron"]

        from services.rag_pipeline import entry_matches_keys

        assert entry_matches_keys(entry, "cross the bridge") is False
        assert entry_matches_keys(entry, "the bridge is iron") is True

    def test_insertion_order_is_not_mapped_onto_depth(self, client, session):
        """`insertion_order` and `depth` are different concepts.

        ST's is where in the prompt the entry lands. This vault's `depth` is a
        scan depth that activation never reads. Mapping one onto the other
        made the value meaningless while looking meaningful.
        """
        entry = self._import_book(
            client,
            session,
            {
                "keys": ["bridge"],
                "content": "The bridge is iron.",
                "insertion_order": 2,
            },
        )
        # The default, not the ST value.
        assert entry.depth == 4
        # And the ST value survives the round trip in the residual blob.
        char = session.exec(select(Character)).first()
        book = char.card_metadata["data"]["character_book"]
        assert book["entries"][0]["insertion_order"] == 2


class TestTagListsStaySeparate:
    def test_the_cards_tags_do_not_reach_the_image_tag_column(self, client, session):
        """`data.tags` is character metadata. `visual_tags` is for images.

        They shared one column, so a card tagged "fantasy, elf" put "elf" into
        the character's own image prompts.
        """
        body = _import(client, _card(tags=["fantasy", "elf"]))
        char = session.get(Character, body["id"])
        assert char.visual_tags == []
        # And the card's own tags survive.
        assert char.card_metadata["data"]["tags"] == ["fantasy", "elf"]

    def test_the_cards_tags_are_written_back_on_export(self, client, session):
        body = _import(client, _card(tags=["fantasy", "elf"]))
        resp = client.get(f"/api/v2/characters/{body['id']}/export?format=json")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["tags"] == ["fantasy", "elf"]

    def test_the_visual_tag_extension_still_reaches_the_column(self, client, session):
        """The TNHComyu image-tag extension IS the column's home."""
        body = _import(
            client,
            _card(extensions={"visual_tags": ["1girl", "blonde"]}),
        )
        char = session.get(Character, body["id"])
        assert char.visual_tags == ["1girl", "blonde"]


class TestSuggestedPersona:
    def test_the_extension_is_not_destroyed(self, client, session):
        """It was in the "mapped extension" list, so it was excluded from the
        residual blob - but the column was only read from `data`, never from
        `extensions`. Read from nowhere, preserved nowhere: destroyed.
        """
        body = _import(
            client,
            _card(extensions={"suggested_persona": "A weary courier."}),
        )
        char = session.get(Character, body["id"])
        assert char.suggested_persona == "A weary courier."


class TestReportIsHonest:
    def test_a_charx_import_reports_charx(self, client):
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("card.json", json.dumps(_card()))
        resp = client.post(
            "/api/v2/characters/import",
            files={"file": ("card.charx", buf.getvalue(), "application/zip")},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["compatibility"]["format"] == "charx"

    def test_an_inert_feature_is_listed_with_its_reason(self, client):
        body = _import(
            client,
            _card(extensions={"regex_scripts": [{"scriptName": "strip"}]}),
        )
        report = body["compatibility"]
        inert = report["preserved_but_inert"]
        assert len(inert) == 1
        assert "regex_scripts" in inert[0]["name"]
        assert inert[0]["detail"], "an inert feature must say WHY it is inert"

    def test_an_inert_feature_is_not_reported_as_lossless(self, client):
        body = _import(
            client,
            _card(extensions={"regex_scripts": [{"scriptName": "strip"}]}),
        )
        assert body["compatibility"]["preserved_but_inert"]

    def test_a_clean_card_reports_nothing_lost(self, client):
        body = _import(client, _card())
        report = body["compatibility"]
        assert report["lost_fields"] == []
        assert report["preserved_but_inert"] == []


class TestAvatarDoesNotCarryTheCard:
    def test_the_stored_avatar_has_no_card_chunk(self, client, session):
        """The avatar PNG is served to every browser that loads it.

        It used to be the card PNG, so it also carried the whole character in
        a `chara` text chunk. The export writes its own chunks, so the
        re-exported card is unaffected.
        """
        import os

        from core.character_cards import parse_png_chunks

        body = _import(client, _card())
        char = session.get(Character, body["id"])
        assert char.avatar_path and os.path.exists(char.avatar_path)
        with open(char.avatar_path, "rb") as handle:
            chunks = parse_png_chunks(handle.read())
        assert "chara" not in chunks
        assert "ccv3" not in chunks

    def test_the_export_still_carries_the_card(self, client, session):
        from core.character_cards import parse_png_chunks

        body = _import(client, _card())
        resp = client.get(f"/api/v2/characters/{body['id']}/export")
        assert resp.status_code == 200, resp.text
        chunks = parse_png_chunks(resp.content)
        assert "chara" in chunks


class TestExpressions:
    """SillyTavern expression images, in both directions.

    A V3 card carries them in `data.assets` as base64. They were preserved
    as inert JSON and never turned into images, so `Character.expressions` was
    always empty after an import and an exported card never carried them back
    out.
    """

    def _png_bytes(self, colour=(200, 30, 30)) -> bytes:
        import io as _io

        from PIL import Image

        buf = _io.BytesIO()
        Image.new("RGB", (8, 8), colour).save(buf, format="PNG")
        return buf.getvalue()

    def _card_with_expressions(self, *emotions: str) -> dict:
        import base64

        return _card(
            assets=[
                {
                    "type": "expression",
                    "name": emotion,
                    "ext": "png",
                    "data": base64.b64encode(self._png_bytes()).decode("ascii"),
                }
                for emotion in emotions
            ]
        )

    def test_a_card_expression_becomes_a_real_expression_file(self, client, session):
        body = _import(client, self._card_with_expressions("happy", "angry"))
        char = session.get(Character, body["id"])

        assert set((char.expressions or {}).keys()) == {"happy", "angry"}
        for emotion, path in (char.expressions or {}).items():
            import os

            assert os.path.exists(path), f"the {emotion} expression file is missing"

    def test_the_image_is_actually_an_image(self, client, session):
        from PIL import Image

        body = _import(client, self._card_with_expressions("happy"))
        char = session.get(Character, body["id"])
        path = (char.expressions or {})["happy"]
        with Image.open(path) as image:
            assert image.size == (8, 8)

    def test_the_base64_is_not_carried_twice(self, client, session):
        """The images are materialised, so the residual does not keep them too."""
        body = _import(client, self._card_with_expressions("happy"))
        char = session.get(Character, body["id"])
        assets = char.card_metadata.get("data", {}).get("assets")
        assert not assets, (
            "the expression base64 is still in the residual after being "
            "written as a real expression file"
        )

    def test_an_export_carries_the_expressions_back(self, client, session):
        import base64

        body = _import(client, self._card_with_expressions("happy"))
        resp = client.get(f"/api/v2/characters/{body['id']}/export?format=json")
        assert resp.status_code == 200, resp.text
        assets = resp.json()["data"]["assets"]
        expression = next(a for a in assets if a.get("type") == "expression")
        assert expression["name"] == "happy"
        # The image really is in there, not just a name.
        assert base64.b64decode(expression["data"])[:4] == b"\x89PNG"

    def test_a_charx_export_carries_the_expression_as_an_archive_member(self, client, session):
        import io as _io
        import zipfile

        body = _import(client, self._card_with_expressions("happy"))
        resp = client.get(f"/api/v2/characters/{body['id']}/export?format=charx")
        assert resp.status_code == 200, resp.text
        with zipfile.ZipFile(_io.BytesIO(resp.content)) as archive:
            names = archive.namelist()
            assert "assets/expressions/happy.png" in names
            card = json.loads(archive.read("card.json"))
        expression = next(
            a
            for a in card["data"]["assets"]
            if a.get("type") == "expression"
        )
        # A CHARX references its assets by path rather than carrying base64.
        assert expression["data"] == "assets/expressions/happy.png"

    def test_a_character_with_no_expressions_exports_none(self, client, session):
        body = _import(client, _card())
        resp = client.get(f"/api/v2/characters/{body['id']}/export?format=json")
        assets = resp.json()["data"].get("assets") or []
        assert not [a for a in assets if a.get("type") == "expression"]


class TestTwoPhaseImport:
    """Analyze writes nothing; commit does the writing.

    The import used to write immediately, so the only way to find out what a
    card would do was to do it — and re-importing a card made a SECOND
    character with the same name, silently.
    """

    def _card(self, **overrides) -> bytes:
        import json as _json

        return _json.dumps(_card(**overrides)).encode("utf-8")

    def test_analyze_writes_nothing(self, client, session):
        from sqlmodel import select

        before = len(session.exec(select(Character)).all())
        resp = client.post(
            "/api/v2/characters/import/analyze",
            files={"file": ("card.json", self._card(), "application/json")},
        )
        assert resp.status_code == 200, resp.text
        assert len(session.exec(select(Character)).all()) == before, (
            "the analyze endpoint wrote a character"
        )

    def test_analyze_says_what_the_card_holds(self, client):
        resp = client.post(
            "/api/v2/characters/import/analyze",
            files={"file": ("card.json", self._card(), "application/json")},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "Ilse of the Bridge"
        assert body["description"] == "A courier with a debt."
        assert body["match"]["action"] == "create"
        # And the two scopes are offered.
        scope_ids = [s["id"] for s in body["scopes"]]
        assert scope_ids == ["character", "world"]

    def test_analyze_finds_the_character_a_card_identifies(self, client, session):
        char = _import(client, _card())
        card = client.get(f"/api/v2/characters/{char['id']}/export?format=json").content

        resp = client.post(
            "/api/v2/characters/import/analyze",
            files={"file": ("card.json", card, "application/json")},
        )
        assert resp.status_code == 200, resp.text
        match = resp.json()["match"]
        assert match["character_id"] == char["id"]
        assert match["action"] == "update"
        assert match["by"] == "identity"

    def test_commit_writes_the_character(self, client, session):
        from sqlmodel import select

        resp = client.post(
            "/api/v2/characters/import/commit",
            data={"scope": "character", "match_action": "auto"},
            files={"file": ("card.json", self._card(), "application/json")},
        )
        assert resp.status_code == 200, resp.text
        assert len(session.exec(select(Character)).all()) == 1

    def test_commit_updates_the_character_the_card_identifies(self, client, session):
        from sqlmodel import select

        char = _import(client, _card())
        card = client.get(f"/api/v2/characters/{char['id']}/export?format=json").content
        payload = json.loads(card)
        payload["data"]["description"] = "A courier with a much bigger debt."
        updated = json.dumps(payload).encode("utf-8")

        resp = client.post(
            "/api/v2/characters/import/commit",
            data={"scope": "character", "match_action": "auto"},
            files={"file": ("card.json", updated, "application/json")},
        )
        assert resp.status_code == 200, resp.text
        assert len(session.exec(select(Character)).all()) == 1, "the commit duplicated the character"
        assert resp.json()["description"] == "A courier with a much bigger debt."

    def test_commit_can_force_a_new_character(self, client, session):
        from sqlmodel import select

        char = _import(client, _card())
        card = client.get(f"/api/v2/characters/{char['id']}/export?format=json").content

        resp = client.post(
            "/api/v2/characters/import/commit",
            data={"scope": "character", "match_action": "create"},
            files={"file": ("card.json", card, "application/json")},
        )
        assert resp.status_code == 200, resp.text
        assert len(session.exec(select(Character)).all()) == 2, (
            "an explicit 'create' did not create a second character"
        )
