"""
Detect generation sessions: groups of images that were, almost certainly, made
together.

## Why this exists

A session is a curatable group of related images. The *cheap* signals for
"these were made together" are already promoted to real columns on `assets` by
`services/asset_reconciler` (seed, checkpoint_name, and the resolved timestamp),
so detection needs no image reads, no prompt hashing and no jsonb walking — a
single columnar pass.

## The half-computed, half-curated contract

This is the part that matters, and it is easy to get wrong:

* the detector writes rows with `auto_detected=True`, `locked=False` and a
  `signature` derived from the cheap signal;
* **any** human edit — rename, split, merge, manual add/remove, accept — sets
  `locked=True`, and a locked session is never touched again by the detector.

Without that second rule, every recompute silently undoes curation, and people
rightly come to distrust auto-tagging. So a detect run over a library the user
has organised does nothing to the parts they organised and only fills in the
gaps. `tests/test_sessions.py::TestLocking` pins this.

## Signals, in priority order

A group is formed by the *first* signal that yields a group of at least
`min_size`. A group already claimed by a stronger signal is not re-formed by a
weaker one — otherwise every seed-matched image would also appear in a
time-proximity session and one picture would live in two sessions.

1. **Identical seed** — `seed IS NOT NULL AND seed != 0`, same `user_id` and
   same `seed`. `seed = 0` is excluded because it is simultaneously a legal seed
   and the "unset" default that `build_image_job_workflow` writes; including it
   would collapse unrelated images into one enormous group. The exclusion
   mirrors the partial index `ix_assets_seed_lookup` from migration 070, so the
   query plan and the semantics cannot disagree.
2. **Identical checkpoint within a time window** — same non-null
   `checkpoint_name`, assets within `time_gap_minutes` of each other.
3. **Time proximity alone** — consecutive assets within `time_gap_minutes`, same
   workspace. The fallback that catches batch work with random seeds.

`min_size` defaults to 2: a group of one is not a session.

"Resolved timestamp" is `coalesce(job_completed_at, generated_at, created_at)` —
the identical expression `_RESOLVED_TS` uses in `services/statistics_service`, so
a session's day bounds agree with every other time bucket in the app.

## Never across workspace

`assets.workspace` partitions the corpus (main / chat / story) and every
grouping key here includes it. A chat image and a story image that share a seed
are two unrelated facts, not a session.

## `signature`

A stable string encoding *the signal and the bucket*, where the bucket is the
group's `start_at` truncated to the minute, for every signal:

    seed:12345@2026-09-27T14:32
    ckpt:sd_xl_base_1.0@2026-09-27T14:32
    time:main@2026-09-27T14:32

It is load-bearing, not decoration. `signature` is deliberately NOT
unique-constrained (a split legitimately leaves two sessions sharing one), so
the detector's own lookup is the only thing keeping runs apart — and it needs a
bucket that is *provably* distinct per run.

Minute resolution is provably distinct. The gap walk starts a new run for a key
only when `ts - last_ts > gap`, and `last_ts >= start` of the previous run, so
consecutive runs of the same key start more than `gap` apart. With
`gap >= 1 minute` — enforced — two runs can never share a minute. An hour bucket
is *not* distinct: on a synthetic 4k-asset corpus with four checkpoints and a
20-minute window, 89 of 576 groups collided, and each collision silently fused
two separate working stretches into one session with a start that belonged to
neither. That was measured, not hypothesised.

Idempotency is then: load the live auto-detected sessions once, index them by
`(user_id, signature)`, and extend the match instead of inserting. An asset set
that has not changed produces zero writes.

One consequence worth stating: the bucket is derived from `time_gap_minutes`, so
re-running with a *different* window produces different signatures and the
previous run's sessions are left in place rather than reconciled. They remain
visible and editable; the detector deliberately does not delete them, because
silently removing sessions is not something a recompute should be able to do.

## Cost

One columnar pass for the assets, one for the existing sessions, one for the
existing memberships. Then set-based: a single executemany insert of the
missing `session_assets` rows and a single row-value `DELETE` for the rows a
shrunken group no longer owns. No query is issued per asset, and nothing but the
seven grouping columns is ever materialised — `assets.metadata_` (~70 MB on this
deployment) is never read into Python.

At the ~16.4k assets this library actually holds that is a scan plus an
in-Python sort of 16k narrow tuples and 4-6 SQL statements, independent of
library size. `MAX_DETECT_ASSETS` refuses anything past it rather than risking a
multi-second synchronous request; see the `POST /detect` route.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, insert, tuple_
from sqlmodel import Session, func, select

from core.entities import Asset
from core.entities import Session as GenerationSession
from core.entities import SessionAsset
from core.exceptions import ValidationError
from infrastructure.logging import get_logger

logger = get_logger("session_detector")

__all__ = ["MAX_DETECT_ASSETS", "RESOLVED_TS", "detect_sessions"]

# Refuse rather than risk. The pass is linear, but it is synchronous and holds a
# request open; 200k is an order of magnitude past this deployment's 16.4k, and a
# library that size wants the batch-job treatment `reindex_asset_loras` uses
# rather than an HTTP request.
MAX_DETECT_ASSETS = 200_000

# The instant an asset counts towards, preferring the job's own completion time.
# Must stay identical to `_RESOLVED_TS` in `services/statistics_service`; that one
# is private, so the expression is mirrored here and the coupling is documented on
# both sides rather than left to drift silently.
RESOLVED_TS = func.coalesce(Asset.job_completed_at, Asset.generated_at, Asset.created_at)

# The checkpoint grouping key. The rollup column is preferred, with the jsonb
# forms behind it so a row written before migration 067 (no `checkpoint_name`)
# still groups under the same name the statistics facet groups it under. Mirrors
# `_CHECKPOINT` in `services/statistics_service`.
_META = Asset.metadata_
CHECKPOINT_KEY = func.coalesce(
    Asset.checkpoint_name,
    _META["checkpoint"]["name"].as_string(),
    _META["checkpoint"].as_string(),
)

_BUCKET = "%Y-%m-%dT%H:%M"

# Checkpoint names reach ~100 characters, sometimes with spaces and colons. A
# signature is a key, not a label, so it gets slugified and bounded; the
# human-facing label goes in `name`.
_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")

MAX_NAME_LENGTH = 120
MAX_SLUG_LENGTH = 48


def _slug(value: str) -> str:
    cleaned = _SLUG_RE.sub("_", value.strip()).strip("_")
    return (cleaned or "unknown")[:MAX_SLUG_LENGTH]


@dataclass
class _Run:
    """One maximal run of assets under a single signal, in time order.

    `members` is (asset_id, resolved_ts, relative_path) in ascending time, so
    that bounds and cover can be recomputed from any *subset* of the run after a
    stronger signal has claimed part of it. `last_ts` deliberately tracks the
    unfiltered tail: the gap walk is over the whole corpus and must not be
    perturbed by which assets happened to be claimed.
    """

    user_id: str
    workspace: str
    value: object
    members: list[tuple[str, datetime, str]] = field(default_factory=list)
    last_ts: datetime | None = None

    def add(self, asset_id: str, ts: datetime, relative_path: str) -> None:
        self.members.append((asset_id, ts, relative_path))
        self.last_ts = ts

    def remaining(self, claimed: set[str]) -> list[tuple[str, datetime, str]]:
        """The run's members no stronger signal has already claimed."""
        return [member for member in self.members if member[0] not in claimed]


