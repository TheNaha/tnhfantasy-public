"""The TNHFantasy character bundle — a native export that is not a card.

A SillyTavern card has a small, fixed vocabulary: some prose, a greeting, an
example, an embedded lorebook, an avatar. This app's characters carry more
than that — expression image sets, a voice binding, world membership with its
locations, the vault's own lorebook library, a gallery, chats, memories.

Exporting one of those characters as a card loses all of it, silently. The
bundle is the other half of the answer: a ZIP that carries the character as
this app understands it, alongside the card so it can still go to
SillyTavern.

    character.tnhzip
      manifest.json            kind, version, character id, what is included
      character.json           every column, plus the card's residual metadata
      card.json                the SillyTavern card
      card.png                 the avatar, carrying the card chunks
      expressions/<emotion>.png
      lorebooks/<name>.json
      world.json               the world and its locations
      chat.jsonl               the chat history, if included

`manifest.json` is what tells the two apart on import. A card has no
manifest, and that is the whole difference.
"""

from __future__ import annotations

import base64
import io
import json
import os
import zipfile
from typing import Any, Iterable

from core.character_cards import (
    CARD_SPEC_V3,
    build_card_payload,
    encode_png_card,
    parse_card_payload,
    parse_png_chunks,
)

BUNDLE_KIND = "tnhfantasy-bundle"
BUNDLE_VERSION = 1
BUNDLE_SUFFIX = ".tnhzip"

# What a bundle can carry. Each is optional; the manifest records which were
# actually included, so an import knows what it is looking at.
BUNDLE_SECTIONS = (
    "expressions",
    "voice",
    "generation",
    "world",
    "lorebooks",
    "chat",
)

# The app's own namespace inside a card's `data.extensions`. SillyTavern
# preserves unknown extensions, so a card that has been through SillyTavern
# still carries the identity of the character it came from.
APP_EXTENSION_KEY = "tnhfantasy"


def app_extension(character_id: str) -> dict[str, Any]:
    """The identity this app writes into a card it exports."""
    return {"character_id": character_id}


def _character_payload(character: Any) -> dict[str, Any]:
    """Every column of the character, plus the card's residual metadata."""
    payload = character.model_dump()
    # The expression PATHS are machine-local; the bundle carries the images
    # themselves and the paths are re-created on import.
    payload["expressions"] = dict(character.expressions or {})
    return payload


def build_bundle(
    character: Any,
    *,
    session: Any = None,
    include: Iterable[str] = (),
    avatar_bytes: bytes | None = None,
    world_payload: dict[str, Any] | None = None,
    lorebook_payloads: list[dict[str, Any]] | None = None,
    chat_payloads: list[dict[str, Any]] | None = None,
) -> bytes:
    """Build the bundle archive for a character.

    `include` names the optional sections to carry; the manifest records
    exactly what was included, so an import never has to guess.
    """
    wanted = {str(s).strip() for s in include if str(s).strip()}

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        # The SillyTavern card, so the bundle is also a card.
        # Pinned to the canonical V3 spec: the bundle's card is the modern
        # one, and a wrapped payload labelled `chara_card_v2` is
        # self-contradictory.
        card_payload = build_card_payload(
            character, version=CARD_SPEC_V3, spec=CARD_SPEC_V3
        )
        archive.writestr(
            "card.json", json.dumps(card_payload, ensure_ascii=False, indent=2).encode("utf-8")
        )
        if avatar_bytes:
            archive.writestr("card.png", encode_png_card(avatar_bytes, character))

        archive.writestr(
            "character.json",
            json.dumps(_character_payload(character), ensure_ascii=False, indent=2, default=str).encode(
                "utf-8"
            ),
        )

        if "expressions" in wanted:
            for emotion, path in sorted((character.expressions or {}).items()):
                try:
                    with open(path, "rb") as handle:
                        data = handle.read()
                except OSError:
                    continue
                if not data:
                    continue
                ext = os.path.splitext(path)[1].lstrip(".").lower() or "png"
                archive.writestr(f"expressions/{emotion}.{ext}", data)

        if "lorebooks" in wanted and lorebook_payloads:
            for payload in lorebook_payloads:
                name = str(payload.get("name") or "lorebook")
                archive.writestr(
                    f"lorebooks/{_safe_name(name)}.json",
                    json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
                )

        if "world" in wanted and world_payload:
            archive.writestr(
                "world.json",
                json.dumps(world_payload, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
            )

        if "chat" in wanted and chat_payloads:
            lines = [
                json.dumps(message, ensure_ascii=False, default=str) for message in chat_payloads
            ]
            archive.writestr("chat.jsonl", ("\n".join(lines) + "\n").encode("utf-8"))

        manifest = {
            "kind": BUNDLE_KIND,
            "version": BUNDLE_VERSION,
            "character_id": character.id,
            "name": character.name,
            "exported_at": _now_iso(),
            "sections": sorted(s for s in wanted if s in BUNDLE_SECTIONS),
            "expressions": sorted((character.expressions or {}).keys()),
        }
        archive.writestr(
            "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        )
    return output.getvalue()


def _safe_name(name: str) -> str:
    import re

    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name or "").strip("_")
    return cleaned or "item"


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def is_bundle(data: bytes) -> bool:
    """Is this a bundle rather than a card?"""
    if not data.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if "manifest.json" not in archive.namelist():
                return False
            manifest = json.loads(archive.read("manifest.json"))
            return isinstance(manifest, dict) and manifest.get("kind") == BUNDLE_KIND
    except Exception:
        return False


def parse_bundle(data: bytes) -> dict[str, Any]:
    """Read a bundle into the pieces an import needs.

    Returns a dict with `character` (the column payload), `card` (the
    SillyTavern card it carries), `expressions` (emotion -> bytes), `world`,
    `lorebooks`, `chat` and `manifest`.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("manifest.json")) if "manifest.json" in names else {}
        character = (
            json.loads(archive.read("character.json")) if "character.json" in names else {}
        )
        card: dict[str, Any] = {}
        if "card.json" in names:
            card = json.loads(archive.read("card.json"))
        elif "card.png" in names:
            # A bundle with only the PNG card still carries the card.
            with archive.open("card.png") as handle:
                chunks = parse_png_chunks(handle.read())
            for keyword in ("ccv3", "chara"):
                for raw in chunks.get(keyword, []):
                    try:
                        decoded = base64.b64decode(raw, validate=True)
                        card = json.loads(decoded.decode("utf-8"))
                        break
                    except Exception:
                        continue
                if card:
                    break

        expressions: dict[str, bytes] = {}
        for name in names:
            if name.startswith("expressions/") and not name.endswith("/"):
                emotion = os.path.splitext(os.path.basename(name))[0]
                expressions[emotion] = archive.read(name)

        world = json.loads(archive.read("world.json")) if "world.json" in names else None
        lorebooks = [
            json.loads(archive.read(name))
            for name in names
            if name.startswith("lorebooks/") and name.endswith(".json")
        ]
        chat: list[dict[str, Any]] = []
        if "chat.jsonl" in names:
            for line in archive.read("chat.jsonl").decode("utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    chat.append(json.loads(line))
                except Exception:
                    continue

        return {
            "manifest": manifest,
            "character": character,
            "card": card,
            "expressions": expressions,
            "world": world,
            "lorebooks": lorebooks,
            "chat": chat,
        }


def card_fields_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """The SillyTavern fields of a bundle's card, mapped onto columns.

    A bundle's card is parsed with the same codec a card upload uses, so the
    two paths cannot drift.
    """
    card = bundle.get("card") or {}
    if not card:
        return {}
    return parse_card_payload(card)
