import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from core.sql_search import LIKE_ESCAPE_CHAR, like_contains
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

logger = get_logger("world_integration")

from services.chat_utils import extract_first_text as _first_text
from services.chat_utils import extract_persistable_text as _persistable_text
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

# A second stamp key, for the TTS handlers.
#
# It cannot reuse `source_job_id`. `_handle_chat_tts` mutates a message that
# ALREADY carries the reply job's stamp, and overwriting it would make that
# message look unwritten for its own reply — so the reconciler would resurrect
# the reply at the tail of the chat, on every sweep, forever. The price is one
# more key to look for, which is cheaper than the failure.
#
# A separate key is also what makes a TTS artefact FINDABLE at all. These were
# excluded from reconciliation with the reasoning "it mutates rather than
# inserts, so there is no row to find" — which was true only because nothing was
# stamped. A lost JOB_COMPLETED was a paid synthesis whose audio_path was never
# written to the message that asked for it.
TTS_SOURCE_JOB_ID_METADATA_KEY = "tts_source_job_id"

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


async def _handle_impersonation(job_data: dict[str, Any], session: Any = None):
    """Write the model's impersonation of the user, then chain a reply.

    `session` is the caller's when this runs before the job goes COMPLETED, and
    None for the event bus consumer.

    Idempotent, and this is the one chaining handler that has to be. It inserts a
    USER message stamped with its own job id and then enqueues a `chat_reply`
    from it — so a second delivery would write the same line twice AND spend a
    second reply on top of it. That asymmetry is why impersonation was left out
    of reconciliation entirely: a replay was a duplicate generator, so the safe
    choice was to make the turn type unrecoverable.

    The guard inverts that tradeoff. The stamp is already there; reading it means
    a replay writes nothing and chains nothing, which makes impersonation the
    only recoverable chaining handler in the table.
    """
    imp_chat_id = job_data.get("metadata", {}).get("chat_id")
    imp_text = _first_text(job_data)
    if not imp_chat_id or not imp_text:
        return

    async with _session_for(job_data, session) as session:
        try:
            # Before the insert, not after: the chained job is spent on the way
            # past, so a check placed after it would save the row and lose the
            # guard's whole point.
            if _impersonation_already_stamped(session, job_data.get("id")):
                return
            _user_msg = Message(
                chat_id=imp_chat_id,
                role=MessageRole.USER,
                content=imp_text,
                message_metadata={
                    "source": "impersonation",
                    **({SOURCE_JOB_ID_METADATA_KEY: job_data["id"]} if job_data.get("id") else {}),
                },
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
                    model=_impersonation_reply_model(_chat, session),
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
    branch_id = metadata.get("branch_id")
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
                branch_id=branch_id,
            )
            logger.info("scene_image_job_queued", job_id=img_job.id, chat_id=chat_id)
    except Exception as e:
        logger.error("scene_chain_failed", job_id=job_data.get("id"), error=str(e), exc_info=True)


async def _handle_narrator(job_data: dict[str, Any], session: Any = None):
    """Persist one narrator message.

    The single writer of narrator messages. The agentic `narrate_scene` tool
    used to insert inline *and* emit `type: "narrator"`, so the same paragraph
    landed twice; the button path came through here alone. Both now do.

    `session` is the caller's when the write is made before the job goes
    COMPLETED, and None for the event bus consumer, which opens its own — the
    same split `_handle_chat_reply` documents.
    """
    metadata = job_data.get("metadata") or {}
    chat_id = metadata.get("chat_id") or job_data.get("chat_id")
    # `_persistable_text`, not `_first_text`: a whitespace-only turn is not prose,
    # and `if not content` does not catch it because `"   \n "` is truthy. Writing
    # it gives the model a blank message and, on the story side, a beat that
    # renders as a bare separator.
    content = _persistable_text(job_data)
    if not chat_id or not content:
        return

    message_metadata: dict[str, Any] = {"source": "narrator"}
    if metadata.get("narration_job_id"):
        message_metadata["narration_job_id"] = metadata["narration_job_id"]
    if job_data.get("id"):
        # The stamp that makes a dropped JOB_COMPLETED recoverable — and, via
        # `_write_once`, the thing that keeps the event bus from writing a
        # second copy of this paragraph.
        message_metadata[SOURCE_JOB_ID_METADATA_KEY] = job_data["id"]

    async def _write(active_session):
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
            active_session.add(msg)
            active_session.commit()
        except Exception as e:
            active_session.rollback()
            logger.warning("narrator_insert_failed", job_id=job_data.get("id"), error=str(e))

    await _write_once(job_data, session, label="narrator", write=_write)


def _first_output_tool_calls(job_data: dict[str, Any]) -> Any:
    """The tool-call transcript on the first output, or None.

    One reader for the two paths that need it (`_write_chat_reply` and
    `_append_swipe_alternative`). Indexing `outputs[0]` directly is a latent
    IndexError on any empty-output job.
    """
    outputs = job_data.get("outputs") or []
    if outputs and isinstance(outputs[0], dict):
        return outputs[0].get("tool_calls")
    return None


def _impersonation_reply_model(chat, session) -> str:
    """The model the reply chained off an impersonation should run on.

    Same authority as every `chats.py` reply path. It used to be
    `chat.llm_model or get_default_llm_model()`, which skipped the rp/util role
    router — so the one reply the user never typed could resolve to a different
    model than the ones they did.
    """
    from services.llm_config import model_for_kind

    return model_for_kind("chat_reply", chat.llm_model, session)


async def _handle_chat_reply(job_data: dict[str, Any], session: Any = None):
    """Persist a paid LLM reply as the assistant Message.

    `session` is the caller's when the write is made by `complete_when_ready` —
    the durable path, run BEFORE the job goes COMPLETED — and None for the
    event bus consumer, which opens its own. The same code runs either way, and
    `_write_once` makes the double delivery a no-op rather than a duplicate
    reply.
    """
    chat_id = job_data.get("metadata", {}).get("chat_id")
    content = _persistable_text(job_data)

    if not chat_id or not content:
        return

    await _write_once(
        job_data,
        session,
        label="chat_reply",
        write=lambda active: _write_chat_reply(job_data, active, content),
    )


