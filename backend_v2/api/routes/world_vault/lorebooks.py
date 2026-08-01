from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select
from typing import List, Optional, Any
from datetime import datetime, timezone

from api.deps import get_session, get_embedding_service
from core.entities import Lorebook, LorebookEntry
from services.embedding_service import EmbeddingService

router = APIRouter()


class LorebookUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class EntryUpdate(BaseModel):
    keys: Optional[List[str]] = None
    content: Optional[str] = None

@router.get("/", response_model=List[Lorebook])
def list_lorebooks(session: Session = Depends(get_session)):
    return session.exec(select(Lorebook).order_by(Lorebook.name)).all()

@router.post("/", response_model=Lorebook)
def create_lorebook(lorebook: Lorebook, session: Session = Depends(get_session)):
    lorebook.created_at = datetime.now(timezone.utc)
    lorebook.updated_at = lorebook.created_at
    session.add(lorebook)
    session.commit()
    session.refresh(lorebook)
    return lorebook

@router.get("/{lorebook_id}", response_model=Lorebook)
def get_lorebook(lorebook_id: str, session: Session = Depends(get_session)):
    lorebook = session.get(Lorebook, lorebook_id)
    if not lorebook:
        raise HTTPException(status_code=404, detail="Lorebook not found")
    return lorebook

@router.put("/{lorebook_id}", response_model=Lorebook)
def update_lorebook(lorebook_id: str, update_data: LorebookUpdate, session: Session = Depends(get_session)):
    lorebook = session.get(Lorebook, lorebook_id)
    if not lorebook:
        raise HTTPException(status_code=404, detail="Lorebook not found")
    
    update_dict = update_data.model_dump(exclude_unset=True)
    if "name" in update_dict:
        lorebook.name = update_dict["name"]
    if "description" in update_dict:
        lorebook.description = update_dict["description"]
        
    lorebook.updated_at = datetime.now(timezone.utc)
    session.add(lorebook)
    session.commit()
    session.refresh(lorebook)
    return lorebook

@router.delete("/{lorebook_id}")
def delete_lorebook(lorebook_id: str, session: Session = Depends(get_session)):
    lorebook = session.get(Lorebook, lorebook_id)
    if not lorebook:
        raise HTTPException(status_code=404, detail="Lorebook not found")
        
    entries = session.exec(select(LorebookEntry).where(LorebookEntry.lorebook_id == lorebook_id)).all()
    for entry in entries:
        session.delete(entry)
        
    session.delete(lorebook)
    session.commit()
    return {"message": "Lorebook deleted"}

# ============================================================================
# SEARCH ENDPOINT
# ============================================================================

@router.get("/{lorebook_id}/search", response_model=List[LorebookEntry])
def search_entries(
    lorebook_id: str, 
    q: str, 
    limit: int = 5,
    session: Session = Depends(get_session),
    embedding_service: EmbeddingService = Depends(get_embedding_service)
):
    """Semantic search for lorebook entries based on a query string."""
    lorebook = session.get(Lorebook, lorebook_id)
    if not lorebook:
        raise HTTPException(status_code=404, detail="Lorebook not found")
        
    if not q or not q.strip():
        return []
        
    try:
        # Generate embedding for the search query
        query_embedding = embedding_service.generate_embedding(q)
        
        # In SQLModel/SQLAlchemy with pgvector, cosine distance is `<=>` operator.
        # We can use .cosine_distance() method on the Vector column.
        results = session.exec(
            select(LorebookEntry)
            .where(LorebookEntry.lorebook_id == lorebook_id)
            .where(LorebookEntry.embedding.is_not(None))
            .order_by(LorebookEntry.embedding.cosine_distance(query_embedding))
            .limit(limit)
        ).all()
        
        return results
    except Exception as e:
        # Fallback to simple ILIKE if pgvector/embeddings fail (e.g. SQLite fallback for testing)
        search_query = f"%{q.strip()}%"
        from sqlalchemy import or_
        results = session.exec(
            select(LorebookEntry)
            .where(LorebookEntry.lorebook_id == lorebook_id)
            .where(
                or_(
                    LorebookEntry.content.ilike(search_query)
                )
            )
            .limit(limit)
        ).all()
        return results

# ============================================================================
# ENTRIES CRUD
# ============================================================================
@router.get("/{lorebook_id}/entries", response_model=List[LorebookEntry])
def list_entries(lorebook_id: str, session: Session = Depends(get_session)):
    return session.exec(select(LorebookEntry).where(LorebookEntry.lorebook_id == lorebook_id)).all()

@router.post("/{lorebook_id}/entries", response_model=LorebookEntry)
def create_entry(
    lorebook_id: str, 
    entry: LorebookEntry, 
    session: Session = Depends(get_session),
    embedding_service: EmbeddingService = Depends(get_embedding_service)
):
    lorebook = session.get(Lorebook, lorebook_id)
    if not lorebook:
        raise HTTPException(status_code=404, detail="Lorebook not found")
        
    entry.lorebook_id = lorebook_id
    
    # Generate embedding for semantic search
    keys_list = entry.keys if entry.keys else []
    text_to_embed = f"{' '.join(keys_list)} {entry.content or ''}".strip()
    try:
        entry.embedding = embedding_service.generate_embedding(text_to_embed)
    except Exception as e:
        # Non-fatal if embedding generation fails, though in production we'd want to know
        pass
        
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry

@router.put("/{lorebook_id}/entries/{entry_id}", response_model=LorebookEntry)
def update_entry(
    lorebook_id: str, 
    entry_id: str, 
    update_data: EntryUpdate, 
    session: Session = Depends(get_session),
    embedding_service: EmbeddingService = Depends(get_embedding_service)
):
    entry = session.get(LorebookEntry, entry_id)
    if not entry or entry.lorebook_id != lorebook_id:
        raise HTTPException(status_code=404, detail="Entry not found")
        
    needs_embedding_update = False
    update_dict = update_data.model_dump(exclude_unset=True)
    
    if "keys" in update_dict:
        entry.keys = update_dict["keys"]
        needs_embedding_update = True
    if "content" in update_dict:
        entry.content = update_dict["content"]
        needs_embedding_update = True
        
    if needs_embedding_update:
        keys_list = entry.keys if entry.keys else []
        text_to_embed = f"{' '.join(keys_list)} {entry.content or ''}".strip()
        try:
            entry.embedding = embedding_service.generate_embedding(text_to_embed)
        except Exception:
            pass
            
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry

@router.delete("/{lorebook_id}/entries/{entry_id}")
def delete_entry(lorebook_id: str, entry_id: str, session: Session = Depends(get_session)):
    entry = session.get(LorebookEntry, entry_id)
    if not entry or entry.lorebook_id != lorebook_id:
        raise HTTPException(status_code=404, detail="Entry not found")
        
    session.delete(entry)
    session.commit()
    return {"message": "Entry deleted"}
