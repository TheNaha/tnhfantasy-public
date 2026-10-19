"""Four roleplay features were wired to nothing, and the tests could not see it.

Each test here pins a specific defect that shipped green, because in every case
the existing test either exercised the route directly (bypassing the service
that dropped the data) or hand-built the input that the real caller could never
produce.

  - `ChapterUpdate`: a PUT of `{"content": ...}` deserialised into the
    `StoryChapter` *table* model, so `beats` arrived as `[]` and the autosave
    wiped the chapter's beat list every two seconds of typing.
  - the job event's `metadata`: the completion payload was merged shallowly, so
    an `event_extra` carrying a three-key `metadata` replaced the job's whole
    dict. Group-chat speaker attribution, swipe alternates and the agentic depth
    stamp all read from the far side of that merge.
  - `UpdateChatRequest.additional_character_ids`: absent from the model, so
    pydantic dropped the group roster on the floor.
  - `_handle_narrator`: the agentic `narrate_scene` tool inserted inline *and*
    emitted `type: "narrator"`, so the same paragraph was persisted twice.
"""

from __future__ import annotations

import uuid

import pytest

from api.routes.world_vault.chats import CreateChatRequest, UpdateChatRequest
from api.routes.world_vault.stories import ChapterUpdate
from core.entities import Character, Message, MessageKind, MessageRole, Story, StoryChapter
from services.job_service import JobService


# --------------------------------------------------------------------------
# Chapter autosave must not destroy the beat list
# --------------------------------------------------------------------------


class TestChapterAutosavePreservesBeats:
    def test_a_content_only_update_never_sends_beats(self):
        """The shape the editor's autosave actually sends.

        Deserialised into the table model this produced `beats == []`, and
        `if chapter_update.beats is not None` read that as an instruction to
        clear them. `StoryChapter` declares `table=True`, which is why FastAPI
        performed no pydantic validation and every absent column came back as
        its default.
        """
        payload = {"content": "the user typed this"}
        update = ChapterUpdate(**payload)

        assert update.content == "the user typed this"
        assert update.beats is None, (
            "an absent field must be absent, not empty: the handler treats "
            "None as 'leave alone' and [] as 'clear'"
        )

    def test_beats_are_still_accepted_when_the_caller_sends_them(self):
        beats = [{"role": "user", "content": "a beat"}]
        update = ChapterUpdate(content="x", beats=beats)
        assert update.beats == beats

    def test_the_model_is_not_a_table_model(self):
        """The structural reason, so the fix cannot be reverted by substitution."""
        assert not getattr(ChapterUpdate, "model_config", {}).get("table", False)
        assert getattr(StoryChapter, "model_config", {}).get("table", False) is True

    def test_a_live_autosave_keeps_the_beats(self, client, session):
        story = Story(id=str(uuid.uuid4()), title="A story")
        session.add(story)
        session.commit()

        beats = [{"id": "b1", "role": "user", "content": "a beat that matters"}]
        chapter = StoryChapter(
            id=str(uuid.uuid4()), story_id=story.id, content="first draft", beats=beats
        )
        session.add(chapter)
        session.commit()
        chapter_id, story_id = chapter.id, story.id

        # Exactly what useUpdateChapter mutates on its 2s debounce.
        response = client.put(
            f"/api/v2/stories/{story_id}/chapters/{chapter_id}",
            json={"content": "second draft"},
        )
        assert response.status_code == 200, response.text

        session.expire_all()
        reloaded = session.get(StoryChapter, chapter_id)
        assert reloaded.content == "second draft"
        assert reloaded.beats == beats, "the autosave cleared the chapter's beat list"


# --------------------------------------------------------------------------
# The completion event must not drop the job's metadata
# --------------------------------------------------------------------------


