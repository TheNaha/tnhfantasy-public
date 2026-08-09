import asyncio
from typing import Any

from core.entities import (
    Chat,
    Character,
    Message,
    MessageRole,
    MessageKind,
    Collection,
    CollectionImage,
    StoryChapter,
    StoryBeatRole,
)
from core.events import event_bus, EventType, Event
from infrastructure.database import engine
from infrastructure.logging import get_logger
from sqlmodel import Session, select
from services.context_builder import build_chat_context_async
from services.job_queue import queue_manager
from services.job_service import JobService
from services.llm_config import get_default_llm_model

logger = get_logger("world_integration")

def _resolve_context_tokens(chat: Chat) -> int:
    return chat.max_context_tokens or 4096


def _first_text(job_data: dict[str, Any]) -> str | None:
    """Extract reply text from a completion payload.

    LLM job outputs are [{'role': 'assistant', 'content': ...}] — the text
    lives under 'content', not 'text'. Fall back to the event_extra fields
    (some branches complete with outputs=[] and carry text top-level).
    """
    outputs = job_data.get("outputs") or []
    if outputs and isinstance(outputs[0], dict):
        v = outputs[0].get("content") or outputs[0].get("text")
        if v:
            return v
    return job_data.get("content") or job_data.get("prompt")


async def _handle_impersonation(job_data: dict[str, Any]):
    imp_chat_id = job_data.get("metadata", {}).get("chat_id")
    imp_text = _first_text(job_data)
    if not imp_chat_id or not imp_text:
        return

    with Session(engine) as session:
        try:
            _user_msg = Message(
                chat_id=imp_chat_id,
                role=MessageRole.USER,
                content=imp_text,
                message_metadata={"source": "impersonation"},
            )
            session.add(_user_msg)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.warning("impersonate_insert_failed", job_id=job_data.get("id"), error=str(e))
            return

        try:
            _chat = session.get(Chat, imp_chat_id)
            if _chat:
                _character = session.get(Character, _chat.character_id) if _chat.character_id else None
                _past = session.exec(
                    select(Message)
                    .where(Message.chat_id == imp_chat_id)
                    .order_by(Message.created_at)
                ).all()
                _sp, _ctx = await build_chat_context_async(
                    session,
                    _past,
                    character=_character,
                    lorebook_ids=_chat.active_lorebook_ids or None,
                    persona_name=_chat.persona_name,
                    story_time=_chat.story_time,
                    story_location=_chat.story_location,
                    system_prompt_override=_chat.system_prompt_override,
                    append_system_prompt=_chat.append_system_prompt,
                    max_context_tokens=_resolve_context_tokens(_chat),
                )
                _reply_job_svc = JobService(session)
                _reply_job = await _reply_job_svc.create_job(
                    task_type="llm",
                    workflow={
                        "messages": _ctx,
                        "chat_id": imp_chat_id,
                        "character_system_prompt": _sp or None,
                        "type": "chat_reply",
                        "model": _chat.llm_model or get_default_llm_model(),
                    },
                    metadata={
                        "chat_id": imp_chat_id,
                        "character_id": _chat.character_id,
                        "workspace": "roleplay",
                    },
                )
                await queue_manager.enqueue(_reply_job.id, task_type="llm")
                logger.info("impersonate_reply_enqueued", imp_job=job_data.get("id"), reply_job=_reply_job.id)
        except Exception as e:
            logger.error("impersonate_reply_failed", job_id=job_data.get("id"), error=str(e), exc_info=True)


async def _handle_story_illustrate(job_data: dict[str, Any]):
    prompt = _first_text(job_data)
    story_id = job_data.get("metadata", {}).get("story_id")
    chapter_id = job_data.get("metadata", {}).get("chapter_id")
    preferred_checkpoint = (
        job_data.get("metadata", {}).get("scene_checkpoint")
        or job_data.get("workflow", {}).get("checkpoint")
    )

    if not prompt or not story_id or not chapter_id:
        return

    logger.info(
        "illustrate_prompt_chaining",
        job_id=job_data.get("id"),
        story_id=story_id,
        chapter_id=chapter_id,
        prompt_preview=prompt[:80],
    )
    try:
        from core.workflow_builder import build_image_workflow
        from services.model_availability_service import ModelAvailabilityService

        with Session(engine) as session:
            checkpoint = ModelAvailabilityService(session).get_available_checkpoint(preferred_checkpoint)
            if not checkpoint:
                logger.error("illustrate_no_checkpoint", story_id=story_id, chapter_id=chapter_id)
                return
            _job_service = JobService(session)
            image_workflow = build_image_workflow(prompt, checkpoint=checkpoint, filename_prefix="ComfyUI")
            img_job = await _job_service.create_job(
                task_type="image",
                workflow=image_workflow,
                metadata={
                    "story_id": story_id,
                    "chapter_id": chapter_id,
                    "prompt": prompt,
                    "source": "story_illustrate",
                },
            )
            await queue_manager.enqueue(img_job.id, task_type="image")
            logger.info("illustrate_image_job_queued", job_id=img_job.id, story_id=story_id)
    except Exception as e:
        logger.error("illustrate_chain_failed", job_id=job_data.get("id"), error=str(e), exc_info=True)


