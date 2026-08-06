import base64
import json
import os
import shutil
import struct
import zlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from api.deps import get_session
from core.entities import Character

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
    alternate_greetings: list[str] | None = None
    checkpoint: str | None = None
    lora: str | None = None
    default_time: str | None = None
    default_location: str | None = None


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

    # Try base64 decode
    try:
        decoded = base64.b64decode(value)
        try:
            decoded = zlib.decompress(decoded)
        except zlib.error:
            pass
        value = decoded.decode("utf-8", errors="replace")
    except Exception:
        pass

    try:
        return json.loads(value)
    except json.JSONDecodeError:
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
        raise HTTPException(status_code=400, detail="Could not parse character card data from PNG")

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


@router.get("/")
def list_characters(session: Session = Depends(get_session)):
    characters = session.exec(select(Character).order_by(Character.name)).all()
    return [_character_to_dict(c) for c in characters]

@router.post("/", response_model=Character)
def create_character(character: Character, session: Session = Depends(get_session)):
    character.created_at = datetime.now(timezone.utc)
    character.updated_at = character.created_at
    session.add(character)
    session.commit()
    session.refresh(character)

    # Auto-create a collection for this character's scene images
    from core.entities import Collection
    collection = Collection(
        name=f"{character.name}'s Gallery",
        color="#8B5CF6",
        description=f"Scene images generated for {character.name}",
        character_id=character.id,
    )
    session.add(collection)
    session.commit()

    return character

@router.post("/import")
def import_character_card(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    if not file.filename or not file.filename.lower().endswith(".png"):
        raise HTTPException(status_code=400, detail="Only PNG files are supported")

    png_bytes = file.file.read()
    if len(png_bytes) < 8 or png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise HTTPException(status_code=400, detail="Invalid PNG file")

    result = parse_character_card(png_bytes)
    char_data = result["character"]
    avatar_bytes = result["avatar_bytes"]

    if not char_data.get("name"):
        raise HTTPException(status_code=400, detail="Character card must have a name")

    character = Character(**{k: v for k, v in char_data.items() if v})
    character.created_at = datetime.now(timezone.utc)
    character.updated_at = character.created_at
    session.add(character)
    session.commit()
    session.refresh(character)

    # Save avatar from card image
    os.makedirs(f"/data/characters/{character.id}", exist_ok=True)
    avatar_path = f"/data/characters/{character.id}/avatar.png"
    with open(avatar_path, "wb") as f:
        f.write(avatar_bytes)
    character.avatar_path = avatar_path
    session.add(character)
    session.commit()
    session.refresh(character)

    # Auto-create collection
    from core.entities import Collection
    collection = Collection(
        name=f"{character.name}'s Gallery",
        color="#8B5CF6",
        description=f"Scene images generated for {character.name}",
        character_id=character.id,
    )
    session.add(collection)
    session.commit()

    return character

@router.get("/{character_id}")
def get_character(character_id: str, session: Session = Depends(get_session)):
    character = session.get(Character, character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    return _character_to_dict(character)

@router.put("/{character_id}")
def update_character(character_id: str, character_update: CharacterUpdateRequest, session: Session = Depends(get_session)):
    """Full update — replaces all provided fields (omitted fields are left unchanged)."""
    character = session.get(Character, character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    update_data = character_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(character, key, value)

    character.updated_at = datetime.now(timezone.utc)
    session.add(character)
    session.commit()
    session.refresh(character)
    return _character_to_dict(character)


@router.patch("/{character_id}")
def patch_character(character_id: str, character_update: CharacterUpdateRequest, session: Session = Depends(get_session)):
    """Partial update — only updates fields explicitly provided (non-None values)."""
    character = session.get(Character, character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

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
def delete_character(character_id: str, session: Session = Depends(get_session)):
    character = session.get(Character, character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    session.delete(character)
    session.commit()
    return {"message": "Character deleted"}

@router.post("/{character_id}/avatar")
async def upload_avatar(character_id: str, file: UploadFile = File(...), session: Session = Depends(get_session)):
    character = session.get(Character, character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    os.makedirs(f"/data/characters/{character_id}", exist_ok=True)
    avatar_path = f"/data/characters/{character_id}/avatar.png"

    with open(avatar_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    character.avatar_path = avatar_path
    character.updated_at = datetime.now(timezone.utc)
    session.add(character)
    session.commit()
    session.refresh(character)

    return {"message": "Avatar uploaded", "avatar_path": avatar_path, "has_avatar": True}

@router.get("/{character_id}/avatar")
def get_avatar(character_id: str, session: Session = Depends(get_session)):
    character = session.get(Character, character_id)
    if not character or not character.avatar_path or not os.path.exists(character.avatar_path):
        raise HTTPException(status_code=404, detail="Avatar not found")
        
    return FileResponse(character.avatar_path)
