"""Every index the migrations declare must exist in the live database.

Fourteen were declared in `steps.py`, had their migrations recorded as applied,
and did not exist. `ix_assets_gallery_ts` — the one that mattered — was a partial
expression index on `coalesce(generated_at, created_at) WHERE deleted_at IS NULL`,
and the 2026-10-01 audit reported it as present while citing the migration line
as evidence. The version table said it ran. The source said it ran. Nothing ever
looked at Postgres.

The cause is the shape thirteen dialect-gated migrations share:

    if conn.dialect.name != "postgresql":
        return True          # <- recorded as "applied", with nothing done

`backend_v2/data/comfy.db` is a SQLite database that ran the steps runner and
recorded those versions as done. `tests/conftest.py` still forces every session
onto a throwaway SQLite, so CI's Postgres — provided by
`.github/workflows/backend-tests.yml` as `PGVECTOR_TEST_URL` — is never asked
about indexes at all. A `return False` would retry forever on SQLite; `True`
claims success in every dialect.

Measured on the live stack, the gallery's own query before and after:

    Seq Scan on assets          15,374 buffers      41 ms
    Index Scan Backward              7 buffers   0.15 ms

273x faster on the app's most-used screen, from an index that was believed to be
there.

So this asserts the *effect* rather than the version list: parse every
`CREATE INDEX` out of the migration source and require it in `pg_indexes`. A
migration that records itself applied without doing its work is invisible to every
other check in this repo.
"""

import os
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import SQLModel

from infrastructure.migrations import run_migrations

STEPS = Path(__file__).resolve().parents[1] / "infrastructure" / "migrations" / "steps.py"
SOURCE = STEPS.read_text()

# `CREATE INDEX [CONCURRENTLY] [IF NOT EXISTS] <name>` — the name may be quoted.
_CREATE_INDEX = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?"
    r'["`]?([A-Za-z_][A-Za-z0-9_]*)',
    re.IGNORECASE,
)

# Indexes that belong to a feature that has been retired, so recreating them
# would be wrong. Each needs the reason it was removed.
RETIRED: dict[str, str] = {
    # `campaigns` was renamed to `worlds` by migration 077, which drops the
    # table. The two `CREATE INDEX idx_campaigns_name` statements that remain in
    # steps.py are inside the migrations that predate the rename and can never run
    # again — the table they index no longer exists on any database, fresh or
    # migrated. Declaring it "missing" would be a false positive; recreating it
    # would be a 500 on every boot.
    "idx_campaigns_name": "campaigns table dropped by migration 077 (renamed to worlds)",
}

