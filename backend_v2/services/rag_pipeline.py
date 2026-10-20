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
from core.sql_search import LIKE_ESCAPE_CHAR, like_contains
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


# Fallback when the config read fails. Matches the shipped default in
# `config.py` DEFAULT_CONFIG, so an unreadable config behaves like a default one
# rather than silently disabling retrieval or silently enabling noise.
_RAG_MAX_DISTANCE_FALLBACK = 0.6


def rag_max_distance() -> float:
    """Cosine-distance cutoff for semantic retrieval (config `ai.ragMaxDistance`).

    pgvector's `cosine_distance` is 0.0 for identical vectors, 1.0 for
    orthogonal ones and 2.0 for opposite ones. Both searches below used to
    `ORDER BY cosine_distance LIMIT n` with no cutoff at all, so the top-N were
    injected into the prompt unconditionally — including the nearest neighbour
    when it was semantically unrelated. That is pure prompt-budget waste and an
    active distractor.

    It also compounded a separate defect: `memory_extraction` inserted memories
    with no dedup, so near-identical copies are always mutual nearest
    neighbours, which means a fixed top-N retrieved the same duplicates for every
    query no matter what the user was talking about.

    Returning fewer rows than `limit` is the intended outcome when nothing is
    close. Injecting unrelated world info into a roleplay is worse than
    injecting none. Set `ai.ragMaxDistance` to 2.0 to restore unconditional
    top-N.
    """
    import config as app_config

    try:
        ai_block = app_config.get_config().get("ai") or {}
    except Exception:  # pragma: no cover - config read failures
        return _RAG_MAX_DISTANCE_FALLBACK
    try:
        value = float(ai_block.get("ragMaxDistance", _RAG_MAX_DISTANCE_FALLBACK))
    except (TypeError, ValueError):
        return _RAG_MAX_DISTANCE_FALLBACK
    # Clamp rather than reject: a config that somehow holds a nonsense value
    # should not make retrieval throw on every turn.
    return max(0.0, min(2.0, value))


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
    # When the caller computed the vector off-thread and got nothing (the model
    # is unavailable), `q_vec` stays None and the `if q_vec:` branch below takes
    # the keyword path exactly as the sync branch does. That was previously an
    # `elif` with an empty body, which read as live handling and would have
    # silently done nothing if edited.
    if not rag_on and query:
        logger.debug("rag_disabled_keyword_fallback", character_id=character_id)

    if q_vec:
        # `.where(distance < cutoff)` is applied in SQL rather than by fetching
        # the top-N and filtering in Python, so the LIMIT means "the N nearest
        # that are actually relevant" instead of "the N nearest, most of which
        # are thrown away".
        stmt = (
            select(CharacterMemory)
            .where(
                CharacterMemory.character_id == character_id,
                CharacterMemory.embedding.is_not(None),
                CharacterMemory.embedding.cosine_distance(q_vec) < rag_max_distance(),
            )
            .order_by(CharacterMemory.embedding.cosine_distance(q_vec))
            .limit(limit)
        )
    else:
        stmt = select(CharacterMemory).where(CharacterMemory.character_id == character_id)
        if query:
            stmt = stmt.where(
                func.lower(CharacterMemory.content).like(
                    like_contains(query.lower()), escape=LIKE_ESCAPE_CHAR
                )
            )
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
    q_vec: list[float] | None = None,
    q_vec_computed: bool = False,
) -> list[LorebookEntry]:
    """Retrieve the top-``limit`` most relevant entries across lorebooks.

    Per lorebook (in ``lorebook_ids`` order):
    - Blank query → most recently created entries.
    - PostgreSQL + embeddings → cosine-distance top-K.
    - Keyword fallback (SQLite, no/missing embeddings): entries without keys are
      always included, entries with keys must match a key substring; if nothing
      matches, the first N entries are returned so context never goes empty.

    Returns a flat, deduplicated list ordered by lorebook order then rank, and
    NEVER more than `limit` entries. The limit is a hard ceiling on the whole
    call, not a per-lorebook allowance: every returned entry is injected verbatim
    into the paid system prompt by `context_builder`, so `limit` entries is the
    budget the caller asked for. It used to be `limit * 3` across the call and up
    to `2 * limit` from a single lorebook.

    Turning RAG off removes only the semantic step, not retrieval: the
    keyword / recency fallback below still runs, so an activated lorebook keeps
    contributing to the prompt. The settings UI describes exactly this, so
    returning [] here would have made lorebooks silently inert.
    """
    rag_on = rag_enabled()
    query = (query or "").strip()
    if not lorebook_ids:
        return []

    if not q_vec_computed:
        q_vec = _try_embedding(query) if (rag_on and query and _is_postgres(session)) else None

    results: list[LorebookEntry] = []
    seen: set[str] = set()

    for lb_id in lorebook_ids:
        if len(results) >= limit:
            break
        if q_vec:
            try:
                top = session.exec(
                    select(LorebookEntry)
                    .where(
                        LorebookEntry.lorebook_id == lb_id,
                        LorebookEntry.embedding.is_not(None),
                        # Same cutoff as the memory search, and for the same
                        # reason. Without it every story turn and every chat turn
                        # received `[World Information]` holding the N nearest
                        # entries whether or not they had anything to do with the
                        # scene.
                        LorebookEntry.embedding.cosine_distance(q_vec) < rag_max_distance(),
                    )
                    .order_by(LorebookEntry.embedding.cosine_distance(q_vec))
                    .limit(limit)
                ).all()
                if top:
                    for e in top:
                        if e.id not in seen and len(results) < limit:
                            seen.add(e.id)
                            results.append(e)
                    # Always-on lore is not a *result* of relevance, so it must
                    # not be filtered by the query that produced these rows.
                    #
                    # This branch returned only rows carrying an embedding, and
                    # a keyless ("constant") entry is invisible to it whenever
                    # the backfill has not reached it yet — a fresh SillyTavern
                    # import, the first turns after creating a lorebook, or any
                    # deployment where the embedding model never loaded. Those
                    # entries then simply did not appear, while the keyword path
                    # below and `context_builder._load_constant_lorebook_entries`
                    # both treat them as always-on. The result was a chat that
                    # lost the cast's always-on facts precisely when the rest of
                    # the context was most relevant.
                    #
                    # Same bounded helper the keyword path uses, so the budget
                    # is still `limit` across the whole call.
                    _append_keyless(session, lb_id, seen, results, limit, len(results))
                    continue
                # `top` is empty but we had a query vector, so embeddings EXIST
                # for this lorebook and none of them is within
                # `rag_max_distance()`. That is a real answer: nothing here is
                # relevant to the current scene.
                #
                # Falling through to the keyword path here would hand back up to
                # `limit` arbitrary entries anyway, which is the precise
                # behaviour the cutoff exists to stop — and it would do so
                # silently, because the caller cannot tell "5 relevant entries"
                # from "5 arbitrary ones". Only reach the keyword scan when there
                # was no vector to begin with (RAG off, SQLite, or the embedding
                # model unavailable); the `except` below keeps that path too,
                # since a pgvector error also means no vector.
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
                if e.id not in seen and len(results) < limit:
                    seen.add(e.id)
                    results.append(e)
            _append_keyless(session, lb_id, seen, results, limit, len(results))
            continue

        matched: list[LorebookEntry] = []
        for e in entries[:scan_cap]:
            # Keyless entries are "always on" — `context_builder` injects them
            # unconditionally — so they match whatever the query is. A DISABLED
            # entry never matches, and a `selective` entry needs a secondary
            # key as well. `entry_matches_keys` is the single definition of
            # those rules.
            if entry_matches_keys(e, query):
                if e.id not in seen and len(results) + len(matched) < limit:
                    seen.add(e.id)
                    matched.append(e)
                # The break belongs HERE, not only in the keyed branch below it.
                # It used to be inside the keyed arm, so a lorebook with many
                # keyless entries appended every one of them and blew through the
                # caller's `limit` by 10x.
                if len(results) + len(matched) >= limit:
                    break

        if not matched:
            for e in entries[:limit]:
                if e.id not in seen and len(results) + len(matched) < limit:
                    seen.add(e.id)
                    matched.append(e)

        results.extend(matched)
        # Keyless entries are always-on, and the scan above only sees the newest
        # `scan_cap` rows — so an always-on fact written early in a SillyTavern
        # import was invisible forever. That is the worst direction for a
        # "constant" entry: it is supposed to always apply. Fetch them oldest
        # first so age does not decide visibility.
        _append_keyless(session, lb_id, seen, results, limit, len(results))

    return results[:limit]


