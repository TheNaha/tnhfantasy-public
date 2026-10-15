"""The chapter's prose is a render of its beats, and nothing else writes it.

This file is the contract for the change that removed the string surgery.

`chapter.content` used to be an independent field and `beats` a parallel log of
the same text. Every writer concatenated onto one or spliced the other by hand,
and the two drifted the moment the user typed in the editor. The cost landed far
from the cause: after a manual edit, `update_story_beat` could not find the
beat's text in the chapter and returned 400 "Beat text no longer matches the
chapter prose", leaving the beats panel's edit and delete affordances
permanently unusable for that chapter with no way back.

Now `content` is always `render_beats(beats)`, and `absorb_prose_edit` folds a
manual prose edit back onto the beat it belongs to. Every test here asserts the
same two things in a different situation: the render round-trips, and the beat
list still describes the text.
"""


import pytest
from unittest.mock import AsyncMock

import infrastructure.database as infra_database
from api.routes.world_vault.stories import (
    absorb_prose_edit,
    append_beat,
    beats_are_renderable,
    render_beats,
    sync_chapter_prose,
)
from core.entities import (
    Job,
    JobStatus,
    Persona,
    Story,
    StoryBeatRole,
    StoryChapter,
    World,
)


@pytest.fixture
def wired_engine(engine, monkeypatch):
    monkeypatch.setattr(infra_database, "engine", engine)
    return engine


@pytest.fixture
def chapter(session, wired_engine):
    """A PERSISTED chapter, because a beat row has a real FK to it.

    The fixture used to build one in memory, which was fine while beats were JSON
    on the chapter itself and is not any more: `story_beats.chapter_id` is a
    foreign key, so an insert against an unsaved chapter is an IntegrityError
    rather than a write.
    """
    story = Story(title="Fixture story")
    session.add(story)
    session.commit()
    session.refresh(story)
    ch = StoryChapter(story_id=story.id, chapter_number=1, title="c1", content="")
    session.add(ch)
    session.commit()
    session.refresh(ch)
    return ch


def _render_ok(ch) -> bool:
    return ch.content == render_beats(ch.beats)


class TestBeatsAreTheRecord:
    def test_content_is_exactly_the_render_of_the_beats(self, session, chapter):
        append_beat(chapter, session, role=StoryBeatRole.USER.value, content="knock on the door")
        append_beat(chapter, session, role=StoryBeatRole.NARRATOR.value, content="The door opens.")
        assert _render_ok(chapter)
        assert chapter.beats[-1]["parent_beat_id"] == chapter.beats[0]["id"]

    def test_a_user_beat_keeps_its_quote_marker_in_the_render(self, session, chapter):
        append_beat(chapter, session, role=StoryBeatRole.USER.value, content="knock")
        append_beat(chapter, session, role=StoryBeatRole.NARRATOR.value, content="The door opens.")
        assert chapter.content.startswith("\n\n> knock\n\n")

    def test_sync_recomputes_rather_than_appends(self, session, chapter):
        append_beat(chapter, session, role="narrator", content="one")
        append_beat(chapter, session, role="narrator", content="two")
        # Directly corrupt the prose the way the old writers left it.
        chapter.content = "not what the beats say"
        sync_chapter_prose(chapter)
        assert _render_ok(chapter)
        assert chapter.content.count("one") == 1

    def test_a_beat_with_no_content_key_refuses_to_render(self, session, chapter):
        """The one shape where the beats are NOT the record.

        Every writer includes `content` (a TTS beat carries `""` deliberately).
        A beat with no such key is an ancient row, and rendering it would drop
        its text on the floor — so the prose is kept and the caller is told.
        """
        chapter.beats = [{"id": "b1", "role": "narrator"}]
        chapter.content = "the prose the beat hides inside it"
        assert beats_are_renderable(chapter.beats) is False
        assert sync_chapter_prose(chapter) is False
        assert chapter.content == "the prose the beat hides inside it"