@asynccontextmanager
async def _session_for(_job_data: dict[str, Any], session: Any):
    """The caller's session if one was passed, otherwise a fresh one."""
    if session is not None:
        yield session
        return
    async with get_session_context() as opened:
        yield opened


async def _write_once(
    job_data: dict[str, Any],
    session: Any,
    *,
    label: str,
    write,
    already_written=None,
) -> None:
    """Run `write(session)` once per job, however often the job is delivered.

    Idempotent, and load-bearing rather than defensive.

    Every handler in `_PRECOMPLETION_PERSISTED_TYPES` is now called twice on the
    happy path: once by `complete_when_ready` BEFORE the job goes COMPLETED, and
    again by the event bus consumer when that completion emits JOB_COMPLETED.
    The first call has to win and the second has to be free — otherwise a reply,
    a narration or an illustration is written twice.

    Which is exactly what happened. `chat_reply` had this guard from the day the
    pre-completion path was introduced; `narrator` and `chat_image` got the
    pre-completion path later and were given the *stamp* but not the *check*, so
    both stamped a value nothing ever read. Every chat illustration therefore
    produced two sets of IMAGE messages and two sets of `CollectionImage` rows,
    and every narration two NARRATOR messages.

    Matched on the flat `source_job_id` scalar, which is the same field
    `find_lost_chat_artifacts` uses to decide an artefact was never written — so
    the guard and the reconciler agree by construction on what "already written"
    means.
    """
    if already_written is None:
        # Resolved here rather than as a default argument because
        # `_reply_already_stamped` is declared below this function, and a default
        # is evaluated at definition time — which would be a NameError on import.
        already_written = _reply_already_stamped

    job_id = job_data.get("id")
    async with _session_for(job_data, session) as active_session:
        if job_id and already_written(active_session, job_id):
            logger.debug("artifact_already_persisted", label=label, job_id=job_id)
            return
        await write(active_session)


def _impersonation_already_stamped(session, job_id: str | None) -> bool:
    """Is this impersonation already written, with its chained reply spent?

    The stamp lives on the USER message the handler inserts. A redelivery finds
    it and returns before the insert — which is the only correct place for the
    check, because the `_reply_job` enqueue that follows is the expensive half
    and runs unconditionally once past the insert.
    """
    if not job_id:
        return False
    from sqlmodel import select

    flat = Message.message_metadata[SOURCE_JOB_ID_METADATA_KEY].as_string()
    rows = session.exec(
        select(Message).where(
            Message.role == MessageRole.USER,
            Message.message_metadata["source"].as_string() == "impersonation",
            flat == job_id,
        )
    ).all()
    return bool(rows)


def _reply_already_stamped(session, job_id: str) -> bool:
    """Is there already a message carrying this job as its source?

    One flat JSON lookup rather than a scan: `source_job_id` is a scalar in
    `message_metadata`, so it can be selected and compared in SQL.

    Synchronous on purpose. It was `async` while being called without `await`,
    which made every call return a truthy coroutine object — and the guard then
    short-circuited every reply for a while.
    """
    from sqlmodel import select

    flat = Message.message_metadata[SOURCE_JOB_ID_METADATA_KEY].as_string()
    return session.exec(select(flat).where(flat == job_id)).first() is not None


def _beat_already_stamped(session, job_id: str) -> bool:
    """Is there already a story beat carrying this job as its source?

    The story counterpart of `_reply_already_stamped`. `source_job_id` is a
    scalar inside each beat dict in `StoryChapter.beats`, which is a JSON
    column — so the lookup is a flat JSON-path select against the chapter row
    rather than a per-beat comparison, for the same reason the chat guard is.

    It needs its own query rather than a shared one because the two write to
    different tables: a chat artefact is a `messages` row, a story artefact is a
    beat inside a `story_chapters` row. Reusing the chat query here would make
    every story continuation look un-written and duplicate on every delivery.
    """
    from sqlalchemy import Text, cast

    from sqlmodel import select

    # A string search, not a JSON path.
    #
    # `beats` is a LIST of dicts, so `beats['source_job_id']` is not the flat key
    # lookup that works on `Message.message_metadata` — Postgres has no `->>` for
    # an array, and the expression silently returns NULL rather than failing, so
    # every story artefact looked un-written. Searching for the quoted id avoids
    # the dialect difference entirely: it serialises identically on JSONB (with
    # spaces after the colons) and on SQLite's JSON1 (without). Same approach and
    # the same escaping helper `reference_cleanup._scrub_json_array` already uses.
    pattern = like_contains(f'"{job_id}"')
    return session.exec(
        select(StoryChapter).where(
            cast(StoryChapter.beats, Text).like(pattern, escape=LIKE_ESCAPE_CHAR)
        )
    ).first() is not None


async def _write_chat_reply(job_data: dict[str, Any], session, content: str) -> None:
    """The write itself. Split out so the guard and the write are distinct."""
    chat_id = job_data.get("metadata", {}).get("chat_id")
    metadata = job_data.get("metadata", {})
    job_id = job_data.get("id")
    tool_calls = _first_output_tool_calls(job_data)
    try:
        msg_metadata = {"agentic": bool(tool_calls)}
        if "orchestrator_depth" in metadata:
            msg_metadata["orchestrator_depth"] = metadata["orchestrator_depth"]
        if job_id:
            # The link that makes a dropped JOB_COMPLETED recoverable:
            # find_unpersisted_chat_replies() looks for COMPLETED chat_reply
            # jobs with no message carrying this stamp.
            msg_metadata[SOURCE_JOB_ID_METADATA_KEY] = job_id
        # The exchange record rides on the job so it can be put on the row: what
        # THIS reply was actually told, as opposed to what the context builder
        # would assemble today. `_sections` and the internal `_pinned` / `_kind`
        # keys exist only inside the build, so this is the one chance to keep
        # them — which is why it is stamped at send time rather than read on
        # demand.
        #
        # A dict, validated by shape, because a malformed blob would surface as
        # a UI crash rather than a bad reply.
        trace = metadata.get("context_trace")
        if isinstance(trace, dict) and trace.get("v") == 1:
            msg_metadata["context_trace"] = trace

        if metadata.get("is_swipe") and metadata.get("target_message_id"):
            await _append_swipe_alternative(job_data, session, content, msg_metadata, metadata)
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


