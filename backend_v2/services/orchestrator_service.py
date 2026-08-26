"""
Agentic Orchestrator Service

Executes tool calls from LLM responses and chains follow-up jobs.
Works as a post-completion processor inside job_processing.py:
  1. LLM returns tool_calls → execute tools (create sub-jobs, wait)
  2. Feed tool results back as a follow-up LLM job
  3. Repeat until plain text response (max depth enforced)
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from core.entities import JobStatus, MessageKind
from infrastructure.logging import get_logger
from services.chat_utils import insert_world_state_marker
from services.job_service import JobService
from services.model_availability_service import ModelAvailabilityService

logger = get_logger("orchestrator")

MAX_AGENTIC_DEPTH = 5

# Top-level guard so a single misbehaving tool whose internal call does not
# enforce its own timeout cannot hang the agentic loop indefinitely. Inner
# per-call timeouts (call_llm_provider, wait_for_job_completion) are still
# kept; this is a safety net above them.
TOOL_TIMEOUT = 120

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
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": (
                "Search the character's long-term memories for relevant information. "
                "Use this when the character needs to remember something from a previous "
                "conversation or when the user asks about past events. Returns the top-K "
                "most semantically relevant memories."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search memories for — a question, topic, or keyword.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of memories to return (default 5, max 20).",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "store_memory",
            "description": (
                "Store a new memory for the character — something important that happened, "
                "a fact about the user, or a piece of world knowledge the character should "
                "remember in future conversations. Use this when something significant is "
                "established in the conversation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The memory to store — a concise summary of the key fact or event.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags to categorize the memory (e.g. ['relationship', 'quest']).",
                    },
                    "importance": {
                        "type": "integer",
                        "description": "Importance level 1-10 (default 5). Higher importance memories are prioritized in context.",
                        "default": 5,
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_expression",
            "description": (
                "Change the character's current facial expression / avatar. "
                "Use this when the character's emotional state changes in a way "
                "that should be reflected visually — anger, surprise, joy, etc. "
                "The expression name must match one configured on the character."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The expression name to switch to (e.g. 'happy', 'angry', 'surprised', 'neutral').",
                    },
                },
                "required": ["expression"],
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
        # recall_memory, store_memory, and set_expression are always available
        # for chats that have a character
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


def get_max_agentic_depth(chat_or_story=None, metadata: dict[str, Any] | None = None) -> int:
    """Resolve the max agentic depth: per-entity override > metadata > global default."""
    if chat_or_story is not None and getattr(chat_or_story, "max_agentic_depth", None) is not None:
        return int(chat_or_story.max_agentic_depth)
    if metadata and metadata.get("max_agentic_depth") is not None:
        return int(metadata["max_agentic_depth"])
    return MAX_AGENTIC_DEPTH


def can_continue_agentic(metadata: dict[str, Any] | None, chat_or_story=None) -> bool:
    """Whether the orchestrator should process another iteration."""
    return get_agentic_depth(metadata) < get_max_agentic_depth(chat_or_story, metadata)


async def execute_tool(
    tool_call: dict[str, Any],
    *,
    chat_id: str | None = None,
    character_id: str | None = None,
    source_job_id: str | None = None,
) -> dict[str, Any]:
    """
    Execute a single tool call and return the result dict.

    A top-level ``asyncio.wait_for`` guard bounds the whole tool execution so a
    misbehaving tool whose internal call does not enforce its own timeout cannot
    hang the agentic loop indefinitely. Inner per-call timeouts are still kept;
    this is purely a safety net. On timeout a graceful error result is returned
    rather than crashing the loop.
    """
    function = tool_call.get("function", {})
    name = function.get("name", "")
    try:
        args = json.loads(function.get("arguments", "{}"))
    except (json.JSONDecodeError, TypeError):
        args = {}

    async def _run():
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
            return await _tool_update_world_state(
                args,
                chat_id=chat_id,
                source_job_id=source_job_id,
            )

        if name == "recall_memory":
            return await _tool_recall_memory(
                args,
                character_id=character_id,
            )

        if name == "store_memory":
            return await _tool_store_memory(
                args,
                character_id=character_id,
            )

        if name == "set_expression":
            return await _tool_set_expression(
                args,
                character_id=character_id,
                chat_id=chat_id,
                source_job_id=source_job_id,
            )

        return {"status": "error", "error": f"Unknown tool: {name}"}

    try:
        return await asyncio.wait_for(_run(), timeout=TOOL_TIMEOUT)
    except asyncio.TimeoutError:
        logger.error(
            "execute_tool_timed_out",
            tool=name,
            chat_id=chat_id,
            source_job_id=source_job_id,
            timeout=TOOL_TIMEOUT,
        )
        return {
            "status": "error",
            "error": f"Tool '{name}' timed out after {TOOL_TIMEOUT}s",
        }


async def _tool_update_world_state(
    args: dict[str, Any],
    *,
    chat_id: str | None = None,
    source_job_id: str | None = None,
) -> dict[str, Any]:
    """Update a chat's story_time / story_location (side-effect tool)."""
    from infrastructure.deps import get_session_context
    from core.entities import Chat

    time_value = (args.get("time") or "").strip()
    location_value = (args.get("location") or "").strip()

    if not time_value and not location_value:
        return {"status": "error", "error": "Provide at least one of 'time' or 'location'."}
    if not chat_id:
        return {"status": "error", "error": "No chat_id available to update world state."}

    async with get_session_context() as session:
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

            insert_world_state_marker(session, chat_id, updated)

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


