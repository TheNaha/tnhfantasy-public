from datetime import datetime, timezone
import json
import re

from fastapi import APIRouter, Depends, Body, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlmodel import Session

from api.deps import get_embedding_service, get_session, get_lorebook_repo, get_lorebook_entry_repo
from infrastructure.logging import get_logger
from infrastructure.repositories.lorebook_repo import LorebookRepository
from infrastructure.repositories.lorebook_entry_repo import LorebookEntryRepository
from services.reference_cleanup import scrub_entity_references
from services.world_ownership import apply_world_id, require_world
from core.entities import Lorebook, LorebookEntry
from core.exceptions import NotFoundError, ValidationError
from services.embedding_service import EmbeddingService

logger = get_logger("lorebooks_route")

# Bound on the entries listing. See `list_entries`.
#
# `memories.py` already bounds its listing the same way (200/500 + offset), so
# this is consistency rather than a new idea. 2,000 is generous enough that a
# real world book never hits it: a large SillyTavern import is a few hundred
# entries, and anything past this is a page the client should ask for.
LOREBOOK_ENTRY_PAGE_DEFAULT_LIMIT = 1000
LOREBOOK_ENTRY_PAGE_MAX_LIMIT = 2000
router = APIRouter()
# Ceiling on any `search`/`q`/`query` term this module accepts, in characters.
# The routes below ILIKE it against application-owned text, and the reader is
# unauthenticated, so an unbounded term is a free full scan.
MAX_SEARCH_LENGTH = 200



class LorebookUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    # Which World this entity belongs to. Ownership of record lives on the
    # member, not in an array on the `worlds` row — see `services/
    # world_ownership.py`. Absent means "leave alone"; an explicit null detaches.
    world_id: str | None = None


class EntryUpdate(BaseModel):
    """The editable fields of one lorebook entry.

    Only `keys` and `content` used to be declared, so `enabled`,
    `secondary_keys`, `case_sensitive`, `selective_logic`, `probability`,
    `depth`, `category` and `tags` were UNREACHABLE through the API: a user
    who imported a book with a disabled entry could never re-enable it, and
    a user who wanted to set a probability had no way to. Pydantic's default
    `extra='ignore'` dropped the fields at the edge and the route answered
    200.
    """

    keys: list[str] | None = None
    content: str | None = None
    enabled: bool | None = None
    secondary_keys: list[str] | None = None
    case_sensitive: bool | None = None
    selective_logic: str | None = None
    probability: int | None = None
    depth: int | None = None
    category: str | None = None
    tags: list[str] | None = None


class BulkEntryDelete(BaseModel):
    entry_ids: list[str]

class LorebookCreateRequest(BaseModel):
    """Create body for POST /lorebooks — see `CharacterCreateRequest` for why a
    table class is not a request body (client-writable `id`, unvalidated 500s)."""

    model_config = {"extra": "forbid"}

    name: str
    description: str | None = None
    # Which World this book belongs to. See `LorebookUpdate.world_id`.
    world_id: str | None = None


class LorebookEntryCreateRequest(BaseModel):
    """Create body for POST /lorebooks/{id}/entries.

    `embedding` is excluded on purpose: it is `exclude=True` on the model and is
    generated server-side from `keys` + `content`, so accepting it would let a
    caller pin an embedding that no longer matches its own text.
    `case_sensitive`, `selective_logic` and `probability` are accepted because
    the columns and the card importer already populate them.
    """

    model_config = {"extra": "forbid"}

    keys: list[str] = Field(default_factory=list)
    content: str
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    depth: int = 4
    case_sensitive: bool = False
    selective_logic: str | None = None
    probability: int | None = None


@router.get("", response_model=list[Lorebook])
def list_lorebooks(session: Session = Depends(get_session), lorebook_repo: LorebookRepository = Depends(get_lorebook_repo)):
    return lorebook_repo.list()

