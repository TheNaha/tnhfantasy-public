from __future__ import annotations

from sqlalchemy import text, func
from sqlmodel import Session, select

from core.entities import Character


class CharacterRepository:
    def __init__(self, session: Session):
        self.session = session

    def list(self) -> list[Character]:
        return self.session.exec(select(Character).order_by(Character.sort_order, Character.name)).all()

    def get(self, character_id: str) -> Character | None:
        return self.session.get(Character, character_id)

    def get_by_ids(self, ids: list[str]) -> list[Character]:
        if not ids:
            return []
        return self.session.exec(select(Character).where(Character.id.in_(ids))).all()

    def search(self, query: str, limit: int = 10) -> list[Character]:
        pattern = f"%{query.lower()}%"
        stmt = select(Character).where(
            func.lower(Character.name).like(pattern)
            | func.lower(Character.description).like(pattern)
        ).limit(limit)
        return self.session.exec(stmt).all()

    def get_recent(self, limit: int = 5) -> list[Character]:
        stmt = select(Character).order_by(Character.created_at.desc()).limit(limit)
        return self.session.exec(stmt).all()
