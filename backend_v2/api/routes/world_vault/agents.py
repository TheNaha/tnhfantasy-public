"""Agents API — CRUD and simulation for autonomous multi-agent profiles."""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from api.deps import get_session
import config as app_config
from core.entities import AgentProfile, AgentPromptVariant
from core.exceptions import NotFoundError, ValidationError
from core.upload_validation import (
    MAX_AVATAR_SIZE_MB,
    inspect_image,
    read_upload_bounded,
    require_declared_size,
)
from services.agent_variants import (
    activate_variant,
    clean_agent_slug,
    resolve_agent,
)
from services.chat_utils import render_agent_template
from services.decision_service import DecisionService

router = APIRouter()

MAX_AVATAR_BYTES = MAX_AVATAR_SIZE_MB * 1024 * 1024


class AgentProfileCreate(BaseModel):
    # `extra="forbid"` so a misspelled field is a 422 instead of a silently
    # dropped value. The characters routes set the same on their request
    # models for the same reason.
    model_config = {"extra": "forbid"}

    slug: str = Field(..., min_length=2, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    agent_type: str = "custom"
    description: str = Field(..., min_length=5)
    system_prompt_template: str = Field(..., min_length=10)
    model_target: str = "rp"
    model_override: Optional[str] = None
    enabled: bool = True
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    avatar_path: Optional[str] = None


class AgentProfileUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    name: Optional[str] = None
    # The Agent Studio's slug field is editable for anything that is not a
    # built-in, and it sent the slug on save — but this model never declared
    # it, so the backend dropped it silently and the user saw their new slug
    # disappear on reload. Declaring it here makes the field real, and the
    # `extra="forbid"` above is only safe because of it: with the field
    # absent, forbidding extras would have turned the frontend's own save
    # into a 422.
    slug: Optional[str] = None
    agent_type: Optional[str] = None
    description: Optional[str] = None
    system_prompt_template: Optional[str] = None
    model_target: Optional[str] = None
    model_override: Optional[str] = None
    enabled: Optional[bool] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    avatar_path: Optional[str] = None


class AgentSimulateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    stage: str = "all"  # "triage", "audit", "chaining", "all"
    character_name: str = "Elysia"
    user_name: str = "Player"
    location: Optional[str] = "The Obsidian Citadel"
    time: Optional[str] = "Midnight"
    recent_messages: Optional[List[Dict[str, str]]] = None
    state_snapshot: Optional[Dict[str, Any]] = None
    # Preview one specific prompt variant instead of the agent's active one.
    variant_slug: Optional[str] = None


class AgentVariantCreate(BaseModel):
    slug: str = Field(..., min_length=2, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    system_prompt_template: str = Field(..., min_length=10)
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    top_p: Optional[float] = Field(default=None, ge=0, le=1)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=32768)
    activate: bool = False
    # Which model (or model role) this variant is FOR. None means "any
    # model". A variant scoped to a model is only offered to Laya when that
    # model is the one the agent will answer with, and is auto-applied when
    # it matches — the scope IS its activation.
    model_scope: Optional[str] = None
    # Which Statekeeper gate this variant is FOR. None means "any gate".
    # The Updater's schema was already gate-specific; this is the prompt
    # half, so the extractor is told in words what shifted.
    gate_scope: Optional[str] = None


class AgentVariantUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt_template: Optional[str] = None
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    top_p: Optional[float] = Field(default=None, ge=0, le=1)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=32768)
    is_active: Optional[bool] = None
    model_scope: Optional[str] = None
    gate_scope: Optional[str] = None


def _get_agent_or_404(session: Session, agent_id: str) -> AgentProfile:
    profile = session.get(AgentProfile, agent_id)
    if not profile:
        profile = session.exec(select(AgentProfile).where(AgentProfile.slug == agent_id)).first()
    if not profile:
        raise NotFoundError("AgentProfile", agent_id)
    return profile


