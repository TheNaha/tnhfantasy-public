"""Keyset cursor integrity and date seeking for `GET /api/v2/assets`.

The bug these pin: the listing ordered on
`(coalesce(generated_at, created_at), id)` but its cursor `WHERE` filtered on the
timestamp alone — `order_col < cur_dt`. `ts` is not unique, so every asset that
shared its instant with the last row of a page fell through the boundary and was
silently dropped from the result set. Ties are the normal case, not a corner:
`upsert_asset` writes one row per output image and a multi-image job stamps them
all with the same `generated_at`.

Also pinned: the composite cursor's format, the legacy bare-timestamp cursor's
one-page-duplicate fallback, the date seek (and the 400s that replace a seek that
silently cannot work), and the day histogram.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, select

from core.entities import Asset

NOW = datetime(2026, 3, 2, 12, 0, 0, tzinfo=timezone.utc)


def seed(session: Session, name: str, moment: datetime, **kwargs) -> Asset:
    """Insert through the real write path, as production does."""
    from services.asset_reconciler import upsert_asset

    relative_path = f"default_user/main/2026/03/02/{name}.png"
    upsert_asset(
        session,
        relative_path=relative_path,
        filename=f"{name}.png",
        width=64,
        height=64,
        generated_at=moment,
        metadata={},
    )
    asset = session.exec(
        select(Asset).where(Asset.relative_path == relative_path)
    ).first()
    for key, value in kwargs.items():
        setattr(asset, key, value)
    session.add(asset)
    session.commit()
    return asset


def list_assets(client, **params) -> dict:
    response = client.get("/api/v2/assets", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def walk_all_pages(client, **params):
    """Every page, following `next_cursor`. The whole point is the seam."""
    seen = []
    cursor = None
    for _ in range(50):  # a hard stop: a broken cursor would loop forever
        page = list_assets(client, cursor=cursor, **params)
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            return seen
    pytest.fail("pagination did not terminate")


def served_days(page) -> list[str]:
    """The UTC day of each listed item, in page order.

    Read off `item["date"]`, which `_asset_as_file_data` derives from the very
    same `coalesce(generated_at, created_at)` the ordering uses — and which is
    what the frontend buckets with `getItemTimelineDate`. (`item["created_at"]`
    is the *row's* insertion time, which is a different instant and would make
    this comparison meaningless.)
    """
    return [
        datetime.fromtimestamp(item["date"], tz=timezone.utc).date().isoformat()
        for item in page["items"]
    ]


# ── the dropped-asset bug ───────────────────────────────────────────────────


def test_no_asset_is_lost_across_a_tie_at_the_page_boundary(session: Session, client):
    """The regression this file exists for.

    Three assets share one `generated_at` and the page holds two, so the split
    falls *inside* the tie. `ts < cur_ts` returned nothing for page 2, and the
    third image was never served at all.
    """
    stamp = NOW - timedelta(days=30)
    seeded = [seed(session, name, stamp) for name in ("a", "b", "c")]

    served = walk_all_pages(client, limit=2)

    assert sorted(served) == sorted(a.id for a in seeded)
    assert len(served) == len(set(served)), "an id was served twice"


def test_tie_split_two_and_one_still_serves_every_row(session: Session, client):
    """Same tie, a different page size, to prove it is the pair and not luck."""
    stamp = NOW - timedelta(days=45)
    seeded = [seed(session, name, stamp) for name in ("a", "b", "c", "d", "e")]

    served = walk_all_pages(client, limit=2)

    assert sorted(served) == sorted(a.id for a in seeded)


def test_tie_at_the_oldest_end_of_the_library_is_served(session: Session, client):
    """The oldest rows are the ones a seek lands on, so the tie that matters most
    is the one at the far end of the sort."""
    old = NOW - timedelta(days=400)
    tie = [seed(session, f"old-{n}", old) for n in range(3)]
    recent = [seed(session, f"new-{n}", NOW - timedelta(days=n)) for n in range(4)]

    served = walk_all_pages(client, limit=4)

    assert sorted(served) == sorted(a.id for a in tie + recent)


def test_cursor_is_the_timestamp_and_the_id(session: Session, client):
    seed(session, "a", NOW - timedelta(days=1))
    seed(session, "b", NOW - timedelta(days=1))
    seed(session, "c", NOW - timedelta(days=2))

    page = list_assets(client, limit=1)

    assert "|" in page["next_cursor"]
    timestamp, _, asset_id = page["next_cursor"].rpartition("|")
    assert asset_id == page["items"][0]["id"]
    # The stored column comes back without a zone from SQLite, so compare the
    # wall clock rather than the offset.
    assert datetime.fromisoformat(timestamp).replace(tzinfo=None) == (
        NOW - timedelta(days=1)
    ).replace(tzinfo=None)


def test_a_legacy_bare_timestamp_cursor_duplicates_one_page_then_heals(session: Session, client):
    """An old in-flight infinite scroll is handed a bare timestamp.

    It must not lose assets. It gets a bounded, visible duplicate instead, and
    the cursor in the response is composite again so every page after it is exact.
    """
    stamp = NOW - timedelta(days=60)
    seeded = [seed(session, name, stamp) for name in ("a", "b", "c")]
    # The strict `<` this replaces would have returned zero rows for this.
    legacy = stamp.isoformat()

    first = list_assets(client, limit=2, cursor=legacy)
    assert first["items"], "a legacy cursor returned nothing; assets were lost"
    assert "|" in first["next_cursor"], "the healed cursor must be composite"

    served = [item["id"] for item in first["items"]]
    cursor = first["next_cursor"]
    while cursor:
        page = list_assets(client, limit=2, cursor=cursor)
        served.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]

    assert set(served) == {a.id for a in seeded}
    assert len(served) <= len(seeded) + 2, "the duplicate must be bounded by one page"


def test_descending_and_ascending_walks_cover_the_same_set(session: Session, client):
    for n in range(6):
        seed(session, f"tie-{n}", NOW - timedelta(days=n))
    seed(session, "solo", NOW - timedelta(days=2, hours=3))

    desc = walk_all_pages(client, limit=2, sort="date_desc")
    asc = walk_all_pages(client, limit=2, sort="date_asc")

    assert set(desc) == set(asc)
    assert len(desc) == len(set(desc))
    assert len(asc) == len(set(asc))


def test_random_sort_cursor_is_untouched(session: Session, client):
    """The md5 cursor is already consistent with its own order; the composite
    change must not leak into it."""
    for n in range(5):
        seed(session, f"r-{n}", NOW - timedelta(days=n))

    page = list_assets(client, limit=2, sort="random")

    assert page["has_more"] is True
    assert "|" not in page["next_cursor"]
    assert len(page["next_cursor"]) == 32  # an md5 hex digest


# ── date seek ───────────────────────────────────────────────────────────────

# A fixed reference so every date in these tests is readable as itself.
DAY = datetime(2026, 3, 2, tzinfo=timezone.utc)


def test_seek_to_a_date_lands_on_that_day_without_walking(session: Session, client):
    """The whole point of the seek: the date is unreachable by keyset alone,
    because a keyset only ever walks newest→oldest, and this page returns it."""
    for n in range(5):
        seed(session, f"recent-{n}", datetime(2026, 9, 1, tzinfo=timezone.utc))
    seeded = [
        seed(session, f"target-{n}", datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc))
        for n in range(3)
    ]

    page = list_assets(client, limit=2, on_or_before="2026-03-02")

    assert served_days(page) == ["2026-03-02", "2026-03-02"]
    assert {item["id"] for item in page["items"]} <= {a.id for a in seeded}
    assert page["has_more"] is True
    assert "|" in page["next_cursor"], "the seek must return a usable cursor"


def test_seek_boundary_is_the_end_of_the_day_not_its_midnight(session: Session, client):
    """Anchoring a bare date to midnight would start the page on 2026-03-01's
    tail, which is the opposite of "jump to 2026-03-02"."""
    seeded = [
        seed(session, "early", datetime(2026, 3, 2, 0, 0, 0, tzinfo=timezone.utc)),
        seed(session, "late", datetime(2026, 3, 2, 23, 59, 59, tzinfo=timezone.utc)),
    ]
    seed(session, "yesterday", datetime(2026, 3, 1, 23, 59, 59, tzinfo=timezone.utc))
    seed(session, "tomorrow", datetime(2026, 3, 3, 0, 0, 0, tzinfo=timezone.utc))

    page = list_assets(client, limit=24, on_or_before="2026-03-02")

    # The page *starts* at the target day and then continues into older rows, so
    # the assertion is on the head of the page, not on the whole page.
    assert served_days(page)[0] == "2026-03-02"
    assert "2026-03-03" not in served_days(page)
    assert {item["id"] for item in page["items"][:2]} == {a.id for a in seeded}


def test_seek_accepts_a_full_instant(session: Session, client):
    seed(session, "before", datetime(2026, 3, 2, 8, 0, tzinfo=timezone.utc))
    after = seed(session, "after", datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc))

    page = list_assets(client, limit=24, on_or_before="2026-03-02T10:00:00+00:00")

    assert [item["id"] for item in page["items"]] != [after.id]
    assert served_days(page)[0] == "2026-03-02"


def test_seek_composes_with_a_cursor(session: Session, client):
    seed(session, "a", datetime(2026, 2, 25, tzinfo=timezone.utc))
    seed(session, "b", datetime(2026, 2, 20, tzinfo=timezone.utc))
    seed(session, "c", datetime(2026, 2, 15, tzinfo=timezone.utc))

    first = list_assets(client, limit=1, on_or_before="2026-03-02")
    second = list_assets(client, limit=1, cursor=first["next_cursor"])

    assert first["items"][0]["id"] != second["items"][0]["id"]


def test_since_seeks_forwards_on_an_ascending_sort(session: Session, client):
    """With the gallery's own ascending sort, `since` is the forward seek."""
    seed(session, "too-old", datetime(2026, 1, 5, tzinfo=timezone.utc))
    seeded = [
        seed(session, f"m-{n}", datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc))
        for n in range(3)
    ]

    page = list_assets(client, limit=24, sort="date_asc", since="2026-03-02")

    assert {item["id"] for item in page["items"]} == {a.id for a in seeded}