async def _append_swipe_alternative(job_data, session, content, msg_metadata, metadata) -> None:
    """Append a swipe's alternate onto its anchor message, or refuse clearly."""
    chat_id = job_data.get("metadata", {}).get("chat_id")
    target_msg = session.get(Message, metadata["target_message_id"])
    if target_msg and target_msg.chat_id != chat_id:
        # The id exists but belongs to a different chat. Swiping a message in
        # one conversation from another is never intended, and writing to it
        # would move text across chats.
        logger.warning(
            "chat_swipe_target_wrong_chat",
            job_id=job_data.get("id"),
            chat_id=chat_id,
            target_chat_id=target_msg.chat_id,
        )
        return
    if not target_msg:
        # The target is gone (deleted, or rolled back) while this job was in
        # flight. Appending a fresh CHAR message at the tail would be wrong in
        # two reachable ways: the user regenerates or deletes the message they
        # asked to swipe, the in-flight job lands afterwards and re-inserts the
        # text they discarded; and
        # `POST /api/jobs/reconcile-chat-replies` replays every COMPLETED
        # chat_reply with no source stamp, so every reply that was ever
        # regenerated or rolled back — the ones whose stamped message was
        # deleted — would be reported as a lost reply and resurrected at the
        # end of the chat.
        #
        # A swipe has no meaning without its anchor, so this is a no-op rather
        # than a fallback. The job still completes normally, so the cost is
        # already sunk either way; what matters is that it does not mutate the
        # conversation.
        logger.warning(
            "chat_swipe_target_missing",
            job_id=job_data.get("id"),
            chat_id=chat_id,
            target_message_id=metadata.get("target_message_id"),
        )
        return

    target_meta = dict(target_msg.message_metadata or {})
    alternates = target_meta.get("alternates", [target_msg.content])
    if target_msg.content not in alternates:
        alternates.insert(0, target_msg.content)

    alternates.append(content)
    active_index = len(alternates) - 1

    target_msg.content = content
    target_msg.tool_calls = _first_output_tool_calls(job_data)
    target_meta.update(msg_metadata)
    target_meta.update({"alternates": alternates, "active_index": active_index})
    target_msg.message_metadata = target_meta
    target_msg.tool_calls = _first_output_tool_calls(job_data)
    session.add(target_msg)
    session.commit()


async def _handle_story_continue(job_data: dict[str, Any], session: Any = None):
    """Append one NARRATOR beat with the continuation's prose.

    `session` is the caller's when the write is made by `complete_when_ready`
    before the job goes COMPLETED, and None for the event bus consumer — the
    same split as `_handle_chat_reply`. Story continuations used to have no
    pre-completion path at all, so an evicted JOB_COMPLETED was a paid
    generation whose text existed nowhere and which nothing could repair.

    Idempotent on `source_job_id`, written onto the beat by
    `_write_story_beat_once` below. Unlike `chat_image` and `story_image` this
    handler is NOT naturally idempotent — it appends — so the guard is what makes
    the double delivery free rather than a duplicate paragraph.
    """
    chapter_id = job_data.get("metadata", {}).get("chapter_id")
    # `_persistable_text`: a whitespace-only continuation is not a paragraph, and
    # `if not content` does not catch it because `"   \n "` is truthy. Writing it
    # gives the chapter a beat whose only contribution to the prose is a bare
    # separator.
    content = _persistable_text(job_data)
    if not chapter_id or not content:
        return

    async def _write(active_session):
        try:
            chapter = active_session.get(StoryChapter, chapter_id)
            if not chapter:
                return
            # Imported here, not at module scope: `stories` imports
            # `SOURCE_JOB_ID_METADATA_KEY` from this module, so a top-level
            # import both ways is a cycle.
            from api.routes.world_vault.stories import append_beat, ensure_beat_ids

            depth = job_data.get("metadata", {}).get("orchestrator_depth", 0)
            retry_of = job_data.get("metadata", {}).get("retry_of")
            ensure_beat_ids(chapter)
            hop_metadata = {
                # The hop this beat came from, so a beats panel can label an
                # intermediate turn the way the chat UI labels one. Until now
                # this was recorded on chat rows only — chat stamps
                # `orchestrator_depth` into `message_metadata` and renders a
                # "Step N/5" badge, and story recorded nothing, so a
                # tool-calling hop's prose was indistinguishable from a real
                # continuation.
                "orchestrator_depth": depth,
                # True only for a hop that exists to make a tool call, so the
                # UI can distinguish "the model is thinking" from "the model
                # is continuing the story".
                **({"intermediate": True} if depth else {}),
            }
            if retry_of:
                # A retry is an ALTERNATE of the beat it replaces, not a
                # replacement of it — the chat-swipe model. Retry used to trim
                # the beat first and append a new one, so the take you disliked
                # was gone the instant you asked for a second opinion.
                from api.routes.world_vault.stories import append_beat_alternate

                append_beat_alternate(
                    chapter, active_session,
                    role=StoryBeatRole.NARRATOR.value,
                    content=content,
                    retry_of=retry_of,
                    source_job_id=job_data.get("id"),
                    extra=hop_metadata,
                )
            else:
                from api.routes.world_vault.stories import append_beat

                append_beat(
                    chapter, active_session,
                    role=StoryBeatRole.NARRATOR.value,
                    content=content,
                    source_job_id=job_data.get("id"),
                    extra=hop_metadata,
                )
            active_session.add(chapter)
            active_session.commit()
        except Exception as e:
            active_session.rollback()
            logger.warning("story_continue_failed", job_id=job_data.get("id"), error=str(e))

    await _write_once(
        job_data,
        session,
        label="story_continue",
        write=_write,
        # Beats live on `StoryChapter`, not `Message`, so the guard has to look
        # there or every redelivery looks like a first delivery.
        already_written=_beat_already_stamped,
    )


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


