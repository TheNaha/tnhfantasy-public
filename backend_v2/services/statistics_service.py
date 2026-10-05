"""SQL-aggregated gallery statistics for `/api/statistics/*`.

Why this module exists
----------------------
The statistics endpoints used to load every non-deleted `assets` row into
Python and aggregate there. On this deployment that is 16k rows carrying
~70 MB of jsonb, and the load dominated everything else: profiling the old
`_calculate_detailed_statistics` attributed ~2.5 s to json decode plus ORM
instantiation against ~0.2 s of actual aggregation, for a 6.5 s cold request
behind a 5-minute cache.

Every distribution here is a `GROUP BY` that returns a handful of rows. Only
the three things SQL cannot group are fetched per row — the LoRA array, prompt
text, and the resolved timestamp — in a single narrow pass.

Portability
-----------
All SQL is built from SQLAlchemy Core constructs that compile to `->>` on
Postgres and `JSON_EXTRACT` on SQLite, so the test suite exercises the same
code path as production. There is no dialect branching and no Postgres-only
operator in a query the tests reach.

Two consequences of aggregating text rather than the decoded document are worth
knowing:

* `metadata_->>'key'` cannot distinguish an absent key from a JSON `null`, so a
  row counts toward a distribution when the value is present and non-null. The
  old loop counted on key presence. These differ only for explicitly-null
  values, which carry no setting.
* Timestamps are bucketed in UTC, matching the backend container and database
  clocks. Host local time is deliberately not involved.
* `metadata_->>'seed'` cannot tell an absent key from a JSON `null`, so a row
  with no recorded seed counts as a random seed. The old loop skipped those rows
  from both counters. Nothing renders `settings.seeds_*`, and "no seed recorded"
  reads as random, so the simpler rule is kept rather than adding a
  dialect-specific key-presence test.
"""

from __future__ import annotations

import re
import threading
from collections import Counter, OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import String, and_, case, func, literal, or_, select
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import Session

from core.entities import (
    Asset,
    Chat,
    Character,
    Job,
    JobStatus,
    Lorebook,
    Message,
    Story,
    StoryChapter,
)
from core.sql_search import LIKE_ESCAPE_CHAR, like_contains
from infrastructure.logging import get_logger
from services.asset_reconciler import METADATA_VERSION

logger = get_logger("statistics_service")

__all__ = [
    "ASSET_GALLERY_TIMESTAMP",
    "get_asset_date_histogram",
    "get_base_statistics",
    "get_detailed_statistics",
    "get_stats_summary",
    "resolve_time_range",
]

# Text fragments counted by the prompt-keyword pass. Three letters minimum, so
# the shorter ComfyUI quality tags ("1g", "ug") are deliberately excluded.
_WORD_RE = re.compile(r"\b[a-zA-Z]{3,}\b")

_STOP_WORDS = frozenset(
    {
        "the", "and", "for", "are", "but", "not", "you", "all", "can", "her",
        "was", "one", "our", "out", "day", "get", "has", "him", "his", "how",
        "man", "new", "now", "old", "see", "two", "way", "who", "boy", "did",
        "its", "let", "put", "say", "she", "too", "use", "with", "from", "that",
        "this", "will", "have", "been", "more", "when", "into", "some", "than",
    }
)

_TIME_RANGES: dict[str, int | None] = {"24h": 24 * 3600, "7d": 7 * 86400, "30d": 30 * 86400}

_META = Asset.metadata_


def _meta(key: str) -> ColumnElement[Any]:
    """A field of `assets.metadata_` as text.

    Compiles to `(metadata_ ->> 'key')::varchar` on Postgres and
    `JSON_EXTRACT(metadata_, '$."key"')` on SQLite.
    """
    return _META[key].as_string()


# A checkpoint is an object with a `name`; legacy rows stored a bare string.
# The rollup column is preferred, with the jsonb forms as a fallback so a row
# written before migration 067 still groups under the right name.
_CHECKPOINT = func.coalesce(
    Asset.checkpoint_name,
    _META["checkpoint"]["name"].as_string(),
    _META["checkpoint"].as_string(),
)

