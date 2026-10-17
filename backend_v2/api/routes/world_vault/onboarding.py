"""World Architect & Onboarding API routes (`/api/v2/world-vault/onboarding/*`)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlmodel import Session

from api.deps import get_session
from core.entities import Chat, Character, Message, MessageKind, MessageRole, Scenario, World
from core.exceptions import NotFoundError, ValidationError
from core.upload_validation import (
    MAX_CARD_SIZE_MB,
    inspect_image,
    read_upload_bounded,
    require_declared_size,
)
from services.chat_utils import resolve_scenario_defaults, substitute_tavern_vars
from services.world_onboarding_service import (
    CROSSOVER_ARCHETYPES,
    analyze_card_for_onboarding,
    analyze_document_for_world,
    analyze_existing_character_for_onboarding,
    analyze_image_to_state,
    commit_chat_to_world_canon,
    commit_world_blueprint,
    compile_chat_to_story,
    fast_travel_chat,
    generate_world_crossover,
    run_world_tick,
)
from services.world_ownership import link_to_world

router = APIRouter()

MAX_ONBOARDING_FILE_BYTES = MAX_CARD_SIZE_MB * 1024 * 1024


class AnalyzeExistingCharacterRequest(BaseModel):
    use_vision: bool = True


class AnalyzeTextStoryRequest(BaseModel):
    raw_text: str
    title: Optional[str] = None


class CrossoverPreviewRequest(BaseModel):
    traveler_character_ids: List[str] = Field(default_factory=list)
    target_world_id: str
    archetype: str = "rift_portal"
    target_location_id: Optional[str] = None
    resident_character_ids: List[str] = Field(default_factory=list)
    custom_premise: Optional[str] = None
    commit_immediately: bool = False


class CommitBlueprintRequest(BaseModel):
    world: Dict[str, Any] = Field(default_factory=dict)
    characters: List[Dict[str, Any]] = Field(default_factory=list)
    locations: List[Dict[str, Any]] = Field(default_factory=list)
    scenarios: List[Dict[str, Any]] = Field(default_factory=list)
    persona: Dict[str, Any] = Field(default_factory=dict)
    lorebook: Dict[str, Any] = Field(default_factory=dict)
    relationships: List[Dict[str, Any]] = Field(default_factory=list)
    initial_state_snapshot: Dict[str, Any] = Field(default_factory=dict)
    story_seed_content: Optional[str] = None
    launch_chat: bool = True
    launch_story: bool = False


class CompileStoryRequest(BaseModel):
    title: Optional[str] = None


class WorldTickRequest(BaseModel):
    time_advance_label: str = "+1 Day"
    active_chat_id: Optional[str] = None


class ReverseVisionRequest(BaseModel):
    image_path: Optional[str] = None
    image_base64: Optional[str] = None


class FastTravelRequest(BaseModel):
    location_id: Optional[str] = None
    location_name: Optional[str] = None
    time_of_day: Optional[str] = None


class VisualizeItemRequest(BaseModel):
    item_name: str
    branch_id: Optional[str] = None


@router.get("/archetypes")
def list_crossover_archetypes():
    """Return available World Crossover / Transmigration archetypes."""
    return {
        "archetypes": [
            {"id": key, "label": val["label"], "summary": val["summary"]}
            for key, val in CROSSOVER_ARCHETYPES.items()
        ]
    }


@router.post("/analyze-card")
async def analyze_card_endpoint(
    file: UploadFile = File(...),
    use_vision: bool = Form(True),
    session: Session = Depends(get_session),
):
    """Upload a SillyTavern card (.png, .json, .charx) and return a full WorldOnboardingBlueprint."""
    filename = file.filename or "card.png"
    if not filename.lower().endswith((".png", ".json", ".charx")):
        raise ValidationError("Only .png, .json, and .charx character cards are supported")

    require_declared_size(file, MAX_ONBOARDING_FILE_BYTES)
    payload = await read_upload_bounded(file, MAX_ONBOARDING_FILE_BYTES)
    if not payload:
        raise ValidationError("Uploaded card file is empty")

    if payload[:8] == b"\x89PNG\r\n\x1a\n":
        inspect_image(payload, field="file", label="Character card")

    return await analyze_card_for_onboarding(
        session,
        file_bytes=payload,
        filename=filename,
        use_vision=use_vision,
    )


@router.post("/analyze-character/{character_id}")
async def analyze_existing_character_endpoint(
    character_id: str,
    request: Optional[AnalyzeExistingCharacterRequest] = None,
    session: Session = Depends(get_session),
):
    """Analyze an already-imported Character and build an editable WorldOnboardingBlueprint."""
    req = request or AnalyzeExistingCharacterRequest()
    return await analyze_existing_character_for_onboarding(
        session,
        character_id=character_id,
        use_vision=req.use_vision,
    )


@router.post("/analyze-document")
async def analyze_document_endpoint(
    file: Optional[UploadFile] = File(None),
    raw_text: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    """Upload a story file (.pdf, .txt, .md) or paste raw text to extract a multi-character WorldOnboardingBlueprint."""
    file_bytes: Optional[bytes] = None
    filename: Optional[str] = None
    if file is not None and file.filename:
        filename = file.filename
        if not filename.lower().endswith((".pdf", ".txt", ".md", ".markdown")):
            raise ValidationError("Only .pdf, .txt, and .md story documents are supported")
        require_declared_size(file, MAX_ONBOARDING_FILE_BYTES)
        file_bytes = await read_upload_bounded(file, MAX_ONBOARDING_FILE_BYTES)

    return await analyze_document_for_world(
        session,
        file_bytes=file_bytes,
        filename=filename,
        raw_text=raw_text,
        title=title,
    )


@router.post("/analyze-story-text")
async def analyze_story_text_json_endpoint(
    request: AnalyzeTextStoryRequest,
    session: Session = Depends(get_session),
):
    """JSON body alternative for analyzing pasted story prose into a WorldOnboardingBlueprint."""
    return await analyze_document_for_world(
        session,
        raw_text=request.raw_text,
        title=request.title,
    )


@router.post("/crossover-preview")
async def crossover_preview_endpoint(
    request: CrossoverPreviewRequest,
    session: Session = Depends(get_session),
):
    """Generate a World Crossover / Transmigration preview (and optionally launch the Crossover Chat)."""
    preview = await generate_world_crossover(
        session,
        traveler_character_ids=request.traveler_character_ids,
        target_world_id=request.target_world_id,
        archetype=request.archetype,
        target_location_id=request.target_location_id,
        resident_character_ids=request.resident_character_ids,
        custom_premise=request.custom_premise,
    )

    if request.commit_immediately:
        launched = await asyncio.to_thread(_commit_crossover_chat_sync, session, request, preview)
        preview["launched_chat_id"] = launched["chat_id"]
        preview["launched_scenario_id"] = launched["scenario_id"]

    return preview


def _commit_crossover_chat_sync(
    session: Session,
    request: CrossoverPreviewRequest,
    preview: Dict[str, Any],
) -> Dict[str, str]:
    now = datetime.now(timezone.utc)
    target_world = session.get(World, request.target_world_id)
    if not target_world:
        raise NotFoundError("World", request.target_world_id)

    primary_cid = request.traveler_character_ids[0]
    primary_char = session.get(Character, primary_cid)
    if not primary_char:
        raise NotFoundError("Character", primary_cid)

    additional_cids = list(request.traveler_character_ids[1:])
    for rcid in request.resident_character_ids or []:
        if rcid not in additional_cids and rcid != primary_cid:
            additional_cids.append(rcid)

    scen_data = preview.get("scenario") or {}
    loc_data = preview.get("target_location") or {}
    scen_name = str(scen_data.get("title") or f"Crossover: {primary_char.name} in {target_world.name}")[:120]
    scen_desc = str(scen_data.get("description") or "")
    scenario = Scenario(
        name=scen_name,
        description=scen_desc or None,
        prompt_template=str(scen_data.get("first_mes") or scen_desc or scen_name),
        world_id=target_world.id,
        created_at=now,
        updated_at=now,
    )
    session.add(scenario)
    session.commit()
    session.refresh(scenario)

    chat = Chat(
        name=scenario.name,
        world_id=target_world.id,
        character_id=primary_cid,
        additional_character_ids=additional_cids,
        scenario_id=scenario.id,
        location_id=loc_data.get("id"),
        story_location=scen_data.get("location_name") or loc_data.get("name"),
        story_time=scen_data.get("story_time") or loc_data.get("time") or "Dusk",
        director_enabled=True,
        state_snapshot=preview.get("initial_state_snapshot") or {},
        created_at=now,
        updated_at=now,
    )
    link_to_world(session, chat, target_world.id)
    session.add(chat)
    session.commit()
    session.refresh(chat)

    raw_first_mes = str(scen_data.get("first_mes") or primary_char.first_mes or "").strip()
    if raw_first_mes:
        rendered = substitute_tavern_vars(
            raw_first_mes,
            char=primary_char.name or "",
            user=chat.persona_name or "User",
            persona_description=chat.persona_description or "",
            original=primary_char.description or "",
        )
        session.add(
            Message(
                chat_id=chat.id,
                role=MessageRole.CHAR,
                kind=MessageKind.CHAR,
                character_id=primary_char.id,
                content=rendered,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    return {"chat_id": chat.id, "scenario_id": scenario.id}


@router.post("/commit")
async def commit_blueprint_endpoint(
    request: CommitBlueprintRequest,
    session: Session = Depends(get_session),
):
    """Commit an edited WorldOnboardingBlueprint into the World Vault."""
    return await asyncio.to_thread(
        commit_world_blueprint,
        session,
        request.model_dump(),
    )


@router.post("/commit-canon/{chat_id}")
async def commit_canon_endpoint(
    chat_id: str,
    session: Session = Depends(get_session),
):
    """Promote a Chat's Statekeeper chronology, locations, and relationships to World Vault Canon."""
    return await asyncio.to_thread(
        commit_chat_to_world_canon,
        session,
        chat_id=chat_id,
    )


