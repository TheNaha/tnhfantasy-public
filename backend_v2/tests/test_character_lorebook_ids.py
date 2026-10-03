"""`Character.lorebook_ids` — the missing link in the library.

A lorebook could be attached to a `Chat` (`active_lorebook_ids`) and to a
`Story` (`lorebook_ids`), and a SillyTavern card could carry an embedded
`data.character_book` (`embedded_lorebook_id`, written by import only) — but
nothing in the product could attach a library lorebook to a character. These
tests pin the column, its normalisation, and the migration that adds it to a
database created before the entity existed.
"""

import pytest
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from core.entities import Character, Lorebook, LorebookEntry
from core.exceptions import ValidationError
from infrastructure.migrations.steps import _migration_079_character_lorebook_ids


def _seed_lorebook(session, name="Ashfall Codex") -> Lorebook:
    lb = Lorebook(name=name)
    session.add(lb)
    session.commit()
    session.refresh(lb)
    return lb


# ── the relationship itself ──────────────────────────────────────────────────


def test_lorebook_ids_default_to_empty(session):
    char = Character(name="Aria")
    session.add(char)
    session.commit()
    session.refresh(char)

    assert char.lorebook_ids == []


def test_lorebook_ids_round_trip_through_the_database(session):
    lb = _seed_lorebook(session)
    char = Character(name="Aria", lorebook_ids=[lb.id])
    session.add(char)
    session.commit()
    session.refresh(char)

    assert char.lorebook_ids == [lb.id]

    # Re-read through a brand-new session so this asserts what was PERSISTED,
    # not the in-memory object that was just committed.
    with Session(session.get_bind()) as fresh:
        assert fresh.get(Character, char.id).lorebook_ids == [lb.id]


def test_lorebook_ids_can_hold_several_books_in_order(session):
    first = _seed_lorebook(session, "Ashfall Codex")
    second = _seed_lorebook(session, "Riverlands")

    char = Character(name="Aria", lorebook_ids=[first.id, second.id])
    session.add(char)
    session.commit()
    session.refresh(char)

    assert char.lorebook_ids == [first.id, second.id]


def test_lorebook_ids_can_be_cleared(session):
    lb = _seed_lorebook(session)
    char = Character(name="Aria", lorebook_ids=[lb.id])
    session.add(char)
    session.commit()

    char.lorebook_ids = []
    session.add(char)
    session.commit()
    session.refresh(char)

    assert char.lorebook_ids == []


def test_lorebook_ids_are_independent_of_the_embedded_card_lorebook(session):
    """The two columns point at the same table and must not be conflated.

    `embedded_lorebook_id` is a card artifact written by import and round-
    tripped on export; `lorebook_ids` is the vault's own, editable list. A
    character can carry both, either, or neither, and editing one must not
    disturb the other — merging them is precisely the mistake this test exists
    to prevent.
    """
    embedded = _seed_lorebook(session, "Card Book")
    owned = _seed_lorebook(session, "Ashfall Codex")

    char = Character(
        name="Aria", embedded_lorebook_id=embedded.id, lorebook_ids=[owned.id]
    )
    session.add(char)
    session.commit()
    session.refresh(char)

    assert char.embedded_lorebook_id == embedded.id
    assert char.lorebook_ids == [owned.id]

    char.lorebook_ids = []
    session.add(char)
    session.commit()
    session.refresh(char)

    assert char.lorebook_ids == []
    assert char.embedded_lorebook_id == embedded.id


# ── validation ───────────────────────────────────────────────────────────────


def test_lorebook_ids_rejects_a_non_string_entry():
    """A bad entry must not be stored.

    The column is consumed as a bare `LorebookEntry.lorebook_id IN (...)` list,
    so a dict or an int inside it matches nothing: the character's facts
    silently stop loading and the only symptom is that the model has forgotten
    who they are. Rejecting it here is the difference between a 422 and a
    character who has mysteriously forgotten their own backstory.

    Asserted on the CONSTRUCTOR, not through `model_validate`: SQLModel's
    `table=True` `__init__` never calls the pydantic validator, so a test that
    used `model_validate` would pass against a rule the write path does not
    enforce.
    """
    with pytest.raises(ValidationError) as excinfo:
        Character(name="Aria", lorebook_ids=[{"id": "lb-1"}])

    assert excinfo.value.code == "VALIDATION_ERROR"
    assert excinfo.value.field == "lorebook_ids"


def test_lorebook_ids_rejects_a_blank_entry():
    # An empty id is as unqueryable as a dict, and the difference is invisible
    # downstream: it matches no row and is silently dropped by the join.
    with pytest.raises(ValidationError):
        Character(name="Aria", lorebook_ids=["lb-1", "  "])


def test_lorebook_ids_rejects_on_assignment_too():
    """The route write path is `setattr`, not the constructor.

    `update_character`/`patch_character` do
    `setattr(character, key, value)` for every field in the request, so a guard
    that only guarded construction would not have guarded the one that matters.
    """
    char = Character(name="Aria")
    with pytest.raises(ValidationError):
        char.lorebook_ids = [42]


def test_lorebook_ids_validation_agrees_on_both_paths():
    """The pydantic and SQLAlchemy rules must not drift apart."""
    with pytest.raises(ValueError):
        Character.model_validate({"name": "Aria", "lorebook_ids": [{"id": "x"}]})


