"""An asset key must resolve to the asset it names, and to nothing else.

`_soft_delete_assets` resolves a caller-supplied key to `Asset` rows and marks
every row it matched deleted. Its fallback for a bare basename carried four
arms, and the fourth had no path boundary:

    (Asset.filename == rel)
    | (Asset.relative_path.endswith("/" + rel))
    | (Asset.relative_path == "/" + rel)
    | (Asset.relative_path.endswith(rel))     # <-- unanchored

So a request for `abc.png` matched every asset whose path merely *ended with*
`abc.png` — `notabc.png` and `xabc.png` included.

The first query cannot rescue this. `Asset.relative_path` is always the
date-partitioned form written by `infrastructure/image_processor.py`, so a bare
basename never satisfies `relative_path == rel` or `== "/" + rel`; **every**
basename-keyed call lands in the fallback and therefore in the over-broad arm.

Two reachable callers, neither of which requires a mistake from the user:

- `GET /api/thumbnail/{size}/{filename}` — the "self-heal a missing index row"
  fall-through. No auth, no user action: a thumbnail miss for one file
  soft-deleted its neighbours out of the gallery.
- the gallery's batch delete, which the UI sends as bare filenames
  (`pages/Dashboard.jsx`, `hooks/useDashboardSelection.js`).

A soft delete is recoverable by hand and invisible until someone notices an
image missing from the gallery, which is the worst shape a defect of this class
can take.

The property asserted here is the one that retires the class: **a basename key
matches only on a path-segment boundary.** It is stated over the real ORM
rather than over the SQL string, so rewriting the query cannot quietly widen it
again, and it is generated over the whole asset table rather than three
hand-picked rows.
"""

import pytest
from sqlmodel import Session

from api.routes import files as files_module
from core.entities import Asset

# Names chosen so that one is a suffix of the others and one is a superstring.
# `abc.png` is the requested key; the rest must survive.
TARGET = "abc.png"
NEIGHBOURS = ["notabc.png", "xabc.png", "abc.png.bak", "zabc.png"]
# Filenames, not relative paths — that is what the assertion helper returns.
UNRELATED = ["totally-different.png", "deep.png"]


def _index(session: Session, rows: list[tuple[str, str]]) -> list[Asset]:
    """Create one asset per `(relative_path, filename)` pair, all live."""
    created = []
    for relative_path, filename in rows:
        asset = Asset(
            id=f"id-{relative_path}",
            user_id="tester",
            filename=filename,
            relative_path=relative_path,
        )
        session.add(asset)
        created.append(asset)
    session.commit()
    return created


@pytest.fixture(name="library")
def library_fixture(session):
    """A date-partitioned library: the shape the writer actually produces."""
    paths = [
        ("2026/01/01/abc.png", "abc.png"),
        ("2026/01/01/notabc.png", "notabc.png"),
        ("2026/01/02/xabc.png", "xabc.png"),
        ("2026/01/02/abc.png.bak", "abc.png.bak"),
        ("2026/01/03/zabc.png", "zabc.png"),
        ("2026/01/03/totally-different.png", "totally-different.png"),
        ("2026/01/04/sub/dir/deep.png", "deep.png"),
    ]
    _index(session, paths)
    return session


def _deleted_names(session: Session) -> set[str]:
    session.expire_all()
    live = session.query(Asset).filter(Asset.deleted_at.is_(None)).all()
    return {a.filename for a in live}


class TestBasenameKeyMatchesOnASegmentBoundary:
    def test_a_bare_basename_deletes_exactly_one_asset(self, library):
        removed = files_module._soft_delete_assets(TARGET, session=library)

        assert removed == 1, (
            "a basename key matched "
            f"{removed} assets; it must match only the asset it names"
        )
        assert _deleted_names(library) == set(NEIGHBOURS) | set(UNRELATED)

    @pytest.mark.parametrize("neighbour", NEIGHBOURS)
    def test_no_string_suffix_of_the_key_is_collateral(self, library, neighbour):
        """Each of these *contains* the key as a substring and must be spared."""
        files_module._soft_delete_assets(TARGET, session=library)

        assert neighbour in _deleted_names(library), (
            f"{neighbour!r} ends with {TARGET!r} as a raw string but is a "
            "different file; matching on a string suffix deleted it"
        )

    def test_every_other_asset_in_the_table_survives(self, library):
        files_module._soft_delete_assets(TARGET, session=library)

        assert _deleted_names(library) == set(NEIGHBOURS) | set(UNRELATED)

    def test_a_leading_slash_is_tolerated(self, library):
        """The UI sends paths with and without a leading slash; both resolve."""
        removed = files_module._soft_delete_assets("/" + TARGET, session=library)

        assert removed == 1
        assert _deleted_names(library) == set(NEIGHBOURS) | set(UNRELATED)

    def test_a_full_date_partitioned_path_still_resolves(self, library):
        """The boundary rule must not break the exact-path form."""
        removed = files_module._soft_delete_assets("2026/01/01/abc.png", session=library)

        assert removed == 1
        assert _deleted_names(library) == set(NEIGHBOURS) | {"abc.png.bak"} | {
            "totally-different.png",
            "deep.png",
        }

    def test_an_unknown_key_deletes_nothing(self, library):
        removed = files_module._soft_delete_assets("no-such-image.png", session=library)

        assert removed == 0
        assert "abc.png" in _deleted_names(library)

    def test_already_deleted_rows_are_not_counted_again(self, library):
        files_module._soft_delete_assets(TARGET, session=library)
        second = files_module._soft_delete_assets(TARGET, session=library)

        assert second == 0, (
            "the query filters `deleted_at IS NULL`, so a repeated delete of an "
            "already-deleted key must report 0 rather than re-deleting it"
        )