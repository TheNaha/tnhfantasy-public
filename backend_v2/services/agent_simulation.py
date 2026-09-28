# Idle simulation service
#
# Periodically generates in-character replies for chats that opted into idle
# simulation (Chat.idle_sim_enabled) and have been inactive for a while. The
# character "keeps the scene alive" while the user is away.
#
# Gated by COMFY_IDLE_SIM_ENABLED; registered in api/lifecycle.py.

from datetime import datetime, timedelta, timezone

from sqlalchemy import exists
from sqlmodel import select

from core.entities import Character, Chat, Job, JobStatus, Message
from infrastructure.logging import get_logger

logger = get_logger("idle_simulation")

IDLE_SIM_ACTIVITY_AGE_MINUTES = 30
IDLE_SIM_IN_FLIGHT_LOOKBACK_MINUTES = 120
MAX_CONTEXT_MESSAGES = 200

# How many chats one tick may bill for.
#
# The loop had no ceiling, and its input is every `Chat` with idle simulation
# enabled and no bound on the query. So N dormant chats meant N paid LLM calls
# every tick, on top of the N paid memory-extraction calls each one triggers —
# a cost multiplier on a feature that is off by default and easy to forget is
# on. The default interval is 600 s, so an account with 50 idle-enabled chats
# spent 50 generations every ten minutes for messages nobody asked for.
#
# Deliberately checked BEFORE the per-chat work rather than after the increment,
# so the last iteration does not bill one more than the cap allows. The overflow
# is not deferred to the next tick: each tick re-evaluates dormency, and a chat
# that is skipped now may be re-engaged by the next one. The cap is a spend
# ceiling, not a queue.
IDLE_SIM_MAX_JOBS_PER_TICK = 5

# The statuses that mean "a reply is already on its way". Named here because
# the previous form of this check listed them inside a Python `any()`, which is
# why the set is easy to forget to extend when a status is added.
IN_FLIGHT_JOB_STATUSES = (
    JobStatus.PENDING,
    JobStatus.SENT_TO_PROVIDER,
    JobStatus.CONNECTED,
    JobStatus.PRE_GENERATION,
    JobStatus.GENERATING,
    JobStatus.POST_PROCESSING,
    JobStatus.RETRYING,
)

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

    from config import get_config
    idle_sim_enabled = bool(get_config().get("ai", {}).get("idleSimEnabled", False))
    if not idle_sim_enabled:
        return 0

    from infrastructure.deps import get_session_context
    from services.context_builder import build_chat_context_async
    from services.job_queue import queue_manager
    from services.job_service import JobService
    from services.llm_config import get_default_llm_model
    from services.llm_workflow import build_chat_llm_workflow, sampler_overrides

    spawned = 0
    eligible = 0
    now = datetime.now(timezone.utc)
    activity_cutoff = now - timedelta(minutes=min_activity_age_minutes)
    inflight_cutoff = now - timedelta(minutes=IDLE_SIM_IN_FLIGHT_LOOKBACK_MINUTES)

    async with get_session_context() as session:
        chats = session.exec(select(Chat).where(Chat.idle_sim_enabled.is_(True))).all()
        eligible = len(chats)

        for chat in chats:
            # Before any per-chat work, so the cap is a real ceiling on spend
            # rather than a post-hoc report of how much was already spent.
            if spawned >= IDLE_SIM_MAX_JOBS_PER_TICK:
                logger.warning(
                    "idle_sim_tick_capped",
                    spawned=spawned,
                    cap=IDLE_SIM_MAX_JOBS_PER_TICK,
                    eligible_chats=eligible,
                )
                break
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
            #
            # `exists()` rather than loading the rows. This ran once per
            # idle-sim-enabled chat on every tick and pulled every LLM job in
            # the lookback window for that chat as a WHOLE `Job` — `workflow`,
            # `metadata_` and `outputs` jsonb included — to read one enum field
            # and then test it in Python. An existence check is what was being
            # asked for and it is answered by the database, in one round trip
            # per chat instead of one that grows with the job table.
            busy = session.exec(
                select(
                    exists(
                        select(Job.id).where(
                            Job.task_type == "llm",
                            Job.created_at >= inflight_cutoff,
                            Job.status.in_(IN_FLIGHT_JOB_STATUSES),
                            Job.metadata_["chat_id"].as_string() == chat.id,
                        )
                    )
                )
            ).one()
            if busy:
                continue

            past_messages = list(
                session.exec(
                    select(Message)
                    .where(Message.chat_id == chat.id)
                    .order_by(Message.created_at.desc())
                    .limit(MAX_CONTEXT_MESSAGES)
                ).all()
            )
            past_messages.reverse()

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

            from services.context_builder import chat_context_kwargs

            # `session` is not optional in practice: it is what resolves
            # chat.persona_id into a persona name and description. Without it a
            # chat linked to a Persona row got its persona in every user-facing
            # path (all three chats.py call sites pass it) and silently lost it
            # here — a divergence visible only as the idle simulation replying
            # out of character.
            ctx_kwargs = chat_context_kwargs(chat, characters=characters, session=session)
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
                # Honour the chat's own sampler settings. Every other
                # Chat-bearing reply path passes this (7 call sites in
                # `chats.py`); this one did not, so a chat configured for
                # `temperature: 0.2` and `max_output_tokens: 300` — deliberately
                # short, low-variance idle chatter — got the global default
                # instead: an unbounded, high-temperature, long-form generation
                # the user neither configured nor wanted, billed every tick.
                samplers=sampler_overrides(chat),
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