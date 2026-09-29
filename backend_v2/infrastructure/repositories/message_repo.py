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
        branch_id: str | None = None,
    ) -> list[Message]:
        """Return one thread's messages in chronological order, most recent `limit`.

        `newest_first` keeps only the newest `limit` rows, which is what a
        caller that wants the tail actually needs; the default stays "the oldest
        `limit` rows" so existing pagination semantics are unchanged.

        `branch_id` is the branch filter, and it is NOT optional in the sense of
        "off when omitted": `None` means the ORIGINAL thread, spelled
        `branch_id IS NULL`. This is exactly what `GET /chats/{id}/messages`
        does with its own `branch_id` query parameter (`_branch_scope` in
        `chats.py` is the same rule), and it is the only safe default for a
        read that feeds an LLM. `create_branch` copies messages with their
        originals' `chat_id` AND `created_at`, so an unfiltered read returns
        every branch's copies interleaved among equal timestamps — the model
        receives the conversation duplicated, which the read route was already
        fixed for and the two paid-path reads were not.
        """
        thread = (
            (Message.branch_id == branch_id) if branch_id is not None
            else Message.branch_id.is_(None)
        )
        if newest_first:
            stmt = (
                select(Message)
                .where(Message.chat_id == chat_id, thread)
                .order_by(Message.created_at.desc())
                .limit(limit if limit is not None else self.DEFAULT_LIMIT)
            )
            rows = self.session.exec(stmt).all()
            return list(reversed(rows))

        stmt = (
            select(Message)
            .where(Message.chat_id == chat_id, thread)
            .order_by(Message.created_at)
        )
        stmt = stmt.limit(limit if limit is not None else self.DEFAULT_LIMIT)
        if offset is not None:
            stmt = stmt.offset(offset)
        return self.session.exec(stmt).all()