async def _handle_chat_tts(job_data: dict[str, Any], session: Any = None):
    """Attach a completed TTS job's audio to the message that asked for it.

    `session` is the caller's when this runs before the job goes COMPLETED, and
    None for the event bus consumer.

    Stamps `tts_source_job_id` — its OWN key, not `source_job_id`, because the
    message already carries the reply job's stamp and overwriting it would break
    chat-reply recovery. This kind used to be excluded from reconciliation with
    the reasoning that there was no row to find; the reason there was no row to
    find is that nothing was stamped.
    """
    chat_id = job_data.get("metadata", {}).get("chat_id")
    message_id = job_data.get("metadata", {}).get("message_id")
    audio_path = _first_output_path(job_data)

    if not chat_id or not message_id or not audio_path:
        return

    async with _session_for(job_data, session) as session:
        try:
            msg = session.get(Message, message_id)
            if msg and msg.chat_id == chat_id:
                meta = dict(msg.message_metadata or {})
                if job_data.get("id"):
                    meta[TTS_SOURCE_JOB_ID_METADATA_KEY] = job_data["id"]
                meta["audio_path"] = audio_path
                msg.message_metadata = meta
                session.add(msg)
                session.commit()
        except Exception as e:
            session.rollback()
            logger.warning("chat_tts_msg_failed", job_id=job_data.get("id"), error=str(e))


async def _handle_story_tts(job_data: dict[str, Any], session: Any = None):
    """Store the audio path from a story chapter TTS job into the chapter's beats.

    `session` is the caller's when this runs before the job goes COMPLETED, and
    None for the event bus consumer.

    Stamps `tts_source_job_id` on the beat, for the same reason `chat_tts` does:
    without it the reconciler cannot tell a written artefact from a lost one, and
    re-drives this kind on every sweep forever.

    Goes through `StoryBeatRepository` and then `sync_from_rows`, like every
    other beat writer. It used to assign `chapter.beats` directly, which was
    invisible until the *next* beat write on that chapter: `sync_from_rows`
    rebuilds the JSON array from the rows, so a TTS beat that was never
    inserted as a row simply stopped existing — the narration's `audio_path`
    vanished with no error and no way to get it back. Re-narrating after any
    other edit was the trigger, which is why it could sit unnoticed: the audio
    was there when it was made and gone after an unrelated continuation.
    """
    from core.entities import StoryChapter

    story_id = job_data.get("metadata", {}).get("story_id")
    chapter_id = job_data.get("metadata", {}).get("chapter_id")
    audio_path = _first_output_path(job_data)

    if not story_id or not chapter_id or not audio_path:
        return

    async with _session_for(job_data, session) as session:
        try:
            from api.routes.world_vault.stories import sync_from_rows
            from infrastructure.repositories.story_beat_repo import StoryBeatRepository

            chapter = session.get(StoryChapter, chapter_id)
            if chapter and chapter.story_id == story_id:
                repo = StoryBeatRepository(session)
                rows = repo.rows_by_chapter(chapter.id)
                job_id = job_data.get("id") or None
                if rows and rows[-1].role == TTS_BEAT_ROLE:
                    repo.set_audio(rows[-1].id, audio_path=audio_path, tts_source_job_id=job_id)
                else:
                    repo.append(
                        chapter.id,
                        role=TTS_BEAT_ROLE,
                        content="",
                        parent_beat_id=(rows[-1].id if rows else None),
                        audio_path=audio_path,
                        tts_source_job_id=job_id,
                    )
                sync_from_rows(chapter, session)
                session.add(chapter)
                session.commit()
        except Exception as e:
            session.rollback()
            logger.warning("story_tts_chapter_failed", job_id=job_data.get("id"), error=str(e))