class TestJobEventMetadataIsMerged:
    @staticmethod
    def _payload(job_metadata, event_extra):
        return JobService._build_event_payload({"id": "j1", "metadata": job_metadata}, event_extra)

    def test_extras_add_to_the_job_metadata(self):
        payload = self._payload(
            {"chat_id": "c1", "character_id": "char-2", "orchestrator_depth": 1},
            {"metadata": {"type": "chat_reply", "regenerated": True}},
        )
        metadata = payload["metadata"]

        # What the shallow merge destroyed. The world-integration handler reads
        # all of these from the event, and each one had a live symptom:
        # character_id -> every group-chat bubble attributed to the primary
        # character; orchestrator_depth -> never stamped on the message.
        assert metadata["character_id"] == "char-2"
        assert metadata["orchestrator_depth"] == 1
        assert metadata["type"] == "chat_reply"
        assert metadata["regenerated"] is True
        assert metadata["chat_id"] == "c1"

    def test_swipe_flags_survive_to_the_event(self):
        """`is_swipe`/`target_message_id` made the alternate branch unreachable.

        "Generate an alternate reply" appended a new message instead of
        creating an alternate, while the UI reported success.
        """
        payload = self._payload(
            {"chat_id": "c1", "is_swipe": True, "target_message_id": "m9"},
            {"metadata": {"type": "chat_reply"}},
        )
        assert payload["metadata"]["is_swipe"] is True
        assert payload["metadata"]["target_message_id"] == "m9"

    def test_the_caller_can_still_correct_a_value(self):
        payload = self._payload(
            {"chat_id": "stale", "keep": "me"}, {"metadata": {"chat_id": "fresh"}}
        )
        assert payload["metadata"]["chat_id"] == "fresh"
        assert payload["metadata"]["keep"] == "me"

    def test_suggestion_flag_survives(self):
        payload = self._payload(
            {"chat_id": "c1", "is_suggestion": True}, {"metadata": {"type": "suggest_reply"}}
        )
        assert payload["metadata"]["is_suggestion"] is True

    def test_no_metadata_key_means_no_metadata_key(self):
        payload = self._payload({"chat_id": "c1"}, {"type": "narrator"})
        assert payload["metadata"] == {"chat_id": "c1"}
        assert payload["type"] == "narrator"

    def test_a_job_with_no_metadata_still_works(self):
        payload = self._payload(None, {"metadata": {"type": "narrator"}})
        assert payload["metadata"] == {"type": "narrator"}

    def test_top_level_extras_still_win(self):
        payload = self._payload({"chat_id": "c1"}, {"status": "COMPLETED"})
        assert payload["status"] == "COMPLETED"
        assert payload["id"] == "j1"


# --------------------------------------------------------------------------
# The group-chat roster must be writable
# --------------------------------------------------------------------------