async def _tool_narrate_scene(
    args: dict[str, Any],
    *,
    chat_id: str | None = None,
    character_id: str | None = None,
    source_job_id: str | None = None,
) -> dict[str, Any]:
    """Run a Narrator LLM job that writes a third-person scene description."""
    from services.job_submission_service import JobSubmissionService
    from infrastructure.deps import get_session_context

    scene_direction = args.get("scene_direction", "")

    logger.info("tool_narrate_scene", chat_id=chat_id, direction=scene_direction[:80])

    from config import get_system_prompt_blocks
    narrator_prompt = (get_system_prompt_blocks() or {}).get("narrator") or NARRATOR_SYSTEM_PROMPT

    job = None
    async with get_session_context() as session:
        submission = JobSubmissionService(session)

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
            from core.entities import Chat as _Chat, Character as _Char
            from services.context_builder import build_system_prompt_sections_async
            try:
                _chat = session.get(_Chat, chat_id)
                if _chat:
                    _char = session.get(_Char, _chat.character_id) if _chat.character_id else None
                    _sections = await build_system_prompt_sections_async(
                        character=_char,
                        system_prompt_override=_chat.system_prompt_override,
                        append_system_prompt=_chat.append_system_prompt,
                        persona_name=_chat.persona_name,
                        story_time=_chat.story_time,
                        story_location=_chat.story_location,
                        lorebook_ids=_chat.active_lorebook_ids or None,
                        include_roleplay_default=False,
                    )
                    character_system_prompt = "\n\n".join(s["content"] for s in _sections) or None
            except Exception as _e:
                logger.warning("narrator_char_prompt_rebuild_failed", chat_id=chat_id, error=str(_e))

        from services.llm_workflow import build_llm_workflow, sampler_overrides

        narrator_samplers: dict = {}
        if chat_id:
            try:
                from core.entities import Chat as _Chat
                _chat_row = session.get(_Chat, chat_id)
                if _chat_row:
                    narrator_samplers = sampler_overrides(_chat_row)
            except Exception as _e:
                logger.warning("narrator_sampler_lookup_failed", chat_id=chat_id, error=str(_e))

        workflow, metadata = build_llm_workflow(
            messages=messages,
            type_="narrator",
            chat_id=chat_id,
            character_id=character_id,
            character_system_prompt=character_system_prompt,
            model=source_meta.get("model"),
            source="narrator",
            parent_job_id=source_job_id,
            samplers=narrator_samplers or None,
        )

        try:
            job = await submission.job_service.create_job(
                task_type="llm",
                workflow=workflow,
                metadata=metadata,
            )
        except Exception as e:
            logger.error("tool_narrate_scene_create_failed", error=str(e))
            return {"status": "error", "error": f"Failed to create narrator job: {e}"}

    # Inline execution: run the narrator call directly against a load-balanced
    # LLM provider instead of enqueueing and waiting. The agentic chain holds
    # the parent job's queue slot, so a queued narrator job could never be
    # claimed by the single LLM worker (deadlock / 180s timeout). The job row
    # is created (not enqueued) so the _LLMReducer streams status/events and
    # the completion event persists the narration via world_integration.
    from services.load_balancer_factory import create_load_balancer
    from services.provider_runtime import resolve_provider_runtime
    from services.provider_client import (
        call_llm_provider,
        JobCancelledError,
        JobTimeoutError,
        ProviderCallError,
    )
    from config import get_job_timeout

    _lb_released = False
    provider = None
    async with get_session_context() as _session:
        _job_service = JobService(_session)
        load_balancer = create_load_balancer(_session, task_type="llm")

        try:
            provider = await load_balancer.get_next_provider(
                required_models=None,
                task_type="llm",
            )
            if provider is None:
                await _job_service.update_job(job.id, status=JobStatus.FAILED, error="No available LLM providers")
                return {"status": "error", "error": "No available LLM providers for narration"}

            try:
                runtime = resolve_provider_runtime(provider)
                if runtime.mode not in ("container_http", "discovery"):
                    # Configuration issue, not a runtime failure: do NOT
                    # penalize the provider's failure counter. The provider is
                    # simply not usable in this mode. Only genuine runtime
                    # failures during execution should call report_failure.
                    await _job_service.update_job(job.id, status=JobStatus.FAILED, error="Provider runtime unavailable")
                    _lb_released = True
                    await load_balancer.release_job(provider.id)
                    return {"status": "error", "error": f"Provider {provider.id} runtime unavailable"}

                timeout = get_job_timeout("llm")
                final_result = await call_llm_provider(
                    worker_url=runtime.worker_url,
                    workflow=workflow,
                    job_id=job.id,
                    job_service=_job_service,
                    timeout=timeout,
                    provider_id=provider.id,
                    provider_type=provider.type,
                )

                await load_balancer.report_success(provider.id)
                _lb_released = True
                await load_balancer.release_job(provider.id)

                content = ""
                outputs = final_result.get("outputs") or []
                if outputs and isinstance(outputs[0], dict):
                    content = outputs[0].get("content", "")
                if not content:
                    content = final_result.get("text", "")

                # Persist narration as a visible narrator message so the user
                # sees the scene being set, not just the final character reply.
                if content:
                    try:
                        narration_msg = Message(
                            id=str(uuid.uuid4()),
                            chat_id=chat_id,
                            role=MessageRole.SYSTEM,
                            kind=MessageKind.NARRATOR,
                            content=content,
                            message_metadata={"source": "narrator", "narration_job_id": job.id},
                            created_at=datetime.now(timezone.utc),
                            updated_at=datetime.now(timezone.utc),
                        )
                        _session.add(narration_msg)
                        _session.commit()
                    except Exception as persist_exc:
                        logger.warning("narrator_message_persist_failed", chat_id=chat_id, error=str(persist_exc))

                return {"status": "success", "narration": content, "job_id": job.id}
            except (JobCancelledError, JobTimeoutError, ProviderCallError) as exc:
                logger.warning("tool_narrate_scene_inline_failed", job_id=job.id, error=str(exc))
                try:
                    await _job_service.update_job(
                        job.id,
                        status=JobStatus.CANCELLED if isinstance(exc, JobCancelledError) else JobStatus.FAILED,
                        error=str(exc),
                    )
                except Exception as update_exc:
                    logger.warning("tool_narrate_scene_status_update_failed", error=str(update_exc))
                await load_balancer.report_failure(provider.id)
                _lb_released = True
                await load_balancer.release_job(provider.id)
                return {"status": "error", "error": f"Narration failed: {exc}"}
            except Exception as exc:
                logger.error("tool_narrate_scene_inline_fatal", job_id=job.id, error=str(exc))
                try:
                    await _job_service.update_job(
                        job.id,
                        status=JobStatus.FAILED,
                        error=f"Narration failed: {exc}",
                    )
                except Exception as update_exc:
                    logger.warning("tool_narrate_scene_status_update_failed", error=str(update_exc))
                await load_balancer.report_failure(provider.id)
                _lb_released = True
                await load_balancer.release_job(provider.id)
                return {"status": "error", "error": f"Narration failed: {exc}"}
        finally:
            if not _lb_released and provider is not None:
                try:
                    await load_balancer.release_job(provider.id)
                except Exception:
                    pass


