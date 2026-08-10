"""
Agentic Orchestrator Service

Executes tool calls from LLM responses and chains follow-up jobs.
Works as a post-completion processor inside job_processing.py:
  1. LLM returns tool_calls → execute tools (create sub-jobs, wait)
  2. Feed tool results back as a follow-up LLM job
  3. Repeat until plain text response (max depth enforced)
"""

import json
import logging
from typing import Any

from core.workflow_builder import build_image_workflow
from infrastructure.logging import get_logger
from services.model_availability_service import ModelAvailabilityService

logger = get_logger("orchestrator")

MAX_AGENTIC_DEPTH = 5

NARRATOR_SYSTEM_PROMPT = (
    "You are the Narrator of an interactive story — a separate role from the characters. "
    "Your job is to describe the world around the conversation from a third-person standpoint: "
    "the environment, the passage of time, off-screen events, and transitions between scenes. "
    "When the characters agree to meet somewhere, you narrate what happens between the decision "
    "and the meeting. Decide what the story needs most: continue the dialogue, add background "
    "information, or cut to a new scene. Write vivid, cinematic prose in the third person, "
    "present tense, describing actions, atmosphere, and surroundings — never speak as a "
    "character and never write dialogue. Keep it concise (2-5 sentences) unless a scene "
    "transition truly demands more."
)

AGENTIC_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": (
                "Generate an image based on a detailed prompt. "
                "Use this when the conversation calls for visual content: "
                "scene illustrations, character portraits, action shots, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": (
                            "A detailed image generation prompt using comma-separated tags "
                            "(Danbooru style). Include subject, pose, lighting, camera angle, "
                            "style, and quality tags."
                        ),
                    },
                    "negative_prompt": {
                        "type": "string",
                        "description": "Negative prompt to avoid unwanted features.",
                    },
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "narrate_scene",
            "description": (
                "Trigger the Narrator to describe the world around the conversation from a "
                "third-person standpoint: scene transitions, the passage of time, off-screen "
                "events, or what happens between conversations (e.g. after agreeing to meet "
                "somewhere). Use this when the story demands narration that the character "
                "reply alone cannot provide. The narrator decides whether to continue the "
                "conversation, add background information, or cut to a new scene."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scene_direction": {
                        "type": "string",
                        "description": (
                            "Optional guidance for the narrator: what should happen between "
                            "scenes, how much time passes, or what background detail to cover."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_world_state",
            "description": (
                "Update the current story context (time and/or location) when the scene "
                "changes: characters move to another place, the time of day shifts, or a "
                "time skip happens. This keeps the chat's Story Time and Location metadata "
                "in sync with the story. Call it alongside or before narrate_scene when "
                "the world state actually changes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "time": {
                        "type": "string",
                        "description": "The new story time, e.g. 'Midnight', 'Next morning', '+3 hours'. Omit if unchanged.",
                    },
                    "location": {
                        "type": "string",
                        "description": "The new story location, e.g. 'The campus library', 'A quiet café downtown'. Omit if unchanged.",
                    },
                },
                "required": [],
            },
        },
    },
]


def filter_agentic_tools(
    tools: list[dict[str, Any]] | None,
    allow_image: bool = True,
    allow_narration: bool = True,
) -> list[dict[str, Any]]:
    """Return the subset of AGENTIC_TOOLS the chat is permitted to use.

    AGENTIC_TOOLS is a list of dicts, so it must never be passed through
    ``set()`` (dicts are unhashable -> TypeError). Filter with a list
    comprehension instead.
    """
    if not tools:
        return []
    allowed: list[dict[str, Any]] = []
    for tool in tools:
        name = tool.get("function", {}).get("name")
        if name == "generate_image" and not allow_image:
            continue
        if name == "narrate_scene" and not allow_narration:
            continue
        allowed.append(tool)
    return allowed


def has_tool_calls(assistant_output: dict[str, Any]) -> bool:
    """Check if an LLM output dict contains tool calls."""
    return bool(assistant_output.get("tool_calls"))