# Resolution is built from the real `width`/`height` columns, not from
# `metadata_`. `reconcile_asset` populates them from the image itself and they
# are filled for every non-deleted row on this deployment, so reading them costs
# no jsonb decompression and cannot drift from the stored dimensions.
_RESOLUTION = func.cast(Asset.width, String) + "x" + func.cast(Asset.height, String)

# `job.completed_at` is an ISO string on enriched rows and an epoch float on
# legacy ones. Only the ISO form truncates to a fixed-width, lexicographically
# comparable prefix; anything else falls through to the row timestamp columns.
# The resolved completion time: the job's own, else the row's own timestamps.
# Mirrors `_resolved_timestamp`, which is the Python version used for the
# timeline buckets.
_RESOLVED_TS = func.coalesce(Asset.job_completed_at, Asset.generated_at, Asset.created_at)

# The gallery's timeline, and therefore the ONE day-bucketing rule.
#
# `_RESOLVED_TS` above is the *analytics* timestamp: it prefers the job's own
# completion time, which is a different instant from the image's own timestamp on
# every enriched row. `get_base_statistics()["images_by_date"]` reports days by
# that instant, so it cannot drive a scrubber attached to the gallery: the two
# disagree about which day an image is on, and the statistics histogram is
# additionally unfiltered (no workspace/character/story scope) and only counts
# rows that carry metadata at all. A scoped gallery would therefore show a rail
# whose ticks point at the wrong days.
#
# So the gallery's rule is `coalesce(generated_at, created_at)` — the moment the
# image was made (PNG tEXt metadata, else file mtime), falling back to the row's
# own creation time for a migrated legacy row that has nothing better. It lives
# here, next to `_RESOLVED_TS`, so that the listing, its date seek and the
# histogram all bind the *same expression object* rather than three copies of a
# rule that can drift. `api/routes/files.py` imports it.
ASSET_GALLERY_TIMESTAMP = func.coalesce(Asset.generated_at, Asset.created_at)

_DIMENSIONS: dict[str, ColumnElement[Any]] = {
    "checkpoint": func.coalesce(Asset.checkpoint_name, _META["checkpoint"]["name"].as_string(), _META["checkpoint"].as_string()),
    "sampler": Asset.sampler,
    "scheduler": Asset.scheduler,
    "steps": func.cast(Asset.steps, String),
    "cfg": func.cast(Asset.cfg, String),
    "resolution": _RESOLUTION,
    "vae": Asset.vae,
}

_PRESENT: dict[str, ColumnElement[bool]] = {
    "checkpoint": _DIMENSIONS["checkpoint"].isnot(None),
    "sampler": Asset.sampler.isnot(None),
    "scheduler": Asset.scheduler.isnot(None),
    "steps": Asset.steps.isnot(None),
    "cfg": Asset.cfg.isnot(None),
    "resolution": and_(Asset.width.isnot(None), Asset.height.isnot(None)),
    "vae": Asset.vae.isnot(None),
}

# A row is "in play" when it carries metadata at all. The old loop skipped
# falsy metadata, which is the same set for every row this index produces.
_IN_PLAY = and_(Asset.metadata_.isnot(None), Asset.deleted_at.is_(None))
_POSITIVE_DURATION = Asset.duration_seconds > 0


# ── SQL helpers ─────────────────────────────────────────────────────────────


def _time_range_filter(cutoff: datetime) -> ColumnElement[bool]:
    """Keep rows whose resolved completion time is at or after `cutoff`.

    The resolved time prefers the job's own completion time and falls back to the
    row's generated_at/created_at, and that is exactly the `job_completed_at`
    column the write path derives. So this is a plain indexed timestamp
    comparison.

    It used to be a jsonb expression, and because it is applied to *every* query
    in a detailed request — ten grouped aggregations plus the totals — each one
    re-parsed the whole document just to test the filter. That is the entire
    reason `?timeRange=30d` cost 3.4s while `?timeRange=all` cost 1.2s on the
    same data: `all` passes no filter at all.
    """
    return _RESOLVED_TS >= cutoff


