"""Auto-extraction of character memories from chat conversations.

When a chat reply finalizes (no more tool calls), this service can enqueue
a background LLM job that reads recent messages and extracts durable memories
for the character's autobiographical memory store.
"""
import json
from datetime import datetime, timezone

from sqlmodel import Session, select

from core.entities import CharacterMemory, Message, MessageRole
from infrastructure.logging import get_logger

logger = get_logger("memory_extraction")

# Marks a row that was written without a vector because the embedding model was
# unavailable, so the memory is findable (`tags @> '["embedding-pending"]'`) and
# not mistaken for a deliberate NULL. See create_memories_from_extraction.
EMBEDDING_PENDING_TAG = "embedding-pending"

# How many recent messages the extraction prompt sees.
MEMORY_EXTRACTION_WINDOW = 20
# How many *newly answered* user turns are worth a billed LLM call. Two, so the
# extraction has something to connect — a single new turn is often small talk.
MEMORY_EXTRACTION_MIN_NEW_TURNS = 2

# Cosine-distance cutoff for treating a newly extracted memory as a near-duplicate
# of one the character already has.
#
# Deliberately very tight. This is not a relevance filter — retrieval has its own
# cutoff (`rag_pipeline.rag_max_distance`) and loosening this would start
# discarding genuinely distinct facts. 0.06 on MiniLM sentence embeddings is
# "the same sentence, lightly reworded", which is what regenerating a reply
# produces. An exact normalised-content match is also checked, and is what
# catches the common case at zero cost.
MEMORY_DEDUP_MAX_DISTANCE = 0.06


def memory_extraction_enabled() -> bool:
    """Whether a chat reply may enqueue the memory-extraction LLM call.

    Config `ai.memoryExtractionEnabled`, default true. There was no gate before,
    so this ran as an unconditional billed call — and not only on real replies:
    `generate_swipe` and `regenerate_reply` both default to `type_="chat_reply"`,
    and the idle simulator fires one for a turn the user never wrote.
    """
    import config as app_config

    try:
        ai_block = app_config.get_config().get("ai") or {}
    except Exception:  # pragma: no cover - config read failures default to on
        return True
    return bool(ai_block.get("memoryExtractionEnabled", True))

EXTRACTION_PROMPT = """You are a memory extraction assistant. Given a conversation between a user and a character, extract durable, factual memories that the character should remember for future interactions.

Rules:
- Extract 1-5 memories maximum
- Each memory should be a single, concise sentence
- Focus on: user preferences, character relationships, important events, decisions, opinions, facts about the user
- Do NOT include trivial greetings or small talk
- Output ONLY a JSON array of strings, e.g. ["memory 1", "memory 2"]
- If nothing worth remembering, output: []

Conversation:
{messages}
"""


def _recent_messages(session: Session, chat_id: str) -> list[Message]:
    """The newest 20 messages, newest first. One query, shared by both callers.

    `should_extract_memories` and `build_extraction_messages` each ran this same
    `select(...).order_by(created_at.desc()).limit(20)`, so every chat reply
    fetched the same twenty rows twice.
    """
    return list(
        session.exec(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.desc())
            .limit(MEMORY_EXTRACTION_WINDOW)
        ).all()
    )


def should_extract_memories(recent: list[Message]) -> bool:
    """Are there enough *newly complete* user turns to be worth an extraction?

    The previous test was `len(user_msgs) >= 2` over the newest 20 messages. Once
    a chat passed 20 messages that is true forever: any normal user/character
    alternation puts at least two user messages in the window, so every single
    chat reply enqueued a second, separately billed LLM job. The gate was
    supposed to be a throttle and was a constant.

    A turn counts as new when the character has already answered it — i.e. there
    is a non-user message after it. The message that triggered the extraction
    IS that answer, so the turn it completes is excluded and the one before it
    is the first candidate. A conversation that alternates
    user/character/user/character therefore yields two user messages before the
    trigger, and the third is the trigger itself: the gate is closed until the
    user sends a fourth.
    """
    answered = False
    new_user_turns = 0
    for message in recent:  # newest first
        if message.role != MessageRole.USER:
            answered = True
            continue
        if answered:
            new_user_turns += 1
    return new_user_turns >= MEMORY_EXTRACTION_MIN_NEW_TURNS


def build_extraction_messages(recent: list[Message]) -> list[str]:
    """Render the extraction window as `Role: content` lines, oldest first."""
    ordered = list(reversed(recent))
    lines = []
    for m in ordered:
        role = "User" if m.role == MessageRole.USER else "Character"
        lines.append(f"{role}: {m.content}")
    return lines


