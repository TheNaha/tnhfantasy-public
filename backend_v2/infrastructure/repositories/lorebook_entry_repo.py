from sqlmodel import Session, select

from core.entities import LorebookEntry


class LorebookEntryRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_by_lorebook(
        self, lorebook_id: str, limit: int | None = None
    ) -> list[LorebookEntry]:
        """A lorebook's entries, oldest first, deterministically.

        `created_at` then `id`: there is no per-book ordering column on
        `LorebookEntry` (the ST importer numbers entries but stores the number
        nowhere), so insertion order is the only ordering this app actually has.
        The trailing `id` breaks ties, because `created_at` is a timestamp and
        every entry from one import shares it — without the tiebreaker a page
        boundary would be arbitrary and the same offset would return different
        rows.

        There was no `ORDER BY` at all, so the order was whatever the planner
        returned. That is survivable while every caller takes everything and
        actively harmful the moment one takes a page, which is what `limit` is
        for.

        `limit` defaults to None (every entry) so the two callers that need the
        whole book — `delete_lorebook` and the SillyTavern export — are
        unchanged. The listing route passes a bound; see
        `LOREBOOK_ENTRY_PAGE_DEFAULT_LIMIT`.
        """
        stmt = (
            select(LorebookEntry)
            .where(LorebookEntry.lorebook_id == lorebook_id)
            .order_by(LorebookEntry.created_at, LorebookEntry.id)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return self.session.exec(stmt).all()

    def get(self, entry_id: str, lorebook_id: str) -> LorebookEntry | None:
        stmt = select(LorebookEntry).where(
            LorebookEntry.id == entry_id,
            LorebookEntry.lorebook_id == lorebook_id,
        )
        return self.session.exec(stmt).first()
