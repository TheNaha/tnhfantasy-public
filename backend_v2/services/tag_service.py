"""Tags on images: the user writer path, the vocabulary, and the auto-tagger.

## Why tags are rows and not a JSONB array

`assets.metadata_` is ~70 MB of jsonb across this deployment and every `->>`
against it re-reads and re-parses the whole document — which is the reason
migration 067 promoted `checkpoint_name`, `sampler`, `steps` and friends out to
real columns. Tags are the same argument one step further: "which images carry
this tag" and "which images used this LoRA" both have to be answerable as
*joins* to reach `session_assets`, and a JSONB array can only be containment-
searched at the asset level. `core.entities.AssetTag` follows
`core.entities.AssetLora` for the same reason, and `core.entities.ModelTag`
for the same provenance discipline.

There is deliberately **no** vocabulary table with a denormalised use-count.
The one thing it would buy is a pre-computed count, and the count is a
`GROUP BY` over this table — one query, no second write on the tag path, and no
counter that can drift from the rows it counts. The project stores tag strings
two other ways without a vocabulary table (`model_tags.tag`, and
`locations.tags` as a GIN-indexed JSONB array), so a third shape is not the
missing piece.

## Provenance, and the one thing the auto-tagger may never do

An auto tag is inferred from the LoRAs an image used, not observed on the
image, so it is *weaker* evidence than a human typing it:

* `source='auto'` — written by `auto_tag_asset`, re-derived on every pass.
* `source='user'` — written by `add_user_tag`; the auto-tagger replaces only
  its own rows and never touches these, and `remove_user_tag` only ever deletes
  `source='user'` rows. Without that, "I disagree with this tag" could not be
  expressed and a re-run would resurrect what the user just deleted.

`confidence` records *how* an auto tag was derived (`extract_tag_evidence`:
trained word 0.9, CivitAI catalogue tag 0.5) so the UI can show the difference
and a later re-tagger has something to rank by. A user tag stores NULL: "the
human said so" is not a point on a confidence scale.

## The batch contract

`reindex_asset_tags` walks the whole `assets` table in keyset batches, commits
per batch, and is resumable with `after_id` — the same contract as
`reindex_asset_loras` in `services.asset_metadata_index.py`, which is the
precedent for a batch job over assets. On 16.4k assets it is seconds of
synchronous work inside an HTTP request, so the route that calls it is `POST`,
bounded by `limit`, and documented as not-polling (see
`api/routes/gallery/tags.py`).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlmodel import Session, delete, func, select
from sqlalchemy import case, true

from core.entities import Asset, AssetTag
from core.exceptions import NotFoundError, ValidationError
from core.sql_search import (
    LIKE_ESCAPE_CHAR,
    like_contains,
    like_startswith,
)
from services.asset_metadata_index import (
    DEFAULT_BATCH_SIZE,
    extract_tag_evidence,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ASSET_TAG_SOURCE_AUTO",
    "ASSET_TAG_SOURCE_USER",
    "DEFAULT_AUTO_TAG_LIMIT",
    "NOT_TOMBSTONED_ASSET_IDS",
    "MAX_AUTO_TAGS_PER_ASSET",
    "MAX_TAG_LENGTH",
    "add_user_tag",
    "auto_tag_asset",
    "list_asset_tags",
    "list_tag_vocabulary",
    "normalise_tag",
    "reindex_asset_tags",
    "remove_user_tag",
]

# Tag provenance. Two sources and no more — see the module docstring. Note the
# absence of a 'civitai' source: a CivitAI tag on an *image* is only ever
# inferred from the LoRA that carried it.
ASSET_TAG_SOURCE_AUTO = "auto"
ASSET_TAG_SOURCE_USER = "user"

# Long enough for "pose: kneeling hands up, 4h, hires, character-loRA" and short
# enough that the whole vocabulary stays a reasonable list in the UI. Same bound
# as `api/routes/models/maintenance.py`.
MAX_TAG_LENGTH = 64

# The ids of every *tombstoned* asset — the complement of the live set, and the
# cheap way to say "is this row live" without a mis-estimate.
#
# `Asset.deleted_at IS NULL` is 97.8% true on this deployment but PostgreSQL
# costs every `IS NULL` test at a hard-coded 0.5% selectivity, so a planner given
# the direct form budgets an 85-row lookup table and nested-loops the *scanning*
# side against `assets_pkey` once per distinct id — measured at 16,514 index
# descents for `/api/v2/tags`. Negated, the build side is the few hundred
# tombstoned ids, `ix_assets_deleted_at` already covers it, and the join hashes.
# Exported because `api/routes/gallery/tags.py` needs the identical
# predicate: two copies of a liveness rule is two places to drift.
#
# `Asset.id` is NOT NULL, which is what makes `NOT IN` safe here — `NOT IN`
# against a subquery that can yield NULL matches nothing at all.
NOT_TOMBSTONED_ASSET_IDS = select(Asset.id).where(Asset.deleted_at.is_not(None))

# Ceiling on auto tags stored per image. A four-LoRA image can offer over a
# hundred distinct tokens (MAX_MODEL_TAGS per reference, and trained words are
# unbounded up to their own cap), and 16.4k assets times an unbounded list is
# millions of rows of mostly-nothing. The cap takes the strongest evidence
# first, which is the trained-word evidence, and ties break on the tag text so
# two runs over the same metadata select the same rows.
MAX_AUTO_TAGS_PER_ASSET = 40

# The auto-tagger's defaults and ceilings. A single unbounded POST over 16.4k
# assets is minutes of commit-bound work; the ceilings make an accidental
# unbounded call fail fast instead.
DEFAULT_AUTO_TAG_BATCH_SIZE = DEFAULT_BATCH_SIZE
MAX_AUTO_TAG_BATCH_SIZE = 2_000
DEFAULT_AUTO_TAG_LIMIT = 2_000
MAX_AUTO_TAG_LIMIT = 50_000


def normalise_tag(raw_tag: str) -> str:
    """Trim and length-bound a tag, or raise.

    Whitespace inside a tag is collapsed rather than rejected, so "pose:
    kneeling" and "pose:  kneeling" are the same tag and the unique constraint
    on (asset_id, tag) actually holds.
    """
    tag = " ".join((raw_tag or "").split())
    if not tag:
        raise ValidationError("Tag must not be empty", field="tag")
    if len(tag) > MAX_TAG_LENGTH:
        raise ValidationError(
            f"Tag must be {MAX_TAG_LENGTH} characters or fewer", field="tag"
        )
    return tag


def _require_asset(session: Session, asset_id: str) -> Asset:
    asset = session.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None:
        raise NotFoundError("Asset", asset_id)
    return asset


# ── the user writer path ─────────────────────────────────────────────────────


def add_user_tag(session: Session, asset_id: str, raw_tag: str) -> dict:
    """Attach a `source='user'` tag to an image. Idempotent.

    Re-adding an existing tag returns it unchanged rather than tripping
    `uq_asset_tag`. A tag the auto-tagger also derived is kept as the single
    existing row instead of being duplicated — and is left with the weaker
    `confidence`, because `uq_asset_tag` is on (asset_id, tag): promoting it
    would mean rewriting the tagger's row, which is exactly the write this
    function does not have. The user can re-type a tag to make their own
    assertion; the auto row is not silently upgraded on the way past.
    """
    _require_asset(session, asset_id)
    tag = normalise_tag(raw_tag)

    existing = session.exec(
        select(AssetTag).where(AssetTag.asset_id == asset_id, AssetTag.tag == tag)
    ).first()
    if existing:
        return {
            "tag": existing.tag,
            "source": existing.source,
            "created": False,
        }

    session.add(
        AssetTag(
            asset_id=asset_id,
            tag=tag,
            source=ASSET_TAG_SOURCE_USER,
            confidence=None,
        )
    )
    session.commit()
    return {"tag": tag, "source": ASSET_TAG_SOURCE_USER, "created": True}


def remove_user_tag(session: Session, asset_id: str, raw_tag: str) -> bool:
    """Remove a `source='user'` tag. Returns True if a row was deleted.

    Refuses to touch an auto tag, exactly as
    `api/routes/models/maintenance.py` refuses to delete a CivitAI-owned model
    tag: the next auto-tagger pass would put it straight back, so a "delete"
    that appears to work and then resurrects itself on the next batch is worse
    than a 404.
    """
    _require_asset(session, asset_id)
    tag = normalise_tag(raw_tag)

    row = session.exec(
        select(AssetTag).where(
            AssetTag.asset_id == asset_id,
            AssetTag.tag == tag,
            AssetTag.source == ASSET_TAG_SOURCE_USER,
        )
    ).first()
    if not row:
        return False

    session.delete(row)
    session.commit()
    return True


def list_asset_tags(session: Session, asset_id: str) -> list[dict]:
    """Every tag on an image with its provenance, for the UI to group by."""
    _require_asset(session, asset_id)

    rows = session.exec(
        select(AssetTag)
        .where(AssetTag.asset_id == asset_id)
        .order_by(AssetTag.source.desc(), AssetTag.tag)
    ).all()
    return [
        {
            "tag": r.tag,
            "source": r.source,
            "confidence": r.confidence,
            "created_at": r.created_at,
        }
        for r in rows
    ]


# ── the vocabulary ───────────────────────────────────────────────────────────


class TagVocabulary(list):
    """A vocabulary page plus whether more exist beyond `limit`.

    A `list` subclass rather than a `(rows, truncated)` tuple so every existing
    reader — `len(...)`, iteration, `row["tag"]` — is untouched, and the route
    can report `truncated` without fetching a second page.
    """

    def __init__(self, rows: list[dict], truncated: bool):
        super().__init__(rows)
        self.truncated = truncated


def list_tag_vocabulary(
    session: Session,
    *,
    prefix: str | None = None,
    query: str | None = None,
    limit: int = 50,
) -> TagVocabulary:
    """Distinct tags with how many live images carry each, most-used first.

    Ordering by use-count is what makes a picker usable: an alphabetical list of
    a few thousand booru tokens is a list nobody scrolls, and the tags worth
    offering are the ones that already describe something in the library. Tag
    text breaks ties so the order is stable between calls.

    `prefix` is anchored (`tag LIKE 'bl%'`) and is the one the autocomplete
    should send: on this deployment's `en_US.utf8` collation a default btree is
    unusable for a prefix LIKE, which is what the `varchar_pattern_ops` index
    created by migration 073 is for. `query` is an unanchored substring for the
    "I know roughly what it is called" case, and is a scan — the endpoint caps
    it and the payload it scans is tag text, not the 70 MB metadata document.

    Soft-deleted assets are excluded: a tombstoned image should not keep a tag
    alive in the picker. That exclusion is `NOT_TOMBSTONED_ASSET_IDS` rather than
    `deleted_at IS NULL` — see its definition for the measured reason; the short
    version is that PostgreSQL costs an `IS NULL` test at a fixed 0.5%
    selectivity, so the direct form planned a memoized `assets_pkey` descent per
    distinct asset id (16,514 of them) and the negated form plans a hash of the
    389 tombstoned ids instead.
    """
    statement = select(
        AssetTag.tag,
        func.count(AssetTag.id),
        # `case` rather than a dialect-specific boolean sum: the same query
        # has to run on the SQLite the tests use and the Postgres it runs on
        # in production.
        func.sum(case((AssetTag.source == ASSET_TAG_SOURCE_USER, 1), else_=0)),
    ).where(AssetTag.asset_id.notin_(NOT_TOMBSTONED_ASSET_IDS))
    if prefix:
        normalised = " ".join(prefix.split())
        if len(normalised) > MAX_TAG_LENGTH:
            raise ValidationError(
                f"Prefix must be {MAX_TAG_LENGTH} characters or fewer", field="prefix"
            )
        statement = statement.where(
            AssetTag.tag.like(like_startswith(normalised), escape=LIKE_ESCAPE_CHAR)
        )
    if query:
        statement = statement.where(
            AssetTag.tag.ilike(like_contains(query.strip()), escape=LIKE_ESCAPE_CHAR)
        )
    statement = (
        statement.group_by(AssetTag.tag)
        .order_by(func.count(AssetTag.id).desc(), AssetTag.tag)
        .limit(limit + 1)
    )

    fetched = session.exec(statement).all()
    # The probe row is not a result: returning it made `?limit=50` answer with
    # 51 tags. It is reported separately, as a flag, so the caller can still
    # tell there is more.
    rows = [
        {
            "tag": tag,
            "count": int(count),
            "user_count": int(user_count or 0),
        }
        for tag, count, user_count in fetched[:limit]
    ]
    return TagVocabulary(rows, truncated=len(fetched) > limit)


# ── the auto-tagger ──────────────────────────────────────────────────────────


def auto_tag_asset(session: Session, asset: Asset) -> tuple[int, int, int]:
    """Re-derive one image's auto tags. Returns `(seen, written, skipped_user)`.

    Delete-then-insert, the same convergence shape as `index_asset_loras`: the
    auto rows for this image are removed and rebuilt from the current
    derivation, so a LoRA whose CivitAI tags changed upstream does not leave a
    stale tag behind forever. The delete is a Core `delete()`, executed
    immediately, NOT `session.delete()` on loaded ORM rows: within one flush
    SQLAlchemy emits INSERTs before DELETEs, and a re-insert of a tag whose row
    is still pending deletion would fail `uq_asset_tag`.
    """
    evidence = extract_tag_evidence(asset.metadata_ or None)
    if not evidence:
        # Still delete: the image may have had auto tags derived before, and a
        # later pass that finds no vocabulary must converge to zero tags, not
        # leave the old set in place.
        session.exec(
            delete(AssetTag).where(
                AssetTag.asset_id == asset.id,
                AssetTag.source == ASSET_TAG_SOURCE_AUTO,
            )
        )
        return (0, 0, 0)

    # Strongest evidence first; tag text breaks ties so the cap is deterministic.
    ranked = sorted(evidence.items(), key=lambda kv: (-kv[1], kv[0]))
    capped = ranked[:MAX_AUTO_TAGS_PER_ASSET]

    session.exec(
        delete(AssetTag).where(
            AssetTag.asset_id == asset.id,
            AssetTag.source == ASSET_TAG_SOURCE_AUTO,
        )
    )

    # Re-read rather than trusting the delete: a surviving `user` row with the
    # same text would violate uq_asset_tag on insert, and is deliberately
    # skipped — one row per (asset_id, tag), owned by whoever got there first.
    # Exactly the same trade `_apply_civitai_metadata` makes.
    user_tags = set(
        session.exec(
            select(AssetTag.tag).where(
                AssetTag.asset_id == asset.id,
                AssetTag.source == ASSET_TAG_SOURCE_USER,
            )
        ).all()
    )

    now = datetime.now(timezone.utc)
    written = 0
    skipped_user = 0
    for tag, confidence in capped:
        if tag in user_tags:
            skipped_user += 1
            continue
        session.add(
            AssetTag(
                asset_id=asset.id,
                tag=tag,
                source=ASSET_TAG_SOURCE_AUTO,
                confidence=confidence,
                created_at=now,
            )
        )
        written += 1

    return (len(evidence), written, skipped_user)


def reindex_asset_tags(
    session: Session,
    *,
    batch_size: int = DEFAULT_AUTO_TAG_BATCH_SIZE,
    limit: int | None = None,
    after_id: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Re-derive `asset_tags` for every live asset. Batched, bounded, resumable.

    Same contract as `reindex_asset_loras` in `services.asset_metadata_index.py`
    — keyset by id so a resume never re-reads the batch just committed, commit
    per batch so an interrupted run loses at most one batch.

    Args:
        batch_size: rows per transaction. Also the commit cadence.
        limit: stop after this many assets; None means "until done". This is the
            bound that makes a single call safe to issue from anywhere.
        after_id: resume keyset — only assets with a greater id. Pass the
            `last_asset_id` from a previous call to continue where it stopped.
        dry_run: report what would be derived and write nothing. Not a
            simulation bolted on afterwards — the writes are simply not issued,
            so a dry run cannot half-apply.

    Returns a summary dict, including `last_asset_id` for resuming.
    """
    statement = select(Asset).where(Asset.deleted_at.is_(None))
    if after_id:
        statement = statement.where(Asset.id > after_id)
    statement = statement.order_by(Asset.id).limit(batch_size)

    processed = 0
    assets_tagged = 0
    tags_seen = 0
    tags_written = 0
    skipped_user = 0
    skipped_no_metadata = 0
    last_id = after_id
    truncated = False

    while True:
        # The fetch size is what enforces `limit`. Checking `processed >= limit`
        # after the batch has already been processed — which is what this used
        # to do — bounds the number of batches *inspected*, not the number of
        # assets processed, so `reindex_asset_tags(limit=2, batch_size=10)` over
        # five assets tagged all five and reported `processed=5`.
        fetch = batch_size
        if limit is not None:
            remaining = limit - processed
            if remaining <= 0:
                break
            fetch = min(fetch, remaining)

        statement = (
            select(Asset)
            .where(Asset.deleted_at.is_(None))
            .where(Asset.id > last_id if last_id else true())
            .order_by(Asset.id)
            .limit(fetch)
        )
        assets = session.exec(statement).all()
        if not assets:
            break

        for asset in assets:
            last_id = asset.id
            processed += 1
            if not asset.metadata_:
                # Counted, but NOT skipped: `auto_tag_asset` deletes the auto
                # rows when it finds no evidence, and that delete is how a
                # re-tag converges. Skipping here left an image whose LoRA
                # metadata was cleared upstream holding its stale tags forever,
                # which is the one outcome the auto-tagger's own docstring says
                # it must not produce.
                skipped_no_metadata += 1
            seen, written, skipped = auto_tag_asset(session, asset)
            tags_seen += seen
            tags_written += written
            skipped_user += skipped
            if written:
                assets_tagged += 1

        if not dry_run:
            session.commit()
        else:
            # Roll the batch back rather than trusting that nothing was written:
            # the whole point of a dry run is that a bug in here cannot reach
            # the database, and a rollback is the only statement of that which
            # does not depend on the code being correct.
            session.rollback()

        if limit is not None and processed >= limit:
            # `truncated` means "there is more to do", so it must not be set
            # when the last batch happened to end exactly on the limit.
            truncated = len(assets) == fetch and (
                session.exec(
                    select(Asset.id)
                    .where(Asset.deleted_at.is_(None))
                    .where(Asset.id > last_id)
                    .limit(1)
                ).first()
                is not None
            )
            break
        if len(assets) < fetch:
            break

    return {
        "dry_run": dry_run,
        "processed": processed,
        "assets_tagged": assets_tagged,
        "tags_seen": tags_seen,
        "tags_written": tags_written,
        "skipped_user": skipped_user,
        "skipped_no_metadata": skipped_no_metadata,
        "last_asset_id": last_id,
        "truncated": truncated,
    }
