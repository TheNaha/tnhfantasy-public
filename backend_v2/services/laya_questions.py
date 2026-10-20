"""Dynamic Laya questions service with database-backed customization and sub-variant routing.

Provides customizable questions for Laya System 1 across all pipeline stages:
- Stage 1: Triage (Agent routing, sub-variant selection, pacing, Fate & Skill check)
- Stage 2: Audit (Completion, image trigger, 16 Statekeeper gates)
- Stage 3: Chaining (Conductor next speaker, continuation threshold)

Users can enable/disable questions, edit text/criteria, or author custom questions
directly from LLM Studio.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional
from sqlmodel import Session, select

from core.entities import AgentProfile, AgentPromptVariant, LayaQuestionOverride
from infrastructure.logging import get_logger
from services.agent_variants import variant_applies
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
    session: Optional[Session],
    agent_slug: str,
    *,
    model_scopes: Optional[Iterable[str]] = None,
) -> Dict[str, str]:
    """Return choice options for sub-variants of an agent, or empty if none have hints.

    `model_scopes` narrows the list to the variants that apply to the model
    that will answer (the model id plus its role). A variant scoped to a
    different model is not offered at all — it is a prompt written for a
    different situation, and offering it would let Laya pick a prompt the
    model it chose was never written for.

    A variant with no `selection_hint` and no `description` is never offered.
    That is not a display detail: it means the variant is invisible to the
    routing that is supposed to choose it, so it is the default and not an
    error.
    """
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
            if not variant_applies(v, model_scopes=model_scopes):
                continue
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


def build_stage_questions(
    session: Optional[Session],
    stage: str,
    *,
    available_agents: Optional[List[Dict[str, Any]]] = None,
    has_secondary_character: bool = False,
    allow_narration: bool = True,
    primary_character_slug: str = "character",
    model_scopes: Optional[Dict[str, Iterable[str]]] = None,
) -> List[Dict[str, Any]]:
    """The questions a stage asks, BEFORE the user's overrides are applied.

    Split out from `resolve_stage_questions` so the LLM Studio can show both
    the shipped default and the current text. They used to be two separate
    implementations — the Studio built its own list, with placeholder
    variant questions — and the two could not be compared.
    """
    if stage == "triage":
        base_questions = _default_triage_questions(
            available_agents=available_agents,
            has_secondary_character=has_secondary_character,
            allow_narration=allow_narration,
        )
        # Inject sub-variant choice questions if the character or narrator have sub-variants
        if session:
            char_variants = get_agent_variant_options(
                session, primary_character_slug, model_scopes=(model_scopes or {}).get(primary_character_slug)
            )
            if char_variants:
                base_questions.append({
                    "key": "character_variant",
                    "type": "choice",
                    "question": f"Which personality variant of {primary_character_slug.capitalize()} best fits this scene beat?",
                    "options": char_variants,
                })
            if allow_narration:
                narr_variants = get_agent_variant_options(
                    session, "narrator", model_scopes=(model_scopes or {}).get("narrator")
                )
                if narr_variants:
                    base_questions.append({
                        "key": "narrator_variant",
                        "type": "choice",
                        "question": "Which storytelling tone or narrative variant best fits the scene?",
                        "options": narr_variants,
                    })
            # Inject variant choice questions for any other enabled agent that has variants
            for agent in available_agents or []:
                agent_slug = agent.get("slug")
                if not agent_slug or agent_slug in ("user", primary_character_slug, "narrator"):
                    continue
                agent_variants = get_agent_variant_options(
                    session, agent_slug, model_scopes=(model_scopes or {}).get(agent_slug)
                )
                if agent_variants:
                    base_questions.append({
                        "key": f"{agent_slug}_variant",
                        "type": "choice",
                        "question": f"Which variant of {agent.get('name', agent_slug)} best fits this scene beat?",
                        "options": agent_variants,
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
    return base_questions


def apply_question_overrides(
    base_questions: List[Dict[str, Any]],
    overrides: Dict[str, LayaQuestionOverride],
) -> List[Dict[str, Any]]:
    """Merge the user's overrides into a stage's questions.

    Split out from `resolve_stage_questions` so the LLM Studio can show the
    shipped default next to the current text without building a second copy
    of the question list.
    """
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
                if item.get("type") == "score":
                    # A score question's rubric is its `key -> description`
                    # map, and the Laya runner reads `rubric` for those. The
                    # override's `options` is the same shape — it is what the
                    # Studio edits — so it is written where the runner looks.
                    # Before this, an override of a score question was
                    # merged into `options`, which the runner never reads, so
                    # editing a score question's rubric changed nothing.
                    merged_rubric = dict(item.get("rubric") or {})
                    merged_rubric.update(override.options)
                    item["rubric"] = merged_rubric
                else:
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


def resolve_stage_questions(
    session: Optional[Session],
    stage: str,
    *,
    available_agents: Optional[List[Dict[str, Any]]] = None,
    has_secondary_character: bool = False,
    allow_narration: bool = True,
    primary_character_slug: str = "character",
    model_scopes: Optional[Dict[str, Iterable[str]]] = None,
) -> List[Dict[str, Any]]:
    """Assemble the active questions for a pipeline stage with user overrides and sub-variant selection.

    `model_scopes` maps an AGENT SLUG to the model scopes that apply to it —
    the model that agent will answer with, plus its role. A variant scoped to
    a model outside that set is not offered: Laya is choosing the best prompt
    for an agent whose model has already been picked, and offering it a prompt
    written for a different model would defeat the point.

    It is per agent rather than per turn because each agent can be bound to a
    different model — the character agent answers on the chat's prose model
    and the narrator on the narrator's.
    """
    base_questions = build_stage_questions(
        session,
        stage,
        available_agents=available_agents,
        has_secondary_character=has_secondary_character,
        allow_narration=allow_narration,
        primary_character_slug=primary_character_slug,
        model_scopes=model_scopes,
    )
    return apply_question_overrides(base_questions, load_question_overrides(session, stage))


def list_all_pipeline_questions(session: Optional[Session]) -> List[Dict[str, Any]]:
    """Return all questions across all stages with metadata and override state for LLM Studio.

    This is the SAME function the pipeline runs — `resolve_stage_questions` —
    so what the Studio shows is what Laya is actually asked.

    It used to build a parallel list: the base questions from the builders
    with no agent list, plus hand-written placeholder variant questions whose
    only option was `{"default": …}`. So the Studio's Laya Questions tab
    showed a variant question that could never have been asked, with none of
    the real variant slugs in it, and an edit made there had no relationship
    to what the pipeline would ask.
    """
    stages = ["triage", "audit", "chaining"]
    result: List[Dict[str, Any]] = []

    available_agents: List[Dict[str, Any]] = []
    if session:
        try:
            rows = session.exec(
                select(AgentProfile).where(AgentProfile.enabled == True)  # noqa: E712
            ).all()
            available_agents = [
                {
                    "id": a.id,
                    "slug": a.slug,
                    "name": a.name,
                    "agent_type": a.agent_type,
                    "description": a.description,
                    "system_prompt_template": a.system_prompt_template,
                    "model_target": a.model_target,
                    "model_override": a.model_override,
                }
                for a in rows
            ]
        except Exception as exc:
            logger.warning("list_all_pipeline_questions_agents_failed", error=str(exc))
            available_agents = []

    for stg in stages:
        overrides = load_question_overrides(session, stg)
        # The Studio shows every possible question, so it asks for the widest
        # possible stage: every enabled agent, narration allowed, a secondary
        # character in the cast. A question that would be skipped in a
        # particular chat is still a question the user can configure.
        #
        # The DEFAULTS come from the builder, and the current text from the
        # override merge — the same two functions the pipeline runs, so the
        # Studio cannot drift from the runtime.
        base_qs = build_stage_questions(
            session,
            stg,
            available_agents=available_agents,
            has_secondary_character=True,
            allow_narration=True,
        )
        resolved_qs = apply_question_overrides(base_qs, overrides)
        resolved_by_key = {q["key"]: q for q in resolved_qs}

        seen_keys = set()
        for q in base_qs:
            key = q["key"]
            seen_keys.add(key)
            ov = overrides.get(key)
            current = resolved_by_key.get(key, q)
            result.append({
                "stage": stg,
                "key": key,
                "type": q["type"],
                "default_question": q.get("question") or q.get("statement") or "",
                "question": current.get("question") or current.get("statement") or "",
                "default_options": q.get("options") or q.get("rubric") or {},
                "options": current.get("options") or current.get("rubric") or {},
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
