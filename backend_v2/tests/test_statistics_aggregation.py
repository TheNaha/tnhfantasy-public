"""Statistics aggregation tests.

These seed real `Asset` rows and run the real SQL aggregations. The previous
statistics test files (test_statistics.py, test_statistics_extended.py,
test_statistics_internal.py, test_statistics_optimization.py) mocked
`api.routes.statistics._all_gallery_files` and asserted on the shape of a
Python loop, which meant the SQL those aggregations now run was never executed
by the suite at all. The mock also coupled every case to an implementation
detail, so the same scenario was re-specified four times.

Everything here runs on the same SQLite dialect as production Postgres because
`services/statistics_service` builds its SQL from SQLAlchemy constructs that
compile to `->>` on Postgres and `JSON_EXTRACT` on SQLite.
"""


from datetime import datetime, timedelta, timezone

import pytest
from infrastructure.cache import invalidate_cache
from sqlmodel import Session

from core.entities import Asset
from services import statistics_service
from services.asset_reconciler import derive_stat_columns, upsert_asset

# Anchored to the wall clock, not a fixed date: `timeRange` cutoffs are computed
# from `datetime.now()`, so a hardcoded anchor silently ages out of every window.
NOW = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def make_asset(
    session: Session,
    name: str,
    metadata: dict | None = None,
    *,
    width: int | None = 1024,
    height: int | None = 1024,
    age_hours: float = 1.0,
) -> Asset:
    """Insert an asset through the real write path, as production does."""
    relative_path = f"default_user/main/now/{name}.png"
    created = NOW - timedelta(hours=age_hours)
    upsert_asset(
        session,
        relative_path=relative_path,
        filename=f"{name}.png",
        width=width,
        height=height,
        generated_at=created,
        metadata=metadata or {},
    )
    # duration_seconds is derived from metadata by upsert_asset, so a test that
    # wants a specific duration states it in the metadata.
    asset = session.exec(Asset.__table__.select().where(Asset.relative_path == relative_path)).first()
    return asset


ENRICHED = {
    "metadata_version": "2.0",
    "checkpoint": {"name": "nova_xl.safetensors"},
    "loras": [{"name": "style.safetensors", "weight": 0.8}],
    "sampler": "euler",
    "scheduler": "normal",
    "steps": 30,
    "cfg": 7.0,
    "width": 1024,
    "height": 1024,
    "prompt": "a beautiful painted landscape with soft light",
    "negativePrompt": "blurry, lowres",
    "seed": 12345,
    "job": {"duration_seconds": 12.5},
}


@pytest.fixture(name="populated")
def populated_fixture(session: Session):
    """Three assets covering the shapes that matter: enriched, legacy string
    checkpoint, and a row with no duration at all."""
    make_asset(session, "a", ENRICHED)
    make_asset(
        session,
        "b",
        {
            "metadata_version": "2.0",
            "checkpoint": "legacy_string_model.safetensors",
            "loras": [{"name": "style.safetensors", "weight": 1.2}],
            "sampler": "dpm",
            "scheduler": "karras",
            "steps": 30,
            "cfg": 7.0,
            "width": 512,
            "height": 768,
            "prompt": "a beautiful portrait",
            "seed": -1,
            "job": {"duration_seconds": 7.5},
        },
        width=512,
        height=768,
    )
    make_asset(session, "c", {"sampler": "euler", "width": 1024, "height": 1024}, width=1024, height=1024)
    return session


@pytest.fixture(autouse=True)
def _clear_stats_cache():
    invalidate_cache("stats")
    yield
    invalidate_cache("stats")


# ── base summary ────────────────────────────────────────────────────────────


def test_empty_index_reports_zeros(session: Session):
    stats = statistics_service.get_base_statistics()
    assert stats["total_images"] == 0
    assert stats["models"] == {}
    assert stats["loras"] == {}
    assert stats["samplers"] == {}
    assert stats["avg_generation_time"] == 0
    assert stats["images_by_date"] == {}
    assert stats["enriched_metadata_count"] == 0
    assert stats["legacy_metadata_count"] == 0


