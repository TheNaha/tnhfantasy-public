from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from api.deps import get_embedding_service, get_session, get_lorebook_repo, get_lorebook_entry_repo
from infrastructure.logging import get_logger
from infrastructure.repositories.lorebook_repo import LorebookRepository
from infrastructure.repositories.lorebook_entry_repo import LorebookEntryRepository
from services.reference_cleanup import scrub_entity_references
from core.entities import Lorebook, LorebookEntry
from core.exceptions import NotFoundError
from services.embedding_service import EmbeddingService

logger = get_logger("lorebooks_route")
router = APIRouter()


class LorebookUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class EntryUpdate(BaseModel):
    keys: list[str] | None = None
    content: str | None = None

@router.get("", response_model=list[Lorebook])
def list_lorebooks(session: Session = Depends(get_session), lorebook_repo: LorebookRepository = Depends(get_lorebook_repo)):
    return lorebook_repo.list()

@router.post("", response_model=Lorebook)
def create_lorebook(lorebook: Lorebook, session: Session = Depends(get_session), lorebook_repo: LorebookRepository = Depends(get_lorebook_repo)):
    lorebook.created_at = datetime.now(timezone.utc)
    lorebook.updated_at = lorebook.created_at
    session.add(lorebook)
    session.commit()
    session.refresh(lorebook)
    return lorebook

@router.get("/{lorebook_id}", response_model=Lorebook)
def get_lorebook(lorebook_id: str, session: Session = Depends(get_session), lorebook_repo: LorebookRepository = Depends(get_lorebook_repo)):
    lorebook = lorebook_repo.get(lorebook_id)
    if not lorebook:
        raise NotFoundError("Lorebook", lorebook_id)
    return lorebook

@router.put("/{lorebook_id}", response_model=Lorebook)
def update_lorebook(lorebook_id: str, update_data: LorebookUpdate, session: Session = Depends(get_session), lorebook_repo: LorebookRepository = Depends(get_lorebook_repo)):
    lorebook = lorebook_repo.get(lorebook_id)
    if not lorebook:
        raise NotFoundError("Lorebook", lorebook_id)
    
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
def delete_lorebook(lorebook_id: str, session: Session = Depends(get_session), lorebook_repo: LorebookRepository = Depends(get_lorebook_repo), lorebook_entry_repo: LorebookEntryRepository = Depends(get_lorebook_entry_repo)):
    lorebook = lorebook_repo.get(lorebook_id)
    if not lorebook:
        raise NotFoundError("Lorebook", lorebook_id)
        
    scrub_entity_references(session, "lorebook", lorebook_id)
    entries = lorebook_entry_repo.list_by_lorebook(lorebook_id)
    for entry in entries:
        session.delete(entry)
        
    session.delete(lorebook)
    session.commit()
    return {"message": "Lorebook deleted"}

# ============================================================================
# SEARCH ENDPOINT
# ============================================================================

@router.get("/{lorebook_id}/search", response_model=list[LorebookEntry])
def search_entries(
    lorebook_id: str, 
    q: str, 
    limit: int = 5,
    session: Session = Depends(get_session),
    lorebook_repo: LorebookRepository = Depends(get_lorebook_repo),
):
    """Semantic search for lorebook entries based on a query string."""
    lorebook = lorebook_repo.get(lorebook_id)
    if not lorebook:
        raise NotFoundError("Lorebook", lorebook_id)

    from services.rag_pipeline import search_lorebook_entries

    return search_lorebook_entries(session, [lorebook_id], q, limit=limit)


@router.post("/{lorebook_id}/reindex")
def reindex_lorebook(
    lorebook_id: str,
    session: Session = Depends(get_session),
    lorebook_repo: LorebookRepository = Depends(get_lorebook_repo),
):
    """Backfill missing embeddings for a lorebook's entries (semantic-search index)."""
    lorebook = lorebook_repo.get(lorebook_id)
    if not lorebook:
        raise NotFoundError("Lorebook", lorebook_id)

    from services.rag_pipeline import backfill_lorebook_embeddings

    reindexed = backfill_lorebook_embeddings(session, lorebook_id)
    return {"reindexed": reindexed}

# ============================================================================
# ENTRIES CRUD
# ============================================================================
@router.get("/{lorebook_id}/entries", response_model=list[LorebookEntry])
def list_entries(lorebook_id: str, session: Session = Depends(get_session), lorebook_repo: LorebookRepository = Depends(get_lorebook_repo), lorebook_entry_repo: LorebookEntryRepository = Depends(get_lorebook_entry_repo)):
    return lorebook_entry_repo.list_by_lorebook(lorebook_id)

@router.post("/{lorebook_id}/entries", response_model=LorebookEntry)
def create_entry(
    lorebook_id: str, 
    entry: LorebookEntry, 
    session: Session = Depends(get_session),
    lorebook_repo: LorebookRepository = Depends(get_lorebook_repo),
    embedding_service: EmbeddingService = Depends(get_embedding_service)
):
    lorebook = lorebook_repo.get(lorebook_id)
    if not lorebook:
        raise NotFoundError("Lorebook", lorebook_id)
        
    entry.lorebook_id = lorebook_id
    
    # Generate embedding for semantic search
    keys_list = entry.keys if entry.keys else []
    text_to_embed = f"{' '.join(keys_list)} {entry.content or ''}".strip()
    try:
        entry.embedding = embedding_service.generate_embedding(text_to_embed)
    except Exception as exc:
        logger.warning("lorebook_entry_embedding_failed", entry_id=entry.id or "new", error=str(exc))
        
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
    lorebook_entry_repo: LorebookEntryRepository = Depends(get_lorebook_entry_repo),
    embedding_service: EmbeddingService = Depends(get_embedding_service)
):
    entry = lorebook_entry_repo.get(entry_id, lorebook_id)
    if not entry or entry.lorebook_id != lorebook_id:
        raise NotFoundError("LorebookEntry", entry_id)
        
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
        except Exception as exc:
            logger.debug("entry_embedding_failed", entry_id=entry.id, error=str(exc))
            
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry

@router.delete("/{lorebook_id}/entries/{entry_id}")
def delete_entry(lorebook_id: str, entry_id: str, session: Session = Depends(get_session), lorebook_repo: LorebookRepository = Depends(get_lorebook_repo), lorebook_entry_repo: LorebookEntryRepository = Depends(get_lorebook_entry_repo)):
    entry = lorebook_entry_repo.get(entry_id, lorebook_id)
    if not entry or entry.lorebook_id != lorebook_id:
        raise NotFoundError("LorebookEntry", entry_id)
        
    session.delete(entry)
    session.commit()
    return {"message": "Entry deleted"}