def _grouped(
    session: Session,
    dims: Sequence[str],
    *,
    where: ColumnElement[bool] | None = None,
    with_duration: bool = False,
) -> list[tuple[Any, ...]]:
    """`GROUP BY` the named dimensions, returning one row per distinct tuple.

    The trailing columns are the group count and, when `with_duration`, the
    summed and counted positive durations for that group — which is how the
    `performance.by_*` breakdowns are produced without a second pass.
    """
    exprs = [_DIMENSIONS[dim] for dim in dims]
    columns: list[ColumnElement[Any]] = [*exprs, func.count()]
    if with_duration:
        columns.append(
            func.coalesce(
                func.sum(case((_POSITIVE_DURATION, Asset.duration_seconds), else_=0.0)), 0.0
            )
        )
        columns.append(func.coalesce(func.sum(case((_POSITIVE_DURATION, 1), else_=0)), 0))

    stmt = select(*columns).where(_IN_PLAY)
    for dim in dims:
        stmt = stmt.where(_PRESENT[dim])
    if where is not None:
        stmt = stmt.where(where)
    return list(session.execute(stmt.group_by(*exprs)).all())


def _clean(value: Any, default: str = "Unknown") -> str | None:
    """Normalise a grouping key to a display string.

    `->>` on a JSON object yields the object's text, so a checkpoint stored as an
    object with no `name` arrives as `{...}` rather than as a name. Those fold
    into `default` so they cannot each become their own chart series.
    """
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    if not text or text.startswith("{"):
        return default
    return text


def _sorted_counts(counts: dict[str, int]) -> dict[str, int]:
    return dict(sorted(counts.items(), key=lambda item: item[1], reverse=True))


def _count_map(rows: Sequence[Sequence[Any]], transform=None) -> dict[str, int]:
    """`{cleaned_dimension: count}` from a single-dimension `_grouped` result.

    `_grouped` omits absent values, so the count is always a real row count —
    there is no zero-filled placeholder to confuse the sum with.
    """
    clean = transform or _clean
    return {clean(row[0]): int(row[1]) for row in rows}


def _performance_map(rows: Sequence[Sequence[Any]]) -> dict[str, dict[str, Any]]:
    """`performance.by_*` entries from a single-dimension `_grouped` result.

    The trailing columns of a `with_duration` grouping are the summed and
    counted positive durations for that group.
    """
    out: dict[str, dict[str, Any]] = {}
    for key, _count, dur_sum, dur_count in rows:
        out[_clean(key)] = {"total_time": float(dur_sum or 0), "count": int(dur_count or 0), "avg": 0}
    return out


# ── per-row pass ────────────────────────────────────────────────────────────


