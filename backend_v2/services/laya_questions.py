"""Dynamic Laya questions service with database-backed customization and sub-variant routing.

Provides customizable questions for Laya System 1 across all pipeline stages:
- Stage 1: Triage (Agent routing, sub-variant selection, pacing, Fate & Skill check)
- Stage 2: Audit (Completion, image trigger, 16 Statekeeper gates)
- Stage 3: Chaining (Conductor next speaker, continuation threshold)

Users can enable/disable questions, edit text/criteria, or author custom questions
directly from LLM Studio.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from sqlmodel import Session, select

from core.entities import AgentProfile, AgentPromptVariant, LayaQuestionOverride
from infrastructure.logging import get_logger
from services.decision_schema import (
    GATE_DESCRIPTIONS,
    GATE_LABELS,
    UPDATER_GATE_KEYS,
    build_post_generation_audit_questions as _default_audit_questions,
    build_pre_generation_triage_questions as _default_triage_questions,
    build_turn_chaining_questions as _default_chaining_questions,
)

logger = get_logger("laya_questions")


def get_agent_variant_options(
    session: Optional[Session], agent_slug: str
) -> Dict[str, str]:
    """Return choice options for sub-variants of an agent, or empty if none have hints."""
    if not session:
        return {}
    try:
        profile = session.exec(
            select(AgentProfile).where(AgentProfile.slug == agent_slug)
        ).first()
        if not profile:
            return {}

        variants = session.exec(
            select(AgentPromptVariant).where(AgentPromptVariant.agent_id == profile.id)
        ).all()

        options: Dict[str, str] = {
            "default": f"Standard {profile.name} default persona"
        }
        for v in variants:
            hint = (v.selection_hint or v.description or "").strip()
            if hint:
                tags_str = f" [{', '.join(v.tags)}]" if v.tags else ""
                options[v.slug] = f"{v.name}{tags_str}: {hint}"

        if len(options) <= 1:
            return {}
        return options
    except Exception as exc:
        logger.debug("get_agent_variant_options_failed", agent=agent_slug, error=str(exc))
        return {}


def load_question_overrides(
    session: Optional[Session], stage: str
) -> Dict[str, LayaQuestionOverride]:
    """Load user question overrides for a given stage."""
    if not session:
        return {}
    try:
        rows = session.exec(
            select(LayaQuestionOverride).where(LayaQuestionOverride.stage == stage)
        ).all()
        return {r.key: r for r in rows}
    except Exception as exc:
        logger.debug("load_question_overrides_failed", stage=stage, error=str(exc))
        return {}


def resolve_stage_questions(
    session: Optional[Session],
    stage: str,
    *,
    available_agents: Optional[List[Dict[str, Any]]] = None,
    has_secondary_character: bool = False,
    allow_narration: bool = True,
    primary_character_slug: str = "character",
) -> List[Dict[str, Any]]:
    """Assemble the active questions for a pipeline stage with user overrides and sub-variant selection."""
    if stage == "triage":
        base_questions = _default_triage_questions(
            available_agents=available_agents,
            has_secondary_character=has_secondary_character,
            allow_narration=allow_narration,
        )
        # Inject sub-variant choice questions if the character or narrator have sub-variants
        if session:
            char_variants = get_agent_variant_options(session, primary_character_slug)
            if char_variants:
                base_questions.append({
                    "key": "character_variant",
                    "type": "choice",
                    "question": f"Which personality variant of {primary_character_slug.capitalize()} best fits this scene beat?",
                    "options": char_variants,
                })
            if allow_narration:
                narr_variants = get_agent_variant_options(session, "narrator")
                if narr_variants:
                    base_questions.append({
                        "key": "narrator_variant",
                        "type": "choice",
                        "question": "Which storytelling tone or narrative variant best fits the scene?",
                        "options": narr_variants,
                    })
    elif stage == "audit":
        base_questions = _default_audit_questions()
    elif stage == "chaining":
        base_questions = _default_chaining_questions(
            available_agents=available_agents,
            has_secondary_character=has_secondary_character,
            allow_narration=allow_narration,
        )
    else:
        base_questions = []

    overrides = load_question_overrides(session, stage)
    resolved: List[Dict[str, Any]] = []

    for q in base_questions:
        key = q["key"]
        override = overrides.get(key)
        if override is not None:
            if not override.enabled:
                # User toggled this question off
                continue
            item = dict(q)
            if override.question:
                if item.get("type") == "noul":
                    item["statement"] = override.question
                else:
                    item["question"] = override.question
            if override.options and isinstance(override.options, dict):
                # User updated descriptions of options
                merged_opts = dict(item.get("options") or {})
                merged_opts.update(override.options)
                item["options"] = merged_opts
            resolved.append(item)
        else:
            resolved.append(q)

    # Append any custom user-authored questions for this stage
    for key, override in overrides.items():
        if override.is_custom and override.enabled:
            resolved.append({
                "key": key,
                "type": "noul",
                "statement": override.question or f"Custom check: {key}",
                "directive": override.directive,
                "threshold": override.threshold or 0.60,
                "is_custom": True,
            })

    return resolved


def list_all_pipeline_questions(session: Optional[Session]) -> List[Dict[str, Any]]:
    """Return all questions across all stages with metadata and override state for LLM Studio."""
    stages = ["triage", "audit", "chaining"]
    result: List[Dict[str, Any]] = []

    for stg in stages:
        overrides = load_question_overrides(session, stg)
        if stg == "triage":
            base_qs = _default_triage_questions()
            # Sample variant placeholders for studio display
            base_qs.extend([
                {
                    "key": "character_variant",
                    "type": "choice",
                    "question": "Which personality variant of the character best fits this scene beat?",
                    "options": {"default": "Standard authentic persona"},
                },
                {
                    "key": "narrator_variant",
                    "type": "choice",
                    "question": "Which storytelling tone or narrative variant best fits the scene?",
                    "options": {"default": "Standard omniscient narrative description"},
                },
            ])
        elif stg == "audit":
            base_qs = _default_audit_questions()
        else:
            base_qs = _default_chaining_questions()

        seen_keys = set()
        for q in base_qs:
            key = q["key"]
            seen_keys.add(key)
            ov = overrides.get(key)
            result.append({
                "stage": stg,
                "key": key,
                "type": q["type"],
                "default_question": q.get("question") or q.get("statement") or "",
                "question": ov.question if (ov and ov.question) else (q.get("question") or q.get("statement") or ""),
                "default_options": q.get("options") or q.get("rubric") or {},
                "options": ov.options if (ov and ov.options) else (q.get("options") or q.get("rubric") or {}),
                "enabled": ov.enabled if ov else True,
                "is_custom": False,
                "is_gate": key in UPDATER_GATE_KEYS,
                "gate_label": GATE_LABELS.get(key),
                "gate_description": GATE_DESCRIPTIONS.get(key),
            })

        for key, ov in overrides.items():
            if key not in seen_keys and ov.is_custom:
                result.append({
                    "stage": stg,
                    "key": key,
                    "type": "noul",
                    "default_question": ov.question or "",
                    "question": ov.question or "",
                    "default_options": {},
                    "options": {},
                    "enabled": ov.enabled,
                    "is_custom": True,
                    "directive": ov.directive,
                    "threshold": ov.threshold or 0.60,
                    "is_gate": False,
                })

    return result


def save_or_update_question_override(
    session: Session,
    stage: str,
    key: str,
    *,
    enabled: Optional[bool] = None,
    question: Optional[str] = None,
    options: Optional[Dict[str, str]] = None,
    directive: Optional[str] = None,
    threshold: Optional[float] = None,
    is_custom: bool = False,
) -> LayaQuestionOverride:
    """Create or update a question override in the database."""
    from datetime import datetime, timezone

    existing = session.exec(
        select(LayaQuestionOverride).where(
            LayaQuestionOverride.stage == stage,
            LayaQuestionOverride.key == key,
        )
    ).first()

    now = datetime.now(timezone.utc)
    if existing:
        if enabled is not None:
            existing.enabled = enabled
        if question is not None:
            existing.question = question
        if options is not None:
            existing.options = options
        if directive is not None:
            existing.directive = directive
        if threshold is not None:
            existing.threshold = threshold
        existing.updated_at = now
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    new_row = LayaQuestionOverride(
        stage=stage,
        key=key,
        enabled=True if enabled is None else enabled,
        question=question,
        options=options,
        directive=directive,
        threshold=threshold,
        is_custom=is_custom,
        created_at=now,
        updated_at=now,
    )
    session.add(new_row)
    session.commit()
    session.refresh(new_row)
    return new_row


def delete_question_override(session: Session, stage: str, key: str) -> bool:
    """Delete a question override (resets built-in to default or deletes custom)."""
    row = session.exec(
        select(LayaQuestionOverride).where(
            LayaQuestionOverride.stage == stage,
            LayaQuestionOverride.key == key,
        )
    ).first()
    if row:
        session.delete(row)
        session.commit()
        return True
    return False
