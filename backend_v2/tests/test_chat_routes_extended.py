"""Extended integration tests for chat World Vault routes.

Covers routes that were previously untested:
  - DELETE/PATCH message
  - PATCH message/pin
  - POST message/swipe, message/generate-swipe
  - POST chat/rollback
  - POST chat/narrate
  - POST chat/scene
"""

from unittest.mock import AsyncMock
from datetime import datetime, timezone, timedelta

from sqlmodel import Session

from core.entities import Chat, Character, Message, MessageRole, Job, JobStatus


def _seed_chat(session: Session, char: Character | None = None) -> Chat:
    chat = Chat(name="Test Chat", character_id=char.id if char else None)
    session.add(chat)
    session.commit()
    session.refresh(chat)
    return chat


def _add_message(session, chat, role, content):
    msg = Message(role=role, content=content, chat_id=chat.id)
    session.add(msg)
    session.commit()
    session.refresh(msg)
    return msg


# ── DELETE message ───────────────────────────────────────────────────────────

class TestDeleteMessage:
    def test_delete_message(self, client, session):
        chat = _seed_chat(session)
        msg = _add_message(session, chat, MessageRole.USER, "Hello")
        resp = client.delete(f"/api/v2/chats/{chat.id}/messages/{msg.id}")
        assert resp.status_code == 200
        assert resp.json()["message"] == "Message deleted"
        assert session.get(Message, msg.id) is None

    def test_delete_message_404(self, client, session):
        chat = _seed_chat(session)
        resp = client.delete(f"/api/v2/chats/{chat.id}/messages/nonexistent")
        assert resp.status_code == 404

    def test_delete_message_wrong_chat(self, client, session):
        chat1 = _seed_chat(session)
        chat2 = _seed_chat(session)
        msg = _add_message(session, chat1, MessageRole.USER, "Hi")
        resp = client.delete(f"/api/v2/chats/{chat2.id}/messages/{msg.id}")
        assert resp.status_code == 404


# ── PATCH message (edit) ─────────────────────────────────────────────────────

class TestEditMessage:
    def test_edit_message(self, client, session):
        chat = _seed_chat(session)
        msg = _add_message(session, chat, MessageRole.USER, "Old content")
        resp = client.patch(f"/api/v2/chats/{chat.id}/messages/{msg.id}", json={"content": "New content"})
        assert resp.status_code == 200
        updated = resp.json()
        assert updated["content"] == "New content"
        assert session.get(Message, msg.id).content == "New content"

    def test_edit_message_404(self, client, session):
        chat = _seed_chat(session)
        resp = client.patch(f"/api/v2/chats/{chat.id}/messages/nonexistent", json={"content": "x"})
        assert resp.status_code == 404

    def test_edit_message_system_rejected(self, client, session):
        chat = _seed_chat(session)
        msg = _add_message(session, chat, MessageRole.SYSTEM, "sys msg")
        resp = client.patch(f"/api/v2/chats/{chat.id}/messages/{msg.id}", json={"content": "edited"})
        assert resp.status_code == 400


# ── PATCH message/pin ────────────────────────────────────────────────────────

class TestPinMessage:
    def test_pin_message(self, client, session):
        chat = _seed_chat(session)
        msg = _add_message(session, chat, MessageRole.CHAR, "Pin me")
        resp = client.patch(f"/api/v2/chats/{chat.id}/messages/{msg.id}/pin", json={"pinned": True})
        assert resp.status_code == 200
        assert resp.json()["pinned"] is True
        assert session.get(Message, msg.id).pinned is True

    def test_unpin_message(self, client, session):
        chat = _seed_chat(session)
        msg = Message(role=MessageRole.CHAR, content="x", chat_id=chat.id, pinned=True)
        session.add(msg)
        session.commit()
        resp = client.patch(f"/api/v2/chats/{chat.id}/messages/{msg.id}/pin", json={"pinned": False})
        assert resp.status_code == 200
        assert resp.json()["pinned"] is False

    def test_pin_message_404(self, client, session):
        chat = _seed_chat(session)
        resp = client.patch(f"/api/v2/chats/{chat.id}/messages/nonexistent/pin", json={"pinned": True})
        assert resp.status_code == 404


# ── POST message/swipe ───────────────────────────────────────────────────────

