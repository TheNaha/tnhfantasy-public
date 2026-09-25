import base64
import json
import os
import shutil
import struct
import zlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from io import BytesIO
from PIL import Image, PngImagePlugin
from pydantic import BaseModel
from sqlmodel import Session, select

from api.deps import get_session, get_character_repo
from infrastructure.logging import get_logger
from infrastructure.repositories.character_repo import CharacterRepository
from services.reference_cleanup import scrub_entity_references
from core.entities import Character, Collection
from core.exceptions import NotFoundError, ValidationError
import config as app_config

logger = get_logger("characters_route")
router = APIRouter()


class CharacterUpdateRequest(BaseModel):
    """Strict optional-field update model for PUT and PATCH endpoints."""
    name: str | None = None
    description: str | None = None
    personality: str | None = None
    scenario: str | None = None
    first_mes: str | None = None
    mes_example: str | None = None
    creator_notes: str | None = None
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
    sort_order: int | None = None


def _character_to_dict(character: Character) -> dict:
    """Serialize a Character with the computed has_avatar field."""
    d = character.model_dump()
    d["has_avatar"] = character.avatar_path is not None and os.path.exists(character.avatar_path)
    return d



def _parse_png_chunks(data: bytes) -> dict[str, bytes]:
    """Extract tEXt/zTXt/iTXt chunks from PNG data, keyed by chunk name."""
    chunks = {}
    pos = 8  # Skip PNG signature
    while pos < len(data):
        if pos + 8 > len(data):
            break
        length = struct.unpack(">I", data[pos:pos+4])[0]
        chunk_type = data[pos+4:pos+8].decode("ascii", errors="replace")
        chunk_data = data[pos+8:pos+8+length]
        if chunk_type == "IEND":
            break
        if chunk_type in ("tEXt", "zTXt", "iTXt"):
            chunks[chunk_type] = chunk_data
        pos += 12 + length  # 4 length + 4 type + data + 4 CRC
    return chunks


def _decode_chara_payload(raw: bytes) -> dict | None:
    """Try to decode a chara/ccv3 tEXt chunk value into a dict."""
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return None

    # V2/V3: key=value format (keyword before null byte)
    if "\x00" in text:
        _, value = text.split("\x00", 1)
    else:
        value = text

    value = value.strip()
    if not value:
        return None

    # Candidate payloads: the raw text first (plain-JSON cards), then the
    # base64-decoded bytes, optionally zlib-decompressed (V2/V3 exports).
    candidates = [value]
    try:
        decoded = base64.b64decode(value)
        try:
            candidates.append(zlib.decompress(decoded).decode("utf-8", errors="replace"))
        except zlib.error:
            candidates.append(decoded.decode("utf-8", errors="replace"))
    except Exception as exc:
        logger.debug("chara_chunk_decode_failed", error=str(exc))

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def parse_character_card(png_bytes: bytes) -> dict:
    """Parse a SillyTavern V1/V2/V3 character card PNG into a dict of fields."""
    chunks = _parse_png_chunks(png_bytes)
    raw_chunks = {}
    for ct, cd in chunks.items():
        if ct == "tEXt":
            # tEXt: keyword\x00value
            sep = cd.find(b"\x00")
            if sep >= 0:
                keyword = cd[:sep].decode("ascii", errors="replace")
                raw_chunks[keyword] = cd[sep+1:]

    # Try ccv3 (V3) first, then chara (V2/V1)
    payload = None
    for key in ("ccv3", "chara"):
        if key in raw_chunks:
            payload = _decode_chara_payload(raw_chunks[key])
            if payload:
                break

    if not payload:
        raise ValidationError("Could not parse character card data from PNG")

    # V2/V3 has a data wrapper; V1 is flat
    data = payload.get("data", payload) if isinstance(payload, dict) else {}

    # Map SillyTavern fields to TNHComfy Character fields
    character = {}
    character["name"] = data.get("name", "")
    character["description"] = data.get("description", "")
    character["personality"] = data.get("personality", "")
    character["scenario"] = data.get("scenario", "")
    character["first_mes"] = data.get("first_mes", "")
    character["mes_example"] = data.get("mes_example", "")
    character["system_prompt"] = data.get("system_prompt", "")
    character["creator_notes"] = data.get("creator_notes", data.get("creator", ""))

    # Tags
    tags = data.get("tags", [])
    if isinstance(tags, list):
        character["visual_tags"] = tags

    # TNHComfy extensions
    extensions = data.get("extensions", {})
    if isinstance(extensions, dict):
        if "lora_triggers" in extensions:
            character["lora_triggers"] = extensions["lora_triggers"]
        if "visual_tags" in extensions:
            character["visual_tags"] = extensions["visual_tags"]
        if "voice_profile" in extensions:
            character["voice_profile"] = extensions["voice_profile"]

    # Alternate greetings -> store as first_mes if first_mes is empty
    alt_greetings = data.get("alternate_greetings", [])
    character["alternate_greetings"] = alt_greetings if isinstance(alt_greetings, list) else []
    
    if character["alternate_greetings"] and not character["first_mes"]:
        character["first_mes"] = character["alternate_greetings"][0]

    return {"character": character, "avatar_bytes": png_bytes}


@router.get("")
def list_characters(session: Session = Depends(get_session), character_repo: CharacterRepository = Depends(get_character_repo)):
    characters = character_repo.list()
    return [_character_to_dict(c) for c in characters]

@router.post("")
def create_character(character: Character, session: Session = Depends(get_session)):
    if character.avatar_path:
        raise ValidationError("Use the avatar upload endpoint to set avatar_path")
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

