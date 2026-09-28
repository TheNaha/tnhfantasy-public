from sqlmodel import Session, select

from core.entities import Message


class MessageRepository:
    # A chat with no explicit limit must never return its entire history.
    #
    # The default was `limit=None`, i.e. "every message in the chat", and two
    # callers relied on it: the context build and the scene-job prep. Both then
    # used only a slice of the result — `prune_context` keeps the most recent
    # `MAX_CONTEXT_MESSAGES` (200), and the scene prep keeps the last 10 — so the
    # database was asked to materialise and ORM-instantiate the whole transcript
    # to hand back a window of it. On a long roleplay that is thousands of rows
    # per send, on the event loop's thread, before any budget is applied.
    #
    # This is the same number `chats.py` already imports and honours in four
    # other places, so the cap is now applied at the repository rather than
    # remembered per call site. `DEFAULT_LIMIT` is deliberately generous: the
    # point is a ceiling, not a change of behaviour for normal chats.
    DEFAULT_LIMIT = 200

    def __init__(self, session: Session):
        self.session = session

    def list_by_chat(
        self,
        chat_id: str,
        limit: int | None = None,
        offset: int | None = None,
        *,
        newest_first: bool = False,
    ) -> list[Message]:
        """Return a chat's messages in chronological order, most recent `limit`.

        `newest_first` keeps only the newest `limit` rows, which is what a
        caller that wants the tail actually needs; the default stays "the oldest
        `limit` rows" so existing pagination semantics are unchanged.
        """
        if newest_first:
            stmt = (
                select(Message)
                .where(Message.chat_id == chat_id)
                .order_by(Message.created_at.desc())
                .limit(limit if limit is not None else self.DEFAULT_LIMIT)
            )
            rows = self.session.exec(stmt).all()
            return list(reversed(rows))

        stmt = select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
        stmt = stmt.limit(limit if limit is not None else self.DEFAULT_LIMIT)
        if offset is not None:
            stmt = stmt.offset(offset)
        return self.session.exec(stmt).all()
