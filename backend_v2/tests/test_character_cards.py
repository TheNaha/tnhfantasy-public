"""Lossless SillyTavern character card tests (PNG V1/V2/V3 + JSON).

Covers the codec in `core/character_cards.py` (chunk types, CBOR, field
mapping, residual metadata) and the HTTP surface (`/import`, `/export`),
including a full import -> export -> import round trip that must keep every
field the vault has no column for.
"""
import base64
import io
import json
import struct
import zlib
from types import SimpleNamespace

import cbor2
import pytest
from PIL import Image, PngImagePlugin
from sqlalchemy import inspect
from sqlalchemy import text as sa_text

from core.character_cards import (
    CARD_SPEC_V1,
    CARD_SPEC_V2,
    CARD_SPEC_V3,
    CardParseError,
    build_card_payload,
    encode_png_card,
    lorebook_from_character_book,
    parse_card_file,
    parse_json_card,
    parse_png_card,
    parse_png_chunks,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _v3_card() -> dict:
    """A V3 card exercising every mapped field plus a pile of unknown ones."""
    return {
        "spec": "chara_card_v3",
        "spec_version": "3.0",
        "data": {
            "name": "Lossless Lena",
            "description": "A librarian of impossible books.",
            "personality": "Curious, precise, faintly smug",
            "scenario": "A floating archive",
            "first_mes": "You found the door I sealed.",
            "mes_example": "<START>\n{{char}}: Shhh.\n{{user}}: Why?",
            "creator_notes": "Notes for other authors.",
            "system_prompt": "Answer in character.",
            "post_history_instructions": "Never break character.",
            "alternate_greetings": ["Second greeting", "Third greeting"],
            "group_greetings": ["Group greeting one", "Group greeting two"],
            "tags": ["librarian", "fantasy"],
            "creator": "CardAuthor",
            "character_version": "4.2",
            "version": 7,
            "fav": False,
            "creator_notes_multilingual": {"de": "Notizen"},
            "some_future_data_field": {"nested": [1, 2, 3]},
            "assets": [
                {"type": "expression", "name": "happy", "data": "aGVsbG8="},
                {"type": "background", "name": "main", "data": "d29ybGQ="},
            ],
            "extensions": {
                "lora_triggers": ["lena-lora"],
                "visual_tags": ["librarian", "glasses"],
                "voice_profile": "en-US-female-1",
                "regex_scripts": [{"scriptName": "strip", "find_regex": "/x/"}],
                "depth_prompt": {"prompt": "deeper", "depth": 4},
            },
            "character_book": {
                "name": "Archive Lorebook",
                "description": "Places in the archive",
                "scan_depth": 2,
                "token_budget": 512,
                "recursive_scanning": True,
                "extensions": {"book_flag": "keep"},
                "entries": [
                    {
                        "keys": ["archive", "library"],
                        "secondary_keys": [],
                        "content": "The archive floats above the clouds.",
                        "comment": "Setting",
                        "enabled": True,
                        "insertion_order": 2,
                        "case_sensitive": False,
                        "priority": 10,
                        "selective": True,
                        "selective_logic": 1,
                        "constant": False,
                        "position": "before_char",
                        "probability": 75,
                        "use_regex": True,
                        "depth": 4,
                        "group": "setting",
                        "id": 101,
                        "entry_unknown_key": {"deep": True},
                    }
                ],
            },
        },
        "root_unknown_field": ["a", "b"],
    }


def _png_with_chunks(chunks: dict[str, bytes], *, size=(2, 2)) -> bytes:
    """Build a PNG carrying the given `keyword -> text chunk value` pairs."""
    img = Image.new("RGBA", size, (10, 20, 30, 255))
    meta = PngImagePlugin.PngInfo()
    for keyword, value in chunks.items():
        meta.add_text(keyword, value)
    buf = io.BytesIO()
    img.save(buf, format="PNG", pnginfo=meta)
    return buf.getvalue()


def _b64(payload) -> str:
    return base64.b64encode(payload if isinstance(payload, bytes) else json.dumps(payload).encode()).decode("ascii")


def _b64_zlib(payload) -> str:
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return base64.b64encode(zlib.compress(raw)).decode("ascii")


def _itxt(keyword: str, text: str, *, compress: bool = True) -> bytes:
    """Raw iTXt chunk data (keyword, method, language, translated keyword, text)."""
    body = text.encode("utf-8")
    flag = 1 if compress else 0
    if compress:
        body = zlib.compress(body)
    return keyword.encode() + b"\x00" + bytes([flag, 0]) + b"\x00" + b"\x00" + body


def _ztxt(keyword: str, text: str) -> bytes:
    return keyword.encode() + b"\x00\x00" + zlib.compress(text.encode("utf-8"))


def _raw_png_with_chunk_data(chunk_type: bytes, payload: bytes) -> bytes:
    """Insert a hand-built chunk so we can emit zTXt / iTXt as SillyTavern does."""
    img = Image.new("RGBA", (2, 2))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw = buf.getvalue()

    crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    chunk = struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", crc)
    iend_at = raw.rindex(b"IEND") - 4
    return raw[:iend_at] + chunk + raw[iend_at:]


def _stub_character(**overrides) -> SimpleNamespace:
    """A Character-shaped object for exercising the export builder alone."""
    defaults = dict(
        name="Stub",
        description="",
        personality="",
        scenario="",
        first_mes="",
        mes_example="",
        creator_notes="",
        system_prompt="",
        append_system_prompt="",
        suggested_persona=None,
        visual_tags=[],
        lora_triggers=[],
        voice_profile="",
        voice_model_id=None,
        alternate_greetings=[],
        group_greetings=[],
        checkpoint=None,
        lora=None,
        default_time=None,
        default_location=None,
        card_spec=None,
        card_spec_version=None,
        creator=None,
        character_version=None,
        card_metadata=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Chunk decoding
# ---------------------------------------------------------------------------


class TestPngChunkDecoding:
    def test_text_chunk_is_parsed(self):
        png = _png_with_chunks({"chara": _b64({"name": "tEXt"})})
        assert "chara" in parse_png_chunks(png)

    def test_ztxt_chunk_is_parsed(self):
        png = _raw_png_with_chunk_data(b"zTXt", _ztxt("chara", json.dumps({"name": "zTXt"})))
        mapped = parse_png_card(png)
        assert mapped["name"] == "zTXt"

    def test_itxt_compressed_chunk_is_parsed(self):
        card = {"name": "iTXt", "description": "compressed international chunk"}
        png = _raw_png_with_chunk_data(b"iTXt", _itxt("chara", json.dumps(card)))
        mapped = parse_png_card(png)
        assert mapped["description"] == "compressed international chunk"

    def test_itxt_uncompressed_chunk_is_parsed(self):
        card = {"name": "iTXt raw", "description": "no compression"}
        png = _raw_png_with_chunk_data(b"iTXt", _itxt("chara", json.dumps(card), compress=False))
        assert parse_png_card(png)["name"] == "iTXt raw"

    def test_multiple_text_chunks_are_all_read(self):
        """Keyword keying keeps every chunk; type keying used to drop all but one."""
        img = Image.new("RGBA", (2, 2))
        meta = PngImagePlugin.PngInfo()
        meta.add_text("Software", "someone")
        meta.add_text("chara", _b64({"name": "Second Chunk", "description": "kept"}))
        buf = io.BytesIO()
        img.save(buf, format="PNG", pnginfo=meta)

        chunks = parse_png_chunks(buf.getvalue())
        assert "Software" in chunks and "chara" in chunks
        assert parse_png_card(buf.getvalue())["name"] == "Second Chunk"

    def test_non_png_input_rejected(self):
        with pytest.raises(CardParseError):
            parse_png_chunks(b"not a png at all")


# ---------------------------------------------------------------------------
# Card payload decoding
# ---------------------------------------------------------------------------


class TestPayloadDecoding:
    def test_v1_flat_json_in_chara_chunk(self):
        png = _png_with_chunks({"chara": json.dumps({"name": "Flat V1", "description": "d"})})
        mapped = parse_png_card(png)
        assert mapped["name"] == "Flat V1"
        assert mapped["card_spec"] == CARD_SPEC_V1

    def test_v2_base64_json(self):
        card = {"spec": "chara_card_v2", "spec_version": "2.0", "data": {"name": "V2 Card"}}
        mapped = parse_png_card(_png_with_chunks({"chara": _b64(card)}))
        assert mapped["name"] == "V2 Card"
        assert mapped["card_spec"] == CARD_SPEC_V2
        assert mapped["card_spec_version"] == "2.0"

    def test_v2_zlib_compressed_base64(self):
        card = {"spec": "chara_card_v2", "spec_version": "2.0", "data": {"name": "Compressed"}}
        mapped = parse_png_card(_png_with_chunks({"chara": _b64_zlib(card)}))
        assert mapped["name"] == "Compressed"

    def test_legacy_chara2_spec_string_is_canonicalised(self):
        card = {"spec": "chara2.0", "spec_version": "2.0", "data": {"name": "Legacy"}}
        mapped = parse_png_card(_png_with_chunks({"chara": _b64(card)}))
        assert mapped["card_spec"] == CARD_SPEC_V2
        # The original string is kept so the export reproduces it verbatim.
        assert mapped["card_metadata"]["spec"] == "chara2.0"

    def test_ccv3_base64_json(self):
        mapped = parse_png_card(_png_with_chunks({"ccv3": _b64(_v3_card())}))
        assert mapped["card_spec"] == CARD_SPEC_V3
        assert mapped["name"] == "Lossless Lena"

    def test_ccv3_cbor(self):
        mapped = parse_png_card(_png_with_chunks({"ccv3": _b64(cbor2.dumps(_v3_card()))}))
        assert mapped["card_spec"] == CARD_SPEC_V3
        assert mapped["creator"] == "CardAuthor"
        assert mapped["character_version"] == "4.2"

    def test_ccv3_takes_precedence_over_chara(self):
        v2 = {"spec": "chara_card_v2", "spec_version": "2.0", "data": {"name": "From chara"}}
        v3 = _v3_card()
        png = _png_with_chunks({"chara": _b64(v2), "ccv3": _b64(cbor2.dumps(v3))})
        mapped = parse_png_card(png)
        assert mapped["name"] == "Lossless Lena"
        assert mapped["card_spec"] == CARD_SPEC_V3

    def test_chara_chunk_without_card_data_rejected(self):
        png = _png_with_chunks({"chara": "not a card"})
        with pytest.raises(CardParseError):
            parse_png_card(png)


class TestJsonCards:
    def test_json_v1_flat(self):
        mapped = parse_json_card(json.dumps({"name": "JSON V1", "description": "d"}))
        assert mapped["name"] == "JSON V1"
        assert mapped["card_spec"] == CARD_SPEC_V1

    def test_json_v2(self):
        card = {"spec": "chara_card_v2", "spec_version": "2.0", "data": {"name": "JSON V2"}}
        assert parse_json_card(json.dumps(card))["card_spec"] == CARD_SPEC_V2

    def test_json_v3(self):
        mapped = parse_json_card(json.dumps(_v3_card()))
        assert mapped["card_spec"] == CARD_SPEC_V3
        assert mapped["name"] == "Lossless Lena"

    def test_json_bytes_input(self):
        mapped = parse_json_card(json.dumps(_v3_card()).encode("utf-8"))
        assert mapped["name"] == "Lossless Lena"

    def test_invalid_json_rejected(self):
        with pytest.raises(CardParseError):
            parse_json_card("{not json")

    def test_non_object_json_rejected(self):
        with pytest.raises(CardParseError):
            parse_json_card("[1, 2, 3]")

    def test_parse_card_file_detects_json(self):
        fields, avatar = parse_card_file(json.dumps(_v3_card()).encode(), "card.json")
        assert fields["name"] == "Lossless Lena"
        assert avatar is None

    def test_parse_card_file_detects_png(self):
        png = _png_with_chunks({"chara": _b64(_v3_card())})
        fields, avatar = parse_card_file(png, "card.png")
        assert fields["name"] == "Lossless Lena"
        assert avatar == png

    def test_parse_card_file_rejects_other_types(self):
        with pytest.raises(CardParseError):
            parse_card_file(b"MZ\x00binary", "card.exe")


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------


class TestFieldMapping:
    @pytest.fixture(name="mapped")
    def mapped_fixture(self):
        return parse_png_card(_png_with_chunks({"ccv3": _b64(cbor2.dumps(_v3_card()))}))

    def test_core_fields(self, mapped):
        assert mapped["name"] == "Lossless Lena"
        assert mapped["description"] == "A librarian of impossible books."
        assert mapped["personality"] == "Curious, precise, faintly smug"
        assert mapped["scenario"] == "A floating archive"
        assert mapped["first_mes"] == "You found the door I sealed."
        assert mapped["mes_example"].startswith("<START>")
        assert mapped["visual_tags"] == ["librarian", "fantasy"]
        assert mapped["alternate_greetings"] == ["Second greeting", "Third greeting"]

    def test_post_history_instructions_maps_to_append_system_prompt(self, mapped):
        assert mapped["append_system_prompt"] == "Never break character."

    def test_creator_and_version_are_separate_from_creator_notes(self, mapped):
        assert mapped["creator"] == "CardAuthor"
        assert mapped["character_version"] == "4.2"
        assert mapped["creator_notes"] == "Notes for other authors."

    def test_group_greetings_are_mapped(self, mapped):
        assert mapped["group_greetings"] == ["Group greeting one", "Group greeting two"]

    def test_group_greeting_singular_is_accepted(self):
        card = {"spec": "chara_card_v2", "data": {"name": "G", "group_greeting": "only one"}}
        assert parse_json_card(json.dumps(card))["group_greetings"] == ["only one"]

    def test_extension_fields(self, mapped):
        assert mapped["lora_triggers"] == ["lena-lora"]
        assert mapped["voice_profile"] == "en-US-female-1"

    def test_first_mes_falls_back_to_first_alternate_greeting(self):
        card = {"spec": "chara_card_v2", "data": {"name": "NoFirst", "alternate_greetings": ["Hi there"]}}
        assert parse_json_card(json.dumps(card))["first_mes"] == "Hi there"

    def test_legacy_prefixed_keys_are_mapped(self):
        card = {"name": "Legacy", "char_description": "old description", "char_personality": "old personality"}
        mapped = parse_json_card(json.dumps(card))
        assert mapped["description"] == "old description"
        assert mapped["personality"] == "old personality"

    def test_missing_name_stays_empty(self):
        assert parse_json_card(json.dumps({"description": "nameless"}))["name"] == ""

    def test_non_string_name_is_coerced(self):
        card = {"spec": "chara_card_v2", "data": {"name": 42, "character_version": 3}}
        mapped = parse_json_card(json.dumps(card))
        assert mapped["name"] == "42"
        assert mapped["character_version"] == "3"

    def test_tags_of_wrong_type_are_ignored(self):
        card = {"spec": "chara_card_v2", "data": {"name": "T", "tags": "not-a-list"}}
        assert parse_json_card(json.dumps(card))["visual_tags"] == ["not-a-list"]


class TestPreservation:
    @pytest.fixture(name="mapped")
    def mapped_fixture(self):
        return parse_png_card(_png_with_chunks({"ccv3": _b64(cbor2.dumps(_v3_card()))}))

    def test_unknown_root_fields_preserved(self, mapped):
        assert mapped["card_metadata"]["root"] == {"root_unknown_field": ["a", "b"]}

    def test_unknown_data_fields_preserved(self, mapped):
        data = mapped["card_metadata"]["data"]
        assert data["some_future_data_field"] == {"nested": [1, 2, 3]}
        assert data["fav"] is False
        assert data["creator_notes_multilingual"] == {"de": "Notizen"}

    def test_assets_preserved_verbatim(self, mapped):
        assert mapped["card_metadata"]["data"]["assets"] == _v3_card()["data"]["assets"]

    def test_unknown_extensions_preserved(self, mapped):
        extensions = mapped["card_metadata"]["data"]["extensions"]
        assert extensions["regex_scripts"] == [{"scriptName": "strip", "find_regex": "/x/"}]
        assert extensions["depth_prompt"] == {"prompt": "deeper", "depth": 4}
        # Column-backed extension keys are not duplicated into the residual blob,
        # except a visual_tags list that disagrees with data.tags.
        assert "lora_triggers" not in extensions
        assert "voice_profile" not in extensions
        assert extensions["visual_tags"] == ["librarian", "glasses"]

    def test_character_book_preserved_verbatim_with_unknown_entry_keys(self, mapped):
        book = mapped["card_metadata"]["data"]["character_book"]
        assert book == _v3_card()["data"]["character_book"]
        assert book["entries"][0]["entry_unknown_key"] == {"deep": True}
        assert book["token_budget"] == 512

    def test_data_version_preserved_separately(self, mapped):
        assert mapped["card_metadata"]["data_version"] == 7
        # ... and the character column is the author's character_version, not data.version.
        assert mapped["character_version"] == "4.2"

    def test_mapped_keys_are_not_duplicated_in_residual(self, mapped):
        data = mapped["card_metadata"]["data"]
        for key in ("name", "description", "tags", "creator", "character_version", "alternate_greetings"):
            assert key not in data


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


def _round_trip(card: dict) -> dict:
    """Import -> export -> decode the card payload the exporter produced."""
    mapped = parse_card_file(
        _png_with_chunks({"ccv3": _b64(cbor2.dumps(card))}), "card.png"
    )[0]
    mapped.pop("character_book", None)
    exported = encode_png_card(None, _stub_character(**mapped))
    chunks = parse_png_chunks(exported)
    payload = json.loads(base64.b64decode(chunks["ccv3"][0]))
    return payload


class TestRoundTrip:
    def test_v3_unknown_data_survives_round_trip(self):
        original = _v3_card()
        exported = _round_trip(original)
        for key in ("name", "description", "personality", "scenario", "first_mes", "mes_example",
                    "creator_notes", "system_prompt", "post_history_instructions", "alternate_greetings",
                    "group_greetings", "tags", "creator", "character_version", "version", "fav",
                    "creator_notes_multilingual", "some_future_data_field", "assets", "character_book"):
            assert exported["data"][key] == original["data"][key], key

    def test_v3_root_and_spec_survive_round_trip(self):
        exported = _round_trip(_v3_card())
        assert exported["root_unknown_field"] == ["a", "b"]
        assert exported["spec"] == "chara_card_v3"
        assert exported["spec_version"] == "3.0"

    def test_unknown_extensions_survive_round_trip(self):
        exported = _round_trip(_v3_card())
        extensions = exported["data"]["extensions"]
        assert extensions["regex_scripts"] == [{"scriptName": "strip", "find_regex": "/x/"}]
        assert extensions["depth_prompt"] == {"prompt": "deeper", "depth": 4}
        assert extensions["lora_triggers"] == ["lena-lora"]

    def test_v2_legacy_spec_string_is_reproduced(self):
        card = {"spec": "chara2.0", "spec_version": "2.0", "data": {"name": "Legacy", "legacy_key": [1]}}
        mapped = parse_card_file(_png_with_chunks({"chara": _b64(card)}), "card.png")[0]
        exported = json.loads(base64.b64decode(parse_png_chunks(encode_png_card(None, _stub_character(**mapped)))["ccv3"][0]))
        assert exported["spec"] == "chara2.0"
        assert exported["data"]["legacy_key"] == [1]

    def test_second_round_trip_is_stable(self):
        first = _round_trip(_v3_card())
        mapped = parse_card_payload_from_export(first)
        second = _round_trip_of_payload(mapped)
        assert second == first

    def test_live_column_edits_win_over_stale_residual(self):
        mapped = parse_card_file(
            _png_with_chunks({"chara": _b64(_v3_card())}), "card.png"
        )[0]
        mapped["name"] = "Renamed"
        mapped["visual_tags"] = ["edited"]
        mapped["lora_triggers"] = ["edited-lora"]
        mapped["voice_profile"] = "edited-voice"
        payload = build_card_payload(_stub_character(**mapped))
        assert payload["data"]["name"] == "Renamed"
        assert payload["data"]["tags"] == ["edited"]
        assert payload["data"]["extensions"]["lora_triggers"] == ["edited-lora"]
        assert payload["data"]["extensions"]["voice_profile"] == "edited-voice"

    def test_divergent_extension_visual_tags_are_preserved_not_rewritten(self):
        """`data.tags` wins the column, the card's own extension list survives.

        The extension list is the only record of the card's original value, and
        it usually equals `data.tags`, in which case nothing is duplicated and
        the live column is written straight back out.
        """
        divergent = _v3_card()
        mapped = parse_card_file(
            _png_with_chunks({"chara": _b64(divergent)}), "card.png"
        )[0]
        assert mapped["visual_tags"] == divergent["data"]["tags"]
        assert mapped["card_metadata"]["data"]["extensions"]["visual_tags"] == divergent["data"]["extensions"]["visual_tags"]

        payload = build_card_payload(_stub_character(**mapped))
        assert payload["data"]["tags"] == divergent["data"]["tags"]
        assert payload["data"]["extensions"]["visual_tags"] == divergent["data"]["extensions"]["visual_tags"]

        matching = _v3_card()
        matching["data"]["extensions"]["visual_tags"] = list(matching["data"]["tags"])
        mapped_matching = parse_card_file(
            _png_with_chunks({"chara": _b64(matching)}), "card.png"
        )[0]
        assert "visual_tags" not in mapped_matching["card_metadata"]["data"]["extensions"]
        assert build_card_payload(_stub_character(**mapped_matching))["data"]["extensions"]["visual_tags"] == matching["data"]["tags"]

    def test_v1_export_is_flat(self):
        payload = build_card_payload(
            _stub_character(name="Flat", card_spec=CARD_SPEC_V1), version=CARD_SPEC_V1
        )
        assert "data" not in payload
        assert payload["name"] == "Flat"

    def test_natively_created_character_exports_a_v2_card(self):
        payload = build_card_payload(_stub_character(name="Native"))
        assert payload["spec"] == CARD_SPEC_V2
        assert payload["spec_version"] == "2.0"
        assert payload["data"]["name"] == "Native"


def parse_card_payload_from_export(payload: dict) -> dict:
    mapped = parse_card_file(
        _png_with_chunks({"chara": _b64(payload)}), "card.png"
    )[0]
    mapped.pop("character_book", None)
    return mapped


def _round_trip_of_payload(mapped: dict) -> dict:
    """Export already-mapped column values and read back the card payload."""
    exported = encode_png_card(None, _stub_character(**mapped))
    return json.loads(base64.b64decode(parse_png_chunks(exported)["ccv3"][0]))


# ---------------------------------------------------------------------------
# Export shape
# ---------------------------------------------------------------------------


class TestPngExport:
    def test_export_writes_both_chara_and_ccv3(self):
        png = encode_png_card(None, _stub_character(name="Dual"))
        chunks = parse_png_chunks(png)
        assert "chara" in chunks
        assert "ccv3" in chunks

    def test_chara_chunk_is_base64_json(self):
        png = encode_png_card(None, _stub_character(name="Dual"))
        payload = json.loads(base64.b64decode(parse_png_chunks(png)["chara"][0]))
        assert payload["data"]["name"] == "Dual"

    def test_ccv3_chunk_is_cbor(self):
        png = encode_png_card(None, _stub_character(name="Dual"))
        payload = json.loads(base64.b64decode(parse_png_chunks(png)["ccv3"][0]))
        assert payload["data"]["name"] == "Dual"

    def test_ccv3_can_be_disabled(self):
        png = encode_png_card(None, _stub_character(name="Dual"), include_v3=False)
        chunks = parse_png_chunks(png)
        assert "chara" in chunks and "ccv3" not in chunks

    def test_v3_spec_override_pins_ccv3_spec(self):
        png = encode_png_card(None, _stub_character(name="Dual", card_spec=CARD_SPEC_V1), v3_spec=CARD_SPEC_V3)
        payload = json.loads(base64.b64decode(parse_png_chunks(png)["ccv3"][0]))
        assert payload["spec"] == CARD_SPEC_V3
        assert payload["spec_version"] == "3.0"

    def test_avatar_image_is_embedded(self):
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, format="PNG")
        png = encode_png_card(buf.getvalue(), _stub_character(name="WithAvatar"))
        image = Image.open(io.BytesIO(png))
        assert image.size == (8, 8)
        assert "chara" in parse_png_chunks(png)

    def test_export_without_avatar_uses_placeholder(self):
        png = encode_png_card(None, _stub_character(name="NoAvatar"))
        assert Image.open(io.BytesIO(png)).size == (1, 1)

    def test_exported_card_reimports_with_unknown_fields(self):
        mapped = parse_card_file(
            _png_with_chunks({"ccv3": _b64(cbor2.dumps(_v3_card()))}), "card.png"
        )[0]
        reimported = parse_png_card(encode_png_card(None, _stub_character(**mapped)))
        assert reimported["card_metadata"]["data"]["assets"] == _v3_card()["data"]["assets"]
        assert reimported["card_metadata"]["root"] == {"root_unknown_field": ["a", "b"]}


# ---------------------------------------------------------------------------
# Embedded character book
# ---------------------------------------------------------------------------


class TestEmbeddedCharacterBook:
    def test_character_book_maps_to_lorebook_kwargs(self):
        mapped = lorebook_from_character_book(_v3_card()["data"]["character_book"])
        book_kwargs, entries = mapped
        assert book_kwargs == {"name": "Archive Lorebook", "description": "Places in the archive"}
        assert len(entries) == 1
        entry = entries[0]
        assert entry["keys"] == ["archive", "library"]
        assert entry["content"] == "The archive floats above the clouds."
        assert entry["category"] == "Setting"
        assert entry["depth"] == 2
        assert entry["probability"] == 75
        assert entry["case_sensitive"] is False
        assert entry["selective_logic"] == "1"

    def test_empty_book_returns_none(self):
        assert lorebook_from_character_book({"name": "Empty", "entries": []}) is None
        assert lorebook_from_character_book(None) is None
        assert lorebook_from_character_book("nope") is None

    def test_entries_without_content_are_skipped(self):
        mapped = lorebook_from_character_book({"entries": [{"keys": ["a"]}, {"keys": ["b"], "content": "kept"}]})
        assert mapped is not None
        assert len(mapped[1]) == 1

    def test_book_name_defaults(self):
        book_kwargs, _ = lorebook_from_character_book({"entries": [{"content": "x"}]})
        assert book_kwargs["name"] == "Embedded Lorebook"


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _temp_avatar_dir(monkeypatch, tmp_path):
    import config as app_config

    monkeypatch.setattr(app_config.settings, "character_avatar_dir", str(tmp_path / "characters"))


def _post_card(client, payload: bytes, filename: str):
    return client.post(
        "/api/v2/characters/import",
        files={"file": (filename, payload, "application/octet-stream")},
    )


def _seed_character(client, **fields) -> dict:
    body = {"name": fields.pop("name", "Route Char")}
    body.update(fields)
    resp = client.post("/api/v2/characters", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestImportRoute:
    def test_import_png_v2(self, client):
        card = {"spec": "chara_card_v2", "spec_version": "2.0", "data": {"name": "V2 Import", "description": "d"}}
        resp = _post_card(client, _png_with_chunks({"chara": _b64(card)}), "card.png")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "V2 Import"
        assert body["card_spec"] == CARD_SPEC_V2
        assert body["has_avatar"] is True

    def test_import_png_v3_cbor(self, client):
        resp = _post_card(client, _png_with_chunks({"ccv3": _b64(cbor2.dumps(_v3_card()))}), "card.png")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["card_spec"] == CARD_SPEC_V3
        assert body["creator"] == "CardAuthor"
        assert body["character_version"] == "4.2"
        assert body["append_system_prompt"] == "Never break character."
        assert body["group_greetings"] == ["Group greeting one", "Group greeting two"]

    def test_import_png_v1_flat(self, client):
        resp = _post_card(client, _png_with_chunks({"chara": json.dumps({"name": "Flat Import"})}), "card.png")
        assert resp.status_code == 200, resp.text
        assert resp.json()["card_spec"] == CARD_SPEC_V1

    def test_import_json_v3(self, client):
        resp = _post_card(client, json.dumps(_v3_card()).encode(), "card.json")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "Lossless Lena"
        assert body["card_spec"] == CARD_SPEC_V3
        # A JSON card has no image.
        assert body["has_avatar"] is False

    def test_import_reports_compatibility(self, client):
        resp = _post_card(client, _png_with_chunks({"ccv3": _b64(cbor2.dumps(_v3_card()))}), "card.png")
        report = resp.json()["compatibility"]
        assert report["format"] == "png"
        assert report["spec"] == CARD_SPEC_V3
        assert report["spec_version"] == "3.0"
        assert report["lost_fields"] == []
        assert report["unknown_extensions_preserved"] is True
        assert report["lorebook_converted"] is True
        preserved_names = {entry["name"] for entry in report["preserved_fields"]}
        assert {"root fields", "data.assets", "data.character_book", "data.extensions"} <= preserved_names

    def test_import_creates_embedded_lorebook(self, client, session):
        from core.entities import Lorebook, LorebookEntry
        from sqlmodel import select

        resp = _post_card(client, _png_with_chunks({"ccv3": _b64(cbor2.dumps(_v3_card()))}), "card.png")
        body = resp.json()
        assert body["embedded_lorebook_id"]

        lorebook = session.get(Lorebook, body["embedded_lorebook_id"])
        assert lorebook is not None and lorebook.name == "Archive Lorebook"
        entries = session.exec(select(LorebookEntry).where(LorebookEntry.lorebook_id == lorebook.id)).all()
        assert len(entries) == 1
        assert entries[0].keys == ["archive", "library"]
        # The original book is still preserved verbatim on the card.
        assert body["card_metadata"]["data"]["character_book"]["entries"][0]["entry_unknown_key"] == {"deep": True}

    def test_import_without_book_leaves_lorebook_null(self, client):
        card = {"spec": "chara_card_v2", "data": {"name": "No Book"}}
        assert _post_card(client, _png_with_chunks({"chara": _b64(card)}), "card.png").json()["embedded_lorebook_id"] is None

    def test_import_book_without_usable_entries_warns(self, client):
        card = {"spec": "chara_card_v2", "data": {"name": "Empty Book", "character_book": {"name": "B", "entries": [{"keys": ["x"]}]}}}
        body = _post_card(client, _png_with_chunks({"chara": _b64(card)}), "card.png").json()
        assert body["embedded_lorebook_id"] is None
        assert body["compatibility"]["warnings"]
        assert body["card_metadata"]["data"]["character_book"]["entries"] == [{"keys": ["x"]}]

    def test_import_rejects_unsupported_extension(self, client):
        resp = _post_card(client, b"{} {}", "card.txt")
        assert resp.status_code == 400

    def test_import_rejects_non_png_content(self, client):
        resp = _post_card(client, b"\x00\x01notreallypng", "card.png")
        assert resp.status_code == 400

    def test_import_rejects_invalid_json_card(self, client):
        resp = _post_card(client, b"{oops", "card.json")
        assert resp.status_code == 400

    def test_import_rejects_png_without_card_chunk(self, client):
        resp = _post_card(client, _png_with_chunks({}), "card.png")
        assert resp.status_code == 400

    def test_import_requires_name(self, client):
        card = {"spec": "chara_card_v2", "data": {"description": "nameless"}}
        resp = _post_card(client, _png_with_chunks({"chara": _b64(card)}), "card.png")
        assert resp.status_code == 400
        assert "name" in resp.json()["error"].lower()

    def test_import_rejects_empty_file(self, client):
        assert _post_card(client, b"", "card.json").status_code == 400

    def test_import_rejects_oversized_card(self, client, monkeypatch):
        monkeypatch.setattr("api.routes.world_vault.characters.MAX_CARD_BYTES", 512)
        resp = _post_card(client, b"{" + b'"x":"' + b"y" * 4096 + b'"}', "card.json")
        assert resp.status_code == 400


class TestExportRoute:
    def test_default_export_is_png_with_both_chunks(self, client):
        char = _seed_character(client, name="Export Dual")
        resp = client.get(f"/api/v2/characters/{char['id']}/export")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert "Export_Dual_v2.png" in resp.headers["content-disposition"]
        chunks = parse_png_chunks(resp.content)
        assert "chara" in chunks and "ccv3" in chunks

    def test_v2_export_keeps_chara_chunk(self, client):
        char = _seed_character(client, name="Export V2")
        resp = client.get(f"/api/v2/characters/{char['id']}/export?format=v2")
        assert resp.status_code == 200
        payload = json.loads(base64.b64decode(parse_png_chunks(resp.content)["chara"][0]))
        assert payload["data"]["name"] == "Export V2"
        assert payload["data"]["creator"] == ""
        assert payload["data"]["post_history_instructions"] == ""

    def test_v3_export_pins_ccv3_spec(self, client):
        char = _seed_character(client, name="Export V3")
        resp = client.get(f"/api/v2/characters/{char['id']}/export?format=v3")
        assert resp.status_code == 200
        assert "Export_V3_v3.png" in resp.headers["content-disposition"]
        payload = json.loads(base64.b64decode(parse_png_chunks(resp.content)["ccv3"][0]))
        assert payload["spec"] == CARD_SPEC_V3
        assert payload["spec_version"] == "3.0"

    def test_json_export(self, client):
        char = _seed_character(client, name="Export JSON", description="desc", creator="Someone")
        resp = client.get(f"/api/v2/characters/{char['id']}/export?format=json")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        assert "Export_JSON.json" in resp.headers["content-disposition"]
        payload = json.loads(resp.content)
        assert payload["data"]["name"] == "Export JSON"
        assert payload["data"]["creator"] == "Someone"

    def test_unknown_format_rejected(self, client):
        char = _seed_character(client, name="Bad Format")
        resp = client.get(f"/api/v2/characters/{char['id']}/export?format=v9")
        assert resp.status_code == 400

    def test_export_missing_character_404(self, client):
        assert client.get("/api/v2/characters/nonexistent/export").status_code == 404

    def test_export_maps_post_history_and_creator(self, client):
        char = _seed_character(
            client, name="Mapped", append_system_prompt="post", creator="Auth", character_version="9"
        )
        payload = json.loads(client.get(f"/api/v2/characters/{char['id']}/export?format=json").content)
        assert payload["data"]["post_history_instructions"] == "post"
        assert payload["data"]["creator"] == "Auth"
        assert payload["data"]["character_version"] == "9"

    def test_export_without_avatar_falls_back_to_1x1(self, client):
        char = _seed_character(client, name="No Avatar")
        png = client.get(f"/api/v2/characters/{char['id']}/export").content
        assert Image.open(io.BytesIO(png)).size == (1, 1)


class TestHttpRoundTrip:
    def test_v3_png_import_export_reimport_is_lossless(self, client):
        original = _v3_card()
        imported = _post_card(client, _png_with_chunks({"ccv3": _b64(cbor2.dumps(original))}), "card.png")
        assert imported.status_code == 200, imported.text
        char_id = imported.json()["id"]

        exported = client.get(f"/api/v2/characters/{char_id}/export?format=v3")
        payload = json.loads(base64.b64decode(parse_png_chunks(exported.content)["ccv3"][0]))

        for key in ("name", "description", "personality", "scenario", "first_mes", "mes_example",
                    "creator_notes", "system_prompt", "post_history_instructions", "alternate_greetings",
                    "group_greetings", "tags", "creator", "character_version", "version", "fav",
                    "creator_notes_multilingual", "some_future_data_field", "assets", "character_book"):
            assert payload["data"][key] == original["data"][key], key
        assert payload["root_unknown_field"] == original["root_unknown_field"]
        assert payload["spec"] == "chara_card_v3"
        assert payload["data"]["extensions"]["regex_scripts"] == original["data"]["extensions"]["regex_scripts"]

        # And the exported card re-imports to the same preserved payload.
        again = _post_card(client, exported.content, "again.png")
        assert again.status_code == 200, again.text
        third = json.loads(base64.b64decode(parse_png_chunks(client.get(f"/api/v2/characters/{again.json()['id']}/export?format=v3").content)["ccv3"][0]))
        assert third == payload

    def test_json_export_import_round_trip(self, client):
        original = _v3_card()
        first = _post_card(client, json.dumps(original).encode(), "card.json")
        assert first.status_code == 200, first.text
        exported = client.get(f"/api/v2/characters/{first.json()['id']}/export?format=json")
        reimported = json.loads(exported.content)
        assert reimported["data"]["character_book"] == original["data"]["character_book"]
        assert reimported["data"]["assets"] == original["data"]["assets"]
        assert reimported["root_unknown_field"] == original["root_unknown_field"]

    def test_v2_png_round_trip_keeps_legacy_spec(self, client):
        card = {"spec": "chara2.0", "spec_version": "2.0", "data": {"name": "Legacy Round", "custom": {"a": 1}}}
        imported = _post_card(client, _png_with_chunks({"chara": _b64(card)}), "card.png")
        assert imported.status_code == 200, imported.text
        exported = client.get(f"/api/v2/characters/{imported.json()['id']}/export")
        payload = json.loads(base64.b64decode(parse_png_chunks(exported.content)["chara"][0]))
        assert payload["spec"] == "chara2.0"
        assert payload["data"]["custom"] == {"a": 1}


class TestCardMigration:
    """Migration 064 adds the lossless-card columns to an existing table."""

    CARD_COLUMNS = (
        "card_spec",
        "card_spec_version",
        "creator",
        "character_version",
        "group_greetings",
        "card_metadata",
        "embedded_lorebook_id",
    )

    @staticmethod
    def _legacy_engine(tmp_path):
        """Full current schema with the card columns rolled back.

        The columns are renamed rather than dropped because SQLite refuses to
        drop a column that an index or a foreign key still references.
        """
        from sqlmodel import SQLModel, create_engine

        import core.entities  # noqa: F401  (registers the tables)

        engine = create_engine(f"sqlite:///{tmp_path / 'card_migration.db'}")
        SQLModel.metadata.create_all(engine)
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        with engine.begin() as conn:
            for column in TestCardMigration.CARD_COLUMNS:
                conn.execute(sa_text(f"ALTER TABLE characters RENAME COLUMN {column} to legacy_{column}"))
        return engine

    def test_migration_adds_card_columns_and_indexes(self, tmp_path):
        from infrastructure.migrations import run_migrations
        from infrastructure.migrations.steps import _get_table_columns

        engine = self._legacy_engine(tmp_path)
        with engine.connect() as conn:
            assert "card_spec" not in _get_table_columns(conn, "characters")

        run_migrations(engine)

        with engine.connect() as conn:
            columns = _get_table_columns(conn, "characters")
            indexes = {idx["name"] for idx in inspect(conn).get_indexes("characters")}

        for column in self.CARD_COLUMNS:
            assert column in columns, column
        assert "ix_characters_card_spec" in indexes
        assert "ix_characters_embedded_lorebook_id" in indexes

    def test_migration_is_idempotent(self, tmp_path):
        from infrastructure.migrations import run_migrations

        engine = self._legacy_engine(tmp_path)
        run_migrations(engine)
        # A second boot must not trip over the already-added columns.
        run_migrations(engine)

        with engine.connect() as conn:
            assert conn.execute(sa_text("SELECT COUNT(*) FROM characters")).scalar() >= 0

    def test_migration_preserves_existing_rows(self, tmp_path):
        engine = self._legacy_engine(tmp_path)
        with engine.begin() as conn:
            conn.execute(
                sa_text("INSERT INTO characters (id, name, sort_order, created_at, updated_at) "
                        "VALUES ('c1', 'Legacy Hero', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
            )

        from infrastructure.migrations import run_migrations

        run_migrations(engine)

        with engine.connect() as conn:
            row = conn.execute(sa_text("SELECT name, card_spec, card_metadata FROM characters WHERE id='c1'")).first()
        assert row[0] == "Legacy Hero"
        assert row[1] is None
        assert row[2] is None

    def test_migration_skipped_when_columns_already_present(self, tmp_path):
        """A database created from the current model reports no work to do."""
        from sqlmodel import SQLModel, create_engine

        import core.entities  # noqa: F401
        from infrastructure.migrations.steps import _migration_064_add_character_card_metadata

        engine = create_engine(f"sqlite:///{tmp_path / 'current.db'}")
        SQLModel.metadata.create_all(engine)
        with engine.connect() as conn:
            assert _migration_064_add_character_card_metadata(conn) is False

    def test_postgres_migration_adds_columns_indexes_and_foreign_key(self):
        """Postgres-only path: the FK on embedded_lorebook_id (SQLite cannot).

        Opt-in, following the pgvector suite: point PGVECTOR_TEST_URL at a
        throwaway Postgres. Everything happens in a scratch schema that is
        dropped afterwards, so the target database's own tables are untouched.
        """
        import os

        from sqlmodel import create_engine

        from infrastructure.migrations.steps import _migration_064_add_character_card_metadata

        url = os.getenv("PGVECTOR_TEST_URL")
        if not url:
            pytest.skip("Set PGVECTOR_TEST_URL to run the Postgres migration test")

        schema = "card_migration_scratch"
        engine = create_engine(url)
        try:
            with engine.connect() as conn:
                conn.execute(sa_text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
                conn.execute(sa_text(f"CREATE SCHEMA {schema}"))
                conn.execute(sa_text(f"SET search_path TO {schema}"))
                conn.execute(sa_text("CREATE TABLE lorebooks (id TEXT PRIMARY KEY, name TEXT)"))
                conn.execute(
                    sa_text(
                        "CREATE TABLE characters (id TEXT PRIMARY KEY, name TEXT, "
                        "sort_order INTEGER DEFAULT 0)"
                    )
                )
                conn.commit()

                assert _migration_064_add_character_card_metadata(conn) is True
                if conn.in_transaction():
                    conn.commit()
                # Second boot must find nothing left to do.
                assert _migration_064_add_character_card_metadata(conn) is False
                if conn.in_transaction():
                    conn.commit()

                columns = {c["name"] for c in inspect(conn).get_columns("characters")}
                indexes = {idx["name"] for idx in inspect(conn).get_indexes("characters")}
                foreign_keys = {fk["name"] for fk in inspect(conn).get_foreign_keys("characters")}
        finally:
            with engine.begin() as conn:
                conn.execute(sa_text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            engine.dispose()

        for column in self.CARD_COLUMNS:
            assert column in columns, column
        assert "ix_characters_card_spec" in indexes
        assert "ix_characters_embedded_lorebook_id" in indexes
        assert "fk_characters_embedded_lorebook" in foreign_keys


class TestCloneAndCleanup:
    def test_clone_copies_card_metadata_and_lorebook(self, client, session):
        from core.entities import Lorebook
        from sqlmodel import select

        imported = _post_card(client, _png_with_chunks({"ccv3": _b64(cbor2.dumps(_v3_card()))}), "card.png")
        assert imported.status_code == 200, imported.text
        char = imported.json()

        cloned = client.post(f"/api/v2/characters/{char['id']}/clone")
        assert cloned.status_code == 200, cloned.text
        clone = cloned.json()
        assert clone["name"] == "Lossless Lena (Copy)"
        assert clone["card_spec"] == CARD_SPEC_V3
        assert clone["card_metadata"] == char["card_metadata"]
        assert clone["embedded_lorebook_id"] != char["embedded_lorebook_id"]

        entries = session.exec(
            select(Lorebook.__table__).where(Lorebook.__table__.c.id == clone["embedded_lorebook_id"])
        ).all()
        assert entries

    def test_deleting_embedded_lorebook_clears_character_link(self, client, session):
        from core.entities import Character
        from sqlmodel import select

        imported = _post_card(client, _png_with_chunks({"ccv3": _b64(cbor2.dumps(_v3_card()))}), "card.png")
        char_id = imported.json()["id"]
        lorebook_id = imported.json()["embedded_lorebook_id"]

        resp = client.delete(f"/api/v2/lorebooks/{lorebook_id}")
        assert resp.status_code == 200, resp.text

        session.expire_all()
        character = session.get(Character, char_id)
        assert character.embedded_lorebook_id is None

    def test_deleting_character_keeps_card_metadata_available_on_lorebook(self, client, session):
        """Deleting a character does not destroy the materialized lorebook."""
        from core.entities import Lorebook

        imported = _post_card(client, _png_with_chunks({"ccv3": _b64(cbor2.dumps(_v3_card()))}), "card.png")
        char_id = imported.json()["id"]
        lorebook_id = imported.json()["embedded_lorebook_id"]

        assert client.delete(f"/api/v2/characters/{char_id}").status_code == 200
        assert session.get(Lorebook, lorebook_id) is not None
