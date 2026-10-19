"""Illustrator Service — crafts ComfyUI generation prompts and dispatches image jobs."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from core.entities import Character, Chat, Message
from infrastructure.logging import get_logger
from services.model_availability_service import ModelAvailabilityService

logger = get_logger("illustrator_service")

FALLBACK_ILLUSTRATOR_PROMPT = (
    "You are an expert anime and fantasy prompt artist. Given the current scene beat "
    "and character appearances, formulate a high-quality descriptive visual prompt "
    "capturing character appearance, outfit, composition, camera angle, and atmosphere."
)

_RECENT_SCENE_MESSAGES = 6


def _illustration_context(
    chat: Chat,
    character: Character | None,
    *,
    recent_messages: list[Message] | None = None,
) -> str:
    """The scene facts the illustrator agent turns into a ComfyUI prompt."""
    snap = chat.state_snapshot if isinstance(chat.state_snapshot, dict) else {}
    lines: list[str] = ["Current scene facts:"]

    if character:
        lines.append(f"- Character: {character.name}")
        if character.description:
            description = " ".join(str(character.description).split())
            lines.append(f"- Appearance / persona: {description[:600]}")
        if character.visual_tags:
            lines.append(f"- Visual tags: {', '.join(character.visual_tags[:20])}")

    if snap.get("character_outfit"):
        lines.append(f"- Outfit: {snap['character_outfit']}")
    expression = snap.get("character_expression")
    if expression:
        lines.append(f"- Expression: {expression}")
    if chat.story_location:
        lines.append(f"- Location: {chat.story_location}")
    if chat.story_time:
        lines.append(f"- Time: {chat.story_time}")
    weather = snap.get("weather")
    if weather:
        lines.append(f"- Weather / atmosphere: {weather}")

    scene_lines = []
    for message in recent_messages or []:
        content = " ".join((message.content or "").split())
        if not content:
            continue
        if message.role.value == "user":
            speaker = chat.persona_name or "User"
        else:
            speaker = character.name if character else "Character"
        scene_lines.append(f"{speaker}: {content[:500]}")
    if scene_lines:
        lines.append("")
        lines.append("Recent scene:")
        lines.extend(scene_lines)

    lines.append("")
    lines.append(
        "Write the image prompt now. Respond with the prompt text only (comma-separated "
        "Danbooru tags)."
    )
    return "\n".join(lines)


def _load_session_messages(session: Session, chat_id: str, limit: int = _RECENT_SCENE_MESSAGES) -> list[Message]:
    newest = list(
        session.exec(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        ).all()
    )
    newest.reverse()
    return newest


async def enqueue_scene_illustration_job(
    session: Session,
    *,
    job_service: Any,
    chat_id: str,
    character_id: Optional[str] = None,
    branch_id: Optional[str] = None,
    source_job_id: Optional[str] = None,
) -> Optional[str]:
    """Queue the illustrator agent's LLM job, which chains into an image job.

    The agent profile (and its active prompt variant) decides the prompt, the
    camera and the expression; Laya only decides *that* an image is warranted. The
    job is marked `source: scene_prompt` and `background: true` so
    `job_processing` chains its returned prompt text into an image without
    rendering a reply bubble. The Illustrator never calls tools.
    """
    chat = session.get(Chat, chat_id)
    if not chat:
        return None

    character = session.get(Character, character_id or chat.character_id) if (character_id or chat.character_id) else None

    from services.agent_variants import resolve_agent

    resolved = resolve_agent(session, "illustrator", require_enabled=False)
    if resolved is not None and not resolved.profile.enabled:
        logger.info("illustrator_agent_disabled", chat_id=chat_id)
        return None

    from services.chat_utils import render_agent_template

    template = resolved.prompt_template if resolved is not None else FALLBACK_ILLUSTRATOR_PROMPT
    system_prompt = render_agent_template(
        template,
        character_name=character.name if character else "Character",
        user_name=chat.persona_name or "User",
        story_location=chat.story_location or "",
        story_time=chat.story_time or "",
    )

    recent_messages = _load_session_messages(session, chat_id)
    context = _illustration_context(
        chat,
        character,
        recent_messages=recent_messages,
    )

    checkpoint = character.checkpoint if character else None
    if not checkpoint:
        try:
            from services.chat_utils import resolve_scenario_defaults

            scenario_checkpoint, _ = resolve_scenario_defaults(session, chat)
            checkpoint = scenario_checkpoint
        except Exception as exc:
            logger.debug("illustrator_scenario_defaults_failed", chat_id=chat_id, error=str(exc))
    if not checkpoint:
        try:
            checkpoint = ModelAvailabilityService(session).resolve_checkpoint()
        except Exception as exc:
            logger.debug("illustrator_checkpoint_resolution_failed", chat_id=chat_id, error=str(exc))

    from services.job_queue import queue_manager
    from services.llm_config import model_for_kind
    from services.llm_workflow import build_llm_workflow
    workflow, metadata = build_llm_workflow(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ],
        type_="illustrator",
        chat_id=chat_id,
        character_id=character.id if character else None,
        model=model_for_kind("illustrator", chat.llm_model, session),
        workspace="chat",
        source="scene_prompt",
        parent_job_id=source_job_id,
        background=True,
        samplers=resolved.sampler_overrides() if resolved is not None else None,
        extra_metadata={
            "scene_checkpoint": checkpoint,
            "generator_checkpoint": checkpoint,
            "branch_id": branch_id,
            "agent_slug": "illustrator",
            "agent_variant_slug": resolved.variant_slug if resolved is not None else None,
        },
    )
    try:
        job = await job_service.create_job(task_type="llm", workflow=workflow, metadata=metadata)
        await queue_manager.enqueue(job.id, task_type="llm")
        logger.info(
            "illustrator_agent_job_queued",
            chat_id=chat_id,
            job_id=job.id,
            variant=metadata.get("agent_variant_slug"),
        )
        return job.id
    except Exception as exc:
        logger.error("illustrator_agent_job_failed", chat_id=chat_id, error=str(exc), exc_info=True)
        return None

