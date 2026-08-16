from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlmodel import Session, select

from core.entities import Location


class LocationRepository:
    def __init__(self, session: Session):
        self.session = session

    def list(self) -> list[Location]:
        return self.session.exec(select(Location).order_by(Location.name)).all()

    def get(self, location_id: str) -> Location | None:
        return self.session.get(Location, location_id)

    def search(self, query: str) -> list[Location]:
        stmt = select(Location).where(
            text("lower(name) LIKE :q OR lower(description) LIKE :q")
        ).order_by(Location.name)
        return self.session.exec(stmt, {"q": f"%{query.lower()}%"}).all()

    def get_by_ids(self, ids: list[str]) -> list[Location]:
        if not ids:
            return []
        return self.session.exec(
            select(Location).where(Location.id.in_(ids))
        ).all()