def get_agentic_depth(metadata: dict[str, Any] | None) -> int:
    """Read the current agentic loop depth from job metadata."""
    if not metadata:
        return 0
    return metadata.get("orchestrator_depth", 0)


def can_continue_agentic(metadata: dict[str, Any] | None) -> bool:
    """Whether the orchestrator should process another iteration."""
    return get_agentic_depth(metadata) < MAX_AGENTIC_DEPTH


def _available_checkpoint(session, preferred: str | None) -> str | None:
    """Pick a checkpoint that is actually installed on an enabled provider."""
    return ModelAvailabilityService(session).get_available_checkpoint(preferred)


def _available_lora(session, preferred: str | None) -> str | None:
    """Pick a LoRA that is actually installed on an enabled provider (or None)."""
    return ModelAvailabilityService(session).get_available_lora(preferred)


async def execute_tool(
    tool_call: dict[str, Any],
    *,
    chat_id: str | None = None,
    character_id: str | None = None,
    source_job_id: str | None = None,
) -> dict[str, Any]:
    """
    Execute a single tool call and return the result dict.
    Currently supports: generate_image
    """
    function = tool_call.get("function", {})
    name = function.get("name", "")
    try:
        args = json.loads(function.get("arguments", "{}"))
    except (json.JSONDecodeError, TypeError):
        args = {}

    if name == "generate_image":
        return await _tool_generate_image(
            args,
            chat_id=chat_id,
            character_id=character_id,
            source_job_id=source_job_id,
        )

    if name == "narrate_scene":
        return await _tool_narrate_scene(
            args,
            chat_id=chat_id,
            character_id=character_id,
            source_job_id=source_job_id,
        )

    if name == "update_world_state":
        return _tool_update_world_state(
            args,
            chat_id=chat_id,
            source_job_id=source_job_id,
        )

    return {"status": "error", "error": f"Unknown tool: {name}"}