# `CREATE INDEX [UNIQUE] [CONCURRENTLY] [IF NOT EXISTS] <name> [USING <method>]
#  ON <table> <balanced parenthesised key list>` — assembled from parts because
#  the key list contains nested parentheses (`coalesce(generated_at, created_at)`,
#  `vector_cosine_ops`), which a single regex cannot delimit.
_CREATE_INDEX_HEAD = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?"
    r'["`]?(?P<name>[A-Za-z_][A-Za-z0-9_]*)["`]?',
    re.IGNORECASE,
)
_CREATE_INDEX_ON = re.compile(
    # A statement split across adjacent Python string literals reads as
    # `... ix_jobs_claim "` + newline + `"ON jobs (...)`, so between the index
    # name and `ON` there is a closing quote, a newline and an opening quote —
    # none of them whitespace. `uq_stories_published_token` and the other six
    # were dropped from the coverage check by exactly that.
    r"[\"'`]?\s*ON\s+[\"'`]?(?P<table>[A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)


def _balanced_key_list(source: str, start: int) -> str | None:
    """The parenthesised key list beginning at/after `start`, or None.

    Scans for the matching close paren so an expression index parses whole. A
    naive `\\(([^)]*)\\)` truncates `coalesce(a, b)` at the first `)` and yields
    `coalesce(a, b` — which then compares unequal to the real index and reports a
    present index as missing.
    """
    open_at = source.find("(", start)
    if open_at == -1:
        return None
    depth = 0
    for pos in range(open_at, len(source)):
        char = source[pos]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return source[open_at + 1:pos]
    return None


def _normalise_key(key: str) -> str:
    """Compare index keys by shape, not by whitespace or quoting.

    Postgres rewrites what it is given: `USING btree (character_id)` comes back
    from `pg_indexes` as `(character_id)`, and a qualified reference comes back
    qualified. Lowercasing, dropping quoting and collapsing whitespace is enough
    to make the two sides comparable without pretending they are identical.
    """
    key = re.sub(r"\s+", " ", key.strip().lower())
    key = key.replace('"', "").replace("`", "")
    key = key.replace("public.", "")
    return key.strip()


def declared_indexes() -> dict[str, tuple[str, str] | None]:
    """Every index the migration source declares, mapped to `(table, key)`.

    The value is `None` when the statement could not be resolved to a table and
    key — those are still reported (by name) so a parse regression cannot quietly
    drop an index from the check.

    Names that are really f-string templates are skipped: the captured group
    stops before `{`, so the check looks at the source character after the match.
    Capturing `idx_job_` from `CREATE INDEX IF NOT EXISTS idx_job_{col_name}` as
    if it were literal produces a failure that means nothing, and a guard that
    cries wolf is a guard that gets deleted.
    """
    found: dict[str, tuple[str, str] | None] = {}
    for match in _CREATE_INDEX_HEAD.finditer(SOURCE):
        name = match.group("name")
        # `IF` and `NOT` are matched as names when the name that follows
        # `IF NOT EXISTS` is a template (`... IF NOT EXISTS {name}`), because the
        # optional group cannot match and the fallback does.
        if name.upper() in {"IF", "NOT", "EXISTS"}:
            continue
        if SOURCE[match.end():match.end() + 1] == "{":
            continue
        tail = SOURCE[match.end():match.end() + 400]
        on = _CREATE_INDEX_ON.search(tail)
        if on is None:
            found[name] = None
            continue
        table = on.group("table").lower()
        # The key list follows the table name, allowing for `USING <method>`.
        key = _balanced_key_list(tail, on.end())
        found[name] = (table, _normalise_key(key)) if key is not None else (table, "")
    for name in RETIRED:
        found.pop(name, None)
    return found


def test_we_parsed_the_migration_source() -> None:
    """Guards against the regex silently matching nothing.

    A sweep that matches zero things is indistinguishable from a healthy database,
    which is the failure mode this file exists to prevent.
    """
    names = declared_indexes()
    assert len(names) > 20, f"only found {len(names)} declared indexes; the parse is broken"
    assert "ix_assets_gallery_ts" in names, (
        "the index this file was written for is no longer declared in steps.py — "
        "if it was replaced, this test needs to know why"
    )
    unresolved = sorted(n for n, v in names.items() if v is None or not v[1])
    assert not unresolved, (
        "these CREATE INDEX statements did not resolve to a table and key, so they "
        "can only be checked by name and a rename would read as a missing index: "
        + ", ".join(unresolved)
    )


@pytest.fixture(scope="module")
def live_indexes() -> dict[str, tuple[str, str]] | None:
    """Index names in the Postgres named by `PGVECTOR_TEST_URL`, or None.

    Deliberately *not* the app's engine: `tests/conftest.py` forces every session
    onto a throwaway SQLite, and SQLite is exactly the dialect where these
    migrations return early and do nothing, so a test reading the app engine could
    only ever see the dialect that hides the bug.

    The database is **migrated first**, by the application's own startup path.
    CI provisions an empty `pgvector/pgvector:pg16` service container and exports
    `PGVECTOR_TEST_URL` pointing at it, so reading it unmigrated reports every
    declared index missing — the assertion cannot tell "this migration recorded
    itself applied without doing its work" from "nothing ever ran here", which is
    the one distinction this file exists to draw. Migrating first also upgrades
    the check: rather than trusting a database someone else prepared, it asserts
    that running the app's own `create_all` + `run_migrations` produces every
    index the source declares.

    Those migrations are additive and idempotent — they are what the backend runs
    on every boot — so pointing this at a development database migrates it rather
    than damaging it.
    """
    url = os.environ.get("PGVECTOR_TEST_URL")
    if not url:
        return None
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            if conn.dialect.name != "postgresql":
                return None
    except Exception as exc:  # pragma: no cover - environment dependent
        engine.dispose()
        pytest.skip(f"could not reach PGVECTOR_TEST_URL: {exc}")

    try:
        # Not `infrastructure.database._enable_pgvector_extension()`: that reads
        # the module-global `engine`, which `conftest.py` has already rebound to
        # the throwaway SQLite, so it would run `CREATE EXTENSION` against SQLite.
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        SQLModel.metadata.create_all(engine)
        run_migrations(engine)
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "select indexname, tablename, indexdef from pg_indexes "
                    "where schemaname = 'public'"
                )
            ).all()
        return {
            name: (table.lower(), _normalise_key(_indexdef_columns(indexdef)))
            for name, table, indexdef in rows
        }
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"could not migrate PGVECTOR_TEST_URL: {exc}")
    finally:
        engine.dispose()