@dataclass
class _Group:
    """A run that cleared `min_size`, with its persisted identity resolved."""

    signal: str
    user_id: str
    workspace: str
    signature: str
    name: str
    asset_ids: list[str]
    start: datetime
    end: datetime
    thumbnail: str | None


def _collect_runs(rows: list, key_of, gap: timedelta) -> list[_Run]:
    """Walk the pre-sorted rows once, opening a new run whenever the gap breaks.

    `rows` must be ordered by (user_id, workspace, timestamp, id) and every
    `key_of` result must include the user/workspace pair, so the timestamps seen
    for any one key are non-decreasing and a single "how stale is the current
    run" comparison is enough. That is what keeps this O(n) rather than the
    O(n·k) of sorting per group.
    """
    open_runs: dict[object, _Run] = {}
    finished: list[_Run] = []

    for row in rows:
        key = key_of(row)
        if key is None:
            continue
        run = open_runs.get(key)
        if run is None or row.ts - run.last_ts > gap:
            if run is not None:
                finished.append(run)
            run = _Run(user_id=row.user_id, workspace=row.workspace, value=key[2])
            open_runs[key] = run
        run.add(row.id, row.ts, row.relative_path)

    finished.extend(open_runs.values())
    return finished


def _seed_key(row) -> tuple | None:
    if row.seed is None or row.seed == 0:
        return None
    return (row.user_id, row.workspace, row.seed)


