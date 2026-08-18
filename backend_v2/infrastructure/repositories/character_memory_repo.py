from __future__ import annotations

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
