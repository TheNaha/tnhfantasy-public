from sqlalchemy import cast, text
from sqlmodel import Session, select

from core.entities import Story


class StoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_active(self) -> list[Story]:
        stmt = select(Story).where(Story.is_archived == False).order_by(Story.updated_at.desc())
        return self.session.exec(stmt).all()

    def get(self, story_id: str) -> Story | None:
        return self.session.get(Story, story_id)

    def get_by_token(self, token: str) -> Story | None:
        stmt = select(Story).where(
            Story.published_token == token,
            Story.is_published == True
        )
        return self.session.exec(stmt).first()

    def get_recent(self, limit: int = 5) -> list[Story]:
        stmt = select(Story).order_by(Story.created_at.desc()).limit(limit)
        return self.session.exec(stmt).all()

    def search(self, query: str, limit: int = 10) -> list[Story]:
        q = f"%{query.lower()}%"
        stmt = text("""
            SELECT * FROM stories
            WHERE lower(title) LIKE :q OR lower(description) LIKE :q
            ORDER BY updated_at DESC
            LIMIT :limit
        """)
        result = self.session.execute(stmt, {"q": q, "limit": limit})
        return [Story.model_validate(row._mapping) for row in result]

    def find_by_character_id(self, character_id: str, limit: int = 100) -> list[Story]:
        stmt = select(Story).where(
            cast(Story.character_ids, text).contains(character_id)
        ).limit(limit)
        return self.session.exec(stmt).all()
