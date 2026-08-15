"""Tests for Message Branching endpoints."""
import pytest

from core.entities import Chat, Message, MessageRole


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
