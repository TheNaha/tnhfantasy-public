from sqlmodel import Session, select

from core.entities import Story


class StoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_active(self, limit: int = 100, offset: int = 0) -> list[Story]:
        stmt = select(Story).where(Story.is_archived == False).order_by(Story.updated_at.desc()).limit(limit).offset(offset)
        return self.session.exec(stmt).all()

    def get(self, story_id: str) -> Story | None:
        return self.session.get(Story, story_id)
