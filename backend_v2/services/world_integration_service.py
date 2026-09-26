from datetime import datetime, timezone
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
from infrastructure.deps import get_session_context
from infrastructure.logging import get_logger
from sqlmodel import select
from services.context_builder import build_chat_context_async
from services.job_queue import queue_manager
from services.job_service import JobService
from services.llm_config import get_default_llm_model

logger = get_logger("world_integration")

from services.chat_utils import extract_first_text as _first_text
from services.chat_utils import resolve_context_tokens as _resolve_context_tokens

# Queue depth for the single world-integration consumer. Sized for a large
# burst (60-image batch + the LLM replies it triggers) with margin, because the
# consumer is the only writer of chat replies and an evicted JOB_COMPLETED is a
# paid generation that nothing downstream can reconstruct. See
# start_world_integration_service for the failure mode this avoids.
WORLD_INTEGRATION_QUEUE_SIZE = 10_000

# Marks a Message as the persisted output of a specific completed job, so a lost
# JOB_COMPLETED event becomes detectable instead of permanent. Set by
# _handle_chat_reply on both the append and the swipe-alternate path.
SOURCE_JOB_ID_METADATA_KEY = "source_job_id"


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
                    .limit(200)
                ).all()
                from services.context_builder import chat_context_kwargs

                _sp, _ctx = await build_chat_context_async(
                    _past,
                    **chat_context_kwargs(
                        _chat,
                        characters=[_character] if _character else None,
                        max_context_tokens=_resolve_context_tokens(_chat),
                    ),
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
            job_id = job_data.get("id")
            metadata = job_data.get("metadata", {}) or {}
            msg_metadata = {"agentic": bool(tool_calls)}
            if "orchestrator_depth" in metadata:
                msg_metadata["orchestrator_depth"] = metadata["orchestrator_depth"]
            if job_id:
                # The link that makes a dropped JOB_COMPLETED recoverable:
                # find_unpersisted_chat_replies() looks for COMPLETED chat_reply
                # jobs with no message carrying this stamp.
                msg_metadata[SOURCE_JOB_ID_METADATA_KEY] = job_id

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
                character_id=metadata.get("character_id"),
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
                # Append audio_path to the last beat, or create a TTS beat entry.
                # MutableList does NOT track in-place mutation of its dict members,
                # so the beats list must be rebuilt (reassigned) to persist.
                beats = list(chapter.beats or [])
                if beats and isinstance(beats[-1], dict) and beats[-1].get("role") == "system_tts":
                    beats[-1] = {**beats[-1], "audio_path": audio_path}
                else:
                    beats.append(
                        {
                            "id": str(uuid4()),
                            "parent_beat_id": (beats[-1].get("id") if beats and isinstance(beats[-1], dict) else None),
                            "role": "system_tts",
                            "content": "",
                            "audio_path": audio_path,
                        }
                    )
                chapter.beats = beats
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
    except Exception as exc:
        logger.warning("story_parse_invalid_json", job_id=job_data.get("id"), error=str(exc))
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
                new_location_ids.append(location.id)
                # Also create a Lorebook entry so the location's description
                # is available in chat/story context via the lorebook pipeline.
                lorebook = Lorebook(
                    name=loc_data.get("name", ""),
                    description=loc_data.get("description"),
                )
                session.add(lorebook)
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
                entry = LorebookEntry(
                    lorebook_id=lorebook.id,
                    content=lore_data.get("description", ""),
                    keys=[lore_data.get("name", "")],
                )
                session.add(entry)
                new_lorebook_ids.append(lorebook.id)

            # One flush for every entity, then ONE commit.
            #
            # This used to commit (and refresh) once per created entity. Every
            # one of those is a blocking round trip on the event loop, inside
            # the single consumer that is the only writer of chat replies — so a
            # story_parse with 20 locations (each creating a Lorebook + entry
            # too) head-of-line-blocked every other handler for the duration. A
            # batch is also the correct unit of work: either the whole parse
            # lands or none of it does, rather than a half-linked story.
            session.flush()

            # Link created entities to the story
            if new_character_ids or new_lorebook_ids or new_location_ids:
                existing_chars = set(story.character_ids or [])
                existing_lore = set(story.lorebook_ids or [])
                existing_locations = set(story.location_ids or [])
                story.character_ids = list(existing_chars | set(new_character_ids))
                story.lorebook_ids = list(existing_lore | set(new_lorebook_ids))
                story.location_ids = list(existing_locations | set(new_location_ids))
                session.add(story)

            session.commit()

            logger.info(
                "story_parse_entities_created",
                job_id=job_data.get("id"),
                story_id=story_id,
                characters=new_character_ids,
                lorebooks=new_lorebook_ids,
                locations=new_location_ids,
            )
        except Exception as e:
            session.rollback()
            logger.warning("story_parse_failed", job_id=job_data.get("id"), error=str(e))


async def _handle_voice_preview(job_data: dict[str, Any]):
    """Store the synthesized preview audio path on the voice model row."""
    from core.entities import VoiceModel

    outputs = job_data.get("outputs", [])
    voice_id = job_data.get("metadata", {}).get("voice_id")
    audio_path = (
        outputs[0].get("relative_path") if outputs and isinstance(outputs[0], dict) else None
    ) or job_data.get("image_path")

    if not voice_id or not audio_path:
        return

    async with get_session_context() as session:
        try:
            voice = session.get(VoiceModel, voice_id)
            if voice:
                voice.preview_path = audio_path
                voice.updated_at = datetime.now(timezone.utc)
                session.add(voice)
                session.commit()
        except Exception as e:
            session.rollback()
            logger.warning("voice_preview_failed", job_id=job_data.get("id"), error=str(e))


async def start_world_integration_service():
    """Start listening to EventBus for world vault events."""
    logger.info("starting_world_integration_service")

    # This consumer is the ONLY thing that turns a paid LLM response into a
    # `messages` row, so its queue must never be the weak link. It used to
    # subscribe at the EventBus default of 100; every handler does synchronous
    # session.exec/commit inline on the event loop, and `_handle_story_parse`
    # used to commit once per created entity, so a burst — a 60-image batch is
    # 60 JOB_COMPLETED events — could push the consumer past 100 behind. On
    # overflow the bus keeps the newest terminal event by EVICTING the oldest,
    # and if that was a chat_reply the generated text was paid for, marked
    # COMPLETED in the DB, and never written anywhere.
    #
    # 10_000 is roughly a 60-image batch with a large margin, at ~200 bytes per
    # queued Event, i.e. ~2 MB for this one consumer. Buffering cannot fix a
    # permanently stuck consumer, so the eviction is also logged at ERROR with
    # the job id (see EventBus._record_drop) and
    # find_unpersisted_chat_replies() can re-drive what was lost.
    async for event in event_bus.subscribe(
        EventType.JOB_COMPLETED.value.split(".")[0],
        max_queue_size=WORLD_INTEGRATION_QUEUE_SIZE,
    ):
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
            elif event_type == "voice_preview":
                await _handle_voice_preview(job_data)
            elif event_type == "story_tts":
                await _handle_story_tts(job_data)
            elif event_type == "story_image":
                await _handle_story_image(job_data)
            elif event_type == "story_parse":
                await _handle_story_parse(job_data)
            elif event_type == "character_avatar_animate":
                await _handle_avatar_animate(job_data)
        except Exception as exc:
            logger.error("world_integration_event_processing_failed", error=str(exc))

async def _handle_avatar_animate(job_data: dict[str, Any]):
    """Update a character's avatar path with the generated AnimateDiff video."""
    import shutil
    import os
    from infrastructure.deps import get_session_context
    from config import settings
    from core.entities import Character
    
    metadata = job_data.get("metadata", {})
    character_id = metadata.get("character_id")
    if not character_id:
        return
        
    video_path = (
        job_data.get("result_paths", [None])[0]
        or (job_data.get("outputs") or [{}])[0].get("relative_path")
        or (job_data.get("outputs") or [{}])[0].get("filename")
        or job_data.get("image_path")
    )
    if not video_path:
        return
    if not os.path.isabs(video_path):
        video_path = os.path.join(settings.output_dir, video_path)
    if not os.path.exists(video_path):
        return
        
    async with get_session_context() as session:
        character = session.get(Character, character_id)
        if not character:
            return
            
        avatar_dir = f"{settings.character_avatar_dir}/{character_id}"
        os.makedirs(avatar_dir, exist_ok=True)
        # Using .webp because our VHS_VideoCombine format is video/webp which works natively in <img> tags
        new_avatar_path = f"{avatar_dir}/avatar.webp"
        
        shutil.copy2(video_path, new_avatar_path)
        character.avatar_path = new_avatar_path
        session.add(character)
        session.commit()


# ---------------------------------------------------------------------------
# Lost-reply reconciliation
# ---------------------------------------------------------------------------
#
# The single consumer above is the only writer of chat replies, and its input is
# a lossy queue. When a JOB_COMPLETED is evicted under backpressure the text is
# gone: the job is COMPLETED in the DB, the user paid for it, and the chat never
# advances. Buffering (WORLD_INTEGRATION_QUEUE_SIZE) and the ERROR log on drop
# make that rare and visible; these two functions make it recoverable.
#
# Detection works because _handle_chat_reply stamps
# `message_metadata["source_job_id"]` on the message it writes. A COMPLETED
# chat_reply job with no message carrying that stamp is a lost reply.

# Job types whose completed output becomes a Message row.
_RECONCILABLE_WORKFLOW_TYPES = ("chat_reply",)

# How far back the reconciler looks. Chats are read newest-first and only the
# tail can still be showing a hole, so a bounded window is both cheaper and less
# likely to re-drive a reply the user has since deleted on purpose.
RECONCILE_LOOKBACK_LIMIT = 500


def find_unpersisted_chat_replies(
    session,
    *,
    limit: int = RECONCILE_LOOKBACK_LIMIT,
) -> list[dict[str, Any]]:
    """Find COMPLETED chat_reply jobs whose reply was never written to `messages`.

    Returns job payloads shaped like a JOB_COMPLETED event's ``job`` dict, so
    the caller can hand them straight back to :func:`_handle_chat_reply`. An
    empty list means nothing is missing.

    Only the newest ``limit`` chat_reply jobs are examined — a hole older than
    the current conversation window is not worth risking a duplicate insert for.
    """
    from core.entities import Job, JobStatus

    jobs = session.exec(
        select(Job)
        .where(
            Job.status == JobStatus.COMPLETED,
            Job.task_type == "llm",
        )
        .order_by(Job.created_at.desc())
        .limit(max(1, limit) * 4)  # over-fetch: most of these are not chat replies
    ).all()

    candidates: list[tuple[Any, dict[str, Any]]] = []
    for job in jobs:
        metadata = job.metadata_ if isinstance(job.metadata_, dict) else {}
        workflow = job.workflow if isinstance(job.workflow, dict) else {}
        if (metadata.get("type") or workflow.get("type")) not in _RECONCILABLE_WORKFLOW_TYPES:
            continue
        if not (metadata.get("chat_id") or workflow.get("chat_id")):
            continue
        candidates.append((job, metadata))
        if len(candidates) >= max(1, limit):
            break

    if not candidates:
        return []

    job_ids = [job.id for job, _ in candidates]
    stamped: set[str] = set()
    rows = session.exec(
        select(Message).where(
            Message.chat_id.in_(
                {
                    (metadata.get("chat_id") or (job.workflow or {}).get("chat_id"))
                    for job, metadata in candidates
                }
            )
        )
    ).all()
    for msg in rows:
        msg_meta = msg.message_metadata if isinstance(msg.message_metadata, dict) else {}
        for value in (msg_meta.get(SOURCE_JOB_ID_METADATA_KEY), *_alternate_source_job_ids(msg_meta)):
            if value in job_ids:
                stamped.add(value)

    return [
        {
            "id": job.id,
            "outputs": job.outputs or [],
            "metadata": metadata,
            "workflow": job.workflow or {},
            "type": "chat_reply",
        }
        for job, metadata in candidates
        if job.id not in stamped
    ]


def _alternate_source_job_ids(msg_metadata: dict) -> list[str]:
    """Source job ids stamped onto a swipe's alternates.

    A swipe writes its text into an existing message's ``alternates`` list, and
    that message may already carry another job's stamp. Every stamped id counts
    as persisted, otherwise a re-driven swipe would duplicate an alternate.
    """
    out: list[str] = []
    for entry in msg_metadata.get("alternates") or []:
        if isinstance(entry, dict):
            value = entry.get(SOURCE_JOB_ID_METADATA_KEY)
            if value:
                out.append(value)
    return out


async def reconcile_unpersisted_chat_replies(session=None, *, limit: int = RECONCILE_LOOKBACK_LIMIT) -> dict[str, Any]:
    """Re-drive chat replies that were generated but never persisted.

    Detection and repair in one call: every lost reply found is replayed through
    the normal :func:`_handle_chat_reply` path, so the write is identical to the
    one the event handler would have made (including the swipe-alternate branch).
    Idempotent: a reply that is already persisted is not found, so a second call
    does nothing.

    ``session`` is accepted so tests and callers can pass their own; the handler
    opens its own session for the write, because a session shared with the
    detection read would be committing from two places.
    """
    if session is None:
        from infrastructure.deps import get_session_context

        async with get_session_context() as detect_session:
            found = find_unpersisted_chat_replies(detect_session, limit=limit)
    else:
        found = find_unpersisted_chat_replies(session, limit=limit)

    repaired: list[str] = []
    failed: list[str] = []
    for job_data in found:
        try:
            await _handle_chat_reply(job_data)
            repaired.append(job_data["id"])
        except Exception as exc:  # pragma: no cover - handler swallows its own errors
            logger.error(
                "chat_reply_reconcile_failed", job_id=job_data.get("id"), error=str(exc)
            )
            failed.append(job_data["id"])

    if found:
        logger.warning(
            "chat_reply_reconcile_complete",
            found=len(found),
            repaired=len(repaired),
            failed=len(failed),
        )
    return {"found": len(found), "repaired": repaired, "failed": failed}
