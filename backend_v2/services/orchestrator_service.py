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
import logging
from typing import Any

from infrastructure.logging import get_logger

logger = get_logger("orchestrator")

MAX_AGENTIC_DEPTH = 5

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

    return {"status": "error", "error": f"Unknown tool: {name}"}


async def _tool_generate_image(
    args: dict[str, Any],
    *,
    chat_id: str | None = None,
    character_id: str | None = None,
    source_job_id: str | None = None,
) -> dict[str, Any]:
    """Generate an image via the job pipeline and wait for completion."""
    from core.entities import JobStatus
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

    workflow = _build_default_image_workflow(prompt, negative, checkpoint=ckpt_name, lora=lora_name)

    metadata: dict[str, Any] = {"source": "agentic_tool", "tool_name": "generate_image"}
    if chat_id:
        metadata["chat_id"] = chat_id
    if character_id:
        metadata["character_id"] = character_id
    if source_job_id:
        metadata["parent_job_id"] = source_job_id

    try:
        job = await submission.create_and_enqueue_job(
            workflow=workflow,
            metadata=metadata,
        )
    except Exception as e:
        logger.error("tool_generate_image_failed", error=str(e))
        return {"status": "error", "error": str(e)}

    for _ in range(120):
        try:
            from services.job_service import JobService
            js = JobService(session)
            job_status = await js.get_job(job.id)
        except Exception:
            await asyncio.sleep(1.0)
            continue

        if job_status.status == JobStatus.COMPLETED:
            outputs = job_status.outputs or []
            image_path = None
            if outputs:
                image_path = outputs[0].get("relative_path") or outputs[0].get("filename")
            return {
                "status": "success",
                "image_path": image_path or f"Generated_{job.id[:8]}.png",
                "prompt_used": prompt,
                "job_id": job.id,
            }

        if job_status.status in (JobStatus.FAILED, JobStatus.CANCELLED):
            return {"status": "error", "error": job_status.error or "Image generation failed"}

        await asyncio.sleep(1.0)

    return {"status": "error", "error": "Image generation timed out (120s)"}


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
) -> bool:
    """
    Detect tool_calls in an LLM response and chain follow-up jobs.

    Returns True if a follow-up job was enqueued (caller should NOT finalize).
    Returns False if there are no tool_calls (caller should finalize normally).
    """
    tool_calls = assistant_output.get("tool_calls", [])
    if not tool_calls:
        return False

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

    text_content = assistant_output.get("content", "")
    if text_content:
        await _persist_system_message(
            chat_id=chat_id,
            content=f"*{text_content}*",
        )

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

        if result.get("image_path") and chat_id:
            await _persist_tool_image_message(
                chat_id=chat_id,
                image_path=result["image_path"],
                tool_name=tc.get("function", {}).get("name", ""),
            )

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


async def _persist_system_message(chat_id: str, content: str) -> None:
    """Persist a system message to the chat (for tool-use narration)."""
    try:
        from datetime import datetime, timezone
        from sqlmodel import Session
        from core.entities import Message, MessageRole
        from infrastructure.database import engine

        with Session(engine) as session:
            msg = Message(
                chat_id=chat_id,
                role=MessageRole.SYSTEM,
                content=content,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(msg)
            session.commit()
    except Exception as e:
        logger.error("persist_system_message_failed", error=str(e))


async def _persist_tool_image_message(chat_id: str, image_path: str, tool_name: str) -> None:
    """Persist a system message with the generated image to the chat."""
    try:
        from datetime import datetime, timezone
        from sqlmodel import Session
        from core.entities import Message, MessageRole
        from infrastructure.database import engine

        with Session(engine) as session:
            msg = Message(
                chat_id=chat_id,
                role=MessageRole.SYSTEM,
                content=f"[Image generated by {tool_name}]",
                image_path=image_path,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(msg)
            session.commit()
    except Exception as e:
        logger.error("persist_tool_image_message_failed", error=str(e))
