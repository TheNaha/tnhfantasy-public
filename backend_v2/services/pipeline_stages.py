"""The executors for the roleplay chat pipeline's stages.

Each function here performs ONE stage of the pipeline described by the
manifest in `services/chat_pipeline.py`, and is named by that manifest. The
runner (`services/pipeline_runner.py`) resolves them by dotted path at call
time, so the manifest and the code cannot drift apart.

The code in this module was moved out of `services/job_processing.py` and
`api/routes/world_vault/chats.py` without changing what it does. The stages
are not new behaviour; they are the same behaviour, with the order and the
limits coming from the manifest instead of from the shape of the code.

Every executor takes one argument: the stage context, a plain dict shared by
reference across the stages of a turn. It carries what the stage needs
(session, job, chat, transcript) and what the stages learn (the audit
decision, the updater job id). Two keys are meaningful to the runner:

  `halt`           — set when a stage ends the turn; the walk stops.
  `updater_job_id` — set by the update stage. The chain stage declines to run
                      when it is set, because the chain is then deferred to
                      the updater job's completion hook, where it reads the
                      state the Statekeeper just wrote.
"""

from __future__ import annotations

import asyncio
from typing import Any

from infrastructure.logging import get_logger

from core.pipeline_limits import (
    AUTONOMY_CHAIN_THRESHOLDS,
    MAX_AUTONOMOUS_TURNS,
    MAX_CONTINUATIONS,
)

logger = get_logger("pipeline_stages")


# ---------------------------------------------------------------------------
# Stage 1: Triage
# ---------------------------------------------------------------------------


async def triage_stage(ctx: dict[str, Any]) -> Any:
    """Route the turn: pick the agent, the variant, the pacing directive.

    Runs in the request path, before the context is assembled, because the
    decision it makes — which character speaks, at what pace, with which
    variant — is an input to the context, not a result of it.
    """
    from services.decision_service import DecisionService
    from services.updater_service import record_director_decision

    session = ctx["session"]
    chat = ctx["chat"]
    chat_id = ctx["chat_id"]
    ctx_overrides = ctx["ctx_overrides"]
    request = ctx.get("request")
    past_messages = ctx.get("past_messages") or []

    chars_list = ctx_overrides.get("characters") or []
    primary_char_name = (
        chars_list[0].name if chars_list and getattr(chars_list[0], "name", None) else "Character"
    )
    recent_transcript = [
        {
            "role": m.role.value if hasattr(m.role, "value") else str(m.role),
            "content": m.content or "",
        }
        for m in past_messages[-6:]
    ]
    decision = await DecisionService(session).evaluate_pre_generation_triage(
        character_name=primary_char_name,
        user_name=chat.persona_name or "User",
        story_location=chat.story_location,
        story_time=chat.story_time,
        state_snapshot=chat.state_snapshot or {},
        recent_messages=recent_transcript,
        has_secondary_character=bool(chat.additional_character_ids),
        allow_narration=bool(chat.allow_narration),
    )
    ctx["director_decision"] = decision
    ctx["director_decision_dict"] = decision.to_dict()
    updated_snap = await asyncio.to_thread(record_director_decision, session, chat_id, decision)
    ctx_overrides["state_snapshot"] = updated_snap

    # Format human-readable pacing directive for the actor LLM
    directive_map = {
        "continue_conversation": "Continue the dialogue and interaction naturally.",
        "sensory_detail": "Slow down and emphasize rich sensory, physical, and atmospheric detail.",
        "escalate_tension": "Escalate dramatic tension, stakes, or emotional intensity.",
        "advance_time_or_scene": "Advance the scene forward in time or transition to the next beat.",
        "de_escalate_reflect": "Slow the pace down for emotional reflection, comfort, or aftermath.",
    }
    speed_map = {1: "Slow-motion", 2: "Real-time", 3: "Fast-forward"}
    speed_label = speed_map.get(round(decision.pacing_speed), "Real-time")
    base_dir = (
        f"{directive_map.get(decision.pacing_directive, decision.pacing_directive)} "
        f"(Pacing speed: {speed_label}; Emotional tone: {decision.emotional_tone})"
    )
    if decision.fate_directive:
        base_dir += f" | Fate & Skill Check: [{str(decision.fate_outcome).upper()}] {decision.fate_directive}"
    ctx_overrides["director_directive"] = base_dir

    # Group chat secondary character auto-routing when user didn't pin target_character_id
    if (
        decision.next_speaker == "secondary_character"
        and not (request is not None and getattr(request, "target_character_id", None))
        and chat.additional_character_ids
    ):
        ctx_overrides["active_character_id"] = chat.additional_character_ids[0]

    return decision


