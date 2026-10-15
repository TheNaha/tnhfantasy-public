import asyncio
import json
import os
import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from io import BytesIO
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from api.deps import get_session, get_character_repo
from infrastructure.logging import get_logger
from infrastructure.repositories.character_repo import CharacterRepository
from services.reference_cleanup import scrub_entity_references
from services.world_ownership import apply_world_id, require_world
from core.workflow_builder import DEFAULT_CHECKPOINT
from core.character_cards import (
    CARD_SPEC_V1,
    CARD_SPEC_V3,
    CardParseError,
    build_card_payload,
    encode_charx_card,
    encode_png_card,
    lorebook_from_character_book,
    parse_card_file,
)
from core.entities import Character, Collection, Lorebook, LorebookEntry
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

CARD_FILE_SUFFIXES = (".png", ".json", ".charx")
CARD_EXPORT_FORMATS = ("default", "v2", "v3", "json", "charx")


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
) -> dict:
    """Describe what an import kept, for the UI's compatibility report.

    `lost_fields` stays empty while the codec is lossless; anything the vault
    cannot use functionally (an embedded book with no usable entries) is
    reported as a warning plus the preserved location instead of being dropped
    silently.
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

    return {
        "format": source_format,
        "spec": char_data.get("card_spec") or CARD_SPEC_V1,
        "spec_version": char_data.get("card_spec_version") or "",
        "warnings": warnings,
        "lost_fields": [],
        "preserved_fields": preserved,
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


@router.post("/import")
def import_character_card(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    filename = file.filename or ""
    if not filename.lower().endswith(CARD_FILE_SUFFIXES):
        raise ValidationError("Only PNG and JSON character cards are supported")

    # Bounded read: a card is a few hundred KB, so a huge body is refused after
    # the first over-limit chunk instead of being held in memory.
    payload = read_upload_file_bounded(file, MAX_CARD_BYTES)

    if not payload:
        raise ValidationError("Character card file is empty")

    is_png = payload[:8] == b"\x89PNG\r\n\x1a\n"
    if is_png:
        # Card dimensions are bounded like any other image upload.
        inspect_image(payload, field="file", label="Character card")

    try:
        char_data, avatar_bytes = parse_card_file(payload, filename)
    except CardParseError as exc:
        raise ValidationError(str(exc)) from exc

    if not char_data.get("name"):
        raise ValidationError("Character card must have a name")

    character_book = char_data.pop("character_book", None)
    known_fields = set(Character.model_fields)
    character = Character(**{k: v for k, v in char_data.items() if k in known_fields and v})
    character.created_at = datetime.now(timezone.utc)
    character.updated_at = character.created_at
    session.add(character)
    session.commit()
    session.refresh(character)

    lorebook_id = _create_embedded_lorebook(session, character_book)
    if lorebook_id:
        character.embedded_lorebook_id = lorebook_id

    # Save avatar from card image (JSON cards carry no image)
    if avatar_bytes:
        os.makedirs(f"{app_config.settings.character_avatar_dir}/{character.id}", exist_ok=True)
        avatar_path = f"{app_config.settings.character_avatar_dir}/{character.id}/avatar.png"
        with open(avatar_path, "wb") as f:
            f.write(avatar_bytes)
        character.avatar_path = avatar_path

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
        source_format="png" if is_png else "json",
        lorebook_created=bool(lorebook_id),
        lorebook_preserved_only=bool(character_book) and not lorebook_id,
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

@router.post("/{character_id}/expressions")
def add_character_expression(character_id: str, req: ExpressionUpdateRequest, session: Session = Depends(get_session), character_repo: CharacterRepository = Depends(get_character_repo)):
    character = character_repo.get(character_id)
    if not character:
        raise NotFoundError("Character", character_id)
    expressions = dict(character.expressions or {})
    expressions[req.name] = req.image_path or ""
    character.expressions = expressions
    if req.lora:
        loras = list(character.expressions_lora or [])
        if req.lora not in loras:
            loras.append(req.lora)
            character.expressions_lora = loras
    character.updated_at = datetime.now(timezone.utc)
    session.add(character)
    session.commit()
    session.refresh(character)
    return _character_to_dict(character)

@router.put("/{character_id}/expressions/{name}")
def update_character_expression(character_id: str, name: str, req: ExpressionUpdateRequest, session: Session = Depends(get_session), character_repo: CharacterRepository = Depends(get_character_repo)):
    character = character_repo.get(character_id)
    if not character:
        raise NotFoundError("Character", character_id)
    expressions = dict(character.expressions or {})
    if name not in expressions:
        raise NotFoundError("Expression", name)
    expressions[name] = req.image_path or ""
    character.expressions = expressions
    character.updated_at = datetime.now(timezone.utc)
    session.add(character)
    session.commit()
    session.refresh(character)
    return _character_to_dict(character)

@router.delete("/{character_id}/expressions/{name}")
def delete_character_expression(character_id: str, name: str, session: Session = Depends(get_session), character_repo: CharacterRepository = Depends(get_character_repo)):
    character = character_repo.get(character_id)
    if not character:
        raise NotFoundError("Character", character_id)
    expressions = dict(character.expressions or {})
    if name not in expressions:
        raise NotFoundError("Expression", name)
    expressions.pop(name, None)
    character.expressions = expressions
    character.updated_at = datetime.now(timezone.utc)
    session.add(character)
    session.commit()
    session.refresh(character)
    return _character_to_dict(character)

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
    """Partial update — only updates fields explicitly provided (non-None values)."""
    character = character_repo.get(character_id)
    if not character:
        raise NotFoundError("Character", character_id)

    update_data = character_update.model_dump(exclude_unset=True)
    if "lorebook_ids" in update_data and update_data["lorebook_ids"] is not None:
        update_data["lorebook_ids"] = _resolve_lorebook_ids(session, update_data["lorebook_ids"])
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


@router.get("/{character_id}/export")
def export_character(
    character_id: str,
    export_format: str = Query(
        default="default",
        alias="format",
        description="default/v2: PNG with chara + ccv3 chunks. v3: canonical V3 spec in ccv3. json: plain JSON card. charx: ZIP card with avatar assets.",
    ),
    session: Session = Depends(get_session),
    character_repo: CharacterRepository = Depends(get_character_repo),
):
    """Export a character as a SillyTavern card.

    PNG exports always carry the backward-compatible `chara` chunk plus the V3
    `ccv3` chunk, so old and new clients both read the same file. Fields with no
    column in the vault are written back from `card_metadata`, which makes
    import -> export lossless.
    """
    character = character_repo.get(character_id)
    if not character:
        raise NotFoundError("Character", character_id)

    fmt = (export_format or "default").strip().lower()
    if fmt not in CARD_EXPORT_FORMATS:
        raise ValidationError(f"Unsupported card format '{export_format}'. Use one of: {', '.join(CARD_EXPORT_FORMATS)}")

    basename = _safe_card_basename(character)

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
