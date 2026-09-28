from datetime import datetime, timezone
import json
import re

from fastapi import APIRouter, Depends, Body
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session

from api.deps import get_embedding_service, get_session, get_lorebook_repo, get_lorebook_entry_repo
from infrastructure.logging import get_logger
from infrastructure.repositories.lorebook_repo import LorebookRepository
from infrastructure.repositories.lorebook_entry_repo import LorebookEntryRepository
from services.reference_cleanup import scrub_entity_references
from core.entities import Lorebook, LorebookEntry
from core.exceptions import NotFoundError, ValidationError
from services.embedding_service import EmbeddingService

logger = get_logger("lorebooks_route")
router = APIRouter()


class LorebookUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class EntryUpdate(BaseModel):
    keys: list[str] | None = None
    content: str | None = None


class BulkEntryDelete(BaseModel):
    entry_ids: list[str]

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


@router.post("/{lorebook_id}/entries/bulk-delete")
def bulk_delete_entries(
    lorebook_id: str,
    payload: BulkEntryDelete,
    session: Session = Depends(get_session),
    lorebook_repo: LorebookRepository = Depends(get_lorebook_repo),
    lorebook_entry_repo: LorebookEntryRepository = Depends(get_lorebook_entry_repo),
):
    """Delete multiple entries from a lorebook in one call."""
    if not lorebook_repo.get(lorebook_id):
        raise NotFoundError("Lorebook", lorebook_id)

    deleted = 0
    for entry_id in payload.entry_ids:
        entry = lorebook_entry_repo.get(entry_id, lorebook_id)
        if entry and entry.lorebook_id == lorebook_id:
            session.delete(entry)
            deleted += 1
    session.commit()
    return {"deleted": deleted}


# ============================================================================
# SILLYTAVERN WORLDBOOK IMPORT / EXPORT
# ============================================================================

def _normalize_st_keys(raw: object) -> list[str]:
    """SillyTavern `key` may be a list or a comma-separated string."""
    if isinstance(raw, list):
        return [str(k).strip() for k in raw if str(k).strip()]
    if isinstance(raw, str):
        return [k.strip() for k in raw.split(",") if k.strip()]
    return []


def _extract_st_entries(payload) -> list[dict]:
    """Pull entry dicts out of any common SillyTavern world-book shape."""
    if isinstance(payload, dict):
        entries = payload.get("entries", payload)
        if isinstance(entries, dict):
            return [v for v in entries.values() if isinstance(v, dict)]
        if isinstance(entries, list):
            return [v for v in entries if isinstance(v, dict)]
        raise ValidationError("Unrecognized lorebook JSON: no 'entries' object found")
    if isinstance(payload, list):
        return [v for v in payload if isinstance(v, dict)]
    raise ValidationError("Unrecognized lorebook JSON: expected an object or list")


@router.post("/{lorebook_id}/import")
def import_sillytavern_entries(
    lorebook_id: str,
    payload=Body(...),
    session: Session = Depends(get_session),
    lorebook_repo: LorebookRepository = Depends(get_lorebook_repo),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
):
    """Import entries from a SillyTavern world-book JSON payload (merged into this book).

    Accepts the full ST export ({name, entries: {uid: {...}}}), a bare
    {entries: [...]} list, or a top-level list of entries.
    """
    lorebook = lorebook_repo.get(lorebook_id)
    if not lorebook:
        raise NotFoundError("Lorebook", lorebook_id)

    st_entries = _extract_st_entries(payload)
    parsed: list[tuple[list[str], str]] = []
    for raw in st_entries:
        keys = _normalize_st_keys(raw.get("key") or raw.get("keys") or raw.get("comment"))
        content = (raw.get("content") or "").strip()
        if not content:
            continue
        parsed.append((keys, content))

    if not parsed:
        raise ValidationError("No importable entries found (entries need non-empty 'content')")

    texts = [f"{' '.join(keys)} {content}".strip() for keys, content in parsed]
    try:
        embeddings = embedding_service.generate_embeddings(texts)
    except Exception as exc:
        logger.warning("lorebook_bulk_embedding_failed", lorebook_id=lorebook_id, error=str(exc))
        embeddings = [None] * len(parsed)

    now = datetime.now(timezone.utc)
    for (keys, content), emb in zip(parsed, embeddings):
        entry = LorebookEntry(
            lorebook_id=lorebook_id,
            keys=keys,
            content=content,
            embedding=emb,
            created_at=now,
            updated_at=now,
        )
        session.add(entry)
    lorebook.updated_at = now
    session.add(lorebook)
    session.commit()
    return {"imported": len(parsed)}


@router.get("/{lorebook_id}/export")
def export_lorebook_sillytavern(
    lorebook_id: str,
    session: Session = Depends(get_session),
    lorebook_repo: LorebookRepository = Depends(get_lorebook_repo),
    lorebook_entry_repo: LorebookEntryRepository = Depends(get_lorebook_entry_repo),
):
    """Export this lorebook as a SillyTavern-compatible world-book JSON download."""
    lorebook = lorebook_repo.get(lorebook_id)
    if not lorebook:
        raise NotFoundError("Lorebook", lorebook_id)

    entries = lorebook_entry_repo.list_by_lorebook(lorebook_id)
    st_entries: dict[str, dict] = {}
    for idx, entry in enumerate(entries):
        st_entries[str(idx)] = {
            "uid": idx,
            "key": list(entry.keys or []),
            "keysecondary": [],
            "comment": "",
            "content": entry.content or "",
            # `not entry.keys` is this app's own always-on semantics, and
            # `rag_pipeline` already treats a keyless entry that way. Hardcoding
            # `False` exported every keyless entry as key-triggered, so a
            # "constant" world-book entry stopped firing the moment it left here.
            "constant": not entry.keys,
            "vectorized": True,
            "selective": True,
            "selectiveLogic": 0,
            "addMemo": True,
            # `order`, `disable` and `position` have no column on `LorebookEntry`
            # at all, so 100/False/0 is the only faithful value. The two that DO
            # have columns were hardcoded too, which meant a depth or
            # probability the user had set was silently discarded on export.
            "order": 100,
            "position": 0,
            "disable": False,
            "excludeRecursion": False,
            "preventRecursion": False,
            "probability": entry.probability if entry.probability is not None else 100,
            "useProbability": True,
            "depth": entry.depth,
            "group": "",
            "displayIndex": idx,
        }

    export_payload = {"name": lorebook.name, "entries": st_entries}

    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", lorebook.name).strip("_") or "lorebook"
    filename = f"{safe_name}.json"
    return Response(
        content=json.dumps(export_payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