async def _handle_chat_image(job_data: dict[str, Any], session: Any = None):
    """Append one IMAGE message per generated output.

    `session` is the caller's when this runs before the job goes COMPLETED —
    the durable path — and None for the event bus consumer. Same split as
    `_handle_chat_reply`.
    """
    image_paths = _output_paths(job_data)
    chat_id = job_data.get("metadata", {}).get("chat_id")
    metadata = job_data.get("metadata", {})
    if not chat_id or not image_paths:
        return

    async def _write(active_session):
        # What the image DEPICTS, which is the only thing worth putting in the
        # transcript. This used to be a string literal per source —
        # "[Image generated by generate_image]" or "[Scene illustration]" — so a
        # conversation full of illustrations said "an illustration happened here"
        # and gave the model nothing to reason with. `_tool_generate_image` now
        # carries the prompt as `image_context`, and the scene-prompt path always
        # did.
        image_context = (metadata.get("image_context") or "").strip()
        if image_context:
            content = image_context
        elif metadata.get("source") == "agentic_tool":
            content = f"[Image generated by {metadata.get('tool_name', 'generate_image')}]"
        else:
            content = "Generated Image:"

        # The thread the image was asked for. A branch's copies share their
        # originals' `chat_id` and `created_at`, so an image written without it
        # interleaves into the original thread and the fork the user is reading
        # never shows it — the same failure `_handle_chat_reply` and
        # `_handle_narrator` already carry `branch_id` to avoid.
        branch_id = metadata.get("branch_id")
        metadata_character_id = metadata.get("character_id")
        # One message per output. This was `image_path = outputs[0]...`, so a
        # batch that produced four images attached one and dropped three, even
        # though all four were already in the `assets` table and visible in the
        # gallery — the conversation was the only place they went missing.
        #
        # All rows go in as ONE unit. This used to `commit()` inside the loop
        # and `rollback()` on failure, which had two defects that only show up
        # when one of several images misbehaves: N images meant N commits
        # (N fsyncs, N transactions, and N chances to lose the whole batch to
        # a mid-flight failure), and the rollback was not scoped to the row
        # that failed — it discarded every other change pending on this shared
        # session. So image 3 of 4 failing could silently drop rows 1 and 2
        # while the job still read COMPLETED, leaving the transcript shorter
        # than the gallery with nothing anywhere recording the gap.
        try:
            active_session.add_all([
                Message(
                    role=MessageRole.SYSTEM,
                    kind=MessageKind.IMAGE,
                    content=content,
                    image_path=path,
                    chat_id=chat_id,
                    branch_id=branch_id,
                    character_id=metadata_character_id,
                    # The stamp that makes a dropped JOB_COMPLETED recoverable.
                    # One job, N messages, all carrying the same id — which is
                    # fine for the "not in stamped" filter, because the filter
                    # asks whether the job was written at all.
                    message_metadata=(
                        {SOURCE_JOB_ID_METADATA_KEY: job_data["id"]} if job_data.get("id") else {}
                    ),
                )
                for path in image_paths
            ])
            active_session.commit()
        except Exception as e:
            active_session.rollback()
            logger.warning(
                "chat_image_msg_failed",
                job_id=job_data.get("id"),
                image_count=len(image_paths),
                error=str(e),
            )

        try:
            character_id = metadata_character_id
            if not character_id:
                chat = active_session.get(Chat, chat_id)
                if chat:
                    character_id = chat.character_id
            if character_id:
                collection = active_session.exec(
                    select(Collection).where(Collection.character_id == character_id)
                ).first()
                if collection:
                    for path in image_paths:
                        existing = active_session.exec(
                            select(CollectionImage).where(
                                CollectionImage.collection_id == collection.id,
                                CollectionImage.image_filename == path,
                            )
                        ).first()
                        if not existing:
                            active_session.add(CollectionImage(
                                collection_id=collection.id,
                                image_filename=path,
                            ))
                    active_session.commit()
        except Exception as e:
            active_session.rollback()
            logger.warning("chat_image_collection_failed", job_id=job_data.get("id"), error=str(e))

    await _write_once(job_data, session, label="chat_image", write=_write)


async def _handle_story_image(job_data: dict[str, Any], session: Any = None):
    """Append the generated images to the chapter.

    `session` is the caller's when this runs before the job goes COMPLETED, and
    None for the event bus consumer.

    Idempotent already, and not by the `source_job_id` stamp: a path already in
    `chapter.image_paths` is skipped, so re-delivery adds nothing. That is what
    makes it safe to add to `_PRECOMPLETION_PERSISTED_TYPES` without a guard of
    its own.
    """
    image_paths = _output_paths(job_data)
    chapter_id = job_data.get("metadata", {}).get("chapter_id")
    if not chapter_id or not image_paths:
        return

    async with _session_for(job_data, session) as session:
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

    from services.embedding_service import get_embedding_service

    entries_to_build: list[dict[str, Any]] = []
    for lore_data in (parsed.get("lorebooks") or []):
        if not lore_data.get("name"):
            continue
        desc = lore_data.get("description") or ""
        name = lore_data.get("name", "")
        text_for_embed = f"{name} {desc}".strip()
        emb = None
        if text_for_embed:
            try:
                emb = await asyncio.to_thread(
                    get_embedding_service().generate_embedding, text_for_embed
                )
            except Exception as exc:
                logger.warning("story_parse_embedding_failed", name=name, error=str(exc))
        entries_to_build.append({
            "name": name,
            "description": lore_data.get("description"),
            "content": desc,
            "keys": [name],
            "embedding": emb,
        })

    async with get_session_context() as session:
        try:
            story = session.get(Story, story_id)
            if not story:
                return

            world_id = story.world_id
            new_character_ids: list[str] = []

            for char_data in (parsed.get("characters") or []):
                if not char_data.get("name"):
                    continue
                character = Character(
                    name=char_data.get("name", ""),
                    description=char_data.get("description"),
                    personality=char_data.get("personality"),
                    world_id=world_id,
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
                    world_id=world_id,
                )
                session.add(location)
                new_location_ids.append(location.id)

            for item in entries_to_build:
                lorebook = Lorebook(
                    name=item["name"],
                    description=item["description"],
                    world_id=world_id,
                )
                session.add(lorebook)
                entry = LorebookEntry(
                    lorebook_id=lorebook.id,
                    content=item["content"],
                    keys=item["keys"],
                    embedding=item["embedding"],
                )
                session.add(entry)
                new_lorebook_ids.append(lorebook.id)

            # One flush for every entity, then ONE commit.
            session.flush()

            if world_id:
                from services.world_ownership import link_to_world
                for c_id in new_character_ids:
                    c_row = session.get(Character, c_id)
                    if c_row:
                        link_to_world(session, c_row, world_id)
                for l_id in new_location_ids:
                    l_row = session.get(Location, l_id)
                    if l_row:
                        link_to_world(session, l_row, world_id)
                for lb_id in new_lorebook_ids:
                    lb_row = session.get(Lorebook, lb_id)
                    if lb_row:
                        link_to_world(session, lb_row, world_id)

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


