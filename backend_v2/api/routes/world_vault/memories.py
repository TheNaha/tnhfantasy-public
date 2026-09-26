from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from api.deps import get_session, get_character_memory_repo, get_character_repo
from infrastructure.logging import get_logger
from infrastructure.repositories.character_memory_repo import CharacterMemoryRepository
from infrastructure.repositories.character_repo import CharacterRepository
from core.entities import Character, CharacterMemory
from core.exceptions import NotFoundError

logger = get_logger("memories_route")
router = APIRouter()

# Row caps. `GET /api/v2/memories` was a bare `SELECT` over the whole
# character_memories table, so a large vault serialised every memory —
# content plus a 384-float vector each — into one response.
#
# The default (200) is deliberately larger than the per-character route's (50)
# below because this listing spans the whole vault, and the ceiling (500) keeps
# the worst-case body in the low tens of MB only if every row were pathological;
# real rows are a few hundred bytes of text.
MEMORY_PAGE_DEFAULT_LIMIT = 200
MEMORY_PAGE_MAX_LIMIT = 500

# Reindex bounds. The route embeds memories with a local sentence-transformer,
# so a single call over a vault with thousands of NULL-embedding rows held a
# request thread for minutes. One call now embeds at most `limit` rows and
# commits every MEMORY_REINDEX_BATCH_SIZE, so the caller drives it to
# completion by repeating until `has_more` is false.
MEMORY_REINDEX_DEFAULT_LIMIT = 200
MEMORY_REINDEX_MAX_LIMIT = 1000
MEMORY_REINDEX_BATCH_SIZE = 32


class MemoryCreate(BaseModel):
    character_id: str
    content: str
    tags: list[str] | None = None
    importance: int | None = 5


class MemoryUpdate(BaseModel):
    content: str | None = None
    tags: list[str] | None = None
    importance: int | None = None
    last_accessed_at: datetime | None = None


@router.get("")
def list_memories(
    response: Response,
    character_id: str | None = None,
    limit: int = Query(default=MEMORY_PAGE_DEFAULT_LIMIT, ge=1, le=MEMORY_PAGE_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session), character_memory_repo: CharacterMemoryRepository = Depends(get_character_memory_repo), ):
    """List memories, newest first, optionally scoped to one character.

    The body stays a bare JSON array (that is the documented shape and what
    callers parse today); truncation is advertised in the X-Total-Count /
    X-Has-More / X-Limit / X-Offset response headers, so a client can tell a
    partial page from the whole table.
    """
    query = select(CharacterMemory).order_by(CharacterMemory.created_at.desc())
    count_query = select(func.count()).select_from(CharacterMemory)
    if character_id is not None:
        query = query.where(CharacterMemory.character_id == character_id)
        count_query = count_query.where(CharacterMemory.character_id == character_id)

    total = session.exec(count_query).one()
    rows = session.exec(query.offset(offset).limit(limit)).all()

    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Limit"] = str(limit)
    response.headers["X-Offset"] = str(offset)
    response.headers["X-Has-More"] = "true" if offset + limit < total else "false"
    return rows


def _embed_batch(emb_svc, memories: list[CharacterMemory]) -> tuple[int, int]:
    """Embed one batch of memories, returning (succeeded, failed).

    Prefers the model's batch encode — one forward pass instead of N — and
    falls back to per-row on any batch-level failure, so a single unreadable
    content string cannot discard the other 31 rows of the batch. Rows are
    already session-persistent, so mutating them is enough to stage the write.
    """
    if not memories:
        return (0, 0)

    try:
        vectors = emb_svc.generate_embeddings([mem.content for mem in memories])
    except Exception as exc:
        logger.warning("memory_reindex_batch_failed", batch_size=len(memories), error=str(exc))
        vectors = None

    if vectors is not None and len(vectors) == len(memories):
        now = datetime.now(timezone.utc)
        for mem, vector in zip(memories, vectors, strict=True):
            mem.embedding = vector
            mem.updated_at = now
        return (len(memories), 0)

    succeeded = 0
    failed = 0
    for mem in memories:
        try:
            mem.embedding = emb_svc.generate_embedding(mem.content)
            mem.updated_at = datetime.now(timezone.utc)
            succeeded += 1
        except Exception as exc:
            # Embedding is optional; semantic search skips rows without one, so
            # a failed row stays NULL and the next call retries it.
            logger.warning("memory_reindex_failed", memory_id=mem.id, error=str(exc))
            failed += 1
    return (succeeded, failed)