def test_a_date_below_the_oldest_row_yields_an_empty_page(session: Session, client):
    seed(session, "recent", NOW)

    page = list_assets(client, limit=24, on_or_before="2000-01-01")

    assert page["items"] == []
    assert page["has_more"] is False
    assert page["next_cursor"] is None


def test_on_or_before_with_an_ascending_sort_is_refused(client):
    response = client.get(
        "/api/v2/assets", params={"sort": "date_asc", "on_or_before": "2026-03-02"}
    )

    assert response.status_code == 400
    assert "date_asc" in response.json()["error"]


def test_since_with_a_descending_sort_is_refused(client):
    response = client.get("/api/v2/assets", params={"since": "2026-03-02"})

    assert response.status_code == 400
    assert "on_or_before" in response.json()["error"]


def test_seeking_with_a_random_sort_is_refused(client):
    response = client.get(
        "/api/v2/assets", params={"sort": "random", "on_or_before": "2026-03-02"}
    )

    assert response.status_code == 400


def test_both_bounds_together_are_a_window_and_are_allowed(session: Session, client):
    seed(session, "too-old", datetime(2026, 1, 5, tzinfo=timezone.utc))
    inside = seed(session, "inside", datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc))
    seed(session, "too-new", datetime(2026, 9, 1, tzinfo=timezone.utc))

    page = list_assets(
        client,
        limit=24,
        sort="date_asc",
        since="2026-02-01",
        on_or_before="2026-04-01",
    )

    assert [item["id"] for item in page["items"]] == [inside.id]


