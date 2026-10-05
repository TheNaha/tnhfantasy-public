from __future__ import annotations

from sqlalchemy import func
from sqlmodel import Session, select

from core.entities import Character
from core.sql_search import LIKE_ESCAPE_CHAR, like_contains


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
        pattern = like_contains(query.lower())
        stmt = select(Character).where(
            func.lower(Character.name).like(pattern, escape=LIKE_ESCAPE_CHAR)
            | func.lower(Character.description).like(pattern, escape=LIKE_ESCAPE_CHAR)
        ).limit(limit)
        return self.session.exec(stmt).all()