async def enqueue_memory_extraction(
    session: Session,
    chat_id: str,
    character_id: str,
    job_service,
) -> bool:
    """Enqueue a background LLM job to extract memories from a chat."""
    if not memory_extraction_enabled():
        logger.debug("memory_extraction_disabled", chat_id=chat_id)
        return False
    recent = _recent_messages(session, chat_id)
    if not should_extract_memories(recent):
        return False

    from services.llm_workflow import build_llm_workflow

    lines = build_extraction_messages(recent)
    if not lines:
        return False

    prompt = EXTRACTION_PROMPT.format(messages="\n".join(lines))
    workflow, metadata = build_llm_workflow(
        messages=[{"role": "user", "content": prompt}],
        type_="memory_extraction",
        chat_id=chat_id,
        character_id=character_id,
        workspace="chat",
        source="auto_memory",
        # Routed by `applyStreamUpdate` to the streaming store, which renders any
        # job with a `chat_id` as a character reply bubble — so an extraction
        # appeared as a second "X is thinking…" under the reply it was derived
        # from. Same mechanism that already suppresses a swipe, extended to
        # background work generally.
        background=True,
    )

    try:
        job = await job_service.create_job(task_type="llm", workflow=workflow, metadata=metadata)
        from services.job_queue import queue_manager
        await queue_manager.enqueue(job.id, task_type="llm")
        logger.info("memory_extraction_enqueued", chat_id=chat_id, job_id=job.id)
        return True
    except Exception as exc:
        logger.warning("memory_extraction_enqueue_failed", chat_id=chat_id, error=str(exc))
        return False


def parse_extraction_result(text: str) -> list[str]:
    """Parse the LLM's JSON array output into a list of memory strings."""
    if not text:
        return []
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(m).strip() for m in parsed if str(m).strip()]
    except json.JSONDecodeError:
        pass
    return []


def _normalize_memory_text(text: str) -> str:
    """Case- and whitespace-insensitive form of a memory, for exact dedup.

    The extractor is an LLM, so the same fact comes back with different casing
    and line breaks between runs. Normalising both is what makes exact matching
    actually catch regeneration instead of only catching byte-identical output.
    """
    return " ".join(str(text or "").split()).strip().casefold()


def _existing_normalized_contents(session: Session, character_id: str) -> set[str]:
    """Normalised content of every memory the character already has.

    `content` is a Text column with no index, so this is a sequential scan of
    one character's memories. That is acceptable because it replaces an embedding
    forward pass per candidate plus a pgvector query per candidate, and a
    character has hundreds of memories, not millions. An index on a normalised
    expression would need a migration and would only pay off at a scale this
    table is not at.
    """
    rows = session.exec(
        select(CharacterMemory.content).where(
            CharacterMemory.character_id == character_id
        )
    ).all()
    return {_normalize_memory_text(c) for c in rows if c}


def _near_duplicate_ids(
    session: Session, character_id: str, embedding: list[float]
) -> set[str]:
    """IDs of existing memories within `MEMORY_DEDUP_MAX_DISTANCE` of `embedding`.

    Postgres only: the column is a `Vector(384)`, so on SQLite the query raises
    and the caller falls back to exact matching alone. That is fine — the exact
    pass is what handles the dominant regeneration case, and the embedding pass
    only catches light rewording.
    """
    try:
        rows = session.exec(
            select(CharacterMemory.id, CharacterMemory.embedding.cosine_distance(embedding))
            .where(
                CharacterMemory.character_id == character_id,
                CharacterMemory.embedding.is_not(None),
            )
            .where(
                CharacterMemory.embedding.cosine_distance(embedding)
                < MEMORY_DEDUP_MAX_DISTANCE
            )
            .limit(5)
        ).all()
    except Exception as exc:  # pragma: no cover - pgvector edge cases, or SQLite
        logger.warning("memory_dedup_vector_query_failed", error=str(exc))
        return set()
    return {row[0] for row in rows if row[1] is not None}


