import asyncio
import base64
import random
import re
import json
import os
import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from io import BytesIO
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from api.deps import get_session, get_character_repo
from infrastructure.logging import get_logger
from infrastructure.repositories.character_repo import CharacterRepository
from services.character_portability import not_portable_features, portable_summary
from services.reference_cleanup import scrub_entity_references
from services.world_ownership import apply_world_id, require_world
from core.workflow_builder import DEFAULT_CHECKPOINT
from core.character_bundle import (
    APP_EXTENSION_KEY,
    BUNDLE_SUFFIX,
    build_bundle,
    card_fields_from_bundle,
    is_bundle as bundle_is_bundle,
    parse_bundle,
)
from core.character_cards import (
    CARD_SPEC_V1,
    CARD_SPEC_V3,
    CardParseError,
    build_card_payload,
    encode_charx_card,
    encode_png_card,
    lorebook_from_character_book,
    parse_card_file,
    preserved_but_inert,
    strip_png_text_chunks,
    take_expression_assets,
)
from core.entities import (
    Chat,
    Character,
    Collection,
    Location,
    Lorebook,
    LorebookEntry,
    Message,
    MessageKind,
    MessageRole,
    VoiceModel,
    World,
)
from core.exceptions import NotFoundError, ValidationError
from core.upload_validation import (
    MAX_AVATAR_SIZE_MB,
    MAX_CARD_SIZE_MB,
    inspect_image,
    read_upload_bounded,
    read_upload_file_bounded,
    require_declared_size,
)
import config as app_config

logger = get_logger("characters_route")
router = APIRouter()

MAX_AVATAR_BYTES = MAX_AVATAR_SIZE_MB * 1024 * 1024
MAX_CARD_BYTES = MAX_CARD_SIZE_MB * 1024 * 1024

CARD_FILE_SUFFIXES = (".png", ".json", ".charx", BUNDLE_SUFFIX)
CARD_EXPORT_FORMATS = ("default", "v2", "v3", "json", "charx", "bundle")


class CharacterCreateRequest(BaseModel):
    """Create body for POST /characters.

    This route used to take the `Character` SQLModel table class as its request
    body, which has two defects at once:

      * `id` is a client-writable field, so `POST {"name":"x","id":"..."}`
        persisted the caller's primary key — and propagated it into the second
        row the route creates, the character's `Collection`.
      * the body was never validated. A missing NOT NULL column reached
        `session.add()` and came back as a 500 instead of a 422, so a malformed
        client request read as a server fault.

    `id`, `created_at`, `updated_at`, `avatar_path`, `card_spec*`,
    `card_metadata` and `embedded_lorebook_id` are server-owned and are
    deliberately absent: `avatar_path` has its own upload endpoint, and the
    SillyTavern card provenance fields are only ever set by card import.
    `extra="forbid"` so a typo'd field is a 422 instead of a silent drop — the
    failure mode that made `ScenarioUpdate` look like it worked.
    """

    model_config = {"extra": "forbid"}

    name: str
    description: str | None = None
    personality: str | None = None
    scenario: str | None = None
    first_mes: str | None = None
    mes_example: str | None = None
    creator_notes: str | None = None
    system_prompt: str | None = None
    append_system_prompt: str | None = None
    suggested_persona: str | None = None
    visual_tags: list[str] = Field(default_factory=list)
    lora_triggers: list[str] | None = None
    voice_profile: str | None = None
    voice_model_id: str | None = None
    alternate_greetings: list[str] | None = None
    expressions: dict[str, str] | None = None
    expressions_lora: list[str] | None = None
    checkpoint: str | None = None
    lora: str | None = None
    default_time: str | None = None
    default_location: str | None = None
    lorebook_ids: list[str] = Field(default_factory=list)
    group_greetings: list[str] | None = None
    creator: str | None = None
    character_version: str | None = None
    sort_order: int = 0
    # Which World this entity belongs to. Ownership of record lives on the
    # member, not in an array on the `worlds` row — see `services/
    # world_ownership.py`. Absent means "leave alone"; an explicit null detaches.
    world_id: str | None = None


class CharacterUpdateRequest(BaseModel):
    """Strict optional-field update model for PUT and PATCH endpoints."""
    name: str | None = None
    description: str | None = None
    personality: str | None = None
    scenario: str | None = None
    first_mes: str | None = None
    mes_example: str | None = None
    creator_notes: str | None = None
    # The vault's own library books this character draws on — distinct from
    # `embedded_lorebook_id`, the SillyTavern `character_book` that arrived
    # inside an imported card and is not editable. Without this field the
    # character's modal payload was dropped by pydantic and the UI was a no-op.
    lorebook_ids: list[str] | None = None
    system_prompt: str | None = None
    append_system_prompt: str | None = None
    suggested_persona: str | None = None
    visual_tags: list[str] | None = None
    lora_triggers: list[str] | None = None
    voice_profile: str | None = None
    voice_model_id: str | None = None
    alternate_greetings: list[str] | None = None
    expressions: dict[str, str] | None = None
    expressions_lora: list[str] | None = None
    checkpoint: str | None = None
    lora: str | None = None
    default_time: str | None = None
    default_location: str | None = None
    # Same three fields `CharacterCreateRequest` accepts. Without them a
    # SillyTavern card's version and creator notes are write-once, and the
    # v3 `group_greetings` list is uneditable after import — pydantic's
    # default `extra='ignore'` dropped them and the route answered 200.
    group_greetings: list[str] | None = None
    creator: str | None = None
    character_version: str | None = None
    sort_order: int | None = None
    # Which World this entity belongs to. Ownership of record lives on the
    # member, not in an array on the `worlds` row — see `services/
    # world_ownership.py`. Absent means "leave alone"; an explicit null detaches.
    world_id: str | None = None


def _character_to_dict(character: Character) -> dict:
    """Serialize a Character with the computed has_avatar field."""
    d = character.model_dump()
    d["has_avatar"] = character.avatar_path is not None and os.path.exists(character.avatar_path)
    return d