async def _tool_generate_image(
    args: dict[str, Any],
    *,
    chat_id: str | None = None,
    character_id: str | None = None,
    source_job_id: str | None = None,
) -> dict[str, Any]:
    """Generate an image via the job pipeline and wait for completion."""
    from services.job_submission_service import JobSubmissionService
    from infrastructure.deps import get_session_context

    prompt = args.get("prompt", "a beautiful fantasy landscape")
    negative = args.get("negative_prompt", "worst quality, low quality, bad anatomy")

    logger.info("tool_generate_image", prompt=prompt[:80], chat_id=chat_id)

    async with get_session_context() as session:
        submission = JobSubmissionService(session)

        # 1. Start with system default checkpoint
        ckpt_name = None
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
                if char.visual_tags:
                    tags = ", ".join(char.visual_tags)
                    prompt = f"{prompt}, {tags}" if prompt else tags

        # 4. Ensure the chosen models are actually installed on an enabled provider
        availability = ModelAvailabilityService(session)
        resolved_ckpt = availability.get_available_checkpoint(ckpt_name)
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
        if resolved_ckpt != (ckpt_name or ""):
            logger.warning("tool_generate_image_ckpt_fallback", preferred=ckpt_name, used=resolved_ckpt)
        resolved_lora = availability.get_available_lora(lora_name)
        if lora_name and resolved_lora is None:
            logger.warning("tool_generate_image_lora_unavailable", preferred=lora_name)

        from core.workflow_builder import build_image_job_workflow

        workflow, metadata = build_image_job_workflow(
            prompt=prompt,
            negative=negative,
            checkpoint=resolved_ckpt,
            lora=resolved_lora,
            filename_prefix="AgenticGen",
            source="agentic_tool",
            workspace="chat",
            chat_id=chat_id,
            character_id=character_id,
            parent_job_id=source_job_id,
            extra_metadata={"tool_name": "generate_image"},
        )

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


