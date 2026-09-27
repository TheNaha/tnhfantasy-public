"""Image tags, and the facet query that answers "what used this?".

Router paths are mounted under `/api/v2` by `world_vault/__init__.py` with no
sub-prefix, so the public paths are:

    GET    /api/v2/asset/{asset_id}/tags   list one image's tags + provenance
    POST   /api/v2/asset/{asset_id}/tags   add a `user` tag (idempotent)
    DELETE /api/v2/asset/{asset_id}/tags/{tag}  remove a `user` tag
    GET    /api/v2/tags                    the vocabulary, by use-count
    POST   /api/v2/assets/auto-tag         BATCH JOB — see the warning below
    GET    /api/v2/assets/facet            the facet list + facet counts

## Why `/api/v2/assets/facet` exists at all, next to `/api/v2/assets`

`api/routes/files.py` owns `GET /api/v2/assets` and its filter vocabulary
(`workspace, character_id, story_id, search, sort, limit, cursor`). That module
was not editable for this change, so the facet query is its own endpoint rather
than extra query parameters on it — and it deliberately accepts the SAME
parameter names, the SAME sort names, the SAME keyset cursor encoding and
returns items in the SAME shape, so the frontend can swap one for the other
without a second adapter. Mirrored, in order:

* the filter vocabulary: `workspace`, `character_id`, `story_id`, `search`
  (identical `ilike` on `filename` OR the cast metadata document), plus `sort`,
  `limit` and a keyset `cursor`;
* the ordering expression, `coalesce(generated_at, created_at)`, with `id` as
  the tiebreak, so page 2 of a facet query and page 2 of the plain gallery are
  the same sequence;
* the cursor encoding: ISO-8601 timestamp for the date sorts, md5 hex for
  `random[:seed]`, and `limit+1` fetched with `has_more` derived from it;
* the item shape, built by the same
  `services.asset_reconciler._asset_as_file_data` and the same twelve extra
  fields, so a card renders identically from either endpoint.

NOT mirrored, and the differences are deliberate:

* `sort=name_asc|name_desc` is honoured here. `files.py`'s keyset path
  (`_list_assets_sync`) has no branch for the name sorts and silently returns
  `date_desc` for them — the name sort only exists on the older offset-based
  `/api/v2/gallery`. Ordering here is done in SQL, so the facet path never
  materialises the whole filtered set the way `_query_gallery_files` does.
* `limit` is bounded (1..200) rather than unbounded, and an unknown `sort` is a
  400 rather than a silent fallback to `date_desc`. A facet query with no
  upper bound is a self-inflicted denial of service; a typo that silently
  changes the order is a bug that reports itself six clicks later.
* The date-range filter uses the gallery's `coalesce(generated_at, created_at)`
  so the two endpoints agree on membership, which means it is NOT served by an
  index. The indexed equivalent is `assets.job_completed_at` (migration 068);
  it is a different column with different NULL behaviour, so using it here
  would silently disagree with the gallery. It is available as
  `?date_column=job_completed_at` for callers that want the index and accept
  the different set.
* `total_matched` is returned (the offset-based `/api/v2/gallery` returns a
  `total`; the keyset `/api/v2/assets` does not). A facet UI has to say
  "9,701 of 16,443" and one count over the filtered subquery is cheap.

## The batch warning

`POST /api/v2/assets/auto-tag` walks the whole `assets` table. On this
deployment that is 16,443 rows. It is `POST` rather than `GET` (a crawler or a
prefetching layer must not be able to trigger it), it is bounded by `limit`,
and it is resumable with `after_id`. **Never put it on a refresh interval.**
The same discipline as `POST /api/v2/sessions/detect`, which is the other
unbounded route in this app.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, func, select
from sqlalchemy import String, cast

from config import settings
from api.deps import get_session
from core.entities import Asset, AssetLora, AssetTag
from core.entities import Session as GenerationSession
from core.entities import SessionAsset
from core.exceptions import NotFoundError, ValidationError
from infrastructure.logging import get_logger
from services import tag_service
from services.asset_reconciler import _asset_as_file_data

logger = get_logger("tags_api")

router = APIRouter()

OUTPUT_DIR = settings.output_dir

# The gallery's default page size (files.py `_list_assets_sync`), and a ceiling
# this endpoint imposes on top of it.
DEFAULT_PAGE_LIMIT = 24
MAX_PAGE_LIMIT = 200

# Facet counts are one query per DIMENSION (never per value), so the cost is
# bounded by how many dimensions the client asks for. Three is enough to build
# a filter panel; more is a report, and reports do not belong in a gallery
# request.
MAX_FACET_DIMENSIONS = 3
DEFAULT_FACET_COUNTS = 24

MAX_SESSION_FACETS = 100
DEFAULT_SESSION_FACETS = 24

# Separator inside a `name_*` keyset cursor. \x1f is ASCII unit separator: it
# cannot appear in a filename, and unlike a comma it cannot appear in a tag.
_CURSOR_SEP = "\x1f"

FACET_DIMENSIONS = ("lora", "tag", "checkpoint", "character", "workspace", "session")
_DATE_SORTS = ("date_desc", "date_asc")
_NAME_SORTS = ("name_asc", "name_desc")

# Mirrors files.py's ordering expression exactly — see the module docstring.
_ORDER_TS = func.coalesce(Asset.generated_at, Asset.created_at)


# ── request DTOs ─────────────────────────────────────────────────────────────


class AssetTagCreate(BaseModel):
    """Body for adding a hand-typed tag to an image."""

    tag: str


class AutoTagRequest(BaseModel):
    """Body for the batch auto-tagger. `dry_run` first; `limit` always.

    `limit` defaults to a bounded value rather than "everything" on purpose:
    an unbounded pass over 16.4k assets is minutes of synchronous work, and a
    default that does the whole library is a default that gets fired by a
    double-click.
    """

    limit: int = Field(default=tag_service.DEFAULT_AUTO_TAG_LIMIT, ge=1, le=tag_service.MAX_AUTO_TAG_LIMIT)
    batch_size: int = Field(
        default=tag_service.DEFAULT_AUTO_TAG_BATCH_SIZE, ge=1, le=tag_service.MAX_AUTO_TAG_BATCH_SIZE
    )
    after_id: str | None = None
    dry_run: bool = False


# ── response DTOs ────────────────────────────────────────────────────────────


class AssetTagOut(BaseModel):
    tag: str
    source: str
    confidence: float | None = None
    created_at: datetime | None = None


class AssetTagListOut(BaseModel):
    asset_id: str
    tags: list[AssetTagOut]


class AssetTagWriteOut(BaseModel):
    status: str
    asset_id: str
    tag: str
    source: str
    created: bool


class TagVocabularyEntry(BaseModel):
    tag: str
    count: int
    user_count: int


class TagVocabularyOut(BaseModel):
    tags: list[TagVocabularyEntry]
    limit: int
    truncated: bool


class FacetCount(BaseModel):
    value: str
    count: int
    label: str | None = None


class FacetSessionOut(BaseModel):
    """A session containing at least one matching image.

    This is the answer to "which SESSIONS used this LoRA" — the question a
    facet on `assets` alone cannot answer, because the membership lives in
    `session_assets` and the LoRA lives in `asset_loras`; reaching it needs the
    two joined, which is what this one query does.
    """

    id: str
    name: str | None = None
    workspace: str | None = None
    thumbnail: str | None = None
    matching_images: int
    image_count: int
    created_at: datetime
    updated_at: datetime


class FacetOut(BaseModel):
    """Same `items` / `has_more` / `next_cursor` shape as `GET /api/v2/assets`,
    plus the facet-specific fields."""

    items: list[dict]
    has_more: bool
    next_cursor: str | None = None
    # `None` when `include_total=false`: the keyset endpoint does not return a
    # total either, and a caller that opted out should not have to distinguish
    # "no total" from a real number.
    total_matched: int | None = None
    facets: dict[str, list[FacetCount]] = Field(default_factory=dict)
    sessions: list[FacetSessionOut] = Field(default_factory=list)


# ── tag routes ───────────────────────────────────────────────────────────────


@router.get("/asset/{asset_id}/tags", response_model=AssetTagListOut)
def list_asset_tags(asset_id: str, session: Session = Depends(get_session)):
    """Every tag on an image, with the provenance the UI groups by."""
    return {"asset_id": asset_id, "tags": tag_service.list_asset_tags(session, asset_id)}


@router.post("/asset/{asset_id}/tags", response_model=AssetTagWriteOut, status_code=201)
def add_asset_tag(asset_id: str, data: AssetTagCreate, session: Session = Depends(get_session)):
    """Add a `source='user'` tag. Idempotent; re-adding reports `created: false`.

    This is the writer path that would otherwise not exist: without it, an
    image's tags could only ever come from the auto-tagger, which re-derives
    them from LoRA metadata and would overwrite any correction.
    """
    result = tag_service.add_user_tag(session, asset_id, data.tag)
    return {"status": "success", "asset_id": asset_id, **result}


@router.delete("/asset/{asset_id}/tags/{tag:path}", response_model=AssetTagWriteOut)
def remove_asset_tag(asset_id: str, tag: str, session: Session = Depends(get_session)):
    """Remove a `source='user'` tag.

    404 when there is no such user tag, including when the tag exists but is
    auto-derived: a rescan would put it straight back, so a "delete" that
    appears to work and then resurrects itself is worse than a 404. Mirrors
    `api/routes/models/maintenance.remove_user_model_tag_endpoint`.

    The tag is a path segment and MUST be percent-encoded by the client —
    `encodeURIComponent` in the browser, `quote(tag, safe='')` in Python. The
    `{tag:path}` converter is there so a tag that itself contains `/` (a
    CivitAI trained word like `Zeta/ゼータ` is a real one) survives the round
    trip instead of 404ing on a slash.
    """
    if not tag_service.remove_user_tag(session, asset_id, tag):
        raise NotFoundError("Asset tag", f"No user tag '{tag}' on asset '{asset_id}'")
    return {
        "status": "success",
        "asset_id": asset_id,
        "tag": tag_service.normalise_tag(tag),
        "source": tag_service.ASSET_TAG_SOURCE_USER,
        "created": False,
    }


@router.get("/tags", response_model=TagVocabularyOut)
def list_tag_vocabulary(
    prefix: str | None = Query(None, description="Anchored prefix — the autocomplete's mode."),
    q: str | None = Query(None, description="Unanchored substring, for a looser search."),
    limit: int = Query(50, ge=1, le=500),
    session: Session = Depends(get_session),
):
    """The distinct tag vocabulary with use-counts, most-used first.

    Use-count order is the point: an alphabetical list of a few thousand booru
    tokens is a list nobody scrolls. Send `prefix` for typeahead (it rides the
    `varchar_pattern_ops` index from migration 073) and `q` when the user is
    recalling a tag rather than completing one.
    """
    rows = tag_service.list_tag_vocabulary(
        session, prefix=prefix, query=q, limit=limit
    )
    return {"tags": rows, "limit": limit, "truncated": len(rows) > limit}


@router.post("/assets/auto-tag")
def auto_tag_assets(data: AutoTagRequest, session: Session = Depends(get_session)):
    """Re-derive auto tags for live assets. BATCH JOB — never poll this.

    Walks the whole `assets` table, so on this deployment (~16.4k assets) it is
    seconds of synchronous work inside a request. It is `POST` (a crawler or a
    prefetcher must not be able to trigger it), bounded by `limit`, and
    resumable: pass the `last_asset_id` from one call as `after_id` on the
    next. Use `dry_run` to see the scale before writing anything.

    User tags are never touched — only `source='auto'` rows are replaced, and
    a tag a human already owns is skipped rather than duplicated.

    `GET /api/v2/tags` is the cheap path. Nothing the UI needs to render tags
    requires this call.
    """
    summary = tag_service.reindex_asset_tags(
        session,
        batch_size=data.batch_size,
        limit=data.limit,
        after_id=data.after_id,
        dry_run=data.dry_run,
    )
    logger.info("asset_auto_tag", **{k: v for k, v in summary.items() if k != "last_asset_id"})
    return {"status": "success", "max_auto_tags_per_asset": tag_service.MAX_AUTO_TAGS_PER_ASSET, **summary}


# ── the facet query ──────────────────────────────────────────────────────────


@dataclass
class AssetFacetFilters:
    """The gallery filter vocabulary plus the facet dimensions.

    A plain dataclass rather than a pydantic model: the route validates and
    coerces every field before building this, and the builder below is also
    called by the facet-count path with one dimension deliberately left out.
    """

    workspace: str | None = None
    character_id: str | None = None
    story_id: str | None = None
    search: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    # Which timestamp the range applies to. `gallery` is the gallery's own
    # coalesce (unindexed, but identical membership); `job_completed_at` is the
    # indexed column from migration 068 and is a different set.
    date_column: str = "gallery"
    lora_civitai_ids: tuple[int, ...] = ()
    lora_model_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    checkpoints: tuple[str, ...] = ()
    session_ids: tuple[str, ...] = ()


def _parse_id_list(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(part for part in (p.strip() for p in raw.split(",")) if part)


def _parse_int_list(raw: str | None, field: str) -> tuple[int, ...]:
    values: list[int] = []
    for part in _parse_id_list(raw):
        try:
            values.append(int(part))
        except ValueError:
            raise ValidationError(
                f"{field} must be a comma-separated list of integers", field=field
            )
    return tuple(values)


def _parse_instant(raw: str | None, field: str) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationError(f"{field} must be an ISO-8601 timestamp", field=field)
    if parsed.tzinfo is None:
        # The columns are tz-aware; a naive bound would be compared against an
        # aware value and Postgres would raise rather than guess a zone.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _date_column(filters: AssetFacetFilters):
    if filters.date_column == "job_completed_at":
        return Asset.job_completed_at
    return _ORDER_TS


def build_asset_query(filters: AssetFacetFilters, exclude: str | None = None):
    """The filtered asset query. `exclude` drops one facet dimension's filter.

    Every facet dimension is an `IN (SELECT ...)` semi-join rather than a
    JOIN, which is the whole reason this is a query and not a loop: the
    subquery is served by the index on the dimension's own column
    (`idx_asset_lora_civitai`, `ix_asset_tags_tag`, `ix_session_assets_session_id`),
    returns asset ids, and the outer scan stays on `assets` with no row
    multiplication — so applying two tags cannot duplicate an image, and
    `LIMIT` after `ORDER BY` is correct without a DISTINCT.

    Within a dimension the values are OR-ed (`IN`), across dimensions they are
    AND-ed. That is the behaviour a filter panel expects: two tags widen the
    result, a tag plus a LoRA narrows it.
    """
    statement = select(Asset).where(Asset.deleted_at.is_(None))

    if filters.workspace:
        statement = statement.where(Asset.workspace == filters.workspace)
    if filters.character_id:
        statement = statement.where(Asset.character_id == filters.character_id)
    if filters.story_id:
        statement = statement.where(Asset.story_id == filters.story_id)
    if filters.search:
        like = f"%{filters.search}%"
        # Identical to files.py `_list_assets_sync`: filename OR the cast
        # metadata document.
        statement = statement.where(
            (Asset.filename.ilike(like)) | (Asset.metadata_.cast(String).ilike(like))
        )

    column = _date_column(filters)
    if filters.date_from is not None:
        statement = statement.where(column >= filters.date_from)
    if filters.date_to is not None:
        statement = statement.where(column <= filters.date_to)

    if exclude != "lora" and (filters.lora_civitai_ids or filters.lora_model_ids):
        conditions = []
        if filters.lora_civitai_ids:
            conditions.append(AssetLora.civitai_model_id.in_(filters.lora_civitai_ids))
        if filters.lora_model_ids:
            conditions.append(AssetLora.model_id.in_(filters.lora_model_ids))
        statement = statement.where(
            Asset.id.in_(select(AssetLora.asset_id).where(*conditions))
        )

    if exclude != "tag" and filters.tags:
        statement = statement.where(
            Asset.id.in_(select(AssetTag.asset_id).where(AssetTag.tag.in_(filters.tags)))
        )

    if exclude != "checkpoint" and filters.checkpoints:
        statement = statement.where(Asset.checkpoint_name.in_(filters.checkpoints))

    if exclude != "session" and filters.session_ids:
        statement = statement.where(
            Asset.id.in_(
                select(SessionAsset.asset_id).where(
                    SessionAsset.session_id.in_(filters.session_ids)
                )
            )
        )

    return statement


def _asset_cursor_codec():
    """`files.py`'s composite `(timestamp, id)` cursor codec, by import.

    Imported lazily rather than at module scope because `files.py` includes this
    module's world-vault siblings, and a top-level import would close that loop
    for the sake of two one-line functions. Resolved once per call; the module
    object is already in `sys.modules` by the time a request arrives.
    """
    from api.routes.files import _decode_asset_cursor, _encode_asset_cursor

    return _decode_asset_cursor, _encode_asset_cursor


def _apply_keyset(statement, sort: str, cursor: str | None, seed: str):
    """Apply the cursor predicate and the ORDER BY for a sort.

    `date_*` and `random` use `files.py`'s cursor codec, imported rather than
    reimplemented, so a cursor from the gallery endpoint really is accepted here.
    The docstring used to CLAIM that byte-compatibility while this function used
    a different separator (`\x1f` vs `|`) and `_parse_instant`, which runs
    `fromisoformat` over the whole composite string — so a real gallery cursor
    raised `ValidationError: cursor must be an ISO-8601 timestamp`. A comment
    that invites a caller to rely on a contract is worse than no comment, so
    the claim is now enforced rather than asserted.

    `name_*` has no `files.py` equivalent and keeps its own `(filename, id)`
    grammar, but uses the same composite predicate shape so all three sorts
    paginate by a total order.

    The `date_*` predicate used to compare the timestamp alone while the ORDER BY
    carried an `Asset.id` tiebreak. That is not a total order, so page 2
    re-served every row sharing the boundary timestamp — a duplicate page at
    exactly the boundary an infinite scroll is most likely to land on.
    """
    if sort in _DATE_SORTS:
        if cursor:
            decode_cursor, _ = _asset_cursor_codec()
            moment, asset_id = decode_cursor(cursor)
            if moment is None:
                raise ValidationError("cursor is not valid for this sort", field="cursor")
            descending = sort == "date_desc"
            if asset_id is None:
                # A bare timestamp — the cursor shape this endpoint issued
                # before the composite existed. Re-serve its ties rather than
                # dropping them; the cost is a one-page duplicate at a boundary
                # the client has to scroll through once, and it heals itself
                # because page N+1 onwards is composite.
                statement = statement.where(
                    _ORDER_TS <= moment if descending else _ORDER_TS >= moment
                )
            else:
                # The total-order predicate over `(ts, id)`, written out as a
                # disjunction because SQLite only gained row-value support in
                # 3.15 and the tests run on SQLite.
                past_ts = _ORDER_TS < moment if descending else _ORDER_TS > moment
                tied = _ORDER_TS == moment
                past_id = Asset.id < asset_id if descending else Asset.id > asset_id
                statement = statement.where(past_ts | (tied & past_id))
        if sort == "date_asc":
            return statement.order_by(_ORDER_TS.asc(), Asset.id.asc())
        return statement.order_by(_ORDER_TS.desc(), Asset.id.desc())

    if sort in _NAME_SORTS:
        ascending = sort == "name_asc"
        if cursor:
            filename, _, asset_id = cursor.rpartition(_CURSOR_SEP)
            if not asset_id:
                raise ValidationError("cursor is not valid for this sort", field="cursor")
            # (filename, id) compared as a pair, written out because SQLite only
            # gained row-value support in 3.15 and the tests run on SQLite.
            # The id comparison is only consulted on a filename tie, which is
            # what keeps the ordering total and the keyset non-overlapping.
            past_name = Asset.filename > filename if ascending else Asset.filename < filename
            tied = Asset.filename == filename
            past_id = Asset.id > asset_id if ascending else Asset.id < asset_id
            statement = statement.where(past_name | (tied & past_id))
        column = Asset.filename.asc() if ascending else Asset.filename.desc()
        tiebreak = Asset.id.asc() if ascending else Asset.id.desc()
        return statement.order_by(column, tiebreak)

    # random[:seed] — same hash column as files.py, so the shuffle is the same
    # shuffle for a given seed.
    hash_col = func.md5(func.concat(cast(Asset.id, String), seed))
    if cursor:
        statement = statement.where(hash_col > cursor)
    return statement.order_by(hash_col.asc())


def _next_cursor(sort: str, seed: str, asset: Asset | None, has_more: bool) -> str | None:
    if not has_more or asset is None:
        return None
    if sort.startswith("random"):
        return hashlib.md5(f"{asset.id}{seed}".encode()).hexdigest()
    if sort in _NAME_SORTS:
        return f"{asset.filename}{_CURSOR_SEP}{asset.id}"
    order_ts = asset.generated_at or asset.created_at
    _, encode_cursor = _asset_cursor_codec()
    return encode_cursor(order_ts, asset.id) if order_ts else None


def _seed_for(sort: str) -> str:
    if sort.startswith("random:"):
        return sort.split(":", 1)[1]
    return "stable_random_seed"


def _validate_sort(sort: str) -> None:
    if sort in _DATE_SORTS or sort in _NAME_SORTS:
        return
    if sort == "random" or sort.startswith("random:"):
        return
    raise ValidationError(
        f"sort must be one of {', '.join((*_DATE_SORTS, *_NAME_SORTS))}, random, or random:<seed>",
        field="sort",
    )


def _facet_item(asset: Asset) -> dict:
    """The gallery item shape. Mirrors `files.py` `_list_assets_sync` exactly.

    Same builder, same twelve extra fields, so a card renders identically from
    `GET /api/v2/assets` and from `GET /api/v2/assets/facet`.
    """
    item = _asset_as_file_data(asset, OUTPUT_DIR)
    item.update(
        {
            "id": asset.id,
            "filename": asset.filename,
            "relative_path": asset.relative_path,
            "thumbnail": f"/api/thumbnail/medium/{asset.relative_path}",
            "file_url": f"/api/v2/assets/{asset.id}/file",
            "thumb_url": (
                f"/api/v2/assets/{asset.id}/thumb"
                if asset.thumbnail_relative_path
                else f"/api/v2/assets/{asset.id}/file"
            ),
            "workspace": asset.workspace,
            "character_id": asset.character_id,
            "story_id": asset.story_id,
            "width": asset.width,
            "height": asset.height,
            "blurhash": asset.blurhash,
            "created_at": asset.created_at.isoformat() if asset.created_at else None,
            "metadata": asset.metadata_ or {},
        }
    )
    return item


# One query per dimension. A facet count is computed with that dimension's own
# filter REMOVED, so the panel can offer the alternatives for the dimension the
# user is currently filtering on — counting with the filter still applied would
# report 1 for every row and make the panel useless.
#
# The column dimensions are named by ATTRIBUTE, not by `InstrumentedAttribute`,
# because the count query selects from the *subquery* of the filtered asset
# query, not from `assets`. Referencing `Asset.checkpoint_name` there would put
# `assets` back into the FROM alongside the subquery with no join condition —
# a cartesian product, which SQLAlchemy warns about and which returns
# meaningless counts.
_COLUMN_DIMENSIONS = {
    "checkpoint": "checkpoint_name",
    "character": "character_id",
    "workspace": "workspace",
}
_JOIN_DIMENSIONS = {
    "lora": (AssetLora, AssetLora.civitai_model_id),
    "tag": (AssetTag, AssetTag.tag),
    "session": (SessionAsset, SessionAsset.session_id),
}


def _matched_ids(filters: AssetFacetFilters, exclude: str | None = None):
    """The filtered asset ids, as a subquery.

    A `Subquery` rather than `select(subquery.c.id)`: passing a subquery column
    to `select()` makes SQLModel treat it as a FROM element, which both drops
    the join and raises `TypeError: 'int' object is not subscriptable` when the
    result is unpacked.
    """
    return build_asset_query(filters, exclude=exclude).subquery()


def _facet_counts(
    session: Session, filters: AssetFacetFilters, dimension: str, limit: int
) -> list[FacetCount]:
    matched = _matched_ids(filters, exclude=dimension)

    if dimension in _COLUMN_DIMENSIONS:
        column = matched.c[_COLUMN_DIMENSIONS[dimension]]
        rows = session.exec(
            select(column, func.count())
            .select_from(matched)
            .where(column.is_not(None))
            .group_by(column)
            .order_by(func.count().desc(), column)
            .limit(limit)
        ).all()
        return [FacetCount(value=str(value), count=int(count)) for value, count in rows]

    model, column = _JOIN_DIMENSIONS[dimension]
    if dimension == "lora":
        # A CivitAI id is a number and useless to render, so the label comes
        # from the model we imported. `models_v2.civitai_model_id` is indexed,
        # and the join is optional: most applied LoRAs are not installed, which
        # is exactly why `civitai_model_id` is the facet's primary key.
        from core.entities import ModelV2

        rows = session.exec(
            select(AssetLora.civitai_model_id, func.count(), func.max(ModelV2.name))
            .select_from(AssetLora)
            .outerjoin(ModelV2, ModelV2.civitai_model_id == AssetLora.civitai_model_id)
            .where(
                AssetLora.asset_id.in_(select(matched.c.id)),
                AssetLora.civitai_model_id.is_not(None),
            )
            .group_by(AssetLora.civitai_model_id)
            .order_by(func.count().desc(), AssetLora.civitai_model_id)
            .limit(limit)
        ).all()
        return [
            FacetCount(value=str(value), count=int(count), label=label)
            for value, count, label in rows
        ]

    rows = session.exec(
        select(column, func.count())
        .select_from(model)
        .where(model.asset_id.in_(select(matched.c.id)), column.is_not(None))
        .group_by(column)
        .order_by(func.count().desc(), column)
        .limit(limit)
    ).all()
    return [FacetCount(value=str(value), count=int(count)) for value, count in rows]


def _matching_sessions(
    session: Session, filters: AssetFacetFilters, limit: int
) -> list[FacetSessionOut]:
    """Sessions containing at least one image matching the facet filters.

    One query: `session_assets` joined to the filtered asset set, grouped by
    session. This is the direction a facet on `assets` cannot reach — the LoRA
    is in `asset_loras` and the membership in `session_assets`, and nothing
    denormalises the two together.
    """
    matched = _matched_ids(filters)
    rows = session.exec(
        select(GenerationSession, func.count(SessionAsset.id))
        .join(SessionAsset, SessionAsset.session_id == GenerationSession.id)
        .where(
            GenerationSession.deleted_at.is_(None),
            SessionAsset.asset_id.in_(select(matched.c.id)),
        )
        .group_by(GenerationSession.id)
        .order_by(func.count(SessionAsset.id).desc(), GenerationSession.updated_at.desc())
        .limit(limit)
    ).all()
    return [
        FacetSessionOut(
            id=row.id,
            name=row.name,
            workspace=row.workspace,
            thumbnail=row.thumbnail,
            matching_images=int(matched_count),
            image_count=row.image_count,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row, matched_count in rows
    ]


@router.get("/assets/facet", response_model=FacetOut)
def facet_assets(
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    cursor: str | None = None,
    workspace: str | None = None,
    character_id: str | None = None,
    story_id: str | None = None,
    search: str | None = None,
    sort: str = Query("date_desc"),
    lora: str | None = Query(
        None, description="Comma-separated CivitAI model ids (asset_loras.civitai_model_id)."
    ),
    lora_model: str | None = Query(
        None, description="Comma-separated internal models_v2 ids (asset_loras.model_id)."
    ),
    tag: str | None = Query(None, description="Comma-separated tags. OR-ed within the facet."),
    checkpoint: str | None = Query(None, description="Comma-separated assets.checkpoint_name values."),
    session_id: str | None = Query(None, description="Comma-separated session ids."),
    date_from: str | None = Query(None, description="ISO-8601 lower bound, inclusive."),
    date_to: str | None = Query(None, description="ISO-8601 upper bound, inclusive."),
    date_column: str = Query(
        "gallery",
        description="'gallery' = coalesce(generated_at, created_at), identical to /api/v2/assets; 'job_completed_at' = the indexed column, a different set.",
    ),
    group_by: str | None = Query(
        None,
        description=f"Comma-separated dimensions to count, from: {', '.join(FACET_DIMENSIONS)}. "
        f"Maximum {MAX_FACET_DIMENSIONS}; one query per dimension.",
    ),
    facet_limit: int = Query(DEFAULT_FACET_COUNTS, ge=1, le=200),
    include_sessions: bool = Query(False),
    session_limit: int = Query(DEFAULT_SESSION_FACETS, ge=1, le=MAX_SESSION_FACETS),
    include_total: bool = Query(True),
    session: Session = Depends(get_session),
):
    """Facet-filtered asset listing, with the facet counts a filter panel needs.

    Synchronous on purpose: FastAPI runs a `def` route in its threadpool, so
    the counting queries are off the event loop without opening a second
    session — the same reasoning as `files.py`'s `asyncio.to_thread`, and the
    session stays request-scoped.
    """
    _validate_sort(sort)
    if date_column not in ("gallery", "job_completed_at"):
        raise ValidationError(
            "date_column must be 'gallery' or 'job_completed_at'", field="date_column"
        )

    filters = AssetFacetFilters(
        workspace=workspace,
        character_id=character_id,
        story_id=story_id,
        search=search,
        date_from=_parse_instant(date_from, "date_from"),
        date_to=_parse_instant(date_to, "date_to"),
        date_column=date_column,
        lora_civitai_ids=_parse_int_list(lora, "lora"),
        lora_model_ids=_parse_id_list(lora_model),
        tags=_parse_id_list(tag),
        checkpoints=_parse_id_list(checkpoint),
        session_ids=_parse_id_list(session_id),
    )
    if filters.date_from and filters.date_to and filters.date_from > filters.date_to:
        raise ValidationError("date_from must not be after date_to", field="date_from")

    dimensions = _parse_id_list(group_by)
    unknown = [d for d in dimensions if d not in FACET_DIMENSIONS]
    if unknown:
        raise ValidationError(
            f"Unknown group_by dimension(s): {', '.join(unknown)}; "
            f"choose from {', '.join(FACET_DIMENSIONS)}",
            field="group_by",
        )
    if len(dimensions) > MAX_FACET_DIMENSIONS:
        raise ValidationError(
            f"At most {MAX_FACET_DIMENSIONS} group_by dimensions per request",
            field="group_by",
        )

    seed = _seed_for(sort)
    paged = _apply_keyset(
        build_asset_query(filters), sort, cursor, seed
    ).limit(limit + 1)
    rows = session.exec(paged).all()
    has_more = len(rows) > limit
    page = rows[:limit]

    facets: dict[str, list[FacetCount]] = {}
    for dimension in dimensions:
        facets[dimension] = _facet_counts(session, filters, dimension, facet_limit)

    # One count over the filtered subquery. `.one()` already returns the scalar
    # here — SQLModel unwraps a single-column select — so indexing it raised
    # `TypeError: 'int' object is not subscriptable`.
    total_matched = (
        session.exec(
            select(func.count()).select_from(_matched_ids(filters))
        ).one()
        if include_total
        else None
    )

    return {
        "items": [_facet_item(a) for a in page],
        "has_more": has_more,
        "next_cursor": _next_cursor(sort, seed, page[-1] if page else None, has_more),
        "total_matched": total_matched,
        "facets": facets,
        "sessions": (
            _matching_sessions(session, filters, session_limit)
            if include_sessions
            else []
        ),
    }