@router.post("", response_model=Lorebook)
def create_lorebook(payload: LorebookCreateRequest, session: Session = Depends(get_session), lorebook_repo: LorebookRepository = Depends(get_lorebook_repo)):
    require_world(session, payload.world_id)
    lorebook = Lorebook(**payload.model_dump())
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
    apply_world_id(session, lorebook, update_dict)
    update_dict.pop("world_id", None)
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
    q: str = Query(..., max_length=MAX_SEARCH_LENGTH),

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
def list_entries(
    lorebook_id: str,
    limit: int = Query(default=LOREBOOK_ENTRY_PAGE_DEFAULT_LIMIT, ge=1, le=LOREBOOK_ENTRY_PAGE_MAX_LIMIT),
    session: Session = Depends(get_session), lorebook_repo: LorebookRepository = Depends(get_lorebook_repo), lorebook_entry_repo: LorebookEntryRepository = Depends(get_lorebook_entry_repo), ):
    """List a lorebook's entries, oldest first.

    Bounded because the query had neither a `LIMIT` nor an `ORDER BY`, so a
    SillyTavern import with a few thousand entries returned every row — and each
    row used to carry a 384-float embedding on top of its text. The default is
    generous because a personal world book is normally far smaller; an
    over-limit request is rejected rather than silently clamped, so a client
    that thinks it has the whole book finds out.
    """
    return lorebook_entry_repo.list_by_lorebook(lorebook_id, limit=limit)

@router.post("/{lorebook_id}/entries", response_model=LorebookEntry)
def create_entry(
    lorebook_id: str, 
    payload: LorebookEntryCreateRequest,
    session: Session = Depends(get_session),
    lorebook_repo: LorebookRepository = Depends(get_lorebook_repo),
    embedding_service: EmbeddingService = Depends(get_embedding_service)
):
    lorebook = lorebook_repo.get(lorebook_id)
    if not lorebook:
        raise NotFoundError("Lorebook", lorebook_id)

    entry = LorebookEntry(**payload.model_dump())
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
    # The rest of the entry's state. These are the fields that decide WHETHER
    # the entry activates, so they were the ones that mattered most and the
    # ones that could not be written at all.
    if "enabled" in update_dict and update_dict["enabled"] is not None:
        entry.enabled = bool(update_dict["enabled"])
    if "secondary_keys" in update_dict and update_dict["secondary_keys"] is not None:
        entry.secondary_keys = list(update_dict["secondary_keys"])
    if "case_sensitive" in update_dict and update_dict["case_sensitive"] is not None:
        entry.case_sensitive = bool(update_dict["case_sensitive"])
    if "selective_logic" in update_dict:
        entry.selective_logic = update_dict["selective_logic"]
    if "probability" in update_dict:
        entry.probability = update_dict["probability"]
    if "depth" in update_dict and update_dict["depth"] is not None:
        entry.depth = int(update_dict["depth"])
    if "category" in update_dict:
        entry.category = update_dict["category"]
    if "tags" in update_dict and update_dict["tags"] is not None:
        entry.tags = list(update_dict["tags"])

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