class TestSwipeMessage:
    def _seed_alternates(self, session, chat) -> Message:
        msg = Message(
            role=MessageRole.CHAR,
            content="alt0",
            chat_id=chat.id,
            message_metadata={"alternates": ["alt0", "alt1", "alt2"], "active_index": 0},
        )
        session.add(msg)
        session.commit()
        session.refresh(msg)
        return msg

    def test_swipe_right(self, client, session):
        chat = _seed_chat(session)
        msg = self._seed_alternates(session, chat)
        resp = client.post(f"/api/v2/chats/{chat.id}/messages/{msg.id}/swipe", json={"direction": "right"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["content"] == "alt1"
        assert body["message_metadata"]["active_index"] == 1
        assert body["message_metadata"]["alternates"] == ["alt0", "alt1", "alt2"]

    def test_swipe_right_wraps(self, client, session):
        chat = _seed_chat(session)
        msg = self._seed_alternates(session, chat)
        # Move to last alternate first
        client.post(f"/api/v2/chats/{chat.id}/messages/{msg.id}/swipe", json={"direction": "right"})
        client.post(f"/api/v2/chats/{chat.id}/messages/{msg.id}/swipe", json={"direction": "right"})
        # Now at index 2; swiping right should wrap to 0
        resp = client.post(f"/api/v2/chats/{chat.id}/messages/{msg.id}/swipe", json={"direction": "right"})
        assert resp.status_code == 200
        assert resp.json()["content"] == "alt0"
        assert resp.json()["message_metadata"]["active_index"] == 0

    def test_swipe_left(self, client, session):
        chat = _seed_chat(session)
        msg = self._seed_alternates(session, chat)
        # Move right first
        client.post(f"/api/v2/chats/{chat.id}/messages/{msg.id}/swipe", json={"direction": "right"})
        # Now swipe left back to 0
        resp = client.post(f"/api/v2/chats/{chat.id}/messages/{msg.id}/swipe", json={"direction": "left"})
        assert resp.status_code == 200
        assert resp.json()["content"] == "alt0"
        assert resp.json()["message_metadata"]["active_index"] == 0

    def test_swipe_select(self, client, session):
        chat = _seed_chat(session)
        msg = self._seed_alternates(session, chat)
        resp = client.post(f"/api/v2/chats/{chat.id}/messages/{msg.id}/swipe", json={"direction": "select", "index": 2})
        assert resp.status_code == 200
        assert resp.json()["content"] == "alt2"
        assert resp.json()["message_metadata"]["active_index"] == 2

    def test_swipe_invalid_direction(self, client, session):
        chat = _seed_chat(session)
        msg = self._seed_alternates(session, chat)
        resp = client.post(f"/api/v2/chats/{chat.id}/messages/{msg.id}/swipe", json={"direction": "up"})
        assert resp.status_code == 400

    def test_swipe_invalid_index(self, client, session):
        chat = _seed_chat(session)
        msg = self._seed_alternates(session, chat)
        resp = client.post(f"/api/v2/chats/{chat.id}/messages/{msg.id}/swipe", json={"direction": "select", "index": 5})
        assert resp.status_code == 400

    def test_swipe_non_char_rejected(self, client, session):
        chat = _seed_chat(session)
        msg = _add_message(session, chat, MessageRole.USER, "user text")
        resp = client.post(f"/api/v2/chats/{chat.id}/messages/{msg.id}/swipe", json={"direction": "right"})
        assert resp.status_code == 400

    def test_swipe_404(self, client, session):
        chat = _seed_chat(session)
        resp = client.post(f"/api/v2/chats/{chat.id}/messages/nonexistent/swipe", json={"direction": "right"})
        assert resp.status_code == 404


# ── POST chat/rollback ────────────────────────────────────────────────────────

class TestRollbackChat:
    def test_rollback(self, client, session):
        chat = _seed_chat(session)
        t0 = datetime.now(timezone.utc)
        m1 = Message(role=MessageRole.USER, content="Hello", chat_id=chat.id, created_at=t0)
        session.add(m1)
        session.commit()
        session.refresh(m1)
        m2 = Message(role=MessageRole.CHAR, content="Hi back", chat_id=chat.id, created_at=t0 + timedelta(minutes=1))
        session.add(m2)
        session.commit()
        session.refresh(m2)
        m3 = Message(role=MessageRole.USER, content="Second", chat_id=chat.id, created_at=t0 + timedelta(minutes=2))
        session.add(m3)
        session.commit()
        session.refresh(m3)
        # Rollback to m2: deletes m2 (anchor) and m3, keeps m1
        resp = client.post(f"/api/v2/chats/{chat.id}/rollback", json={"message_id": m2.id})
        assert resp.status_code == 200
        body = resp.json()
        assert body["deleted"] == 2  # m2 and m3 removed
        assert body["kept"] == 1     # m1 kept
        assert session.get(Message, m1.id) is not None
        assert session.get(Message, m2.id) is None
        assert session.get(Message, m3.id) is None

    def test_rollback_404(self, client, session):
        chat = _seed_chat(session)
        resp = client.post(f"/api/v2/chats/{chat.id}/rollback", json={"message_id": "nonexistent"})
        assert resp.status_code == 404

    def test_rollback_chat_404(self, client, session):
        resp = client.post("/api/v2/chats/nonexistent/rollback", json={"message_id": "x"})
        assert resp.status_code == 404


# ── POST chat/scene ──────────────────────────────────────────────────────────

class TestGenerateScene:
    def test_scene_queues_llm_job(self, client, session, monkeypatch):
        char = Character(name="Aria", checkpoint="aria_ckpt.safetensors")
        session.add(char)
        session.commit()
        session.refresh(char)
        chat = _seed_chat(session, char)
        _add_message(session, chat, MessageRole.USER, "Let's go on an adventure")
        _add_message(session, chat, MessageRole.CHAR, "I'm ready!")

        from services.model_availability_service import ModelAvailabilityService
        monkeypatch.setattr(
            ModelAvailabilityService, "resolve_checkpoint", lambda self, preferred=None: "aria_ckpt.safetensors"
        )
        monkeypatch.setattr("services.llm_config.get_default_llm_model", lambda: "test-model")
        enqueue = AsyncMock(return_value=True)
        monkeypatch.setattr("services.job_queue.queue_manager.enqueue", enqueue)

        resp = client.post(f"/api/v2/chats/{chat.id}/scene")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "queued"
        assert body["job_id"]

        enqueue.assert_awaited_once()
        job = session.get(Job, body["job_id"])
        assert job.task_type == "llm"
        assert job.metadata_["type"] == "chat_reply"
        assert job.metadata_["workspace"] == "roleplay"
        assert job.metadata_["source"] == "scene_prompt"
        assert job.metadata_["agentic"] is True

    def test_scene_no_messages_400(self, client, session):
        char = Character(name="Aria")
        session.add(char)
        session.commit()
        session.refresh(char)
        chat = _seed_chat(session, char)
        resp = client.post(f"/api/v2/chats/{chat.id}/scene")
        assert resp.status_code == 400

    def test_scene_chat_404(self, client, session):
        resp = client.post("/api/v2/chats/nonexistent/scene")
        assert resp.status_code == 404


# ── POST chat/impersonate ────────────────────────────────────────────────────

class TestImpersonate:
    """Regression coverage for the Batch 1.1 fix: impersonate must not
    NameError, must queue an LLM job (task_type 'llm'), and must tag the
    job as impersonation with the optional hint preserved."""

    def _seed(self, session):
        char = Character(name="Aria")
        session.add(char)
        session.commit()
        session.refresh(char)
        chat = _seed_chat(session, char)
        _add_message(session, chat, MessageRole.USER, "Hello Aria")
        _add_message(session, chat, MessageRole.CHAR, "Hello there, friend")
        return char, chat

    def test_impersonate_queues_llm_job(self, client, session, monkeypatch):
        char, chat = self._seed(session)
        monkeypatch.setattr("services.llm_config.get_default_llm_model", lambda: "test-model")
        enqueue = AsyncMock(return_value=True)
        monkeypatch.setattr("services.job_queue.queue_manager.enqueue", enqueue)

        resp = client.post(f"/api/v2/chats/{chat.id}/impersonate", json={"hint": "ask about the storm"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["job_id"]

        enqueue.assert_awaited_once_with(body["job_id"], task_type="llm")
        job = session.get(Job, body["job_id"])
        assert job.task_type == "llm"
        assert job.metadata_["is_impersonation"] is True
        assert job.metadata_["hint"] == "ask about the storm"
        # The roleplay voice prompt must reference the human (persona) and the char name
        system = job.workflow["messages"][0]["content"]
        assert "Aria" in system
        assert "human participant" in system

    def test_impersonate_without_hint(self, client, session, monkeypatch):
        _, chat = self._seed(session)
        monkeypatch.setattr("services.llm_config.get_default_llm_model", lambda: "test-model")
        enqueue = AsyncMock(return_value=True)
        monkeypatch.setattr("services.job_queue.queue_manager.enqueue", enqueue)

        resp = client.post(f"/api/v2/chats/{chat.id}/impersonate", json={})
        assert resp.status_code == 200, resp.text
        job = session.get(Job, resp.json()["job_id"])
        assert job.metadata_["is_impersonation"] is True
        assert "hint" not in job.metadata_

    def test_impersonate_chat_404(self, client, session):
        resp = client.post("/api/v2/chats/nonexistent/impersonate", json={"hint": "x"})
        assert resp.status_code == 404


# ── POST chat/messages/{id}/narrate ──────────────────────────────────────────

class TestNarrateMessage:
    def _seed(self, session):
        char = Character(name="Aria")
        session.add(char)
        session.commit()
        session.refresh(char)
        chat = _seed_chat(session, char)
        msg = _add_message(session, chat, MessageRole.CHAR, "Hello, adventurer.")
        return chat, msg

    def test_narrate_with_voice_override(self, client, session, monkeypatch):
        from core.entities import VoiceModel
        voice = VoiceModel(name="Midnight", voice_profile="midnight_xtts", language="en")
        session.add(voice)
        session.commit()
        session.refresh(voice)
        chat, msg = self._seed(session)

        enqueue = AsyncMock(return_value=True)
        monkeypatch.setattr("services.job_queue.queue_manager.enqueue", enqueue)

        resp = client.post(
            f"/api/v2/chats/{chat.id}/messages/{msg.id}/narrate",
            json={"voice_id": voice.id},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["job_id"]

        enqueue.assert_awaited_once_with(body["job_id"], task_type="image")
        job = session.get(Job, body["job_id"])
        assert job.task_type == "image"
        assert job.metadata_["type"] == "tts"
        assert job.metadata_["source"] == "chat_tts"
        assert job.workflow["prompt"]["3"]["inputs"]["text"] == "Hello, adventurer."

    def test_narrate_voice_override_404(self, client, session, monkeypatch):
        chat, msg = self._seed(session)
        resp = client.post(
            f"/api/v2/chats/{chat.id}/messages/{msg.id}/narrate",
            json={"voice_id": "missing-voice"},
        )
        assert resp.status_code == 404

    def test_narrate_chat_override_fallback(self, client, session, monkeypatch):
        from core.entities import VoiceModel
        voice = VoiceModel(name="Echo", voice_profile="echo_xtts", language="en")
        session.add(voice)
        session.commit()
        session.refresh(voice)
        chat, msg = self._seed(session)
        chat.tts_voice_id = voice.id
        session.add(chat)
        session.commit()

        enqueue = AsyncMock(return_value=True)
        monkeypatch.setattr("services.job_queue.queue_manager.enqueue", enqueue)

        resp = client.post(f"/api/v2/chats/{chat.id}/messages/{msg.id}/narrate", json={})
        assert resp.status_code == 200, resp.text
        job = session.get(Job, resp.json()["job_id"])
        assert job.metadata_["voice_profile"] == "echo_xtts"
        assert job.workflow["prompt"]["3"]["inputs"]["voice"] == "echo_xtts"


# ── list_chat_jobs ───────────────────────────────────────────────────────────

class TestListChatJobs:
    def test_lists_jobs_for_chat(self, client, session):
        chat = _seed_chat(session)
        job = Job(
            task_type="llm",
            status=JobStatus.COMPLETED,
            provider_id="p1",
            metadata_={"chat_id": chat.id, "type": "chat_reply"},
            workflow={"type": "chat_reply"},
        )
        session.add(job)
        session.commit()

        resp = client.get(f"/api/v2/chats/{chat.id}/jobs")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["id"] == job.id

    def test_ignores_jobs_for_other_chats(self, client, session):
        chat = _seed_chat(session)
        other = _seed_chat(session)
        job = Job(
            task_type="llm",
            status=JobStatus.COMPLETED,
            provider_id="p1",
            metadata_={"chat_id": other.id},
        )
        session.add(job)
        session.commit()

        resp = client.get(f"/api/v2/chats/{chat.id}/jobs")
        assert resp.status_code == 200
        assert resp.json() == []
