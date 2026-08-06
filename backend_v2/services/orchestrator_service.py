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

from infrastructure.logging import get_logger

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
]


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


def _ready_model_files(session, directory: str) -> list[str]:
    """List filenames of ready, enabled model files of a directory across enabled providers."""
    from sqlmodel import select

    from core.entities import (
        ModelFile,
        ModelV2,
        ModelVersion,
        Provider,
        ProviderVersionStatus,
    )

    try:
        rows = session.exec(
            select(ModelFile.filename)
            .join(ModelVersion, ModelVersion.id == ModelFile.version_id)
            .join(ModelV2, ModelV2.id == ModelVersion.model_id)
            .join(
                ProviderVersionStatus,
                ProviderVersionStatus.version_id == ModelVersion.id,
            )
            .join(Provider, Provider.id == ProviderVersionStatus.provider_id)
            .where(
                ModelV2.directory == directory,
                ModelVersion.is_enabled == True,  # noqa: E712
                Provider.enabled == True,  # noqa: E712
                ProviderVersionStatus.status == "ready",
            )
            .distinct()
        ).all()
        return [r for r in rows if r]
    except Exception as e:
        logger.warning("ready_model_files_query_failed", directory=directory, error=str(e))
        return []


def _available_checkpoint(session, preferred: str | None) -> str | None:
    """Pick a checkpoint that is actually installed on an enabled provider."""
    ready = _ready_model_files(session, "checkpoints")
    if not ready:
        return None
    if preferred and preferred in ready:
        return preferred
    return ready[0]


def _available_lora(session, preferred: str | None) -> str | None:
    """Pick a LoRA that is actually installed on an enabled provider (or None)."""
    if not preferred:
        return None
    ready = _ready_model_files(session, "loras")
    if preferred in ready:
        return preferred
    return None


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

    return {"status": "error", "error": f"Unknown tool: {name}"}


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

    session = get_session_sync()

    messages: list[dict[str, Any]] = [{"role": "system", "content": NARRATOR_SYSTEM_PROMPT}]

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
        from core.entities import Chat
        chat = session.get(Chat, chat_id)
        if chat and chat.system_prompt_override:
            character_system_prompt = chat.system_prompt_override

    workflow: dict[str, Any] = {
        "messages": messages,
        "chat_id": chat_id,
        "character_system_prompt": character_system_prompt,
        "type": "narrator",
        "model": None,
    }
    if source_meta.get("model"):
        workflow["model"] = source_meta.get("model")

    metadata: dict[str, Any] = {
        "chat_id": chat_id,
        "character_id": character_id,
        "workspace": "roleplay",
        "source": "narrator",
        "type": "narrator",
    }
    if source_job_id:
        metadata["parent_job_id"] = source_job_id

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

    workflow = _build_default_image_workflow(prompt, negative, checkpoint=resolved_ckpt, lora=resolved_lora)

    metadata: dict[str, Any] = {"source": "agentic_tool", "tool_name": "generate_image"}
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


def _build_default_image_workflow(prompt: str, negative: str, checkpoint: str = "sd_xl_base_1.0.safetensors", lora: str | None = None) -> dict[str, Any]:
    """Build a basic SDXL text-to-image workflow."""
    workflow = {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 0,
                "steps": 20,
                "cfg": 7,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1,
                "model": ["10", 0] if lora else ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"batch_size": 1, "width": 1024, "height": 1024},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative, "clip": ["4", 1]},
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "AgenticGen", "images": ["8", 0]},
        },
    }
    
    if lora:
        workflow["10"] = {
            "class_type": "LoraLoader",
            "inputs": {
                "lora_name": lora,
                "strength_model": 1.0,
                "strength_clip": 1.0,
                "model": ["4", 0],
                "clip": ["4", 1]
            }
        }
        workflow["6"]["inputs"]["clip"] = ["10", 1]
        workflow["7"]["inputs"]["clip"] = ["10", 1]
        
    return workflow


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
        from services.job_queue import queue_manager
        followup_job = await job_service.create_job(
            task_type="llm",
            workflow=followup_workflow,
            metadata=followup_metadata,
        )
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
