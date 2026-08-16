from sqlalchemy import text
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

    def list_by_chat_for_context(self, chat_id: str, max_messages: int = 50) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at)
            .limit(max_messages)
        )
        return self.session.exec(stmt).all()

    def list_images(self, chat_id: str) -> list[Message]:
        stmt = (
            select(Message)
            .where(
                Message.chat_id == chat_id,
                Message.image_path.is_not(None)
            )
            .order_by(Message.created_at.desc())
        )
        return self.session.exec(stmt).all()

    def get_last_content_message(self, chat_id: str) -> Message | None:
        stmt = (
            select(Message)
            .where(
                Message.chat_id == chat_id,
                Message.role.in_(["char", "user"]),
                Message.content.is_not(None)
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        return self.session.exec(stmt).first()

    def delete_by_chat(self, chat_id: str):
        self.session.execute(
            text("DELETE FROM messages WHERE chat_id = :chat_id"),
            {"chat_id": chat_id}
        )

    def delete_message(self, message_id: str, chat_id: str):
        stmt = text("DELETE FROM messages WHERE id = :message_id AND chat_id = :chat_id")
        self.session.execute(stmt, {"message_id": message_id, "chat_id": chat_id})

    def get(self, message_id: str) -> Message | None:
        return self.session.get(Message, message_id)

    def list_by_branch(self, chat_id: str, branch_id: str) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.chat_id == chat_id, Message.branch_id == branch_id)
            .order_by(Message.created_at)
        )
        return self.session.exec(stmt).all()