def _compatibility_report(
    char_data: dict,
    *,
    source_format: str,
    lorebook_created: bool,
    lorebook_preserved_only: bool,
    lost_fields: list[dict[str, str]] | None = None,
) -> dict:
    """Describe what an import kept, for the UI's compatibility report.

    Three buckets, and the distinction between them is the whole point:

    * `lost_fields` — values the card carried that this app DROPPED. They
      are gone, and the user should be told.
    * `preserved_fields` — groups of card data kept verbatim in
      `card_metadata` and written back on export.
    * `preserved_but_inert` — preserved, and round-tripped, but NOT ACTED ON
      here. A SillyTavern `regex_scripts` extension, an entry's `position`:
      they survive the trip and change nothing about how this app behaves.

    The report used to hardcode `lost_fields: []` and the UI turned that into
    "Fully compatible. All reported card data was imported." — while the
    report itself only ever counted groups, and said nothing at all about the
    features that were inert.
    """
    metadata = char_data.get("card_metadata") or {}
    residual_data = metadata.get("data") or {}
    preserved: list[dict] = []

    for label, value in (
        ("root fields", metadata.get("root") or {}),
        ("data fields", {k: v for k, v in residual_data.items() if k not in ("extensions", "assets", "character_book")}),
        ("data.extensions", residual_data.get("extensions") or {}),
        ("data.assets", residual_data.get("assets") or {}),
        ("data.character_book", residual_data.get("character_book") or {}),
    ):
        if value:
            preserved.append({"name": label, "field": label, "detail": f"{len(value)} entr{'y' if len(value) == 1 else 'ies'}"})

    warnings: list[dict] = []
    if lorebook_preserved_only:
        warnings.append({
            "name": "character_book",
            "field": "data.character_book",
            "detail": "No usable entries; kept in card metadata only",
        })

    inert = preserved_but_inert(char_data)
    if inert:
        warnings.append({
            "name": "preserved but not executed",
            "field": "preserved_but_inert",
            "detail": f"{len(inert)} feature(s) are preserved and re-exported, but do not change how this app behaves",
        })

    return {
        "format": source_format,
        "spec": char_data.get("card_spec") or CARD_SPEC_V1,
        "spec_version": char_data.get("card_spec_version") or "",
        "warnings": warnings,
        "lost_fields": list(lost_fields or []),
        "preserved_fields": preserved,
        "preserved_but_inert": inert,
        "lorebook_converted": lorebook_created,
        "unknown_extensions_preserved": bool(residual_data.get("extensions")),
    }


def _avatar_bytes(character: Character) -> bytes | None:
    """Read the character's avatar for embedding in an exported PNG."""
    if not character.avatar_path or not os.path.exists(character.avatar_path):
        return None
    try:
        with open(character.avatar_path, "rb") as handle:
            return handle.read()
    except OSError as exc:  # pragma: no cover - unreadable avatar
        logger.warning("character_avatar_read_failed", character_id=character.id, error=str(exc))
        return None


def _safe_card_basename(character: Character) -> str:
    safe_name = "".join([c for c in (character.name or "") if c.isalpha() or c.isdigit() or c == " "]).rstrip()
    if not safe_name:
        safe_name = "character"
    return safe_name.replace(" ", "_")



@router.get("")
def list_characters(session: Session = Depends(get_session), character_repo: CharacterRepository = Depends(get_character_repo)):
    characters = character_repo.list()
    return [_character_to_dict(c) for c in characters]

@router.post("")
def create_character(payload: CharacterCreateRequest, session: Session = Depends(get_session)):
    require_world(session, payload.world_id)
    character = Character(**payload.model_dump())
    character.created_at = datetime.now(timezone.utc)
    character.updated_at = character.created_at
    session.add(character)
    session.commit()
    session.refresh(character)

    # Auto-create a collection for this character's scene images
    collection = Collection(
        name=f"{character.name}'s Gallery",
        color="#8B5CF6",
        description=f"Scene images generated for {character.name}",
        character_id=character.id,
    )
    session.add(collection)
    session.commit()

    # The second commit expires `character`; refresh so serialization works
    session.refresh(character)

    return _character_to_dict(character)

def _clone_lorebook(session: Session, lorebook_id: str, character_name: str) -> str | None:
    """Copy a lorebook and its entries, returning the new lorebook id."""
    source = session.get(Lorebook, lorebook_id)
    if not source:
        return None

    clone = Lorebook(
        name=f"{source.name} (Copy)" if source.name == character_name else source.name,
        description=source.description,
    )
    session.add(clone)
    session.commit()
    session.refresh(clone)

    for entry in session.exec(select(LorebookEntry).where(LorebookEntry.lorebook_id == source.id)).all():
        row = entry.model_dump(exclude={"id", "lorebook_id", "created_at", "updated_at"})
        session.add(LorebookEntry(lorebook_id=clone.id, **row))
    session.commit()
    return clone.id


def _create_embedded_lorebook(session: Session, character_book: dict | None) -> str | None:
    """Materialize an embedded `character_book` as a Lorebook, returning its id.

    The card keeps the original book verbatim in `card_metadata`, so this is a
    functional copy: dropping it later loses nothing from the card itself.
    """
    mapped = lorebook_from_character_book(character_book)
    if not mapped:
        return None

    book_kwargs, entry_kwargs = mapped
    lorebook = Lorebook(**book_kwargs)
    session.add(lorebook)
    session.commit()
    session.refresh(lorebook)

    for entry_kwargs_row in entry_kwargs:
        session.add(LorebookEntry(lorebook_id=lorebook.id, **entry_kwargs_row))
    session.commit()
    return lorebook.id


def _write_expression_images(
    session: Session, character: Character, assets: list[dict[str, str]]
) -> dict[str, str]:
    """Materialise a card's expression images as real expression files.

    A SillyTavern V3 card carries its expression images in `data.assets` as
    base64. They were preserved as inert JSON in the residual blob and never
    turned into images, so `Character.expressions` was always empty after an
    import, and an exported card never carried them back out.

    Returns `{emotion: path}` for the ones that were written.
    """
    if not assets:
        return {}
    out: dict[str, str] = {}
    base_dir = f"{app_config.settings.character_avatar_dir}/{character.id}/expressions"
    for asset in assets:
        emotion = asset.get("emotion") or ""
        if not emotion:
            continue
        try:
            raw = base64.b64decode(asset.get("data") or "", validate=True)
        except Exception:
            logger.warning("card_expression_decode_failed", emotion=emotion)
            continue
        if not raw:
            continue
        try:
            # The bytes have to be an actual image, or the expression picker
            # would serve something the browser cannot render.
            inspect_image(raw, field="expression", label=f"expression '{emotion}'")
        except Exception as exc:
            logger.warning("card_expression_not_an_image", emotion=emotion, error=str(exc))
            continue
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", emotion).strip("_") or "expression"
        try:
            os.makedirs(base_dir, exist_ok=True)
            path = os.path.join(base_dir, f"{safe}.png")
            with open(path, "wb") as handle:
                handle.write(raw)
        except OSError as exc:
            logger.warning("card_expression_write_failed", emotion=emotion, error=str(exc))
            continue
        out[emotion] = path
    return out