def _checkpoint_key(row) -> tuple | None:
    if not row.checkpoint:
        return None
    return (row.user_id, row.workspace, row.checkpoint)


def _time_key(row) -> tuple:
    # `workspace` is NOT NULL, but normalise '' so it partitions identically.
    return (row.user_id, row.workspace or "main", "")


def _finalise(signal: str, run: _Run, members: list[tuple[str, datetime, str]]) -> _Group:
    """Resolve the run's persisted identity from the members it actually keeps.

    `members` is already filtered to the unclaimed, in-time-order remainder, so
    the bucket below is derived from the *real* first member of the session and
    cannot be shifted by assets a stronger signal already owns.
    """
    if not members:
        raise ValueError("cannot finalise an empty run")
    start = members[0][1]
    bucket = start.strftime(_BUCKET)
    if signal == "seed":
        signature = f"seed:{run.value}@{bucket}"
        name = f"Seed {run.value}"
    elif signal == "ckpt":
        signature = f"ckpt:{_slug(str(run.value))}@{bucket}"
        name = str(run.value)[:MAX_NAME_LENGTH]
    else:
        signature = f"time:{_slug(run.workspace or 'main')}@{bucket}"
        name = f"Session {run.workspace} {start.strftime(_BUCKET)}"[:MAX_NAME_LENGTH]
    return _Group(
        signal=signal,
        user_id=run.user_id,
        workspace=run.workspace,
        signature=signature,
        name=name,
        asset_ids=[member[0] for member in members],
        start=start,
        end=members[-1][1],
        thumbnail=members[0][2],
    )


def _load_rows(session: Session, max_assets: int) -> list:
    """The single columnar pass: grouping columns only, never `metadata_`."""
    considered = session.execute(
        select(func.count(Asset.id)).where(Asset.deleted_at.is_(None))
    ).scalar_one()
    if considered > max_assets:
        raise ValidationError(
            f"Session detection is limited to {max_assets} assets and this library "
            f"holds {considered}. Run it as a batch job instead.",
            field="assets",
        )

    rows = session.exec(
        select(
            Asset.id,
            Asset.user_id,
            Asset.workspace,
            Asset.seed,
            CHECKPOINT_KEY.label("checkpoint"),
            RESOLVED_TS.label("ts"),
            Asset.relative_path,
        ).where(Asset.deleted_at.is_(None))
    ).all()

    # The resolved timestamp is an expression, so no index orders it; sorting
    # 16k narrow tuples in Python beats a database sort here and gives a
    # deterministic order, which the gap walk depends on.
    ordered = sorted(
        rows, key=lambda r: (r.user_id, r.workspace or "", r.ts, r.id)
    )
    return [r for r in ordered if r.ts is not None]


def _build_groups(rows: list, min_size: int, gap: timedelta) -> tuple[list[_Group], int]:
    """Apply the three signals in priority order, claiming assets as we go.

    A weaker signal only forms a group out of the assets a stronger one left
    behind. Restricting the remainder rather than discarding the whole run
    matters: with five images sharing a seed interleaved with five unrelated
    images in the same working stretch, the time signal's single run spans all
    ten, and dropping it outright would leave those five permanently
    unsessioned while their seed-matched neighbours got one.
    """
    signals: list[tuple[str, list[_Run]]] = [
        ("seed", _collect_runs(rows, _seed_key, gap)),
        ("ckpt", _collect_runs(rows, _checkpoint_key, gap)),
        ("time", _collect_runs(rows, _time_key, gap)),
    ]

    claimed: set[str] = set()
    groups: list[_Group] = []
    below_min = 0
    for signal, candidates in signals:
        for run in candidates:
            members = run.remaining(claimed)
            if len(members) < min_size:
                below_min += 1
                continue
            groups.append(_finalise(signal, run, members))
            claimed.update(member[0] for member in members)
    return groups, below_min


def _load_index(session: Session) -> dict[tuple[str, str], list[GenerationSession]]:
    """Live auto-detected sessions, indexed by `(user_id, signature)`.

    One query for the whole corpus rather than an `IN` per group: the set of
    auto-detected sessions is bounded by the number of sessions, not the number
    of assets, and an `IN` list that size would exceed SQLite's bound-parameter
    limit anyway.
    """
    index: dict[tuple[str, str], list[GenerationSession]] = {}
    rows = session.exec(
        select(GenerationSession).where(
            GenerationSession.auto_detected.is_(True),
            GenerationSession.deleted_at.is_(None),
            GenerationSession.signature.isnot(None),
        )
    ).all()
    for row in rows:
        index.setdefault((row.user_id, row.signature), []).append(row)
    return index