def test_lorebook_ids_rejects_null():
    """`[]` is "no books"; NULL is a third state nothing downstream handles.

    The field is a non-nullable JSON list, so a NULL would read identically to
    `[]` in the prompt and differently in every `or []` fallback — a value that
    depends on which code path reached it.
    """
    with pytest.raises(ValidationError):
        Character(name="Aria", lorebook_ids=None)


def test_a_rejected_value_leaves_the_row_untouched(session):
    """A refusal must not half-apply."""
    lb = _seed_lorebook(session)
    char = Character(name="Aria", lorebook_ids=[lb.id])
    session.add(char)
    session.commit()

    with pytest.raises(ValidationError):
        char.lorebook_ids = [lb.id, {"nope": True}]
    session.rollback()

    session.refresh(char)
    assert char.lorebook_ids == [lb.id]


# ── migration 079 ────────────────────────────────────────────────────────────


@pytest.fixture(name="legacy_engine")
def legacy_engine_fixture():
    """An engine whose `characters` table predates `lorebook_ids`.

    Built by hand rather than from `SQLModel.metadata`, because `create_all`
    creates the column for you and the migration would then be untested.
    """
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE characters (
                    id VARCHAR NOT NULL PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    embedded_lorebook_id VARCHAR
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO characters (id, name, embedded_lorebook_id) "
                "VALUES ('char-1', 'Aria', 'lb-embedded')"
            )
        )
    return engine


def test_migration_adds_the_column(legacy_engine):
    with legacy_engine.begin() as conn:
        assert _migration_079_character_lorebook_ids(conn) is True

    columns = {c["name"] for c in inspect(legacy_engine).get_columns("characters")}
    assert "lorebook_ids" in columns


def test_migration_preserves_existing_character_rows(legacy_engine):
    """A missing column must not cost the rows that were already there."""
    with legacy_engine.begin() as conn:
        _migration_079_character_lorebook_ids(conn)

    with legacy_engine.connect() as conn:
        row = conn.execute(
            text("SELECT name, embedded_lorebook_id, lorebook_ids FROM characters")
        ).one()

    assert row[0] == "Aria"
    assert row[1] == "lb-embedded"
    # The entity default is `[]`, and a row that read back as NULL would make
    # every consumer's `or []` fallback load instead of the column's own value.
    assert row[2] == "[]"


def test_migration_is_idempotent(legacy_engine):
    """Re-running is a no-op, and it says so.

    The runner does `if applied: _record_migration(...)`, so a step that
    returned False here would never be recorded and would re-execute on every
    startup forever.
    """
    with legacy_engine.begin() as conn:
        assert _migration_079_character_lorebook_ids(conn) is True
        assert _migration_079_character_lorebook_ids(conn) is True

    assert "lorebook_ids" in {
        c["name"] for c in inspect(legacy_engine).get_columns("characters")
    }


def test_migration_is_a_noop_against_the_current_model(legacy_engine):
    """The ORM and the migration must not disagree about the column.

    A fresh install gets `lorebook_ids` from `create_all`; a legacy one gets it
    from 079. If the two shapes ever diverged the failure would only appear on
    one kind of database.
    """
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        assert _migration_079_character_lorebook_ids(conn) is True

    columns = {c["name"] for c in inspect(engine).get_columns("characters")}
    assert "lorebook_ids" in columns


def test_migration_declines_when_there_is_no_characters_table():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        assert _migration_079_character_lorebook_ids(conn) is False


def test_step_is_registered_with_the_next_version():
    from infrastructure.migrations.steps import _get_schema_migration_steps

    versions = [step.version for step in _get_schema_migration_steps()]
    assert "079_character_lorebook_ids" in versions
    # Order matters — the runner applies steps in list order — but "last" is not
    # the property worth pinning. It was `len(versions) - 1` until 080 was added,
    # and the fix was to edit the number rather than to read the failure, which is
    # what makes this assertion worthless: it breaks for every future migration
    # and means nothing for any existing one.
    #
    # What is worth pinning is that no step is registered after this one that
    # depends on its column, and that the numbering is monotonic — both of which
    # hold by construction and neither of which this can check. So: the version
    # is registered, it appears exactly once, and the list has no duplicates.
    assert versions.count("079_character_lorebook_ids") == 1
    assert len(versions) == len(set(versions)), "duplicate migration version"


# ── the entries a character's book actually carries ──────────────────────────


def test_attached_lorebook_entries_are_queryable_by_id(session):
    """Why the column exists: the entries have to be reachable from it.

    Without this the field is write-only — a column that survives every test
    and is read by nothing, which an audit of this schema already found nine of.
    """
    lb = _seed_lorebook(session)
    session.add(
        LorebookEntry(
            lorebook_id=lb.id, keys=[], content="Brine tolls are paid at low tide."
        )
    )
    char = Character(name="Aria", lorebook_ids=[lb.id])
    session.add(char)
    session.commit()
    session.refresh(char)

    entries = session.query(LorebookEntry).filter(
        LorebookEntry.lorebook_id.in_(char.lorebook_ids)
    ).all()

    assert [e.content for e in entries] == [
        "Brine tolls are paid at low tide."
    ]
