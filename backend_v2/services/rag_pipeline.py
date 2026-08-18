"""Canonical semantic retrieval for the World Vault.

All pgvector/keyword retrieval flows through this module so the previous
inline copies (context_builder sections, orchestrator recall_memory tool,
memories + lorebooks routes) cannot drift apart. Repositories may still
exist for CRUD, but search semantics live here.
"""

from __future__ import annotations

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


def search_memories(
    session: Session,
    character_id: str,
    query: str = "",
    limit: int = 10,
    *,
    touch_last_accessed: bool = False,
) -> list[CharacterMemory]:
    """Search a character's memories semantically (pgvector) with a keyword fallback.

    - Blank query: most-recent memories (last_accessed_at, importance, created_at).
    - PostgreSQL: cosine-distance ranking over embedded memories.
    - Otherwise (SQLite, or embedding model unavailable): ILIKE content match.
    - touch_last_accessed: stamps retrieved memories (used by the recall_memory agent tool).
    """
    query = (query or "").strip()
    q_vec = _try_embedding(query) if query and _is_postgres(session) else None

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
    """
    query = (query or "").strip()
    if not lorebook_ids:
        return []

    q_vec = _try_embedding(query) if query and _is_postgres(session) else None

    results: list[LorebookEntry] = []
    seen: set[str] = set()

    for lb_id in lorebook_ids:
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

        entries = list(
            session.exec(
                select(LorebookEntry)
                .where(LorebookEntry.lorebook_id == lb_id)
                .order_by(LorebookEntry.created_at.desc())
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
        scan_cap = max(limit, 50)
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

    return results


def backfill_lorebook_embeddings(session: Session, lorebook_id: str | None = None) -> int:
    """Generate embeddings for lorebook entries that lack them.

    Returns the number of entries newly embedded.
    """
    from services.embedding_service import get_embedding_service

    stmt = select(LorebookEntry).where(LorebookEntry.embedding.is_(None))
    if lorebook_id is not None:
        stmt = stmt.where(LorebookEntry.lorebook_id == lorebook_id)
    entries = list(session.exec(stmt).all())

    emb_svc = get_embedding_service()
    updated = 0
    for entry in entries:
        try:
            keys_text = " ".join(entry.keys or [])
            text_to_embed = f"{keys_text} {entry.content or ''}".strip()
            entry.embedding = emb_svc.generate_embedding(text_to_embed)
            session.add(entry)
            updated += 1
        except Exception as exc:
            logger.warning("lorebook_entry_embedding_failed", entry_id=entry.id, error=str(exc))
    if updated:
        session.commit()
    return updated