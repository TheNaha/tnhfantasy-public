"""Postgres rejects a boolean column whose default is an integer.

`ALTER TABLE chats ADD COLUMN scene_graph_enabled BOOLEAN NOT NULL DEFAULT 0`
is accepted by SQLite and rejected by PostgreSQL:

    ERROR: column "scene_graph_enabled" is of type boolean but default
           expression is of type integer
    HINT: You will need to rewrite or cast the expression.

SQLite is dynamically typed and coerces the integer to a boolean. The whole
backend suite runs on SQLite, so a migration that is perfectly correct in the
test suite can still take the container down at startup — which is exactly
what migration 108 did: the suite was green and the backend refused to boot.

The rule is simple enough to check statically, so it is checked statically.
`DEFAULT TRUE` / `DEFAULT FALSE` are the only spellings Postgres accepts for a
boolean column, and they are what the rest of this file already uses.

The same check is applied to CREATE TABLE, where the same error appears:
`CREATE TABLE t (flag BOOLEAN NOT NULL DEFAULT 0)` fails identically.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

MIGRATIONS = Path(__file__).resolve().parents[1] / "infrastructure" / "migrations" / "steps.py"

# A boolean column declaration, and the default that follows it.
_BOOLEAN_COLUMN = re.compile(
    r"BOOLEAN\b[^,;)\n]*?DEFAULT\s+(?P<default>[0-9]+)\b",
    re.IGNORECASE | re.DOTALL,
)


def _boolean_columns_with_integer_defaults() -> list[tuple[int, str]]:
    source = MIGRATIONS.read_text()
    hits: list[tuple[int, str]] = []
    for match in _BOOLEAN_COLUMN.finditer(source):
        line = source.count("\n", 0, match.start()) + 1
        hits.append((line, match.group(0).strip().replace("\n", " ")))
    return hits


def test_no_boolean_column_defaults_to_an_integer():
    """Every boolean default must be TRUE or FALSE, never 0 or 1."""
    offenders = _boolean_columns_with_integer_defaults()
    assert not offenders, (
        "PostgreSQL rejects a boolean column whose DEFAULT is an integer "
        "(SQLite accepts it, so the test suite would not catch it):\n"
        + "\n".join(f"  steps.py:{line}: {text}" for line, text in offenders)
    )


def test_the_migration_file_is_readable():
    """A guard that silently matches nothing is not a guard."""
    source = MIGRATIONS.read_text()
    assert "BOOLEAN" in source, "the migrations file no longer declares boolean columns at all"
    # And the check must be capable of matching a violation, or it is inert.
    assert _BOOLEAN_COLUMN.search(
        "some_column BOOLEAN NOT NULL DEFAULT 0"
    ), "the boolean-column pattern no longer matches the shape it is meant to catch"


@pytest.mark.parametrize(
    "sql",
    [
        "ALTER TABLE t ADD COLUMN c BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE t ADD COLUMN c BOOLEAN DEFAULT 1",
        "CREATE TABLE t (c BOOLEAN NOT NULL DEFAULT 0)",
    ],
)
def test_the_pattern_catches_each_way_of_writing_it(sql: str):
    assert _BOOLEAN_COLUMN.search(sql), f"the guard does not catch: {sql}"


def test_the_accepted_spellings_are_not_matched():
    """The house spellings must pass."""
    for sql in (
        "ALTER TABLE t ADD COLUMN c BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE t ADD COLUMN c BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE t ADD COLUMN c BOOLEAN DEFAULT FALSE NOT NULL",
        "CREATE TABLE t (c BOOLEAN NOT NULL DEFAULT TRUE)",
    ):
        assert not _BOOLEAN_COLUMN.search(sql), f"the guard wrongly flags: {sql}"


class TestPostgresEnumComparisons:
    """Comparing an enum column to a bound string is not a valid operation.

    `messages.role` is a Postgres enum (`messagerole`). A bound string is
    typed VARCHAR, so `role = :role` is `messagerole = character varying`,
    which PostgreSQL rejects:

        ERROR: operator does not exist: messagerole = character varying

    It never showed up on an existing deployment because the column was
    VARCHAR when migration 032 was written, and by the time it became an
    enum the step had already been recorded as applied. On a fresh install
    `create_all` makes it the enum and the step runs against it — so a fresh
    PostgreSQL database could not be created at all. The whole suite runs on
    SQLite, which has no enum type, so nothing caught it.

    The parameter has to be cast to the column's own enum type, and the
    comparison has to stay a boolean expression — a bare
    `CAST(:role AS messagerole)` is an enum where a boolean belongs, and
    PostgreSQL rejects that too.
    """

    STEPS = MIGRATIONS

    def test_the_enum_comparison_casts_its_parameter(self):
        source = self.STEPS.read_text()
        body = source[source.index("def _migration_backfill_message_kind") :]
        body = body[: body.index("\ndef ")]
        assert "CAST(:role AS" in body, (
            "the role comparison no longer casts its parameter, so a fresh "
            "PostgreSQL install fails on an enum-vs-VARCHAR comparison"
        )
        # The comparison itself must stay boolean.
        assert "role = CAST(:role AS" in body, (
            "the cast must be applied to the PARAMETER, with the comparison "
            "kept as `role = CAST(...)`"
        )

    def test_the_sqlite_path_is_unchanged(self):
        """SQLite has no enum type, so its branch must not gain a cast."""
        source = self.STEPS.read_text()
        body = source[source.index("def _migration_backfill_message_kind") :]
        body = body[: body.index("\ndef ")]
        sqlite_branch = body[body.index("else:") : body.index("if is_postgres:")]
        # The SQLite branch binds the lowercase values with no cast.
        assert "role IN ('assistant', 'char')" in body, (
            "the SQLite branch's role=IN form was changed"
        )
        assert "CAST" not in sqlite_branch, (
            "the SQLite branch must not cast — SQLite has no enum type"
        )