def _parse_card_upload(payload: bytes, filename: str) -> dict:
    """Parse an uploaded card WITHOUT writing anything.

    Shared by the one-shot import, the analyze preview and the commit, so the
    three cannot disagree about what a card contains.
    """
    is_png = payload[:8] == b"\x89PNG\r\n\x1a\n"
    is_charx = (filename or "").lower().endswith(".charx")
    is_bundle = (filename or "").lower().endswith(BUNDLE_SUFFIX) or bundle_is_bundle(payload)
    if is_png:
        # Card dimensions are bounded like any other image upload.
        inspect_image(payload, field="file", label="Character card")

    bundle: dict | None = None
    if is_bundle:
        try:
            bundle = parse_bundle(payload)
        except Exception as exc:
            raise ValidationError(f"Could not read the character bundle: {exc}") from exc
        char_data = card_fields_from_bundle(bundle)
        avatar_bytes = None
        archive_members: dict[str, bytes] = {}
        # The bundle's own character payload wins: it is this app's model of
        # the character, and the card inside it is the portable projection.
        for key, value in (bundle.get("character") or {}).items():
            if key in Character.model_fields and value is not None:
                char_data[key] = value
        # The world and the lorebook library are recreated by
        # `_restore_bundle`, so they must not be written onto the character
        # first — the rows do not exist yet, and the write would fail the
        # foreign key. The bundle restores them with their own ids.
        char_data.pop("world_id", None)
        char_data.pop("lorebook_ids", None)
    else:
        try:
            char_data, avatar_bytes, archive_members = parse_card_file(payload, filename)
        except CardParseError as exc:
            raise ValidationError(str(exc)) from exc

    return {
        "char_data": char_data,
        "avatar_bytes": avatar_bytes,
        "archive_members": archive_members,
        "bundle": bundle,
        "is_png": is_png,
        "is_charx": is_charx,
        "is_bundle": is_bundle,
    }


def _card_identity(char_data: dict) -> str | None:
    """The id of the character this card came from, if it says.

    A card exported from this app carries the character id in the app's own
    `data.extensions.tnhcomfy` namespace. SillyTavern preserves unknown
    extensions, so a card that has been through SillyTavern still carries it —
    which is what lets a re-import UPDATE the character instead of creating a
    second one with the same name.

    A card from anywhere else has no such identity and is a new character.
    """
    metadata = char_data.get("card_metadata") or {}
    residual = metadata.get("data") or {}
    extensions = residual.get("extensions")
    if not isinstance(extensions, dict):
        return None
    identity = extensions.get(APP_EXTENSION_KEY)
    if not isinstance(identity, dict):
        return None
    character_id = str(identity.get("character_id") or "").strip()
    return character_id or None


def _restore_bundle(session: Session, character: Character, bundle: dict) -> None:
    """Restore what a bundle carries that a card cannot.

    A bundle is this app's own model of a character, so the round trip is
    the whole point: the expressions, the world and its locations, the
    vault's lorebook library, and the chat history.
    """
    # Expression images.
    expressions = bundle.get("expressions") or {}
    if expressions:
        base_dir = f"{app_config.settings.character_avatar_dir}/{character.id}/expressions"
        written: dict[str, str] = {}
        for emotion, data in expressions.items():
            if not data:
                continue
            try:
                inspect_image(data, field="expression", label=f"expression '{emotion}'")
            except Exception as exc:
                logger.warning("bundle_expression_not_an_image", emotion=emotion, error=str(exc))
                continue
            safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(emotion)).strip("_") or "expression"
            try:
                os.makedirs(base_dir, exist_ok=True)
                path = os.path.join(base_dir, f"{safe}.png")
                with open(path, "wb") as handle:
                    handle.write(data)
                written[str(emotion)] = path
            except OSError as exc:
                logger.warning("bundle_expression_write_failed", emotion=emotion, error=str(exc))
        if written:
            character.expressions = written

    # The world and its locations.
    world_payload = bundle.get("world")
    if world_payload and not character.world_id:
        world_data = world_payload.get("world") or {}
        world_id = str(world_data.get("id") or "").strip()
        if world_id:
            world = session.get(World, world_id)
            if world is None:
                world = World(
                    id=world_id,
                    name=str(world_data.get("name") or "Imported World"),
                    description=world_data.get("description"),
                )
                session.add(world)
                session.flush()
            for location_data in world_payload.get("locations") or []:
                location_id = str(location_data.get("id") or "").strip()
                if not location_id or session.get(Location, location_id) is not None:
                    continue
                session.add(
                    Location(
                        id=location_id,
                        name=str(location_data.get("name") or "Imported Location"),
                        description=location_data.get("description"),
                        world_id=world.id,
                    )
                )
            session.flush()
            # Through the one sanctioned writer: `world_id` is written in
            # exactly one place, so a member cannot end up linked to a world
            # that does not count it.
            from services.world_ownership import link_to_world

            link_to_world(session, character, world.id)

    # The vault's lorebook library.
    lorebook_ids: list[str] = list(character.lorebook_ids or [])
    for payload in bundle.get("lorebooks") or []:
        book = payload.get("lorebook") or {}
        book_id = str(book.get("id") or "").strip()
        if not book_id or session.get(Lorebook, book_id) is not None:
            continue
        session.add(
            Lorebook(
                id=book_id,
                name=str(book.get("name") or "Imported Lorebook"),
                description=book.get("description"),
            )
        )
        session.flush()
        for entry_data in payload.get("entries") or []:
            entry_id = str(entry_data.get("id") or "").strip()
            if not entry_id or session.get(LorebookEntry, entry_id) is not None:
                continue
            session.add(
                LorebookEntry(
                    id=entry_id,
                    lorebook_id=book_id,
                    keys=list(entry_data.get("keys") or []),
                    content=entry_data.get("content") or "",
                    category=entry_data.get("category"),
                    tags=list(entry_data.get("tags") or []),
                    depth=int(entry_data.get("depth") or 4),
                    case_sensitive=bool(entry_data.get("case_sensitive", False)),
                    selective_logic=entry_data.get("selective_logic"),
                    probability=entry_data.get("probability"),
                    enabled=bool(entry_data.get("enabled", True)),
                    secondary_keys=list(entry_data.get("secondary_keys") or []),
                )
            )
        if book_id not in lorebook_ids:
            lorebook_ids.append(book_id)
    if lorebook_ids:
        character.lorebook_ids = lorebook_ids

    # The chat history.
    for message in bundle.get("chat") or []:
        chat_id = str(message.get("chat_id") or "").strip()
        if not chat_id:
            continue
        chat = session.get(Chat, chat_id)
        if chat is None:
            chat = Chat(
                id=chat_id,
                name=str(message.get("chat_name") or "Imported Chat"),
                character_id=character.id,
            )
            session.add(chat)
            session.flush()
        role = str(message.get("role") or "user")
        try:
            role_enum = MessageRole(role)
        except Exception:
            role_enum = MessageRole.USER
        session.add(
            Message(
                chat_id=chat.id,
                role=role_enum,
                kind=MessageKind.CHAR if role_enum == MessageRole.CHAR else MessageKind.USER,
                content=message.get("content") or "",
            )
        )
    session.flush()


