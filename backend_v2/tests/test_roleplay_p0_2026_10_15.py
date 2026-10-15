"""Regression tests for the three roleplay P0s found in the 2026-10-15 review.

Each test was written against the defect and verified to fail before the fix.
The common thread is that all three were invisible in normal use: the two
budget sliders looked live, the narration audio vanished only after an
unrelated edit, and deleting a row left no trace that anything had been left
behind.
"""

import pytest
from sqlmodel import select

from core.entities import (
    Asset,
    Chat,
    GraphLayout,
    Message,
    Story,
    StoryBeat,
    StoryChapter,
    StoryChapterRevision,
)
from infrastructure.repositories.story_beat_repo import StoryBeatRepository


# ---------------------------------------------------------------------------
# P0-1: the per-chat agentic budgets could never be set
# ---------------------------------------------------------------------------


class TestChatAgenticBudgetsAreWritable:
    """`UpdateChatRequest` never declared `max_agentic_images` /
    `max_agentic_narrations`, so pydantic's `extra='ignore'` dropped them.

    The columns, the migrations and the budget reader were all in place, and
    `ChatContextPanel` PATCHed exactly these keys with an optimistic cache
    update — so the sliders rendered, moved, and looked saved. Every refetch
    reverted them and the chat ran on the global defaults.
    """

    def test_the_update_schema_declares_both_budgets(self):
        from api.routes.world_vault.chats import UpdateChatRequest

        fields = UpdateChatRequest.model_fields
        assert "max_agentic_images" in fields
        assert "max_agentic_narrations" in fields

    def test_the_create_schema_declares_both_budgets(self):
        """A chat that never set a budget could not be given one without a PUT."""
        from api.routes.world_vault.chats import CreateChatRequest

        fields = CreateChatRequest.model_fields
        assert "max_agentic_images" in fields
        assert "max_agentic_narrations" in fields

    def test_patch_persists_the_image_budget(self, client, session):
        chat_id = client.post("/api/v2/chats", json={"name": "C"}).json()["id"]

        response = client.patch(
            f"/api/v2/chats/{chat_id}", json={"max_agentic_images": 5}
        )
        assert response.status_code == 200, response.text

        session.expire_all()
        assert session.get(Chat, chat_id).max_agentic_images == 5

    def test_patch_persists_the_narration_budget(self, client, session):
        chat_id = client.post("/api/v2/chats", json={"name": "C"}).json()["id"]

        response = client.patch(
            f"/api/v2/chats/{chat_id}", json={"max_agentic_narrations": 0}
        )
        assert response.status_code == 200, response.text

        session.expire_all()
        # 0 is "off", not "unset" — the assertion that matters is that it is 0
        # and not the column default, since an ignored field leaves it None and
        # the agentic gate reads `0` and `None` differently.
        assert session.get(Chat, chat_id).max_agentic_narrations == 0

    def test_a_refetch_reports_the_budget_it_stored(self, client):
        """The round trip the optimistic update was hiding."""
        chat_id = client.post("/api/v2/chats", json={"name": "C"}).json()["id"]
        client.patch(f"/api/v2/chats/{chat_id}", json={"max_agentic_images": 7})

        assert client.get(f"/api/v2/chats/{chat_id}").json()["max_agentic_images"] == 7


# ---------------------------------------------------------------------------
# P0-2: story narration audio was written to the JSON array, not the rows
# ---------------------------------------------------------------------------


class TestStoryTtsWritesABeatRow:
    """`_handle_story_tts` assigned `chapter.beats` directly.

    Beats became rows in migration 095, with `sync_from_rows` documented as the
    single writer of both the rows and the JSON. A TTS beat that was never
    inserted as a row therefore stopped existing the next time anything else
    touched that chapter — the audio was there when it was rendered and gone
    after an unrelated continuation, with no error either way.
    """

    @staticmethod
    def _chapter(session, story_id: str) -> StoryChapter:
        chapter = StoryChapter(story_id=story_id, chapter_number=1, title="C1")
        session.add(chapter)
        session.commit()
        session.refresh(chapter)
        return chapter

    @staticmethod
    async def _handle(session, story_id: str, chapter_id: str, audio_path: str):
        from services import world_integration_service as wis

        return await wis._handle_story_tts(
            {
                "id": "job-1",
                "metadata": {"story_id": story_id, "chapter_id": chapter_id},
                "outputs": [{"relative_path": audio_path}],
            },
            session=session,
        )

    @pytest.mark.asyncio
    async def test_the_narration_lands_as_a_row(self, session):
        story = Story(title="S")
        session.add(story)
        session.commit()
        chapter = self._chapter(session, story.id)

        await self._handle(session, story.id, chapter.id, "story_tts/s/c/1.wav")

        rows = session.exec(
            select(StoryBeat).where(StoryBeat.chapter_id == chapter.id)
        ).all()
        tts_rows = [r for r in rows if r.role == "tts"]
        assert len(tts_rows) == 1
        assert tts_rows[0].audio_path == "story_tts/s/c/1.wav"
        assert tts_rows[0].tts_source_job_id == "job-1"

    @pytest.mark.asyncio
    async def test_a_later_beat_write_does_not_erase_the_audio(self, session):
        """The defect itself: the audio vanished on the next unrelated edit.

        The trigger has to be `append_beat` and not a bare repo append —
        `append_beat` is what calls `sync_from_rows`, and `sync_from_rows` is
        what rebuilds the JSON array from the rows. Anything that skips it leaves
        the old JSON in place and would pass even against the broken handler.
        """
        from api.routes.world_vault.stories import append_beat

        story = Story(title="S")
        session.add(story)
        session.commit()
        chapter = self._chapter(session, story.id)

        await self._handle(session, story.id, chapter.id, "story_tts/s/c/1.wav")

        # What any later continuation or hand-entered beat does.
        append_beat(chapter, session, role="narrator", content="Then…")

        session.expire_all()
        refreshed = session.get(StoryChapter, chapter.id)
        audio = [b for b in (refreshed.beats or []) if b.get("role") == "tts"]
        assert len(audio) == 1
        assert audio[0]["audio_path"] == "story_tts/s/c/1.wav"

    @pytest.mark.asyncio
    async def test_re_narration_replaces_rather_than_stacks(self, session):
        story = Story(title="S")
        session.add(story)
        session.commit()
        chapter = self._chapter(session, story.id)

        await self._handle(session, story.id, chapter.id, "a.wav")
        await self._handle(session, story.id, chapter.id, "b.wav")

        session.expire_all()
        rows = [
            r
            for r in session.exec(
                select(StoryBeat).where(StoryBeat.chapter_id == chapter.id)
            ).all()
            if r.role == "tts"
        ]
        assert len(rows) == 1
        assert rows[0].audio_path == "b.wav"