async def _handle_scene_prompt(job_data: dict[str, Any]):
    """Chain a chat scene prompt into an image job (non-agentic fallback path)."""
    from core.workflow_builder import build_image_workflow, DEFAULT_NEGATIVE_PROMPT
    from services.model_availability_service import ModelAvailabilityService

    prompt = _first_text(job_data)
    metadata = job_data.get("metadata", {})
    chat_id = metadata.get("chat_id")
    character_id = metadata.get("character_id")
    preferred_checkpoint = (
        metadata.get("scene_checkpoint")
        or metadata.get("checkpoint")
    )

    if not prompt or not chat_id:
        return

    logger.info(
        "scene_prompt_chaining",
        job_id=job_data.get("id"),
        chat_id=chat_id,
        prompt_preview=prompt[:80],
    )
    try:
        with Session(engine) as session:
            resolved_ckpt = ModelAvailabilityService(session).get_available_checkpoint(preferred_checkpoint)
            if not resolved_ckpt:
                logger.error("scene_prompt_no_checkpoint", chat_id=chat_id)
                return
            workflow = build_image_workflow(
                prompt,
                DEFAULT_NEGATIVE_PROMPT,
                checkpoint=resolved_ckpt,
                filename_prefix="ComfyUI",
            )
            img_job = await JobService(session).create_job(
                task_type="image",
                workflow=workflow,
                metadata={
                    "chat_id": chat_id,
                    "character_id": character_id,
                    "prompt": prompt,
                    "source": "scene_illustrate",
                },
            )
            await queue_manager.enqueue(img_job.id, task_type="image")
            logger.info("scene_image_job_queued", job_id=img_job.id, chat_id=chat_id)
    except Exception as e:
        logger.error("scene_chain_failed", job_id=job_data.get("id"), error=str(e), exc_info=True)


async def _handle_narrator(job_data: dict[str, Any]):
    chat_id = job_data.get("metadata", {}).get("chat_id")
    content = _first_text(job_data)
    if not chat_id or not content:
        return

    with Session(engine) as session:
        try:
            msg = Message(
                role=MessageRole.SYSTEM,
                kind=MessageKind.NARRATOR,
                content=content,
                chat_id=chat_id,
                message_metadata={"source": "narrator"},
            )
            session.add(msg)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.warning("narrator_insert_failed", job_id=job_data.get("id"), error=str(e))


async def _handle_chat_reply(job_data: dict[str, Any]):
    chat_id = job_data.get("metadata", {}).get("chat_id")
    content = _first_text(job_data)

    if not chat_id or not content:
        return

    # Capture tool calls (agentic loop) as a transcript on the message so the
    # UI can show what the character did (generated an image, narrated, etc.)
    # without needing to re-derive it. The orchestrator chains follow-up jobs
    # for the actual tool effects; this is just the inline record.
    tool_calls = None
    outputs = job_data.get("outputs") or []
    if outputs and isinstance(outputs[0], dict):
        tool_calls = outputs[0].get("tool_calls")

    # NOTE: regeneration deletes the old trailing messages in the route
    # (chats.py regenerate_reply) and then enqueues a fresh job, so both the
    # normal and regenerated paths must insert a NEW CHAR message. The old
    # alternates/swipe overwrite branch was removed — it overwrote the
    # character message BEFORE the prompt because the old reply was already
    # deleted, pushing regenerated output above the prompt.
    with Session(engine) as session:
        try:
            msg = Message(
                role=MessageRole.CHAR,
                kind=MessageKind.CHAR,
                content=content,
                chat_id=chat_id,
                tool_calls=tool_calls,
                message_metadata={"agentic": bool(tool_calls)},
            )
            session.add(msg)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.warning("chat_reply_insert_failed", job_id=job_data.get("id"), error=str(e))


