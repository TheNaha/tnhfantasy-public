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

from sqlmodel import Session, select

from core.entities import Chat, Character, Message, MessageRole, Job, JobStatus


def _seed_chat(session: Session, char: Character | None = None) -> Chat:
    chat = Chat(name="Test Chat", character_id=char.id if char else None)
    session.add(chat)
    session.commit()
    session.refresh(chat)
    return chat


def _seed_character_named(session, name, description=""):
    char = Character(name=name, description=description)
    session.add(char)
    session.commit()
    session.refresh(char)
    return char


def _add_message(session, chat, role, content):
    msg = Message(role=role, content=content, chat_id=chat.id)
    session.add(msg)
    session.commit()
    session.refresh(msg)
    return msg


class TestListChatsByCharacter:
    """`GET /api/v2/chats?character_id=…` — the character's own conversations.

    There was no way to get from a character to its chats: the chat list had
    no character filter, so the only route was to read every chat in the
    vault and look.
    """

    def test_the_primary_character_matches(self, client, session):
        char = _seed_character_named(session, "Aria")
        chat = _seed_chat(session, char)
        _seed_chat(session)  # a chat with no character

        resp = client.get(f"/api/v2/chats?character_id={char.id}")
        assert resp.status_code == 200, resp.text
        ids = [c["id"] for c in resp.json()]
        assert chat.id in ids
        assert len(ids) == 1

    def test_the_additional_cast_matches(self, client, session):
        char = _seed_character_named(session, "Borin")
        other = _seed_character_named(session, "Aria")
        chat = _seed_chat(session, other)
        chat.additional_character_ids = [char.id]
        session.add(chat)
        session.commit()

        resp = client.get(f"/api/v2/chats?character_id={char.id}")
        assert resp.status_code == 200, resp.text
        assert [c["id"] for c in resp.json()] == [chat.id]

    def test_a_prefix_of_a_stored_id_does_not_match(self, client, session):
        """The membership test is exact, not a substring match.

        `additional_character_ids` is a JSON array, and SQLAlchemy's
        `.contains()` renders `LIKE '%value%'` on SQLite — a raw substring
        match — while the same call on PostgreSQL's `jsonb` renders the exact
        `@>` operator. The filter casts the array to text and matches the
        QUOTED token instead, so the closing quote is part of the pattern and
        a prefix cannot match.
        """
        char = _seed_character_named(session, "Ceri")
        chat = _seed_chat(session)
        chat.additional_character_ids = [char.id]
        session.add(chat)
        session.commit()

        prefix = char.id[:-4]
        resp = client.get(f"/api/v2/chats?character_id={prefix}")
        assert resp.status_code == 200, resp.text
        assert resp.json() == [], "a prefix of a stored id matched the row"


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

    def test_rollback_does_not_delete_other_branches(self, client, session):
        """Branch copies share chat_id AND created_at, so a rollback anchored on
        the original thread used to delete every branch's messages too."""
        chat = _seed_chat(session)
        t0 = datetime.now(timezone.utc)
        m1 = Message(role=MessageRole.USER, content="Hello", chat_id=chat.id, created_at=t0)
        session.add(m1)
        session.commit()
        session.refresh(m1)

        # An alternate branch forked from m1, with its own reply.
        b1 = Message(
            role=MessageRole.USER, content="Hello", chat_id=chat.id,
            branch_id="branch-alt", branch_name="alt", created_at=t0,
        )
        b2 = Message(
            role=MessageRole.CHAR, content="Different reply", chat_id=chat.id,
            branch_id="branch-alt", branch_name="alt", created_at=t0 + timedelta(minutes=1),
        )
        session.add(b1)
        session.add(b2)
        session.commit()
        session.refresh(b1)
        session.refresh(b2)

        resp = client.post(f"/api/v2/chats/{chat.id}/rollback", json={"message_id": m1.id})
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1  # only m1
        assert session.get(Message, m1.id) is None
        # The unrelated branch survives.
        assert session.get(Message, b1.id) is not None
        assert session.get(Message, b2.id) is not None

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

    def test_idempotency_key_collapses_a_double_submit(
        self, client, session, monkeypatch, tts_capable
    ):
        """The narrator has no client-side guard, so a double click is two jobs.

        `_handle_chat_tts` writes the same `audio_path` onto the same message, so
        the second job's cost is invisible in the UI — which is exactly why this
        needed the opt-in header `POST /{chat_id}/messages` already has.
        """
        chat, msg = self._seed(session)
        enqueue = AsyncMock(return_value=True)
        monkeypatch.setattr("services.job_queue.queue_manager.enqueue", enqueue)

        headers = {"Idempotency-Key": "narrate-once"}
        first = client.post(
            f"/api/v2/chats/{chat.id}/messages/{msg.id}/narrate",
            json={},
            headers=headers,
        )
        assert first.status_code == 200, first.text
        second = client.post(
            f"/api/v2/chats/{chat.id}/messages/{msg.id}/narrate",
            json={},
            headers=headers,
        )
        assert second.status_code == 200, second.text

        # One job, one enqueue, one identical response.
        assert second.json() == first.json()
        assert enqueue.await_count == 1
        jobs = session.exec(select(Job).where(Job.task_type == "tts")).all()
        assert len(jobs) == 1

    def test_a_different_idempotency_key_is_a_second_job(
        self, client, session, monkeypatch, tts_capable
    ):
        """The key must scope to the key, not swallow every narration."""
        chat, msg = self._seed(session)
        enqueue = AsyncMock(return_value=True)
        monkeypatch.setattr("services.job_queue.queue_manager.enqueue", enqueue)

        client.post(
            f"/api/v2/chats/{chat.id}/messages/{msg.id}/narrate",
            json={},
            headers={"Idempotency-Key": "first"},
        )
        client.post(
            f"/api/v2/chats/{chat.id}/messages/{msg.id}/narrate",
            json={},
            headers={"Idempotency-Key": "second"},
        )

        assert enqueue.await_count == 2

    def test_no_key_means_no_dedup(
        self, client, session, monkeypatch, tts_capable
    ):
        """Opt-in, same as `POST /{chat_id}/messages`.

        A default-on guard would collapse every deliberate re-narration a user
        asks for after changing the voice, which is a real action.
        """
        chat, msg = self._seed(session)
        enqueue = AsyncMock(return_value=True)
        monkeypatch.setattr("services.job_queue.queue_manager.enqueue", enqueue)

        for _ in range(2):
            resp = client.post(
                f"/api/v2/chats/{chat.id}/messages/{msg.id}/narrate", json={}
            )
            assert resp.status_code == 200, resp.text

        assert enqueue.await_count == 2

    def test_narrate_with_voice_override(self, client, session, monkeypatch, tts_capable):
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

        # Was `task_type="image"` with an `XTTS_v2` + `SaveAudio` graph — node
        # types that exist in no provider image, submitted to a worker that
        # therefore could not build it. The TTS worker is its own provider
        # capability, so the task type has to say so, or the load balancer offers
        # the job to a provider that cannot serve it.
        enqueue.assert_awaited_once_with(body["job_id"], task_type="tts")
        job = session.get(Job, body["job_id"])
        assert job.task_type == "tts"
        assert job.metadata_["type"] == "tts"
        assert job.metadata_["source"] == "chat_tts"
        assert job.workflow["type"] == "tts"
        # The graph is the one the TTS worker can build: the dedicated Qwen nodes,
        # never the XTTS pair.
        node_types = {n["class_type"] for n in job.workflow["prompt"].values()}
        assert node_types == {"QwenTTSSpeak", "SaveAudio"}
        assert "XTTS_v2" not in node_types
        speak = next(n for n in job.workflow["prompt"].values() if n["class_type"] == "QwenTTSSpeak")
        assert speak["inputs"]["text"] == "Hello, adventurer."

    def test_narrate_refuses_when_no_provider_can_serve_tts(self, client, session):
        """A job accepted here died inside a container on a graph naming a node
        that was never installed. It is refused before a job row exists."""
        chat, msg = self._seed(session)
        resp = client.post(f"/api/v2/chats/{chat.id}/messages/{msg.id}/narrate", json={})
        assert resp.status_code == 400
        body = resp.text.lower()
        assert "tts" in body
        assert "capabilit" in body, "the error should name the missing capability"

    def test_narrate_voice_override_404(self, client, session, tts_capable):
        chat, msg = self._seed(session)
        resp = client.post(
            f"/api/v2/chats/{chat.id}/messages/{msg.id}/narrate",
            json={"voice_id": "missing-voice"},
        )
        assert resp.status_code == 404

    def test_narrate_chat_override_fallback(self, client, session, monkeypatch, tts_capable):
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
        speak = next(
            n for n in job.workflow["prompt"].values()
            if n["class_type"] == "QwenTTSSpeak"
        )
        assert speak["inputs"]["voice"] == "echo_xtts"


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


