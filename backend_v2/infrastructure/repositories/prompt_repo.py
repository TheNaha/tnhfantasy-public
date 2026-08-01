from sqlalchemy import or_
from sqlmodel import Session, select

from core.entities import Prompt


class PromptRepository:
    def __init__(self, session: Session):
        self.session = session

    def search_prompts(self, query: str = "", include_nsfw: bool = False, tag: str = "") -> list[Prompt]:
        stmt = select(Prompt)
        
        if query:
            if tag:
                stmt = stmt.where(
                    or_(
                        Prompt.text.contains(query),
                        Prompt.tags.contains(tag)
                    )
                )
            else:
                stmt = stmt.where(Prompt.text.contains(query))
        elif tag:
            stmt = stmt.where(Prompt.tags.contains(tag))
            
        if not include_nsfw:
            stmt = stmt.where(Prompt.is_nsfw == False)
            
        stmt = stmt.order_by(Prompt.updated_at.desc())
        return self.session.exec(stmt).all()

    def get_favorite_prompts(self, limit: int = 50) -> list[Prompt]:
        stmt = select(Prompt).where(Prompt.favorite == True).order_by(Prompt.usage_count.desc()).limit(limit)
        return self.session.exec(stmt).all()

    def get_top_prompts(self, limit: int = 50) -> list[Prompt]:
        stmt = select(Prompt).order_by(Prompt.usage_count.desc()).limit(limit)
        return self.session.exec(stmt).all()

    def get_all_prompts(self) -> list[Prompt]:
        return self.session.exec(select(Prompt)).all()
