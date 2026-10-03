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
RETIRED: dict[str, str] = {}


def declared_indexes() -> set[str]:
    """Every index name the migration source declares.

    Names that are really f-string templates are skipped — the captured group
    stops before `{`, so the check looks at the source character after the match.
    Capturing `idx_job_` from `CREATE INDEX IF NOT EXISTS idx_job_{col_name}` as
    if it were literal produces a failure that means nothing, and a guard that
    cries wolf is a guard that gets deleted.
    """
    names = set()
    for match in _CREATE_INDEX.finditer(SOURCE):
        # `IF` and `NOT` are matched as names when the name that follows
        # `IF NOT EXISTS` is a template (`... IF NOT EXISTS {name}`), because the
        # optional group cannot match and the fallback does. Reserved words, not
        # index names.
        if match.group(1).upper() in {"IF", "NOT", "EXISTS"}:
            continue
        if SOURCE[match.end():match.end() + 1] == "{":
            continue
        names.add(match.group(1))
    return names - set(RETIRED)


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


@pytest.fixture(scope="module")
def live_indexes() -> set[str] | None:
    """Index names in the Postgres named by `PGVECTOR_TEST_URL`, or None.

    Deliberately *not* the app's engine: `tests/conftest.py` forces every session
    onto a throwaway SQLite, and SQLite is exactly the dialect where these
    migrations return early and do nothing, so a test reading the app engine could
    only ever see the dialect that hides the bug.
    """
    url = os.environ.get("PGVECTOR_TEST_URL")
    if not url:
        return None
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            if conn.dialect.name != "postgresql":
                return None
            return {
                name
                for (name,) in conn.execute(
                    text("select indexname from pg_indexes where schemaname = 'public'")
                ).all()
            }
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"could not reach PGVECTOR_TEST_URL: {exc}")
    finally:
        engine.dispose()


def test_every_declared_index_exists(live_indexes) -> None:
    """A `CREATE INDEX` in the migrations must be a real index on a real table.

    Skipped without `PGVECTOR_TEST_URL`, which is the honest outcome: this is a
    statement about a Postgres deployment, and asserting it against SQLite would
    assert nothing. Against the live stack:

        PGVECTOR_TEST_URL=postgresql://comfy:comfy@localhost:5432/comfy \\
          .venv/bin/python -m pytest tests/test_migration_indexes_exist.py

    `scripts/preflight.sh` runs the same check, because the thing being asserted
    is deployment state rather than code state.
    """
    if live_indexes is None:
        pytest.skip("set PGVECTOR_TEST_URL to assert against a real Postgres")

    missing = sorted(declared_indexes() - live_indexes)
    assert not missing, (
        "these indexes are declared in steps.py and their migrations are recorded "
        "as applied, but Postgres does not have them. Either a migration returned "
        "True on a dialect it did not run on, or a later step dropped one.\n  "
        + "\n  ".join(missing)
    )