async def _tool_recall_memory(
    args: dict[str, Any],
    *,
    character_id: str | None = None,
) -> dict[str, Any]:
    """Search the character's memories for relevant information."""
    from infrastructure.deps import get_session_context

    query = args.get("query", "")
    limit = min(args.get("limit", 5), 20)

    if not character_id:
        return {"status": "error", "error": "No character_id available for memory recall"}
    if not query:
        return {"status": "error", "error": "Query parameter is required for memory recall"}

    async with get_session_context() as session:
        try:
            from services.rag_pipeline import search_memories

            memories = search_memories(
                session,
                character_id,
                query,
                limit=limit,
                touch_last_accessed=True,
            )

            results = [
                {
                    "content": mem.content,
                    "tags": mem.tags,
                    "importance": mem.importance,
                }
                for mem in memories
            ]

            return {
                "status": "success",
                "results": results,
                "count": len(results),
            }
        except Exception as exc:
            logger.error("tool_recall_memory_failed", character_id=character_id, error=str(exc))
            return {"status": "error", "error": str(exc)}


async def _tool_store_memory(
    args: dict[str, Any],
    *,
    character_id: str | None = None,
) -> dict[str, Any]:
    """Store a new memory for the character."""
    from infrastructure.deps import get_session_context
    from core.entities import CharacterMemory
    from services.embedding_service import get_embedding_service

    content = args.get("content", "")
    tags = args.get("tags") or []
    importance = int(min(max(args.get("importance", 5), 1), 10))

    if not character_id:
        return {"status": "error", "error": "No character_id available for storing memory"}
    if not content:
        return {"status": "error", "error": "Content parameter is required for storing memory"}

    async with get_session_context() as session:
        try:
            mem = CharacterMemory(
                character_id=character_id,
                content=content,
                tags=tags,
                importance=importance,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

            # Generate embedding
            emb_svc = get_embedding_service()
            try:
                mem.embedding = emb_svc.generate_embedding(content)
            except Exception as e:
                logger.debug("embedding_generation_failed", error=str(e))  # Embedding is optional

            session.add(mem)
            session.commit()
            session.refresh(mem)

            logger.info(
                "tool_store_memory",
                character_id=character_id,
                memory_id=mem.id,
                tags=tags,
            )
            return {
                "status": "success",
                "memory_id": mem.id,
                "content": content,
                "tags": tags,
                "importance": importance,
            }
        except Exception as exc:
            logger.error("tool_store_memory_failed", character_id=character_id, error=str(exc))
            session.rollback()
            return {"status": "error", "error": str(exc)}


async def _tool_set_expression(
    args: dict[str, Any],
    *,
    character_id: str | None = None,
    chat_id: str | None = None,
    source_job_id: str | None = None,
) -> dict[str, Any]:
    """Update a character's current expression in the chat context."""
    from infrastructure.deps import get_session_context
    from core.entities import Character

    expression = args.get("expression", "")

    if not character_id:
        return {"status": "error", "error": "No character_id available for expression change"}
    if not expression:
        return {"status": "error", "error": "Expression parameter is required"}

    async with get_session_context() as session:
        try:
            char = session.get(Character, character_id)
            if not char:
                return {"status": "error", "error": f"Character {character_id} not found"}

            expressions = char.expressions or {}
            if expression not in expressions:
                return {
                    "status": "error",
                    "error": f"Character '{char.name}' has no expression '{expression}'. Available: {list(expressions.keys())}",
                }

            # Store the expression as a world-state marker so the frontend
            # can display the correct avatar for subsequent messages.
            from services.chat_utils import insert_world_state_marker

            if chat_id:
                insert_world_state_marker(
                    session,
                    chat_id=chat_id,
                    changed={"expression": expression, "expression_avatar": expressions[expression]},
                )

            logger.info(
                "tool_set_expression",
                character_id=character_id,
                chat_id=chat_id,
                expression=expression,
                job_id=source_job_id,
            )
            return {
                "status": "success",
                "expression": expression,
                "avatar_path": expressions[expression],
            }
        except Exception as exc:
            logger.error("tool_set_expression_failed", character_id=character_id, error=str(exc))
            session.rollback()
            return {"status": "error", "error": str(exc)}


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
    max_depth = get_max_agentic_depth(metadata=metadata)
    if not can_continue_agentic(metadata):
        logger.warning(
            "agentic_depth_exceeded",
            job_id=job.id,
            depth=depth,
            max=max_depth,
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

    from services.llm_workflow import SAMPLER_KEYS, build_llm_workflow

    prev_workflow = job.workflow if isinstance(job.workflow, dict) else {}
    followup_model = prev_workflow.get("model")
    # Carry the original job's sampling overrides through every chained hop.
    followup_samplers = {k: prev_workflow[k] for k in SAMPLER_KEYS if prev_workflow.get(k) is not None}

    followup_workflow, followup_metadata = build_llm_workflow(
        messages=context,
        type_="chat_reply",
        chat_id=chat_id,
        character_id=character_id,
        character_system_prompt=metadata.get("character_system_prompt"),
        model=followup_model,
        workspace="chat",
        parent_job_id=job.id,
        samplers=followup_samplers or None,
        extra_metadata={
            "agentic": True,
            "orchestrator_depth": depth + 1,
            "original_messages": context,
            "max_agentic_depth": metadata.get("max_agentic_depth"),
        },
    )
    if allowed_tools is not None:
        followup_workflow["tools"] = [
            t
            for t in AGENTIC_TOOLS
            if t.get("function", {}).get("name") in allowed_tools
        ]
    else:
        # No explicit allow-list was provided.  This branch is only hit
        # when the caller (job_processing.py) omits allowed_tools —
        # normally the parent job's already-filtered tool list is passed
        # through, so this is just a safe fallback to the full tool set.
        followup_workflow["tools"] = AGENTIC_TOOLS

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
