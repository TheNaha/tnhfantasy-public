"""Lossless SillyTavern character card codec (V1 / V2 / V3).

Supported inputs
----------------
* PNG cards carrying a `ccv3` chunk (V3: base64 of JSON) or a
  `chara` chunk (V2/V1: base64 of zlib-compressed or plain JSON, or raw JSON),
  in any of the `tEXt`, `zTXt` and `iTXt` chunk types.
* Standalone `.json` cards: V1 (flat), V2 (`{spec, spec_version, data}`) and V3.

Losslessness
-------------
A card is split into the fields this app has columns for and a residual
`card_metadata` blob holding *everything else* - unknown root keys, unknown
`data` keys, unknown `data.extensions` keys, and all of `data.assets` and
`data.character_book` (including per-entry keys we cannot represent). Export
merges the residual blob back under the live column values, so a card that
round-trips through the vault comes back byte-equivalent in content: any field
we do not understand survives the trip.
"""
from __future__ import annotations

import base64
import binascii
import io
import json
import logging
import os
import struct
import zipfile
import zlib
from typing import Any

logger = logging.getLogger("character_cards")

try:
    import cbor2
except ImportError:  # pragma: no cover - optional non-standard CBOR cards
    cbor2 = None

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

CARD_SPEC_V1 = "chara_card_v1"
CARD_SPEC_V2 = "chara_card_v2"
CARD_SPEC_V3 = "chara_card_v3"

# Non-canonical spec strings seen in the wild, mapped to their canonical form.
_SPEC_ALIASES: dict[str, str] = {
    "chara1.0": CARD_SPEC_V1,
    "chara_card_v1": CARD_SPEC_V1,
    "chara2.0": CARD_SPEC_V2,
    "chara_card_v2": CARD_SPEC_V2,
    "chara3.0": CARD_SPEC_V3,
    "chara_card_v3": CARD_SPEC_V3,
    "ccv3": CARD_SPEC_V3,
}

# Chunk keyword -> spec, most specific first. V3 wins over V2 when a card was
# exported by a client that writes both (we do, too).
_CHUNK_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("ccv3", CARD_SPEC_V3),
    ("chara", CARD_SPEC_V2),
)

# Root keys that are structural rather than content: they are re-derived on
# export from `card_spec` / `card_spec_version`, so they are not duplicated in
# the residual blob.
_ROOT_STRUCTURAL_KEYS = frozenset({"spec", "spec_version", "data"})

# `data` keys with a first-class column. Everything else about `data` is
# preserved in card_metadata.
_MAPPED_DATA_KEYS = frozenset(
    {
        "name",
        "description",
        "personality",
        "scenario",
        "first_mes",
        "mes_example",
        "creator_notes",
        "system_prompt",
        "post_history_instructions",
        "alternate_greetings",
        "group_greeting",
        "group_greetings",
        "creator",
        "character_version",
        # NOT "tags": SillyTavern's `data.tags` is character metadata, and
        # this app's `visual_tags` is the image-generation tag list. They are
        # different things, so the card's own tags are preserved verbatim in
        # the residual blob instead of being mapped onto the column.
        "extensions",
    }
)

# `data.extensions` keys backed by a column. The live column wins on export so
# edits in the app are reflected instead of being shadowed by a stale copy.
_MAPPED_EXTENSION_KEYS = frozenset(
    {
        "lora_triggers",
        "visual_tags",
        "voice_profile",
        "voice_model_id",
        "checkpoint",
        "lora",
        "default_time",
        "default_location",
        "suggested_persona",
    }
)

# `data` keys `build_card_payload` always writes from live column values, so a
# residual copy of the same key is dropped instead of being written twice.
_REBUILT_DATA_KEYS = frozenset(
    {
        "name",
        "description",
        "personality",
        "scenario",
        "first_mes",
        "mes_example",
        "creator_notes",
        "system_prompt",
        "post_history_instructions",
        "alternate_greetings",
        "group_greeting",
        "group_greetings",
        # NOT "tags": the residual copy of the card's own tags must win, or
        # exporting would replace "fantasy, elf" with this app's image tags.
        "creator",
        "character_version",
        "extensions",
        "version",
    }
)

# Legacy `data` keys that SillyTavern clients still read, mapped to our columns.
_LEGACY_DATA_ALIASES: dict[str, str] = {
    "char_personality": "personality",
    "char_name": "name",
    "char_description": "description",
    "char_scenario": "scenario",
    "world_scenario": "scenario",
    "persona_description": "suggested_persona",
}


