from sqlmodel import Session, select

from core.entities import StoryChapter


class StoryChapterRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_by_story(self, story_id: str) -> list[StoryChapter]:
        stmt = select(StoryChapter).where(StoryChapter.story_id == story_id).order_by(StoryChapter.chapter_number)
        return self.session.exec(stmt).all()

    def get_max_chapter_number(self, story_id: str) -> StoryChapter | None:
        stmt = select(StoryChapter).where(StoryChapter.story_id == story_id).order_by(StoryChapter.chapter_number.desc())
        return self.session.exec(stmt).first()

    def get(self, chapter_id: str, story_id: str) -> StoryChapter | None:
        stmt = select(StoryChapter).where(
            StoryChapter.id == chapter_id,
            StoryChapter.story_id == story_id
        )
        return self.session.exec(stmt).first()