@router.post("/compile-story/{chat_id}")
async def compile_story_endpoint(
    chat_id: str,
    request: Optional[CompileStoryRequest] = None,
    session: Session = Depends(get_session),
):
    """Compile a roleplay chat into a Story Sandbox chapter."""
    req = request or CompileStoryRequest()
    return await compile_chat_to_story(
        session,
        chat_id=chat_id,
        title=req.title,
    )


@router.post("/world-tick/{world_id}")
async def world_tick_endpoint(
    world_id: str,
    request: Optional[WorldTickRequest] = None,
    session: Session = Depends(get_session),
):
    """Advance the Living World Clock and simulate off-screen NPC autonomy."""
    req = request or WorldTickRequest()
    return await run_world_tick(
        session,
        world_id=world_id,
        time_advance_label=req.time_advance_label,
        active_chat_id=req.active_chat_id,
    )


@router.post("/reverse-vision/{chat_id}")
async def reverse_vision_endpoint(
    chat_id: str,
    request: Optional[ReverseVisionRequest] = None,
    session: Session = Depends(get_session),
):
    """Sync a Chat's Statekeeper outfit, mood, and location from a generated or uploaded image."""
    req = request or ReverseVisionRequest()
    return await analyze_image_to_state(
        session,
        chat_id=chat_id,
        image_path=req.image_path,
        image_base64=req.image_base64,
    )