class TestGroupChatRosterIsWritable:
    def test_the_field_is_not_dropped_by_pydantic(self):
        """`extra='ignore'` is why this failed silently and looked like a UI bug.

        The panel PATCHed the field, the mutation applied an optimistic cache
        update, so the add/remove buttons worked right up until the next
        refetch and then the roster vanished.
        """
        dumped = UpdateChatRequest(
            name="x", additional_character_ids=["a", "b"]
        ).model_dump(exclude_unset=True)
        assert dumped["additional_character_ids"] == ["a", "b"]

    def test_create_accepts_it_too(self):
        assert CreateChatRequest(additional_character_ids=["a"]).additional_character_ids == ["a"]

    def test_absent_means_absent_not_empty(self):
        assert "additional_character_ids" not in UpdateChatRequest(name="x").model_dump(
            exclude_unset=True
        )

    def test_the_roster_survives_a_real_patch(self, client, session):
        from core.entities import Chat

        primary = Character(id=str(uuid.uuid4()), name="Primary")
        extra = Character(id=str(uuid.uuid4()), name="Extra")
        session.add(primary)
        session.add(extra)
        session.commit()

        chat = Chat(id=str(uuid.uuid4()), name="Group", character_id=primary.id)
        session.add(chat)
        session.commit()
        chat_id, extra_id = chat.id, extra.id

        response = client.patch(
            f"/api/v2/chats/{chat_id}", json={"additional_character_ids": [extra_id]}
        )
        assert response.status_code == 200, response.text

        session.expire_all()
        assert session.get(Chat, chat_id).additional_character_ids == [extra_id]

        # And clearing it, which is the other half of the toggle.
        response = client.patch(
            f"/api/v2/chats/{chat_id}", json={"additional_character_ids": []}
        )
        assert response.status_code == 200, response.text
        session.expire_all()
        assert session.get(Chat, chat_id).additional_character_ids == []

    def test_the_primary_character_is_rejected_as_a_roster_member(self, client, session):
        from core.entities import Chat

        primary = Character(id=str(uuid.uuid4()), name="Primary")
        session.add(primary)
        session.commit()
        chat = Chat(id=str(uuid.uuid4()), name="Group", character_id=primary.id)
        session.add(chat)
        session.commit()

        response = client.patch(
            f"/api/v2/chats/{chat.id}", json={"additional_character_ids": [primary.id]}
        )
        assert response.status_code == 400, response.text

    def test_a_dangling_roster_id_is_rejected_rather_than_silently_dropped(self, client, session):
        """A missing speaker is not a rendering problem.

        It silently drops that character from the prompt context, so the failure
        would surface as "the character I added just never replies".
        """
        from core.entities import Chat

        chat = Chat(id=str(uuid.uuid4()), name="Group")
        session.add(chat)
        session.commit()

        response = client.patch(
            f"/api/v2/chats/{chat.id}",
            json={"additional_character_ids": [str(uuid.uuid4())]},
        )
        assert response.status_code == 404, response.text


# --------------------------------------------------------------------------
# The narrator is persisted exactly once
# --------------------------------------------------------------------------


class TestNarratorIsPersistedOnce:
    @staticmethod
    def _chat(session) -> str:
        from core.entities import Chat

        chat = Chat(id=str(uuid.uuid4()), name="A chat")
        session.add(chat)
        session.commit()
        return chat.id

    @pytest.mark.asyncio
    async def test_the_completion_handler_writes_exactly_one_message(self, session):
        """`_handle_narrator` is the single writer, and it writes one row.

        The agentic `narrate_scene` tool used to insert a Message inline *and*
        emit `type: "narrator"`, which routes here — so the same paragraph
        landed twice, once per path. The button path never inserted inline,
        which is why the two entry points disagreed and neither looked wrong.
        """
        from sqlmodel import select as sa_select

        from services.world_integration_service import _handle_narrator

        chat_id = self._chat(session)
        event = {
            "id": "job-1",
            "metadata": {"chat_id": chat_id, "narration_job_id": "job-1"},
            "content": "Rain hammers the roof of the station.",
        }

        await _handle_narrator(event)

        rows = session.exec(sa_select(Message).where(Message.chat_id == chat_id)).all()
        assert len(rows) == 1
        assert rows[0].kind == MessageKind.NARRATOR
        assert rows[0].role == MessageRole.SYSTEM
        assert rows[0].message_metadata.get("narration_job_id") == "job-1"

    @pytest.mark.asyncio
    async def test_chat_id_can_come_from_the_top_level_too(self, session):
        """Both the button path and the tool path put `chat_id` in metadata;
        the tool path also sets it at the top level. Reading only one of them
        is how a narration ends up with no chat and is silently dropped."""
        from sqlmodel import select as sa_select

        from services.world_integration_service import _handle_narrator

        chat_id = self._chat(session)
        await _handle_narrator(
            {"id": "job-2", "chat_id": chat_id, "content": "A door opens."}
        )

        rows = session.exec(sa_select(Message).where(Message.chat_id == chat_id)).all()
        assert len(rows) == 1