# ── Message search ──────────────────────────────────────────────────────────

class TestMessageSearch:
    def test_search_messages_by_content(self, client, session):
        chat = _seed_chat(session)
        _add_message(session, chat, MessageRole.USER, "Hello there")
        _add_message(session, chat, MessageRole.CHAR, "Greetings, traveler")
        _add_message(session, chat, MessageRole.USER, "The dragon is here")

        resp = client.get(f"/api/v2/chats/{chat.id}/messages?q=dragon")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert "dragon" in results[0]["content"].lower()

    def test_search_messages_case_insensitive(self, client, session):
        chat = _seed_chat(session)
        _add_message(session, chat, MessageRole.USER, "Hello World")

        resp = client.get(f"/api/v2/chats/{chat.id}/messages?q=hello")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_search_messages_no_match(self, client, session):
        chat = _seed_chat(session)
        _add_message(session, chat, MessageRole.USER, "Hello")

        resp = client.get(f"/api/v2/chats/{chat.id}/messages?q=nonexistent")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_search_messages_empty_query_returns_all(self, client, session):
        chat = _seed_chat(session)
        _add_message(session, chat, MessageRole.USER, "First")
        _add_message(session, chat, MessageRole.CHAR, "Second")

        resp = client.get(f"/api/v2/chats/{chat.id}/messages")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