def _indexdef_columns(indexdef: str) -> str:
    """The key list out of a `pg_indexes.indexdef` row.

    `indexdef` is a complete `CREATE INDEX ...` statement, so the same balanced
    scan used on the migration source applies to it.
    """
    on = _CREATE_INDEX_ON.search(indexdef)
    if on is None:
        return ""
    return _balanced_key_list(indexdef, on.end()) or ""


def test_every_declared_index_exists(live_indexes) -> None:
    """A `CREATE INDEX` in the migrations must be a real index on a real table.

    Skipped without `PGVECTOR_TEST_URL`, which is the honest outcome: this is a
    statement about a Postgres deployment, and asserting it against SQLite would
    assert nothing. Against the live stack:

    PGVECTOR_TEST_URL=postgresql://comfy:comfy@localhost:5432/comfy \\
      .venv/bin/python -m pytest tests/test_migration_indexes_exist.py

    Note that an earlier revision of this docstring claimed `scripts/preflight.sh`
    ran the same check "because the thing being asserted is deployment state
    rather than code state". It does not — `grep -n index scripts/preflight.sh`
    returns nothing — so nothing anywhere checked the *deployed* index state and
    the sentence described a check that did not exist. This test now migrates the
    database it reads, which is the stronger of the two claims: it proves the
    runner produces the indexes, not that some prepared database has them.

    **Matching is by coverage, not by name.** A column declared `index=True` on a
    SQLModel model is emitted by `create_all` under SQLAlchemy's default name —
    `ix_voice_models_character_id` — while the migration that also declares it
    calls it `idx_voice_models_character`. Comparing names made this test report
    three present indexes as missing on a freshly migrated database, which is both
    a false positive and the kind of noise that gets a guard deleted. Worse, the
    name comparison could not see the one index that genuinely *was* absent: the
    HNSW vector index on `character_memories(embedding)`, which `create_all`
    cannot emit at all because it is a pgvector operator-class index rather than a
    plain btree. Semantic memory search had no index on any fresh install.
    """
    if live_indexes is None:
        pytest.skip("set PGVECTOR_TEST_URL to assert against a real Postgres")

    declared = declared_indexes()
    missing: list[str] = []
    for name, coverage in declared.items():
        if coverage is None:
            if name not in live_indexes:
                missing.append(name)
            continue
        table, key = coverage
        satisfied = name in live_indexes or any(
            live_table == table and live_key == key
            for live_table, live_key in live_indexes.values()
        )
        if not satisfied:
            where = f" ({table}({key}))" if key else ""
            missing.append(f"{name}{where}")

    assert not missing, (
        "these indexes are declared in steps.py and their migrations are recorded "
        "as applied, but no index on the live Postgres covers them. Either a "
        "migration returned True on a dialect it did not run on, a later step "
        "dropped one, or the table is created by `create_all` before the migration "
        "that would have added the index can run.\n  "
        + "\n  ".join(missing)
    )