async def _handle_voice_design(job_data: dict[str, Any]):
    """Persist designed VoiceModel rows and attach to characters if requested."""
    from core.entities import VoiceModel

    metadata = job_data.get("metadata") or {}
    specs = metadata.get("voices") or []
    outputs = job_data.get("outputs") or []
    if not specs:
        return

    output_paths: list[str] = []
    for out in outputs:
        if isinstance(out, dict):
            path = out.get("relative_path") or out.get("filename") or out.get("path")
            if path:
                output_paths.append(path)
    if not output_paths and job_data.get("image_path"):
        output_paths.append(job_data["image_path"])

    async with get_session_context() as session:
        try:
            for idx, spec in enumerate(specs):
                if not isinstance(spec, dict) or not spec.get("name"):
                    continue
                audio_path = (
                    output_paths[idx]
                    if idx < len(output_paths)
                    else (output_paths[0] if output_paths else None)
                )
                char_id = spec.get("character_id")
                char = session.get(Character, char_id) if char_id else None
                world_id = char.world_id if char else metadata.get("world_id")
                voice = VoiceModel(
                    name=spec["name"],
                    description=spec.get("description"),
                    sample_audio_path=audio_path,
                    preview_path=audio_path,
                    character_id=char.id if char else None,
                    world_id=world_id,
                    provider="qwen3_tts",
                )
                session.add(voice)
                session.flush()
                if char:
                    char.voice_model_id = voice.id
                    if not char.tts_voice_profile and spec.get("description"):
                        char.tts_voice_profile = spec["description"]
                    session.add(char)
                if world_id:
                    from services.world_ownership import link_to_world
                    link_to_world(session, voice, world_id)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.warning("voice_design_failed", job_id=job_data.get("id"), error=str(e))


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
            event_type = _event_type_of(job_data)

            handler = _EVENT_DISPATCH.get(event_type)
            if handler is not None:
                await handler(job_data)
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
# Lost-artefact reconciliation
# ---------------------------------------------------------------------------
#
# The single consumer above is the only writer of chat replies, narrator
# paragraphs and chat images, and its input is a lossy queue. When a
# JOB_COMPLETED is evicted under backpressure the output is gone: the job is
# COMPLETED in the DB, the user paid for it, and the chat never shows it.
# Buffering (WORLD_INTEGRATION_QUEUE_SIZE) and the ERROR log on drop make that
# rare and visible; these functions make it recoverable.
#
# Detection works because a reconcilable handler stamps
# `message_metadata["source_job_id"]` on what it writes. A COMPLETED job of a
# reconcilable kind with no message carrying that stamp is a lost artefact.

# Event kinds -> handler. One table rather than the if/elif chain this
# replaces, because the reconciler needs the same routing the consumer does,
# and two copies of a dispatch table is how a job gets replayed through the
# wrong handler.
async def _handle_suggest_reply(job_data: dict[str, Any], session: Any = None) -> None:
    """A suggest-reply job's completion has nothing to persist.

    The suggestion is streamed to the client and nothing else — it is never
    written to `messages`, so there is no artefact to store and no recovery to
    perform. This entry exists purely so the kind is DISPATCHABLE, which is what
    it was not: with no key here, a suggest job's `JOB_COMPLETED` fell through
    every branch of the consumer.

    That mattered because `_finalize_llm_job` calls `apply_agentic_chain` for any
    job with a `chat_id` that is not `background`, not `suppress_bubble`, and not
    `suppress_memory_extraction` — which a suggest job is. So it took this path
    and depends on it returning early here. Returning is also what keeps the
    handler out of `_RECONCILABLE_EVENT_TYPES`: there is nothing to find, because
    nothing is ever stamped.

    `chat_tts` is the contrast that makes the asymmetry worth a comment. It also
    mutates an existing message rather than inserting one, but it is NOT
    dispatchable, so it exits through this same fall-through. Two kinds, same
    shape, opposite choices — and the difference is that suggest-reply's output
    is not persisted anywhere, whereas chat_tts's is, and a mutation that never
    lands is a loss.
    """
    logger.debug("suggest_reply_no_artifact", job_id=job_data.get("id"))
    return


_EVENT_DISPATCH: dict[str, Any] = {
    "impersonation": _handle_impersonation,
    "suggest_reply": _handle_suggest_reply,
    "story_illustrate_prompt": _handle_story_illustrate,
    "scene_prompt": _handle_scene_prompt,
    "narrator": _handle_narrator,
    "chat_reply": _handle_chat_reply,
    "story_continue": _handle_story_continue,
    "chat_image": _handle_chat_image,
    "chat_tts": _handle_chat_tts,
    "voice_preview": _handle_voice_preview,
    "voice_design": _handle_voice_design,
    "story_tts": _handle_story_tts,
    "story_image": _handle_story_image,
    "story_parse": _handle_story_parse,
    "character_avatar_animate": _handle_avatar_animate,
}

# Job kinds whose completed output is recoverable by replaying the handler.
#
# The rule is one sentence: a kind is here when a replay of its handler is free
# — when the handler either inserts on an identity the sweep can query, or
# idempotently stamps/marks what it already wrote. What is NOT here is
# `suggest_reply`, and the reason is the same rule rather than an exception to
# it.
#
# Everything below is recoverable, and each one got there by the same route: the
# kind was excluded with a reason that described what had been built rather than
# what was possible.
#
#   `chat_tts`      — excluded because "it mutates an existing message, so there
#                     is no row to find". True only because nothing was
#                     stamped. It now stamps its OWN key — not `source_job_id`,
#                     which the reply on that message already carries and
#                     overwriting would make the reply look unwritten — and is
#                     found by the message-level sweep like any insert kind.
#   `impersonation`  — excluded because it chains a reply, so a replay meant a
#                     duplicate line plus a second spent reply. Guarded on the
#                     stamp it already wrote, it is the only chaining handler
#                     that is recoverable without duplicating anything.
#   `story_image` / `story_tts` — were excluded by omission, not by reason. They
#                     were idempotent by construction and therefore also
#                     invisible: found as lost on every sweep, forever, re-driven
#                     each time. Idempotence without detection is not safety, it
#                     is invisibility — so both stamp now, `story_image` by
#                     comparing its output paths against `chapter.image_paths`.
#
# `suggest_reply` is dispatched (it returns early) and deliberately NOT here: a
# suggestion is streamed and never stored, so there is no artefact to find and
# nothing the reconciler could restore. That is the same rule applied to the
# other outcome — durable and stamped is recoverable, not durable is not.
_RECONCILABLE_EVENT_TYPES = (
    "chat_reply",
    "narrator",
    "chat_image",
    "story_continue",
    "story_image",
    "story_tts",
    "chat_tts",
    "impersonation",
)

# How far back the reconciler looks. Chats are read newest-first and only the
# tail can still be showing a hole, so a bounded window is both cheaper and less
# likely to re-drive a reply the user has since deleted on purpose.
RECONCILE_LOOKBACK_LIMIT = 500


