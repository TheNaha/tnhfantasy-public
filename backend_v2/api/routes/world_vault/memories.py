from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session, select, func

from api.deps import get_session, get_character_memory_repo, get_character_repo
from infrastructure.repositories.character_memory_repo import CharacterMemoryRepository
from infrastructure.repositories.character_repo import CharacterRepository
from core.entities import Character, CharacterMemory
from core.exceptions import NotFoundError, ValidationError

router = APIRouter()


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
    character_id: str | None = None,
    session: Session = Depends(get_session), character_memory_repo: CharacterMemoryRepository = Depends(get_character_memory_repo), ):
    query = select(CharacterMemory).order_by(CharacterMemory.created_at.desc())
    if character_id is not None:
        query = query.where(CharacterMemory.character_id == character_id)
    return session.exec(query).all()


@router.post("/reindex")
def reindex_memories(session: Session = Depends(get_session)):
    """Backfill missing embeddings for all stored memories (semantic-search index)."""
    from services.embedding_service import get_embedding_service

    emb_svc = get_embedding_service()
    memories = session.exec(select(CharacterMemory).where(CharacterMemory.embedding.is_(None))).all()
    updated = 0
    for mem in memories:
        try:
            mem.embedding = emb_svc.generate_embedding(mem.content)
            mem.updated_at = datetime.now(timezone.utc)
            session.add(mem)
            updated += 1
        except Exception:
            continue
    session.commit()
    return {"reindexed": updated, "total_missing": len(memories)}


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
    except Exception:
        pass  # Embedding is optional; semantic search will skip it

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
    """Semantic search over a character's memories using pgvector."""
    character = session.get(Character, character_id)
    if not character:
        raise NotFoundError("Character", character_id)

    # SQLite fallback: keyword matching on content (no embedding needed)
    if not (session.bind and session.bind.dialect.name == "postgresql"):
        stmt = (
            select(CharacterMemory)
            .where(CharacterMemory.character_id == character_id)
            .where(func.lower(CharacterMemory.content).like(f"%{query.lower()}%"))
            .limit(limit)
        )
        results = session.exec(stmt).all()
        return results

    # PostgreSQL: use pgvector cosine distance for semantic search
    from services.embedding_service import get_embedding_service
    try:
        emb_svc = get_embedding_service()
        q_vec = emb_svc.generate_embedding(query)
    except Exception:
        raise ValidationError("Could not generate embedding for search query")

    stmt = (
        select(CharacterMemory)
        .where(CharacterMemory.character_id == character_id)
        .where(CharacterMemory.embedding.is_not(None))
        .order_by(CharacterMemory.embedding.cosine_distance(q_vec))
        .limit(limit)
    )

    results = session.exec(stmt).all()
    return results


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
