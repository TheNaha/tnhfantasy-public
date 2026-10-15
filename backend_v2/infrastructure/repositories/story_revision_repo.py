from datetime import datetime, timezone

from sqlmodel import Session, select

from core.entities import StoryChapterRevision

MAX_REVISIONS_PER_CHAPTER = 20


class StoryChapterRevisionRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_for_chapter(self, chapter_id: str) -> list[StoryChapterRevision]:
        stmt = (
            select(StoryChapterRevision)
            .where(StoryChapterRevision.chapter_id == chapter_id)
            .order_by(StoryChapterRevision.created_at.desc(), StoryChapterRevision.id.desc())
        )
        return list(self.session.exec(stmt).all())

    def get(self, revision_id: str, story_id: str) -> StoryChapterRevision | None:
        stmt = select(StoryChapterRevision).where(
            StoryChapterRevision.id == revision_id,
            StoryChapterRevision.story_id == story_id,
        )
        return self.session.exec(stmt).first()

    def create_snapshot(self, chapter, source: str = "manual") -> StoryChapterRevision:
        """Snapshot the beats with the prose.

        A snapshot of `content` alone cannot be restored faithfully, because the
        prose is a render of the beat list: restoring it without the beats put
        the chapter back into a state where the two describe different text —
        the exact drift the beat list exists to prevent, reintroduced by the one
        route that rewinds state.
        """
        revision = StoryChapterRevision(
            chapter_id=chapter.id,
            story_id=chapter.story_id,
            content=chapter.content or "",
            beats=[dict(b) for b in (chapter.beats or []) if isinstance(b, dict)],
            source=source,
            word_count=len((chapter.content or "").split()),
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(revision)
        self._prune(chapter.id)
        return revision

    def _prune(self, chapter_id: str) -> None:
        """Keep only the most recent MAX_REVISIONS_PER_CHAPTER snapshots."""
        stmt = (
            select(StoryChapterRevision)
            .where(StoryChapterRevision.chapter_id == chapter_id)
            .order_by(StoryChapterRevision.created_at.desc(), StoryChapterRevision.id.desc())
            .offset(MAX_REVISIONS_PER_CHAPTER)
        )
        for stale in self.session.exec(stmt).all():
            self.session.delete(stale)
