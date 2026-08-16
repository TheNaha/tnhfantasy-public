from sqlalchemy import text
from sqlmodel import Session, select

from core.entities import LorebookEntry


class LorebookEntryRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_by_lorebook(self, lorebook_id: str) -> list[LorebookEntry]:
        stmt = select(LorebookEntry).where(LorebookEntry.lorebook_id == lorebook_id)
        return self.session.exec(stmt).all()

    def semantic_search(
        self, lorebook_id: str, query_vec: list[float], limit: int = 5
    ) -> list[LorebookEntry]:
        stmt = (
            select(LorebookEntry)
            .where(
                LorebookEntry.lorebook_id == lorebook_id,
                LorebookEntry.embedding.isnot(None),
            )
            .order_by(text("embedding <=> :vec"))
            .limit(limit)
        )
        return self.session.exec(stmt, {"vec": str(query_vec)}).all()

    def keyword_search(
        self, lorebook_id: str, query: str, limit: int = 5
    ) -> list[LorebookEntry]:
        stmt = (
            select(LorebookEntry)
            .where(
                LorebookEntry.lorebook_id == lorebook_id,
                LorebookEntry.content.ilike(f"%{query}%"),
            )
            .limit(limit)
        )
        return self.session.exec(stmt).all()

    def get(self, entry_id: str, lorebook_id: str) -> LorebookEntry | None:
        stmt = select(LorebookEntry).where(
            LorebookEntry.id == entry_id,
            LorebookEntry.lorebook_id == lorebook_id,
        )
        return self.session.exec(stmt).first()