# ---------------------------------------------------------------------------
# P0-3: `scrub_entity_references` had no `chat` or `story` branch
# ---------------------------------------------------------------------------


class TestScrubCoversChatAndStory:
    """Both delete routes called the scrubber with a kind it did not handle.

    The `if/elif` chain fell through, returned having done nothing, and raised
    nothing — so deleting a story left its beats, revisions, asset tags and
    graph node behind, and nothing anywhere recorded that it had.
    """

    def test_an_unknown_kind_is_rejected_rather_than_ignored(self, session):
        from services.reference_cleanup import scrub_entity_references

        # The old behaviour — a silent no-op for an unhandled kind — is what
        # let the two missing branches sit unnoticed.
        with pytest.raises(ValueError, match="unknown entity kind"):
            scrub_entity_references(session, "campaign", "x")

    def test_deleting_a_story_removes_its_beats_and_revisions(self, client, session):
        story = Story(title="S")
        session.add(story)
        session.commit()
        chapter = StoryChapter(story_id=story.id, chapter_number=1, title="C1")
        session.add(chapter)
        session.commit()
        session.refresh(chapter)
        StoryBeatRepository(session).append(chapter.id, role="narrator", content="x")
        session.add(
            StoryChapterRevision(chapter_id=chapter.id, story_id=story.id, content="s")
        )
        session.commit()
        beat_id = session.exec(
            select(StoryBeat).where(StoryBeat.chapter_id == chapter.id)
        ).first().id

        assert client.delete(f"/api/v2/stories/{story.id}").status_code == 200

        session.expire_all()
        assert session.get(Story, story.id) is None
        assert session.get(StoryChapter, chapter.id) is None
        assert session.get(StoryBeat, beat_id) is None
        assert (
            session.exec(
                select(StoryChapterRevision).where(
                    StoryChapterRevision.story_id == story.id
                )
            ).all()
            == []
        )

    def test_deleting_a_story_untags_its_assets_without_deleting_them(
        self, client, session
    ):
        """An orphaned gallery entry is worse than an untagged one."""
        story = Story(title="S")
        session.add(story)
        session.commit()
        asset = Asset(filename="c.png", relative_path="a/b/c.png", story_id=story.id)
        session.add(asset)
        session.commit()
        asset_id = asset.id

        assert client.delete(f"/api/v2/stories/{story.id}").status_code == 200

        session.expire_all()
        surviving = session.get(Asset, asset_id)
        assert surviving is not None
        assert surviving.story_id is None

    def test_deleting_a_story_drops_its_graph_node(self, client, session):
        story = Story(title="S")
        session.add(story)
        session.commit()
        session.add(
            GraphLayout(name="default", entity_type="story", entity_id=story.id, x=1.0, y=2.0)
        )
        session.commit()

        assert client.delete(f"/api/v2/stories/{story.id}").status_code == 200

        session.expire_all()
        assert (
            session.exec(
                select(GraphLayout).where(GraphLayout.entity_id == story.id)
            ).all()
            == []
        )

    def test_deleting_a_chat_removes_its_messages(self, client, session):
        chat = Chat(name="C")
        session.add(chat)
        session.commit()
        session.add(Message(chat_id=chat.id, role="user", content="hi"))
        session.add(
            GraphLayout(name="default", entity_type="chat", entity_id=chat.id, x=1.0, y=2.0)
        )
        session.commit()

        assert client.delete(f"/api/v2/chats/{chat.id}").status_code == 200

        session.expire_all()
        assert session.get(Chat, chat.id) is None
        assert (
            session.exec(select(Message).where(Message.chat_id == chat.id)).all() == []
        )
        assert (
            session.exec(
                select(GraphLayout).where(GraphLayout.entity_id == chat.id)
            ).all()
            == []
        )