# ---------------------------------------------------------------------------
# Stage 3: Audit
# ---------------------------------------------------------------------------


async def audit_stage(ctx: dict[str, Any]) -> Any:
    """Audit the generated reply: is it complete, and which gates fired.

    The continuation lives here, not beside the audit, because it is a branch
    OUT of it: a reply that was cut off is continued and the turn ends there,
    so the illustrate, update and chain stages never run for it. That is what
    the audit stage's own description says it does.
    """
    from services.decision_service import DecisionService
    from services.updater_service import record_director_decision

    session = ctx["session"]
    chat_obj = ctx["chat"]
    char_obj = ctx.get("character")
    chat_id = ctx["chat_id"]
    outputs = ctx.get("outputs") or []
    final_result = ctx.get("final_result") or {}
    assistant_content = ctx.get("assistant_content") or ""
    recent_msgs = ctx.get("recent_msgs") or []
    current_turns = int(ctx.get("current_turns", 1))
    continuation_count = int(ctx.get("continuation_count", 0))

    audit_decision = await DecisionService(session).evaluate_post_generation_audit(
        generated_text=assistant_content or "",
        character_name=char_obj.name if char_obj else "Character",
        user_name=chat_obj.persona_name or "User",
        story_location=chat_obj.story_location,
        story_time=chat_obj.story_time,
        state_snapshot=chat_obj.state_snapshot or {},
        recent_messages=recent_msgs,
        allow_image_generation=bool(chat_obj.allow_image_generation),
        chat_id=chat_id,
        turn=current_turns,
    )
    ctx["audit_decision"] = audit_decision

    # Continuation check: check finish_reason == "length" first, fallback to
    # Laya is_complete
    finish_reason = (
        final_result.get("finish_reason")
        or (outputs[0].get("finish_reason") if outputs and isinstance(outputs[0], dict) else None)
        or ""
    )
    is_incomplete = (finish_reason == "length") or (not audit_decision.is_complete)
    if is_incomplete and continuation_count < _max_continuations():
        cont_job_id = await _enqueue_continuation(ctx, finish_reason=finish_reason)
        if cont_job_id:
            ctx["halt"] = True
            ctx["halt_reason"] = "continuation"
            return audit_decision

    # Record the final audited decision
    await asyncio.to_thread(record_director_decision, session, chat_id, audit_decision)
    return audit_decision


def _max_continuations() -> int:
    from services.pipeline_runner import limit

    return int(limit("audit", "max_continuations", MAX_CONTINUATIONS))