def _event_type_of(job_data: dict[str, Any]) -> str | None:
    """The event kind a JOB_COMPLETED payload carries.

    Image, TTS and story jobs put it in the top-level `type`, merged from
    `event_extra` by `finalize_persisted_job_outputs`. LLM jobs keep it in
    `workflow.type` as well. The reconciler has to resolve this the same way the
    consumer does, or it replays a job through the wrong handler.
    """
    return (
        job_data.get("type")
        or (job_data.get("workflow") or {}).get("type")
        or (job_data.get("metadata") or {}).get("source")
    )


def _reconcilable_event_type(
    job: Any, metadata: dict[str, Any], workflow: dict[str, Any], artifact_event_type
) -> str | None:
    """The reconcilable event kind this job would have dispatched to, or None.

    The whole point of this function is that it derives the SAME kind the
    consumer derived, from the same evidence. It used to read a combination of
    `workflow["type"]` and `metadata["source"]`, which is not what the consumer
    reads: `_finalize_image_job` builds `event_extra` with a type computed from
    the *output path* and the job's scope, and that computed type is what
    `world_integration_service` dispatched on. So an image job with
    `source: "scene_illustrate"` dispatched as `chat_image` at runtime and
    looked like `scene_illustrate` to the old reconciler — which never matched
    `("chat_reply",)`, so no image was ever lost-and-recoverable even though it
    could be lost.

    LLM kinds are read from `workflow["type"]` / `metadata["type"]`, which is
    where the LLM builders put them. Artefact kinds come from the shared
    `artifact_event_type`, which is the single implementation of the output-based
    decision so this cannot drift from it again.
    """
    llm_type = workflow.get("type") or metadata.get("type")
    if llm_type in _RECONCILABLE_EVENT_TYPES:
        return llm_type

    if llm_type in ("tts", "voice_design") or artifact_event_type is None:
        return None

    outputs = job.outputs or []
    image_path = None
    for output in outputs:
        if isinstance(output, dict):
            image_path = output.get("relative_path") or output.get("filename")
            if image_path:
                break

    resolved = artifact_event_type(metadata, image_path)
    return resolved if resolved in _RECONCILABLE_EVENT_TYPES else None


def find_lost_chat_artifacts(
    session,
    *,
    limit: int = RECONCILE_LOOKBACK_LIMIT,
) -> list[tuple[str, dict[str, Any]]]:
    """Find COMPLETED reconcilable jobs whose message was never written.

    Returns ``(event_type, job_payload)`` pairs shaped like a JOB_COMPLETED
    event's ``job`` dict, so the caller can hand them straight back to the
    matching handler in :data:`_EVENT_DISPATCH`. An empty list means nothing is
    missing.

    Was `chat_reply`-only. It now covers narrator paragraphs and chat images
    too, which used to have exactly the same failure — a paid generation marked
    COMPLETED in the DB, never written to `messages`, and nothing anywhere
    recording the gap — because they came through the same lossy queue.

    Only the newest ``limit`` reconcilable jobs are examined — a hole older than
    the current conversation window is not worth risking a duplicate insert for.
    """
    from core.entities import Job, JobStatus

    # Imported here rather than at module scope: `job_processing` imports
    # `_handle_chat_reply` from this module, so a top-level import both ways
    # would be a cycle.
    from services.job_processing import artifact_event_type

    jobs = session.exec(
        select(Job)
        .where(
            Job.status == JobStatus.COMPLETED,
            # Two task types. `llm` for a reply or a narration, `image` for a
            # chat illustration; `tts` is absent by design (see
            # `_RECONCILABLE_EVENT_TYPES`).
            # `tts` as well as `llm` and `image`. It was omitted, so the
            # reconciler asked "which COMPLETED llm or image jobs lost their
            # artefact" and a COMPLETED tts job was never a candidate no matter
            # which kinds were listed in `_RECONCILABLE_EVENT_TYPES` — which is
            # how `chat_tts` stayed unrecoverable even once it had a stamp and a
            # dispatch entry.
            Job.task_type.in_(["llm", "image", "tts"]),
        )
        .order_by(Job.created_at.desc())
        .limit(max(1, limit) * 8)  # over-fetch: most of these are not reconcilable
    ).all()

    candidates: list[tuple[str, Any, dict[str, Any]]] = []
    for job in jobs:
        metadata = job.metadata_ if isinstance(job.metadata_, dict) else {}
        workflow = job.workflow if isinstance(job.workflow, dict) else {}
        event_type = _reconcilable_event_type(job, metadata, workflow, artifact_event_type)
        if event_type is None:
            continue
        # A chat artefact is scoped by `chat_id`, a story artefact by the
        # story/chapter pair. Both, because the reconciler used to accept only
        # `chat_id` and a story job carries neither — so every story artefact
        # kind was outside recovery entirely, no matter which kinds were listed
        # above.
        if not (
            metadata.get("chat_id")
            or workflow.get("chat_id")
            or metadata.get("chapter_id")
            or workflow.get("chapter_id")
        ):
            continue
        candidates.append((event_type, job, metadata))
        if len(candidates) >= max(1, limit):
            break

    if not candidates:
        return []

    job_ids = [job.id for _event_type, job, _metadata in candidates]
    stamped = _stamped_source_job_ids(
        session,
        [(job, metadata) for _event_type, job, metadata in candidates],
        job_ids,
    )

    return [
        (
            event_type,
            {
                "id": job.id,
                "outputs": job.outputs or [],
                "metadata": metadata,
                "workflow": job.workflow or {},
                "type": event_type,
            },
        )
        for event_type, job, metadata in candidates
        if job.id not in stamped
    ]


# Back-compat alias. The function is chat-scoped ("lost chat *artefacts*") and
# covers three kinds, but the old name is what `api/routes/jobs.py` and the
# existing tests call it.
find_unpersisted_chat_replies = find_lost_chat_artifacts