class CardParseError(ValueError):
    """Raised when a file cannot be interpreted as a character card."""


# ---------------------------------------------------------------------------
# PNG chunk plumbing
# ---------------------------------------------------------------------------
def parse_png_chunks(data: bytes) -> dict[str, list[bytes]]:
    """Return PNG textual chunk values keyed by keyword.

    Handles `tEXt` (keyword\\0value), `zTXt` (keyword\\0method + zlib stream)
    and `iTXt` (keyword\\0 flags / method / language / translated keyword +
    optional zlib stream). Keyed by keyword rather than chunk type so cards
    carrying several textual chunks are not truncated to one of them.
    """
    if not data.startswith(PNG_SIGNATURE):
        raise CardParseError("Invalid PNG file")

    chunks: dict[str, list[bytes]] = {}
    pos = len(PNG_SIGNATURE)
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        chunk_type = data[pos + 4 : pos + 8]
        payload = data[pos + 8 : pos + 8 + length]
        pos += 12 + length  # length + type + data + CRC

        if chunk_type == b"IEND":
            break
        try:
            name = chunk_type.decode("ascii")
        except UnicodeDecodeError:
            continue
        if name not in ("tEXt", "zTXt", "iTXt"):
            continue

        values = _decode_textual_chunk(name, payload)
        if values:
            chunks.setdefault(values[0], []).append(values[1])

    return chunks


def _decode_textual_chunk(chunk_type: str, payload: bytes) -> tuple[str, bytes] | None:
    """Decode one textual chunk into `(keyword, value_bytes)`."""
    sep = payload.find(b"\x00")
    if sep <= 0:
        return None
    keyword = payload[:sep].decode("latin-1", errors="replace")

    if chunk_type == "tEXt":
        return keyword, payload[sep + 1 :]

    if chunk_type == "zTXt":
        if len(payload) < sep + 2 or payload[sep + 1] != 0:
            return None
        try:
            return keyword, zlib.decompress(payload[sep + 2 :])
        except zlib.error:
            return None

    # iTXt: keyword \0 compression_flag compression_method language \0 translated \0 text
    body = payload[sep + 1 :]
    if len(body) < 2:
        return None
    compression_flag = body[0]
    method = body[1]
    language_end = body.find(b"\x00", 2)
    if language_end < 0:
        return None
    translated_end = body.find(b"\x00", language_end + 1)
    if translated_end < 0:
        return None
    text = body[translated_end + 1 :]
    if compression_flag == 1:
        if method != 0:
            return None
        try:
            text = zlib.decompress(text)
        except zlib.error:
            return None
    return keyword, text


def _payload_candidates(value: bytes) -> list[bytes]:
    """Candidate byte strings for a chunk value, in preference order.

    Cards in the wild store plain UTF-8 JSON, base64 of UTF-8 JSON, and base64
    of zlib-compressed UTF-8 JSON. V3 additionally allows base64 of CBOR.
    """
    stripped = value.strip()
    if not stripped:
        return []

    candidates: list[bytes] = [stripped]
    compact = b"".join(stripped.split())
    try:
        decoded = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError):
        return candidates
    if not decoded:
        return candidates

    candidates.append(decoded)
    try:
        candidates.append(zlib.decompress(decoded))
    except zlib.error:
        pass
    return candidates


def _decode_card_payload(value: bytes) -> dict | None:
    """Decode a card chunk value into a dict, trying JSON then CBOR."""
    for candidate in _payload_candidates(value):
        text = candidate.decode("utf-8", errors="replace").strip()
        if text.startswith("{"):
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, dict):
                return decoded
        if cbor2 is None:
            continue
        try:
            cbor_decoded = cbor2.loads(candidate)
        except Exception:  # cbor2 raises a family of errors on junk input
            continue
        if isinstance(cbor_decoded, dict):
            return cbor_decoded
    return None


# ---------------------------------------------------------------------------
# Card -> field mapping
# ---------------------------------------------------------------------------
def normalize_spec(spec: Any, spec_version: Any) -> tuple[str, str | None]:
    """Return `(card_spec, card_spec_version)` for a raw root spec pair.

    Handles the canonical V2/V3 strings, the older `chara2.0` / `chara3.0`
    variants, and cards with no spec at all (flat payload -> V1).
    """
    raw = str(spec).strip().lower() if spec is not None else ""
    canonical = _SPEC_ALIASES.get(raw, "")
    if not canonical and raw.startswith("chara_card_v") and raw.rsplit("_v", 1)[-1] in ("1", "2", "3"):
        canonical = raw
    if not canonical and not raw:
        # No spec at all: a flat payload is V1, anything else is at least V2.
        return CARD_SPEC_V1, None

    version = str(spec_version).strip() if spec_version not in (None, "") else None
    if not version:
        version = canonical.rsplit("_v", 1)[-1] + ".0"
    return canonical or raw, version