def entry_is_enabled(entry: LorebookEntry) -> bool:
    """Whether this entry is allowed to activate at all.

    A SillyTavern `character_book` entry can carry `enabled: false`, and the
    flag was DROPPED on import — there was no column to hold it — so a
    disabled entry activated anyway.
    """
    return bool(getattr(entry, "enabled", True))


def entry_matches_keys(entry: LorebookEntry, query: str) -> bool:
    """Does this entry's key set match the query?

    * A DISABLED entry never matches.
    * A KEYLESS entry is "always on". This is the vault's convention, and it
      is how a SillyTavern `constant: true` entry is represented: ST's
      `constant` flag was dropped on import, so the entry was made keyless
      instead — and this vault's always-on test is "no keys".
    * A keyed entry matches when one of its keys appears in the query. With
      `secondary_keys` set, a SECONDARY key must match too, which is
      SillyTavern's `selective` matching — its `secondary_keys` were dropped
      on import along with the flag.
    """
    if not entry_is_enabled(entry):
        return False

    keys = [k for k in (entry.keys or []) if k]
    if not keys:
        return True

    case_sensitive = bool(getattr(entry, "case_sensitive", False))
    haystack = query if case_sensitive else query.lower()

    def _hits(words: list[str]) -> bool:
        return any((w if case_sensitive else w.lower()) in haystack for w in words)

    if not _hits(keys):
        return False

    secondary = [k for k in (getattr(entry, "secondary_keys", None) or []) if k]
    if secondary and not _hits(secondary):
        return False
    return True