def test_counts_every_asset_with_metadata(populated: Session):
    stats = statistics_service.get_base_statistics()
    assert stats["total_images"] == 3


def test_soft_deleted_assets_are_excluded(session: Session):
    make_asset(session, "live", ENRICHED)
    make_asset(session, "gone", ENRICHED)
    session.exec(Asset.__table__.update().where(Asset.filename == "gone.png").values(deleted_at=NOW))
    session.commit()

    assert statistics_service.get_base_statistics()["total_images"] == 1


def test_model_sampler_and_scheduler_counts(populated: Session):
    stats = statistics_service.get_base_statistics()
    assert stats["models"] == {"nova_xl.safetensors": 1, "legacy_string_model.safetensors": 1}
    assert stats["samplers"] == {"euler": 2, "dpm": 1}
    assert stats["schedulers"] == {"normal": 1, "karras": 1}


def test_lora_usage_is_flattened_across_the_array(session: Session):
    make_asset(session, "a", {"loras": [{"name": "one.safetensors"}, {"name": "two.safetensors"}]})
    make_asset(session, "b", {"loras": [{"name": "one.safetensors"}]})
    assert statistics_service.get_base_statistics()["loras"] == {
        "one.safetensors": 2,
        "two.safetensors": 1,
    }


def test_popular_settings(populated: Session):
    settings = statistics_service.get_base_statistics()["popular_settings"]
    assert settings["steps"] == {"30": 2}
    # cfg is stored as a real float column, so 7 and 7.0 are one series, not two.
    assert settings["cfg"] == {"7.0": 2}
    # Resolution is read from the real image columns. A row whose metadata claims
    # a size the decoder rounded away is reported at the size it actually is.
    assert settings["resolution"] == {"1024x1024": 2, "512x768": 1}


def test_resolution_uses_the_image_columns_not_the_requested_latent_size(session: Session):
    make_asset(
        session,
        "rounded",
        {"width": 1024, "height": 1277},
        width=1024,
        height=1272,
    )
    settings = statistics_service.get_base_statistics()["popular_settings"]
    assert settings["resolution"] == {"1024x1272": 1}


def test_duration_averages_only_positive_values(session: Session):
    make_asset(session, "a", {"job": {"duration_seconds": 10}})
    make_asset(session, "b", {"job": {"duration_seconds": 30}})
    make_asset(session, "c", {"job": {"duration_seconds": 0}})
    make_asset(session, "d", {})
    stats = statistics_service.get_base_statistics()
    assert stats["total_generation_time"] == 40
    assert stats["avg_generation_time"] == 20


def test_enriched_and_legacy_split(populated: Session):
    stats = statistics_service.get_base_statistics()
    assert stats["enriched_metadata_count"] == 2
    assert stats["legacy_metadata_count"] == 1