def _get_variant_or_404(
    session: Session, profile: AgentProfile, variant_id: str
) -> AgentPromptVariant:
    variant = session.get(AgentPromptVariant, variant_id)
    if variant is None or variant.agent_id != profile.id:
        variant = session.exec(
            select(AgentPromptVariant).where(
                AgentPromptVariant.agent_id == profile.id,
                AgentPromptVariant.slug == variant_id,
            )
        ).first()
    if variant is None:
        raise NotFoundError("AgentPromptVariant", variant_id)
    return variant


@router.get("", response_model=List[AgentProfile])
def list_agents(
    session: Session = Depends(get_session),
    enabled_only: bool = Query(False),
) -> List[AgentProfile]:
    """List all registered agent profiles."""
    stmt = select(AgentProfile).order_by(AgentProfile.is_builtin.desc(), AgentProfile.created_at.asc())
    if enabled_only:
        stmt = stmt.where(AgentProfile.enabled == True)  # noqa: E712
    return list(session.exec(stmt).all())


@router.post("", response_model=AgentProfile)
def create_agent(
    req: AgentProfileCreate,
    session: Session = Depends(get_session),
) -> AgentProfile:
    """Create a new custom agent profile."""
    clean_slug = re.sub(r"[^a-z0-9_]+", "_", req.slug.lower().strip()).strip("_")
    if not clean_slug:
        raise ValidationError("Agent slug must contain at least one alphanumeric character.")

    # Check slug collision
    existing = session.exec(select(AgentProfile).where(AgentProfile.slug == clean_slug)).first()
    if existing:
        raise ValidationError(f"An agent with slug '{clean_slug}' already exists.")

    now = datetime.now(timezone.utc)
    profile = AgentProfile(
        id=str(uuid.uuid4()),
        slug=clean_slug,
        name=req.name.strip(),
        agent_type=req.agent_type.strip(),
        description=req.description.strip(),
        system_prompt_template=req.system_prompt_template.strip(),
        model_target=req.model_target.strip(),
        model_override=req.model_override.strip() if req.model_override else None,
        is_builtin=False,
        enabled=req.enabled,
        temperature=req.temperature,
        top_p=req.top_p,
        max_tokens=req.max_tokens,
        avatar_path=req.avatar_path,
        created_at=now,
        updated_at=now,
    )
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


@router.get("/{agent_id}", response_model=AgentProfile)
def get_agent(
    agent_id: str,
    session: Session = Depends(get_session),
) -> AgentProfile:
    """Get an agent profile by ID or slug."""
    profile = session.get(AgentProfile, agent_id)
    if not profile:
        profile = session.exec(select(AgentProfile).where(AgentProfile.slug == agent_id)).first()
    if not profile:
        raise NotFoundError("AgentProfile", agent_id)
    return profile


@router.put("/{agent_id}", response_model=AgentProfile)
def update_agent(
    agent_id: str,
    req: AgentProfileUpdate,
    session: Session = Depends(get_session),
) -> AgentProfile:
    """Update an existing agent profile."""
    profile = session.get(AgentProfile, agent_id)
    if not profile:
        profile = session.exec(select(AgentProfile).where(AgentProfile.slug == agent_id)).first()
    if not profile:
        raise NotFoundError("AgentProfile", agent_id)

    if req.name is not None:
        profile.name = req.name.strip()
    if req.slug is not None:
        # A built-in agent is looked up by its slug (`resolve_agent(session,
        # "character")`), so its slug is part of the contract and is not
        # editable. `agent_type` is protected for the same reason.
        if profile.is_builtin:
            raise ValidationError("A built-in agent's slug cannot be changed.")
        clean_slug = re.sub(r"[^a-z0-9_]+", "_", req.slug.lower().strip()).strip("_")
        if not clean_slug:
            raise ValidationError("Agent slug must contain at least one alphanumeric character.")
        if clean_slug != profile.slug:
            existing = session.exec(
                select(AgentProfile).where(AgentProfile.slug == clean_slug)
            ).first()
            if existing:
                raise ValidationError(f"An agent with slug '{clean_slug}' already exists.")
            profile.slug = clean_slug
    if req.agent_type is not None and not profile.is_builtin:
        profile.agent_type = req.agent_type.strip()
    if req.description is not None:
        profile.description = req.description.strip()
    if req.system_prompt_template is not None:
        profile.system_prompt_template = req.system_prompt_template.strip()
    if req.model_target is not None:
        profile.model_target = req.model_target.strip()
    if "model_override" in req.model_fields_set:
        profile.model_override = req.model_override.strip() if req.model_override else None
    if req.enabled is not None:
        profile.enabled = req.enabled
    if "temperature" in req.model_fields_set:
        profile.temperature = req.temperature
    if "top_p" in req.model_fields_set:
        profile.top_p = req.top_p
    if "max_tokens" in req.model_fields_set:
        profile.max_tokens = req.max_tokens
    if "avatar_path" in req.model_fields_set:
        profile.avatar_path = req.avatar_path

    profile.updated_at = datetime.now(timezone.utc)
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


