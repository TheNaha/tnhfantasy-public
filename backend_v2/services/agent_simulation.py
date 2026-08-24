# Idle simulation service
#
# Periodically generates in-character replies for chats that opted into idle
# simulation (Chat.idle_sim_enabled) and have been inactive for a while. The
# character "keeps the scene alive" while the user is away.
#
# Gated by COMFY_IDLE_SIM_ENABLED; registered in api/lifecycle.py.

from datetime import datetime, timedelta, timezone

from sqlmodel import select

from core.entities import Character, Chat, Job, JobStatus, Message
from infrastructure.logging import get_logger

logger = get_logger("idle_simulation")

IDLE_SIM_ACTIVITY_AGE_MINUTES = 30
IDLE_SIM_IN_FLIGHT_LOOKBACK_MINUTES = 120
MAX_CONTEXT_MESSAGES = 200

_IDLE_SIM_TRIGGER = (
    "[Idle simulation] The user has been away for a while. Act on your own "
    "as {character}: continue the scene with a brief in-character message, "
    "take a small initiative, or simply muse aloud. Do not narrate for the "
    "user or speak as them."
)


async def run_idle_simulation_tick(min_activity_age_minutes: int = IDLE_SIM_ACTIVITY_AGE_MINUTES) -> int:
    """Scan chats with idle simulation enabled and spawn an LLM reply job for
    those that have been dormant long enough and have no work in flight.

    Always registered in the scheduler; checks config at runtime so the
    toggle takes effect without a backend restart.

    Returns the number of jobs spawned.
    """
    import asyncio

    from config import get_config
    idle_sim_enabled = bool(get_config().get("ai", {}).get("idleSimEnabled", False))
    if not idle_sim_enabled:
        return 0

    from infrastructure.deps import get_session_context
    from services.context_builder import build_chat_context_async
    from services.job_queue import queue_manager
    from services.job_service import JobService
    from services.llm_config import get_default_llm_model
    from services.llm_workflow import build_chat_llm_workflow

    spawned = 0
    now = datetime.now(timezone.utc)
    activity_cutoff = now - timedelta(minutes=min_activity_age_minutes)
    inflight_cutoff = now - timedelta(minutes=IDLE_SIM_IN_FLIGHT_LOOKBACK_MINUTES)

    async with get_session_context() as session:
        chats = session.exec(select(Chat).where(Chat.idle_sim_enabled.is_(True))).all()

        for chat in chats:
            if chat.chat_type not in ("chat", "story"):
                continue

            last_message = session.exec(
                select(Message)
                .where(Message.chat_id == chat.id)
                .order_by(Message.created_at.desc())
                .limit(1)
            ).first()
            last_activity = last_message.created_at if last_message else chat.updated_at
            if last_activity is not None and last_activity.tzinfo is None:
                last_activity = last_activity.replace(tzinfo=timezone.utc)
            if not last_activity or last_activity > activity_cutoff:
                continue

            # Skip chats that already have an LLM job pending/running — the
            # reply is likely still landing or the user just re-engaged.
            recent_jobs = session.exec(
                select(Job)
                .where(Job.task_type == "llm", Job.created_at >= inflight_cutoff)
            ).all()
            busy = any(
                bool(j.metadata_) and j.metadata_.get("chat_id") == chat.id
                and j.status
                in (
                    JobStatus.PENDING,
                    JobStatus.SENT_TO_PROVIDER,
                    JobStatus.CONNECTED,
                    JobStatus.PRE_GENERATION,
                    JobStatus.GENERATING,
                    JobStatus.POST_PROCESSING,
                )
                for j in recent_jobs
            )
            if busy:
                continue

            past_messages = session.exec(
                select(Message)
                .where(Message.chat_id == chat.id)
                .order_by(Message.created_at)
                .limit(MAX_CONTEXT_MESSAGES)
            ).all()

            characters: list[Character] = []
            if chat.character_id:
                primary = session.get(Character, chat.character_id)
                if primary:
                    characters.append(primary)
            for cid in chat.additional_character_ids or []:
                if cid == chat.character_id:
                    continue
                extra = session.get(Character, cid)
                if extra and extra not in characters:
                    characters.append(extra)

            ctx_kwargs = {
                "characters": characters,
                "lorebook_ids": chat.active_lorebook_ids or None,
                "persona_name": chat.persona_name,
                "persona_description": getattr(chat, "persona_description", None),
                "story_time": chat.story_time,
                "story_location": chat.story_location,
                "location_id": getattr(chat, "location_id", None),
                "system_prompt_override": chat.system_prompt_override,
                "append_system_prompt": chat.append_system_prompt,
            }
            if chat.max_context_tokens:
                ctx_kwargs["max_context_tokens"] = chat.max_context_tokens

            system_prompt, context = await build_chat_context_async(
                past_messages,
                **ctx_kwargs,
            )

            character_display = characters[0].name if characters else (chat.persona_name or "character")
            workflow, metadata = build_chat_llm_workflow(
                messages=[
                    *context,
                    {"role": "user", "content": _IDLE_SIM_TRIGGER.format(character=character_display)},
                ],
                chat_id=chat.id,
                character_id=chat.character_id,
                system_prompt=system_prompt or None,
                model=chat.llm_model or get_default_llm_model(),
                type_="chat_reply",
                source="idle_simulation",
                extra_metadata={"idle_simulation": True},
            )

            job = await JobService(session).create_job(
                task_type="llm",
                workflow=workflow,
                metadata=metadata,
            )
            await queue_manager.enqueue(job.id, task_type="llm")
            spawned += 1
            logger.info("idle_sim_job_spawned", chat_id=chat.id, job_id=job.id)

    if spawned:
        logger.info("idle_sim_tick_complete", spawned=spawned)
    return spawned