def test_images_by_date_uses_the_job_completion_time(session: Session):
    stamp = (NOW - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    make_asset(session, "a", {"job": {"completed_at": stamp}}, age_hours=0)
    stats = statistics_service.get_base_statistics()
    assert stats["images_by_date"] == {(NOW - timedelta(days=2)).date().isoformat(): 1}


def test_images_by_date_falls_back_to_the_row_timestamp(session: Session):
    make_asset(session, "a", {}, age_hours=30)
    stats = statistics_service.get_base_statistics()
    assert stats["images_by_date"] == {(NOW - timedelta(hours=30)).date().isoformat(): 1}


# ── detailed ────────────────────────────────────────────────────────────────


def test_detailed_empty_index_has_every_section(session: Session):
    stats = statistics_service.get_detailed_statistics("all")
    for section in ("timeline", "models", "settings", "prompts", "performance", "correlations"):
        assert section in stats
    assert stats["total_images"] == 0
    assert stats["prompts"]["total"] == 0
    assert stats["performance"]["total_time"] == 0
    assert stats["performance"]["success_rate"] is None


def test_detailed_counts_legacy_string_checkpoints(populated: Session):
    """A bare-string checkpoint is a real legacy shape and must be counted, not
    dropped the way the old detailed loop dropped it."""
    stats = statistics_service.get_detailed_statistics("all")
    assert stats["models"]["checkpoints"] == {
        "nova_xl.safetensors": 1,
        "legacy_string_model.safetensors": 1,
    }


def test_lora_weights_average_per_lora(session: Session):
    make_asset(session, "a", {"loras": [{"name": "style.safetensors", "weight": 0.6}]})
    make_asset(session, "b", {"loras": [{"name": "style.safetensors", "weight": 0.8}]})
    weights = statistics_service.get_detailed_statistics("all")["models"]["lora_weights"]
    assert weights == [{"name": "style.safetensors", "avg_weight": 0.7, "count": 2}]


def test_lora_weight_defaults_to_one_when_absent(session: Session):
    make_asset(session, "a", {"loras": [{"name": "style.safetensors"}]})
    weights = statistics_service.get_detailed_statistics("all")["models"]["lora_weights"]
    assert weights[0]["avg_weight"] == 1.0


def test_prompt_analytics(session: Session):
    make_asset(session, "a", {"prompt": "a beautiful red fox in the snow", "negativePrompt": "blurry"})
    make_asset(session, "b", {"prompt": "a beautiful red boat"})
    prompts = statistics_service.get_detailed_statistics("all")["prompts"]
    assert prompts["total"] == 2
    assert prompts["negative_usage"] == 1
    assert prompts["keywords"]["beautiful"] == 2
    assert prompts["keywords"]["red"] == 2
    # Stop words and sub-3-character fragments are excluded.
    assert "the" not in prompts["keywords"]
    assert "a" not in prompts["keywords"]
    assert prompts["min_length"] == len("a beautiful red boat")
    assert prompts["max_length"] == len("a beautiful red fox in the snow")


def test_prompt_length_array_is_not_returned(session: Session):
    """The old payload shipped a per-asset `lengths` array (~16k entries) that
    nothing read; avg/min/max carry the same information."""
    stats = statistics_service.get_detailed_statistics("all")
    assert "lengths" not in stats["prompts"]


def test_timeline_buckets_by_day_hour_and_weekday(session: Session):
    # Pick two distinct hours on the anchor's own date so the day bucket has one key.
    day = NOW.date()
    early = f"{day.isoformat()}T03:00:00.000Z"
    late = f"{day.isoformat()}T15:00:00.000Z"
    make_asset(session, "a", {"job": {"completed_at": early}}, age_hours=0)
    make_asset(session, "b", {"job": {"completed_at": late}}, age_hours=0)
    timeline = statistics_service.get_detailed_statistics("all")["timeline"]
    assert timeline["daily"] == {day.isoformat(): 2}
    assert timeline["hourly"] == {"3": 1, "15": 1}
    assert timeline["weekday"] == {str(day.weekday()): 2}


def test_timeline_accepts_a_numeric_job_completion_time(session: Session):
    """Legacy rows store an epoch float, not an ISO string."""
    make_asset(session, "a", {"job": {"completed_at": NOW.timestamp()}})
    timeline = statistics_service.get_detailed_statistics("all")["timeline"]
    assert sum(timeline["daily"].values()) == 1


def test_time_range_filters_by_job_completion_time(session: Session):
    make_asset(session, "recent", {"job": {"completed_at": NOW.isoformat()}}, age_hours=0)
    make_asset(
        session,
        "old",
        {"job": {"completed_at": (NOW - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%S.000Z")}},
        age_hours=0,
    )

    assert statistics_service.get_detailed_statistics("all")["total_images"] == 2
    assert statistics_service.get_detailed_statistics("24h")["total_images"] == 1


def test_unknown_time_range_is_treated_as_all(session: Session):
    make_asset(session, "a", ENRICHED)
    assert statistics_service.get_detailed_statistics("nonsense")["total_images"] == 1


def test_performance_breakdowns_exclude_models_without_durations(session: Session):
    make_asset(session, "a", {"checkpoint": {"name": "fast.safetensors"}, "job": {"duration_seconds": 4}})
    make_asset(session, "b", {"checkpoint": {"name": "slow.safetensors"}, "job": {"duration_seconds": 16}})
    make_asset(session, "c", {"checkpoint": {"name": "unknown.safetensors"}})
    performance = statistics_service.get_detailed_statistics("all")["performance"]
    assert set(performance["by_model"]) == {"fast.safetensors", "slow.safetensors"}
    assert performance["by_model"]["fast.safetensors"] == {
        "total_time": 4.0,
        "count": 1,
        "avg": 4.0,
    }
    assert performance["fastest"] == 4.0
    assert performance["slowest"] == 16.0
    assert performance["total_time"] == 20.0
    assert performance["avg_time"] == 10.0


def test_model_sampler_matrix_and_correlations(populated: Session):
    stats = statistics_service.get_detailed_statistics("all")
    assert stats["model_sampler_matrix"]["nova_xl.safetensors"] == {"euler": 1}
    pairs = {(row["steps"], row["cfg"]): row["count"] for row in stats["correlations"]["steps_cfg"]}
    assert pairs[(30, 7.0)] == 2
    assert stats["correlations"]["model_resolution"]


def test_seed_counters(session: Session):
    make_asset(session, "a", {"seed": 42})
    make_asset(session, "b", {"seed": -1})
    make_asset(session, "c", {})
    settings = statistics_service.get_detailed_statistics("all")["settings"]
    assert settings["seeds_fixed"] == 1
    assert settings["seeds_random"] == 2


def test_pillar_counts_are_included(session: Session):
    stats = statistics_service.get_detailed_statistics("all")
    assert stats["pillars"]["images"] == 0
    for key in ("characters", "chats", "messages", "stories", "story_chapters", "lorebooks", "image_jobs", "llm_jobs"):
        assert key in stats["pillars"]


def test_success_rate_is_reported_when_jobs_exist(session: Session):
    from core.entities import Job, JobStatus

    for status in (JobStatus.COMPLETED, JobStatus.COMPLETED, JobStatus.FAILED):
        session.add(Job(task_type="image", status=status))
    session.add(Job(task_type="llm", status=JobStatus.COMPLETED))
    session.commit()

    rate = statistics_service.get_detailed_statistics("all")["performance"]["success_rate"]
    assert rate == 0.6667


# ── summary ─────────────────────────────────────────────────────────────────


def test_summary_derives_headline_numbers(populated: Session):
    summary = statistics_service.get_stats_summary()
    assert summary["total_images"] == 3
    assert summary["models_used"] == 2
    assert summary["loras_used"] == 1
    assert summary["top_model"] in {"nova_xl.safetensors", "legacy_string_model.safetensors"}
    assert summary["top_sampler"] == "euler"


# ── rollup columns ──────────────────────────────────────────────────────────


def test_derive_stat_columns_reads_the_document():
    derived = derive_stat_columns(ENRICHED)
    assert derived == {
        "duration_seconds": 12.5,
        "job_completed_at": None,
        "checkpoint_name": "nova_xl.safetensors",
        "sampler": "euler",
        "scheduler": "normal",
        "vae": None,
        "steps": 30,
        "cfg": 7.0,
        "seed": 12345,
        "metadata_version": "2.0",
    }


def test_derive_stat_columns_tolerates_junk():
    derived = derive_stat_columns(
        {
            "checkpoint": {"nope": 1},
            "sampler": {"not": "a string"},
            "steps": "not a number",
            "cfg": [1, 2],
            "seed": True,
            "job": {"duration_seconds": "junk"},
        }
    )
    assert derived["checkpoint_name"] is None
    assert derived["sampler"] is None
    assert derived["steps"] is None
    assert derived["cfg"] is None
    assert derived["seed"] is None
    assert derived["duration_seconds"] is None


def test_derive_stat_columns_of_nothing_is_all_null():
    assert all(value is None for value in derive_stat_columns(None).values())
    assert all(value is None for value in derive_stat_columns({}).values())


def test_upsert_writes_rollup_columns_matching_the_document(populated: Session):
    """The columns are a rollup, so they must never disagree with `metadata_`."""
    for asset in populated.exec(Asset.__table__.select()).all():
        expected = derive_stat_columns(asset.metadata_)
        for column, value in expected.items():
            assert getattr(asset, column) == value, f"{asset.filename}.{column}"


def test_upsert_is_idempotent_and_refreshes_rollups(session: Session):
    upsert_asset(session, relative_path="p/x.png", filename="x.png", metadata={"sampler": "euler"})
    upsert_asset(
        session,
        relative_path="p/x.png",
        filename="x.png",
        metadata={"sampler": "dpm", "checkpoint": {"name": "new.safetensors"}},
    )
    asset = session.exec(Asset.__table__.select()).one()
    assert asset.sampler == "dpm"
    assert asset.checkpoint_name == "new.safetensors"


# ── HTTP surface ────────────────────────────────────────────────────────────


def test_endpoints_respond(client, session: Session):
    make_asset(session, "a", ENRICHED)

    base = client.get("/api/statistics")
    assert base.status_code == 200
    assert base.json()["total_images"] == 1

    detailed = client.get("/api/statistics/detailed?timeRange=all")
    assert detailed.status_code == 200
    body = detailed.json()
    assert body["total_images"] == 1
    assert body["prompts"]["total"] == 1

    summary = client.get("/api/statistics/summary")
    assert summary.status_code == 200
    assert summary.json()["total_images"] == 1


# ── prompt cache ─────────────────────────────────────────────────────────────


def test_prompt_cache_returns_identical_output_on_a_second_call(populated: Session):
    """The prompt-derived aggregates are a pure function of the prompt strings,
    so a cache hit must be indistinguishable from a miss."""
    first = statistics_service.get_detailed_statistics("all")["prompts"]
    second = statistics_service.get_detailed_statistics("all")["prompts"]
    assert first == second


def test_prompt_cache_is_invalidated_when_a_prompt_changes(session: Session):
    """The cache key is an exact content hash, so an edit to an existing prompt
    must be seen even though the row count and id are unchanged."""
    make_asset(session, "a", {"prompt": "alpha beta gamma"})
    baseline = statistics_service.get_detailed_statistics("all")["prompts"]
    assert baseline["keywords"].get("alpha") == 1

    asset = session.exec(Asset.__table__.select()).one()
    # Same length as before, so a signature built from total length would miss it.
    session.exec(
        Asset.__table__.update()
        .where(Asset.relative_path == asset.relative_path)
        .values(metadata_={"prompt": "alpha beta delta"})
    )
    session.commit()

    updated = statistics_service.get_detailed_statistics("all")["prompts"]
    assert "gamma" not in updated["keywords"]
    assert updated["keywords"].get("delta") == 1


def test_the_prompt_signature_orders_the_aggregate_on_postgres():
    """`string_agg` without ORDER BY emits rows in executor order.

    Stable for a sequential scan, not for a parallel or index-driven plan — so
    the same table produced two different hashes, the cache missed on unchanged
    data, and the entire 1.4s rebuild was paid for a key that was read once.

    Behaviour testing cannot see this on SQLite: SQLite's own `string_agg`
    happens to follow scan order, so the caveat is invisible locally. Pinned by
    reading the production source instead, which is the only place the difference
    is observable from here.

    An earlier version of this test built its own statement and asserted ORDER BY
    on it, which passed whether or not production ordered anything — it was
    testing SQLAlchemy's compiler, not this code.
    """
    import ast
    import inspect
    import textwrap

    from services import statistics_service

    # Strip comments AND docstrings, and normalise indentation: the function's
    # own explanation quotes `aggregate_order_by` at length, so a plain
    # `inspect.getsource` substring check matches its prose and passes whether or
    # not the ordering survived. `ast.walk` over docstring-stripped statements
    # leaves only what executes.
    tree = ast.parse(textwrap.dedent(inspect.getsource(statistics_service._prompt_signature)))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body = node.body[1:] or [ast.Pass()]
    src = ast.unparse(tree)

    assert "aggregate_order_by" in src, (
        "the ordered string_agg is gone, so the prompt cache key depends on the "
        "query plan again and misses on unchanged data"
    )
    # And it must be gated on the dialect: the construct cannot be compiled by
    # any other dialect, so an unconditional one is a compile-time crash on the
    # SQLite the test suite runs, not a better hash.
    # `ast.unparse` normalises quote style, so assert on the rendered form.
    assert "'postgresql'" in src, (
        "aggregate_order_by is no longer gated on the dialect"
    )
    # The plain form must still exist for the other branch.
    assert "func.string_agg(pair, literal(''))" in src, (
        "the non-Postgres branch no longer has a plain string_agg, so the "
        "ordered form is unconditional and the SQLite suite fails at compile time"
    )


def test_prompt_cache_is_scoped_per_time_range(session: Session):
    """Two ranges in flight must not share a cache entry."""
    make_asset(session, "old", {"prompt": "ancient keywords here"}, age_hours=48 * 30)
    make_asset(session, "new", {"prompt": "recent keywords here"}, age_hours=0)

    everything = statistics_service.get_detailed_statistics("all")["prompts"]
    recent = statistics_service.get_detailed_statistics("24h")["prompts"]

    assert "ancient" in everything["keywords"]
    assert "ancient" not in recent["keywords"]
    assert "recent" in recent["keywords"]


def test_derive_stat_columns_resolves_the_job_completion_time():
    """Both encodings the writer has ever produced: an ISO string on enriched
    rows, an epoch float on legacy ones."""
    iso = derive_stat_columns({"job": {"completed_at": "2026-09-20T10:00:00.000Z"}})
    assert iso["job_completed_at"] == datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)

    epoch = derive_stat_columns({"job": {"completed_at": 1789898400.0}})
    assert epoch["job_completed_at"] == datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)

    # A timestamp with no offset is read as UTC, matching the container clock.
    naive = derive_stat_columns({"job": {"completed_at": "2026-09-20T10:00:00"}})
    assert naive["job_completed_at"] == datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)


def test_derive_stat_columns_ignores_an_unparseable_completion_time():
    for junk in ({"job": {"completed_at": "not a date"}}, {"job": {"completed_at": ""}}, {"job": {}}, {}):
        assert derive_stat_columns(junk)["job_completed_at"] is None


# ── the gallery day histogram: bucketed in SQL, and cached ───────────────────
#
# This endpoint used to ship 16,518 timestamps out of the database and count them
# in Python. Measured on this deployment, the scan was 80-109 ms of a 296 ms
# request, so ~two thirds of it was the row pass — and because each request opens
# its own session, sixteen of them inverted throughput (c=1 3.35 rps → c=16
# 2.53 rps). So both halves are pinned here: the day bucket has to reach the
# statement, and the unfiltered form has to be cached.


def histogram_sql(engine, call) -> list[str]:
    """Every statement `call` sends to `engine`."""
    from sqlalchemy import event

    seen: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(_conn, _cursor, statement, _params, _ctx, _many):
        seen.append(" ".join(str(statement).split()))

    try:
        call()
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    return seen


class TestDayBucket:
    def test_postgres_buckets_the_day_in_sql(self):
        """The production dialect has to do its own bucketing. `date_trunc` on a
        `timestamp without time zone` truncates the stored wall clock, which is
        UTC — the same assumption `gallery_day_key` makes when it reads a naive
        value, so the two agree by construction and not by coincidence."""
        from sqlalchemy.dialects import postgresql

        bucket = statistics_service._day_bucket(
            "postgresql", statistics_service.ASSET_GALLERY_TIMESTAMP
        )
        assert bucket is not None
        sql = " ".join(
            str(
                bucket.compile(
                    dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
                )
            ).split()
        )
        assert sql.lower().startswith("date_trunc('day', coalesce(assets.generated_at"), sql

    def test_a_dialect_without_date_trunc_buckets_in_python(self):
        """SQLite is the dialect the suite runs on, and it has no `date_trunc`."""
        assert statistics_service._day_bucket("sqlite", statistics_service.ASSET_GALLERY_TIMESTAMP) is None

    def test_the_bucket_reaches_the_statement(self, session, engine, monkeypatch):
        """Structural, and the only honest assertion for "the grouping moved into
        SQL": stand a SQLite-valid bucket in for `date_trunc` and read the SQL off
        the wire. Reverting to the Python pass drops the expression from the
        statement and this fails."""
        from sqlalchemy import func

        monkeypatch.setattr(
            statistics_service,
            "_day_bucket",
            lambda dialect_name, moment: func.strftime("%Y-%m-%d", moment),
        )
        sql = histogram_sql(engine, statistics_service.get_asset_date_histogram)
        assert sql, "the histogram issued no statement at all"
        assert any("strftime" in statement and "GROUP BY" in statement.upper() for statement in sql), sql
        # The row pass is gone: no statement selects the bare timestamp column.
        assert not any(
            statement.startswith("SELECT assets.generated_at") for statement in sql
        ), sql

    def test_both_branches_produce_the_same_day_keys(self, session, engine, monkeypatch):
        """A dialect branch that changes the answer is a bug, not an optimisation.
        Seeded across three UTC days, then compared key for key."""
        base = NOW
        for offset, count in ((0, 2), (1, 1), (40, 3)):
            for index in range(count):
                session.add(
                    Asset(
                        filename=f"h{offset}-{index}.png",
                        relative_path=f"default_user/main/x/h{offset}-{index}.png",
                        workspace="main",
                        created_at=base + timedelta(days=offset),
                        generated_at=base + timedelta(days=offset),
                        metadata_={"prompt": "p"},
                    )
                )
        session.commit()

        python_side = statistics_service.get_asset_date_histogram()

        from sqlalchemy import func

        monkeypatch.setattr(
            statistics_service,
            "_day_bucket",
            lambda dialect_name, moment: func.strftime("%Y-%m-%d", moment),
        )
        sql_side = statistics_service.get_asset_date_histogram()
        assert sql_side == python_side, (python_side, sql_side)
        assert sql_side["total"] == 6
        assert [day["count"] for day in sql_side["days"]] == [2, 1, 3]


class TestUnfilteredHistogramCache:
    def _seed(self, session, filename="c.png"):
        session.add(
            Asset(
                filename=filename,
                relative_path=f"default_user/main/x/{filename}",
                workspace="main",
                created_at=NOW,
                generated_at=NOW,
                metadata_={"prompt": "p"},
            )
        )
        session.commit()

    def test_the_second_unfiltered_request_does_not_query(self, engine):
        """One statement for the first request, none for the second. Counting
        statements rather than timing: the defect being pinned is 'the scan runs
        again', which is a fact about the code path, not about this machine."""
        first = len(histogram_sql(engine, statistics_service.get_asset_date_histogram))
        assert first == 1, first
        second = histogram_sql(engine, statistics_service.get_asset_date_histogram)
        assert second == [], second

    def test_a_scoped_request_never_reads_the_unfiltered_cache(self, engine):
        """A character-scoped rail must not be served the whole-library one."""
        histogram_sql(engine, statistics_service.get_asset_date_histogram)
        scoped = histogram_sql(
            engine, lambda: statistics_service.get_asset_date_histogram(workspace="chat")
        )
        assert len(scoped) == 1, scoped

    def test_an_expired_entry_is_recomputed(self, engine, monkeypatch):
        monkeypatch.setattr(statistics_service, "_HISTOGRAM_CACHE_TTL_SECONDS", -1.0)
        histogram_sql(engine, statistics_service.get_asset_date_histogram)
        assert histogram_sql(engine, statistics_service.get_asset_date_histogram), "expired"