async def _handle_story_continue(job_data: dict[str, Any]):
    chapter_id = job_data.get("metadata", {}).get("chapter_id")
    content = _first_text(job_data)
    if not chapter_id or not content:
        return

    with Session(engine) as session:
        try:
            chapter = session.get(StoryChapter, chapter_id)
            if chapter:
                chapter.beats.append({"role": StoryBeatRole.NARRATOR, "content": content})
                chapter.content += f"\n\n{content}\n\n"
                session.add(chapter)
                session.commit()
        except Exception as e:
            session.rollback()
            logger.warning("story_continue_failed", job_id=job_data.get("id"), error=str(e))


async def _handle_chat_image(job_data: dict[str, Any]):
    outputs = job_data.get("outputs", [])
    chat_id = job_data.get("metadata", {}).get("chat_id")
    image_path = (
        outputs[0].get("relative_path") if outputs and isinstance(outputs[0], dict) else None
    ) or job_data.get("image_path")
    metadata = job_data.get("metadata", {})
    if not chat_id or not image_path:
        return

    with Session(engine) as session:
        if metadata.get("source") == "agentic_tool":
            tool_name = metadata.get("tool_name", "generate_image")
            content = f"[Image generated by {tool_name}]"
        else:
            content = metadata.get("image_context", "Generated Image:")
        
        try:
            msg = Message(
                role=MessageRole.SYSTEM,
                kind=MessageKind.IMAGE,
                content=content,
                image_path=image_path,
                chat_id=chat_id,
            )
            session.add(msg)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.warning("chat_image_msg_failed", job_id=job_data.get("id"), error=str(e))

        try:
            character_id = metadata.get("character_id")
            if not character_id:
                chat = session.get(Chat, chat_id)
                if chat:
                    character_id = chat.character_id
            if character_id:
                collection = session.exec(
                    select(Collection).where(Collection.character_id == character_id)
                ).first()
                if collection:
                    existing = session.exec(
                        select(CollectionImage).where(
                            CollectionImage.collection_id == collection.id,
                            CollectionImage.image_filename == image_path,
                        )
                    ).first()
                    if not existing:
                        session.add(CollectionImage(
                            collection_id=collection.id,
                            image_filename=image_path,
                        ))
                        session.commit()
        except Exception as e:
            session.rollback()
            logger.warning("chat_image_collection_failed", job_id=job_data.get("id"), error=str(e))


async def _handle_story_image(job_data: dict[str, Any]):
    outputs = job_data.get("outputs", [])
    chapter_id = job_data.get("metadata", {}).get("chapter_id")
    image_path = (
        outputs[0].get("relative_path") if outputs and isinstance(outputs[0], dict) else None
    ) or job_data.get("image_path")
    if not chapter_id or not image_path:
        return

    with Session(engine) as session:
        try:
            chapter = session.get(StoryChapter, chapter_id)
            if chapter:
                if image_path not in (chapter.image_paths or []):
                    chapter.image_paths = (chapter.image_paths or []) + [image_path]
                    session.add(chapter)
                    session.commit()
        except Exception as e:
            session.rollback()
            logger.warning("story_image_failed", job_id=job_data.get("id"), error=str(e))


async def start_world_integration_service():
    """Start listening to EventBus for world vault events."""
    logger.info("starting_world_integration_service")
    # publish() fans out on the short topic ("job", not "job.completed"),
    # so subscribe to the short topic and filter for terminal events.
    async for event in event_bus.subscribe(EventType.JOB_COMPLETED.value.split(".")[0]):
        if event.type != EventType.JOB_COMPLETED:
            continue
        try:
            # emit_job_event wraps the payload as {"job": {...}}
            job_data = event.data.get("job") or event.data

            # chat_image/story_image/... carry the event kind in the
            # top-level 'type' (merged from event_extra); LLM jobs keep it
            # in workflow.type as well.
            event_type = (
                job_data.get("type")
                or (job_data.get("workflow") or {}).get("type")
                or (job_data.get("metadata") or {}).get("source")
            )
            
            if event_type == "impersonation":
                await _handle_impersonation(job_data)
            elif event_type == "story_illustrate_prompt":
                await _handle_story_illustrate(job_data)
            elif event_type == "scene_prompt":
                await _handle_scene_prompt(job_data)
            elif event_type == "narrator":
                await _handle_narrator(job_data)
            elif event_type == "chat_reply":
                await _handle_chat_reply(job_data)
            elif event_type == "story_continue":
                await _handle_story_continue(job_data)
            elif event_type == "chat_image":
                await _handle_chat_image(job_data)
            elif event_type == "story_image":
                await _handle_story_image(job_data)
        except Exception as exc:
            logger.error("world_integration_event_processing_failed", error=str(exc))
