from sqlmodel import Session, select

from core.entities import LorebookEntry


class LorebookEntryRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_by_lorebook(self, lorebook_id: str) -> list[LorebookEntry]:
        stmt = select(LorebookEntry).where(LorebookEntry.lorebook_id == lorebook_id)
        return self.session.exec(stmt).all()

    def get(self, entry_id: str, lorebook_id: str) -> LorebookEntry | None:
        stmt = select(LorebookEntry).where(
            LorebookEntry.id == entry_id,
            LorebookEntry.lorebook_id == lorebook_id,
        )
        return self.session.exec(stmt).first()