def _append_keyless(
    session: Session,
    lorebook_id: str,
    seen: set[str],
    results: list[LorebookEntry],
    limit: int,
    already: int,
) -> None:
    """Append keyless ("always on") entries oldest-first, skipping `seen`.

    A second, ascending query rather than a bigger `scan_cap`: raising the cap
    would trade a correctness bug for a memory bug on a path that runs on every
    chat message, suggest, impersonate and story continue. The rows are bounded by
    `limit` regardless.

    `already` is how many entries `results` already holds, across every lorebook
    processed so far. The budget left is `limit - already`, and nothing else: the
    old expression was `limit - (already - len(seen))`, but every append adds the
    entry to both lists, so `len(seen) == len(results) == already`, the subtraction
    cancelled, and `remaining` came out as the FULL `limit`. A lorebook with both
    keyword matches and many keyless entries therefore returned up to `2 * limit`
    from this one call, and `context_builder` injects every returned entry verbatim
    into a paid system prompt.

    `keys == []` renders as `keys = %(keys_1)s::JSONB` on Postgres and
    `keys = ?` on SQLite — the same bound-parameter comparison, so no dialect
    branch is needed. The `not entry.keys` guard afterwards keeps this honest on
    any backend that stores the empty list differently: a row that slips through
    the predicate but is not actually keyless is skipped rather than injected.
    """
    remaining = max(0, limit - already)
    if remaining <= 0:
        return
    try:
        keyless = session.exec(
            select(LorebookEntry)
            .where(
                LorebookEntry.lorebook_id == lorebook_id,
                LorebookEntry.keys == [],
            )
            .order_by(LorebookEntry.created_at.asc())
            .limit(remaining)
        ).all()
    except Exception as exc:  # pragma: no cover - dialect differences
        logger.debug("keyless_entry_query_skipped", lorebook_id=lorebook_id, error=str(exc))
        return
    for entry in keyless:
        # A DISABLED entry never activates, even when it is keyless. The
        # `enabled` flag was dropped on import, so a SillyTavern entry with
        # `enabled: false` was always-on here.
        if not entry.keys and entry_is_enabled(entry) and entry.id not in seen:
            seen.add(entry.id)
            results.append(entry)


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