def _resolved_timestamp(job_ts: Any, generated_at: Any, created_at: Any) -> datetime | None:
    """The instant an asset counts towards, mirroring the old resolution order.

    `job.completed_at` wins when it holds a parseable ISO timestamp; legacy rows
    store an epoch float there, which is also accepted. Otherwise the row's own
    `generated_at`/`created_at` is used.
    """
    if job_ts is not None:
        if isinstance(job_ts, (int, float)) and not isinstance(job_ts, bool):
            try:
                return datetime.fromtimestamp(float(job_ts), tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                pass
        else:
            text = str(job_ts).strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                pass
            else:
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    for candidate in (generated_at, created_at):
        if isinstance(candidate, datetime):
            return candidate if candidate.tzinfo else candidate.replace(tzinfo=timezone.utc)
    return None


def _row_pass(
    session: Session,
    where: ColumnElement[bool] | None,
    *,
    with_prompts: bool,
) -> list[tuple]:
    """The one query that still touches `metadata_`.

    LoRA weights, prompt keywords, and timeline buckets cannot be expressed as a
    `GROUP BY`, so they need per-row data. Everything else is read from the
    rollup columns, which keeps this the single jsonb pass in the request.

    `with_prompts` is off on a prompt-cache hit. The prompt text is by far the
    largest thing here — 9.1 MB across 16k rows on this deployment, and fetching
    it costs more than every other column combined — so it is only transferred
    when the histogram actually has to be rebuilt.
    """
    columns: list[ColumnElement[Any]] = [
        _META["loras"],
        _META["job"]["completed_at"].as_string(),
        Asset.generated_at,
        Asset.created_at,
    ]
    if with_prompts:
        columns.append(_meta("prompt"))
        columns.append(_meta("negativePrompt"))

    stmt = select(*columns).where(_IN_PLAY)
    if where is not None:
        stmt = stmt.where(where)
    return list(session.execute(stmt).all())


def _prompt_signature(session: Session, where: ColumnElement[bool] | None) -> str:
    """An exact content hash of every prompt and negative prompt in scope.

    The prompt-derived part of the response — the keyword histogram, the length
    statistics, `negative_usage` — depends only on those strings, so the hash is
    a sound cache key: any edit to any prompt, including one that keeps the same
    length, changes it. That is what makes this exact rather than approximate.
    A cheaper signature (row count, total length, newest timestamp) was rejected
    because an in-place edit of identical length would not be noticed.

    Cost is one jsonb pass that never leaves Postgres: measured 0.37–0.58s
    against the 1.4s the row pass costs to transfer the same 9.1 MB and tokenise
    it in Python.
    """
    # ASCII unit separator, bound as a parameter rather than interpolated. It
    # keeps the concatenation injective — a separator that occurs inside prompts
    # could let two different prompt sets produce the same hash.
    separator = literal(chr(31), type_=String)
    pair = func.concat(
        func.coalesce(_meta("prompt"), ""),
        separator,
        func.coalesce(_meta("negativePrompt"), ""),
    )
    stmt = select(
        func.count(),
        func.coalesce(
            func.md5(func.coalesce(func.string_agg(pair, literal("")), literal(""))),
            literal(""),
        ),
    ).where(_IN_PLAY)
    if where is not None:
        stmt = stmt.where(where)
    row = session.execute(stmt).one()
    return f"{row[0]}:{row[1]}"


# One entry is enough: a request either hits the signature it left behind, or the
# cache is stale and gets replaced. Bounded so a series of distinct time ranges
# cannot grow it without limit.
_PROMPT_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_PROMPT_CACHE_MAX = 8
_prompt_cache_lock = threading.Lock()


def _cached_prompt_aggregates(
    session: Session, where: ColumnElement[bool] | None, signature: str
) -> dict[str, Any] | None:
    with _prompt_cache_lock:
        return _PROMPT_CACHE.get(signature)


def _store_prompt_aggregates(signature: str, aggregates: dict[str, Any]) -> None:
    with _prompt_cache_lock:
        _PROMPT_CACHE[signature] = aggregates
        while len(_PROMPT_CACHE) > _PROMPT_CACHE_MAX:
            _PROMPT_CACHE.popitem(last=False)


def _totals(session: Session, where: ColumnElement[bool] | None) -> dict[str, Any]:
    """Scalar aggregates over the rollup columns: counts, versions, seeds, durations.

    Reads no jsonb at all, so it is a plain columnar scan. Prompt presence is
    counted in `_row_pass` instead of being extracted a second time here.
    """
    version = Asset.metadata_version
    seed = Asset.seed
    seed_is_random = case((or_(seed.is_(None), seed == -1), 1), else_=0)
    columns: list[ColumnElement[Any]] = [
        func.count(),
        func.coalesce(func.sum(case((version == METADATA_VERSION, 1), else_=0)), 0),
        func.coalesce(func.sum(seed_is_random), 0),
        # `seed_fixed` is the complement of `seed_is_random` rather than a second
        # pair of comparisons over the same column.
        func.count() - func.coalesce(func.sum(seed_is_random), 0),
        func.coalesce(func.sum(case((_POSITIVE_DURATION, Asset.duration_seconds), else_=0.0)), 0.0),
        func.coalesce(func.sum(case((_POSITIVE_DURATION, 1), else_=0)), 0),
        func.min(case((_POSITIVE_DURATION, Asset.duration_seconds))),
        func.max(case((_POSITIVE_DURATION, Asset.duration_seconds))),
    ]

    stmt = select(*columns).where(_IN_PLAY)
    if where is not None:
        stmt = stmt.where(where)
    row = session.execute(stmt).one()
    return dict(
        zip(
            [
                "total",
                "enriched",
                "seeds_random",
                "seeds_fixed",
                "duration_sum",
                "duration_count",
                "duration_min",
                "duration_max",
            ],
            row,
        )
    )


def _image_job_success_rate(session: Session) -> float | None:
    """Fraction of image jobs that completed.

    Reported as `performance.success_rate`. The Statistics page has read this
    key since it was written, but nothing ever produced it, so the card silently
    rendered nothing.
    """
    completed = session.execute(
        select(func.count())
        .select_from(Job)
        .where(Job.task_type == "image", Job.status == JobStatus.COMPLETED)
    ).scalar()
    total = session.execute(
        select(func.count()).select_from(Job).where(Job.task_type == "image")
    ).scalar()
    if not total:
        return None
    return round(float(completed) / float(total), 4)


def _pillar_counts(session: Session) -> dict[str, int]:
    """Cross-pillar entity counts for the World Vault."""
    counts = {
        "images": 0,
        "characters": 0,
        "chats": 0,
        "messages": 0,
        "stories": 0,
        "story_chapters": 0,
        "lorebooks": 0,
        "image_jobs": 0,
        "llm_jobs": 0,
    }
    try:
        def _count(model, *filters):
            stmt = select(func.count()).select_from(model)
            if filters:
                stmt = stmt.where(*filters)
            return session.execute(stmt).scalar() or 0

        counts["characters"] = _count(Character)
        counts["chats"] = _count(Chat)
        counts["messages"] = _count(Message)
        counts["stories"] = _count(Story)
        counts["story_chapters"] = _count(StoryChapter)
        counts["lorebooks"] = _count(Lorebook)
        counts["image_jobs"] = _count(Job, Job.task_type == "image")
        counts["llm_jobs"] = _count(Job, Job.task_type == "llm")
    except Exception as exc:  # pragma: no cover - analytics must not 500
        logger.warning("pillar_counts_failed", error=str(exc))
    return counts


def resolve_time_range(time_range: str | None) -> datetime | None:
    """Cutoff instant for a `timeRange` query parameter, or None for "all"."""
    seconds = _TIME_RANGES.get((time_range or "all").strip().lower())
    if seconds is None:
        return None
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


def _session_scope() -> Any:
    """A short-lived session. The callers run in a worker thread, so the
    request-scoped session cannot be shared across the thread boundary."""
    from infrastructure.database import get_session_sync

    return get_session_sync()


# ── the gallery's day histogram ─────────────────────────────────────────────


def gallery_day_key(moment: Any) -> str | None:
    """`YYYY-MM-DD` in UTC for one gallery timestamp, or None if unusable.

    The bucketing is done in Python rather than as a SQL `GROUP BY date_trunc`
    for one reason: correctness across both dialects this module supports.
    Postgres has no `date_trunc` equivalent in SQLite, and SQLite's `date()` has
    no Postgres equivalent, so a SQL-side bucket either branches on dialect —
    which this module's portability rule exists to prevent — or picks
    `cast(ts AS varchar)` and silently depends on the session `TimeZone` being
    UTC, which is an environment fact rather than a guarantee. One narrow
    column scan of already-materialised datetimes is the honest cost: the
    expensive part of the old row pass was 70 MB of jsonb, not the timestamps.
    """
    if not isinstance(moment, datetime):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d")


def get_asset_date_histogram(
    *,
    workspace: str | None = None,
    character_id: str | None = None,
    story_id: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    """Per-day image counts for the gallery timeline scrubber.

    Scoped by exactly the filters `GET /api/v2/assets` accepts, so the rail
    always describes the list it is attached to. A full-library histogram next to
    a character-scoped gallery would put ticks on days the gallery cannot show.

    Days are UTC calendar days of `ASSET_GALLERY_TIMESTAMP` and are returned
    oldest-first, ascending. The caller projects them onto its own local day keys
    for display; it does not recompute them.
    """
    stmt = select(ASSET_GALLERY_TIMESTAMP).where(Asset.deleted_at.is_(None))
    if workspace:
        stmt = stmt.where(Asset.workspace == workspace)
    if character_id:
        stmt = stmt.where(Asset.character_id == character_id)
    if story_id:
        stmt = stmt.where(Asset.story_id == story_id)
    if search:
        like = like_contains(search)
        stmt = stmt.where(
            (Asset.filename.ilike(like, escape=LIKE_ESCAPE_CHAR))
            | (Asset.metadata_.cast(String).ilike(like, escape=LIKE_ESCAPE_CHAR))
        )

    session = _session_scope()
    try:
        moments = session.execute(stmt).all()
    finally:
        session.close()

    counts: Counter[str] = Counter()
    for (moment,) in moments:
        key = gallery_day_key(moment)
        if key is not None:
            counts[key] += 1

    days = [{"day": day, "count": counts[day]} for day in sorted(counts)]
    return {
        "days": days,
        "total": sum(counts.values()),
        "first_day": days[0]["day"] if days else None,
        "last_day": days[-1]["day"] if days else None,
        "day_rule": "utc",
    }


# ── public API ──────────────────────────────────────────────────────────────


def get_base_statistics() -> dict[str, Any]:
    """Aggregate usage summary. Every distribution is a SQL `GROUP BY`."""
    session = _session_scope()
    try:
        totals = _totals(session, None)

        models = _count_map(_grouped(session, ["checkpoint"]))
        samplers = _count_map(_grouped(session, ["sampler"]))
        schedulers = _count_map(_grouped(session, ["scheduler"]))
        steps = _count_map(_grouped(session, ["steps"]))
        cfg = _count_map(_grouped(session, ["cfg"]))
        resolutions = _count_map(_grouped(session, ["resolution"]))

        # LoRA usage flattens an array column, so it stays in the row pass.
        loras: dict[str, int] = {}
        images_by_date: dict[str, int] = {}
        for lora_array, job_ts, generated_at, created_at in _row_pass(
            session, None, with_prompts=False
        ):
            for name in _lora_names(lora_array):
                loras[name] = loras.get(name, 0) + 1
            moment = _resolved_timestamp(job_ts, generated_at, created_at)
            if moment is not None:
                day = moment.strftime("%Y-%m-%d")
                images_by_date[day] = images_by_date.get(day, 0) + 1

        duration_count = totals["duration_count"] or 0
        return {
            "total_images": totals["total"],
            "models": _sorted_counts(models),
            "loras": _sorted_counts(loras),
            "samplers": _sorted_counts(samplers),
            "schedulers": _sorted_counts(schedulers),
            "avg_generation_time": (
                round(float(totals["duration_sum"]) / duration_count, 2) if duration_count else 0
            ),
            "total_generation_time": round(float(totals["duration_sum"]), 2) if duration_count else 0,
            "images_by_date": dict(sorted(images_by_date.items())),
            "popular_settings": {
                "steps": steps,
                "cfg": cfg,
                "resolution": resolutions,
            },
            "enriched_metadata_count": totals["enriched"],
            "legacy_metadata_count": totals["total"] - totals["enriched"],
        }
    finally:
        session.close()


def get_detailed_statistics(time_range: str = "all") -> dict[str, Any]:
    """Chart-ready breakdown for the Statistics page."""
    session = _session_scope()
    try:
        cutoff = resolve_time_range(time_range)
        where = _time_range_filter(cutoff) if cutoff is not None else None
        totals = _totals(session, where)

        # Single-dimension groupings supply the distributions and the
        # `performance.by_*` breakdowns. Two-key groupings supply only the
        # matrices and correlations, which are meaningless without both parts.
        #
        # The two kinds cannot be merged: the marginal of a joint grouping
        # silently omits every row that lacks the *other* dimension, so deriving
        # `models.checkpoints` from `GROUP BY (checkpoint, sampler)` would drop
        # any checkpoint generated without a recorded sampler.
        checkpoint_rows = _grouped(session, ["checkpoint"], where=where, with_duration=True)
        sampler_rows = _grouped(session, ["sampler"], where=where)
        scheduler_rows = _grouped(session, ["scheduler"], where=where)
        vae_rows = _grouped(session, ["vae"], where=where)
        steps_rows = _grouped(session, ["steps"], where=where, with_duration=True)
        cfg_rows = _grouped(session, ["cfg"], where=where)
        resolution_rows = _grouped(session, ["resolution"], where=where, with_duration=True)

        steps_cfg_rows = _grouped(session, ["steps", "cfg"], where=where)
        model_sampler_rows = _grouped(session, ["checkpoint", "sampler"], where=where)
        model_res_rows = _grouped(session, ["checkpoint", "resolution"], where=where)

        steps = _count_map(steps_rows)
        cfg = _count_map(cfg_rows, _clean_cfg)
        resolutions = _count_map(resolution_rows)
        by_steps = _performance_map(steps_rows)
        by_model = _performance_map(checkpoint_rows)
        by_resolution = _performance_map(resolution_rows)

        steps_cfg = [
            {"steps": _as_number(s), "cfg": _as_number(_clean_cfg(c)), "count": count}
            for s, c, count in steps_cfg_rows
        ]

        model_sampler_matrix: dict[str, dict[str, int]] = {}
        for model_key, sampler_key, count in model_sampler_rows:
            bucket = model_sampler_matrix.setdefault(_clean(model_key), {})
            sampler_name = _clean(sampler_key)
            bucket[sampler_name] = bucket.get(sampler_name, 0) + count

        model_resolution = [
            {"model": _clean(model_key), "resolution": _clean(res_key), "count": count}
            for model_key, res_key, count in model_res_rows
        ]

        # The prompt-derived aggregates are a pure function of the prompt strings,
        # so they are reused when the content hash is unchanged. This is an exact
        # cache, not an approximation — see `_prompt_signature`.
        signature = _prompt_signature(session, where)
        cached_prompts = _cached_prompt_aggregates(session, where, signature)

        # Per-row work: LoRA weights, prompt keywords, timeline buckets.
        lora_weights: dict[str, list[float]] = {}
        daily: dict[str, int] = {}
        hourly: dict[str, int] = {}
        weekday: dict[str, int] = {}

        for row in _row_pass(session, where, with_prompts=cached_prompts is None):
            lora_array, job_ts, generated_at, created_at, *prompt_columns = row

            for name, weight in _lora_entries(lora_array):
                lora_weights.setdefault(name, []).append(weight)

            moment = _resolved_timestamp(job_ts, generated_at, created_at)
            if moment is not None:
                day = moment.date().isoformat()
                daily[day] = daily.get(day, 0) + 1
                hour = str(moment.hour)
                hourly[hour] = hourly.get(hour, 0) + 1
                dow = str(moment.weekday())
                weekday[dow] = weekday.get(dow, 0) + 1

        if cached_prompts is not None:
            keyword_counts = Counter(cached_prompts["keywords"])
            prompt_total = cached_prompts["total"]
            prompt_len_sum = cached_prompts["length_sum"]
            prompt_len_min = cached_prompts["length_min"]
            prompt_len_max = cached_prompts["length_max"]
            negative_usage = cached_prompts["negative_usage"]
        else:
            keyword_counts = Counter()
            prompt_total = 0
            prompt_len_sum = 0
            prompt_len_min = None
            prompt_len_max = None
            negative_usage = 0

            for row in _row_pass(session, where, with_prompts=True):
                prompt, negative = row[4], row[5]

                if negative is not None and str(negative).strip():
                    negative_usage += 1

                if prompt is None:
                    continue
                prompt_total += 1
                text = prompt if isinstance(prompt, str) else str(prompt)
                length = len(text)
                prompt_len_sum += length
                prompt_len_min = length if prompt_len_min is None else min(prompt_len_min, length)
                prompt_len_max = length if prompt_len_max is None else max(prompt_len_max, length)
                # `Counter.update` tallies in C; a per-word `dict.get` loop over
                # ~1.3M words was the single most expensive thing in this function.
                keyword_counts.update(
                    word
                    for word in _WORD_RE.findall(text.lower())
                    if word not in _STOP_WORDS
                )

            _store_prompt_aggregates(signature, {
                "keywords": dict(keyword_counts),
                "total": prompt_total,
                "length_sum": prompt_len_sum,
                "length_min": prompt_len_min,
                "length_max": prompt_len_max,
                "negative_usage": negative_usage,
            })

        duration_count = totals["duration_count"] or 0
        total_time = round(float(totals["duration_sum"]), 2)
        pillars = _pillar_counts(session)
        pillars["images"] = totals["total"]

        for values in (by_model, by_resolution, by_steps):
            for key in [k for k, entry in values.items() if not entry["count"]]:
                del values[key]
            for entry in values.values():
                entry["avg"] = round(entry["total_time"] / entry["count"], 2)

        return {
            "timeline": {
                "daily": dict(sorted(daily.items())),
                "hourly": _sorted_counts(hourly),
                "weekday": _sorted_counts(weekday),
            },
            "models": {
                "checkpoints": _sorted_counts(_count_map(checkpoint_rows)),
                "loras": _sorted_counts(
                    {name: len(weights) for name, weights in lora_weights.items()}
                ),
                "lora_weights": sorted(
                    (
                        {
                            "name": name,
                            "avg_weight": round(sum(weights) / len(weights), 2),
                            "count": len(weights),
                        }
                        for name, weights in lora_weights.items()
                    ),
                    key=lambda item: item["count"],
                    reverse=True,
                ),
                "vaes": _sorted_counts(_count_map(vae_rows)),
                "samplers": _sorted_counts(_count_map(sampler_rows)),
                "schedulers": _sorted_counts(_count_map(scheduler_rows)),
            },
            "settings": {
                "steps": _sorted_counts(steps),
                "cfg": _sorted_counts(cfg),
                "resolutions": _sorted_counts(resolutions),
                "seeds_random": totals["seeds_random"],
                "seeds_fixed": totals["seeds_fixed"],
            },
            "prompts": {
                "keywords": dict(keyword_counts.most_common(100)),
                "avg_length": round(prompt_len_sum / prompt_total, 1) if prompt_total else 0,
                "min_length": prompt_len_min or 0,
                "max_length": prompt_len_max or 0,
                "negative_usage": negative_usage,
                "total": prompt_total,
            },
            "performance": {
                "by_model": by_model,
                "by_resolution": by_resolution,
                "by_steps": by_steps,
                "fastest": round(float(totals["duration_min"]), 2) if totals["duration_min"] else None,
                "slowest": round(float(totals["duration_max"]), 2) if totals["duration_max"] else None,
                "total_time": total_time,
                "avg_time": round(total_time / duration_count, 2) if duration_count else 0,
                "success_rate": _image_job_success_rate(session),
            },
            "model_sampler_matrix": model_sampler_matrix,
            "correlations": {
                "steps_cfg": sorted(steps_cfg, key=lambda item: item["count"], reverse=True),
                "model_resolution": sorted(
                    model_resolution, key=lambda item: item["count"], reverse=True
                ),
            },
            "total_images": totals["total"],
            "enriched_count": totals["enriched"],
            "legacy_count": totals["total"] - totals["enriched"],
            "pillars": pillars,
        }
    finally:
        session.close()


def get_stats_summary() -> dict[str, Any]:
    """Quick headline numbers derived from the base aggregate."""
    base = get_base_statistics()
    models = base.get("models") or {}
    samplers = base.get("samplers") or {}
    return {
        "total_images": base.get("total_images", 0),
        "models_used": len(models),
        "loras_used": len(base.get("loras") or {}),
        "avg_generation_time": base.get("avg_generation_time", 0),
        "top_model": next(iter(models), None),
        "top_sampler": next(iter(samplers), None),
    }


# ── small local helpers ─────────────────────────────────────────────────────


def _as_number(value: Any) -> Any:
    """Render a grouping key as a number when it is one, else as text.

    The correlations carry `steps` and `cfg` as numbers; a plain `str()` would
    turn 30 into "30" and 7.0 into "7.0", which the charts coerce back anyway.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    text = str(value)
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _clean_cfg(value: Any) -> str:
    """Normalise a cfg grouping key to one canonical float rendering.

    `metadata_` stores cfg as an int for some rows and a float for others, so
    keying on the raw text would split one setting into two chart series
    ("4" and "4.0"). Float normalisation is what the previous Python loop did,
    and it is kept so the distribution stays a single series per value.
    """
    cleaned = _clean(value)
    if cleaned is None:
        return "Unknown"
    try:
        return str(float(cleaned))
    except (TypeError, ValueError):
        return cleaned


def _lora_entries(lora_array: Any) -> Iterable[tuple[str, float]]:
    """`(name, weight)` for every entry of a `loras` array column."""
    if not isinstance(lora_array, (list, tuple)):
        return
    for item in lora_array:
        if isinstance(item, dict):
            name = item.get("name") or item.get("filename") or "Unknown"
            try:
                weight = float(item.get("weight", 1.0))
            except (TypeError, ValueError):
                weight = 1.0
        else:
            name, weight = str(item), 1.0
        yield str(name), weight


def _lora_names(lora_array: Any) -> Iterable[str]:
    return (name for name, _weight in _lora_entries(lora_array))