def _as_text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [item for item in (_as_text(v) for v in value) if item]
    return []


def _group_greetings(data: dict) -> list[str]:
    """Collect group greetings, tolerating singular and plural spellings."""
    out: list[str] = []
    for key in ("group_greetings", "group_greeting"):
        for greeting in _as_str_list(data.get(key)):
            if greeting not in out:
                out.append(greeting)
    return out


def _residual_card_metadata(root: dict, data: dict, data_wrapper: bool) -> dict:
    """Everything in the card that has no column, grouped for stable export.

    A `data.extensions` key that a column mirrors is NOT preserved here: the
    column is that extension's home, and the live value must win on export.
    The one thing that used to need a divergent copy was `visual_tags`, and
    that was only because `data.tags` and `extensions.visual_tags` used to
    share a column. They do not any more.
    """
    metadata: dict[str, Any] = {}

    root_extra = {k: v for k, v in root.items() if k not in _ROOT_STRUCTURAL_KEYS}
    if root_extra:
        metadata["root"] = root_extra

    residual_data: dict[str, Any] = {}
    for key, value in data.items():
        if key == "extensions" and isinstance(value, dict):
            # `tnhcomyu` is app-owned: it is written on every export and is
            # never kept here, so the identity is not carried twice.
            extra_ext = {
                k: v
                for k, v in value.items()
                if k not in _MAPPED_EXTENSION_KEYS and k != "tnhcomyu"
            }
            if extra_ext:
                residual_data[key] = extra_ext
            continue
        if key in _MAPPED_DATA_KEYS or key in _LEGACY_DATA_ALIASES:
            continue
        residual_data[key] = value
    if residual_data:
        metadata["data"] = residual_data

    raw_spec = root.get("spec")
    if raw_spec not in (None, ""):
        metadata["spec"] = raw_spec
    raw_spec_version = root.get("spec_version")
    if raw_spec_version not in (None, ""):
        metadata["spec_version"] = raw_spec_version
    if data_wrapper and "version" in data:
        metadata["data_version"] = data.get("version")

    return metadata


