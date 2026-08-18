from __future__ import annotations

from sqlmodel import Session

from core.entities import Chat


class ChatRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, chat_id: str) -> Chat | None:
        return self.session.get(Chat, chat_id)