# ── POST chat/messages with narration disabled ───────────────────────────────

class TestNarrationDisabledDoesNotOrphanTheMessage:
    """The 500 that also left the user's message behind.

    `allow_narration` was checked in the route, *after* `_add_message_prep_sync`
    had already committed the user's message. So asking for narration on a chat
    that has it disabled returned a failure and persisted the message anyway:
    the frontend reads the error as "send failed", the user sends it again, and
    the transcript holds the question twice. The error was also re-wrapped as a
    bare `ComfyError`, which turned a 400 into a 500.
    """

    def _seed_chat_without_narration(self, session: Session) -> Chat:
        chat = Chat(name="No narration", character_id=None, allow_narration=False)
        session.add(chat)
        session.commit()
        session.refresh(chat)
        return chat

    def test_it_is_a_client_error_not_a_500(self, client, session):
        chat = self._seed_chat_without_narration(session)

        resp = client.post(
            f"/api/v2/chats/{chat.id}/messages",
            json={"role": "user", "content": "The door creaks open.", "narrate": True},
        )

        assert resp.status_code == 400, resp.text
        assert "narration" in resp.text.lower()

    def test_the_user_message_is_not_persisted(self, client, session):
        chat = self._seed_chat_without_narration(session)

        client.post(
            f"/api/v2/chats/{chat.id}/messages",
            json={"role": "user", "content": "The door creaks open.", "narrate": True},
        )

        stored = session.exec(
            select(Message).where(Message.chat_id == chat.id)
        ).all()
        assert stored == [], f"the refused message was persisted anyway: {[m.content for m in stored]}"

    def test_a_message_without_narration_still_works(self, client, session):
        """The guard must not swallow ordinary sends."""
        chat = self._seed_chat_without_narration(session)

        resp = client.post(
            f"/api/v2/chats/{chat.id}/messages",
            json={"role": "user", "content": "Hello", "no_reply": True},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["user_message_id"]


class TestContextTraceOnAReply:
    """The exchange record reaches the message a user can read it from.

    The send path is the one that matters: it is where the trace is captured, so
    the test has to go through the HTTP route rather than calling the handler,
    or it would only prove the handler copies what it is handed.
    """

    def test_a_sent_message_stamps_the_trace_on_its_reply(self, client, session, engine, monkeypatch):
        import asyncio

        from core.entities import Message

        char = _seed_character_named(session, "Aria", "A guard.")
        chat = _seed_chat(session, char)
        monkeypatch.setattr("services.job_queue.queue_manager.enqueue", AsyncMock(return_value=True))

        resp = client.post(f"/api/v2/chats/{chat.id}/messages", json={"content": "I knock.", "role": "user"})
        assert resp.status_code == 200, resp.text

        job = session.exec(select(Job).where(Job.task_type == "llm")).all()[0]
        trace = (job.metadata_ or {}).get("context_trace")
        assert trace and trace["v"] == 1
        # The mapping actually applied is recorded, which is the part nobody
        # could otherwise verify from outside the payload.
        assert trace["config"]["narrator_prefix"] == "[Narration]"

        import services.world_integration_service as wis

        asyncio.run(wis._handle_chat_reply({
            "id": job.id,
            "metadata": job.metadata_ or {},
            "outputs": [{"role": "assistant", "content": "The door opens."}],
        }))

        # Same session the routes write through, which is what the client
        # fixture overrides.
        reply = session.exec(
            select(Message)
            .where(Message.chat_id == chat.id)
            .order_by(Message.created_at.desc())
        ).all()[0]
        stamped = reply.message_metadata.get("context_trace")
        assert stamped and stamped["v"] == 1
        assert stamped["turns"][-1]["role"] == "user"

    def test_a_swipe_also_stamps_a_trace(self, client, session, engine, monkeypatch):

        char = _seed_character_named(session, "Aria", "A guard.")
        chat = _seed_chat(session, char)
        _add_message(session, chat, MessageRole.USER, "Is it open?")
        reply = _add_message(session, chat, MessageRole.CHAR, "The door is shut.")
        monkeypatch.setattr("services.job_queue.queue_manager.enqueue", AsyncMock(return_value=True))

        resp = client.post(f"/api/v2/chats/{chat.id}/messages/{reply.id}/generate-swipe", json={})
        assert resp.status_code == 200, resp.text

        # Read through the response rather than the session: the route commits on
        # its own, and re-querying is more brittle than asserting what came back.
        assert "job_id" in resp.json()
        jobs = session.exec(select(Job).where(Job.task_type == "llm")).all()
        # Only when the turn was agentic does the swipe carry budgets, but the
        # trace itself is always there — it describes the conversation the
        # alternate is generated from.
        assert (jobs[-1].metadata_ or {}).get("context_trace", {}).get("v") == 1