def create_memories_from_extraction(session: Session, character_id: str, memories: list[str]) -> int:
    """Persist extracted memories as CharacterMemory rows with embeddings.

    An embedding failure is recorded, not swallowed. It used to be a bare
    `except Exception: pass`, which committed the row with `embedding = NULL`
    and no trace: `POST /api/v2/memories/search/semantic` runs a pgvector cosine
    search that can never match NULL, so a memory written while the embedding
    model was unloaded or OOM-ing was invisible to semantic recall for the rest
    of its life with nothing anywhere saying why.

    On failure the row is still written — the memory itself is the valuable part
    and it stays visible in the keyword/list paths — and it is tagged
    ``embedding-pending`` so the gap is greppable
    (``tags @> '["embedding-pending"]'``) and re-drivable by a reindex, which
    selects on ``embedding IS NULL``. A dedicated ``embedding_error`` column
    would be better than a tag; that needs an entity column plus a migration and
    is outside this module's scope.
    """
    if not memories:
        return 0

    from services.embedding_service import get_embedding_service
    emb_svc = get_embedding_service()

    # Drop anything the character already has, BEFORE paying for embeddings.
    #
    # There was no dedup at all, and the extraction hook fires for more than real
    # replies: `generate_swipe` and `regenerate_reply` both default to
    # `type_="chat_reply"`, and the idle simulator fires one for a turn the user
    # never wrote. `should_extract_memories` counts only USER messages, so a
    # swipe leaves the count unchanged and re-opens the gate. Regenerating a reply
    # therefore re-ran extraction over a near-identical 20-message window and
    # inserted a second copy of the same 1-5 memories, permanently.
    #
    # That is not just table bloat. Duplicates are mutual nearest neighbours, so
    # a fixed top-N retrieval returned the same copies for *every* query — the
    # memory store's effective capacity was a handful of entries no matter how
    # many turns had passed.
    #
    # Two passes, cheapest first: an exact normalised-content match catches the
    # common regeneration case with no vector maths at all, and the embedding
    # comparison only runs on what survives.
    existing_contents = _existing_normalized_contents(session, character_id)
    candidates = [m for m in memories if _normalize_memory_text(m) not in existing_contents]
    # Also dedup within this batch: the extractor can return the same fact twice.
    seen_in_batch: set[str] = set()
    deduped: list[str] = []
    for content in candidates:
        key = _normalize_memory_text(content)
        if key in seen_in_batch:
            continue
        seen_in_batch.add(key)
        deduped.append(content)

    duplicate_count = len(memories) - len(deduped)
    if duplicate_count:
        logger.info(
            "memory_extraction_duplicates_dropped",
            character_id=character_id,
            dropped=duplicate_count,
            kept=len(deduped),
        )
    if not deduped:
        return 0
    memories = deduped

    # One batched forward pass, not one per memory. The batched API already
    # exists and `rag_pipeline` already uses it; the per-item loop made this the
    # only embedding call site in the app that did N forward passes for N
    # memories, on a caller that runs on the event loop.
    #
    # A batch failure falls back to per-item so one un-embeddable memory does not
    # cost the other four their vectors — the same shape `rag_pipeline` uses, and
    # the same reason the docstring above cares about NULL vectors.
    # `errors` is kept per index so a NULL vector is still attributable to a
    # specific memory and a specific reason in the log.
    embeddings: list[list[float] | None] = [None] * len(memories)
    errors: list[Exception | None] = [None] * len(memories)
    try:
        batch = emb_svc.generate_embeddings(list(memories))
        if len(batch) == len(memories):
            embeddings = list(batch)
        else:
            raise ValueError(
                f"generate_embeddings returned {len(batch)} vectors for "
                f"{len(memories)} memories"
            )
    except Exception as exc:
        logger.warning(
            "memory_extraction_embedding_batch_failed",
            character_id=character_id,
            count=len(memories),
            error=str(exc),
        )
        for index, content in enumerate(memories):
            try:
                embeddings[index] = emb_svc.generate_embedding(content)
                errors[index] = None
            except Exception as item_exc:
                errors[index] = item_exc

    created = 0
    embedding_failures = 0
    near_duplicates = 0
    for content, embedding, error in zip(memories, embeddings, errors, strict=True):
        # Second dedup pass, now that vectors exist: the extractor can restate
        # something the character has under slightly different wording, which the
        # normalised exact match cannot see. Skipped when this memory has no
        # vector (it failed to embed), and when the store is SQLite.
        if embedding is not None:
            if _near_duplicate_ids(session, character_id, embedding):
                near_duplicates += 1
                logger.info(
                    "memory_extraction_near_duplicate_dropped",
                    character_id=character_id,
                    content_preview=content[:60],
                )
                continue
        now = datetime.now(timezone.utc)
        mem = CharacterMemory(
            character_id=character_id,
            content=content,
            tags=["auto-extracted"],
            importance=5,
            created_at=now,
            updated_at=now,
        )
        if embedding is None:
            embedding_failures += 1
            mem.tags = [*mem.tags, EMBEDDING_PENDING_TAG]
            logger.warning(
                "memory_extraction_embedding_failed",
                character_id=character_id,
                content_preview=content[:60],
                error=str(error) if error is not None else "no vector returned",
            )
        else:
            mem.embedding = embedding
        session.add(mem)
        created += 1

    session.commit()
    logger.info(
        "memories_auto_created",
        character_id=character_id,
        count=created,
        exact_duplicates_dropped=duplicate_count,
        near_duplicates_dropped=near_duplicates,
        embedding_failures=embedding_failures,
    )
    return created