@router.post("/import")
def import_character_card(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    if not file.filename or not file.filename.lower().endswith(".png"):
        raise ValidationError("Only PNG files are supported")

    png_bytes = file.file.read()
    if len(png_bytes) < 8 or png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValidationError("Invalid PNG file")

    result = parse_character_card(png_bytes)
    char_data = result["character"]
    avatar_bytes = result["avatar_bytes"]

    if not char_data.get("name"):
        raise ValidationError("Character card must have a name")

    character = Character(**{k: v for k, v in char_data.items() if v})
    character.created_at = datetime.now(timezone.utc)
    character.updated_at = character.created_at
    session.add(character)
    session.commit()
    session.refresh(character)

    # Save avatar from card image
    os.makedirs(f"{app_config.settings.character_avatar_dir}/{character.id}", exist_ok=True)
    avatar_path = f"{app_config.settings.character_avatar_dir}/{character.id}/avatar.png"
    with open(avatar_path, "wb") as f:
        f.write(avatar_bytes)
    character.avatar_path = avatar_path
    session.add(character)
    session.commit()
    session.refresh(character)

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

    return _character_to_dict(character)

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
    for key, value in update_data.items():
        setattr(character, key, value)

    character.updated_at = datetime.now(timezone.utc)
    session.add(character)
    session.commit()
    session.refresh(character)
    return _character_to_dict(character)


@router.patch("/{character_id}")
def patch_character(character_id: str, character_update: CharacterUpdateRequest, session: Session = Depends(get_session), character_repo: CharacterRepository = Depends(get_character_repo)):
    """Partial update — only updates fields explicitly provided (non-None values)."""
    character = character_repo.get(character_id)
    if not character:
        raise NotFoundError("Character", character_id)

    update_data = character_update.model_dump(exclude_unset=True)
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
    character = character_repo.get(character_id)
    if not character:
        raise NotFoundError("Character", character_id)

    os.makedirs(f"{app_config.settings.character_avatar_dir}/{character_id}", exist_ok=True)
    avatar_path = f"{app_config.settings.character_avatar_dir}/{character_id}/avatar.png"

    with open(avatar_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    character.avatar_path = avatar_path
    character.updated_at = datetime.now(timezone.utc)
    session.add(character)
    session.commit()
    session.refresh(character)

    return {"message": "Avatar uploaded", "avatar_path": avatar_path, "has_avatar": True}

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
    from services.job_queue import queue_manager
    from services.job_service import JobService
    from core.workflow_builder import build_video_job_workflow

    character = character_repo.get(character_id)
    if not character:
        raise NotFoundError("Character", character_id)

    prompt = request.prompt
    if not prompt:
        prompt = f"portrait of {character.name}, {character.description}, {character.personality}, highly detailed, cinematic lighting"

    workflow, metadata = build_video_job_workflow(
        prompt=prompt,
        negative=request.negative_prompt or "worst quality, low quality, bad anatomy, bad hands, missing fingers, extra limbs, text, watermark",
        checkpoint=request.checkpoint or "sd_xl_base_1.0.safetensors",
        width=512,
        height=512,
        frames=16,
        source="character_avatar_animate",
        character_id=character.id,
    )

    job = await JobService(session).create_job(
        task_type="image",
        workflow=workflow,
        metadata=metadata,
    )
    await queue_manager.enqueue(job.id, task_type="image")
    
    return {"message": "Animation job enqueued", "job_id": job.id}

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
        
    char_dict = character.model_dump(exclude={"id", "created_at", "updated_at", "avatar_path"})
    char_dict["name"] = f"{character.name} (Copy)"
    
    new_char = Character(**char_dict)
    new_char.created_at = datetime.now(timezone.utc)
    new_char.updated_at = new_char.created_at
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
def export_character(character_id: str, session: Session = Depends(get_session), character_repo: CharacterRepository = Depends(get_character_repo)):
    character = character_repo.get(character_id)
    if not character:
        raise NotFoundError("Character", character_id)

    v2_data = {
        "spec": "chara2.0",
        "spec_version": "2.0",
        "data": {
            "name": character.name,
            "description": character.description or "",
            "personality": character.personality or "",
            "scenario": character.scenario or "",
            "first_mes": character.first_mes or "",
            "mes_example": character.mes_example or "",
            "creator_notes": character.creator_notes or "",
            "system_prompt": character.system_prompt or "",
            "post_history_instructions": character.append_system_prompt or "",
            "alternate_greetings": character.alternate_greetings or [],
            "tags": character.visual_tags or [],
            "creator": character.creator_notes or "",
            "character_version": "",
            "extensions": {
                "lora_triggers": character.lora_triggers or [],
                "visual_tags": character.visual_tags or [],
                "voice_profile": character.voice_profile or "",
            },
        },
    }

    json_str = json.dumps(v2_data, ensure_ascii=False)
    b64_data = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

    if character.avatar_path and os.path.exists(character.avatar_path):
        img = Image.open(character.avatar_path)
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("chara", b64_data)

        output = BytesIO()
        img.save(output, format="PNG", pnginfo=metadata)
        output.seek(0)

        safe_name = "".join([c for c in character.name if c.isalpha() or c.isdigit() or c == " "]).rstrip()
        if not safe_name:
            safe_name = "character"
        filename = f"{safe_name.replace(' ', '_')}_v2.png"

        return StreamingResponse(output, media_type="image/png", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("chara", b64_data)

    output = BytesIO()
    img.save(output, format="PNG", pnginfo=metadata)
    output.seek(0)

    safe_name = "".join([c for c in character.name if c.isalpha() or c.isdigit() or c == " "]).rstrip()
    if not safe_name:
        safe_name = "character"
    filename = f"{safe_name.replace(' ', '_')}_v2.png"

    return StreamingResponse(output, media_type="image/png", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