async def _enqueue_continuation(ctx: dict[str, Any], *, finish_reason: str) -> str | None:
    """Continue a reply that was cut off. Returns the new job id, if any."""
    from services.agent_variants import resolve_agent
    from services.chat_utils import render_agent_template
    from services.llm_workflow import build_chat_llm_workflow, sampler_overrides
    from services.llm_config import model_for_kind
    from services.context_builder import build_context
    from services.job_queue import queue_manager

    session = ctx["session"]
    chat_obj = ctx["chat"]
    char_obj = ctx.get("character")
    chat_id = ctx["chat_id"]
    job = ctx["job"]
    job_meta = ctx.get("job_meta") or {}
    job_service = ctx["job_service"]
    assistant_content = ctx.get("assistant_content") or ""
    recent_msgs_objs = ctx.get("recent_msgs_objs") or []
    continuation_count = int(ctx.get("continuation_count", 0))

    system_prompt, context, _sections = await asyncio.to_thread(
        build_context, session, "chat", chat_obj, recent_msgs_objs,
    )

    resolved_cont_agent = resolve_agent(session, "continuation", require_enabled=False)
    fallback_prompt = (
        "[System Note: Your previous response was cut off mid-thought. Continue seamlessly from the exact word where you stopped, without repeating previous text.]"
    )
    cont_instruction = None
    cont_agent_slug = None
    cont_variant_slug = None
    cont_samplers: dict = {}
    if resolved_cont_agent is not None:
        cont_agent_slug = resolved_cont_agent.slug
        cont_variant_slug = resolved_cont_agent.variant_slug
        cont_instruction = render_agent_template(
            resolved_cont_agent.prompt_template,
            character_name=char_obj.name if char_obj else "Character",
            user_name=chat_obj.persona_name or "User",
            story_location=chat_obj.story_location or "",
            story_time=chat_obj.story_time or "",
        )
        cont_samplers = resolved_cont_agent.sampler_overrides()
    if cont_instruction is None:
        cont_instruction = fallback_prompt

    cont_workflow, cont_metadata = build_chat_llm_workflow(
        messages=[
            *context,
            {"role": "assistant", "content": assistant_content or ""},
            {"role": "user", "content": cont_instruction},
        ],
        chat_id=chat_id,
        character_id=char_obj.id if char_obj else None,
        system_prompt=system_prompt or None,
        model=model_for_kind("chat_reply", chat_obj.llm_model, session),
        samplers={**sampler_overrides(chat_obj), **cont_samplers},
        type_="chat_reply",
        source="continuation",
        extra_metadata={
            "continuation_count": continuation_count + 1,
            "continuation_of_job_id": job.id,
            "branch_id": job_meta.get("branch_id"),
            "autonomous_turn_count": job_meta.get("autonomous_turn_count", 1),
            "max_autonomous_turns": job_meta.get("max_autonomous_turns", MAX_AUTONOMOUS_TURNS),
            "agent_slug": cont_agent_slug or "continuation",
            "agent_variant_slug": cont_variant_slug,
        },
    )
    cont_job = await job_service.create_job(task_type="llm", workflow=cont_workflow, metadata=cont_metadata)
    await queue_manager.enqueue(cont_job.id, task_type="llm")
    logger.info(
        "laya_continuation_triggered",
        chat_id=chat_id,
        continuation_count=continuation_count + 1,
        finish_reason=finish_reason,
        agent_slug=cont_agent_slug or "continuation",
        variant_slug=cont_variant_slug,
    )
    return cont_job.id


# ---------------------------------------------------------------------------
# Stage 5: Illustrate
# ---------------------------------------------------------------------------


async def illustrate_stage(ctx: dict[str, Any]) -> str | None:
    """Dispatch the Illustrator agent when the audit says a visual beat is due."""
    session = ctx["session"]
    chat_obj = ctx["chat"]
    job = ctx["job"]
    job_meta = ctx.get("job_meta") or {}
    audit_decision = ctx.get("audit_decision")
    character_id = ctx.get("character_id")

    if audit_decision is None:
        return None

    max_images = getattr(chat_obj, "max_agentic_images", 2) or 2
    if not (
        audit_decision.should_trigger_image
        and getattr(chat_obj, "allow_image_generation", True)
        and job_meta.get("agentic_image_count", 0) < max_images
    ):
        return None

    from services.illustrator_service import enqueue_scene_illustration_job

    try:
        illustrator_job_id = await enqueue_scene_illustration_job(
            session,
            job_service=ctx["job_service"],
            chat_id=ctx["chat_id"],
            character_id=character_id or chat_obj.character_id,
            source_job_id=job.id,
            branch_id=job_meta.get("branch_id"),
        )
    except Exception as img_exc:
        logger.warning("illustrator_agent_trigger_failed", job_id=job.id, error=str(img_exc))
        return None

    if illustrator_job_id:
        logger.info(
            "illustrator_agent_image_triggered",
            chat_id=ctx["chat_id"],
            job_id=illustrator_job_id,
        )
    return illustrator_job_id


# ---------------------------------------------------------------------------
# Stage 4: Update
# ---------------------------------------------------------------------------