class TestAbsorbProseEdit:
    def test_an_edit_lands_in_the_beat_that_owns_it(self, session, chapter):
        append_beat(chapter, session, role=StoryBeatRole.USER.value, content="knock on the door")
        append_beat(chapter, session, role=StoryBeatRole.NARRATOR.value, content="The door opens.")

        absorb_prose_edit(chapter, session, chapter.content.replace("The door opens.", "The door swung wide."))

        assert chapter.beats[0]["content"] == "knock on the door"
        assert chapter.beats[1]["content"] == "The door swung wide."
        assert _render_ok(chapter)

    def test_a_substitution_inside_a_user_beat_keeps_the_quote_marker(self, session, chapter):
        """The `> ` prefix is part of the render, not of the beat's text.

        Mapping a prose offset straight onto a content offset includes the
        separators in the splice, which produced beats reading
        `"The door opswung wids"` out of a one-word substitution.
        """
        append_beat(chapter, session, role=StoryBeatRole.USER.value, content="knock on the door")
        absorb_prose_edit(chapter, session, chapter.content.replace("knock", "KNOCK"))
        assert chapter.beats[0]["content"] == "KNOCK on the door"
        assert _render_ok(chapter)

    def test_typing_at_the_end_starts_a_new_beat(self, session, chapter):
        """A boundary insertion is a new turn, not more text in the last one.

        Typing at the end of the chapter is the single most common edit. Folding
        it into the last beat was also unrepresentable: the user's text carries
        the beat separator plus their own blank line where the render has only
        one separator, so the fold silently dropped a newline. As a new beat it
        round-trips exactly.
        """
        append_beat(chapter, session, role=StoryBeatRole.NARRATOR.value, content="The door opens.")
        absorb_prose_edit(chapter, session, chapter.content + "\n\nHe stepped inside.")
        assert [b["content"] for b in chapter.beats] == [
            "The door opens.",
            "He stepped inside.",
        ]
        assert _render_ok(chapter)

    def test_a_boundary_insertion_prefixed_as_a_quote_is_a_user_beat(self, session, chapter):
        """The editor's `> ` convention has to survive the fold."""
        append_beat(chapter, session, role=StoryBeatRole.NARRATOR.value, content="The door opens.")
        absorb_prose_edit(chapter, session, chapter.content + "\n\n> I knock again.")
        assert [b["content"] for b in chapter.beats] == [
            "The door opens.",
            "I knock again.",
        ]
        assert chapter.beats[-1]["role"] == StoryBeatRole.USER.value
        assert _render_ok(chapter)

    def test_a_fold_that_would_change_the_users_text_is_refused(self, session, chapter):
        """Deleting a whole paragraph is genuinely ambiguous, and says so.

        The minimal diff between the old and new prose matches the deleted
        paragraph's words inside the replacement, so the edit reads as an
        insertion into the preceding beat and the beat that was deleted survives
        as a stale duplicate. Expressing it either way changes what the user
        typed, so the fold is refused, the prose is kept exactly, and the beat
        list is left alone rather than guessing.
        """
        append_beat(chapter, session, role=StoryBeatRole.NARRATOR.value, content="one")
        append_beat(chapter, session, role=StoryBeatRole.NARRATOR.value, content="two")
        append_beat(chapter, session, role=StoryBeatRole.NARRATOR.value, content="three")
        whole = chapter.content
        edited = whole.replace("one\n\n\n\ntwo", "one and two")

        absorb_prose_edit(chapter, session, edited)

        # The user's text survives byte for byte.
        assert chapter.content == edited
        # Nothing was garbled and nothing was silently dropped from the log.
        assert [b["content"] for b in chapter.beats] == ["one", "two", "three"]

    def test_a_fold_inside_one_beat_stays_exact(self, session, chapter):
        """The common case, and the one the whole change is for."""
        append_beat(chapter, session, role=StoryBeatRole.NARRATOR.value, content="one")
        append_beat(chapter, session, role=StoryBeatRole.NARRATOR.value, content="two")
        absorb_prose_edit(chapter, session, chapter.content.replace("two", "TWO"))
        assert [b["content"] for b in chapter.beats] == ["one", "TWO"]
        assert _render_ok(chapter)

    def test_a_beat_edit_after_a_manual_edit_is_no_longer_an_error(self, session, chapter):
        """The failure this whole change exists to remove.

        The old path located the beat's text in the chapter with `rfind` and
        400'd with "Beat text no longer matches the chapter prose" when a manual
        edit had moved it. It now recomputes the prose from the beat list, so
        there is nothing to locate.
        """
        append_beat(chapter, session, role=StoryBeatRole.NARRATOR.value, content="The door opens.")
        append_beat(chapter, session, role=StoryBeatRole.NARRATOR.value, content="He stepped inside.")

        # The user hand-edits the paragraph, the way the textarea lets them.
        absorb_prose_edit(chapter, session, chapter.content.replace("He stepped inside.", "He stepped in."))

        # A beat-level edit on top of that still works. Through the row path,
        # which is what the route does and what the row FK requires.
        from api.routes.world_vault.stories import write_beats

        beats = [dict(b) for b in chapter.beats]
        beats[0]["content"] = "The door opened at last."
        write_beats(chapter, session, beats)

        assert _render_ok(chapter)
        assert "The door opened at last." in chapter.content

    def test_an_already_drifted_chapter_is_left_alone_not_corrupted(self, session, chapter):
        """A baseline this chapter never had.

        `stored != render` means the prose and the beats were already describing
        different text — a restore of a pre-`092` snapshot, or old data. An edit
        can only be located against a known baseline, so folding one in would
        splice text into beats at positions they never produced, and a short
        accidental `SequenceMatcher` match is enough to corrupt a beat.
        """
        append_beat(chapter, session, role=StoryBeatRole.NARRATOR.value, content="the beat's own text")
        chapter.content = "prose the user typed, which the beats do not describe"

        absorb_prose_edit(chapter, session, "prose the user typed, with a new word")

        # The prose wins, the beats are untouched, and nothing is garbled.
        assert chapter.content == "prose the user typed, with a new word"
        assert chapter.beats[0]["content"] == "the beat's own text"

    def test_an_audio_beat_survives_a_prose_edit_that_empties_it(self, session, chapter):
        """A TTS beat's content is `""` by construction.

        Dropping beats that emptied would delete narration audio along with the
        text, so `audio_path` is what keeps one.
        """
        append_beat(chapter, session, role=StoryBeatRole.NARRATOR.value, content="The door opens.")
        chapter.beats.append(
            {"id": "tts-1", "parent_beat_id": None, "role": "tts", "content": "", "audio_path": "a.mp3"}
        )
        sync_chapter_prose(chapter)
        whole = chapter.content
        absorb_prose_edit(chapter, session, whole.replace("The door opens.", "The door opened."))
        assert any(b.get("audio_path") == "a.mp3" for b in chapter.beats)


