import asyncio
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
from sqlmodel import Session, select
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

# The beat role `_handle_story_tts` writes when a completed TTS job is filed
# against its chapter: an audio attachment, not prose — empty `content`, an
# `audio_path` beside it.
#
# Declared here, beside its only writer, because the service is the lower layer:
# `api/routes/world_vault/stories.py` imports it to widen the set of roles the
# beat routes accept, which is the direction this codebase already imports in
# (routes import services). It was the literal `"system_tts"`, which was in no
# allowed set at all — the beat routes refused to edit such a beat, and
# "retry last continuation" refused to retry anything after it because the
# trailing beat was not a narrator turn.
TTS_BEAT_ROLE = "tts"


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
                # Newest 200, not the oldest 200. `.order_by(created_at)` with a
                # limit takes the FIRST 200, so past a 200-message chat the
                # impersonation was generated from the opening of the
                # conversation and asked to continue a scene the user had long
                # since left. Every other reply path in the codebase takes the
                # newest (limit, then reverse) — `chats.py` does it four times.
                _past = list(session.exec(
                    select(Message)
                    .where(Message.chat_id == imp_chat_id)
                    .order_by(Message.created_at.desc())
                    .limit(200)
                ).all())
                _past.reverse()
                from services.context_builder import chat_context_kwargs

                _sp, _ctx = await build_chat_context_async(
                    _past,
                    **chat_context_kwargs(
                        _chat,
                        characters=[_character] if _character else None,
                        # Without `session` the persona library is not resolved,
                        # so an impersonated reply was the one reply path that
                        # dropped the user's persona and their World's lorebooks.
                        session=session,
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
                source="scene_illustrate",
                workspace="chat",
                chat_id=chat_id,
                character_id=character_id,
            )
            logger.info("scene_image_job_queued", job_id=img_job.id, chat_id=chat_id)
    except Exception as e:
        logger.error("scene_chain_failed", job_id=job_data.get("id"), error=str(e), exc_info=True)


async def _handle_narrator(job_data: dict[str, Any]):
    """Persist one narrator message.

    The single writer of narrator messages. The agentic `narrate_scene` tool
    used to insert inline *and* emit `type: "narrator"`, so the same paragraph
    landed twice; the button path came through here alone. Both now do.
    """
    metadata = job_data.get("metadata") or {}
    chat_id = metadata.get("chat_id") or job_data.get("chat_id")
    content = _first_text(job_data)
    if not chat_id or not content:
        return

    message_metadata: dict[str, Any] = {"source": "narrator"}
    if metadata.get("narration_job_id"):
        message_metadata["narration_job_id"] = metadata["narration_job_id"]

    async with get_session_context() as session:
        try:
            msg = Message(
                role=MessageRole.SYSTEM,
                kind=MessageKind.NARRATOR,
                content=content,
                chat_id=chat_id,
                # The thread the narrated message lives on. Branch copies share
                # their originals' `chat_id` and `created_at`, so a narrator row
                # written without it interleaves into the original thread and the
                # fork the user is reading never shows its own narration.
                branch_id=metadata.get("branch_id"),
                message_metadata=message_metadata,
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
                if target_msg and target_msg.chat_id != chat_id:
                    # The id exists but belongs to a different chat. Swiping a
                    # message in one conversation from another is never intended,
                    # and writing to it would move text across chats.
                    logger.warning(
                        "chat_swipe_target_wrong_chat",
                        job_id=job_data.get("id"),
                        chat_id=chat_id,
                        target_chat_id=target_msg.chat_id,
                    )
                    return
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
                # The target is gone (deleted, or rolled back) while this job was
                # in flight. Appending a fresh CHAR message at the tail would be
                # wrong in two reachable ways: the user regenerates or deletes the
                # message they asked to swipe, the in-flight job lands afterwards
                # and re-inserts the text they discarded; and
                # `POST /api/jobs/reconcile-chat-replies` replays every COMPLETED
                # chat_reply with no source stamp, so every reply that was ever
                # regenerated or rolled back — the ones whose stamped message was
                # deleted — would be reported as a lost reply and resurrected at
                # the end of the chat.

                # A swipe has no meaning without its anchor, so this is a no-op
                # rather than a fallback. The job still completes normally, so the
                # cost is already sunk either way; what matters is that it does
                # not mutate the conversation.
                logger.warning(
                    "chat_swipe_target_missing",
                    job_id=job_data.get("id"),
                    chat_id=chat_id,
                    target_message_id=metadata.get("target_message_id"),
                )
                return

            # Normal path: insert NEW CHAR message
            msg = Message(
                role=MessageRole.CHAR,
                kind=MessageKind.CHAR,
                content=content,
                chat_id=chat_id,
                # The thread the question was asked on, carried on the job
                # metadata by the send/regenerate routes. A branch's copies share
                # their originals' `chat_id` and `created_at`, so an answer written
                # without it interleaves into the original thread and the fork the
                # user is reading never advances.
                branch_id=metadata.get("branch_id"),
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


def _output_paths(job_data: dict[str, Any]) -> list[str]:
    """Every usable path a completed job produced, in output order.

    This expression was written out five times in this file, once per handler,
    and every copy read `outputs[0]` only. That is not a cosmetic duplication:
    `job_processing` reconciles ALL of a batch's outputs into the `assets` table
    (`job_processing.py:264-289`), so a four-image chat job put four images in
    the gallery and attached exactly ONE `Message(..., image_path=...)` to the
    chat. Three of the four silently vanished from the conversation.
    """
    paths: list[str] = []
    for output in job_data.get("outputs") or []:
        if not isinstance(output, dict):
            continue
        path = output.get("relative_path") or output.get("filename")
        if path and path not in paths:
            paths.append(path)
    fallback = job_data.get("image_path")
    if not paths and fallback:
        paths.append(fallback)
    return paths


def _first_output_path(job_data: dict[str, Any]) -> str | None:
    """The first usable path, for the single-output handlers (TTS, previews).

    Deliberately not a general answer: a voice clip and a story illustration are
    one file each, and taking `[0]` there is correct. It is only the *image*
    handlers that need all of them.
    """
    paths = _output_paths(job_data)
    return paths[0] if paths else None


async def _handle_chat_tts(job_data: dict[str, Any]):
    chat_id = job_data.get("metadata", {}).get("chat_id")
    message_id = job_data.get("metadata", {}).get("message_id")
    audio_path = _first_output_path(job_data)
    
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

    story_id = job_data.get("metadata", {}).get("story_id")
    chapter_id = job_data.get("metadata", {}).get("chapter_id")
    audio_path = _first_output_path(job_data)

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
                if beats and isinstance(beats[-1], dict) and beats[-1].get("role") == TTS_BEAT_ROLE:
                    beats[-1] = {**beats[-1], "audio_path": audio_path}
                else:
                    beats.append(
                        {
                            "id": str(uuid4()),
                            "parent_beat_id": (beats[-1].get("id") if beats and isinstance(beats[-1], dict) else None),
                            "role": TTS_BEAT_ROLE,
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
    image_paths = _output_paths(job_data)
    chat_id = job_data.get("metadata", {}).get("chat_id")
    metadata = job_data.get("metadata", {})
    if not chat_id or not image_paths:
        return

    async with get_session_context() as session:
        if metadata.get("source") == "agentic_tool":
            tool_name = metadata.get("tool_name", "generate_image")
            content = f"[Image generated by {tool_name}]"
        elif metadata.get("source") in ("scene_illustrate", "chat_image"):
            content = "[Scene illustration]"
        else:
            content = metadata.get("image_context", "Generated Image:")
        
        # One message per output. This was `image_path = outputs[0]...`, so a
        # batch that produced four images attached one and dropped three, even
        # though all four were already in the `assets` table and visible in the
        # gallery — the conversation was the only place they went missing.
        for path in image_paths:
            try:
                msg = Message(
                    role=MessageRole.SYSTEM,
                    kind=MessageKind.IMAGE,
                    content=content,
                    image_path=path,
                    chat_id=chat_id,
                )
                session.add(msg)
                session.commit()
            except Exception as e:
                session.rollback()
                logger.warning(
                    "chat_image_msg_failed",
                    job_id=job_data.get("id"),
                    image_path=path,
                    error=str(e),
                )

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
                    for path in image_paths:
                        existing = session.exec(
                            select(CollectionImage).where(
                                CollectionImage.collection_id == collection.id,
                                CollectionImage.image_filename == path,
                            )
                        ).first()
                        if not existing:
                            session.add(CollectionImage(
                                collection_id=collection.id,
                                image_filename=path,
                            ))
                    session.commit()
        except Exception as e:
            session.rollback()
            logger.warning("chat_image_collection_failed", job_id=job_data.get("id"), error=str(e))


async def _handle_story_image(job_data: dict[str, Any]):
    image_paths = _output_paths(job_data)
    chapter_id = job_data.get("metadata", {}).get("chapter_id")
    if not chapter_id or not image_paths:
        return

    async with get_session_context() as session:
        try:
            chapter = session.get(StoryChapter, chapter_id)
            if chapter:
                # All of them, appended in order. `image_paths` is already a list
                # on the chapter, so this is the same shape as the single-image
                # case — it just no longer stops after the first.
                existing = list(chapter.image_paths or [])
                added = [path for path in image_paths if path not in existing]
                if added:
                    chapter.image_paths = existing + added
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

    voice_id = job_data.get("metadata", {}).get("voice_id")
    audio_path = _first_output_path(job_data)

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

def _install_avatar(video_path: str, avatar_dir: str) -> str:
    """Copy the rendered video into the character's avatar slot. BLOCKING.

    `os.path.isabs`, `os.path.exists`, `os.makedirs` and `shutil.copy2` are all
    blocking filesystem calls, and a rendered avatar is a multi-megabyte file on
    a possibly cold mount. Run in a worker thread: this function is reached from
    the single JOB_COMPLETED consumer whose own docstring says it must never
    head-of-line block, because an evicted completed job is a paid generation
    nothing can reconstruct.
    """
    import os
    import shutil

    if not os.path.isabs(video_path):
        from config import settings

        video_path = os.path.join(settings.output_dir, video_path)
    if not os.path.exists(video_path):
        return ""

    os.makedirs(avatar_dir, exist_ok=True)
    # Using .webp because our VHS_VideoCombine format is video/webp which works natively in <img> tags
    new_avatar_path = f"{avatar_dir}/avatar.webp"
    shutil.copy2(video_path, new_avatar_path)
    return new_avatar_path


async def _handle_avatar_animate(job_data: dict[str, Any]):
    """Update a character's avatar path with the generated AnimateDiff video."""
    from config import settings
    from core.entities import Character

    from infrastructure.deps import get_session_context

    metadata = job_data.get("metadata", {})
    character_id = metadata.get("character_id")
    if not character_id:
        return

    # `result_paths` was read here and written nowhere in the repository, so that
    # branch could only ever yield `None` — and it would have raised IndexError
    # into the blanket handler above if ever present-but-empty. A rendered video
    # is one file, so the first usable output is the whole answer.
    video_path = _first_output_path(job_data)
    if not video_path:
        return

    avatar_dir = f"{settings.character_avatar_dir}/{character_id}"
    new_avatar_path = await asyncio.to_thread(_install_avatar, video_path, avatar_dir)
    if not new_avatar_path:
        return

    async with get_session_context() as session:
        character = session.get(Character, character_id)
        if not character:
            return
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
    # Narrow select, and a narrower question.
    #
    # This loaded EVERY `Message` row for the affected chats — no `LIMIT`, no
    # column narrowing, `content` TEXT included — solely to test one key of
    # `message_metadata` against a set of at most `limit` job ids. On a
    # 5,000-message chat that is 5,000 full rows into memory on every
    # reconciliation tick, to answer "which of these few jobs has already been
    # stamped onto a message". The content is never read here; the whole row was
    # loaded and then two fields were picked off it in Python.
    stamped = _stamped_source_job_ids(session, candidates, job_ids)
    if not stamped:
        return [
            {
                "id": job.id,
                "outputs": job.outputs or [],
                "metadata": metadata,
                "workflow": job.workflow or {},
                "type": "chat_reply",
            }
            for job, metadata in candidates
        ]

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


def _stamped_source_job_ids(
    session: Session, candidates: list[tuple[Any, dict[str, Any]]], job_ids: list[str]
) -> set[str]:
    """Which of `job_ids` already appear as a `source_job_id` on a message.

    Two narrow queries instead of one unbounded full-row load. The flat
    `source_job_id` is a scalar in `message_metadata`, so it can be compared and
    indexed in SQL. A swipe's `alternates` is a LIST of objects nested inside the
    same jsonb, which no plain column comparison can reach — so that half selects
    the one jsonb column, with the same chat and job filters applied, and matches
    in Python. Both queries carry `chat_id IN (...) AND ... IN (job_ids)`, so
    neither walks a chat.
    """
    chat_ids = {
        (metadata.get("chat_id") or (job.workflow or {}).get("chat_id"))
        for job, metadata in candidates
    }
    chat_ids.discard(None)
    if not chat_ids:
        return set()

    wanted = set(job_ids)
    stamped: set[str] = set()

    flat = Message.message_metadata[SOURCE_JOB_ID_METADATA_KEY].as_string()
    for value in session.exec(
        select(flat).where(Message.chat_id.in_(chat_ids), flat.in_(list(wanted)))
    ).all():
        if value in wanted:
            stamped.add(value)

    for alternates in session.exec(
        select(Message.message_metadata["alternates"]).where(
            Message.chat_id.in_(chat_ids),
            Message.message_metadata["alternates"].is_not(None),
        )
    ).all():
        if not isinstance(alternates, list):
            continue
        for value in _alternate_source_job_ids({"alternates": alternates}):
            if value in wanted:
                stamped.add(value)

    return stamped


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