@router.post("/import/analyze")
def analyze_character_card_import(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """What importing this card would do. Writes nothing.

    The import used to write immediately, so the only way to find out what a
    card would do was to do it — and re-importing a card created a SECOND
    character with the same name, silently, because the merge needed the
    identity that the card may or may not carry.

    This is the preview: what the card holds, whether it matches a character
    that already exists, and what the two scopes would create.
    """
    filename = file.filename or ""
    if not filename.lower().endswith(CARD_FILE_SUFFIXES):
        raise ValidationError(
            "Only PNG, JSON, CHARX and TNHComfy bundle files are supported"
        )
    payload = read_upload_file_bounded(file, MAX_CARD_BYTES)
    if not payload:
        raise ValidationError("Character card file is empty")

    parsed = _parse_card_upload(payload, filename)
    char_data = parsed["char_data"]
    if not char_data.get("name"):
        raise ValidationError("Character card must have a name")

    # The match, resolved the way the commit will resolve it.
    identity_id = _card_identity(char_data)
    existing = session.get(Character, identity_id) if identity_id else None
    if existing is None:
        # A card from elsewhere may still name a character that is here.
        existing = session.exec(
            select(Character).where(Character.name == str(char_data.get("name")))
        ).first()

    book = char_data.get("character_book") or {}
    expression_assets = take_expression_assets(dict(char_data))

    return {
        "format": (
            "png"
            if parsed["is_png"]
            else ("charx" if parsed["is_charx"] else ("bundle" if parsed["is_bundle"] else "json"))
        ),
        "spec": char_data.get("card_spec") or "",
        "spec_version": char_data.get("card_spec_version") or "",
        "name": char_data.get("name"),
        "description": char_data.get("description") or "",
        "personality": char_data.get("personality") or "",
        "scenario": char_data.get("scenario") or "",
        "first_mes": char_data.get("first_mes") or "",
        "mes_example": char_data.get("mes_example") or "",
        "alternate_greetings": list(char_data.get("alternate_greetings") or []),
        "creator": char_data.get("creator") or "",
        "character_version": char_data.get("character_version") or "",
        "match": {
            "character_id": existing.id if existing is not None else None,
            "name": existing.name if existing is not None else None,
            "action": "update" if existing is not None else "create",
            "by": "identity" if (identity_id and existing is not None) else ("name" if existing is not None else None),
        },
        "counts": {
            "lorebook_entries": len(book.get("entries") or []),
            "expressions": len(expression_assets),
            "alternate_greetings": len(char_data.get("alternate_greetings") or []),
        },
        "scopes": [
            {
                "id": "character",
                "label": "Just the character",
                "detail": "A character with the card's fields, its expressions and its embedded lorebook. No world.",
            },
            {
                "id": "world",
                "label": "Into a world",
                "detail": "The World Architect's depth: a world, its locations, a lorebook and the members — with the optional Vision and enrichment passes.",
            },
        ],
    }


@router.post("/import/commit")
async def commit_character_card_import(
    file: UploadFile = File(...),
    scope: str = Form("character"),
    match_action: str = Form("auto"),
    use_vision: bool = Form(False),
    session: Session = Depends(get_session),
):
    """Import a card, with the scope and the match already chosen.

    `scope` is `character` (the card's fields and nothing else) or `world`
    (the World Architect's blueprint). `match_action` is `auto` (update the
    character the card identifies, else create one), `update` or `create`.
    """
    filename = file.filename or ""
    if not filename.lower().endswith(CARD_FILE_SUFFIXES):
        raise ValidationError(
            "Only PNG, JSON, CHARX and TNHComfy bundle files are supported"
        )
    payload = read_upload_file_bounded(file, MAX_CARD_BYTES)
    if not payload:
        raise ValidationError("Character card file is empty")

    if (scope or "character").strip().lower() == "world":
        # The deep scope, delegated to the World Architect — one parser, one
        # blueprint, one commit. The card path does not reimplement it.
        from services.world_onboarding_service import (
            analyze_card_for_onboarding,
            commit_world_blueprint,
        )

        blueprint = await analyze_card_for_onboarding(
            session,
            file_bytes=payload,
            filename=filename,
            use_vision=use_vision,
        )
        result = await asyncio.to_thread(
            commit_world_blueprint, session, blueprint
        )
        return {"scope": "world", "blueprint": blueprint, "result": result}

    if (match_action or "auto").strip().lower() == "create":
        # Explicitly create a new character even if the card names one.
        parsed = _parse_card_upload(payload, filename)
        char_data = parsed["char_data"]
        char_data.pop("id", None)
        metadata = char_data.get("card_metadata")
        if isinstance(metadata, dict):
            extensions = metadata.get("data", {}).get("extensions")
            if isinstance(extensions, dict):
                extensions.pop(APP_EXTENSION_KEY, None)
        return _import_card_payload(session, payload, filename, force_new=True)

    return _import_card_payload(session, payload, filename, force_new=False)


def _import_card_payload(
    session: Session, payload: bytes, filename: str, *, force_new: bool = False
) -> dict:
    """The one-shot import, shared by the old route and the commit route."""
    parsed = _parse_card_upload(payload, filename)
    char_data = parsed["char_data"]
    if force_new:
        char_data.pop("id", None)
        metadata = char_data.get("card_metadata")
        if isinstance(metadata, dict):
            extensions = (metadata.get("data") or {}).get("extensions")
            if isinstance(extensions, dict):
                extensions.pop(APP_EXTENSION_KEY, None)
    return _import_parsed_card(session, parsed)


@router.post("/import")
def import_character_card(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    filename = file.filename or ""
    if not filename.lower().endswith(CARD_FILE_SUFFIXES):
        raise ValidationError(
            "Only PNG, JSON, CHARX and TNHComfy bundle files are supported"
        )

    # Bounded read: a card is a few hundred KB, so a huge body is refused after
    # the first over-limit chunk instead of being held in memory.
    payload = read_upload_file_bounded(file, MAX_CARD_BYTES)

    if not payload:
        raise ValidationError("Character card file is empty")

    parsed = _parse_card_upload(payload, filename)
    return _import_parsed_card(session, parsed)


def _import_parsed_card(session: Session, parsed: dict) -> dict:
    """Write a parsed card into the vault.

    Shared by the one-shot import, the commit route and the World
    Architect's card path, so the three cannot disagree about what a card
    creates.
    """
    char_data = parsed["char_data"]
    avatar_bytes = parsed["avatar_bytes"]
    archive_members = parsed["archive_members"]
    bundle = parsed["bundle"]

    if not char_data.get("name"):
        raise ValidationError("Character card must have a name")

    character_book = char_data.pop("character_book", None)
    known_fields = set(Character.model_fields)

    # MERGE, not duplicate.
    #
    # A card exported from this app carries the character's id in the app's
    # own extension namespace, and SillyTavern preserves unknown extensions —
    # so a card that has been through SillyTavern still says which character
    # it is. Re-importing it UPDATES that character instead of creating a
    # second one with the same name.
    #
    # A card from anywhere else has no such identity, and is a new character.
    identity_id = _card_identity(char_data)
    existing = session.get(Character, identity_id) if identity_id else None
    if existing is not None:
        character = existing
        for key, value in char_data.items():
            if key in known_fields and key not in ("id", "created_at") and value is not None:
                setattr(character, key, value)
        character.updated_at = datetime.now(timezone.utc)
    else:
        character = Character(**{k: v for k, v in char_data.items() if k in known_fields and v})
        character.created_at = datetime.now(timezone.utc)
        character.updated_at = character.created_at

    # A card can name a voice model. If this vault does not have it, the
    # INSERT failed the foreign key and the WHOLE import was lost to a 500.
    #
    # The value is dropped instead, and reported, because a card from another
    # vault is a normal thing to import and "the voice model it referenced is
    # not here" is a fact about the card, not a reason to refuse it.
    dropped_voice_model = None
    if character.voice_model_id:
        exists = session.get(VoiceModel, character.voice_model_id)
        if exists is None:
            dropped_voice_model = character.voice_model_id
            character.voice_model_id = None

    try:
        session.add(character)
        session.commit()
        session.refresh(character)
    except Exception as exc:
        session.rollback()
        # A constraint violation on a card-supplied value is a fact about the
        # card, not a server fault. Answer 400 with the reason rather than
        # letting the generic handler turn it into a 500.
        logger.warning("character_card_import_write_failed", error=str(exc))
        raise ValidationError(f"The card could not be imported: {exc}") from exc

    lorebook_id = _create_embedded_lorebook(session, character_book)
    if lorebook_id:
        character.embedded_lorebook_id = lorebook_id

    # Save avatar from card image (JSON cards carry no image)
    if avatar_bytes:
        # The card PNG carries the whole character in a `chara`/`ccv3` text
        # chunk, so the file that is ALSO the avatar is mostly card payload —
        # served to every browser that loads the avatar, and re-read on every
        # request. The chunks come back on export, which writes its own.
        avatar_bytes = strip_png_text_chunks(avatar_bytes)
        os.makedirs(f"{app_config.settings.character_avatar_dir}/{character.id}", exist_ok=True)
        avatar_path = f"{app_config.settings.character_avatar_dir}/{character.id}/avatar.png"
        with open(avatar_path, "wb") as f:
            f.write(avatar_bytes)
        character.avatar_path = avatar_path

    # SillyTavern expression images, turned into real expression files.
    expression_assets = take_expression_assets(char_data)
    # A CHARX references its assets BY PATH rather than carrying base64, so
    # the archive's members are resolved here.
    for asset in expression_assets:
        reference = asset.get("data") or ""
        if reference in archive_members:
            asset["data"] = base64.b64encode(archive_members[reference]).decode("ascii")
    if expression_assets:
        # `session.refresh()` above re-read the row, so `character.card_metadata`
        # is a FRESH object and no longer the same dict `char_data` holds.
        # Without this the residual keeps the base64 of images that are now
        # real expression files, and every export carries them twice.
        character.card_metadata = char_data.get("card_metadata")
        expressions = _write_expression_images(session, character, expression_assets)
        if expressions:
            character.expressions = expressions

    if bundle is not None:
        _restore_bundle(session, character, bundle)

    character.updated_at = datetime.now(timezone.utc)
    session.add(character)
    session.commit()

    # Auto-create collection
    collection = Collection(
        name=f"{character.name}'s Gallery",
        color="#8B5CF6",
        description=f"Scene images generated for {character.name}",
        character_id=character.id,
    )
    session.add(collection)
    session.commit()

    # The final commit expires `character`; refresh so serialization works
    session.refresh(character)

    report = _compatibility_report(
        char_data,
        source_format=(
            "png"
            if parsed["is_png"]
            else ("charx" if parsed["is_charx"] else ("bundle" if parsed["is_bundle"] else "json"))
        ),
        lorebook_created=bool(lorebook_id),
        lorebook_preserved_only=bool(character_book) and not lorebook_id,
        lost_fields=(
            [
                {
                    "name": "extensions.voice_model_id",
                    "field": "voice_model_id",
                    "detail": f"no voice model with id '{dropped_voice_model}' in this vault",
                }
            ]
            if dropped_voice_model
            else []
        ),
    )
    # The character dict is returned unchanged (existing consumers read id/name/...)
    # with the compatibility report as an extra key.
    return {**_character_to_dict(character), "compatibility": report}

@router.get("/{character_id}/expressions")
def get_character_expressions(character_id: str, session: Session = Depends(get_session), character_repo: CharacterRepository = Depends(get_character_repo)):
    character = character_repo.get(character_id)
    if not character:
        raise NotFoundError("Character", character_id)
    return {
        "expressions": character.expressions or {},
        "expressions_lora": character.expressions_lora or [],
    }

class ExpressionUpdateRequest(BaseModel):
    name: str
    image_path: str | None = None
    lora: str | None = None

# The POST/PUT/DELETE `/characters/{id}/expressions` sub-routes were removed.
#
# They were a SECOND write path to the same two columns that
# `PATCH /characters/{id}` already owns, and the two did not agree: the
# sub-routes merged one expression at a time and appended LoRAs, while PATCH
# replaced the whole map. The frontend used PATCH (`hooks/useExpressions.js`)
# and the sub-routes had no consumer, so the renderer had to pick a winner
# between two shapes of the same data at read time
# (`components/chat/ExpressionSelector.jsx`). PATCH is now the only writer.
# Reading the expressions is still supported: `GET /{character_id}/expressions`.

@router.get("/{character_id}")
def get_character(character_id: str, session: Session = Depends(get_session), character_repo: CharacterRepository = Depends(get_character_repo)):
    character = character_repo.get(character_id)
    if not character:
        raise NotFoundError("Character", character_id)
    return _character_to_dict(character)

@router.put("/{character_id}")
def update_character(character_id: str, character_update: CharacterUpdateRequest, session: Session = Depends(get_session), character_repo: CharacterRepository = Depends(get_character_repo)):
    """Full update — replaces all provided fields (omitted fields are left unchanged)."""
    character = character_repo.get(character_id)
    if not character:
        raise NotFoundError("Character", character_id)

    update_data = character_update.model_dump(exclude_unset=True)
    if "lorebook_ids" in update_data and update_data["lorebook_ids"] is not None:
        update_data["lorebook_ids"] = _resolve_lorebook_ids(session, update_data["lorebook_ids"])
    apply_world_id(session, character, update_data)
    update_data.pop("world_id", None)
    for key, value in update_data.items():
        setattr(character, key, value)

    character.updated_at = datetime.now(timezone.utc)
    session.add(character)
    session.commit()
    session.refresh(character)
    return _character_to_dict(character)


def _resolve_lorebook_ids(session: Session, lorebook_ids: list[str]) -> list[str]:
    """Dedupe and verify a character's lorebook links.

    An id that does not resolve is a 404 rather than a stored one: these are
    read on every prompt build now, so a dangling id would become a per-turn
    lookup that silently finds nothing.
    """
    from core.entities import Lorebook

    resolved: list[str] = []
    for lorebook_id in lorebook_ids:
        if not lorebook_id or lorebook_id in resolved:
            continue
        if session.get(Lorebook, lorebook_id) is None:
            raise NotFoundError("Lorebook", lorebook_id)
        resolved.append(lorebook_id)
    return resolved


@router.patch("/{character_id}")
def patch_character(character_id: str, character_update: CharacterUpdateRequest, session: Session = Depends(get_session), character_repo: CharacterRepository = Depends(get_character_repo)):
    """Partial update — only updates fields explicitly provided (non-None values).

    `world_id` is the exception, and it is the exception on purpose: it is
    ownership, not a column assignment. It goes through `apply_world_id`, so
    an unknown world id is a 404 rather than an `IntegrityError` (which was a
    500, and left the session poisoned), and an explicit `null` DETACHES the
    character from its world. It used to fall through the generic `setattr`
    loop below, which is why `PATCH {"world_id": "does-not-exist"}` answered
    500 while `PUT` answered 404, and why a character could never be detached
    at all.
    """
    character = character_repo.get(character_id)
    if not character:
        raise NotFoundError("Character", character_id)

    update_data = character_update.model_dump(exclude_unset=True)
    if "lorebook_ids" in update_data and update_data["lorebook_ids"] is not None:
        update_data["lorebook_ids"] = _resolve_lorebook_ids(session, update_data["lorebook_ids"])
    # `apply_world_id` reads the key BEFORE the None-filter below, so an
    # explicit null still reaches it — that is the detach.
    apply_world_id(session, character, update_data)
    update_data.pop("world_id", None)
    # For PATCH, also skip None values so we never overwrite with null
    update_data = {k: v for k, v in update_data.items() if v is not None}
    for key, value in update_data.items():
        setattr(character, key, value)

    character.updated_at = datetime.now(timezone.utc)
    session.add(character)
    session.commit()
    session.refresh(character)
    return _character_to_dict(character)

@router.delete("/{character_id}")
def delete_character(character_id: str, session: Session = Depends(get_session), character_repo: CharacterRepository = Depends(get_character_repo)):
    character = character_repo.get(character_id)
    if not character:
        raise NotFoundError("Character", character_id)
    
    scrub_entity_references(session, "character", character_id)
    session.delete(character)
    session.commit()
    return {"message": "Character deleted"}

class CharacterReorderRequest(BaseModel):
    """Reorder characters by specifying their IDs in the desired order."""

    character_ids: list[str]

@router.post("/reorder")
def reorder_characters(
    request: CharacterReorderRequest,
    session: Session = Depends(get_session),
    character_repo: CharacterRepository = Depends(get_character_repo),
):
    """Persist a new sort order from a drag-and-drop reorder in the UI."""

    ids = list(dict.fromkeys(request.character_ids))
    existing = {c.id: c for c in session.exec(select(Character).where(Character.id.in_(ids))).all()}
    missing = [cid for cid in ids if cid not in existing]
    if missing:
        raise NotFoundError("Character", missing[0])

    now = datetime.now(timezone.utc)
    for index, cid in enumerate(ids):
        character = existing[cid]
        character.sort_order = index
        character.updated_at = now
        session.add(character)

    session.commit()
    return {"updated": len(ids)}

@router.post("/{character_id}/avatar")
async def upload_avatar(character_id: str, file: UploadFile = File(...), session: Session = Depends(get_session), character_repo: CharacterRepository = Depends(get_character_repo)):
    # The upload read below is awaited, so the two session writes around it move
    # to a worker thread.
    await asyncio.to_thread(_require_character, character_repo, character_id)

    # Avatars are rendered inline everywhere, so they are bounded tightly and
    # must be a real image (an .html or .svg renamed to .png is rejected).
    require_declared_size(file, MAX_AVATAR_BYTES)
    content = await read_upload_bounded(file, MAX_AVATAR_BYTES)
    inspect_image(content, field="file", label="Avatar")

    os.makedirs(f"{app_config.settings.character_avatar_dir}/{character_id}", exist_ok=True)
    avatar_path = f"{app_config.settings.character_avatar_dir}/{character_id}/avatar.png"

    with open(avatar_path, "wb") as buffer:
        buffer.write(content)

    await asyncio.to_thread(_save_character_avatar, session, character_repo, character_id, avatar_path)

    return {"message": "Avatar uploaded", "avatar_path": avatar_path, "has_avatar": True}


def _require_character(character_repo: CharacterRepository, character_id: str) -> None:
    """404 before the upload is consumed, off the event loop."""
    if not character_repo.get(character_id):
        raise NotFoundError("Character", character_id)


def _save_character_avatar(
    session: Session,
    character_repo: CharacterRepository,
    character_id: str,
    avatar_path: str,
) -> None:
    """Persist the stored avatar path on the character."""
    character = character_repo.get(character_id)
    character.avatar_path = avatar_path
    character.updated_at = datetime.now(timezone.utc)
    session.add(character)
    session.commit()
    session.refresh(character)

from pydantic import BaseModel
from typing import Optional

class AnimateAvatarRequest(BaseModel):
    prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    checkpoint: Optional[str] = None

@router.post("/{character_id}/avatar/animate")
async def generate_animated_avatar(
    character_id: str,
    request: AnimateAvatarRequest,
    session: Session = Depends(get_session),
    character_repo: CharacterRepository = Depends(get_character_repo)
):
    """Enqueue a ComfyUI AnimateDiff video generation job for this character's avatar."""
    from services.job_submission_service import submit_job

    # The prompt is built from session-loaded character columns, and only the
    # job creation below is awaited.
    character_id, workflow, metadata = await asyncio.to_thread(
        _animate_avatar_prep_sync, character_repo, character_id, request
    )

    # Through the shared submission path, not a bare `create_job` +
    # `enqueue`: it validates the workflow against what is installed first, so a
    # missing AnimateDiff motion model surfaces as a clean
    # `MissingModelsError` (400) instead of a job that dies inside the worker.
    job = await submit_job(session, workflow, metadata, task_type="image")

    return {"message": "Animation job enqueued", "job_id": job.id}


def _animate_avatar_prep_sync(
    character_repo: CharacterRepository,
    character_id: str,
    request: "AnimateAvatarRequest",
) -> tuple[str, dict, dict]:
    """Validate the character and build the AnimateDiff workflow.

    Synchronous on purpose: the job creation is awaited, so the route stays
    `async def` and these reads would otherwise run on the event loop.
    """
    character = character_repo.get(character_id)
    if not character:
        raise NotFoundError("Character", character_id)

    prompt = request.prompt
    if not prompt:
        prompt = f"portrait of {character.name}, {character.description}, {character.personality}, highly detailed, cinematic lighting"

    from core.workflow_builder import build_video_job_workflow

    workflow, metadata = build_video_job_workflow(
        prompt=prompt,
        negative=request.negative_prompt or "worst quality, low quality, bad anatomy, bad hands, missing fingers, extra limbs, text, watermark",
        checkpoint=request.checkpoint or DEFAULT_CHECKPOINT,
        width=512,
        height=512,
        frames=16,
        source="character_avatar_animate",
        character_id=character.id,
    )
    return character.id, workflow, metadata


class GenerateExpressionsRequest(BaseModel):
    checkpoint: str | None = None
    lora: str | None = None
    emotions: list[str] = Field(
        default_factory=lambda: ["neutral", "happy", "angry", "blushing", "sad", "serious"]
    )
    base_prompt: str | None = None
    negative_prompt: str | None = None
    seed: int | None = None


@router.post("/{character_id}/expressions/generate")
async def generate_character_expressions(
    character_id: str,
    request: GenerateExpressionsRequest,
    session: Session = Depends(get_session),
    character_repo: CharacterRepository = Depends(get_character_repo),
):
    """Enqueue batch image generation for character emotional expression avatars."""
    from services.job_submission_service import submit_job
    from core.workflow_builder import GeneratorOptions, LoraOption, WorkflowBuilder

    character = character_repo.get(character_id)
    if not character:
        raise NotFoundError("Character", character_id)

    checkpoint = request.checkpoint or character.checkpoint or DEFAULT_CHECKPOINT
    lora_name = request.lora or character.lora
    loras = [LoraOption(name=lora_name, strength=0.85)] if lora_name else []

    base = request.base_prompt or f"portrait of {character.name}, {character.description or ''}"
    neg = request.negative_prompt or "worst quality, low quality, bad anatomy, bad hands, blurry"
    seed = request.seed if request.seed is not None else random.randint(1, 2147483647)

    job_ids = []
    builder = WorkflowBuilder()

    for emotion in request.emotions:
        prompt = f"{base}, {emotion} expression, facing viewer, close-up, masterpiece, best quality"
        opts = GeneratorOptions(
            prompt=prompt,
            negativePrompt=neg,
            checkpoint=checkpoint,
            loras=loras,
            seed=seed,
            steps=20,
            cfg=7.0,
            width=512,
            height=512,
            filenamePrefix=f"Char_{character.id}_{emotion}",
        )
        workflow = builder.build(opts)
        meta = {
            "source": "character_expression_generate",
            "character_id": character.id,
            "emotion": emotion,
            "checkpoint": checkpoint,
        }
        job = await submit_job(session, workflow, meta, task_type="image")
        job_ids.append(job.id)

    return {
        "message": f"Enqueued {len(job_ids)} expression generation jobs",
        "job_ids": job_ids,
        "emotions": request.emotions,
        "seed": seed,
    }

@router.get("/{character_id}/avatar")
def get_avatar(character_id: str, session: Session = Depends(get_session), character_repo: CharacterRepository = Depends(get_character_repo)):
    character = character_repo.get(character_id)
    if not character or not character.avatar_path or not os.path.exists(character.avatar_path):
        raise NotFoundError("Avatar", character_id)
    
    media_type = "video/webp" if character.avatar_path.lower().endswith(".webp") else None
    response = FileResponse(character.avatar_path, media_type=media_type)
    response.headers["Cache-Control"] = "no-cache"
    return response


@router.post("/{character_id}/clone", response_model=Character)
def clone_character(character_id: str, session: Session = Depends(get_session), character_repo: CharacterRepository = Depends(get_character_repo)):
    character = character_repo.get(character_id)
    if not character:
        raise NotFoundError("Character", character_id)

    # The embedded lorebook is copied rather than shared, so edits to either
    # character's book stay independent.
    embedded_lorebook_id = character.embedded_lorebook_id

    char_dict = character.model_dump(
        exclude={"id", "created_at", "updated_at", "avatar_path", "embedded_lorebook_id"}
    )
    char_dict["name"] = f"{character.name} (Copy)"

    new_char = Character(**char_dict)
    new_char.created_at = datetime.now(timezone.utc)
    new_char.updated_at = new_char.created_at
    if embedded_lorebook_id:
        new_char.embedded_lorebook_id = _clone_lorebook(session, embedded_lorebook_id, character.name)
    session.add(new_char)
    session.commit()
    session.refresh(new_char)
    
    if character.avatar_path and os.path.exists(character.avatar_path):
        os.makedirs(f"{app_config.settings.character_avatar_dir}/{new_char.id}", exist_ok=True)
        new_avatar_path = f"{app_config.settings.character_avatar_dir}/{new_char.id}/avatar.png"
        shutil.copy2(character.avatar_path, new_avatar_path)
        new_char.avatar_path = new_avatar_path
        session.add(new_char)
        session.commit()
        session.refresh(new_char)
        
    # Auto-create collection
    collection = Collection(
        name=f"{new_char.name}'s Gallery",
        color="#8B5CF6",
        description=f"Scene images generated for {new_char.name}",
        character_id=new_char.id,
    )
    session.add(collection)
    session.commit()

    # The second commit expires `new_char`; refresh so serialization works
    session.refresh(new_char)

    return _character_to_dict(new_char)


def _bundle_world_payload(session: Session, character: Character) -> dict | None:
    """The character's world and its locations, for the bundle."""
    if not character.world_id:
        return None
    world = session.get(World, character.world_id)
    if world is None:
        return None
    locations = session.exec(
        select(Location).where(Location.world_id == character.world_id)
    ).all()
    return {
        "world": world.model_dump(),
        "locations": [location.model_dump() for location in locations],
    }


def _bundle_lorebook_payloads(session: Session, character: Character) -> list[dict]:
    """The vault's lorebook library for this character, for the bundle."""
    payloads: list[dict] = []
    for lorebook_id in character.lorebook_ids or []:
        lorebook = session.get(Lorebook, lorebook_id)
        if lorebook is None:
            continue
        entries = session.exec(
            select(LorebookEntry).where(LorebookEntry.lorebook_id == lorebook_id)
        ).all()
        payloads.append(
            {
                "lorebook": lorebook.model_dump(),
                "entries": [entry.model_dump() for entry in entries],
            }
        )
    return payloads


def _bundle_chat_payloads(session: Session, character: Character) -> list[dict]:
    """The character's chat history, for the bundle."""
    chats = session.exec(select(Chat).where(Chat.character_id == character.id)).all()
    payloads: list[dict] = []
    for chat in chats:
        messages = session.exec(
            select(Message).where(Message.chat_id == chat.id).order_by(Message.created_at)
        ).all()
        for message in messages:
            payloads.append(
                {
                    "chat_id": chat.id,
                    "chat_name": chat.name,
                    "role": message.role.value if hasattr(message.role, "value") else str(message.role),
                    "content": message.content,
                    "created_at": message.created_at.isoformat() if message.created_at else None,
                }
            )
    return payloads


@router.get("/{character_id}/export/preview")
def export_character_preview(
    character_id: str,
    session: Session = Depends(get_session),
    character_repo: CharacterRepository = Depends(get_character_repo),
):
    """What an export of this character can and cannot carry.

    The export itself is a PNG or an archive, so it has nowhere to say "this
    character has six expressions and a voice model and the card has neither".
    This is that list, so the export menu can show it BEFORE the download
    rather than the user discovering it by opening the card elsewhere.
    """
    character = character_repo.get(character_id)
    if not character:
        raise NotFoundError("Character", character_id)

    features = not_portable_features(session, character)
    return {
        "character_id": character.id,
        "name": character.name,
        "formats": list(CARD_EXPORT_FORMATS),
        "not_portable": features,
        "not_portable_summary": portable_summary(features),
        "lossless": not features,
    }


@router.get("/{character_id}/export")
def export_character(
    character_id: str,
    export_format: str = Query(
        default="default",
        alias="format",
        description="default/v2: PNG with chara + ccv3 chunks. v3: canonical V3 spec in ccv3. json: plain JSON card. charx: ZIP card with avatar assets. bundle: the TNHComfy bundle, which carries what a card cannot.",
    ),
    include: str = Query(
        default="",
        description="For format=bundle: a comma-separated list of the optional sections to carry (expressions, voice, generation, world, lorebooks, chat).",
    ),
    session: Session = Depends(get_session),
    character_repo: CharacterRepository = Depends(get_character_repo),
):
    """Export a character as a SillyTavern card, or as a TNHComfy bundle.

    PNG exports always carry the backward-compatible `chara` chunk plus the V3
    `ccv3` chunk, so old and new clients both read the same file. Fields with no
    column in the vault are written back from `card_metadata`, which makes
    import -> export lossless.

    The BUNDLE is the other answer to the same question. A card has a small
    fixed vocabulary; this app's characters have expression image sets, a
    voice binding, a world with locations, a lorebook library, a gallery and
    chats. The bundle carries those, and the card alongside, so one file is
    both a SillyTavern card and a complete TNHComfy character.
    """
    character = character_repo.get(character_id)
    if not character:
        raise NotFoundError("Character", character_id)

    fmt = (export_format or "default").strip().lower()
    if fmt not in CARD_EXPORT_FORMATS:
        raise ValidationError(f"Unsupported card format '{export_format}'. Use one of: {', '.join(CARD_EXPORT_FORMATS)}")

    basename = _safe_card_basename(character)

    if fmt == "bundle":
        wanted = [s.strip() for s in (include or "").split(",") if s.strip()]
        bundle = build_bundle(
            character,
            session=session,
            include=wanted,
            avatar_bytes=_avatar_bytes(character),
            world_payload=_bundle_world_payload(session, character) if "world" in wanted else None,
            lorebook_payloads=_bundle_lorebook_payloads(session, character) if "lorebooks" in wanted else None,
            chat_payloads=_bundle_chat_payloads(session, character) if "chat" in wanted else None,
        )
        return Response(
            content=bundle,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{basename}.tnhzip"'},
        )

    if fmt == "json":
        payload = build_card_payload(character, version=CARD_SPEC_V3)
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{basename}.json"'},
        )

    if fmt == "charx":
        return Response(
            content=encode_charx_card(character, _avatar_bytes(character)),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{basename}.charx"'},
        )

    # `v3` pins the ccv3 payload to the canonical V3 spec even for characters
    # that were created or imported as V1/V2.
    png_bytes = encode_png_card(
        _avatar_bytes(character),
        character,
        include_v3=True,
        v3_spec=CARD_SPEC_V3 if fmt == "v3" else None,
    )
    suffix = "_v3.png" if fmt == "v3" else "_v2.png"
    return StreamingResponse(
        BytesIO(png_bytes),
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{basename}{suffix}"'},
    )
