"""Route tests for POST /chats/{id}/messages/{mid}/generate-swipe.

Covers the Batch 1 fix: the route must create an LLM job (task_type "llm"),
flag it as a swipe targeting the original message, and enqueue it — plus the
validation paths (CHAR-only, ownership, 404s).
"""

from unittest.mock import AsyncMock

from sqlmodel import Session

from core.entities import Chat, Character, Job, Message, MessageRole


def _seed_chat_with_char_message(session: Session, content="Hello there", char_name="Aria"):
    char = Character(name=char_name)
    session.add(char)
    session.commit()
    session.refresh(char)
    chat = Chat(name="Swipe Chat", character_id=char.id)
    session.add(chat)
    session.commit()
    session.refresh(chat)
    msg = Message(role=MessageRole.CHAR, content=content, chat_id=chat.id)
    session.add(msg)
    session.commit()
    session.refresh(msg)
    return chat, msg


class TestGenerateSwipeValidation:
    def test_only_character_messages_allowed(self, client, session):
        chat, _ = _seed_chat_with_char_message(session)
        user_msg = Message(role=MessageRole.USER, content="user text", chat_id=chat.id)
        session.add(user_msg)
        session.commit()
        session.refresh(user_msg)
        resp = client.post(f"/api/v2/chats/{chat.id}/messages/{user_msg.id}/generate-swipe")
        assert resp.status_code == 400

    def test_missing_chat_404(self, client, session):
        chat, msg = _seed_chat_with_char_message(session)
        resp = client.post(f"/api/v2/chats/nope/messages/{msg.id}/generate-swipe")
        assert resp.status_code == 404

    def test_missing_message_404(self, client, session):
        chat, _ = _seed_chat_with_char_message(session)
        resp = client.post(f"/api/v2/chats/{chat.id}/messages/nope/generate-swipe")
        assert resp.status_code == 404

    def test_message_from_other_chat_404(self, client, session):
        chat_a, _ = _seed_chat_with_char_message(session, char_name="A")
        chat_b, msg_b = _seed_chat_with_char_message(session, char_name="B")
        resp = client.post(f"/api/v2/chats/{chat_a.id}/messages/{msg_b.id}/generate-swipe")
        assert resp.status_code == 404


class TestGenerateSwipeDispatch:
    def test_generate_swipe_enqueues_llm_job(self, client, session, monkeypatch):
        chat, msg = _seed_chat_with_char_message(session, content="The first reply")

        enqueue = AsyncMock(return_value=True)
        monkeypatch.setattr("services.job_queue.queue_manager.enqueue", enqueue)
        monkeypatch.setattr("services.llm_config.get_default_llm_model", lambda: "test-model")

        resp = client.post(f"/api/v2/chats/{chat.id}/messages/{msg.id}/generate-swipe")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["job_id"]

        enqueue.assert_awaited_once()
        job = session.get(Job, body["job_id"])
        assert job is not None
        assert job.task_type == "llm"
        assert job.metadata_["is_swipe"] is True
        assert job.metadata_["target_message_id"] == msg.id
        assert job.metadata_["workspace"] == "chat"

    def test_generate_swipe_preserves_agentic_context(self, client, session, monkeypatch):
        """A swipe on an agentic message must mirror the orchestrator tools."""
        chat, msg = _seed_chat_with_char_message(session, content="Agentic reply")
        msg.tool_calls = [{"id": "call_1", "type": "function", "function": {"name": "scene", "arguments": "{}"}}]
        session.add(msg)
        session.commit()

        enqueue = AsyncMock(return_value=True)
        monkeypatch.setattr("services.job_queue.queue_manager.enqueue", enqueue)
        monkeypatch.setattr("services.llm_config.get_default_llm_model", lambda: "test-model")

        resp = client.post(f"/api/v2/chats/{chat.id}/messages/{msg.id}/generate-swipe")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        job = session.get(Job, body["job_id"])
        assert job.task_type == "llm"
        assert job.metadata_["agentic"] is True
        assert job.metadata_["orchestrator_depth"] == 0
        assert job.metadata_["max_agentic_depth"] == (chat.max_agentic_depth or 3)
        assert "tools" in job.workflow
        enqueue.assert_awaited_once()

    def test_generate_swipe_non_agentic_skips_orchestrator(self, client, session, monkeypatch):
        chat, msg = _seed_chat_with_char_message(session, content="Plain reply")

        enqueue = AsyncMock(return_value=True)
        monkeypatch.setattr("services.job_queue.queue_manager.enqueue", enqueue)
        monkeypatch.setattr("services.llm_config.get_default_llm_model", lambda: "test-model")

        resp = client.post(f"/api/v2/chats/{chat.id}/messages/{msg.id}/generate-swipe")
        assert resp.status_code == 200
        job = session.get(Job, resp.json()["job_id"])
        assert job.metadata_.get("agentic") is not True
        assert not job.workflow.get("tools")

    def test_generate_swipe_uses_preceding_messages_as_context(self, client, session, monkeypatch):
        """Context must contain only messages BEFORE the target."""
        char = Character(name="Aria")
        session.add(char)
        session.commit()
        session.refresh(char)
        chat = Chat(name="Swipe Chat", character_id=char.id)
        session.add(chat)
        session.commit()
        session.refresh(chat)
        earlier = Message(role=MessageRole.USER, content="Earlier", chat_id=chat.id)
        session.add(earlier)
        session.commit()
        session.refresh(earlier)
        msg = Message(role=MessageRole.CHAR, content="Target line", chat_id=chat.id)
        session.add(msg)
        session.commit()
        session.refresh(msg)
        later = Message(role=MessageRole.USER, content="Later", chat_id=chat.id)
        session.add(later)
        session.commit()

        enqueue = AsyncMock(return_value=True)
        monkeypatch.setattr("services.job_queue.queue_manager.enqueue", enqueue)
        monkeypatch.setattr("services.llm_config.get_default_llm_model", lambda: "test-model")

        resp = client.post(f"/api/v2/chats/{chat.id}/messages/{msg.id}/generate-swipe")
        assert resp.status_code == 200, resp.text
        job = session.get(Job, resp.json()["job_id"])
        # The workflow's messages array holds the assembled turn context as
        # role/content dicts; the target and any later messages must be absent.
        context_msgs = job.workflow.get("messages", [])
        contents = [m.get("content", "") for m in context_msgs]
        assert msg.content not in contents
        assert "Later" not in contents
        assert "Earlier" in contents