async def update_stage(ctx: dict[str, Any]) -> str | None:
    """Enqueue the Statekeeper, and hand it the chain payload.

    The chain payload travels with the updater job rather than running
    straight after it, because the chain's decision depends on the state the
    Statekeeper is about to write. Running the chain here would read the
    pre-update snapshot.
    """
    from services.updater_service import enqueue_state_updater_if_needed

    session = ctx["session"]
    chat_obj = ctx["chat"]
    audit_decision = ctx.get("audit_decision")
    character_id = ctx.get("character_id")
    if audit_decision is None:
        return None

    autonomy_level = getattr(chat_obj, "director_autonomy_level", "balanced") or "balanced"
    max_turns = getattr(chat_obj, "max_autonomous_turns", MAX_AUTONOMOUS_TURNS) or MAX_AUTONOMOUS_TURNS
    current_turns = int(ctx.get("current_turns", 1))
    job_meta = ctx.get("job_meta") or {}

    should_chain = (autonomy_level != "strict" and current_turns < max_turns)
    chain_payload = {
        "turn": current_turns + 1,
        "max_turns": max_turns,
        "autonomy_level": autonomy_level,
        "branch_id": job_meta.get("branch_id"),
        "last_speaker": ctx.get("last_speaker"),
    } if should_chain else None

    updater_job_id = None
    if audit_decision.should_run_updater and (character_id or chat_obj.character_id):
        updater_job_id = await enqueue_state_updater_if_needed(
            session,
            chat_id=ctx["chat_id"],
            character_id=character_id or chat_obj.character_id,
            decision=audit_decision,
            job_service=ctx["job_service"],
            pending_chain=chain_payload,
        )

    ctx["updater_job_id"] = updater_job_id
    ctx["chain_payload"] = chain_payload
    return updater_job_id


# ---------------------------------------------------------------------------
# Stage 6: Chain
# ---------------------------------------------------------------------------