class TestTheWriterRoutesRoundTrip:
    """The routes used to concatenate onto `content` and splice it by hand."""

    def _wire(self, session):
        world = World(name="W")
        session.add(world)
        session.commit()
        session.refresh(world)
        story = Story(title="s", world_id=world.id)
        session.add(story)
        session.commit()
        session.refresh(story)
        chapter = StoryChapter(story_id=story.id, chapter_number=1, title="c1", content="")
        session.add(chapter)
        session.commit()
        session.refresh(chapter)
        return story, chapter

    def test_add_beat_renders_the_prose(self, client, session):
        story, chapter = self._wire(session)
        resp = client.post(
            f"/api/v2/stories/{story.id}/chapters/{chapter.id}/beats",
            json={"role": "narrator", "content": "A line of prose."},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert _render_ok_from(body)
        assert body["beats"][-1]["content"] == "A line of prose."

    def test_update_beat_does_not_400_after_a_manual_edit(self, client, session):
        story, chapter = self._wire(session)
        client.post(
            f"/api/v2/stories/{story.id}/chapters/{chapter.id}/beats",
            json={"role": "narrator", "content": "First beat."},
        )
        # Hand-edit the chapter through the autosave route.
        chapter_id = chapter.id
        chapter = session.get(StoryChapter, chapter_id)
        absorb_prose_edit(chapter, session, chapter.content.replace("First beat.", "First beat, edited."))
        session.add(chapter)
        session.commit()

        beat_id = session.get(StoryChapter, chapter_id).beats[0]["id"]
        resp = client.patch(
            f"/api/v2/stories/{story.id}/chapters/{chapter_id}/beats/{beat_id}",
            json={"content": "First beat, rewritten."},
        )
        assert resp.status_code == 200, resp.text
        assert _render_ok_from(resp.json())
        assert "First beat, rewritten." in resp.json()["content"]

    def test_delete_beat_removes_its_prose(self, client, session):
        story, chapter = self._wire(session)
        for text in ("One.", "Two."):
            client.post(
                f"/api/v2/stories/{story.id}/chapters/{chapter.id}/beats",
                json={"role": "narrator", "content": text},
            )
        chapter_id = chapter.id
        beat_id = session.get(StoryChapter, chapter_id).beats[0]["id"]
        resp = client.delete(
            f"/api/v2/stories/{story.id}/chapters/{chapter_id}/beats/{beat_id}"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert _render_ok_from(body)
        assert "One." not in body["content"]
        assert "Two." in body["content"]

    def test_autosave_with_prose_only_keeps_the_beats(self, client, session):
        """The regression that used to wipe the beat list wholesale."""
        story, chapter = self._wire(session)
        client.post(
            f"/api/v2/stories/{story.id}/chapters/{chapter.id}/beats",
            json={"role": "narrator", "content": "A line."},
        )
        chapter_id = chapter.id
        before = session.get(StoryChapter, chapter_id).beats

        resp = client.put(
            f"/api/v2/stories/{story.id}/chapters/{chapter_id}",
            json={"content": "The user retyped the whole thing."},
        )
        assert resp.status_code == 200, resp.text
        after = session.get(StoryChapter, chapter_id).beats
        assert len(after) == 1
        assert after[0]["id"] == before[0]["id"]

    def test_restore_rewinds_the_beats_with_the_prose(self, client, session):
        story, chapter = self._wire(session)
        client.post(
            f"/api/v2/stories/{story.id}/chapters/{chapter.id}/beats",
            json={"role": "narrator", "content": "One."},
        )
        chapter_id = chapter.id
        revision = client.post(
            f"/api/v2/stories/{story.id}/chapters/{chapter_id}/revisions"
        )
        assert revision.status_code == 200, revision.text
        revision_id = revision.json()["id"]

        client.post(
            f"/api/v2/stories/{story.id}/chapters/{chapter_id}/beats",
            json={"role": "narrator", "content": "Two."},
        )
        assert len(session.get(StoryChapter, chapter_id).beats) == 2

        resp = client.post(
            f"/api/v2/stories/{story.id}/chapters/{chapter_id}/revisions/{revision_id}/restore"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert _render_ok_from(body)
        assert [b["content"] for b in body["beats"]] == ["One."]
        assert "Two." not in body["content"]


def _render_ok_from(body: dict) -> bool:
    """Render-check an API response body."""
    return (body.get("content") or "") == render_beats(body.get("beats"))


class TestBeatAlternates:
    """A retry is a second take, not a replacement.

    `retry_last_continuation` used to TRIM the last narrator beat and re-enqueue,
    so a continuation you only wanted another opinion on was destroyed the moment
    you asked for one. A chat swipe has been additive since it existed —
    `alternates` on one row, `active_index` pointing at the one that renders —
    and a story now does the same thing on a beat.
    """

    def _chapter_with_beats(self, session, chapter, beats):
        """Seed a chapter's beats as ROWS, then re-render.

        The beats used to be seeded by assigning the JSON column directly; a beat
        is a row now, so the seed goes through the same writer the routes do.
        That also means the JSON column is populated from the rows, which is the
        invariant every test here asserts.
        """
        from api.routes.world_vault.stories import write_beats

        write_beats(chapter, session, list(beats))
        return chapter

    def test_a_retry_stores_its_take_beside_the_original(self, session, chapter):
        from api.routes.world_vault.stories import append_beat_alternate

        chapter = self._chapter_with_beats(session, chapter, [
            {"id": "b1", "parent_beat_id": None, "role": "user", "content": "Opening move"},
            {"id": "b2", "parent_beat_id": None, "role": "narrator",
             "content": "A shadow moved.", "source_job_id": "job-first"},
        ])

        beat = append_beat_alternate(
            chapter, session,
            role=StoryBeatRole.NARRATOR.value,
            content="A cat watched.",
            retry_of="b2",
            source_job_id="job-second",
        )

        # One beat, two takes, the new one showing.
        assert [a["text"] for a in beat["alternates"]] == ["A shadow moved.", "A cat watched."]
        assert beat["active_index"] == 1
        assert beat["content"] == "A cat watched."
        # The first take keeps the stamp of the job that made it, so switching
        # back to it does not orphan what the reconciler looks for.
        assert beat["alternates"][0]["source_job_id"] == "job-first"
        assert _render_ok(chapter)

    def test_a_retry_on_a_missing_anchor_appends_instead(self, session, chapter):
        """The anchor is gone: a fresh beat is the honest recovery."""
        from api.routes.world_vault.stories import append_beat_alternate

        chapter = self._chapter_with_beats(session, chapter, [
            {"id": "b1", "parent_beat_id": None, "role": "narrator", "content": "One."},
        ])
        append_beat_alternate(
            chapter, session, role="narrator", content="Two.", retry_of="does-not-exist"
        )
        assert [b["content"] for b in chapter.beats] == ["One.", "Two."]
        assert _render_ok(chapter)

    def test_selecting_switches_which_take_renders(self, session, chapter):
        from api.routes.world_vault.stories import select_beat_alternate

        chapter = self._chapter_with_beats(session, chapter, [
            {"id": "b2", "parent_beat_id": None, "role": "narrator", "content": "second",
             "alternates": [{"text": "first", "source_job_id": "j1"},
                            {"text": "second", "source_job_id": "j2"}],
             "active_index": 1},
        ])

        assert select_beat_alternate(chapter, session, "b2", 0) is True
        assert chapter.beats[0]["content"] == "first"
        # The stamp follows the take on screen, so the reconciler looks for the
        # job that produced the text the user is actually reading.
        assert chapter.beats[0]["source_job_id"] == "j1"
        assert _render_ok(chapter)

    def test_selecting_an_out_of_range_index_is_refused(self, session, chapter):
        from api.routes.world_vault.stories import select_beat_alternate

        chapter = self._chapter_with_beats(session, chapter, [
            {"id": "b2", "parent_beat_id": None, "role": "narrator", "content": "only",
             "alternates": [{"text": "only"}], "active_index": 0},
        ])
        assert select_beat_alternate(chapter, session, "b2", 5) is False
        assert select_beat_alternate(chapter, session, "no-such-beat", 0) is False

    def test_a_beat_with_one_take_has_nothing_to_switch(self, session, chapter):
        """`alternates` only exists from the first retry on."""
        from api.routes.world_vault.stories import select_beat_alternate

        chapter = self._chapter_with_beats(session, chapter, [
            {"id": "b1", "parent_beat_id": None, "role": "narrator", "content": "one take"},
        ])
        assert select_beat_alternate(chapter, session, "b1", 0) is False

    def test_the_stamp_inside_an_alternate_is_found_by_the_reconciler(
        self, session, wired_engine
    ):
        """A retry's stamp lives inside the alternate, not on the beat.

        The detector scans the serialised beats column, so it finds one anywhere
        in it — but the per-beat scan looks at `beat[key]`, and a job whose take
        wrote successfully would otherwise be found as lost forever and re-driven
        on every sweep. Same reason the chat half scans `alternates` too.
        """

        import services.world_integration_service as wis

        world = World(name="W")
        session.add(world)
        session.commit()
        session.refresh(world)
        story = Story(title="s", world_id=world.id)
        session.add(story)
        session.commit()
        session.refresh(story)
        chapter = StoryChapter(
            story_id=story.id, chapter_number=1, title="c1", content="",
            beats=[{"id": "b2", "parent_beat_id": None, "role": "narrator",
                    "content": "the take on screen",
                    "alternates": [{"text": "an earlier take", "source_job_id": "job-earlier"}],
                    "active_index": 0, "source_job_id": "job-earlier"}],
        )
        session.add(chapter)
        session.commit()
        session.refresh(chapter)

        session.add(Job(
            id="job-earlier",
            task_type="llm",
            status=JobStatus.COMPLETED,
            workflow={"type": "story_continue", "story_id": story.id},
            metadata_={
                "type": "story_continue",
                "story_id": story.id,
                "chapter_id": chapter.id,
                "retry_of": "b2",
            },
            outputs=[{"role": "assistant", "content": "an earlier take"}],
        ))
        session.commit()

        # Already written, as an alternate, so the sweep must be clean.
        assert wis.find_unpersisted_chat_replies(session) == []


class TestStoryPersonaReachesTheModel:
    """The protagonist used to be anonymous.

    `Story.character_ids` gave the model every other person in the scene and none
    of them was the one typing `> I draw my blade`. A chat resolves `persona_id`
    from the library through `chat_context_kwargs`; a story passed none of it.
    """

    def test_the_persona_fields_are_persisted_by_update(self, client, session):
        story = Story(title="s")
        session.add(story)
        session.commit()
        session.refresh(story)

        resp = client.put(f"/api/v2/stories/{story.id}", json={
            "persona_name": "Kai",
            "persona_description": "A tired courier with a bad knee.",
        })
        assert resp.status_code == 200, resp.text
        session.expire_all()
        after = session.get(Story, story.id)
        assert after.persona_name == "Kai"
        assert after.persona_description == "A tired courier with a bad knee."

    def test_a_library_persona_fills_what_the_story_leaves_blank(self, session, monkeypatch):
        """The same precedence `chat_context_kwargs` uses: story first, library second."""
        from api.routes.world_vault.stories import _enqueue_story_continuation

        persona = Persona(name="FromLibrary", description="Someone else's.")
        session.add(persona)
        session.commit()
        session.refresh(persona)
        story = Story(title="s", persona_id=persona.id)
        session.add(story)
        session.commit()
        session.refresh(story)
        chapter = StoryChapter(story_id=story.id, chapter_number=1, title="c1", content="")
        session.add(chapter)
        session.commit()
        session.refresh(chapter)

        seen = {}
        import services.context_builder as context_builder

        async def _spy(messages, **kwargs):
            seen.update(kwargs)
            return "sys", []

        # Patched on the source module, not the route: `_enqueue_story_continuation`
        # imports the builder inside its own body, so an attribute on the route
        # module is not what it calls.
        monkeypatch.setattr(context_builder, "build_chat_context_async", _spy)
        monkeypatch.setattr(
            "services.job_queue.queue_manager.enqueue", AsyncMock(return_value=True)
        )

        import asyncio

        asyncio.run(_enqueue_story_continuation(session, story, chapter))

        assert seen["persona_name"] == "FromLibrary"
        assert seen["persona_description"] == "Someone else's."


class TestChapterPruning:
    """A chapter is sent as its beats, not as one blob — which is what rows buy.

    `prune_context` trims from the front of a MESSAGE LIST. A chapter arriving as
    a single `{"role": "user", "content": <whole prose>}` message therefore had
    nothing to trim inside it, and a 6,000-word chapter ate the budget regardless
    of `maxContextTokens` — the plumbing's own comment says `prune_context`
    "truncated the user's own prose".

    The beats are rows, so they go in as turns and the earlier ones are what go.
    """

    def _turns_for(self, session, beats):
        """What the context build would be handed for a given beat list."""
        return [
            {
                "role": "user" if b.get("role") == "user" else "assistant",
                "content": b.get("content") or "",
            }
            for b in beats
            if (b.get("content") or "").strip()
        ]

    def test_a_long_chapter_prunes_from_the_front(self, session, chapter):
        from services.context_builder import estimate_tokens, prune_context

        beats = [
            {"id": f"b{i}", "role": "narrator" if i % 2 else "user",
             "content": f"Beat {i}. " + ("filler text " * 30)}
            for i in range(12)
        ]
        turns = self._turns_for(session, beats)

        # A budget that fits the last few beats but not all twelve.
        system = "SYS"
        budget = estimate_tokens(system) + estimate_tokens(turns[-1]["content"]) + estimate_tokens(turns[-2]["content"])
        pruned = prune_context(turns, system, [], max_tokens=budget)

        assert len(pruned) < len(turns), "the tail is kept but the head is not, which is the fix"
        assert pruned[-1]["content"] == turns[-1]["content"], "the most recent beat always survives"

    def test_a_beat_with_only_whitespace_is_not_a_turn(self, session, chapter):
        """A TTS beat's content is `""` and must not become an empty turn."""
        beats = [
            {"id": "b1", "role": "user", "content": "Opening move"},
            {"id": "b2", "role": "tts", "content": "", "audio_path": "a.wav"},
        ]
        assert len(self._turns_for(session, beats)) == 1

    def test_a_user_beat_goes_in_as_a_user_turn(self, session, chapter):
        """The same split `llm_turn_for` uses, so the reader's inputs are its side."""
        beats = [{"id": "b1", "role": "user", "content": "I draw my blade."}]
        assert self._turns_for(session, beats) == [{"role": "user", "content": "I draw my blade."}]


class TestBeatsMigration:
    """The backfill from `story_chapters.beats` to `story_beats` rows.

    No test covered this, which is the worst place to be uncovered: it runs once,
    at boot, on a database the developer does not have, and a backfill that loses
    a beat's stamp or permutes its order is silent — the chapter renders, the
    beats panel works, and only a redelivered job behaves oddly.
    """

    # Two statements, executed separately: the sqlite3 driver accepts one
    # statement per `execute`, and a script with a semicolon in it fails with
    # "You can only execute one statement at a time".
    LEGACY_DDL = [
        "CREATE TABLE stories (id VARCHAR PRIMARY KEY, title VARCHAR)",
        """CREATE TABLE story_chapters (
            id VARCHAR PRIMARY KEY, story_id VARCHAR, chapter_number INTEGER,
            title VARCHAR, content TEXT, beats JSON, image_paths JSON,
            created_at TIMESTAMP, updated_at TIMESTAMP)""",
    ]

    def _legacy(self, engine, beats_json, content="RAINFALL PLACEHOLDER"):
        from sqlalchemy import text

        with engine.begin() as conn:
            for stmt in self.LEGACY_DDL:
                conn.execute(text(stmt))
            conn.execute(text("INSERT INTO stories VALUES ('s1','Tale')"))
            conn.execute(
                text("INSERT INTO story_chapters VALUES ('c1','s1',1,'ch',:c,:b,'[]','2026-01-01','2026-01-01')"),
                {"c": content, "b": beats_json},
            )

    def _rows(self, engine):
        from sqlalchemy import text

        with engine.connect() as conn:
            return conn.execute(
                text("SELECT id, position, role, content, source_job_id, extra, alternates, active_index FROM story_beats ORDER BY position")
            ).all()

    def test_a_backfill_preserves_order_and_stamps(self, session):
        import json
        from sqlalchemy import create_engine

        from infrastructure.migrations.steps import _migration_095_beats_as_rows

        engine = create_engine("sqlite://")
        self._legacy(engine, json.dumps([
            {"id": "b1", "parent_beat_id": None, "role": "user", "content": "Opening move"},
            {"id": "b2", "parent_beat_id": "b1", "role": "narrator", "content": "Rain fell.",
             "source_job_id": "job-x", "orchestrator_depth": 1, "intermediate": True},
            {"id": "b3", "parent_beat_id": "b2", "role": "tts", "content": "", "audio_path": "a.wav"},
        ]))

        assert _migration_095_beats_as_rows(engine.connect()) is True
        rows = self._rows(engine)

        assert [r[0] for r in rows] == ["b1", "b2", "b3"], "position order must survive"
        assert [r[1] for r in rows] == [0, 1, 2]
        assert rows[1][4] == "job-x"
        # Everything the JSON carried that is not a column of its own lands in
        # `extra`, so nothing is lost by the move.
        assert json.loads(rows[1][5]) == {"orchestrator_depth": 1, "intermediate": True}
        assert rows[2][2] == "tts"

    def test_a_rerun_does_not_reseed(self, session):
        import json
        from sqlalchemy import create_engine, text

        from infrastructure.migrations.steps import _migration_095_beats_as_rows

        engine = create_engine("sqlite://")
        self._legacy(engine, json.dumps([{"id": "b1", "role": "narrator", "content": "one"}]))
        _migration_095_beats_as_rows(engine.connect())

        # A second boot re-runs the step, and it must be a no-op — not a second
        # copy of every beat, which would double the chapter's prose.
        with engine.begin() as conn:
            _migration_095_beats_as_rows(conn)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM story_beats")).scalar() == 1

    def test_an_unparseable_beats_column_is_skipped_not_fatal(self, session):
        """A corrupt row must not take the whole migration down at boot."""
        from sqlalchemy import create_engine, text

        from infrastructure.migrations.steps import _migration_095_beats_as_rows

        engine = create_engine("sqlite://")
        self._legacy(engine, "not json at all")

        # Returns True (the step ran and is recorded); the bad chapter is simply
        # skipped, which is better than failing to boot.
        assert _migration_095_beats_as_rows(engine.connect()) is True
        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM story_beats")).scalar() == 0

    def test_a_chapter_with_no_beats_yields_no_rows(self, session):
        from sqlalchemy import create_engine, text

        from infrastructure.migrations.steps import _migration_095_beats_as_rows

        engine = create_engine("sqlite://")
        self._legacy(engine, "[]")
        _migration_095_beats_as_rows(engine.connect())
        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM story_beats")).scalar() == 0
