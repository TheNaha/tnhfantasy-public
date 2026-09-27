"""Tests for generation sessions: the detector's grouping and its curation
contract, and the CRUD/split/merge routes.

The assertions that matter most here are the negative ones — that the detector
does *not* group across workspaces, does *not* group on seed 0 or NULL, and does
*not* touch a session a human has curated. Everything else in the module is
expendable; those three are what the whole half-computed/half-curated design
rests on, and each of them is a bug that would silently destroy someone's work.

The query-count test is the other load-bearing one: a detector that issues a
query per asset is still correct, and still unusable at 16k.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event as sa_event
from sqlmodel import Session as SQLModelSession
from sqlmodel import select

from core.entities import Asset, SessionAsset
from core.entities import Session as GenerationSession
from services.session_detector import MAX_DETECT_ASSETS, detect_sessions

BASE = datetime(2026, 9, 27, 14, 0, 0)


def _asset(
    index: int,
    *,
    seed: int | None = None,
    checkpoint: str | None = None,
    minutes: float = 0,
    workspace: str = "main",
    user_id: str = "default_user",
    deleted: bool = False,
) -> Asset:
    """One asset with a deterministic id, path and resolved timestamp."""
    stamp = BASE + timedelta(minutes=minutes)
    return Asset(
        id=f"a{index:04d}",
        user_id=user_id,
        filename=f"f{index:04d}.png",
        relative_path=f"{user_id}/{workspace}/f{index:04d}.png",
        workspace=workspace,
        seed=seed,
        checkpoint_name=checkpoint,
        job_completed_at=stamp,
        created_at=stamp,
        deleted_at=stamp if deleted else None,
    )


def _add(session: SQLModelSession, *assets: Asset) -> None:
    session.add_all(assets)
    session.commit()


def _sessions(session: SQLModelSession) -> list[GenerationSession]:
    return list(
        session.exec(select(GenerationSession).order_by(GenerationSession.signature)).all()
    )


def _by_signature(session: SQLModelSession, signature: str) -> GenerationSession | None:
    for row in _sessions(session):
        if row.signature == signature:
            return row
    return None


def _members(session: SQLModelSession, session_id: str) -> set[str]:
    rows = session.exec(
        select(SessionAsset.asset_id).where(SessionAsset.session_id == session_id)
    ).all()
    return set(rows)


def _iso(moment: datetime) -> str:
    """API payloads carry datetimes as ISO strings, not as `datetime` objects."""
    return moment.isoformat()


class TestSignals:
    def test_identical_seed_groups(self, session):
        _add(session, _asset(1, seed=12345), _asset(2, seed=12345), _asset(3, seed=12345))

        summary = detect_sessions(session)

        assert summary["sessions_created"] == 1
        assert summary["signals"]["seed"] == 1
        found = _sessions(session)[0]
        assert found.signature == "seed:12345@2026-09-27T14:00"
        assert found.auto_detected is True
        assert found.locked is False
        assert _members(session, found.id) == {"a0001", "a0002", "a0003"}
        assert found.image_count == 3

    def test_seed_zero_does_not_group(self, session):
        """`seed = 0` is a legal seed AND the "unset" default, so it must never
        form a group on its own — otherwise every default-seeded image in the
        library collapses into one enormous session."""
        _add(session, _asset(1, seed=0), _asset(2, seed=0))

        detect_sessions(session)

        assert all(row.signature is None or not row.signature.startswith("seed:0")
                   for row in _sessions(session))

    def test_null_seed_does_not_group(self, session):
        _add(session, _asset(1, seed=None), _asset(2, seed=None))

        detect_sessions(session)

        assert all(not (row.signature or "").startswith("seed:") for row in _sessions(session))

    def test_seed_zero_and_null_are_kept_out_of_the_seed_signal_but_not_the_corpus(
        self, session
    ):
        """They are excluded from *seed* grouping, not ignored: the time signal
        still legitimately collects them into a working stretch."""
        _add(session, _asset(1, seed=0), _asset(2, seed=None))

        summary = detect_sessions(session)

        assert summary["signals"]["seed"] == 0
        assert summary["signals"]["time"] == 1
        assert summary["assets_considered"] == 2
        assert summary["assets_grouped"] == 2

    def test_identical_checkpoint_within_window_groups(self, session):
        _add(
            session,
            _asset(1, checkpoint="sd_xl_base", minutes=0),
            _asset(2, checkpoint="sd_xl_base", minutes=5),
        )

        summary = detect_sessions(session)

        assert summary["signals"]["ckpt"] == 1
        found = _sessions(session)[0]
        assert found.signature == "ckpt:sd_xl_base@2026-09-27T14:00"
        assert _members(session, found.id) == {"a0001", "a0002"}

    def test_time_gap_larger_than_window_splits_a_checkpoint_group(self, session):
        """Two pairs of the same checkpoint an hour apart are two sessions, not
        one — and they get different signatures, which is what keeps the
        idempotency lookup from fusing them again on the next run."""
        _add(
            session,
            _asset(1, checkpoint="flux_dev", minutes=0),
            _asset(2, checkpoint="flux_dev", minutes=4),
            _asset(3, checkpoint="flux_dev", minutes=60),
            _asset(4, checkpoint="flux_dev", minutes=64),
        )

        detect_sessions(session)

        rows = _sessions(session)
        assert len(rows) == 2
        assert {row.signature for row in rows} == {
            "ckpt:flux_dev@2026-09-27T14:00",
            "ckpt:flux_dev@2026-09-27T15:00",
        }
        assert all(row.image_count == 2 for row in rows)

    def test_two_runs_of_one_checkpoint_in_the_same_hour_stay_separate(self, session):
        """A bucket coarser than the gap fuses two working stretches.

        This is a regression, not a hypothetical: with an hour-resolution bucket,
        a 4k-asset corpus produced 89 colliding signatures out of 576 groups, and
        each collision merged two unrelated stretches into one session whose
        start belonged to neither. The bucket must be finer than the window.
        """
        _add(
            session,
            _asset(1, checkpoint="flux_dev", minutes=0),
            _asset(2, checkpoint="flux_dev", minutes=3),
            _asset(3, checkpoint="flux_dev", minutes=30),
            _asset(4, checkpoint="flux_dev", minutes=33),
            _asset(5, checkpoint="flux_dev", minutes=60),
            _asset(6, checkpoint="flux_dev", minutes=63),
        )

        detect_sessions(session)

        rows = _sessions(session)
        assert len(rows) == 3, [row.signature for row in rows]
        assert len({row.signature for row in rows}) == 3
        assert all(row.image_count == 2 for row in rows)
        # No asset is double-counted, and every session's bounds describe the
        # two images that are actually in it.
        expected = {
            "a0001": 0, "a0002": 3,
            "a0003": 30, "a0004": 33,
            "a0005": 60, "a0006": 63,
        }
        seen: set[str] = set()
        for row in rows:
            own = _members(session, row.id)
            assert len(own) == 2
            assert not (seen & own), "an asset landed in two sessions"
            seen |= own
            minutes = sorted(expected[asset_id] for asset_id in own)
            assert row.start_at == BASE + timedelta(minutes=minutes[0])
            assert row.end_at == BASE + timedelta(minutes=minutes[1])
            cover = min(own, key=lambda asset_id: expected[asset_id])
            assert row.thumbnail == f"default_user/main/f{cover[1:]}.png"
        assert seen == set(expected)

    def test_time_proximity_is_the_fallback(self, session):
        _add(
            session,
            _asset(1, seed=11, minutes=0),
            _asset(2, seed=22, minutes=2),
            _asset(3, seed=33, minutes=4),
        )

        summary = detect_sessions(session)

        assert summary["signals"] == {"seed": 0, "ckpt": 0, "time": 1}
        found = _sessions(session)[0]
        assert found.signature == "time:main@2026-09-27T14:00"
        assert _members(session, found.id) == {"a0001", "a0002", "a0003"}

    def test_never_groups_across_workspaces(self, session):
        """The corpus partitions by workspace; a chat image and a story image
        that share a seed are unrelated facts."""
        _add(
            session,
            _asset(1, seed=777, workspace="chat", minutes=0),
            _asset(2, seed=777, workspace="story", minutes=1),
            _asset(3, seed=777, workspace="main", minutes=2),
            _asset(4, seed=777, workspace="main", minutes=3),
        )

        detect_sessions(session)

        rows = _sessions(session)
        assert len(rows) == 1
        assert rows[0].workspace == "main"
        assert _members(session, rows[0].id) == {"a0003", "a0004"}

    def test_never_groups_across_users(self, session):
        _add(
            session,
            _asset(1, seed=5, user_id="default_user"),
            _asset(2, seed=5, user_id="other_user"),
        )

        detect_sessions(session)

        assert _sessions(session) == []

    def test_deleted_assets_are_skipped(self, session):
        _add(
            session,
            _asset(1, seed=31),
            _asset(2, seed=31),
            _asset(3, seed=31, deleted=True),
        )

        summary = detect_sessions(session)

        assert summary["assets_considered"] == 2
        found = _sessions(session)[0]
        assert _members(session, found.id) == {"a0001", "a0002"}

    def test_min_size_is_honoured(self, session):
        # The non-matching seeds are spaced beyond the window so the
        # time-proximity fallback cannot rescue what the seed signal refuses;
        # the assertion is about `min_size`, not about the other two signals.
        _add(
            session,
            _asset(1, seed=4, minutes=0),
            _asset(2, seed=5, minutes=30),
            _asset(3, seed=6, minutes=60),
        )

        detect_sessions(session)
        assert _sessions(session) == []

        _add(session, _asset(4, seed=4, minutes=5))
        summary = detect_sessions(session)

        assert summary["sessions_created"] == 1
        assert summary["signals"]["seed"] == 1
        assert _members(session, _sessions(session)[0].id) == {"a0001", "a0004"}

    def test_min_size_above_two_demotes_a_pair(self, session):
        _add(session, _asset(1, seed=9), _asset(2, seed=9), _asset(3, seed=9))

        assert detect_sessions(session, min_size=3)["sessions_created"] == 1
        assert detect_sessions(session, min_size=4)["sessions_created"] == 0

    def test_resolved_timestamp_precedence(self, session):
        """`coalesce(job_completed_at, generated_at, created_at)` — the same
        precedence the statistics service uses, so a session's day bounds match
        every other time bucket in the app."""
        only_created = Asset(
            id="b0001",
            user_id="default_user",
            filename="b1.png",
            relative_path="default_user/main/b1.png",
            seed=61,
            created_at=BASE,
        )
        only_generated = Asset(
            id="b0002",
            user_id="default_user",
            filename="b2.png",
            relative_path="default_user/main/b2.png",
            seed=61,
            generated_at=BASE + timedelta(minutes=3),
            created_at=BASE,
        )
        completed = Asset(
            id="b0003",
            user_id="default_user",
            filename="b3.png",
            relative_path="default_user/main/b3.png",
            seed=61,
            job_completed_at=BASE + timedelta(minutes=9),
            generated_at=BASE + timedelta(minutes=1),
            created_at=BASE,
        )
        _add(session, only_created, only_generated, completed)

        detect_sessions(session)

        found = _sessions(session)[0]
        assert found.start_at == BASE
        assert found.end_at == BASE + timedelta(minutes=9)

    def test_bounds_count_and_cover_are_maintained(self, session):
        _add(
            session,
            _asset(1, seed=77, minutes=10),
            _asset(2, seed=77, minutes=20),
            _asset(3, seed=77, minutes=30),
        )

        detect_sessions(session)

        found = _sessions(session)[0]
        assert found.start_at == BASE + timedelta(minutes=10)
        assert found.end_at == BASE + timedelta(minutes=30)
        assert found.image_count == 3
        # The cover is the earliest member, which does not move when the tail of
        # a session grows.
        assert found.thumbnail == "default_user/main/f0001.png"

    def test_refuses_a_library_past_the_guard(self, session):
        _add(session, _asset(1, seed=1), _asset(2, seed=1))

        from core.exceptions import ValidationError

        with pytest.raises(ValidationError) as excinfo:
            detect_sessions(session, max_assets=1)
        assert "Session detection is limited to" in str(excinfo.value)

    def test_rejects_nonsense_parameters(self, session):
        from core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            detect_sessions(session, min_size=0)
        with pytest.raises(ValidationError):
            detect_sessions(session, time_gap_minutes=0)


class TestIdempotency:
    def test_rerun_is_idempotent(self, session):
        _add(
            session,
            _asset(1, seed=101),
            _asset(2, seed=101),
            _asset(3, seed=102),
            _asset(4, seed=102),
        )

        first = detect_sessions(session)
        second = detect_sessions(session)
        third = detect_sessions(session)

        assert first["sessions_created"] == 2
        # A true no-op: nothing about the sessions changed, so nothing was
        # written — not even an UPDATE, so `updated_at` did not move either.
        for rerun in (second, third):
            assert rerun["sessions_created"] == 0
            assert rerun["sessions_extended"] == 0
            assert rerun["sessions_modified"] == 0
        assert len(_sessions(session)) == 2
        assert all(row.image_count == 2 for row in _sessions(session))

    def test_rerun_does_not_duplicate_membership(self, session):
        _add(session, _asset(1, seed=55), _asset(2, seed=55), _asset(3, seed=55))

        detect_sessions(session)
        for _ in range(3):
            detect_sessions(session)

        found = _sessions(session)[0]
        assert _members(session, found.id) == {"a0001", "a0002", "a0003"}
        assert len(_members(session, found.id)) == found.image_count

    def test_a_new_asset_extends_rather_than_duplicates(self, session):
        _add(session, _asset(1, seed=808), _asset(2, seed=808))
        detect_sessions(session)

        _add(session, _asset(3, seed=808, minutes=5))
        summary = detect_sessions(session)

        assert summary["sessions_created"] == 0
        assert summary["sessions_extended"] == 1
        assert summary["sessions_modified"] == 1
        assert len(_sessions(session)) == 1
        found = _sessions(session)[0]
        assert found.image_count == 3
        assert _members(session, found.id) == {"a0001", "a0002", "a0003"}

    def test_a_shrinking_group_drops_its_orphaned_members(self, session):
        _add(session, _asset(1, seed=909), _asset(2, seed=909), _asset(3, seed=909))
        detect_sessions(session)
        found = _sessions(session)[0]

        _add(session, _asset(4, seed=909, minutes=1))
        session.get(Asset, "a0003").deleted_at = BASE
        session.commit()

        detect_sessions(session)

        assert len(_sessions(session)) == 1
        assert _members(session, found.id) == {"a0001", "a0002", "a0004"}
        assert _sessions(session)[0].image_count == 3

    def test_dry_run_writes_nothing(self, session):
        _add(session, _asset(1, seed=4004), _asset(2, seed=4004))

        summary = detect_sessions(session, dry_run=True)

        assert summary["dry_run"] is True
        assert summary["sessions_created"] == 0
        assert summary["pending_create"] == 1
        assert summary["groups_detected"] == 1
        assert _sessions(session) == []

        # And the dry run was not merely reporting a guess: the real run does the
        # same thing afterwards.
        assert detect_sessions(session)["sessions_created"] == 1

    def test_dry_run_on_an_existing_session_extends_nothing(self, session):
        _add(session, _asset(1, seed=4100), _asset(2, seed=4100))
        detect_sessions(session)
        _add(session, _asset(3, seed=4100, minutes=2))

        summary = detect_sessions(session, dry_run=True)

        assert summary["pending_extend"] == 1
        assert summary["sessions_extended"] == 0
        assert _sessions(session)[0].image_count == 2


class TestLocking:
    def test_locked_session_is_never_touched(self, session):
        _add(session, _asset(1, seed=2020), _asset(2, seed=2020))
        detect_sessions(session)
        found = _sessions(session)[0]
        found.locked = True
        found.name = "My curated session"
        found.image_count = 99
        session.add(found)
        session.commit()

        summary = detect_sessions(session)

        assert summary["sessions_skipped_locked"] == 1
        assert summary["sessions_created"] == 0
        assert summary["sessions_extended"] == 0
        assert len(_sessions(session)) == 1
        after = _sessions(session)[0]
        assert after.name == "My curated session"
        assert after.image_count == 99
        assert after.locked is True

    def test_adding_an_asset_to_a_locked_session_never_rebuilds_it(self, session):
        """The stale-member case: the detector must not drop the asset the user
        put back, nor resurrect the two it was going to group."""
        _add(session, _asset(1, seed=3030), _asset(2, seed=3030))
        detect_sessions(session)
        found = _sessions(session)[0]
        found.locked = True
        session.add(found)
        session.commit()
        _add(session, _asset(3, seed=3030, minutes=2))

        summary = detect_sessions(session)

        assert summary["sessions_skipped_locked"] == 1
        assert _members(session, found.id) == {"a0001", "a0002"}
        assert _sessions(session)[0].image_count == 2

    def test_a_rename_locks_and_a_later_detect_leaves_it_alone(self, session, client):
        _add(session, _asset(1, seed=6060), _asset(2, seed=6060))
        detect_sessions(session)
        session_id = _sessions(session)[0].id
        assert _sessions(session)[0].locked is False

        patched = client.patch(
            f"/api/v2/sessions/{session_id}", json={"name": "Autumn portraits"}
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["locked"] is True

        _add(session, _asset(3, seed=6060, minutes=3))
        summary = detect_sessions(session)

        assert summary["sessions_skipped_locked"] == 1
        assert summary["sessions_created"] == 0
        assert _members(session, session_id) == {"a0001", "a0002"}
        assert _sessions(session)[0].name == "Autumn portraits"

    def test_claims_are_not_reused_by_a_weaker_signal(self, session):
        """Accepting a seed session must not leave its images to be rebuilt as a
        second, time-proximity session alongside it."""
        _add(
            session,
            _asset(1, seed=700, minutes=0),
            _asset(2, seed=700, minutes=1),
            _asset(3, seed=701, minutes=2),
            _asset(4, seed=702, minutes=3),
        )
        detect_sessions(session)
        seed_session = _by_signature(session, "seed:700@2026-09-27T14:00")
        seed_session.locked = True
        session.add(seed_session)
        session.commit()

        summary = detect_sessions(session)

        assert summary["sessions_skipped_locked"] == 1
        # a3/a4 form the time session; a1/a2 are NOT re-filed into it.
        time_session = _by_signature(session, "time:main@2026-09-27T14:02")
        assert time_session is not None
        assert _members(session, time_session.id) == {"a0003", "a0004"}
        assert time_session.image_count == 2


class TestScale:
    """The detector must not be O(n) in queries.

    This is asserted as a *difference* between a small and a large corpus rather
    than as a raw count, because a raw bound can be met by an implementation
    that is merely cheap today. A fixed-but-still-per-row query grows with the
    corpus and cannot pass a comparison.
    """

    @staticmethod
    def _seed_corpus(session: SQLModelSession, count: int, offset: int = 0) -> None:
        batch = [
            _asset(
                offset + index,
                # Six images per seed, so ~count/6 seed groups plus a
                # time-proximity remainder: a realistic mix rather than one
                # degenerate group.
                seed=1000 + (index // 6) if index % 7 else None,
                minutes=index * 3,
            )
            for index in range(count)
        ]
        session.add_all(batch)
        session.commit()

    @staticmethod
    def _record_selects(session: SQLModelSession, engine) -> list[str]:
        statements: list[str] = []

        @sa_event.listens_for(engine, "before_cursor_execute")
        def _record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        try:
            detect_sessions(session)
        finally:
            sa_event.remove(engine, "before_cursor_execute", _record)
        return statements

    def test_query_count_does_not_scale_with_asset_count(self, session, engine):
        self._seed_corpus(session, 150)
        few = [s for s in self._record_selects(session, engine) if s.lstrip().upper().startswith("SELECT")]

        self._seed_corpus(session, 300, offset=1000)
        many = [s for s in self._record_selects(session, engine) if s.lstrip().upper().startswith("SELECT")]

        assert len(few) == len(many), (
            f"detector issues per-asset queries: {len(few)} at 150 assets vs "
            f"{len(many)} at 450"
        )
        # And the constant is small: the count guard, the asset pass, the
        # session lookup, the membership lookup. Nothing per group, per asset.
        assert len(few) <= 5, f"expected a fixed handful of queries, got {len(few)}"
        assert len(few) > 0

    def test_no_query_per_asset_or_per_group(self, session, engine):
        self._seed_corpus(session, 240)
        statements = self._record_selects(session, engine)

        per_asset = [
            s
            for s in statements
            if s.lstrip().upper().startswith("SELECT")
            and "FROM assets" in s
            and "WHERE" in s
            and "assets.id IN" in s
        ]
        assert per_asset == [], f"per-asset lookup detected: {per_asset}"

        per_session = [
            s
            for s in statements
            if s.lstrip().upper().startswith("SELECT")
            and "FROM sessions" in s
            and "signature IN" in s
        ]
        assert per_session == [], f"per-signature lookup detected: {per_session}"

    def test_a_few_hundred_assets_detect_correctly_and_quickly(self, session):
        self._seed_corpus(session, 300, offset=5000)

        started = time.perf_counter()
        summary = detect_sessions(session)
        elapsed = time.perf_counter() - started

        assert summary["assets_considered"] == 300
        assert summary["groups_detected"] > 0
        assert summary["sessions_created"] == summary["groups_detected"]
        assert summary["elapsed_seconds"] == pytest.approx(elapsed, abs=5)

        rows = _sessions(session)
        assert len(rows) == summary["groups_detected"]
        # Membership and the denormalised count must agree on every row, and no
        # asset may sit in two sessions.
        paths = {
            asset.id: asset.relative_path
            for asset in session.exec(select(Asset)).all()
        }
        seen: set[str] = set()
        for row in rows:
            members = _members(session, row.id)
            assert len(members) == row.image_count
            assert row.image_count >= 2
            assert not (seen & members), "an asset landed in two sessions"
            seen |= members
            assert row.start_at is not None and row.end_at is not None
            assert row.start_at <= row.end_at
            assert row.thumbnail in {paths[asset_id] for asset_id in members}
        assert seen == {f"a{5000 + i:04d}" for i in range(300)}


# ── API ─────────────────────────────────────────────────────────────────────


def _api_asset(session, index: int, **kwargs) -> str:
    asset = _asset(index, **kwargs)
    session.add(asset)
    session.commit()
    return asset.id


class TestSessionRoutes:
    def test_list_is_empty_by_default(self, client):
        resp = client.get("/api/v2/sessions")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["sessions"] == []
        assert body["total"] == 0

    def test_create_manual_session_is_curated_by_construction(self, client, session):
        first = _api_asset(session, 1, seed=1)
        second = _api_asset(session, 2, seed=1, minutes=1)

        resp = client.post(
            "/api/v2/sessions",
            json={"name": "Hand picked", "asset_ids": [first, second]},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["auto_detected"] is False
        assert body["locked"] is True
        assert body["signature"] is None
        assert body["image_count"] == 2
        assert body["start_at"] == _iso(BASE)
        assert body["end_at"] == _iso(BASE + timedelta(minutes=1))
        assert body["thumbnail"] == "default_user/main/f0001.png"
        assert sorted(body["asset_ids"]) == sorted([first, second])

    def test_create_rejects_unknown_asset(self, client, session):
        known = _api_asset(session, 1)

        resp = client.post(
            "/api/v2/sessions", json={"name": "x", "asset_ids": [known, "nope"]}
        )

        assert resp.status_code == 400, resp.text
        assert resp.json()["field"] == "asset_ids"
        assert "nope" in resp.json()["error"]
        assert client.get("/api/v2/sessions").json()["total"] == 0

    def test_create_rejects_deleted_asset(self, client, session):
        deleted = _api_asset(session, 1, deleted=True)

        resp = client.post("/api/v2/sessions", json={"name": "x", "asset_ids": [deleted]})

        assert resp.status_code == 400, resp.text

    def test_create_requires_a_name(self, client):
        assert client.post("/api/v2/sessions", json={"description": "no name"}).status_code == 422
        assert client.post("/api/v2/sessions", json={"name": "  "}).status_code == 422

    def test_patch_sets_locked(self, client, session):
        created = client.post("/api/v2/sessions", json={"name": "Before"}).json()

        resp = client.patch(
            f"/api/v2/sessions/{created['id']}",
            json={"name": "After", "description": "curated"},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "After"
        assert body["description"] == "curated"
        assert body["locked"] is True
        assert body["updated_at"] >= created["updated_at"]

    def test_soft_delete(self, client, session):
        created = client.post("/api/v2/sessions", json={"name": "Doomed"}).json()

        resp = client.delete(f"/api/v2/sessions/{created['id']}")

        assert resp.status_code == 200, resp.text
        assert client.get(f"/api/v2/sessions/{created['id']}").status_code == 404
        assert client.get("/api/v2/sessions").json()["total"] == 0
        row = session.get(GenerationSession, created["id"])
        assert row is not None and row.deleted_at is not None

    def test_missing_session_is_404_everywhere(self, client):
        assert client.get("/api/v2/sessions/nope").status_code == 404
        assert client.patch("/api/v2/sessions/nope", json={"name": "x"}).status_code == 404
        assert client.delete("/api/v2/sessions/nope").status_code == 404
        assert client.post("/api/v2/sessions/nope/assets", json={"asset_ids": []}).status_code == 404
        assert client.delete("/api/v2/sessions/nope/assets/zzz").status_code == 404
        assert client.post("/api/v2/sessions/nope/split", json={"keep_asset_ids": []}).status_code == 404
        assert client.post(
            "/api/v2/sessions/nope/merge", json={"target_session_id": "x"}
        ).status_code == 404
        assert client.get("/api/v2/sessions/nope/assets").status_code == 404

    def test_list_filters_and_search(self, client, session):
        detect_sessions(_seeded_for_filter(session))
        client.post(
            "/api/v2/sessions",
            json={"name": "Winter set", "description": "snow", "workspace": "main"},
        )
        client.post("/api/v2/sessions", json={"name": "Chat picks", "workspace": "chat"})

        assert client.get("/api/v2/sessions", params={"auto_detected": True}).json()["total"] == 1
        assert client.get("/api/v2/sessions", params={"auto_detected": False}).json()["total"] == 2
        assert client.get("/api/v2/sessions", params={"locked": True}).json()["total"] == 2
        assert client.get("/api/v2/sessions", params={"locked": False}).json()["total"] == 1
        assert client.get("/api/v2/sessions", params={"search": "winter"}).json()["total"] == 1
        assert client.get("/api/v2/sessions", params={"search": "snow"}).json()["total"] == 1
        assert client.get("/api/v2/sessions", params={"search": "nothing"}).json()["total"] == 0
        assert client.get("/api/v2/sessions", params={"workspace": "main"}).json()["total"] == 2
        assert client.get("/api/v2/sessions", params={"workspace": "chat"}).json()["total"] == 1

    def test_list_limit_is_capped_and_ordered(self, client, session):
        for index in range(5):
            client.post("/api/v2/sessions", json={"name": f"S{index}"})

        assert client.get("/api/v2/sessions", params={"limit": 500}).status_code == 422
        page = client.get("/api/v2/sessions", params={"limit": 2, "offset": 0}).json()
        assert len(page["sessions"]) == 2
        assert page["total"] == 5
        stamps = [row["updated_at"] for row in client.get("/api/v2/sessions").json()["sessions"]]
        assert stamps == sorted(stamps, reverse=True)


def _seeded_for_filter(session):
    _add(session, _asset(1, seed=12), _asset(2, seed=12))
    return session


class TestMembershipRoutes:
    def test_add_assets_sets_locked_and_maintains_bounds(self, client, session):
        first = _api_asset(session, 1, minutes=0)
        second = _api_asset(session, 2, minutes=5)
        third = _api_asset(session, 3, minutes=9)
        created = client.post("/api/v2/sessions", json={"name": "A"}).json()

        resp = client.post(
            f"/api/v2/sessions/{created['id']}/assets",
            json={"asset_ids": [first, second, third]},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["added"] == 3
        row = resp.json()["session"]
        assert row["locked"] is True
        assert row["image_count"] == 3
        assert row["start_at"] == _iso(BASE)
        assert row["end_at"] == _iso(BASE + timedelta(minutes=9))
        assert row["thumbnail"] == "default_user/main/f0001.png"

    def test_duplicate_member_is_a_clean_4xx(self, client, session):
        first = _api_asset(session, 1)
        _api_asset(session, 2)
        created = client.post(
            "/api/v2/sessions", json={"name": "A", "asset_ids": [first]}
        ).json()

        resp = client.post(
            f"/api/v2/sessions/{created['id']}/assets", json={"asset_ids": [first]}
        )

        assert 400 <= resp.status_code < 500, resp.text
        assert resp.status_code == 400
        assert resp.json()["field"] == "asset_ids"
        assert resp.json()["code"] == "VALIDATION_ERROR"
        # Nothing partial landed.
        assert client.get(f"/api/v2/sessions/{created['id']}").json()["image_count"] == 1

    def test_duplicate_inside_one_request_is_a_clean_4xx(self, client, session):
        first = _api_asset(session, 1)
        created = client.post("/api/v2/sessions", json={"name": "A"}).json()

        resp = client.post(
            f"/api/v2/sessions/{created['id']}/assets",
            json={"asset_ids": [first, first]},
        )

        assert resp.status_code == 400, resp.text
        assert client.get(f"/api/v2/sessions/{created['id']}").json()["image_count"] == 0

    def test_add_unknown_asset_is_400(self, client, session):
        created = client.post("/api/v2/sessions", json={"name": "A"}).json()

        resp = client.post(
            f"/api/v2/sessions/{created['id']}/assets", json={"asset_ids": ["ghost"]}
        )

        assert resp.status_code == 400, resp.text
        assert "ghost" in resp.json()["error"]

    def test_add_empty_list_is_400(self, client, session):
        created = client.post("/api/v2/sessions", json={"name": "A"}).json()

        resp = client.post(f"/api/v2/sessions/{created['id']}/assets", json={"asset_ids": []})

        assert resp.status_code == 400, resp.text

    def test_remove_member_sets_locked_and_maintains_bounds(self, client, session):
        first = _api_asset(session, 1, minutes=0)
        second = _api_asset(session, 2, minutes=5)
        third = _api_asset(session, 3, minutes=9)
        created = client.post(
            "/api/v2/sessions",
            json={"name": "A", "asset_ids": [first, second, third]},
        ).json()
        assert created["image_count"] == 3

        # Removing the earliest must move the cover, not just the count.
        resp = client.delete(f"/api/v2/sessions/{created['id']}/assets/{first}")

        assert resp.status_code == 200, resp.text
        assert resp.json()["removed"] == 1
        after = client.get(f"/api/v2/sessions/{created['id']}").json()
        assert after["image_count"] == 2
        assert after["start_at"] == _iso(BASE + timedelta(minutes=5))
        assert after["end_at"] == _iso(BASE + timedelta(minutes=9))
        assert after["thumbnail"] == "default_user/main/f0002.png"
        assert after["locked"] is True
        assert sorted(after["asset_ids"]) == sorted([second, third])

    def test_remove_non_member_is_404(self, client, session):
        other = _api_asset(session, 1)
        created = client.post("/api/v2/sessions", json={"name": "A"}).json()

        resp = client.delete(f"/api/v2/sessions/{created['id']}/assets/{other}")

        assert resp.status_code == 404, resp.text

    def test_members_endpoint_returns_metadata_without_n_plus_one(
        self, client, session
    ):
        from sqlalchemy import event as sa_event

        ids = []
        for index in range(6):
            asset = _asset(index, seed=1, minutes=index)
            asset.metadata_ = {
                "prompt": f"a portrait of thing {index}",
                "negativePrompt": "blurry",
                "loras": [
                    {
                        "name": "Zeta_Thing.safetensors",
                        "strength": 0.8,
                        "metadata": {
                            "id": 1189691,
                            "name": "Zeta/Thing LoRA",
                            "tags": ["character", "z3t4"],
                        },
                    }
                ],
                "checkpoint": {"name": "sd_xl_base", "display_name": "SDXL Base"},
            }
            ids.append(asset.id)
            session.add(asset)
        session.commit()
        created = client.post(
            "/api/v2/sessions", json={"name": "A", "asset_ids": ids}
        ).json()

        statements: list[str] = []

        @sa_event.listens_for(session.bind, "before_cursor_execute")
        def _record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        try:
            resp = client.get(f"/api/v2/sessions/{created['id']}/assets")
        finally:
            sa_event.remove(session.bind, "before_cursor_execute", _record)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 6
        assert [row["prompt"] for row in body["assets"]] == [
            f"a portrait of thing {index}" for index in range(6)
        ]
        first = body["assets"][0]
        assert first["seed"] == 1
        assert first["negative_prompt"] == "blurry"
        # The display name, because the panel shows a human label rather than a
        # filename.
        assert first["checkpoint"] == "SDXL Base"
        # The nested shape is the ONLY LoRA shape in this library, so a consumer
        # reading `entry["civitai_id"]` gets None for every one of them.
        assert first["loras"][0]["civitai_id"] == 1189691
        assert first["loras"][0]["display_name"] == "Zeta/Thing LoRA"
        assert first["loras"][0]["strength"] == 0.8

        per_asset = [
            s
            for s in statements
            if s.lstrip().upper().startswith("SELECT") and "FROM assets" in s and "assets.id IN" in s
        ]
        assert per_asset == [], f"members endpoint lazy-loads per asset: {per_asset}"

    def test_members_endpoint_paginates(self, client, session):
        ids = [_api_asset(session, index, seed=2, minutes=index) for index in range(5)]
        created = client.post(
            "/api/v2/sessions", json={"name": "A", "asset_ids": ids}
        ).json()

        page = client.get(
            f"/api/v2/sessions/{created['id']}/assets", params={"limit": 2}
        ).json()

        assert page["total"] == 5
        assert len(page["assets"]) == 2
        assert client.get(
            f"/api/v2/sessions/{created['id']}/assets", params={"limit": 999}
        ).status_code == 422


class TestSplit:
    def test_split_moves_exactly_the_complement(self, client, session):
        ids = [
            _api_asset(session, index, seed=3, minutes=index) for index in range(1, 6)
        ]
        created = client.post(
            "/api/v2/sessions", json={"name": "Batch", "asset_ids": ids}
        ).json()

        resp = client.post(
            f"/api/v2/sessions/{created['id']}/split",
            json={"keep_asset_ids": [ids[0], ids[1]]},
        )

        assert resp.status_code == 200, resp.text
        kept = resp.json()["session"]
        moved = resp.json()["created"]

        assert sorted(kept["asset_ids"]) == sorted([ids[0], ids[1]])
        assert sorted(moved["asset_ids"]) == sorted([ids[2], ids[3], ids[4]])
        assert kept["id"] == created["id"]
        assert moved["id"] != created["id"]
        assert moved["name"] == "Batch (split)"
        assert moved["locked"] is True
        assert moved["auto_detected"] is False
        assert moved["signature"] == created["signature"]
        assert kept["locked"] is True

        # Bounds, counts and cover on both sides.
        assert kept["image_count"] == 2
        assert kept["start_at"] == _iso(BASE + timedelta(minutes=1))
        assert kept["end_at"] == _iso(BASE + timedelta(minutes=2))
        assert kept["thumbnail"] == "default_user/main/f0001.png"
        assert moved["image_count"] == 3
        assert moved["start_at"] == _iso(BASE + timedelta(minutes=3))
        assert moved["end_at"] == _iso(BASE + timedelta(minutes=5))
        assert moved["thumbnail"] == "default_user/main/f0003.png"

        # Membership rows really moved; nothing is in both.
        assert _members(session, kept["id"]) == {ids[0], ids[1]}
        assert _members(session, moved["id"]) == {ids[2], ids[3], ids[4]}

    def test_split_of_a_detected_session_survives_a_redetect(self, client, session):
        """The whole reason membership is stored rather than derived."""
        _add(session, _asset(1, seed=88), _asset(2, seed=88), _asset(3, seed=88))
        detect_sessions(session)
        original = _sessions(session)[0]

        resp = client.post(
            f"/api/v2/sessions/{original.id}/split",
            json={"keep_asset_ids": ["a0001"]},
        )
        assert resp.status_code == 200, resp.text
        moved = resp.json()["created"]
        assert moved["locked"] is True

        detect_sessions(session)

        assert _members(session, original.id) == {"a0001"}
        assert _members(session, moved["id"]) == {"a0002", "a0003"}
        assert session.get(GenerationSession, original.id).locked is True
        assert session.get(GenerationSession, moved["id"]).locked is True

    def test_split_names_do_not_collide(self, client, session):
        ids = [_api_asset(session, index, seed=4, minutes=index) for index in range(1, 4)]
        first = client.post(
            "/api/v2/sessions", json={"name": "Batch", "asset_ids": ids}
        ).json()
        second = client.post(
            f"/api/v2/sessions/{first['id']}/split", json={"keep_asset_ids": [ids[0]]}
        ).json()["created"]

        resp = client.post(
            f"/api/v2/sessions/{second['id']}/split", json={"keep_asset_ids": [ids[1]]}
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["created"]["name"] == "Batch (split 2)"

    def test_split_rejects_degenerate_requests(self, client, session):
        ids = [_api_asset(session, index, seed=5, minutes=index) for index in range(1, 4)]
        created = client.post(
            "/api/v2/sessions", json={"name": "Batch", "asset_ids": ids}
        ).json()

        empty = client.post(
            f"/api/v2/sessions/{created['id']}/split", json={"keep_asset_ids": []}
        )
        everything = client.post(
            f"/api/v2/sessions/{created['id']}/split", json={"keep_asset_ids": ids}
        )
        non_member = _api_asset(session, 99, seed=5)
        stranger = client.post(
            f"/api/v2/sessions/{created['id']}/split", json={"keep_asset_ids": [non_member]}
        )

        assert empty.status_code == 400, empty.text
        assert everything.status_code == 400, everything.text
        assert stranger.status_code == 400, stranger.text
        assert client.get(f"/api/v2/sessions/{created['id']}").json()["image_count"] == 3


class TestMerge:
    def test_merge_moves_members_and_soft_deletes_the_source(self, client, session):
        left = [
            _api_asset(session, index, seed=6, minutes=index) for index in range(1, 3)
        ]
        right = [
            _api_asset(session, index, seed=6, minutes=10 + index)
            for index in range(3, 5)
        ]
        source = client.post(
            "/api/v2/sessions", json={"name": "Source", "asset_ids": left}
        ).json()
        target = client.post(
            "/api/v2/sessions", json={"name": "Target", "asset_ids": right}
        ).json()

        resp = client.post(
            f"/api/v2/sessions/{source['id']}/merge",
            json={"target_session_id": target["id"]},
        )

        assert resp.status_code == 200, resp.text
        merged = resp.json()
        assert merged["id"] == target["id"]
        assert merged["locked"] is True
        assert merged["image_count"] == 4
        assert merged["start_at"] == _iso(BASE + timedelta(minutes=1))
        assert merged["end_at"] == _iso(BASE + timedelta(minutes=14))
        assert merged["thumbnail"] == "default_user/main/f0001.png"

        assert _members(session, target["id"]) == set(left + right)
        assert _members(session, source["id"]) == set()
        assert client.get(f"/api/v2/sessions/{source['id']}").status_code == 404
        dead = session.get(GenerationSession, source["id"])
        assert dead.deleted_at is not None and dead.image_count == 0
        assert client.get("/api/v2/sessions").json()["total"] == 1

    def test_merge_preserves_shared_members(self, client, session):
        """An asset can sit in more than one session, so the target may already
        hold some of the source's members. Those must not blow up on the unique
        constraint."""
        shared = _api_asset(session, 1, seed=7, minutes=0)
        only_source = _api_asset(session, 2, seed=7, minutes=1)
        source = client.post(
            "/api/v2/sessions",
            json={"name": "Source", "asset_ids": [shared, only_source]},
        ).json()
        target = client.post(
            "/api/v2/sessions", json={"name": "Target", "asset_ids": [shared]}
        ).json()

        resp = client.post(
            f"/api/v2/sessions/{source['id']}/merge",
            json={"target_session_id": target["id"]},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["image_count"] == 2
        assert _members(session, target["id"]) == {shared, only_source}

    def test_merge_rejects_itself_and_missing_targets(self, client, session):
        ids = [_api_asset(session, index, seed=8) for index in range(1, 3)]
        created = client.post(
            "/api/v2/sessions", json={"name": "A", "asset_ids": ids}
        ).json()

        itself = client.post(
            f"/api/v2/sessions/{created['id']}/merge",
            json={"target_session_id": created["id"]},
        )
        missing = client.post(
            f"/api/v2/sessions/{created['id']}/merge", json={"target_session_id": "ghost"}
        )

        assert itself.status_code == 400, itself.text
        assert missing.status_code == 404, missing.text
        assert client.get(f"/api/v2/sessions/{created['id']}").json()["image_count"] == 2


class TestDetectRoute:
    def test_detect_is_a_post_and_reports(self, client, session):
        _add(session, _asset(1, seed=1010), _asset(2, seed=1010))

        assert client.get("/api/v2/sessions/detect").status_code in (404, 405)

        resp = client.post("/api/v2/sessions/detect", json={})

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["min_size"] == 2
        assert body["time_gap_minutes"] == 20
        assert body["dry_run"] is False
        assert body["max_assets"] == MAX_DETECT_ASSETS
        assert body["summary"]["sessions_created"] == 1
        assert "elapsed_seconds" in body["summary"]
        assert client.get("/api/v2/sessions").json()["total"] == 1

    def test_detect_dry_run_through_the_route(self, client, session):
        _add(session, _asset(1, seed=2020), _asset(2, seed=2020))

        resp = client.post("/api/v2/sessions/detect", json={"dry_run": True})

        assert resp.status_code == 200, resp.text
        assert resp.json()["summary"]["pending_create"] == 1
        assert client.get("/api/v2/sessions").json()["total"] == 0

    def test_detect_validates_its_parameters(self, client):
        assert client.post("/api/v2/sessions/detect", json={"min_size": 0}).status_code == 422
        assert client.post(
            "/api/v2/sessions/detect", json={"time_gap_minutes": 0}
        ).status_code == 422
