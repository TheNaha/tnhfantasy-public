"""`GET /api/files?sort=name_asc` must be ordered and paged in SQL.

The name branch used to be:

    rows = session.exec(q.order_by(order_col.desc(), Asset.id.desc())).all()
    total = len(rows)
    rows = sorted(rows, key=lambda a: a.filename, reverse=(sort == "name_desc"))
    page = rows[offset : offset + limit]

so the whole `assets` table — every row including the `metadata_` jsonb — was
materialised to answer a request whose response is tens of kilobytes. Measured
on the live deployment before the fix: **5.5–9.8 s wall and the backend
container's RSS going 150 MiB → 555 MiB** for one request, which two concurrent
requests would exhaust on a 2 GiB container.

The date branch on the same function already counted and paged in SQL; this
brings name up to it.
"""
from sqlmodel import Session, select

from core.entities import Asset


def _seed(session: Session, count: int = 12) -> None:
    for i in range(count):
        session.add(
            Asset(
                user_id="default_user",
                filename=f"img_{count - i:03d}.png",
                relative_path=f"output/img_{count - i:03d}.png",
                size=1024,
            )
        )
    session.commit()


def _files(response) -> list[str]:
    return [f["name"] for f in response.json()["files"]]


class TestNameSortPagesInSql:
    def test_ascending_order_is_correct(self, client, session):
        _seed(session)
        response = client.get("/api/files?sort=name_asc&limit=100")
        assert response.status_code == 200, response.text
        assert _files(response) == sorted(_files(response))

    def test_descending_order_is_correct(self, client, session):
        _seed(session)
        response = client.get("/api/files?sort=name_desc&limit=100")
        assert response.status_code == 200, response.text
        names = _files(response)
        assert names == sorted(names, reverse=True)

    def test_total_is_the_full_count_not_the_page(self, client, session):
        _seed(session, 12)
        response = client.get("/api/files?sort=name_asc&limit=5")
        body = response.json()
        assert len(body["files"]) == 5
        assert body["total"] == 12

    def test_offset_walks_the_whole_set_without_repeating(self, client, session):
        _seed(session, 12)
        first = _files(client.get("/api/files?sort=name_asc&limit=5&offset=0"))
        second = _files(client.get("/api/files?sort=name_asc&limit=5&offset=5"))
        third = _files(client.get("/api/files?sort=name_asc&limit=5&offset=10"))

        assert len(first) == len(second) == 5
        assert len(third) == 2, "the last page is short; that is the point of a limit"
        assert not set(first) & set(second)
        assert not set(second) & set(third)
        assert first + second + third == sorted(first + second + third)

    def test_soft_deleted_rows_are_excluded_from_the_total(self, client, session):
        from datetime import datetime, timezone

        _seed(session, 6)
        row = session.exec(select(Asset)).first()
        row.deleted_at = datetime.now(timezone.utc)
        session.commit()

        body = client.get("/api/files?sort=name_asc&limit=100").json()
        assert body["total"] == 5

    def test_the_query_carries_a_limit(self):
        """The structural half of the fix.

        A behavioural test passes just as well against the old code — it returned
        the right twenty rows, slowly. This asserts the statement is bounded, so
        the shape cannot come back.
        """
        from api.routes import files as files_module

        source = open(files_module.__file__).read()
        branch_start = source.index('if sort in ("name_asc", "name_desc"):')
        branch_end = source.index('order = order_col.asc()', branch_start)
        branch = source[branch_start:branch_end]
        # Comments in the branch describe the bug, so they contain the very
        # tokens being asserted absent. Strip them before looking.
        import re

        branch = re.sub(r"#.*", "", branch)

        assert ".limit(limit)" in branch, "the name branch must page in SQL"
        assert ".offset(offset)" in branch
        assert "sorted(" not in branch, "no Python-side sort of the whole table"
        assert "total = len(rows)" not in branch, (
            "the total must come from a count query, not from the length of a "
            "materialised result set"
        )
        # The one `.all()` that remains must be the paged fetch, not the
        # un-bounded statement the old code ended with.
        unbounded = [line for line in branch.splitlines() if ".all()" in line]
        assert not unbounded or all(
            ".limit(limit)" in branch[: branch.index(line)] for line in unbounded
        ), f"an un-paged fetch remains: {unbounded}"