def _load_memberships(session: Session) -> dict[str, set[str]]:
    """Member sets for every live auto-detected session, in one joined query."""
    memberships: dict[str, set[str]] = {}
    rows = session.exec(
        select(SessionAsset.session_id, SessionAsset.asset_id).join(
            GenerationSession, GenerationSession.id == SessionAsset.session_id
        ).where(
            GenerationSession.auto_detected.is_(True),
            GenerationSession.deleted_at.is_(None),
        )
    ).all()
    for session_id, asset_id in rows:
        memberships.setdefault(session_id, set()).add(asset_id)
    return memberships


def _apply(target: GenerationSession, values: dict) -> bool:
    """Assign only what actually differs.

    A detect run over an unchanged library must be a true no-op, and a blind
    assignment marks every row dirty so SQLAlchemy emits an UPDATE for each one.
    """
    changed = False
    for key, value in values.items():
        if getattr(target, key) != value:
            setattr(target, key, value)
            changed = True
    return changed


def detect_sessions(
    session: Session,
    *,
    min_size: int = 2,
    time_gap_minutes: int = 20,
    dry_run: bool = False,
    max_assets: int = MAX_DETECT_ASSETS,
) -> dict:
    """Recompute auto-detected sessions from the cheap signals.

    Args:
        session: request-scoped DB session.
        min_size: smallest group worth calling a session. A group of one is not
            a session, which is why the default is 2.
        time_gap_minutes: the window within which "consecutive" counts as
            "together". It also splits an otherwise-identical seed or checkpoint
            group, which is why the bucket is part of the signature.
        dry_run: compute and report, write nothing. `sessions_created`,
        `sessions_extended` and `sessions_modified` all stay 0 — nothing
        happened — and the projections appear as `pending_create` /
        `pending_extend`, so a caller cannot mistake a dry run for work that
        landed.
        max_assets: refuse rather than run unbounded.

    Returns:
        A summary dict. Keys:

        * `groups_detected` — groups that cleared `min_size` after the priority
          order was applied.
        * `sessions_created` / `sessions_extended` / `sessions_modified` — what
          actually happened. `extended` counts pre-existing sessions whose
          membership changed; `modified` counts every session whose stored
          fields (bounds, count, cover, name) changed, new ones included. A
          re-run over unchanged data reports 0 for all three.
        * `sessions_skipped_locked` — groups whose signature matched a session a
          human has curated. Nothing about those sessions was touched.
        * `assets_considered` / `assets_grouped`.
        * `signals` — group count per signal.
        * `dry_run`, plus `pending_create` / `pending_extend` as the projection.
    """
    started = time.perf_counter()

    if min_size < 1:
        raise ValidationError("min_size must be at least 1", field="min_size")
    if time_gap_minutes <= 0:
        raise ValidationError(
            "time_gap_minutes must be positive", field="time_gap_minutes"
        )

    gap = timedelta(minutes=time_gap_minutes)
    rows = _load_rows(session, max_assets)
    groups, below_min = _build_groups(rows, min_size, gap)

    summary: dict = {
        "groups_detected": len(groups),
        "sessions_created": 0,
        "sessions_extended": 0,
        "sessions_skipped_locked": 0,
        "assets_considered": len(rows),
        "assets_grouped": 0,
        "sessions_modified": 0,
        "sessions_superseded": 0,
        "groups_below_min_size": below_min,
        "signals": {"seed": 0, "ckpt": 0, "time": 0},
        "dry_run": dry_run,
        "pending_create": 0,
        "pending_extend": 0,
    }

    if not groups:
        summary["elapsed_seconds"] = round(time.perf_counter() - started, 4)
        return summary

    index = _load_index(session)
    memberships = _load_memberships(session)
    now = datetime.now(timezone.utc)

    # Phase 1: resolve each group onto a session row and record the membership it
    # should end up with. Deliberately separate from phase 2 so that the
    # insert/delete diff is computed once per session against a FINAL member
    # set, not incrementally. Deriving it inside the loop looks equivalent and is
    # not: two groups resolving onto one row would emit a pair in both the
    # insert list and the delete list, and the write that follows is a duplicate
    # key on `uq_session_asset`.
    desired: dict[str, set[str]] = {}
    touched: set[str] = set()

    for group in groups:
        summary["signals"][group.signal] += 1
        summary["assets_grouped"] += len(group.asset_ids)

        candidates = index.get((group.user_id, group.signature)) or []
        unlocked = [c for c in candidates if not c.locked]

        if candidates and not unlocked:
            # The user has curated this exact group: leave membership, bounds,
            # name and the lock itself completely alone. The assets stay claimed
            # so a weaker signal cannot rebuild them into a second session, which
            # is the whole point of claiming at formation time.
            summary["sessions_skipped_locked"] += 1
            continue

        target = unlocked[0] if unlocked else None
        if target is None:
            summary["pending_create"] += 1
        else:
            summary["pending_extend"] += 1
        if dry_run:
            # Nothing below this line may touch the database, including the
            # denormalised bounds on an existing row.
            continue
        changed = False

        if target is None:
            target = GenerationSession(
                user_id=group.user_id,
                name=group.name,
                description=None,
                signature=group.signature,
                auto_detected=True,
                locked=False,
                workspace=group.workspace,
                start_at=group.start,
                end_at=group.end,
                image_count=len(group.asset_ids),
                thumbnail=group.thumbnail,
                created_at=now,
                updated_at=now,
            )
            session.add(target)
            index[(group.user_id, group.signature)] = [target]
            summary["sessions_created"] += 1
            changed = True
            # The extras can only exist from a concurrent detect. The invariant
            # is one unlocked session per (user, signature); soft-deleting them
            # restores it instead of leaving orphans that shadow every future
            # lookup of this key.
            for extra in unlocked[1:]:
                _apply(
                    extra,
                    {
                        "deleted_at": now,
                        "updated_at": now,
                        "image_count": 0,
                        "thumbnail": None,
                    },
                )
                summary["sessions_superseded"] += 1

        desired.setdefault(target.id, set()).update(group.asset_ids)

        # Denormalised bounds, count and cover. Maintained on every write
        # because the scrubber orders and seeks by them and must never see a
        # stale value. Recomputed from `desired`, not from this group alone, so
        # two groups landing on one row still get coherent numbers.
        members = desired[target.id]
        if _apply(
            target,
            {
                "name": group.name,
                "workspace": group.workspace,
                "start_at": min(group.start, target.start_at or group.start),
                "end_at": max(group.end, target.end_at or group.end),
                "image_count": len(members),
                "thumbnail": target.thumbnail or group.thumbnail,
            },
        ):
            changed = True
        if changed:
            _apply(target, {"updated_at": now})
            summary["sessions_modified"] += 1
        touched.add(target.id)

    if not dry_run:
        # Phase 2: the insert/delete diff, once per touched session.
        pending: list[SessionAsset] = []
        to_remove: list[tuple[str, str]] = []
        for target_id, wanted in desired.items():
            existing_members = memberships.get(target_id, set())
            if existing_members == wanted:
                continue
            summary["sessions_extended"] += 1
            to_remove.extend(
                (target_id, asset_id) for asset_id in existing_members - wanted
            )
            for asset_id in sorted(wanted - existing_members):
                pending.append(
                    SessionAsset(session_id=target_id, asset_id=asset_id, added_at=now)
                )
            memberships[target_id] = wanted

        if pending:
            session.execute(
                insert(SessionAsset),
                [
                    {
                        "id": row.id,
                        "session_id": row.session_id,
                        "asset_id": row.asset_id,
                        "added_at": row.added_at,
                    }
                    for row in pending
                ],
            )
        if to_remove:
            # One row-value predicate rather than a DELETE per session. Verified
            # to compile for both dialects: SQLite 3.15+ and Postgres both
            # support `(a, b) IN ((...), (...))`.
            session.execute(
                delete(SessionAsset).where(
                    tuple_(SessionAsset.session_id, SessionAsset.asset_id).in_(to_remove)
                )
            )
        session.commit()

    summary["sessions_touched"] = len(touched)
    summary["elapsed_seconds"] = round(time.perf_counter() - started, 4)
    logger.info(
        "session_detect",
        groups=summary["groups_detected"],
        created=summary["sessions_created"],
        extended=summary["sessions_extended"],
        skipped_locked=summary["sessions_skipped_locked"],
        considered=summary["assets_considered"],
        elapsed_ms=round(summary["elapsed_seconds"] * 1000, 2),
        dry_run=dry_run,
    )
    return summary
