from sqlmodel import Session, select

from core.entities import Story

# Page ceiling, matching api/routes/world_vault/stories.py.
MAX_STORY_PAGE_SIZE = 200


class StoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_active(self, limit: int = 100, offset: int = 0) -> list[Story]:
        # Clamped here as well as at the route, because this method is reachable
        # from services directly and `?limit=100000000` used to pass the route
        # uncaught. The route is the authoritative bound; this is the backstop
        # for the next caller that forgets one.
        limit = max(1, min(int(limit), MAX_STORY_PAGE_SIZE))
        offset = max(0, int(offset))
        stmt = select(Story).where(Story.is_archived == False).order_by(Story.updated_at.desc()).limit(limit).offset(offset)
        return self.session.exec(stmt).all()

    def get(self, story_id: str) -> Story | None:
        return self.session.get(Story, story_id)