def parse_card_payload(payload: dict, *, spec_hint: str | None = None) -> dict:
    """Map a raw card dict onto Character columns plus residual metadata.

    `spec_hint` is the spec implied by the container (the `ccv3`/`chara` chunk
    keyword) and is used when the card itself carries no `spec` field.

    Returns a dict of column values (``name``, ``description``, ...), plus
    ``card_metadata``, ``card_spec``, ``card_spec_version``, ``creator``,
    ``character_version``, ``group_greetings`` and, when the card embeds a
    ``character_book``, ``character_book`` holding it verbatim.
    """
    if not isinstance(payload, dict):
        raise CardParseError("Character card is not a JSON object")

    data_wrapper = isinstance(payload.get("data"), dict)
    data = payload["data"] if data_wrapper else payload
    root = payload if data_wrapper else {}

    # Legacy flat cards occasionally carry the ST-exported prefixed names.
    for legacy_key, column in _LEGACY_DATA_ALIASES.items():
        if legacy_key in data and not data.get(column):
            data = {**data, column: data[legacy_key]}

    if not root.get("spec") and spec_hint:
        card_spec, card_spec_version = spec_hint, spec_hint.rsplit("_v", 1)[-1] + ".0"
    else:
        card_spec, card_spec_version = normalize_spec(root.get("spec"), root.get("spec_version"))
    extensions = data.get("extensions") if isinstance(data.get("extensions"), dict) else {}
    # ST's `data.tags` and this app's `extensions.visual_tags` are DIFFERENT
    # things that used to share one column.
    #
    # `data.tags` is character metadata ("fantasy", "elf"). `visual_tags` is
    # the image-generation tag list. Mapping one onto the other put "elf"
    # into the character's own image prompts, and the character then
    # polluted its own generations.
    #
    # So the card's tags stay in the residual blob (`tags` is not in
    # `_MAPPED_DATA_KEYS`, so it is preserved verbatim and written back on
    # export), and only the TNHComyu `extensions.visual_tags` reaches the
    # column.
    ext_visual_tags = _as_str_list(extensions.get("visual_tags"))
    visual_tags = ext_visual_tags

    creator_notes = _as_text(data.get("creator_notes"))
    alternate_greetings = _as_str_list(data.get("alternate_greetings"))
    first_mes = _as_text(data.get("first_mes"))
    if not first_mes and alternate_greetings:
        # Cards that only ship alternate greetings still need a greeting.
        first_mes = alternate_greetings[0]

    character: dict[str, Any] = {
        "name": _as_text(data.get("name")),
        "description": _as_text(data.get("description")),
        "personality": _as_text(data.get("personality")),
        "scenario": _as_text(data.get("scenario")),
        "first_mes": first_mes,
        "mes_example": _as_text(data.get("mes_example")),
        "creator_notes": creator_notes,
        "system_prompt": _as_text(data.get("system_prompt")),
        "append_system_prompt": _as_text(data.get("post_history_instructions")),
        "suggested_persona": (
            _as_text(data.get("suggested_persona"))
            or _as_text(extensions.get("suggested_persona"))
        ),
        "visual_tags": visual_tags,
        "alternate_greetings": alternate_greetings,
        "group_greetings": _group_greetings(data),
        "card_spec": card_spec,
        "card_spec_version": card_spec_version,
        # `creator` and `character_version` are distinct from creator_notes.
        "creator": _as_text(data.get("creator")),
        "character_version": _as_text(data.get("character_version")),
        "lora_triggers": _as_str_list(extensions.get("lora_triggers")),
        "voice_profile": _as_text(extensions.get("voice_profile")),
        "voice_model_id": _as_text(extensions.get("voice_model_id")) or None,
        "checkpoint": _as_text(data.get("checkpoint")) or _as_text(extensions.get("checkpoint")) or None,
        "lora": _as_text(data.get("lora")) or _as_text(extensions.get("lora")) or None,
        "default_time": _as_text(data.get("default_time")) or _as_text(extensions.get("default_time")) or None,
        "default_location": _as_text(data.get("default_location")) or _as_text(extensions.get("default_location")) or None,
        "card_metadata": _residual_card_metadata(root, data, data_wrapper),
    }

    character_book = data.get("character_book")
    if isinstance(character_book, dict) and character_book.get("entries"):
        # Preserved verbatim in card_metadata; also mapped to a Lorebook by the
        # caller so the vault can actually use it.
        character["character_book"] = character_book

    return character


def parse_png_card(png_bytes: bytes) -> dict:
    """Parse a PNG character card into mapped column values."""
    chunks = parse_png_chunks(png_bytes)

    payload: dict | None = None
    spec_hint = CARD_SPEC_V1
    for keyword, keyword_spec in _CHUNK_KEYWORDS:
        for raw_value in chunks.get(keyword, []):
            payload = _decode_card_payload(raw_value)
            if payload is not None:
                spec_hint = keyword_spec
                break
        if payload is not None:
            break

    if payload is None:
        raise CardParseError("Could not parse character card data from PNG")

    # The chunk keyword only pins the spec for a wrapped card; a flat payload in
    # a `chara` chunk is a V1 card no matter which chunk carried it.
    hint = spec_hint if isinstance(payload.get("data"), dict) else None
    return parse_card_payload(payload, spec_hint=hint)


