"""Canonical semantic retrieval for the World Vault.

All pgvector/keyword retrieval flows through this module so the previous
inline copies (context_builder sections, orchestrator recall_memory tool,
memories + lorebooks routes) cannot drift apart. Repositories may still
exist for CRUD, but search semantics live here.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlmodel import Session, func, select

from core.entities import CharacterMemory, LorebookEntry
from infrastructure.logging import get_logger

logger = get_logger("rag_pipeline")


def _is_postgres(session: Session) -> bool:
    bind = getattr(session, "bind", None)
    return bool(bind and getattr(bind, "dialect", None) and bind.dialect.name == "postgresql")


def _try_embedding(text: str) -> list[float] | None:
    """Generate a query embedding, returning None when the model is unavailable."""
    try:
        from services.embedding_service import get_embedding_service

        return get_embedding_service().generate_embedding(text)
    except Exception as exc:  # pragma: no cover - model-load failures are env-specific
        logger.warning("rag_embedding_query_failed", error=str(exc))
        return None


def rag_enabled() -> bool:
    """Whether semantic retrieval is enabled (config `ai.ragEnabled`, default true)."""
    import config as app_config

    try:
        ai_block = app_config.get_config().get("ai") or {}
    except Exception:  # pragma: no cover - config read failures default to enabled
        return True
    return bool(ai_block.get("ragEnabled", True))


def search_memories(
    session: Session,
    character_id: str,
    query: str = "",
    limit: int = 10,
    *,
    touch_last_accessed: bool = False,
    q_vec: list[float] | None = None,
    q_vec_computed: bool = False,
) -> list[CharacterMemory]:
    """Search a character's memories semantically (pgvector) with a keyword fallback.

    - Blank query: most-recent memories (last_accessed_at, importance, created_at).
    - PostgreSQL: cosine-distance ranking over embedded memories.
    - Otherwise (SQLite, RAG disabled, or embedding model unavailable): ILIKE
      content match, or recency order when there is no query.
    - touch_last_accessed: stamps retrieved memories (used by the recall_memory agent tool).
    - q_vec: a precomputed query embedding. Pass it (with
      ``q_vec_computed=True``) from an async caller that has already run
      ``_try_embedding`` in a thread; see ``search_memories_async``.

    Turning RAG off does NOT remove retrieval. It removes only the *semantic*
    step: without an embedding the function falls through to its keyword /
    recency path, which is what the settings UI promises the user when it says
    context "falls back to recent/recency-based retrieval only". Returning []
    here would have made the control mean "no memory at all", and the prompt
    would silently lose the character's history.
    """
    rag_on = rag_enabled()
    query = (query or "").strip()
    if not q_vec_computed:
        q_vec = _try_embedding(query) if (rag_on and query and _is_postgres(session)) else None
    elif q_vec is None and rag_on and query and _is_postgres(session):
        # The caller computed it off-thread and got nothing (model unavailable).
        # Fall through to the keyword path exactly as the sync branch would.
        pass
    if not rag_on and query:
        logger.debug("rag_disabled_keyword_fallback", character_id=character_id)

    if q_vec:
        stmt = (
            select(CharacterMemory)
            .where(
                CharacterMemory.character_id == character_id,
                CharacterMemory.embedding.is_not(None),
            )
            .order_by(CharacterMemory.embedding.cosine_distance(q_vec))
            .limit(limit)
        )
    else:
        stmt = select(CharacterMemory).where(CharacterMemory.character_id == character_id)
        if query:
            stmt = stmt.where(func.lower(CharacterMemory.content).like(f"%{query.lower()}%"))
        else:
            stmt = stmt.order_by(
                CharacterMemory.last_accessed_at.desc(),
                CharacterMemory.importance.desc(),
                CharacterMemory.created_at.desc(),
            )
        stmt = stmt.limit(limit)

    memories = list(session.exec(stmt).all())

    if touch_last_accessed and memories:
        now = datetime.now(timezone.utc)
        for mem in memories:
            mem.last_accessed_at = now
        session.add_all(memories)
        session.commit()

    return memories


async def search_memories_async(
    session: Session,
    character_id: str,
    query: str = "",
    limit: int = 10,
    *,
    touch_last_accessed: bool = False,
) -> list[CharacterMemory]:
    """`search_memories` with the embedding pass moved off the event loop.

    The model forward is the expensive part (seconds on first call); the query
    itself is a bounded, indexed lookup and is left alone. Without this split,
    every `recall_memory` agent tool call blocked the whole event loop for the
    duration of a synchronous sentence-transformers pass.
    """
    rag_on = rag_enabled()
    query = (query or "").strip()
    q_vec = None
    if rag_on and query and _is_postgres(session):
        q_vec = await asyncio.to_thread(_try_embedding, query)
    return search_memories(
        session,
        character_id,
        query,
        limit,
        touch_last_accessed=touch_last_accessed,
        q_vec=q_vec,
        q_vec_computed=True,
    )


def search_lorebook_entries(
    session: Session,
    lorebook_ids: list[str],
    query: str = "",
    limit: int = 5,
) -> list[LorebookEntry]:
    """Retrieve the top-``limit`` most relevant entries across lorebooks.

    Per lorebook (in ``lorebook_ids`` order):
    - Blank query → most recently created entries.
    - PostgreSQL + embeddings → cosine-distance top-K.
    - Keyword fallback (SQLite, no/missing embeddings): entries without keys are
      always included, entries with keys must match a key substring; if nothing
      matches, the first N entries are returned so context never goes empty.

    Returns a flat, deduplicated list ordered by lorebook order then rank.

    Turning RAG off removes only the semantic step, not retrieval: the
    keyword / recency fallback below still runs, so an activated lorebook keeps
    contributing to the prompt. The settings UI describes exactly this, so
    returning [] here would have made lorebooks silently inert.
    """
    rag_on = rag_enabled()
    query = (query or "").strip()
    if not lorebook_ids:
        return []

    q_vec = _try_embedding(query) if (rag_on and query and _is_postgres(session)) else None

    results: list[LorebookEntry] = []
    global_limit = max(limit * 3, limit)
    seen: set[str] = set()

    for lb_id in lorebook_ids:
        if len(results) >= global_limit:
            break
        if q_vec:
            try:
                top = session.exec(
                    select(LorebookEntry)
                    .where(
                        LorebookEntry.lorebook_id == lb_id,
                        LorebookEntry.embedding.is_not(None),
                    )
                    .order_by(LorebookEntry.embedding.cosine_distance(q_vec))
                    .limit(limit)
                ).all()
                if top:
                    for e in top:
                        if e.id not in seen:
                            seen.add(e.id)
                            results.append(e)
                    continue
            except Exception as exc:  # pragma: no cover - pgvector edge cases
                logger.warning(
                    "lorebook_semantic_fallback", lorebook_id=lb_id, error=str(exc)
                )

        # Keyword-fallback path. Cap the rows pulled out of Postgres instead of
        # materialising every entry in the lorebook and slicing in Python: this
        # runs on every chat message, suggest, impersonate and story continue.
        # The cap is what the Python scan_cap would have applied anyway, so the
        # result set is unchanged while the transfer is bounded.
        scan_cap = max(limit, 50)
        entries = list(
            session.exec(
                select(LorebookEntry)
                .where(LorebookEntry.lorebook_id == lb_id)
                .order_by(LorebookEntry.created_at.desc())
                .limit(scan_cap)
            ).all()
        )
        if not entries:
            continue

        if not query:
            for e in entries[:limit]:
                if e.id not in seen:
                    seen.add(e.id)
                    results.append(e)
            continue

        query_lower = query.lower()
        matched: list[LorebookEntry] = []
        for e in entries[:scan_cap]:
            if not e.keys:
                if e.id not in seen:
                    seen.add(e.id)
                    matched.append(e)
                continue
            if any(k.lower() in query_lower for k in e.keys):
                if e.id not in seen:
                    seen.add(e.id)
                    matched.append(e)
                if len(matched) >= limit:
                    break

        if not matched:
            for e in entries[:limit]:
                if e.id not in seen:
                    seen.add(e.id)
                    matched.append(e)

        results.extend(matched)

    return results[:global_limit]


# Lorebook reindex bounding. Same shape as the memories backfill
# (api/routes/world_vault/memories.py:34-36): one call embeds at most `limit`
# rows and commits every `batch_size` rows, so no single request can run
# unbounded local inference. The lorebook reindex is the one the UI actually
# calls (POST /api/v2/lorebooks/{id}/reindex) and it had neither bound nor
# batching, so a lorebook imported from SillyTavern with a few thousand entries
# held the request open while running one model call per entry, serially.
LOREBOOK_REINDEX_DEFAULT_LIMIT = 200
LOREBOOK_REINDEX_MAX_LIMIT = 1000
LOREBOOK_REINDEX_BATCH_SIZE = 32


def backfill_lorebook_embeddings(
    session: Session,
    lorebook_id: str | None = None,
    *,
    limit: int = LOREBOOK_REINDEX_DEFAULT_LIMIT,
    batch_size: int = LOREBOOK_REINDEX_BATCH_SIZE,
) -> int:
    """Generate embeddings for lorebook entries that lack them.

    Bounded and batched: at most `limit` rows are selected, the model's batch
    encode is used per `batch_size` chunk, and each chunk is committed on its
    own so a failure part-way through does not throw away the work already done.
    A row whose embedding fails is left NULL, so the next call retries it —
    same contract as the memories backfill.

    Returns the number of entries newly embedded. Entries beyond `limit` are
    left for a subsequent call.
    """
    from services.embedding_service import get_embedding_service

    limit = max(1, min(limit, LOREBOOK_REINDEX_MAX_LIMIT))
    batch_size = max(1, batch_size)

    stmt = (
        select(LorebookEntry)
        .where(LorebookEntry.embedding.is_(None))
        .order_by(LorebookEntry.created_at)
        .limit(limit)
    )
    if lorebook_id is not None:
        stmt = stmt.where(LorebookEntry.lorebook_id == lorebook_id)
    entries = list(session.exec(stmt).all())
    if not entries:
        return 0

    emb_svc = get_embedding_service()
    updated = 0
    for start in range(0, len(entries), batch_size):
        chunk = entries[start:start + batch_size]
        texts = [
            f"{' '.join(entry.keys or [])} {entry.content or ''}".strip()
            for entry in chunk
        ]
        vectors: list[list[float]] | None = None
        try:
            candidates = emb_svc.generate_embeddings(texts)
            if candidates is not None and len(candidates) == len(chunk):
                vectors = candidates
        except Exception as exc:
            logger.warning(
                "lorebook_reindex_batch_failed", batch_size=len(chunk), error=str(exc)
            )
            vectors = None

        if vectors is None:
            # Batch encode failed (model unloaded, OOM). Fall back per row so one
            # unreadable entry cannot discard the rest of the chunk — and so a
            # batch-level failure is not indistinguishable from 32 row failures.
            for entry, text in zip(chunk, texts, strict=True):
                try:
                    entry.embedding = emb_svc.generate_embedding(text)
                    session.add(entry)
                    updated += 1
                except Exception as exc:
                    logger.warning(
                        "lorebook_entry_embedding_failed", entry_id=entry.id, error=str(exc)
                    )
        else:
            for entry, vector in zip(chunk, vectors, strict=True):
                entry.embedding = vector
                session.add(entry)
                updated += 1

        try:
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.warning(
                "lorebook_reindex_commit_failed", batch_size=len(chunk), error=str(exc)
            )
            continue

    if len(entries) >= limit:
        logger.info(
            "lorebook_reindex_limit_reached",
            lorebook_id=lorebook_id,
            embedded=updated,
            limit=limit,
        )
    return updated