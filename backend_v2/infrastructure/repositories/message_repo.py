from sqlmodel import Session, select

from core.entities import Message


class MessageRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_by_chat(self, chat_id: str, limit: int | None = None, offset: int | None = None) -> list[Message]:
        stmt = select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset is not None:
            stmt = stmt.offset(offset)
        return self.session.exec(stmt).all()