def parse_json_card(raw: bytes | str) -> dict:
    """Parse a standalone JSON character card (V1 flat, V2 or V3)."""
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CardParseError(f"Character card is not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise CardParseError("Character card is not a JSON object")
    return parse_card_payload(payload)


def parse_charx_card(data: bytes) -> tuple[dict, bytes | None, dict[str, bytes]]:
    """Parse a CHARX/ZIP card, preserving its JSON card payload and manifest.

    Returns `(mapped fields, avatar bytes or None, archive members)`. The
    archive members are returned so the caller can materialise the assets the
    card REFERENCES BY PATH — a CHARX's `data.assets` entries point at archive
    members rather than carrying base64, and an expression image referenced
    that way is otherwise just a filename.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            card_name = next(
                (name for name in archive.namelist() if name.lower() in {"card.json", "character.json"}),
                None,
            )
            if not card_name:
                raise CardParseError("CHARX archive must contain card.json")
            card_payload = archive.read(card_name)
            mapped = parse_json_card(card_payload)
            assets = [name for name in archive.namelist() if not name.endswith("/") and name != card_name]
            metadata = mapped.setdefault("card_metadata", {})
            metadata["charx_assets"] = assets
            avatar_name = next(
                (
                    name for name in assets
                    if name.lower() in {"assets/main.png", "assets/portrait.png", "assets/avatar.png", "main.png"}
                ),
                None,
            )
            avatar = archive.read(avatar_name) if avatar_name else None
            members = {name: archive.read(name) for name in assets}
            return mapped, avatar, members
    except zipfile.BadZipFile as exc:
        raise CardParseError("CHARX archive is not a valid ZIP file") from exc


def parse_card_file(
    data: bytes, filename: str | None = None
) -> tuple[dict, bytes | None, dict[str, bytes]]:
    """Parse an uploaded card.

    Returns `(mapped fields, avatar bytes or None, archive members)`. PNG
    uploads double as the avatar image; JSON cards have no image; a CHARX
    archive carries its own members.
    """
    if data[:8] == PNG_SIGNATURE:
        return parse_png_card(data), data, {}

    name = (filename or "").lower()
    if data[:2] == b"PK" or name.endswith(".charx"):
        return parse_charx_card(data)
    if name.endswith(".json") or not name:
        try:
            return parse_json_card(data), None, {}
        except CardParseError:
            if not name:
                raise
    raise CardParseError("Could not parse character card data from PNG, JSON, or CHARX")


# SillyTavern `character_book` entry fields this vault has no equivalent for.
#
# They are preserved verbatim in the card's residual blob, so they round-trip
# back out on export — but nothing here acts on them, so the import report has
# to say so. The report used to claim "fully compatible" while every one of
# these was silently inert.
_INERT_LOREBOOK_ENTRY_FIELDS: dict[str, str] = {
    "position": "no equivalent: this vault has no per-entry prompt position",
    "insertion_order": "no equivalent: this vault's `depth` is a scan depth, not a prompt position",
    "priority": "no equivalent: this vault has no per-entry priority",
    "use_regex": "no equivalent: this vault matches keys literally",
    "group": "no equivalent: this vault has no entry groups",
    "id": "no equivalent: this vault assigns its own entry ids",
}

# `data.extensions` keys this app DOES act on, so they are not "inert".
# They are column-backed (see `_MAPPED_EXTENSION_KEYS`).
_EXECUTED_EXTENSION_KEYS = frozenset(
    {
        "lora_triggers",
        "visual_tags",
        "voice_profile",
        "voice_model_id",
        "checkpoint",
        "lora",
        "default_time",
        "default_location",
        "suggested_persona",
    }
)


def take_expression_assets(char_data: dict) -> list[dict[str, str]]:
    """Remove the expression images a card carries and return them.

    SillyTavern V3 puts expression images in `data.assets` as entries of
    `type: "expression"`, keyed by the emotion name, with the image as
    base64 in `data`.

    The codec preserved them as inert JSON in the residual blob and never
    turned them into images, so `Character.expressions` was always empty
    after an import and an exported card never carried the expressions back
    out.

    They are REMOVED from the residual as they are taken, because the caller
    materialises them as real expression files — and keeping the base64 as
    well would carry every expression image twice.
    """
    metadata = char_data.get("card_metadata") or {}
    residual = metadata.get("data") or {}
    assets = residual.get("assets")
    if not isinstance(assets, list):
        return []

    taken: list[dict[str, str]] = []
    kept: list[Any] = []
    for asset in assets:
        if isinstance(asset, dict) and str(asset.get("type") or "").lower() == "expression":
            name = str(asset.get("name") or "").strip()
            data = asset.get("data")
            if name and isinstance(data, str) and data.strip():
                taken.append({"emotion": name, "data": data})
            continue
        kept.append(asset)

    if taken:
        residual["assets"] = kept
    return taken


def expression_assets_to_card(expressions: dict[str, str] | None) -> list[dict[str, str]]:
    """The `data.assets` entries for a character's expression images.

    The inverse of `take_expression_assets`. `expressions` maps an emotion
    name to the path of its image; the image is read and base64'd by
    `_expression_asset_bytes`, which knows the file system.
    """
    return [
        {"type": "expression", "name": emotion}
        for emotion in sorted(expressions or {})
        if (expressions or {}).get(emotion)
    ]


def _expression_asset_bytes(path: str) -> tuple[str, str] | None:
    """`(extension, base64)` for an expression image, or None.

    The extension is sniffed from the file, and falls back to `png` — the
    format SillyTavern expects and the one the avatar directory uses.
    """
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return None
    if not data:
        return None
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    if ext not in ("png", "webp", "jpg", "jpeg"):
        ext = "png"
    return ext, base64.b64encode(data).decode("ascii")


def preserved_but_inert(char_data: dict) -> list[dict[str, str]]:
    """Features the card carried that this app preserves but does NOT act on.

    The import report used to say "fully compatible" while every one of these
    was silently inert. This is the list it should have been showing.

    Each entry is `{"name", "field", "detail"}`, where `detail` says WHY it is
    inert — a preserved extension is not automatically an inert one, and
    "preserved but not executed" is a different thing from "lost".
    """
    out: list[dict[str, str]] = []
    metadata = char_data.get("card_metadata") or {}
    residual = metadata.get("data") or {}

    extensions = residual.get("extensions") or {}
    if isinstance(extensions, dict):
        for key in sorted(extensions):
            if key in _EXECUTED_EXTENSION_KEYS:
                continue
            out.append(
                {
                    "name": f"data.extensions.{key}",
                    "field": key,
                    "detail": "preserved and re-exported, but not executed by this app",
                }
            )

    book = residual.get("character_book") or {}
    if isinstance(book, dict):
        inert_keys: dict[str, str] = {}
        for entry in book.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            for key, reason in _INERT_LOREBOOK_ENTRY_FIELDS.items():
                if key in entry:
                    inert_keys.setdefault(key, reason)
        for key, reason in sorted(inert_keys.items()):
            out.append(
                {
                    "name": f"data.character_book.entries[].{key}",
                    "field": key,
                    "detail": reason,
                }
            )

    return out


def strip_png_text_chunks(data: bytes) -> bytes:
    """Return the PNG with its textual chunks removed.

    A card PNG carries the whole character in a `chara`/`ccv3` text chunk, so
    the file that is ALSO the character's avatar is a few hundred KB, most of
    it the card payload — which is then served to every browser that loads
    the avatar, and would be re-read on every avatar request.

    The export path writes a fresh `PngInfo`, so the re-exported card is
    unaffected: it gets its chunks back from the payload.

    Returns the input unchanged if it is not a PNG or cannot be rewritten.
    """
    if not data.startswith(PNG_SIGNATURE):
        return data
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(data))
        image.load()
        output = io.BytesIO()
        # No `pnginfo=`, so PIL writes no textual chunks at all.
        image.save(output, format="PNG")
        return output.getvalue()
    except Exception as exc:  # pragma: no cover - PIL failure keeps the original
        logger.debug("card_avatar_chunk_strip_failed", error=str(exc))
        return data


# ---------------------------------------------------------------------------
# Character -> card
# ---------------------------------------------------------------------------
def build_card_payload(
    character,
    *,
    version: str = CARD_SPEC_V2,
    spec: str | None = None,
    expression_assets_mode: str = "embed",
) -> dict:
    """Build a card payload for export, merging residual metadata back in.

    Live column values always win over a stale copy in `card_metadata`, so edits
    made in the app survive an export; everything the app has no column for
    (unknown root/data/extensions keys, assets, the embedded character book) is
    written back verbatim. `version=CARD_SPEC_V1` returns the flat, unwrapped
    V1 shape, and `spec` pins the root spec string (e.g. to force canonical V3).
    """
    metadata = character.card_metadata if isinstance(character.card_metadata, dict) else {}
    residual_root = metadata.get("root") if isinstance(metadata.get("root"), dict) else {}
    residual_data = metadata.get("data") if isinstance(metadata.get("data"), dict) else {}
    data_version = metadata.get("data_version")

    extensions: dict[str, Any] = dict(residual_data.get("extensions") or {})
    extensions["lora_triggers"] = list(character.lora_triggers or [])    # A card that carried its own `extensions.visual_tags` keeps them: that value
    # is the only record of the card's original tag list, which may differ from
    # the live column (which mirrors `data.tags`).
    extensions["visual_tags"] = list(character.visual_tags or [])
    extensions["voice_profile"] = character.voice_profile or ""
    if character.voice_model_id:
        extensions["voice_model_id"] = character.voice_model_id
    if character.checkpoint:
        extensions["checkpoint"] = character.checkpoint
    if character.lora:
        extensions["lora"] = character.lora
    if character.default_time:
        extensions["default_time"] = character.default_time
    if character.default_location:
        extensions["default_location"] = character.default_location
    if character.suggested_persona:
        extensions["suggested_persona"] = character.suggested_persona

    # This app's IDENTITY, so a card that has been through SillyTavern is
    # recognised as the same character when it comes back.
    #
    # SillyTavern preserves unknown `data.extensions` keys, and so does this
    # app's residual blob, so the identity survives a round trip through
    # another client. That is what lets a re-import UPDATE a character
    # instead of creating a second one.
    #
    # The key is app-owned: it is written on every export and excluded from
    # the residual, so it is never carried twice.
    from core.character_bundle import APP_EXTENSION_KEY, app_extension

    extensions[APP_EXTENSION_KEY] = app_extension(getattr(character, "id", "") or "")

    group_greetings = list(character.group_greetings or [])

    data: dict[str, Any] = {
        "name": character.name or "",
        "description": character.description or "",
        "personality": character.personality or "",
        "scenario": character.scenario or "",
        "first_mes": character.first_mes or "",
        "mes_example": character.mes_example or "",
        "creator_notes": character.creator_notes or "",
        "system_prompt": character.system_prompt or "",
        "post_history_instructions": character.append_system_prompt or "",
        "alternate_greetings": list(character.alternate_greetings or []),
        "tags": list(character.visual_tags or []),        "creator": character.creator or "",
        "character_version": character.character_version or "",
        "extensions": extensions,
    }
    if group_greetings:
        data["group_greetings"] = group_greetings
    if data_version is not None:
        data["version"] = data_version

    # Residual data keys we do not map, minus structural ones we rebuild above.
    for key, value in residual_data.items():
        if key in _REBUILT_DATA_KEYS:
            continue
        if key == "tags":
            # The card's own tag list, normalised. It wins over this app's
            # `visual_tags`, which are a DIFFERENT thing (the image-generation
            # tag list) and must not be written over the card's metadata tags.
            data["tags"] = _as_str_list(value)
            continue
        data[key] = value
    if "tags" not in residual_data:
        # No card provenance for the tags: a character created here exports its
        # image-generation tags as the card's, which is the useful default.
        data["tags"] = list(character.visual_tags or [])

    # Expression images, as SillyTavern V3 `data.assets` entries.
    #
    # The LIVE expression files win for the emotions they cover; the card's
    # own other assets (a background, a character book image) are kept. A
    # character whose expressions were never imported simply has none, and
    # the card carries none — which is honest, and the export report says so.
    expression_assets: list[dict[str, Any]] = []
    for emotion, path in sorted((getattr(character, "expressions", None) or {}).items()):
        loaded = _expression_asset_bytes(path)
        if not loaded:
            continue
        ext, encoded = loaded
        if expression_assets_mode == "path":
            # A CHARX carries the image as an archive member and the entry
            # references it by path.
            expression_assets.append(
                {
                    "type": "expression",
                    "name": emotion,
                    "ext": ext,
                    "data": f"assets/expressions/{emotion}.{ext}",
                }
            )
        else:
            expression_assets.append(
                {"type": "expression", "name": emotion, "ext": ext, "data": encoded}
            )
    if expression_assets:
        covered = {asset["name"] for asset in expression_assets}
        merged = [
            asset
            for asset in (data.get("assets") or [])
            if not (
                isinstance(asset, dict)
                and str(asset.get("type") or "").lower() == "expression"
                and str(asset.get("name") or "") in covered
            )
        ]
        data["assets"] = merged + expression_assets

    spec_string = character.card_spec or CARD_SPEC_V2
    spec_version_string = character.card_spec_version or (spec_string.rsplit("_v", 1)[-1] + ".0")
    if metadata.get("spec"):
        # Preserve a non-canonical spec string ("chara2.0") the card came with.
        spec_string = metadata["spec"]
    if metadata.get("spec_version"):
        spec_version_string = metadata["spec_version"]
    if spec:
        spec_string = spec
        spec_version_string = spec.rsplit("_v", 1)[-1] + ".0"

    payload: dict[str, Any] = {
        "spec": spec_string,
        "spec_version": spec_version_string,
        "data": data,
    }
    for key, value in residual_root.items():
        payload.setdefault(key, value)

    if version == CARD_SPEC_V1:
        # A V1 card is the flat payload with no wrapper.
        flat = {k: v for k, v in data.items() if k not in ("group_greetings",)}
        flat.update(residual_root)
        return flat
    return payload


def encode_png_card(
    image_bytes: bytes | None,
    character,
    *,
    include_v3: bool = True,
    v3_spec: str | None = None,
) -> bytes:
    """Return a PNG carrying both a V2 `chara` chunk and a V3 `ccv3` chunk.

    The `chara` chunk holds base64 of the JSON payload (accepted by every
    SillyTavern version, and read by our own importer), while `ccv3` holds
    base64 of the canonical V3 JSON payload. Older clients read `chara` and
    ignore the extra chunk, so the export stays backward compatible.
    `v3_spec` pins the `ccv3` payload to a specific spec string.
    """
    from io import BytesIO

    from PIL import Image, PngImagePlugin

    v2_payload = build_card_payload(character, version=CARD_SPEC_V2)
    json_bytes = json.dumps(v2_payload, ensure_ascii=False).encode("utf-8")

    if image_bytes:
        image = Image.open(BytesIO(image_bytes))
        image.load()
    else:
        image = Image.new("RGBA", (1, 1), (0, 0, 0, 0))

    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("chara", base64.b64encode(json_bytes).decode("ascii"))

    if include_v3:
        v3_payload = build_card_payload(character, version=CARD_SPEC_V3, spec=v3_spec)
        v3_json = json.dumps(v3_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        metadata.add_text("ccv3", base64.b64encode(v3_json).decode("ascii"))

    output = BytesIO()
    image.save(output, format="PNG", pnginfo=metadata)
    return output.getvalue()


def encode_charx_card(character, avatar_bytes: bytes | None = None) -> bytes:
    """Encode a V3 card and available avatar assets as a CHARX/ZIP archive.

    The expression images go in as archive MEMBERS and the card's
    `data.assets` entries reference them BY PATH — which is what CHARX is
    for, and what a SillyTavern client that reads a CHARX expects. The
    reference is the archive-relative path, so the same archive is the
    transport.
    """
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        payload = build_card_payload(character, version=CARD_SPEC_V3, expression_assets_mode="path")
        archive.writestr("card.json", json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
        if avatar_bytes:
            archive.writestr("assets/main.png", avatar_bytes)
        for asset in payload.get("data", {}).get("assets") or []:
            if not isinstance(asset, dict):
                continue
            if str(asset.get("type") or "").lower() != "expression":
                continue
            source = getattr(character, "expressions", None) or {}
            path = source.get(str(asset.get("name") or ""))
            loaded = _expression_asset_bytes(path) if path else None
            if not loaded:
                continue
            ext, encoded = loaded
            archive.writestr(
                f"assets/expressions/{asset.get('name')}.{ext}",
                base64.b64decode(encoded),
            )
    return output.getvalue()


# ---------------------------------------------------------------------------
# Embedded character book
# ---------------------------------------------------------------------------
def lorebook_from_character_book(character_book: Any) -> tuple[dict, list[dict]] | None:
    """Map an embedded `character_book` onto Lorebook / LorebookEntry kwargs.

    Returns `(lorebook_kwargs, entry_kwargs_list)` or None when the book has no
    usable entries. Fields the Lorebook model cannot hold stay in the card's
    `card_metadata` residual blob, so nothing is lost on re-export.
    """
    if not isinstance(character_book, dict):
        return None
    entries = character_book.get("entries")
    if not isinstance(entries, list) or not entries:
        return None

    name = _as_text(character_book.get("name")).strip() or "Embedded Lorebook"
    description = _as_text(character_book.get("description")) or None

    entry_kwargs: list[dict] = []
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        content = _as_text(raw.get("content"))
        if not content:
            continue
        # `constant: true` means "always on" in SillyTavern, and this vault's
        # always-on test is a KEYLESS entry (`rag_pipeline` and
        # `context_builder` both select on `not e.keys`). A ST entry that is
        # constant AND has keys therefore became KEY-GATED and stopped firing
        # unless the user happened to type one of them. Making it keyless
        # restores the ST meaning.
        #
        # `insertion_order` is NOT written to `depth`. The two are different
        # concepts — ST's is where in the prompt the entry lands, this vault's
        # `depth` is a scan depth that activation never reads — so mapping
        # one onto the other made the value meaningless while looking
        # meaningful. It stays in the card's residual blob and round-trips.
        keys = [] if raw.get("constant") else _as_str_list(raw.get("keys") or raw.get("key"))
        entry_kwargs.append(
            {
                "keys": keys,
                "content": content,
                "category": _as_text(raw.get("comment")) or None,
                "tags": _as_str_list(raw.get("tags")),
                "case_sensitive": bool(raw.get("case_sensitive", False)),
                "selective_logic": _as_text(raw.get("selective_logic")) or None,
                "probability": _as_int(raw.get("probability"), default=None),
                # A disabled ST entry must not activate here.
                "enabled": bool(raw.get("enabled", True)),
                # ST's secondary keys, for `selective` matching.
                "secondary_keys": _as_str_list(raw.get("secondary_keys")),
            }
        )

    if not entry_kwargs:
        return None
    return {"name": name, "description": description}, entry_kwargs


def _as_int(value: Any, *, default: int | None) -> int | None:
    if isinstance(value, bool) or value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
