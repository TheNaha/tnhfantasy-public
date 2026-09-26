"""Tests for the World Timeline message query (N+1 + character attribution).

Two defects in one loop, both asserted here:

1. `msg.chat.character_id` on a `select(Message)` that never eager-loaded the
   relationship was one extra SELECT per row, up to `limit + offset` (600 on
   `?limit=500&offset=100`).
2. It reported the CHAT's primary character for every message, so a
   `?character_id=X` timeline labelled narrator turns and other group-chat
   members as X. `Message.character_id` is the speaking character (entities.py,
   indexed, migration 060) and must win, with the chat's primary as the fallback.
"""

from sqlalchemy import event as sa_event
from sqlmodel import Session

from core.entities import (
    Character,
    Chat,
    Message,
    MessageKind,
    MessageRole,
)


def _seed_group_chat(session: Session) -> tuple[Chat, Character, Character]:
    primary = Character(name="Aria")
    other = Character(name="Rhen")
    session.add(primary)
    session.add(other)
    session.commit()
    session.refresh(primary)
    session.refresh(other)

    chat = Chat(name="Group", character_id=primary.id)
    session.add(chat)
    session.commit()
    session.refresh(chat)
    return chat, primary, other


def _add_message(session: Session, chat: Chat, *, character_id, kind, content, role=MessageRole.CHAR):
    msg = Message(
        role=role,
        kind=kind,
        content=content,
        chat_id=chat.id,
        character_id=character_id.id if character_id else None,
    )
    session.add(msg)
    session.commit()
    session.refresh(msg)
    return msg


def _message_events(client, **params):
    resp = client.get("/api/v2/timeline/timeline", params=params)
    assert resp.status_code == 200, resp.text
    return [e for e in resp.json()["events"] if e["type"] == "message"]


class TestMessageAttribution:
    def test_narrator_message_attributes_to_the_narrator_not_the_chats_primary(
        self, client, session
    ):
        """A narrator turn has no speaking character; it must not inherit the
        chat's primary character, which is what the old code always did."""
        chat, primary, other = _seed_group_chat(session)
        narrator = _add_message(
            session, chat, character_id=other, kind=MessageKind.NARRATOR,
            content="The rain begins to fall.",
        )

        event = next(e for e in _message_events(client) if e["id"] == narrator.id)

        assert event["character_id"] == other.id
        assert event["character_id"] != primary.id

    def test_group_chat_member_message_keeps_its_own_speaker(self, client, session):
        chat, primary, other = _seed_group_chat(session)
        msg = _add_message(
            session, chat, character_id=other, kind=MessageKind.CHAR,
            content="I disagree.",
        )

        event = next(e for e in _message_events(client) if e["id"] == msg.id)

        assert event["character_id"] == other.id

    def test_message_with_no_speaker_falls_back_to_the_chats_primary_character(
        self, client, session
    ):
        chat, primary, _other = _seed_group_chat(session)
        msg = _add_message(
            session, chat, character_id=None, kind=MessageKind.CHAR,
            content="...", role=MessageRole.USER,
        )

        event = next(e for e in _message_events(client) if e["id"] == msg.id)

        assert event["character_id"] == primary.id

    def test_character_filter_does_not_relabel_every_message_in_the_chat(
        self, client, session
    ):
        """`?character_id=X` used to make the whole chat's timeline read as X."""
        chat, primary, other = _seed_group_chat(session)
        from_other = _add_message(
            session, chat, character_id=other, kind=MessageKind.CHAR, content="mine"
        )
        from_primary = _add_message(
            session, chat, character_id=primary, kind=MessageKind.CHAR, content="theirs"
        )

        events = {e["id"]: e for e in _message_events(client, character_id=primary.id)}

        assert events[from_primary.id]["character_id"] == primary.id
        assert events[from_other.id]["character_id"] == other.id


class TestNoNPlusOne:
    def test_message_page_query_count_does_not_scale_with_row_count(
        self, client, session, engine
    ):
        """The N+1 was 1 lazy SELECT per message.

        Run the same request with 2 and then 12 messages — each in its OWN chat,
        so a lazy `Message.chat` load cannot be satisfied from the session
        identity map and really does hit the database — and require the SELECT
        count to be identical. This is the form a fixed-but-still-per-row query
        cannot pass.
        """
        for index in range(2):
            self._seed_one_message(session, index)
        few = self._count_selects(client, engine)

        for index in range(2, 12):
            self._seed_one_message(session, index)
        many = self._count_selects(client, engine)

        assert few == many, (
            f"SELECT count grew with row count: {few} for 2 messages, {many} for 12"
        )

    @staticmethod
    def _seed_one_message(session: Session, index: int) -> None:
        char = Character(name=f"Char {index}")
        session.add(char)
        session.commit()
        session.refresh(char)
        chat = Chat(name=f"Chat {index}", character_id=char.id)
        session.add(chat)
        session.commit()
        session.refresh(chat)
        msg = Message(
            role=MessageRole.CHAR,
            kind=MessageKind.CHAR,
            content=f"message {index}",
            chat_id=chat.id,
            character_id=char.id,
        )
        session.add(msg)
        session.commit()

    def test_no_per_row_chat_lookup_is_emitted(self, client, session, engine):
        """Pins the specific statement the N+1 produced."""
        for index in range(8):
            self._seed_one_message(session, index)

        statements = self._record_selects(client, engine)

        per_row_chat_lookups = [
            s for s in statements
            if s.lstrip().upper().startswith("SELECT")
            and "FROM chats" in s
            and "WHERE" in s
        ]
        assert per_row_chat_lookups == [], (
            f"timeline still lazy-loads Message.chat per row: {per_row_chat_lookups}"
        )

    @staticmethod
    def _record_selects(client, engine) -> list[str]:
        statements: list[str] = []

        @sa_event.listens_for(engine, "before_cursor_execute")
        def _count(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        try:
            _message_events(client, limit=50)
        finally:
            sa_event.remove(engine, "before_cursor_execute", _count)
        return statements

    @classmethod
    def _count_selects(cls, client, engine) -> int:
        return len([
            s for s in cls._record_selects(client, engine)
            if s.lstrip().upper().startswith("SELECT")
        ])
