from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session, select, func

from api.deps import get_session
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
    session: Session = Depends(get_session),
):
    query = select(CharacterMemory).order_by(CharacterMemory.created_at.desc())
    if character_id is not None:
        query = query.where(CharacterMemory.character_id == character_id)
    return session.exec(query).all()


@router.post("")
def create_memory(memory_in: MemoryCreate, session: Session = Depends(get_session)):
    character = session.get(Character, memory_in.character_id)
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
def get_memory(memory_id: str, session: Session = Depends(get_session)):
    mem = session.get(CharacterMemory, memory_id)
    if not mem:
        raise NotFoundError("CharacterMemory", memory_id)
    return mem


@router.put("/{memory_id}")
def update_memory(memory_id: str, update_data: MemoryUpdate, session: Session = Depends(get_session)):
    mem = session.get(CharacterMemory, memory_id)
    if not mem:
        raise NotFoundError("CharacterMemory", memory_id)

    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(mem, key, value)

    mem.updated_at = datetime.now(timezone.utc)
    session.add(mem)
    session.commit()
    session.refresh(mem)
    return mem


@router.delete("/{memory_id}")
def delete_memory(memory_id: str, session: Session = Depends(get_session)):
    mem = session.get(CharacterMemory, memory_id)
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
        .order_by(func.cosine_distance(CharacterMemory.embedding, q_vec))
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