def _st_int(raw: dict, *names: str) -> int | None:
    """The first of `names` that is present and reads as an int, else None."""
    for name in names:
        value = raw.get(name)
        if value is None or isinstance(value, bool):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _st_entry_kwargs(raw: dict) -> dict:
    """Map one SillyTavern world-book entry onto this vault's entry columns.

    The same mapping the character-card importer applies
    (`core/character_cards.py`), so the same book arrives with the same state
    whether it came in as a card or as a world-book file.

    Beyond `key` and `content`, a SillyTavern entry carries `keysecondary`,
    `constant`, `disable`, `caseSensitive`, `selectiveLogic`, `probability`
    and `depth`. They were ALL dropped on import and hardcoded on export, so:

      * a `disable: true` entry was imported ENABLED and started firing;
      * a `keysecondary` entry lost its secondary keys and stopped being
        selective;
      * a `probability` was imported and then never consulted;
      * a `caseSensitive` entry matched case-insensitively.

    Only the fields the payload actually carries are returned, so an absent
    field keeps the column's own default instead of being written as null.
    """
    # `key` may be a list or a comma-separated string, and ST falls back to
    # the entry's comment when there is no key at all.
    keys = _normalize_st_keys(raw.get("key") or raw.get("keys") or raw.get("comment"))
    # `constant: true` means "always on" in SillyTavern, and this vault's
    # always-on test is a KEYLESS entry — the rule the card importer uses.
    if raw.get("constant"):
        keys = []

    kwargs: dict = {
        "keys": keys,
        "content": (raw.get("content") or "").strip(),
        "secondary_keys": _normalize_st_keys(raw.get("keysecondary") or raw.get("secondary_keys")),
    }

    # `disable` is ST's negative flag; `enabled` is this vault's positive
    # one. An ST entry with `disable: true` must not activate here.
    if raw.get("disable") is not None:
        kwargs["enabled"] = not bool(raw.get("disable"))
    elif raw.get("enabled") is not None:
        kwargs["enabled"] = bool(raw.get("enabled"))

    case_sensitive = raw.get("caseSensitive")
    if case_sensitive is None:
        case_sensitive = raw.get("case_sensitive")
    if case_sensitive is not None:
        kwargs["case_sensitive"] = bool(case_sensitive)

    selective_logic = raw.get("selectiveLogic")
    if selective_logic is None:
        selective_logic = raw.get("selective_logic")
    if selective_logic is not None:
        kwargs["selective_logic"] = str(selective_logic)

    probability = _st_int(raw, "probability")
    if probability is not None:
        kwargs["probability"] = probability

    depth = _st_int(raw, "depth")
    if depth is not None:
        kwargs["depth"] = depth

    comment = raw.get("comment")
    if isinstance(comment, str) and comment.strip():
        kwargs["category"] = comment.strip()

    tags = raw.get("tags")
    if isinstance(tags, list):
        kwargs["tags"] = [str(t) for t in tags if str(t).strip()]

    return kwargs


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
    parsed: list[dict] = []
    for raw in st_entries:
        fields = _st_entry_kwargs(raw)
        if not fields["content"]:
            continue
        parsed.append(fields)

    if not parsed:
        raise ValidationError("No importable entries found (entries need non-empty 'content')")

    texts = [
        f"{' '.join(fields.get('keys') or [])} {fields['content']}".strip()
        for fields in parsed
    ]
    try:
        embeddings = embedding_service.generate_embeddings(texts)
    except Exception as exc:
        logger.warning("lorebook_bulk_embedding_failed", lorebook_id=lorebook_id, error=str(exc))
        embeddings = [None] * len(parsed)

    now = datetime.now(timezone.utc)
    for fields, emb in zip(parsed, embeddings):
        entry = LorebookEntry(
            lorebook_id=lorebook_id,
            embedding=emb,
            created_at=now,
            updated_at=now,
            **fields,
        )
        session.add(entry)
    lorebook.updated_at = now
    session.add(lorebook)
    session.commit()
    return {"imported": len(parsed)}


def _st_selective_logic(value) -> int:
    """SillyTavern's `selectiveLogic` as the NUMBER it is.

    0 is AND, 1 is OR, 2 is NOT AND and 3 is NOT OR. The column is free text
    (the card importer stores "1"), and the export has to emit a number: a
    string here would make the payload invalid for SillyTavern and would make
    the round trip unstable, because the second export would then carry the
    string the first one did not.
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number in (0, 1, 2, 3) else 0


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
            # ST's secondary keys, for `selective` matching. They were dropped
            # on import, so an entry that was selective in SillyTavern came
            # here with an empty list and was exported as never-selective.
            "keysecondary": list(entry.secondary_keys or []),
            "comment": entry.category or "",
            "content": entry.content or "",
            # `not entry.keys` is this app's own always-on semantics, and
            # `rag_pipeline` already treats a keyless entry that way. Hardcoding
            # `False` exported every keyless entry as key-triggered, so a
            # "constant" world-book entry stopped firing the moment it left here.
            "constant": not entry.keys,
            "vectorized": True,
            # `selective` is ST's flag for "the secondary keys count". This
            # vault's equivalent is "the entry HAS secondary keys", so the
            # export derives it rather than hardcoding `True` — which claimed
            # every entry was selective, including the ones with no secondary
            # keys at all.
            "selective": bool(entry.secondary_keys),
            "selectiveLogic": _st_selective_logic(entry.selective_logic),
            "addMemo": True,
            # `order` and `position` have no column on `LorebookEntry` at
            # all, so 100/0 is the only faithful value. The fields that DO
            # have columns are emitted from the row: a disabled entry used to
            # be exported as enabled, a probability the user had set was
            # discarded, and a depth was hardcoded.
            "order": 100,
            "position": 0,
            "disable": not bool(entry.enabled),
            "excludeRecursion": False,
            "preventRecursion": False,
            "probability": entry.probability if entry.probability is not None else 100,
            "useProbability": True,
            "depth": entry.depth,
            "caseSensitive": bool(entry.case_sensitive),
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