async def chain_stage(ctx: dict[str, Any]) -> str | None:
    """Decide whether the scene wants another autonomous turn, and take it.

    Declines to run when the Statekeeper ran: the chain is then deferred to
    the updater job's completion hook, where it reads the state the
    Statekeeper just wrote.
    """
    if ctx.get("updater_job_id"):
        return None

    from core.entities import Chat, Character
    from infrastructure.repositories.message_repo import MessageRepository
    from services.decision_service import DecisionService
    from services.agent_variants import resolve_agent
    from services.chat_utils import render_agent_template
    from services.llm_workflow import build_chat_llm_workflow, sampler_overrides
    from services.llm_config import model_for_kind
    from services.context_builder import build_context
    from config import get_system_prompt_blocks
    from services.orchestrator_service import NARRATOR_SYSTEM_PROMPT
    from services.job_queue import queue_manager

    session = ctx["session"]
    job_service = ctx["job_service"]
    chat_id = ctx["chat_id"]
    character_id = ctx.get("character_id")
    last_speaker = ctx.get("last_speaker") or "character"
    current_turns = int(ctx.get("current_turns", 1))
    max_turns = int(ctx.get("max_turns", MAX_AUTONOMOUS_TURNS))
    autonomy_level = ctx.get("autonomy_level") or "balanced"
    branch_id = ctx.get("branch_id")

    chat_obj = session.get(Chat, chat_id)
    if not chat_obj:
        return None
    char_obj = session.get(Character, character_id or chat_obj.character_id) if (character_id or chat_obj.character_id) else None

    msg_repo = MessageRepository(session)
    recent_msgs_objs = msg_repo.list_by_chat(chat_id, limit=8, newest_first=True)
    recent_msgs = [
        {
            "role": m.role.value if hasattr(m.role, "value") else str(m.role),
            "content": m.content or "",
        }
        for m in recent_msgs_objs
    ]

    min_chain_prob = AUTONOMY_CHAIN_THRESHOLDS.get(
        autonomy_level, AUTONOMY_CHAIN_THRESHOLDS["balanced"]
    )

    chain_decision = await DecisionService(session).evaluate_turn_chaining(
        last_speaker=last_speaker,
        character_name=char_obj.name if char_obj else "Character",
        user_name=chat_obj.persona_name or "User",
        story_location=chat_obj.story_location,
        story_time=chat_obj.story_time,
        state_snapshot=chat_obj.state_snapshot or {},
        recent_messages=recent_msgs,
        has_secondary_character=bool(chat_obj.additional_character_ids),
        allow_narration=bool(chat_obj.allow_narration),
        chat_id=chat_id,
        turn=current_turns,
    )

    if (
        chain_decision.continue_chain_probability < min_chain_prob
        or chain_decision.next_speaker == "user"
    ):
        return None

    target_speaker = chain_decision.next_speaker

    # Run Stage 1 triage and Fate & Skill check for the target speaker
    primary_slug = "character"
    if char_obj and hasattr(char_obj, "slug") and char_obj.slug:
        primary_slug = char_obj.slug
    triage_decision = await DecisionService(session).evaluate_pre_generation_triage(
        character_name=char_obj.name if char_obj else "Character",
        user_name=chat_obj.persona_name or "User",
        story_location=chat_obj.story_location,
        story_time=chat_obj.story_time,
        state_snapshot=chat_obj.state_snapshot or {},
        recent_messages=recent_msgs,
        last_speaker=last_speaker,
        has_secondary_character=bool(chat_obj.additional_character_ids),
        allow_narration=bool(chat_obj.allow_narration),
        primary_character_slug=primary_slug,
        chat_id=chat_id,
        turn=current_turns,
    )

    # Resolve agent and selected sub-variant
    resolved_agent = resolve_agent(session, target_speaker, variant_slug=triage_decision.selected_variant)

    # Build directive text combining pacing, fate directive, and custom directives
    directives: list[str] = []
    if chain_decision.pacing_directive:
        directives.append(f"Pacing: {chain_decision.pacing_directive}")
    if triage_decision.fate_directive:
        directives.append(f"Fate Check: {triage_decision.fate_outcome} ({triage_decision.fate_directive})")
    for cd in triage_decision.custom_directives:
        if cd.get("directive"):
            directives.append(cd["directive"])
    directive_str = " | ".join(directives)

    followup_job = None
    if target_speaker == "narrator" and getattr(chat_obj, "allow_narration", True):
        narrator_prompt = resolved_agent.prompt_template if resolved_agent else ((get_system_prompt_blocks() or {}).get("narrator") or NARRATOR_SYSTEM_PROMPT)
        system_prompt, context, _sections = await asyncio.to_thread(
            build_context, session, "chat", chat_obj, recent_msgs_objs,
        )
        instruction_content = (
            f"[Scene Direction] {directive_str}: describe the scene consequences, environment, or passage of time."
            if directive_str
            else "[Scene Direction] Describe the scene consequences, environment, or passage of time."
        )
        workflow, metadata = build_chat_llm_workflow(
            messages=[
                {"role": "system", "content": narrator_prompt},
                *context,
                {"role": "user", "content": instruction_content},
            ],
            chat_id=chat_id,
            character_id=char_obj.id if char_obj else None,
            system_prompt=system_prompt or None,
            model=model_for_kind("narrator", chat_obj.llm_model, session),
            samplers={**sampler_overrides(chat_obj), **(resolved_agent.sampler_overrides() if resolved_agent else {})},
            type_="narrator",
            source="narrator",
            extra_metadata={
                "autonomous_turn_count": current_turns,
                "max_autonomous_turns": max_turns,
                "branch_id": branch_id,
                "selected_variant": triage_decision.selected_variant,
            },
        )
        followup_job = await job_service.create_job(task_type="llm", workflow=workflow, metadata=metadata)
        await queue_manager.enqueue(followup_job.id, task_type="llm")
        logger.info("laya_conductor_narrator_chained", chat_id=chat_id, job_id=followup_job.id, turn=current_turns, variant=triage_decision.selected_variant)
    elif target_speaker == "secondary_character" and getattr(chat_obj, "additional_character_ids", None):
        secondary_id = chat_obj.additional_character_ids[0]
        system_prompt, context, _sections = await asyncio.to_thread(
            build_context, session, "chat", chat_obj, recent_msgs_objs, active_character_id=secondary_id,
        )
        instruction_content = (
            f"[Scene Direction] {directive_str}: react to the situation."
            if directive_str
            else "[Scene Direction] React to the situation."
        )
        workflow, metadata = build_chat_llm_workflow(
            messages=[
                *context,
                {"role": "user", "content": instruction_content},
            ],
            chat_id=chat_id,
            character_id=secondary_id,
            system_prompt=system_prompt or None,
            model=model_for_kind("chat_reply", chat_obj.llm_model, session),
            samplers=sampler_overrides(chat_obj),
            extra_metadata={
                "autonomous_turn_count": current_turns,
                "max_autonomous_turns": max_turns,
                "branch_id": branch_id,
            },
        )
        followup_job = await job_service.create_job(task_type="llm", workflow=workflow, metadata=metadata)
        await queue_manager.enqueue(followup_job.id, task_type="llm")
        logger.info("laya_conductor_secondary_char_chained", chat_id=chat_id, secondary_id=secondary_id, job_id=followup_job.id, turn=current_turns)
    elif target_speaker == "character" and char_obj is not None:
        char_custom_prompt = resolved_agent.prompt_template if resolved_agent else None
        system_prompt, context, _sections = await asyncio.to_thread(
            build_context, session, "chat", chat_obj, recent_msgs_objs,
        )
        instruction_content = (
            f"[Scene Direction] {directive_str}: continue the scene as {char_obj.name}."
            if directive_str
            else f"[Scene Direction] Continue the scene as {char_obj.name}."
        )
        workflow, metadata = build_chat_llm_workflow(
            messages=[
                *context,
                {"role": "user", "content": instruction_content},
            ],
            chat_id=chat_id,
            character_id=char_obj.id,
            system_prompt=(char_custom_prompt or system_prompt) or None,
            model=model_for_kind("chat_reply", chat_obj.llm_model, session),
            samplers={**sampler_overrides(chat_obj), **(resolved_agent.sampler_overrides() if resolved_agent else {})},
            type_="chat_reply",
            source="character",
            extra_metadata={
                "autonomous_turn_count": current_turns,
                "max_autonomous_turns": max_turns,
                "branch_id": branch_id,
                "selected_variant": triage_decision.selected_variant,
            },
        )
        followup_job = await job_service.create_job(task_type="llm", workflow=workflow, metadata=metadata)
        await queue_manager.enqueue(followup_job.id, task_type="llm")
        logger.info("laya_conductor_character_chained", chat_id=chat_id, job_id=followup_job.id, turn=current_turns, variant=triage_decision.selected_variant)
    elif resolved_agent:
        custom_agent = resolved_agent.profile
        char_name = char_obj.name if char_obj else "Character"
        u_name = chat_obj.persona_name or "User"
        rendered_prompt = render_agent_template(
            resolved_agent.prompt_template,
            character_name=char_name,
            user_name=u_name,
            story_location=chat_obj.story_location or "",
            story_time=chat_obj.story_time or "",
        )
        system_prompt, context, _sections = await asyncio.to_thread(
            build_context, session, "chat", chat_obj, recent_msgs_objs,
        )
        instruction_content = (
            f"[Agent Directive: {custom_agent.name}] {directive_str}: Continue the scene according to your persona and expertise."
            if directive_str
            else f"[Agent Directive: {custom_agent.name}] Continue the scene according to your persona and expertise."
        )
        workflow, metadata = build_chat_llm_workflow(
            messages=[
                {"role": "system", "content": rendered_prompt},
                *context,
                {"role": "user", "content": instruction_content},
            ],
            chat_id=chat_id,
            character_id=char_obj.id if char_obj else None,
            system_prompt=system_prompt or None,
            model=model_for_kind(custom_agent.model_target, custom_agent.model_override or chat_obj.llm_model, session),
            samplers={**sampler_overrides(chat_obj), **resolved_agent.sampler_overrides()},
            type_="chat_reply",
            source="custom_agent",
            extra_metadata={
                "autonomous_turn_count": current_turns,
                "max_autonomous_turns": max_turns,
                "branch_id": branch_id,
                "agent_slug": target_speaker,
                "selected_variant": triage_decision.selected_variant,
            },
        )
        followup_job = await job_service.create_job(task_type="llm", workflow=workflow, metadata=metadata)
        await queue_manager.enqueue(followup_job.id, task_type="llm")
        logger.info("laya_conductor_custom_agent_chained", chat_id=chat_id, agent=target_speaker, job_id=followup_job.id, turn=current_turns, variant=triage_decision.selected_variant)

    return followup_job.id if followup_job is not None else None