@router.post("/fast-travel/{chat_id}")
async def fast_travel_endpoint(
    chat_id: str,
    request: FastTravelRequest,
    session: Session = Depends(get_session),
):
    """Move a Chat to a selected World Vault Location and update the World Clock."""
    return await asyncio.to_thread(
        fast_travel_chat,
        session,
        chat_id=chat_id,
        location_id=request.location_id,
        location_name=request.location_name,
        time_of_day=request.time_of_day,
    )


@router.post("/visualize-item/{chat_id}")
async def visualize_item_endpoint(
    chat_id: str,
    request: VisualizeItemRequest,
    session: Session = Depends(get_session),
):
    """1-Click Inventory Item Visualizer: enqueue a ComfyUI concept art illustration for an item."""
    from services.image_submission import submit_image_job
    from services.model_availability_service import ModelAvailabilityService

    item_name = (request.item_name or "").strip()
    if not item_name:
        raise ValidationError("Item name is required")

    chat = session.get(Chat, chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)
    if not chat.allow_image_generation:
        raise ValidationError("Image generation is disabled for this chat")

    character = session.get(Character, chat.character_id) if chat.character_id else None
    checkpoint = character.checkpoint if character and character.checkpoint else None
    if not checkpoint:
        scenario_ckpt, _ = resolve_scenario_defaults(session, chat)
        checkpoint = scenario_ckpt
    if not checkpoint:
        checkpoint = ModelAvailabilityService(session).resolve_checkpoint()

    loc_tag = f"in {chat.story_location}" if chat.story_location else "dramatic dark fantasy background"
    prompt = (
        f"detailed close-up concept art of {item_name}, intricate craftsmanship, "
        f"glowing details, {loc_tag}, cinematic lighting, masterpiece, best quality, no humans"
    )

    job = await submit_image_job(
        session,
        prompt=prompt,
        checkpoint=checkpoint,
        lora=character.lora if character and character.lora else None,
        filename_prefix="ItemVisualize",
        source="chat_image",
        workspace="chat",
        chat_id=chat_id,
        character_id=chat.character_id,
        branch_id=request.branch_id,
        extra_metadata={"image_context": f"Inventory Item: {item_name}"},
    )
    return {
        "job_id": job.id,
        "status": "queued",
        "item_name": item_name,
        "prompt": prompt,
    }
