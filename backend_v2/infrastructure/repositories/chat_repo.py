from __future__ import annotations

from sqlalchemy import text, func
from sqlmodel import Session, select

from core.entities import Chat, Message


class ChatRepository:
    def __init__(self, session: Session):
        self.session = session

    def list(self, workspace: str | None = None, q: str | None = None, limit: int = 20, offset: int = 0) -> list[Chat]:
        stmt = select(Chat).order_by(Chat.updated_at.desc()).offset(offset).limit(limit)
        if workspace:
            stmt = stmt.where(Chat.chat_type == workspace)
        if q and q.strip():
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(Chat.name.ilike(pattern))
        return self.session.exec(stmt).all()

    def get(self, chat_id: str) -> Chat | None:
        return self.session.get(Chat, chat_id)

    def delete_messages(self, chat_id: str):
        self.session.execute(
            text("DELETE FROM messages WHERE chat_id = :chat_id"),
            {"chat_id": chat_id}
        )

    def get_for_timeline(self, character_id: str | None = None, location: str | None = None, limit: int = 100) -> list[Message]:
        stmt = select(Message).order_by(Message.created_at.desc()).limit(limit)
        if character_id or location:
            stmt = stmt.join(Chat)
            if character_id:
                stmt = stmt.where(Chat.character_id == character_id)
            if location:
                stmt = stmt.where(Chat.story_location == location)
        return self.session.exec(stmt).all()

    def search(self, query: str, limit: int = 10) -> list[Chat]:
        pattern = f"%{query.lower()}%"
        stmt = select(Chat).where(func.lower(Chat.name).like(pattern)).limit(limit)
        return self.session.exec(stmt).all()
