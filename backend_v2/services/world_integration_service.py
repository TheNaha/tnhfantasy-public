from typing import Any
from uuid import uuid4

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
    Story,
    Lorebook,
    LorebookEntry,
    Location,
)
from core.events import event_bus, EventType
from infrastructure.database import get_session_context
from infrastructure.logging import get_logger
from sqlmodel import select
from services.context_builder import build_chat_context_async
from services.job_queue import queue_manager
from services.job_service import JobService
from services.llm_config import get_default_llm_model

logger = get_logger("world_integration")

from services.chat_utils import extract_first_text as _first_text
from services.chat_utils import resolve_context_tokens as _resolve_context_tokens


async def _handle_impersonation(job_data: dict[str, Any]):
    imp_chat_id = job_data.get("metadata", {}).get("chat_id")
    imp_text = _first_text(job_data)
    if not imp_chat_id or not imp_text:
        return

    async with get_session_context() as session:
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
                    _past,
                    characters=[_character] if _character else None,
                    lorebook_ids=_chat.active_lorebook_ids or None,
                    persona_name=_chat.persona_name,
                    story_time=_chat.story_time,
                    story_location=_chat.story_location,
                    system_prompt_override=_chat.system_prompt_override,
                    append_system_prompt=_chat.append_system_prompt,
                    max_context_tokens=_resolve_context_tokens(_chat),
                )
                _reply_job_svc = JobService(session)
                from services.llm_workflow import build_llm_workflow

                _workflow, _metadata = build_llm_workflow(
                    messages=_ctx,
                    type_="chat_reply",
                    chat_id=imp_chat_id,
                    character_id=_chat.character_id,
                    character_system_prompt=_sp or None,
                    model=_chat.llm_model or get_default_llm_model(),
                    workspace="chat",
                )
                _reply_job = await _reply_job_svc.create_job(
                    task_type="llm",
                    workflow=_workflow,
                    metadata=_metadata,
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
        async with get_session_context() as session:
            from services.image_submission import submit_image_job

            img_job = await submit_image_job(
                session,
                prompt=prompt,
                checkpoint=preferred_checkpoint,
                filename_prefix="ComfyUI",
                source="story_illustrate",
                workspace="story",
                story_id=story_id,
                chapter_id=chapter_id,
            )
            logger.info("illustrate_image_job_queued", job_id=img_job.id, story_id=story_id)
    except Exception as e:
        logger.error("illustrate_chain_failed", job_id=job_data.get("id"), error=str(e), exc_info=True)


async def _handle_scene_prompt(job_data: dict[str, Any]):
    """Chain a chat scene prompt into an image job (non-agentic fallback path)."""

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
        async with get_session_context() as session:
            from core.workflow_builder import DEFAULT_NEGATIVE_PROMPT
            from services.image_submission import submit_image_job

            img_job = await submit_image_job(
                session,
                prompt=prompt,
                negative_prompt=DEFAULT_NEGATIVE_PROMPT,
                checkpoint=preferred_checkpoint,
                filename_prefix="ComfyUI",
                source="scene_illustrate",
                workspace="chat",
                chat_id=chat_id,
                character_id=character_id,
            )
            logger.info("scene_image_job_queued", job_id=img_job.id, chat_id=chat_id)
    except Exception as e:
        logger.error("scene_chain_failed", job_id=job_data.get("id"), error=str(e), exc_info=True)


async def _handle_narrator(job_data: dict[str, Any]):
    chat_id = job_data.get("metadata", {}).get("chat_id")
    content = _first_text(job_data)
    if not chat_id or not content:
        return

    async with get_session_context() as session:
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

    async with get_session_context() as session:
        try:
            metadata = job_data.get("metadata", {}) or {}
            msg_metadata = {"agentic": bool(tool_calls)}
            if "orchestrator_depth" in metadata:
                msg_metadata["orchestrator_depth"] = metadata["orchestrator_depth"]

            if metadata.get("is_swipe") and metadata.get("target_message_id"):
                # Append as alternate to existing message
                target_msg = session.get(Message, metadata["target_message_id"])
                if target_msg:
                    target_meta = dict(target_msg.message_metadata or {})
                    alternates = target_meta.get("alternates", [target_msg.content])
                    if target_msg.content not in alternates:
                        alternates.insert(0, target_msg.content)
                    
                    alternates.append(content)
                    active_index = len(alternates) - 1
                    
                    target_msg.content = content
                    target_msg.tool_calls = tool_calls
                    target_meta.update(msg_metadata)
                    target_meta.update({"alternates": alternates, "active_index": active_index})
                    target_msg.message_metadata = target_meta
                    session.add(target_msg)
                    session.commit()
                    return

            # Normal path: insert NEW CHAR message
            msg = Message(
                role=MessageRole.CHAR,
                kind=MessageKind.CHAR,
                content=content,
                chat_id=chat_id,
                tool_calls=tool_calls,
                message_metadata=msg_metadata,
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

    async with get_session_context() as session:
        try:
            chapter = session.get(StoryChapter, chapter_id)
            if chapter:
                if not chapter.beats or not all(isinstance(b, dict) and b.get("id") for b in chapter.beats):
                    chapter.beats = [
                        ({**b, "id": str(uuid4()), "parent_beat_id": None}
                         if isinstance(b, dict) and not b.get("id") else b)
                        for b in (chapter.beats or [])
                    ]
                beat = {
                    "id": str(uuid4()),
                    "parent_beat_id": (chapter.beats[-1].get("id") if chapter.beats else None),
                    "role": StoryBeatRole.NARRATOR.value,
                    "content": content,
                }
                chapter.beats.append(beat)
                chapter.content += f"\n\n{content}\n\n"
                session.add(chapter)
                session.commit()
        except Exception as e:
            session.rollback()
            logger.warning("story_continue_failed", job_id=job_data.get("id"), error=str(e))


async def _handle_chat_tts(job_data: dict[str, Any]):
    outputs = job_data.get("outputs", [])
    chat_id = job_data.get("metadata", {}).get("chat_id")
    message_id = job_data.get("metadata", {}).get("message_id")
    audio_path = (
        outputs[0].get("relative_path") if outputs and isinstance(outputs[0], dict) else None
    ) or job_data.get("image_path")
    
    if not chat_id or not message_id or not audio_path:
        return
        
    async with get_session_context() as session:
        try:
            msg = session.get(Message, message_id)
            if msg and msg.chat_id == chat_id:
                meta = dict(msg.message_metadata or {})
                meta["audio_path"] = audio_path
                msg.message_metadata = meta
                session.add(msg)
                session.commit()
        except Exception as e:
            session.rollback()
            logger.warning("chat_tts_msg_failed", job_id=job_data.get("id"), error=str(e))


async def _handle_story_tts(job_data: dict[str, Any]):
    """Store the audio path from a story chapter TTS job into the chapter's beats metadata."""
    from core.entities import StoryChapter

    outputs = job_data.get("outputs", [])
    story_id = job_data.get("metadata", {}).get("story_id")
    chapter_id = job_data.get("metadata", {}).get("chapter_id")
    audio_path = (
        outputs[0].get("relative_path") if outputs and isinstance(outputs[0], dict) else None
    ) or job_data.get("image_path")

    if not story_id or not chapter_id or not audio_path:
        return

    async with get_session_context() as session:
        try:
            chapter = session.get(StoryChapter, chapter_id)
            if chapter and chapter.story_id == story_id:
                # Append audio_path to the chapter's metadata or create a beat entry
                meta = dict(chapter.beats[-1]) if chapter.beats else {}
                if meta.get("role") == "system_tts":
                    meta["audio_path"] = audio_path
                else:
                    meta = {
                        "id": str(uuid4()),
                        "parent_beat_id": (chapter.beats[-1].get("id") if chapter.beats else None),
                        "role": "system_tts",
                        "content": "",
                        "audio_path": audio_path,
                    }
                    chapter.beats.append(meta)
                session.add(chapter)
                session.commit()
        except Exception as e:
            session.rollback()
            logger.warning("story_tts_chapter_failed", job_id=job_data.get("id"), error=str(e))

async def _handle_chat_image(job_data: dict[str, Any]):
    outputs = job_data.get("outputs", [])
    chat_id = job_data.get("metadata", {}).get("chat_id")
    image_path = (
        outputs[0].get("relative_path") if outputs and isinstance(outputs[0], dict) else None
    ) or job_data.get("image_path")
    metadata = job_data.get("metadata", {})
    if not chat_id or not image_path:
        return

    async with get_session_context() as session:
        if metadata.get("source") == "agentic_tool":
            tool_name = metadata.get("tool_name", "generate_image")
            content = f"[Image generated by {tool_name}]"
        elif metadata.get("source") in ("scene_illustrate", "chat_image"):
            content = "[Scene illustration]"
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

    async with get_session_context() as session:
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


async def _handle_story_parse(job_data: dict[str, Any]):
    text = _first_text(job_data)
    story_id = job_data.get("metadata", {}).get("story_id")
    if not text or not story_id:
        return

    parsed = None
    try:
        import json
        parsed = json.loads(text)
    except Exception:
        logger.warning("story_parse_invalid_json", job_id=job_data.get("id"))
        return
    if not isinstance(parsed, dict):
        return

    async with get_session_context() as session:
        try:
            story = session.get(Story, story_id)
            if not story:
                return

            new_character_ids: list[str] = []

            for char_data in (parsed.get("characters") or []):
                if not char_data.get("name"):
                    continue
                character = Character(
                    name=char_data.get("name", ""),
                    description=char_data.get("description"),
                    personality=char_data.get("personality"),
                )
                session.add(character)
                session.commit()
                session.refresh(character)
                new_character_ids.append(character.id)

            new_lorebook_ids: list[str] = []
            new_location_ids: list[str] = []

            for loc_data in (parsed.get("locations") or []):
                if not loc_data.get("name"):
                    continue
                location = Location(
                    name=loc_data.get("name", ""),
                    description=loc_data.get("description"),
                    atmosphere=loc_data.get("atmosphere"),
                    tags=loc_data.get("tags", []),
                )
                session.add(location)
                session.commit()
                session.refresh(location)
                new_location_ids.append(location.id)
                # Also create a Lorebook entry so the location's description
                # is available in chat/story context via the lorebook pipeline.
                lorebook = Lorebook(
                    name=loc_data.get("name", ""),
                    description=loc_data.get("description"),
                )
                session.add(lorebook)
                session.commit()
                session.refresh(lorebook)
                entry = LorebookEntry(
                    lorebook_id=lorebook.id,
                    content=loc_data.get("description", ""),
                    keys=[loc_data.get("name", "")],
                )
                session.add(entry)
                new_lorebook_ids.append(lorebook.id)

            for lore_data in (parsed.get("lorebooks") or []):
                if not lore_data.get("name"):
                    continue
                lorebook = Lorebook(
                    name=lore_data.get("name", ""),
                    description=lore_data.get("description"),
                )
                session.add(lorebook)
                session.commit()
                session.refresh(lorebook)
                entry = LorebookEntry(
                    lorebook_id=lorebook.id,
                    content=lore_data.get("description", ""),
                    keys=[lore_data.get("name", "")],
                )
                session.add(entry)
                new_lorebook_ids.append(lorebook.id)

            # Link created entities to the story
            if new_character_ids or new_lorebook_ids:
                existing_chars = set(story.character_ids or [])
                existing_lore = set(story.lorebook_ids or [])
                story.character_ids = list(existing_chars | set(new_character_ids))
                story.lorebook_ids = list(existing_lore | set(new_lorebook_ids))
                session.add(story)
                session.commit()

            logger.info(
                "story_parse_entities_created",
                job_id=job_data.get("id"),
                story_id=story_id,
                characters=new_character_ids,
                lorebooks=new_lorebook_ids,
            )
        except Exception as e:
            session.rollback()
            logger.warning("story_parse_failed", job_id=job_data.get("id"), error=str(e))


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
            elif event_type == "chat_tts":
                await _handle_chat_tts(job_data)
            elif event_type == "story_tts":
                await _handle_story_tts(job_data)
            elif event_type == "story_image":
                await _handle_story_image(job_data)
            elif event_type == "story_parse":
                await _handle_story_parse(job_data)
        except Exception as exc:
            logger.error("world_integration_event_processing_failed", error=str(exc))
