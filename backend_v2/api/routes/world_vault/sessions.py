"""Sessions API — curatable groups of related images.

A session is either **auto-detected** (`services/session_detector`, from seed /
checkpoint / time-proximity) or **hand-made**, and the difference is enforced
here rather than trusted: every human edit — rename, add, remove, split, merge —
sets `locked=True`, and the detector never touches a locked session again. That
invariant is the reason this module funnels every mutation through
`SessionRepository.recompute_bounds` as well: `start_at`, `end_at`,
`image_count` and `thumbnail` are denormalised because the scrubber orders by
them, and they have exactly one source of truth, `session_assets`.

Membership is a real join table rather than a computed time range, because
split and merge are the operations people actually need and both mutate
membership — and because a split has to survive the next recompute, which it
only can if membership is stored.

Router paths are mounted under `/api/v2` by `world_vault/__init__.py`, so the
public prefix is `/api/v2/sessions`.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlmodel import Session, func, select

from api.deps import get_session
from core.entities import Asset, SessionAsset
from core.entities import Session as GenerationSession
from core.exceptions import NotFoundError, ValidationError
from core.sql_search import LIKE_ESCAPE_CHAR, like_contains
from infrastructure.logging import get_logger
from infrastructure.repositories.session_repo import SessionRepository
from services.asset_metadata_index import normalise_checkpoints, normalise_loras
from services.asset_reconciler import DEFAULT_USER_ID
from services.session_detector import MAX_DETECT_ASSETS, RESOLVED_TS, detect_sessions

logger = get_logger("sessions_api")

router = APIRouter()

MAX_LIST_LIMIT = 100
DEFAULT_LIST_LIMIT = 24
MAX_MEMBER_PAGE = 500
DEFAULT_MEMBER_PAGE = 200

MAX_SPLIT_SUFFIX_ATTEMPTS = 50
_SPLIT_SUFFIX_RE = re.compile(r"\s*\(split(?: \d+)?\)$")

# The columns the read models expose. Spelled out rather than using
# `__dict__` so adding a field to the entity cannot silently change the payload.
_SESSION_COLUMNS = (
    "id",
    "user_id",
    "name",
    "description",
    "signature",
    "auto_detected",
    "locked",
    "workspace",
    "start_at",
    "end_at",
    "image_count",
    "thumbnail",
    "created_at",
    "updated_at",
    "deleted_at",
)


def get_session_repo(session: Session = Depends(get_session)) -> SessionRepository:
    """Request-scoped repository provider.

    Every other repository provider lives in `api/deps.py`. This one is declared
    here because `api/deps.py` was outside the change set for this work; it is a
    drop-in `get_session_repo` for that file and nothing else about it is
    different. Move it when the file is next editable.
    """
    return SessionRepository(session)


# ── request DTOs ────────────────────────────────────────────────────────────


class SessionCreate(BaseModel):
    name: str
    description: str | None = None
    workspace: str | None = None
    asset_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _reject_empty_name(self):
        if not self.name.strip():
            raise ValueError("name cannot be empty")
        return self


class SessionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class SessionAssetAdd(BaseModel):
    asset_ids: list[str] = Field(default_factory=list)


class SessionSplit(BaseModel):
    keep_asset_ids: list[str] = Field(default_factory=list)


class SessionMerge(BaseModel):
    target_session_id: str


class SessionDetect(BaseModel):
    min_size: int = Field(default=2, ge=1, le=100)
    time_gap_minutes: int = Field(default=20, ge=1, le=24 * 60)
    dry_run: bool = False


# ── response DTOs ───────────────────────────────────────────────────────────


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str | None = None
    description: str | None = None
    signature: str | None = None
    auto_detected: bool
    locked: bool
    workspace: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    image_count: int
    thumbnail: str | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class SessionDetailOut(SessionOut):
    asset_ids: list[str] = Field(default_factory=list)


class SessionListOut(BaseModel):
    sessions: list[SessionOut]
    total: int
    limit: int
    offset: int


class SessionAssetOut(BaseModel):
    """One member, with the metadata a session panel renders.

    LoRAs come from `normalise_loras` rather than a `->` into `assets.metadata_`
    because the real library nests the CivitAI id at `metadata.id` and stores the
    display name in `metadata.name`; a direct read returns `None` for every LoRA
    in the deployment. Resolving them here costs no extra query, which is the
    point: the client must not have to make N+1 calls to draw a session.
    """

    id: str
    relative_path: str
    thumbnail_relative_path: str | None = None
    width: int | None = None
    height: int | None = None
    workspace: str
    job_completed_at: datetime | None = None
    generated_at: datetime | None = None
    created_at: datetime
    added_at: datetime
    prompt: str | None = None
    negative_prompt: str | None = None
    seed: int | None = None
    steps: int | None = None
    cfg: float | None = None
    sampler: str | None = None
    scheduler: str | None = None
    vae: str | None = None
    checkpoint: str | None = None
    loras: list[dict] = Field(default_factory=list)


class SessionMembersOut(BaseModel):
    session_id: str
    assets: list[SessionAssetOut]
    total: int
    limit: int
    offset: int


class SessionAssetIdsOut(BaseModel):
    added: int
    already_members: list[str]
    session: SessionOut


class SessionSplitOut(BaseModel):
    """Both halves, each with its own member ids — the client has to redraw the
    whole list from this, and the two are now independent sessions."""

    session: SessionDetailOut
    created: SessionDetailOut


class SessionDetectOut(BaseModel):
    min_size: int
    time_gap_minutes: int
    dry_run: bool
    max_assets: int
    summary: dict


# ── helpers ─────────────────────────────────────────────────────────────────


def _require(session_repo: SessionRepository, session_id: str) -> GenerationSession:
    row = session_repo.get(session_id)
    if row is None:
        raise NotFoundError("Session", session_id)
    return row


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _require_assets(repo: SessionRepository, asset_ids: list[str], field: str) -> list[str]:
    """Validate that every id names a live asset, in one query.

    Reports the missing ids rather than the first one: a client posting a
    thousand ids from a stale gallery list wants to know which of them are wrong.
    A repeated id inside one request is rejected rather than collapsed, because
    silently de-duplicating turns an honest `added: 2` into `added: 1` and the
    client never learns which of its two ids was the duplicate.
    """
    requested = [asset_id for asset_id in asset_ids if asset_id]
    if not requested:
        return requested
    repeated = [asset_id for asset_id, count in Counter(requested).items() if count > 1]
    if repeated:
        preview = ", ".join(repeated[:5]) + ("…" if len(repeated) > 5 else "")
        raise ValidationError(
            f"asset_ids repeats the same id more than once: {preview}", field=field
        )
    live = repo.live_asset_ids(requested)
    missing = [asset_id for asset_id in requested if asset_id not in live]
    if missing:
        preview = ", ".join(missing[:5]) + ("…" if len(missing) > 5 else "")
        raise ValidationError(
            f"Unknown or deleted asset(s): {preview}", field=field
        )
    return requested


def _detail(repo: SessionRepository, row: GenerationSession) -> dict:
    """The session plus its member ids.

    Returned explicitly rather than handing the ORM object to
    `SessionDetailOut`: a model field with no matching attribute silently
    defaults, so an object that lacks `asset_ids` validates into a session that
    reports zero members.
    """
    return {
        **{column: getattr(row, column) for column in _SESSION_COLUMNS},
        "asset_ids": repo.member_ids(row.id),
    }


def _member_payload(asset: Asset, added_at: datetime) -> dict:
    metadata = asset.metadata_ or {}
    checkpoints = normalise_checkpoints(metadata)
    checkpoint = asset.checkpoint_name
    if not checkpoint and checkpoints:
        checkpoint = checkpoints[0].get("display_name") or checkpoints[0].get("name")
    return {
        "id": asset.id,
        "relative_path": asset.relative_path,
        "thumbnail_relative_path": asset.thumbnail_relative_path,
        "width": asset.width,
        "height": asset.height,
        "workspace": asset.workspace,
        "job_completed_at": asset.job_completed_at,
        "generated_at": asset.generated_at,
        "created_at": asset.created_at,
        "added_at": added_at,
        "prompt": metadata.get("prompt") if isinstance(metadata.get("prompt"), str) else None,
        "negative_prompt": (
            metadata.get("negativePrompt")
            if isinstance(metadata.get("negativePrompt"), str)
            else None
        ),
        "seed": asset.seed,
        "steps": asset.steps,
        "cfg": asset.cfg,
        "sampler": asset.sampler,
        "scheduler": asset.scheduler,
        "vae": asset.vae,
        "checkpoint": checkpoint,
        "loras": normalise_loras(metadata),
    }


def _split_name(repo: SessionRepository, source: GenerationSession) -> str:
    """A name for the new half: the original plus a suffix that is not taken.

    The base is the original with any earlier split suffix stripped, so splitting
    a split yields `Batch (split 2)` rather than `Batch (split) (split)`. Suffix
    numbers are counted off the live set rather than guessed.
    """
    base = _SPLIT_SUFFIX_RE.sub("", (source.name or "Session").strip()).strip() or "Session"
    taken = repo.live_names(source.workspace)
    candidate = f"{base} (split)"
    attempt = 1
    while candidate in taken and attempt <= MAX_SPLIT_SUFFIX_ATTEMPTS:
        attempt += 1
        candidate = f"{base} (split {attempt})"
    return candidate


# ── list / read ─────────────────────────────────────────────────────────────


@router.get("", response_model=SessionListOut)
def list_sessions(
    workspace: str | None = None,
    auto_detected: bool | None = None,
    locked: bool | None = None,
    search: str | None = None,
    limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    offset: int = Query(0, ge=0),
    repo: SessionRepository = Depends(get_session_repo),
):
    """List live sessions, newest activity first."""
    filters = [GenerationSession.deleted_at.is_(None)]
    if workspace is not None:
        filters.append(GenerationSession.workspace == workspace)
    if auto_detected is not None:
        filters.append(GenerationSession.auto_detected == auto_detected)
    if locked is not None:
        filters.append(GenerationSession.locked == locked)
    if search:
        pattern = func.lower(like_contains(search.strip()))
        filters.append(
            func.lower(GenerationSession.name).like(pattern, escape=LIKE_ESCAPE_CHAR)
            | func.lower(GenerationSession.description).like(pattern, escape=LIKE_ESCAPE_CHAR)
        )

    total = repo.session.execute(
        select(func.count(GenerationSession.id)).where(*filters)
    ).scalar_one()
    rows = repo.session.exec(
        select(GenerationSession)
        .where(*filters)
        .order_by(GenerationSession.updated_at.desc(), GenerationSession.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return {"sessions": rows, "total": total, "limit": limit, "offset": offset}


@router.post("/detect", response_model=SessionDetectOut)
def detect(
    data: SessionDetect,
    session: Session = Depends(get_session),
):
    """Run the detector.

    This is the only expensive endpoint in the module and it is deliberately not
    reachable from a poll: it scans the whole asset table, so on this deployment
    (~16.4k assets) it is a second or more of synchronous work inside a request.
    Never put it on a UI refresh interval — call it once, from an explicit action,
    and use `dry_run` to preview.

    `POST` rather than `GET` because the body is a request to do work, and
    because a crawler or a prefetching layer must not be able to trigger it.

    `GET /` is the cheap path. Anything the UI needs to show sessions does not
    require this.
    """
    summary = detect_sessions(
        session,
        min_size=data.min_size,
        time_gap_minutes=data.time_gap_minutes,
        dry_run=data.dry_run,
    )
    return {
        "min_size": data.min_size,
        "time_gap_minutes": data.time_gap_minutes,
        "dry_run": data.dry_run,
        "max_assets": MAX_DETECT_ASSETS,
        "summary": summary,
    }


@router.get("/{session_id}", response_model=SessionDetailOut)
def get_session_detail(
    session_id: str,
    repo: SessionRepository = Depends(get_session_repo),
):
    """One session with its member ids. Members themselves are `/assets`."""
    return _detail(repo, _require(repo, session_id))


@router.get("/{session_id}/assets", response_model=SessionMembersOut)
def list_session_assets(
    session_id: str,
    limit: int = Query(DEFAULT_MEMBER_PAGE, ge=1, le=MAX_MEMBER_PAGE),
    offset: int = Query(0, ge=0),
    repo: SessionRepository = Depends(get_session_repo),
):
    """The members, with generation metadata, in one request.

    Ordered by the resolved timestamp so the panel's order matches the session's
    own `start_at`/`end_at`. The LoRAs and the prompt are resolved in Python from
    the already-selected `metadata_`, so this stays one joined query no matter
    how many images the session holds.
    """
    row = _require(repo, session_id)

    base = (
        select(SessionAsset.asset_id, SessionAsset.added_at)
        .where(SessionAsset.session_id == row.id)
    )
    total = repo.session.execute(
        select(func.count()).select_from(base.subquery())
    ).scalar_one()
    pairs = repo.session.exec(
        base.join(Asset, Asset.id == SessionAsset.asset_id)
        .add_columns(Asset)
        .order_by(RESOLVED_TS, Asset.id)
        .limit(limit)
        .offset(offset)
    ).all()

    return {
        "session_id": row.id,
        "assets": [_member_payload(asset, added_at) for _, added_at, asset in pairs],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ── create / mutate ─────────────────────────────────────────────────────────


@router.post("", response_model=SessionDetailOut)
def create_session(
    data: SessionCreate,
    session: Session = Depends(get_session),
    repo: SessionRepository = Depends(get_session_repo),
):
    """Create a hand-made session.

    `auto_detected=False` and `locked=True` from the start: a session a person
    built is curated by definition, and the detector must never second-guess it.
    """
    asset_ids = _require_assets(repo, data.asset_ids, "asset_ids")
    now = datetime.now(timezone.utc)
    row = GenerationSession(
        user_id=DEFAULT_USER_ID,
        name=data.name.strip(),
        description=data.description,
        signature=None,
        auto_detected=False,
        locked=True,
        workspace=data.workspace,
        image_count=0,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    if asset_ids:
        repo.add_members(row.id, asset_ids)
        repo.recompute_bounds(row)
    session.commit()
    session.refresh(row)
    return {**{c: getattr(row, c) for c in _SESSION_COLUMNS}, "asset_ids": asset_ids}

@router.patch("/{session_id}", response_model=SessionOut)
def patch_session(
    session_id: str,
    data: SessionUpdate,
    session: Session = Depends(get_session),
    repo: SessionRepository = Depends(get_session_repo),
):
    """Rename or re-describe a session.

    Any successful patch sets `locked=True`: it is a human edit, and the whole
    curation contract rests on the detector never overwriting one.
    """
    row = _require(repo, session_id)
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(row, key, value)
    row.locked = True
    repo.touch(row)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@router.delete("/{session_id}")
def delete_session(
    session_id: str,
    session: Session = Depends(get_session),
    repo: SessionRepository = Depends(get_session_repo),
):
    """Soft delete. The images themselves are untouched."""
    row = _require(repo, session_id)
    now = datetime.now(timezone.utc)
    row.deleted_at = now
    row.updated_at = now
    # Zeroed so a soft-deleted row cannot be mistaken for a live empty one by
    # anything that reads it outside the `deleted_at IS NULL` filter.
    row.image_count = 0
    row.start_at = None
    row.end_at = None
    row.thumbnail = None
    session.add(row)
    session.commit()
    return {"success": True, "message": f"Session {session_id} deleted"}


@router.post("/{session_id}/assets", response_model=SessionAssetIdsOut)
def add_session_assets(
    session_id: str,
    data: SessionAssetAdd,
    session: Session = Depends(get_session),
    repo: SessionRepository = Depends(get_session_repo),
):
    """Add members. Sets `locked=True`."""
    row = _require(repo, session_id)
    requested = _require_assets(repo, data.asset_ids, "asset_ids")
    if not requested:
        raise ValidationError("asset_ids is empty", field="asset_ids")

    existing = set(repo.member_ids(row.id))
    duplicates = [asset_id for asset_id in requested if asset_id in existing]
    if duplicates:
        # Checked before writing, not caught after: `uq_session_asset` would
        # reject the whole executemany and surface as a 500, and a partial write
        # would leave the caller guessing what landed.
        preview = ", ".join(duplicates[:5]) + ("…" if len(duplicates) > 5 else "")
        raise ValidationError(
            f"Asset(s) already in this session: {preview}", field="asset_ids"
        )

    repo.add_members(row.id, requested)
    row.locked = True
    repo.recompute_bounds(row)
    session.add(row)
    session.commit()
    session.refresh(row)
    return {"added": len(requested), "already_members": [], "session": row}


@router.delete("/{session_id}/assets/{asset_id}")
def remove_session_asset(
    session_id: str,
    asset_id: str,
    session: Session = Depends(get_session),
    repo: SessionRepository = Depends(get_session_repo),
):
    """Remove one member. Sets `locked=True`."""
    row = _require(repo, session_id)
    if asset_id not in set(repo.member_ids(row.id)):
        raise NotFoundError("SessionAsset", f"{session_id}/{asset_id}")
    removed = repo.remove_members(row.id, [asset_id])
    row.locked = True
    repo.recompute_bounds(row)
    session.add(row)
    session.commit()
    return {"success": True, "removed": removed}


@router.post("/{session_id}/split", response_model=SessionSplitOut)
def split_session(
    session_id: str,
    data: SessionSplit,
    session: Session = Depends(get_session),
    repo: SessionRepository = Depends(get_session_repo),
):
    """Split off the complement of `keep_asset_ids` into a new session.

    Exactly the named members stay; every other member moves. Both halves are
    `locked=True` and both get their bounds, count and cover recomputed, because
    the two are now independent sessions and a stale denormalisation on either
    would misreport it in the scrubber. The new half keeps `signature` for
    lineage — it is deliberately not unique-constrained, which is what lets two
    sessions share one — but sets `auto_detected=False` because a human made it.
    """
    source = _require(repo, session_id)
    members = set(repo.member_ids(source.id))
    keep = _dedupe(data.keep_asset_ids)

    unknown = [asset_id for asset_id in keep if asset_id not in members]
    if unknown:
        preview = ", ".join(unknown[:5]) + ("…" if len(unknown) > 5 else "")
        raise ValidationError(
            f"keep_asset_ids contains non-member(s): {preview}", field="keep_asset_ids"
        )
    if not keep:
        raise ValidationError(
            "keep_asset_ids must name at least one member to keep",
            field="keep_asset_ids",
        )
    moved = sorted(members - set(keep))
    if not moved:
        raise ValidationError(
            "keep_asset_ids names every member; there is nothing to split off",
            field="keep_asset_ids",
        )

    now = datetime.now(timezone.utc)
    created = GenerationSession(
        user_id=source.user_id,
        name=_split_name(repo, source),
        description=source.description,
        signature=source.signature,
        auto_detected=False,
        locked=True,
        workspace=source.workspace,
        image_count=0,
        created_at=now,
        updated_at=now,
    )
    session.add(created)

    repo.remove_members(source.id, moved)
    repo.add_members(created.id, moved)
    repo.recompute_bounds(source)
    repo.recompute_bounds(created)
    source.locked = True
    session.add(source)
    session.commit()
    session.refresh(created)
    return {"session": _detail(repo, source), "created": _detail(repo, created)}


@router.post("/{session_id}/merge", response_model=SessionOut)
def merge_session(
    session_id: str,
    data: SessionMerge,
    session: Session = Depends(get_session),
    repo: SessionRepository = Depends(get_session_repo),
):
    """Merge this session into another and soft-delete this one.

    Returns the target. `workspace` is not narrowed or widened: the target keeps
    whatever it had, because only a manual merge may produce a session spanning
    workspaces and narrowing it here would silently mislabel the result.
    """
    source = _require(repo, session_id)
    if data.target_session_id == source.id:
        raise ValidationError(
            "A session cannot be merged into itself", field="target_session_id"
        )
    target = _require(repo, data.target_session_id)

    repo.move_members(source.id, target.id)

    now = datetime.now(timezone.utc)
    source.deleted_at = now
    source.updated_at = now
    source.image_count = 0
    source.start_at = None
    source.end_at = None
    source.thumbnail = None

    target.locked = True
    repo.recompute_bounds(target)
    session.add(source)
    session.add(target)
    session.commit()
    session.refresh(target)
    return target
