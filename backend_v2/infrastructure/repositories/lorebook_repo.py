from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlmodel import Session, select

from core.entities import Lorebook


class LorebookRepository:
    def __init__(self, session: Session):
        self.session = session

    def list(self) -> list[Lorebook]:
        stmt = select(Lorebook).order_by(Lorebook.name)
        return self.session.exec(stmt).all()

    def get(self, lorebook_id: str) -> Lorebook | None:
        return self.session.get(Lorebook, lorebook_id)

    def search(self, query: str, limit: int = 10) -> list[Lorebook]:
        stmt = (
            select(Lorebook)
            .where(Lorebook.name.ilike(f"%{query}%"))
            .order_by(Lorebook.name)
            .limit(limit)
        )
        return self.session.exec(stmt).all()

    def get_by_ids(self, ids: list[str]) -> list[Lorebook]:
        if not ids:
            return []
        return self.session.exec(select(Lorebook).where(Lorebook.id.in_(ids))).all()