@router.post("/{agent_id}/avatar")
async def upload_agent_avatar(
    agent_id: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """Upload an avatar for an agent profile.

    Mirrors the character avatar route: the file is bounded and has to be a
    real image (an `.html` or `.svg` renamed to `.png` is rejected), and it is
    written to the avatar directory under the agent's own id.
    """
    profile = session.get(AgentProfile, agent_id)
    if not profile:
        profile = session.exec(select(AgentProfile).where(AgentProfile.slug == agent_id)).first()
    if not profile:
        raise NotFoundError("AgentProfile", agent_id)

    require_declared_size(file, MAX_AVATAR_BYTES)
    content = await read_upload_bounded(file, MAX_AVATAR_BYTES)
    inspect_image(content, field="file", label="Avatar")

    os.makedirs(f"{app_config.settings.character_avatar_dir}/{profile.id}", exist_ok=True)
    avatar_path = f"{app_config.settings.character_avatar_dir}/{profile.id}/avatar.png"

    with open(avatar_path, "wb") as buffer:
        buffer.write(content)

    profile.avatar_path = avatar_path
    profile.updated_at = datetime.now(timezone.utc)
    session.add(profile)
    session.commit()
    session.refresh(profile)

    return {"message": "Avatar uploaded", "avatar_path": avatar_path, "has_avatar": True}


@router.get("/{agent_id}/avatar")
def get_agent_avatar(agent_id: str, session: Session = Depends(get_session)):
    """Serve an agent's avatar image."""
    profile = session.get(AgentProfile, agent_id)
    if not profile:
        profile = session.exec(select(AgentProfile).where(AgentProfile.slug == agent_id)).first()
    if not profile or not profile.avatar_path or not os.path.exists(profile.avatar_path):
        raise NotFoundError("Avatar", agent_id)

    media_type = "video/webp" if profile.avatar_path.lower().endswith(".webp") else None
    response = FileResponse(profile.avatar_path, media_type=media_type)
    response.headers["Cache-Control"] = "no-cache"
    return response


@router.delete("/{agent_id}")
def delete_agent(
    agent_id: str,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Delete a custom agent profile. Built-in agents cannot be deleted."""
    profile = session.get(AgentProfile, agent_id)
    if not profile:
        profile = session.exec(select(AgentProfile).where(AgentProfile.slug == agent_id)).first()
    if not profile:
        raise NotFoundError("AgentProfile", agent_id)

    if profile.is_builtin:
        raise ValidationError(f"Agent '{profile.slug}' is built-in and cannot be deleted.")

    # Variants are owned by the profile; delete them first so the FK holds on
    # SQLite (where a missing ON DELETE CASCADE would otherwise surface as an
    # IntegrityError only in tests that enable foreign keys).
    variants = session.exec(
        select(AgentPromptVariant).where(AgentPromptVariant.agent_id == profile.id)
    ).all()
    for variant in variants:
        session.delete(variant)
    # Flush the child deletes before the parent: SQLModel defines the FK but no
    # relationship, so the unit of work does not know the rows must go first.
    session.flush()

    session.delete(profile)
    session.commit()
    return {"deleted": True, "id": profile.id, "slug": profile.slug}


@router.get("/{agent_id}/variants", response_model=List[AgentPromptVariant])
def list_agent_variants(
    agent_id: str,
    session: Session = Depends(get_session),
) -> List[AgentPromptVariant]:
    """List the prompt variants defined for an agent."""
    profile = _get_agent_or_404(session, agent_id)
    stmt = (
        select(AgentPromptVariant)
        .where(AgentPromptVariant.agent_id == profile.id)
        .order_by(AgentPromptVariant.is_active.desc(), AgentPromptVariant.name.asc())
    )
    return list(session.exec(stmt).all())


@router.post("/{agent_id}/variants", response_model=AgentPromptVariant)
def create_agent_variant(
    agent_id: str,
    req: AgentVariantCreate,
    session: Session = Depends(get_session),
) -> AgentPromptVariant:
    """Create a prompt variant. Built-in agents can be overridden this way."""
    profile = _get_agent_or_404(session, agent_id)

    clean_slug = clean_agent_slug(req.slug)
    if not clean_slug:
        raise ValidationError("Variant slug must contain at least one alphanumeric character.")

    existing = session.exec(
        select(AgentPromptVariant).where(AgentPromptVariant.slug == clean_slug)
    ).first()
    if existing:
        raise ValidationError(f"A prompt variant with slug '{clean_slug}' already exists.")

    now = datetime.now(timezone.utc)
    variant = AgentPromptVariant(
        id=str(uuid.uuid4()),
        agent_id=profile.id,
        slug=clean_slug,
        name=req.name.strip(),
        description=req.description.strip(),
        system_prompt_template=req.system_prompt_template.strip(),
        temperature=req.temperature,
        top_p=req.top_p,
        max_tokens=req.max_tokens,
        model_scope=(req.model_scope or "").strip() or None,
        gate_scope=(req.gate_scope or "").strip() or None,
        created_at=now,
        updated_at=now,
    )
    session.add(variant)
    session.flush()
    if req.activate:
        activate_variant(session, variant)
    session.commit()
    session.refresh(variant)
    return variant


@router.get("/{agent_id}/variants/{variant_id}", response_model=AgentPromptVariant)
def get_agent_variant(
    agent_id: str,
    variant_id: str,
    session: Session = Depends(get_session),
) -> AgentPromptVariant:
    """Get one variant by id or slug."""
    profile = _get_agent_or_404(session, agent_id)
    return _get_variant_or_404(session, profile, variant_id)


@router.put("/{agent_id}/variants/{variant_id}", response_model=AgentPromptVariant)
def update_agent_variant(
    agent_id: str,
    variant_id: str,
    req: AgentVariantUpdate,
    session: Session = Depends(get_session),
) -> AgentPromptVariant:
    """Update a variant's prompt, metadata, or sampling overrides."""
    profile = _get_agent_or_404(session, agent_id)
    variant = _get_variant_or_404(session, profile, variant_id)

    if req.name is not None:
        variant.name = req.name.strip()
    if req.description is not None:
        variant.description = req.description.strip()
    if req.system_prompt_template is not None:
        variant.system_prompt_template = req.system_prompt_template.strip()
    if "temperature" in req.model_fields_set:
        variant.temperature = req.temperature
    if "top_p" in req.model_fields_set:
        variant.top_p = req.top_p
    if "max_tokens" in req.model_fields_set:
        variant.max_tokens = req.max_tokens
    if "model_scope" in req.model_fields_set:
        variant.model_scope = (req.model_scope or "").strip() or None
    if "gate_scope" in req.model_fields_set:
        variant.gate_scope = (req.gate_scope or "").strip() or None

    variant.updated_at = datetime.now(timezone.utc)
    session.add(variant)
    if req.is_active is True:
        activate_variant(session, variant)
    elif req.is_active is False:
        variant.is_active = False
    session.commit()
    session.refresh(variant)
    return variant


@router.post("/{agent_id}/variants/{variant_id}/activate", response_model=AgentPromptVariant)
def activate_agent_variant(
    agent_id: str,
    variant_id: str,
    session: Session = Depends(get_session),
) -> AgentPromptVariant:
    """Make this the only active variant for the agent."""
    profile = _get_agent_or_404(session, agent_id)
    variant = _get_variant_or_404(session, profile, variant_id)

    activate_variant(session, variant)
    variant.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(variant)
    return variant


@router.delete("/{agent_id}/variants/{variant_id}")
def delete_agent_variant(
    agent_id: str,
    variant_id: str,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Delete a variant. Resolution falls back to the profile template."""
    profile = _get_agent_or_404(session, agent_id)
    variant = _get_variant_or_404(session, profile, variant_id)

    session.delete(variant)
    session.commit()
    return {"deleted": True, "id": variant.id, "slug": variant.slug}


@router.post("/simulate", response_model=Dict[str, Any])
async def simulate_agent_decision(
    req: AgentSimulateRequest,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Interactively simulate multi-agent routing, triage, audit, or turn-chaining."""
    service = DecisionService(session)

    msgs = list(req.recent_messages or [])
    if not msgs:
        msgs = [{"role": "user", "content": req.prompt}]
    elif msgs[-1].get("content") != req.prompt:
        msgs.append({"role": "user", "content": req.prompt})

    results: Dict[str, Any] = {"stage": req.stage}

    if req.stage in ("triage", "all"):
        triage_res = await service.evaluate_pre_generation_triage(
            character_name=req.character_name,
            user_name=req.user_name,
            story_location=req.location,
            story_time=req.time,
            state_snapshot=req.state_snapshot or {},
            recent_messages=msgs,
        )
        results["triage"] = triage_res.to_dict()

    if req.stage in ("audit", "all"):
        audit_res = await service.evaluate_post_generation_audit(
            generated_text=req.prompt,
            character_name=req.character_name,
            user_name=req.user_name,
            story_location=req.location,
            story_time=req.time,
            state_snapshot=req.state_snapshot or {},
            recent_messages=msgs,
        )
        results["audit"] = audit_res.to_dict()

    if req.stage in ("chaining", "all"):
        chaining_res = await service.evaluate_turn_chaining(
            last_speaker="character",
            character_name=req.character_name,
            user_name=req.user_name,
            story_location=req.location,
            story_time=req.time,
            state_snapshot=req.state_snapshot or {},
            recent_messages=msgs,
        )
        results["chaining"] = chaining_res.to_dict()

    # Provide simulated prompt preview if an agent or variant was selected
    selected_slug = None
    if "triage" in results:
        selected_slug = results["triage"].get("selected_agent") or results["triage"].get("agent_slug")
    elif "chaining" in results:
        selected_slug = results["chaining"].get("selected_agent")

    reference = f"variant:{clean_agent_slug(req.variant_slug)}" if req.variant_slug else selected_slug
    resolved = resolve_agent(session, reference) if reference else None
    if resolved:
        preview = render_agent_template(
            resolved.prompt_template,
            character_name=req.character_name,
            user_name=req.user_name,
            story_location=req.location or "",
            story_time=req.time or "",
        )
        results["agent_profile"] = {
            "id": resolved.profile.id,
            "slug": resolved.profile.slug,
            "name": resolved.profile.name,
            "model_target": resolved.profile.model_target,
            "model_override": resolved.profile.model_override,
            "variant_slug": resolved.variant_slug,
            "system_prompt_template": resolved.prompt_template,
            "rendered_prompt_preview": preview,
        }
    elif req.variant_slug:
        results["agent_profile_error"] = f"Unknown prompt variant '{req.variant_slug}'."

    return results
