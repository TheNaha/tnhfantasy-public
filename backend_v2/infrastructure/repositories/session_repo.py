"""Data access for generation sessions.

Everything that mutates membership funnels through here so `start_at`, `end_at`,
`image_count` and `thumbnail` cannot drift. They are denormalised on the session
row (the scrubber orders and seeks by them) but their only source of truth is
`session_assets`, so every path that changes membership ends in
`recompute_bounds`.

Bounds are computed over **non-deleted** members only. A soft-deleted asset
stays a member row — nothing cascades an asset deletion into the session tables
— but it must not inflate the count a UI shows, and the next membership change
or detect run reconciles the difference on its own.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, update
from sqlmodel import Session, func, select

from core.entities import Asset, SessionAsset
from core.entities import Session as GenerationSession
from services.session_detector import RESOLVED_TS


class SessionRepository:
    def __init__(self, session: Session):
        self.session = session

    # ── reads ────────────────────────────────────────────────────────────────

    def get(self, session_id: str) -> GenerationSession | None:
        """A live (not soft-deleted) session, or None."""
        row = self.session.get(GenerationSession, session_id)
        if row is None or row.deleted_at is not None:
            return None
        return row

    def member_ids(self, session_id: str) -> list[str]:
        rows = self.session.exec(
            select(SessionAsset.asset_id).where(
                SessionAsset.session_id == session_id
            )
        ).all()
        return [row for row in rows if row]

    def count(self) -> int:
        return self.session.execute(
            select(func.count(GenerationSession.id)).where(
                GenerationSession.deleted_at.is_(None)
            )
        ).scalar_one()

    def live_names(self, workspace: str | None = None) -> set[str]:
        """Names of live sessions, so a generated sibling name can avoid a clash."""
        statement = select(GenerationSession.name).where(
            GenerationSession.deleted_at.is_(None)
        )
        if workspace is not None:
            statement = statement.where(GenerationSession.workspace == workspace)
        rows = self.session.exec(statement).all()
        return {(row or "").strip() for row in rows}

    def live_asset_ids(self, asset_ids: list[str]) -> set[str]:
        """Which of `asset_ids` exist and are not soft-deleted.

        One query for the whole batch rather than a lookup per id.
        """
        if not asset_ids:
            return set()
        rows = self.session.exec(
            select(Asset.id).where(
                Asset.id.in_(asset_ids), Asset.deleted_at.is_(None)
            )
        ).all()
        return {row for row in rows if row}

    # ── membership writes ────────────────────────────────────────────────────

    def add_members(self, session_id: str, asset_ids: list[str]) -> int:
        now = datetime.now(timezone.utc)
        self.session.add_all(
            [
                SessionAsset(session_id=session_id, asset_id=asset_id, added_at=now)
                for asset_id in asset_ids
            ]
        )
        return len(asset_ids)

    def remove_members(self, session_id: str, asset_ids: list[str]) -> int:
        """Drop members. `None` removes every member of the session."""
        statement = delete(SessionAsset).where(SessionAsset.session_id == session_id)
        if asset_ids is not None:
            if not asset_ids:
                return 0
            statement = statement.where(SessionAsset.asset_id.in_(asset_ids))
        result = self.session.execute(statement)
        return result.rowcount or 0

    def move_members(self, source_id: str, target_id: str) -> int:
        """Re-point every member of `source_id` at `target_id`.

        An asset may legitimately sit in several sessions, so the target may
        already hold some of the source's members. Those rows are deleted rather
        than moved — the unique constraint is on `(session_id, asset_id)`, so
        moving them would be a no-op at best and an IntegrityError at worst.
        """
        source_assets = set(self.member_ids(source_id))
        if not source_assets:
            return 0
        target_assets = set(self.member_ids(target_id))
        collisions = source_assets & target_assets

        if collisions:
            self.session.execute(
                delete(SessionAsset).where(
                    SessionAsset.session_id == source_id,
                    SessionAsset.asset_id.in_(sorted(collisions)),
                )
            )
        statement = update(SessionAsset).where(SessionAsset.session_id == source_id)
        if collisions:
            statement = statement.where(
                SessionAsset.asset_id.not_in(sorted(collisions))
            )
        result = self.session.execute(statement.values(session_id=target_id))
        return result.rowcount or 0

    # ── denormalised bounds ──────────────────────────────────────────────────

    def recompute_bounds(self, row: GenerationSession) -> GenerationSession:
        """Refresh `start_at` / `end_at` / `image_count` / `thumbnail`.

        Two fixed queries — an aggregate and a single "earliest member" lookup —
        regardless of how many members the session has. The cover is the earliest
        member's `relative_path`, which is deterministic and does not move when
        the tail of a session grows.
        """
        count, start, end = self.session.execute(
            select(
                func.count(Asset.id),
                func.min(RESOLVED_TS),
                func.max(RESOLVED_TS),
            )
            .select_from(SessionAsset)
            .join(Asset, Asset.id == SessionAsset.asset_id)
            .where(
                SessionAsset.session_id == row.id,
                Asset.deleted_at.is_(None),
            )
        ).one()

        cover = self.session.execute(
            select(Asset.relative_path)
            .select_from(SessionAsset)
            .join(Asset, Asset.id == SessionAsset.asset_id)
            .where(
                SessionAsset.session_id == row.id,
                Asset.deleted_at.is_(None),
            )
            .order_by(RESOLVED_TS, Asset.id)
            .limit(1)
        ).scalar_one_or_none()

        row.start_at = start
        row.end_at = end
        row.image_count = count or 0
        row.thumbnail = cover
        row.updated_at = datetime.now(timezone.utc)
        return row

    def touch(self, row: GenerationSession) -> GenerationSession:
        row.updated_at = datetime.now(timezone.utc)
        return row