def test_seek_respects_every_scope_filter(session: Session, client):
    mine = seed(session, "mine", NOW - timedelta(days=100), character_id="char-1")
    seed(session, "theirs", NOW - timedelta(days=100), character_id="char-2")

    page = list_assets(client, limit=24, character_id="char-1", on_or_before="2026-03-02")

    assert [item["id"] for item in page["items"]] == [mine.id]


# ── the day histogram ───────────────────────────────────────────────────────


def test_histogram_buckets_by_the_gallery_timestamp_not_the_job_clock(session: Session, client):
    """`/api/statistics` prefers `metadata.job.completed_at`. The gallery does
    not, so the histogram must not either or the rail points at the wrong days."""
    from services.asset_reconciler import upsert_asset

    upsert_asset(
        session,
        relative_path="default_user/main/2026/03/02/job.png",
        filename="job.png",
        width=64,
        height=64,
        generated_at=datetime(2026, 3, 2, 6, 0, tzinfo=timezone.utc),
        metadata={"job": {"completed_at": "2026-03-09T00:00:00.000Z"}},
    )
    session.commit()

    body = client.get("/api/v2/assets/dates").json()

    assert body["days"] == [{"day": "2026-03-02", "count": 1}]
    assert body["day_rule"] == "utc"


def test_histogram_counts_a_row_with_no_metadata_at_all(session: Session, client):
    """`/api/statistics` skips rows with no `metadata_`; the gallery shows them,
    so the rail must have a tick for them or it disagrees with the list."""
    from services.asset_reconciler import upsert_asset

    upsert_asset(
        session,
        relative_path="default_user/main/2026/03/02/bare.png",
        filename="bare.png",
        width=64,
        height=64,
        generated_at=datetime(2026, 3, 2, 6, 0, tzinfo=timezone.utc),
        metadata={},
    )
    session.commit()

    assert client.get("/api/v2/assets/dates").json()["total"] == 1