def _stamped_source_job_ids(
    session: Session, candidates: list[tuple[Any, dict[str, Any]]], job_ids: list[str]
) -> set[str]:
    """Which of `job_ids` already appear as a `source_job_id` on what they wrote.

    Three narrow queries instead of one unbounded full-row load, one per place an
    artefact lands: `messages` for a chat artefact, `story_chapters.beats` for a
    story one.

    The flat `source_job_id` is a scalar in `message_metadata`, so it can be
    compared and indexed in SQL. A swipe's `alternates` is a LIST of objects
    nested inside the same jsonb, which no plain column comparison can reach — so
    that half selects the one jsonb column and matches in Python. `beats` is the
    same shape and uses the same LIKE search as `_beat_already_stamped`, because a
    JSON path into an array is not a thing.

    The story half used to be missing entirely, which is why a repaired story
    artefact was found again forever: the detector asked only whether a job's id
    was on a `messages` row, and a story continuation writes no message.
    """
    wanted = set(job_ids)
    stamped: set[str] = set()

    # An image artefact is recognised by its OUTPUT PATHS, not by a stamp.
    #
    # `_handle_story_image` writes into `chapter.image_paths`, which holds bare
    # strings — there is nowhere on the artefact itself to put a stamp, and
    # stamping the last beat would mean the chapter's beats carry state about a
    # different thing. Comparing the job's outputs against that list is exact:
    # every path a completed job produced is either in the chapter or it is not.
    #
    # This kind used to have no detection at all, so it was found as lost on
    # every sweep forever and re-driven each time. It is idempotent (path dedupe
    # in the handler), so the cost was silent — the reconciler just never
    # reported a clean state, and an operator reading `found` could not tell a
    # real loss from a permanent false positive.
    for job, metadata in candidates:
        if metadata.get("type") != "story_image" and (job.workflow or {}).get("type") != "story_image":
            continue
        chapter_id = metadata.get("chapter_id") or (job.workflow or {}).get("chapter_id")
        if not chapter_id:
            continue
        chapter = session.get(StoryChapter, chapter_id)
        written = set(chapter.image_paths or []) if chapter is not None else set()
        wanted_paths = {
            o.get("relative_path") or o.get("filename")
            for o in (job.outputs or [])
            if isinstance(o, dict)
        }
        wanted_paths.discard(None)
        if wanted_paths and wanted_paths <= written:
            stamped.add(job.id)

    # A TTS artefact is recognised by its own stamp key, because it mutates a
    # row that already carries the general one.
    for job, metadata in candidates:
        tts_kind = metadata.get("type") == "chat_tts" or (job.workflow or {}).get("type") == "chat_tts"
        if not tts_kind:
            continue
        message_id = metadata.get("message_id")
        if not message_id:
            continue
        msg = session.get(Message, message_id)
        if msg is not None and (msg.message_metadata or {}).get(TTS_SOURCE_JOB_ID_METADATA_KEY) == job.id:
            stamped.add(job.id)

    chapter_ids = {
        (metadata.get("chapter_id") or (job.workflow or {}).get("chapter_id"))
        for job, metadata in candidates
    }
    chapter_ids.discard(None)
    if chapter_ids:
        for row in session.exec(
            select(StoryChapter.id, StoryChapter.beats).where(
                StoryChapter.id.in_(list(chapter_ids))
            )
        ).all():
            beats = row[1] or []
            for beat in beats:
                if not isinstance(beat, dict):
                    continue
                for key in (SOURCE_JOB_ID_METADATA_KEY, TTS_SOURCE_JOB_ID_METADATA_KEY):
                    value = beat.get(key)
                    if value in wanted:
                        stamped.add(value)
                # And inside `alternates`, which is where a RETRY's stamp lives.
                # A story retry stores its take as `{"text": ..., "source_job_id":
                # ...}` beside the original, so a job whose take was written
                # successfully would otherwise be found as lost forever and
                # re-driven on every sweep. Same reason the chat half scans
                # `alternates` too.
                for entry in beat.get("alternates") or []:
                    if not isinstance(entry, dict):
                        continue
                    for key in (SOURCE_JOB_ID_METADATA_KEY, TTS_SOURCE_JOB_ID_METADATA_KEY):
                        value = entry.get(key)
                        if value in wanted:
                            stamped.add(value)

    chat_ids = {
        (metadata.get("chat_id") or (job.workflow or {}).get("chat_id"))
        for job, metadata in candidates
    }
    chat_ids.discard(None)
    if not chat_ids:
        return stamped

    # One query per key rather than one per kind: both are flat scalars in the
    # same jsonb, and the kinds the detector accepts use exactly these two.
    for key in (SOURCE_JOB_ID_METADATA_KEY, TTS_SOURCE_JOB_ID_METADATA_KEY):
        flat = Message.message_metadata[key].as_string()
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


async def reconcile_unpersisted_chat_replies(
    session=None, *, limit: int = RECONCILE_LOOKBACK_LIMIT
) -> dict[str, Any]:
    """Re-drive chat artefacts that were generated but never persisted.

    Detection and repair in one call: every lost artefact found is replayed
    through the normal handler in :data:`_EVENT_DISPATCH`, so the write is
    identical to the one the event handler would have made (including the
    swipe-alternate branch on a reply). Idempotent: an artefact that is already
    persisted is not found, so a second call does nothing.

    Was `chat_reply`-only. The name stays because `api/routes/jobs.py` exposes
    it as `POST /reconcile-chat-replies` and an operator may have that wired
    into a cron; what it repairs is broader than either name says.

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
    for event_type, job_data in found:
        handler = _EVENT_DISPATCH.get(event_type)
        if handler is None:
            # Belt and braces: `find_lost_chat_artifacts` only returns kinds in
            # `_RECONCILABLE_EVENT_TYPES`, and every one of those has an entry.
            failed.append(job_data["id"])
            continue
        try:
            await handler(job_data)
            repaired.append(job_data["id"])
        except Exception as exc:  # pragma: no cover - handler swallows its own errors
            logger.error(
                "chat_reply_reconcile_failed",
                event_type=event_type,
                job_id=job_data.get("id"),
                error=str(exc),
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
