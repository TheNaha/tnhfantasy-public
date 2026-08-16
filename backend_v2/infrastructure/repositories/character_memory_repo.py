from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session, select

from core.entities import CharacterMemory


class CharacterMemoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def list(self, character_id: str | None = None) -> list[CharacterMemory]:
        stmt = select(CharacterMemory).order_by(CharacterMemory.created_at.desc())
        if character_id is not None:
            stmt = stmt.where(CharacterMemory.character_id == character_id)
        return self.session.exec(stmt).all()

    def get(self, memory_id: str) -> CharacterMemory | None:
        return self.session.get(CharacterMemory, memory_id)

    def search_keyword(
        self, character_id: str, query: str, limit: int = 10
    ) -> list[CharacterMemory]:
        stmt = (
            select(CharacterMemory)
            .where(
                CharacterMemory.character_id == character_id,
                CharacterMemory.content.ilike(f"%{query}%"),
            )
            .limit(limit)
        )
        return self.session.exec(stmt).all()

    def search_semantic(
        self, character_id: str, query_vec: list[float], limit: int = 5
    ) -> list[CharacterMemory]:
        stmt = (
            select(CharacterMemory)
            .where(
                CharacterMemory.character_id == character_id,
                CharacterMemory.embedding.isnot(None),
            )
            .order_by(text("embedding <=> :vec"))
            .limit(limit)
        )
        return self.session.exec(stmt, {"vec": str(query_vec)}).all()

    def get_recent_for_character(
        self, character_id: str, limit: int = 10
    ) -> list[CharacterMemory]:
        stmt = (
            select(CharacterMemory)
            .where(CharacterMemory.character_id == character_id)
            .order_by(
                CharacterMemory.last_accessed_at.desc(nulls_last=True),
                CharacterMemory.importance.desc(),
                CharacterMemory.created_at.desc(),
            )
            .limit(limit)
        )
        return self.session.exec(stmt).all()