def test_histogram_and_the_listing_agree_on_every_day(session: Session, client):
    """The contract that makes a tick trustworthy: walk the whole listing, bucket
    it with the same UTC rule, and demand the same map."""
    for day in range(1, 15):
        for n in range(day % 4):
            seed(session, f"d{day}-{n}", datetime(2026, 2, day, 8, 0, tzinfo=timezone.utc))

    cursor = None
    served: list[str] = []
    listed: dict[str, int] = {}
    while True:
        page = list_assets(client, limit=3, cursor=cursor)
        served.extend(item["id"] for item in page["items"])
        for day in served_days(page):
            listed[day] = listed.get(day, 0) + 1
        cursor = page["next_cursor"]
        if not cursor:
            break

    body = client.get("/api/v2/assets/dates").json()

    assert {d["day"]: d["count"] for d in body["days"]} == listed
    assert body["total"] == sum(listed.values()) == len(served)
    assert len(served) == len(set(served))


def test_histogram_is_scoped_like_the_gallery(session: Session, client):
    seed(session, "mine", NOW, workspace="main", character_id="char-1")
    seed(session, "theirs", NOW, workspace="main", character_id="char-2")
    seed(session, "other-ws", NOW, workspace="alt")

    body = client.get(
        "/api/v2/assets/dates", params={"workspace": "main", "character_id": "char-1"}
    ).json()

    assert body["total"] == 1


def test_histogram_excludes_soft_deleted_rows(session: Session, client):
    asset = seed(session, "gone", NOW)
    session.exec(
        Asset.__table__.update().where(Asset.id == asset.id).values(deleted_at=NOW)
    )
    session.commit()

    assert client.get("/api/v2/assets/dates").json()["total"] == 0


def test_histogram_reports_its_span_and_sorts_ascending(session: Session, client):
    for day in (5, 1, 3):
        seed(session, f"s-{day}", datetime(2026, 2, day, 12, 0, tzinfo=timezone.utc))

    body = client.get("/api/v2/assets/dates").json()

    assert [d["day"] for d in body["days"]] == ["2026-02-01", "2026-02-03", "2026-02-05"]
    assert body["first_day"] == "2026-02-01"
    assert body["last_day"] == "2026-02-05"


def test_empty_histogram_is_empty_not_an_error(client):
    assert client.get("/api/v2/assets/dates").json() == {
        "days": [],
        "total": 0,
        "first_day": None,
        "last_day": None,
        "day_rule": "utc",
    }


# ── cursor and bound decoding ───────────────────────────────────────────────


def test_cursor_decoding():
    from api.routes.files import _decode_asset_cursor, _encode_asset_cursor

    assert _decode_asset_cursor(_encode_asset_cursor(NOW, "abc")) == (NOW, "abc")

    bare, asset_id = _decode_asset_cursor(NOW.isoformat())
    assert bare == NOW and asset_id is None

    assert _decode_asset_cursor("") == (None, None)
    assert _decode_asset_cursor(None) == (None, None)
    assert _decode_asset_cursor("not-a-cursor") == (None, None)
    # A `Z` suffix is what every cursor carried when the ISO string was
    # forwarded verbatim.
    assert _decode_asset_cursor("2026-03-02T12:00:00Z") == (NOW, None)


def test_seek_bound_parsing():
    from api.routes.files import _parse_seek_bound

    end = _parse_seek_bound("2026-03-02", end_of_day=True)
    start = _parse_seek_bound("2026-03-02", end_of_day=False)

    assert start == datetime(2026, 3, 2, tzinfo=timezone.utc)
    assert end - start == timedelta(days=1) - timedelta(microseconds=1)
    assert _parse_seek_bound("2026-03-02T10:00:00", end_of_day=True).tzinfo is timezone.utc
    assert _parse_seek_bound("", end_of_day=True) is None
    assert _parse_seek_bound("yesterday", end_of_day=True) is None
    assert _parse_seek_bound("2026-13-02", end_of_day=True) is None