def _tool_update_world_state(
    args: dict[str, Any],
    *,
    chat_id: str | None = None,
    source_job_id: str | None = None,
) -> dict[str, Any]:
    """Synchronously update a chat's story_time / story_location (side-effect tool)."""
    from infrastructure.database import get_session_sync
    from core.entities import Chat, Message, MessageRole

    time_value = (args.get("time") or "").strip()
    location_value = (args.get("location") or "").strip()

    if not time_value and not location_value:
        return {"status": "error", "error": "Provide at least one of 'time' or 'location'."}
    if not chat_id:
        return {"status": "error", "error": "No chat_id available to update world state."}

    session = get_session_sync()
    try:
        chat = session.get(Chat, chat_id)
        if not chat:
            return {"status": "error", "error": f"Chat {chat_id} not found."}
        updated = {}
        if time_value:
            chat.story_time = time_value
            updated["time"] = time_value
        if location_value:
            chat.story_location = location_value
            updated["location"] = location_value
        session.add(chat)
        session.commit()

        # Insert a UI-only world-state divider marker so the chat shows the scene split.
        try:
            from datetime import datetime, timezone
            parts = []
            if updated.get("location"):
                parts.append(f"Location: {updated['location']}")
            if updated.get("time"):
                parts.append(f"Time: {updated['time']}")
            marker = Message(
                chat_id=chat_id,
                role=MessageRole.SYSTEM,
                content="\n".join(parts),
                message_metadata={"source": "world_state", **updated},
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(marker)
            session.commit()
        except Exception as marker_exc:  # pragma: no cover
            session.rollback()
            logger.warning("tool_update_world_state_marker_failed", chat_id=chat_id, error=str(marker_exc))

        logger.info(
            "tool_update_world_state",
            chat_id=chat_id,
            job_id=source_job_id,
            updated=updated,
        )
        return {"status": "success", "updated": updated}
    except Exception as exc:  # pragma: no cover
        session.rollback()
        logger.error("tool_update_world_state_failed", chat_id=chat_id, error=str(exc))
        return {"status": "error", "error": f"Failed to update world state: {exc}"}
    finally:
        session.close()


async def _tool_narrate_scene(
    args: dict[str, Any],
    *,
    chat_id: str | None = None,
    character_id: str | None = None,
    source_job_id: str | None = None,
) -> dict[str, Any]:
    """Run a Narrator LLM job that writes a third-person scene description."""
    from services.job_submission_service import JobSubmissionService
    from infrastructure.database import get_session_sync

    scene_direction = args.get("scene_direction", "")

    logger.info("tool_narrate_scene", chat_id=chat_id, direction=scene_direction[:80])

    from config import get_system_prompt_blocks
    narrator_prompt = (get_system_prompt_blocks() or {}).get("narrator") or NARRATOR_SYSTEM_PROMPT

    session = get_session_sync()

    messages: list[dict[str, Any]] = [{"role": "system", "content": narrator_prompt}]

    source_context: list[dict[str, Any]] = []
    source_meta: dict[str, Any] = {}
    if source_job_id:
        from core.entities import Job
        source_job = session.get(Job, source_job_id)
        if source_job:
            source_meta = getattr(source_job, "metadata_", None) or {}
            source_context = source_meta.get("original_messages", []) or []
            if not source_context and isinstance(source_job.workflow, dict):
                source_context = source_job.workflow.get("messages", [])

    if source_context:
        messages.extend(source_context[-12:])
    elif chat_id:
        from sqlmodel import select
        from core.entities import Message, MessageRole
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
        recent = session.exec(
            select(Message)
            .where(Message.chat_id == chat_id, Message.created_at >= cutoff)
            .order_by(Message.created_at)
        ).all()
        for m in recent[-20:]:
            if m.role == MessageRole.SYSTEM and (m.message_metadata or {}).get("source") == "narrator":
                continue
            messages.append({"role": "user" if m.role == MessageRole.USER else "assistant", "content": m.content})

    if scene_direction:
        messages.append({"role": "user", "content": f"[Narrate: {scene_direction}]"})

    character_system_prompt = source_meta.get("character_system_prompt")
    if not character_system_prompt and chat_id:
        # Re-build the character system prompt fresh from DB so the narrator
        # always has the full character identity even in deeply-chained agentic jobs.
        try:
            from infrastructure.database import get_session_sync as _gsync
            from core.entities import Chat as _Chat, Character as _Char
            from services.context_builder import build_system_prompt_sections
            _s = _gsync()
            try:
                _chat = _s.get(_Chat, chat_id)
                if _chat:
                    _char = _s.get(_Char, _chat.character_id) if _chat.character_id else None
                    _sections = build_system_prompt_sections(
                        _s,
                        character=_char,
                        system_prompt_override=_chat.system_prompt_override,
                        append_system_prompt=_chat.append_system_prompt,
                        persona_name=_chat.persona_name,
                        story_time=_chat.story_time,
                        story_location=_chat.story_location,
                        lorebook_ids=_chat.active_lorebook_ids or None,
                        # Don't include roleplay_default in the narrator context —
                        # the narrator has its own dedicated system prompt.
                        include_roleplay_default=False,
                    )
                    character_system_prompt = "\n\n".join(s["content"] for s in _sections) or None
            finally:
                _s.close()
        except Exception as _e:
            logger.warning("narrator_char_prompt_rebuild_failed", chat_id=chat_id, error=str(_e))

    from services.llm_workflow import build_llm_workflow

    workflow, metadata = build_llm_workflow(
        messages=messages,
        type_="narrator",
        chat_id=chat_id,
        character_id=character_id,
        character_system_prompt=character_system_prompt,
        model=source_meta.get("model"),
        source="narrator",
        parent_job_id=source_job_id,
    )

    submission = JobSubmissionService(session)
    try:
        job = await submission.create_and_enqueue_job(
            workflow=workflow,
            metadata=metadata,
            task_type="llm",
        )
    except Exception as e:
        logger.error("tool_narrate_scene_enqueue_failed", error=str(e))
        return {"status": "error", "error": f"Failed to start narrator job: {e}"}

    try:
        from core.events import wait_for_job_completion
        final_status, output = await wait_for_job_completion(job.id, timeout=180.0)
    except Exception as e:
        logger.error("tool_narrate_scene_wait_failed", error=str(e))
        return {"status": "error", "error": f"Failed waiting for narrator job: {e}"}

    if final_status == "completed":
        content = ""
        if output:
            content = output.get("content") or output.get("text") or ""
        return {"status": "success", "narration": content, "job_id": job.id}

    if final_status in ("failed", "cancelled"):
        return {"status": "error", "error": f"Narration {final_status}"}

    return {"status": "error", "error": f"Narration ended with status: {final_status}"}


async def _tool_generate_image(
    args: dict[str, Any],
    *,
    chat_id: str | None = None,
    character_id: str | None = None,
    source_job_id: str | None = None,
) -> dict[str, Any]:
    """Generate an image via the job pipeline and wait for completion."""
    from services.job_submission_service import JobSubmissionService
    from infrastructure.database import get_session_sync

    prompt = args.get("prompt", "a beautiful fantasy landscape")
    negative = args.get("negative_prompt", "worst quality, low quality, bad anatomy")

    logger.info("tool_generate_image", prompt=prompt[:80], chat_id=chat_id)

    session = get_session_sync()
    submission = JobSubmissionService(session)

    # 1. Start with system default checkpoint
    import config as app_config
    default_ckpt = app_config.get_config().get("generator", {}).get("default_checkpoint") or "sd_xl_base_1.0.safetensors"
    
    ckpt_name = default_ckpt
    lora_name = None
    
    # 2. Override with frontend user setting if provided via the parent LLM job metadata
    if source_job_id:
        from core.entities import Job
        source_job = session.get(Job, source_job_id)
        if source_job and getattr(source_job, "metadata_", None):
            frontend_ckpt = source_job.metadata_.get("generator_checkpoint")
            if frontend_ckpt:
                ckpt_name = frontend_ckpt

    # 3. Override with character's preferred models if set
    if character_id:
        from core.entities import Character
        char = session.get(Character, character_id)
        if char:
            if char.checkpoint:
                ckpt_name = char.checkpoint
            if char.lora:
                lora_name = char.lora

    # 4. Ensure the chosen models are actually installed on an enabled provider
    resolved_ckpt = _available_checkpoint(session, ckpt_name)
    if not resolved_ckpt:
        logger.error(
            "tool_generate_image_no_checkpoint",
            preferred=ckpt_name,
        )
        return {
            "status": "error",
            "error": (
                "No image checkpoints are installed on any provider. "
                "Install a checkpoint before using the image generation tool."
            ),
        }
    if resolved_ckpt != ckpt_name:
        logger.warning("tool_generate_image_ckpt_fallback", preferred=ckpt_name, used=resolved_ckpt)
    resolved_lora = _available_lora(session, lora_name)
    if lora_name and resolved_lora is None:
        logger.warning("tool_generate_image_lora_unavailable", preferred=lora_name)

    workflow = build_image_workflow(
        prompt=prompt,
        negative=negative,
        checkpoint=resolved_ckpt,
        lora=resolved_lora,
        filename_prefix="AgenticGen",
    )

    metadata: dict[str, Any] = {"source": "agentic_tool", "tool_name": "generate_image", "workspace": "roleplay"}
    if chat_id:
        metadata["chat_id"] = chat_id
    if character_id:
        metadata["character_id"] = character_id
    if source_job_id:
        metadata["parent_job_id"] = source_job_id

    # Persist generation parameters so the details panel shows real values
    # instead of "Model Unknown".
    metadata["prompt"] = prompt
    metadata["negativePrompt"] = negative
    metadata["checkpoint"] = resolved_ckpt
    if resolved_lora:
        metadata["loras"] = [resolved_lora]
    metadata["steps"] = 20
    metadata["cfg"] = 7
    metadata["sampler"] = "euler"
    metadata["scheduler"] = "normal"
    metadata["width"] = 1024
    metadata["height"] = 1024
    metadata["seed"] = 0

    try:
        job = await submission.create_and_enqueue_job(
            workflow=workflow,
            metadata=metadata,
        )
    except Exception as e:
        logger.error("tool_generate_image_failed", error=str(e))
        return {"status": "error", "error": str(e)}

    try:
        from core.events import wait_for_job_completion
        final_status, output = await wait_for_job_completion(job.id, timeout=330.0)
    except Exception as e:
        logger.error("wait_for_job_completion_failed", error=str(e))
        return {"status": "error", "error": f"Failed waiting for image job: {e}"}

    if final_status == "completed":
        image_path = None
        if output:
            image_path = output.get("relative_path") or output.get("filename")
        return {
            "status": "success",
            "image_path": image_path or f"Generated_{job.id[:8]}.png",
            "prompt_used": prompt,
            "job_id": job.id,
        }

    if final_status in ("failed", "cancelled"):
        return {"status": "error", "error": f"Image generation {final_status}"}

    return {"status": "error", "error": f"Image generation ended with status: {final_status}"}


async def process_tool_calls_and_chain(
    *,
    job,
    assistant_output: dict[str, Any],
    final_result: dict[str, Any],
    chat_id: str | None,
    character_id: str | None,
    job_service,
    enqueue_fn,
    allowed_tools: set[str] | None = None,
) -> bool:
    """
    Detect tool_calls in an LLM response and chain follow-up jobs.

    Returns True if a follow-up job was enqueued (caller should NOT finalize).
    Returns False if there are no tool_calls (caller should finalize normally).
    """
    tool_calls = assistant_output.get("tool_calls", [])
    if not tool_calls:
        return False

    if allowed_tools:
        filtered = []
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            if name in allowed_tools:
                filtered.append(tc)
        if not filtered:
            logger.info("agentic_tools_all_filtered", job_id=job.id)
            return False
        tool_calls = filtered

    metadata = job.metadata_ or {}
    depth = get_agentic_depth(metadata)
    if not can_continue_agentic(metadata):
        logger.warning(
            "agentic_depth_exceeded",
            job_id=job.id,
            depth=depth,
            max=MAX_AGENTIC_DEPTH,
        )
        return False

    # Note: intermediate narration text is NOT persisted as a SYSTEM message here;
    # it is forwarded to the follow-up job via context so the final reply is the
    # only visible character message for this exchange.

    tool_results = []
    for tc in tool_calls:
        result = await execute_tool(
            tc,
            chat_id=chat_id,
            character_id=character_id,
            source_job_id=job.id,
        )
        tool_results.append({
            "role": "tool",
            "tool_call_id": tc.get("id", ""),
            "name": tc.get("function", {}).get("name", ""),
            "content": json.dumps(result),
        })

    original_messages = metadata.get("original_messages", [])
    context = list(original_messages) if original_messages else []
    if not context:
        wf = job.workflow if isinstance(job.workflow, dict) else {}
        context = wf.get("messages", [])

    context.append(assistant_output)
    context.extend(tool_results)

    followup_metadata: dict[str, Any] = {
        "chat_id": chat_id,
        "character_id": character_id,
        "type": "chat_reply",
        "agentic": True,
        "orchestrator_depth": depth + 1,
        "parent_job_id": job.id,
        "workspace": "roleplay",
        "original_messages": context,
    }

    followup_workflow: dict[str, Any] = {
        "messages": context,
        "chat_id": chat_id,
        "character_system_prompt": metadata.get("character_system_prompt"),
        "type": "chat_reply",
        "tools": AGENTIC_TOOLS,
    }

    try:
        followup_job = await job_service.create_job(
            task_type="llm",
            workflow=followup_workflow,
            metadata=followup_metadata,
        )
        if enqueue_fn is not None:
            await enqueue_fn(followup_job.id)
        else:
            from services.job_queue import queue_manager
            await queue_manager.enqueue(followup_job.id, task_type="llm")
        logger.info(
            "agentic_followup_enqueued",
            parent_job_id=job.id,
            followup_job_id=followup_job.id,
            depth=depth + 1,
            tool_count=len(tool_calls),
        )
        return True
    except Exception as e:
        logger.error("agentic_followup_failed", error=str(e))
        return False
