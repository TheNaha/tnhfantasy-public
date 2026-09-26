"""Tests for Message Branching endpoints."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from api.routes.world_vault import branches as branches_module
from api.routes.world_vault.branches import (
    BRANCH_COPY_MAX_MESSAGES,
    BRANCH_PAGE_DEFAULT_LIMIT,
    BRANCH_PAGE_MAX_LIMIT,
)
from core.entities import Chat, Message, MessageRole


def _seed_messages(session, chat, count, *, start=None):
    """Create `count` messages with strictly increasing created_at.

    Explicit timestamps keep page order deterministic; the default factory
    stamps `now()` per row, which is fine but makes an off-by-one in a page
    assertion hard to tell apart from clock jitter.
    """
    base = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    created = []
    for i in range(count):
        msg = Message(
            chat_id=chat.id,
            role=MessageRole.USER,
            content=f"message {i}",
            created_at=base + timedelta(seconds=i),
            updated_at=base + timedelta(seconds=i),
        )
        session.add(msg)
        created.append(msg)
    session.commit()
    for msg in created:
        session.refresh(msg)
    return created


@pytest.fixture
def chat_with_messages(session):
    chat = Chat(title="BranchTest", character_id=None, llm_provider="test")
    session.add(chat)
    session.commit()
    session.refresh(chat)

    msg1 = Message(
        chat_id=chat.id,
        role=MessageRole.USER,
        content="Hello there",
        sequence_num=0,
    )
    session.add(msg1)
    session.commit()
    session.refresh(msg1)

    msg2 = Message(
        chat_id=chat.id,
        role=MessageRole.CHAR,
        content="Hi! How can I help?",
        sequence_num=1,
        parent_id=msg1.id,
    )
    session.add(msg2)
    session.commit()
    session.refresh(msg2)

    return chat, msg1, msg2


def test_list_branches(client, session, chat_with_messages):
    chat, msg1, msg2 = chat_with_messages
    response = client.get(f"/api/v2/chats/{chat.id}/branches")
    assert response.status_code == 200
    data = response.json()
    # Should return branches (at minimum the main branch)
    assert isinstance(data, list)


def test_create_branch(client, session, chat_with_messages):
    chat, msg1, msg2 = chat_with_messages
    response = client.post(f"/api/v2/chats/{chat.id}/branches", json={
        "message_id": msg1.id,
        "branch_name": "Alternative greeting",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["branch_id"]
    assert data["branch_name"] == "Alternative greeting"
    assert data["anchor_message_id"] == msg1.id


def test_get_alternates(client, session, chat_with_messages):
    chat, msg1, msg2 = chat_with_messages
    response = client.get(f"/api/v2/chats/{chat.id}/messages/{msg1.id}/alternates")
    assert response.status_code == 200
    data = response.json()
    # Should return a dict with alternates list
    assert "alternates" in data
    assert isinstance(data["alternates"], list)


def _returned_messages(payload):
    return [m for branch in payload for m in branch["messages"]]


def test_list_branches_truncates_and_says_so(client, session):
    """An over-cap chat comes back as a flagged page, not a silent prefix."""
    chat = Chat(title="PagedBranchTest", character_id=None, llm_provider="test")
    session.add(chat)
    session.commit()
    session.refresh(chat)
    _seed_messages(session, chat, 5)

    response = client.get(f"/api/v2/chats/{chat.id}/branches?limit=2")

    assert response.status_code == 200
    payload = response.json()
    assert len(_returned_messages(payload)) == 2
    assert response.headers["X-Total-Count"] == "5"
    assert response.headers["X-Has-More"] == "true"
    assert response.headers["X-Limit"] == "2"
    assert response.headers["X-Offset"] == "0"


def test_list_branches_offset_pages_do_not_overlap(client, session):
    chat = Chat(title="PagedOffsetTest", character_id=None, llm_provider="test")
    session.add(chat)
    session.commit()
    session.refresh(chat)
    _seed_messages(session, chat, 5)

    first = client.get(f"/api/v2/chats/{chat.id}/branches?limit=2&offset=0").json()
    second = client.get(f"/api/v2/chats/{chat.id}/branches?limit=2&offset=2").json()
    last = client.get(f"/api/v2/chats/{chat.id}/branches?limit=2&offset=4")

    ids = [m["id"] for m in _returned_messages(first + second + last.json())]
    assert len(ids) == 5
    assert len(set(ids)) == 5
    assert last.headers["X-Has-More"] == "false"
    assert last.headers["X-Offset"] == "4"


def test_list_branches_default_cap_bounds_a_long_chat(client, session):
    """The default page is BRANCH_PAGE_DEFAULT_LIMIT, whatever the chat size."""
    chat = Chat(title="LongBranchTest", character_id=None, llm_provider="test")
    session.add(chat)
    session.commit()
    session.refresh(chat)
    total = BRANCH_PAGE_DEFAULT_LIMIT + 1
    _seed_messages(session, chat, total)

    response = client.get(f"/api/v2/chats/{chat.id}/branches")

    assert response.status_code == 200
    assert len(_returned_messages(response.json())) == BRANCH_PAGE_DEFAULT_LIMIT
    assert response.headers["X-Total-Count"] == str(total)
    assert response.headers["X-Has-More"] == "true"


def test_list_branches_rejects_limit_over_max(client, session, chat_with_messages):
    chat, _msg1, _msg2 = chat_with_messages
    response = client.get(f"/api/v2/chats/{chat.id}/branches?limit={BRANCH_PAGE_MAX_LIMIT + 1}")
    assert response.status_code == 422


def test_list_branches_unknown_chat_is_404(client):
    assert client.get("/api/v2/chats/does-not-exist/branches").status_code == 404


def test_create_branch_refuses_when_copy_exceeds_cap(client, session, monkeypatch):
    """Over the cap it is a 400 with the real count — never a truncated branch."""
    monkeypatch.setattr(branches_module, "BRANCH_COPY_MAX_MESSAGES", 2)
    chat = Chat(title="CapRefusalTest", character_id=None, llm_provider="test")
    session.add(chat)
    session.commit()
    session.refresh(chat)
    msgs = _seed_messages(session, chat, 4)

    response = client.post(f"/api/v2/chats/{chat.id}/branches", json={"message_id": msgs[-1].id})

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["field"] == "message_id"
    assert "4 messages" in body["error"]
    # Refused, so nothing was written: no half-built branch left behind.
    assert len(session.exec(select(Message).where(Message.chat_id == chat.id)).all()) == 4


def test_create_branch_copies_only_up_to_the_anchor_under_cap(client, session, monkeypatch):
    monkeypatch.setattr(branches_module, "BRANCH_COPY_MAX_MESSAGES", 3)
    chat = Chat(title="CapCopyTest", character_id=None, llm_provider="test")
    session.add(chat)
    session.commit()
    session.refresh(chat)
    msgs = _seed_messages(session, chat, 4)

    response = client.post(
        f"/api/v2/chats/{chat.id}/branches",
        json={"message_id": msgs[1].id, "branch_name": "Capped"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["branch_name"] == "Capped"
    copied = session.exec(
        select(Message).where(Message.branch_id == data["branch_id"]).order_by(Message.created_at)
    ).all()
    assert [m.content for m in copied] == ["message 0", "message 1"]
    assert data["new_anchor_message_id"] == copied[-1].id


def test_create_branch_cap_is_shared_with_the_read(client):
    """The write refuses at the same ceiling the read caps at."""
    assert BRANCH_COPY_MAX_MESSAGES == BRANCH_PAGE_MAX_LIMIT