@router.post("/reindex")
def reindex_memories(
    limit: int = Query(default=MEMORY_REINDEX_DEFAULT_LIMIT, ge=1, le=MEMORY_REINDEX_MAX_LIMIT),
    session: Session = Depends(get_session), ):
    """Backfill missing embeddings for stored memories (semantic-search index).

    Bounded and batched: one call embeds at most `limit` memories and commits
    every MEMORY_REINDEX_BATCH_SIZE rows, so no single request can run unbounded
    local inference. Call again while `has_more` is true.

    This route has no frontend consumer — the UI's reindex action is
    `POST /api/v2/lorebooks/{id}/reindex` (frontend_v2/src/hooks/useLorebooks.js)
    — but it is the only backfill path for memories written while the embedding
    model was unavailable, so it stays, bounded, for operators and scripts.

    `total_missing` is measured before the batch (how many rows were missing
    when the call started); `remaining` is measured after it, so `has_more` is
    a real "there is more work left" signal rather than arithmetic on failures.
    """
    from services.embedding_service import get_embedding_service

    emb_svc = get_embedding_service()

    missing = CharacterMemory.embedding.is_(None)
    total_missing = session.exec(
        select(func.count()).select_from(CharacterMemory).where(missing)
    ).one()

    batch = session.exec(
        select(CharacterMemory)
        .where(missing)
        .order_by(CharacterMemory.created_at)
        .limit(limit)
    ).all()

    reindexed = 0
    failed = 0
    for start in range(0, len(batch), MEMORY_REINDEX_BATCH_SIZE):
        chunk = batch[start:start + MEMORY_REINDEX_BATCH_SIZE]
        succeeded, chunk_failed = _embed_batch(emb_svc, list(chunk))
        try:
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.warning("memory_reindex_commit_failed", batch_size=len(chunk), error=str(exc))
            failed += len(chunk)
            continue
        reindexed += succeeded
        failed += chunk_failed

    remaining = session.exec(
        select(func.count()).select_from(CharacterMemory).where(missing)
    ).one()

    return {
        "reindexed": reindexed,
        "failed": failed,
        "total_missing": total_missing,
        "remaining": remaining,
        "limit": limit,
        "batch_size": MEMORY_REINDEX_BATCH_SIZE,
        "has_more": remaining > 0,
    }


@router.post("")
def create_memory(memory_in: MemoryCreate, session: Session = Depends(get_session), character_repo: CharacterRepository = Depends(get_character_repo), character_memory_repo: CharacterMemoryRepository = Depends(get_character_memory_repo)):
    character = character_repo.get(memory_in.character_id)
    if not character:
        raise NotFoundError("Character", memory_in.character_id)

    mem = CharacterMemory(
        character_id=memory_in.character_id,
        content=memory_in.content,
        tags=memory_in.tags or [],
        importance=memory_in.importance or 5,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    # Generate embedding via EmbeddingService
    from services.embedding_service import get_embedding_service
    try:
        emb_svc = get_embedding_service()
        embedding = emb_svc.generate_embedding(memory_in.content)
        mem.embedding = embedding
    except Exception as exc:
        logger.debug("memory_embedding_failed", memory_id=mem.id, error=str(exc))  # Embedding is optional; semantic search will skip it

    session.add(mem)
    session.commit()
    session.refresh(mem)
    return mem


@router.get("/{memory_id}")
def get_memory(memory_id: str, session: Session = Depends(get_session), character_memory_repo: CharacterMemoryRepository = Depends(get_character_memory_repo)):
    mem = character_memory_repo.get(memory_id)
    if not mem:
        raise NotFoundError("CharacterMemory", memory_id)
    return mem


@router.put("/{memory_id}")
def update_memory(memory_id: str, update_data: MemoryUpdate, session: Session = Depends(get_session), character_memory_repo: CharacterMemoryRepository = Depends(get_character_memory_repo)):
    mem = character_memory_repo.get(memory_id)
    if not mem:
        raise NotFoundError("CharacterMemory", memory_id)

    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(mem, key, value)

    if "content" in update_dict:
        # Content changed — regenerate the embedding so semantic search
        # never matches against stale vectors.
        try:
            from services.embedding_service import get_embedding_service

            emb_svc = get_embedding_service()
            mem.embedding = emb_svc.generate_embedding(mem.content)
        except Exception:
            mem.embedding = None

    mem.updated_at = datetime.now(timezone.utc)
    session.add(mem)
    session.commit()
    session.refresh(mem)
    return mem


@router.delete("/{memory_id}")
def delete_memory(memory_id: str, session: Session = Depends(get_session), character_memory_repo: CharacterMemoryRepository = Depends(get_character_memory_repo)):
    mem = character_memory_repo.get(memory_id)
    if not mem:
        raise NotFoundError("CharacterMemory", memory_id)
    session.delete(mem)
    session.commit()
    return {"message": "Memory deleted"}


@router.get("/search/semantic")
def search_memories(
    character_id: str = Query(...),
    query: str = Query(...),
    limit: int = Query(default=10, le=50),
    session: Session = Depends(get_session),
):
    """Semantic search over a character's memories (pgvector + keyword fallback)."""
    character = session.get(Character, character_id)
    if not character:
        raise NotFoundError("Character", character_id)

    from services.rag_pipeline import search_memories as rag_search_memories

    return rag_search_memories(session, character_id, query, limit=limit)


@router.get("/character/{character_id}")
def get_character_memories(
    character_id: str,
    limit: int = Query(default=50, le=200),
    session: Session = Depends(get_session),
):
    """Get recent memories for a character, sorted by last_accessed_at + importance."""
    character = session.get(Character, character_id)
    if not character:
        raise NotFoundError("Character", character_id)

    stmt = (
        select(CharacterMemory)
        .where(CharacterMemory.character_id == character_id)
        .order_by(
            CharacterMemory.last_accessed_at.desc().nullslast(),
            CharacterMemory.importance.desc(),
            CharacterMemory.created_at.desc(),
        )
        .limit(limit)
    )
    return session.exec(stmt).all()
