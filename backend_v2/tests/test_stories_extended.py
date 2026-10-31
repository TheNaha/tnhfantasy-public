"""Tests for Story publish, export, narrate, and branching endpoints."""
from uuid import uuid4

import pytest
from PIL import Image as PILImage
from sqlmodel import select

import config as app_config
from api.routes.world_vault.stories import (
    _collect_story_illustration_assets,
    _resolve_story_image_path,
)
from core.entities import Asset, AssetKind, Character, Job, Story, StoryChapter, World

@pytest.fixture
def story_with_character(session):
    char = Character(name="StoryTeller", description="test")
    session.add(char)
    session.commit()
    session.refresh(char)

    story = Story(
        title="Published Tale",
        description="A story for publishing test",
        genre="fantasy",
        memory="Written by TNHFantasy",
        character_ids=[char.id],
    )
    session.add(story)
    session.commit()
    session.refresh(story)

    ch1 = StoryChapter(story_id=story.id, chapter_number=1, title="Beginning", content="Once upon a time...")
    session.add(ch1)
    session.commit()
    session.refresh(ch1)

    return story, ch1


def test_publish_story(client, session, story_with_character):
    story, chapter = story_with_character
    response = client.post(f"/api/v2/stories/{story.id}/publish")
    assert response.status_code == 200
    data = response.json()
    assert data["is_published"] is True
    assert data["published_token"] is not None
    assert data["read_url"]


def test_publish_story_not_found(client):
    response = client.post("/api/v2/stories/nonexistent/publish")
    assert response.status_code == 404


def test_update_story_writing_prefs(client, session, story_with_character):
    story, _chapter = story_with_character
    resp = client.put(
        f"/api/v2/stories/{story.id}",
        json={"pov": "second", "word_count_goal": 50000},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["pov"] == "second"
    assert data["word_count_goal"] == 50000

    # Explicit null clears the override
    resp = client.put(f"/api/v2/stories/{story.id}", json={"pov": None})
    assert resp.status_code == 200
    assert resp.json()["pov"] is None


def test_read_published_story(client, session, story_with_character):
    story, chapter = story_with_character
    # Publish first
    publish_resp = client.post(f"/api/v2/stories/{story.id}/publish")
    token = publish_resp.json()["published_token"]

    response = client.get(f"/api/v2/stories/published/{token}")
    assert response.status_code == 200
    data = response.json()
    assert data["story"]["title"] == "Published Tale"
    assert len(data["chapters"]) >= 1
    assert data["chapters"][0]["title"] == "Beginning"


def test_read_published_story_not_found(client):
    response = client.get("/api/v2/stories/published/nonexistent-token")
    assert response.status_code == 404


def test_unpublish_story(client, session, story_with_character):
    story, chapter = story_with_character
    # Publish first
    client.post(f"/api/v2/stories/{story.id}/publish")

    response = client.post(f"/api/v2/stories/{story.id}/unpublish")
    assert response.status_code == 200
    data = response.json()
    assert data["is_published"] is False
    assert data["published_token"] is None


def test_export_story_json(client, session, story_with_character):
    story, chapter = story_with_character
    response = client.get(f"/api/v2/stories/{story.id}/export?format=json")
    assert response.status_code == 200
    data = response.json()
    assert "story" in data
    assert data["story"]["title"] == "Published Tale"
    assert len(data["chapters"]) >= 1


def test_export_story_markdown(client, session, story_with_character):
    story, chapter = story_with_character
    response = client.get(f"/api/v2/stories/{story.id}/export?format=md")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "markdown"
    assert "Published Tale" in data["content"]
    assert "Chapter 1" in data["content"]


def test_export_story_epub(client, session, story_with_character):
    story, chapter = story_with_character
    response = client.get(f"/api/v2/stories/{story.id}/export?format=epub")
    assert response.status_code == 200
    # ePub returns binary content (ZIP)
    import zipfile, io
    assert zipfile.is_zipfile(io.BytesIO(response.content))


def test_export_published_story(client, session, story_with_character):
    story, chapter = story_with_character
    # Publish first
    publish_resp = client.post(f"/api/v2/stories/{story.id}/publish")
    token = publish_resp.json()["published_token"]

    response = client.get(f"/api/v2/stories/published/{token}/export?format=md")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "markdown"
    assert "Published Tale" in data["content"]


def test_export_published_story_not_found(client):
    response = client.get("/api/v2/stories/published/nonexistent/export")
    assert response.status_code == 404


def test_narrate_chapter(client, session, story_with_character, tts_capable):
    from core.entities import Job

    story, chapter = story_with_character
    response = client.post(f"/api/v2/stories/{story.id}/chapters/{chapter.id}/narrate")
    assert response.status_code == 200, response.text
    data = response.json()
    assert "job_id" in data

    # Was `task_type="image"` with an `XTTS_v2` graph — node types no provider
    # image has, submitted to a worker that could not build it. TTS is its own
    # provider capability now; the task type has to say so.
    job = session.get(Job, data["job_id"])
    assert job.task_type == "tts"
    assert job.metadata_["source"] == "story_tts"
    assert job.metadata_["chapter_id"] == chapter.id
    assert job.metadata_["story_id"] == story.id
    node_types = {n["class_type"] for n in job.workflow["prompt"].values()}
    assert node_types == {"QwenTTSSpeak", "SaveAudio"}


def test_narrate_chapter_refuses_without_tts_capability(client, session, story_with_character):
    story, chapter = story_with_character
    response = client.post(f"/api/v2/stories/{story.id}/chapters/{chapter.id}/narrate")
    assert response.status_code == 400
    assert "capabilit" in response.text.lower()


def test_narrate_chapter_not_found(client, tts_capable):
    response = client.post("/api/v2/stories/nonexistent/chapters/nonexistent/narrate")
    assert response.status_code == 404


def test_ai_action_rejects_unknown_action(client, session, story_with_character):
    story, chapter = story_with_character
    response = client.post(f"/api/v2/stories/{story.id}/chapters/{chapter.id}/ai-action", json={
        "action": "vibes", "target_text": "some text",
    })
    assert response.status_code == 400


def test_ai_action_requires_target_text(client, session, story_with_character):
    story, chapter = story_with_character
    response = client.post(f"/api/v2/stories/{story.id}/chapters/{chapter.id}/ai-action", json={
        "action": "summarize", "target_text": "   ",
    })
    assert response.status_code == 400


def test_ai_action_enqueues_job(client, session, story_with_character):
    story, chapter = story_with_character
    response = client.post(f"/api/v2/stories/{story.id}/chapters/{chapter.id}/ai-action", json={
        "action": "rewrite",
        "target_text": "Once upon a time...",
        "directive": "make it darker",
    })
    assert response.status_code == 200
    assert response.json()["job_id"]


def test_retry_last_requires_narrator_tail(client, session, story_with_character):
    story, chapter = story_with_character
    # Chapter has no beats at all -> nothing AI-generated to retry
    response = client.post(f"/api/v2/stories/{story.id}/chapters/{chapter.id}/retry-last")
    assert response.status_code == 400


def test_retry_last_keeps_the_take_it_replaces(client, session, story_with_character):
    """A retry is a second take, not a replacement.

    It used to TRIM the last narrator beat and re-enqueue, so a continuation you
    only wanted another opinion on was destroyed the moment you asked for one, and
    the only way back was a revision snapshot that rewound the whole chapter.
    """
    story, chapter = story_with_character
    from core.entities import StoryChapter as SC
    ch = session.get(SC, chapter.id)
    ai_text = "A shadow slid across the courtyard wall."
    from api.routes.world_vault.stories import write_beats

    write_beats(ch, session, [
        {"id": str(uuid4()), "parent_beat_id": None, "role": "user", "content": "Opening move"},
        {"id": str(uuid4()), "parent_beat_id": None, "role": "narrator", "content": ai_text},
    ])
    session.add(ch)
    session.commit()
    session.refresh(ch)

    response = client.post(f"/api/v2/stories/{story.id}/chapters/{ch.id}/retry-last")
    assert response.status_code == 200
    assert response.json()["job_id"]

    # The beat is still there, still rendering, and the job carries the anchor so
    # the answer lands as an alternate rather than a new paragraph.
    job = session.exec(select(Job).where(Job.task_type == "llm")).all()[-1]
    assert job.metadata_["retry_of"] == ch.beats[1]["id"]

    session.expire_all()
    reloaded = session.get(SC, ch.id)
    assert len(reloaded.beats) == 2
    assert reloaded.beats[1]["role"] == "narrator"
    assert ai_text in reloaded.content
    assert "Opening move" in reloaded.content


def test_a_retry_answer_becomes_an_alternate_not_a_new_beat(
    client, session, story_with_character, monkeypatch
):
    import asyncio
    from unittest.mock import AsyncMock

    from core.entities import StoryChapter as SC
    import services.world_integration_service as wis

    story, chapter = story_with_character
    ch = session.get(SC, chapter.id)
    first = "A shadow slid across the courtyard wall."
    # Seeded through the row writer, not by assigning the JSON column: a beat is
    # a `story_beats` row now, and the JSON is its render.
    from api.routes.world_vault.stories import write_beats

    write_beats(ch, session, [
        {"id": "b1", "parent_beat_id": None, "role": "user", "content": "Opening move"},
        {"id": "b2", "parent_beat_id": None, "role": "narrator", "content": first,
         "source_job_id": "job-first"},
    ])
    session.add(ch)
    session.commit()
    session.refresh(ch)

    monkeypatch.setattr("services.job_queue.queue_manager.enqueue", AsyncMock(return_value=True))
    client.post(f"/api/v2/stories/{story.id}/chapters/{ch.id}/retry-last")
    job = session.exec(select(Job).where(Job.task_type == "llm")).all()[-1]

    print("JOB META:", job.metadata_)
    asyncio.run(wis._handle_story_continue({
        "id": job.id,
        "metadata": job.metadata_ or {},
        "outputs": [{"role": "assistant", "content": "A cat watched from the wall."}],
    }))

    session.expire_all()
    reloaded = session.get(SC, ch.id)
    beat = reloaded.beats[1]
    # One beat, two takes, the second showing.
    assert beat["content"] == "A cat watched from the wall."
    assert [a["text"] for a in beat["alternates"]] == [
        "A shadow slid across the courtyard wall.",
        "A cat watched from the wall.",
    ]
    assert beat["active_index"] == 1
    # And the first take keeps the job it came from, so switching back to it does
    # not orphan the stamp the reconciler looks for.
    assert beat["alternates"][0]["source_job_id"] == "job-first"
    assert reloaded.content.count("A cat watched") == 1


def test_selecting_an_alternate_switches_which_take_renders(
    client, session, story_with_character
):
    """The story counterpart of a chat swipe."""
    from core.entities import StoryChapter as SC

    story, chapter = story_with_character
    ch = session.get(SC, chapter.id)
    from api.routes.world_vault.stories import write_beats

    write_beats(ch, session, [
        {"id": "b2", "parent_beat_id": None, "role": "narrator", "content": "second take",
         "alternates": [{"text": "first take", "source_job_id": "j1"},
                        {"text": "second take", "source_job_id": "j2"}],
         "active_index": 1},
    ])
    session.add(ch)
    session.commit()
    session.refresh(ch)

    resp = client.post(
        f"/api/v2/stories/{story.id}/chapters/{ch.id}/beats/b2/select-alternate",
        json={"index": 0},
    )
    assert resp.status_code == 200, resp.text
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["content"] == "\n\nfirst take\n\n"
    beat = body["beats"][0]
    assert beat["active_index"] == 0
    # The stamp follows the take on screen, so the reconciler looks for the job
    # that produced the text the user is actually reading.
    assert beat["source_job_id"] == "j1"


def test_story_branch_chapter(client, session, story_with_character):
    story, chapter = story_with_character
    # First ensure the chapter has beats with IDs
    from core.entities import StoryChapter as SC
    ch = session.get(SC, chapter.id)
    if not ch.beats:
        ch.beats = [{"id": str(uuid4()), "role": "user", "content": "Starting prompt", "parent_beat_id": None}]
        session.add(ch)
        session.commit()
        session.refresh(ch)
    beat_id = ch.beats[-1]["id"]
    response = client.post(f"/api/v2/stories/{story.id}/chapters/{chapter.id}/branch", json={
        "from_beat_id": beat_id,
        "prompt": "What happens next?",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["id"]


def test_resolve_story_image_path(tmp_path):
    existing = tmp_path / "real.png"
    PILImage.new("RGB", (10, 10), (1, 2, 3)).save(existing)
    missing_relative = "does_not_exist.png"

    app_config.settings.output_dir = str(tmp_path)

    # absolute existing path inside the output root resolves as-is
    assert _resolve_story_image_path(str(existing)) == str(existing)
    # relative path resolves against configured output_dir when present
    monkeypatch_dir = tmp_path / "out"
    monkeypatch_dir.mkdir()
    rel = monkeypatch_dir / "rel.png"
    PILImage.new("RGB", (10, 10), (1, 2, 3)).save(rel)
    app_config.settings.output_dir = str(monkeypatch_dir)
    assert _resolve_story_image_path("rel.png") == str(rel)
    # missing file returns None
    assert _resolve_story_image_path(missing_relative) is None
    assert _resolve_story_image_path(None) is None


def test_collect_story_illustration_assets(tmp_path, session):
    story = Story(title="Asset Tale")
    session.add(story)
    session.commit()
    session.refresh(story)

    # existing image asset -> included and resolved
    good_dir = tmp_path / "out"
    good_dir.mkdir()
    good = good_dir / "good.png"
    PILImage.new("RGB", (10, 10), (1, 2, 3)).save(good)
    session.add(Asset(
        filename="good.png",
        relative_path="good.png",
        kind=AssetKind.IMAGE,
        story_id=story.id,
    ))
    # asset pointing at a missing file -> excluded (no gray fallthrough)
    session.add(Asset(
        filename="missing.png",
        relative_path="missing.png",
        kind=AssetKind.IMAGE,
        story_id=story.id,
    ))
    # asset for a different story -> excluded
    other = Story(title="Other")
    session.add(other)
    session.commit()
    session.refresh(other)
    session.add(Asset(
        filename="other.png",
        relative_path="other.png",
        kind=AssetKind.IMAGE,
        story_id=other.id,
    ))
    # non-image asset -> excluded
    session.add(Asset(
        filename="note.txt",
        relative_path="note.txt",
        kind=AssetKind.TEXT,
        story_id=story.id,
    ))
    session.commit()

    app_config.settings.output_dir = str(good_dir)
    result = _collect_story_illustration_assets(session, story.id)
    assert result == [str(good)]


def test_export_story_comic_embeds_real_asset(client, session, story_with_character, tmp_path, monkeypatch):
    story, chapter = story_with_character
    # A real illustration image on disk, indexed as a story asset
    img_dir = tmp_path / "story_imgs"
    img_dir.mkdir(parents=True, exist_ok=True)
    img_path = img_dir / "illus.png"
    PILImage.new("RGB", (200, 300), (10, 200, 50)).save(img_path)
    session.add(Asset(
        filename="illus.png",
        relative_path="story_imgs/illus.png",
        kind=AssetKind.IMAGE,
        story_id=story.id,
    ))
    session.commit()

    monkeypatch.setattr(app_config.settings, "output_dir", str(tmp_path))

    response = client.get(f"/api/v2/stories/{story.id}/export?format=comic")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content[:4] == b"%PDF"
    # Non-empty PDF produced from a real embedded image (far larger than a
    # single blank gray page would compress to).
    assert len(response.content) > 500


def _beat_chapter(session, story):
    from core.entities import StoryChapter as SC
    ch = session.get(SC, session.query(SC).filter_by(story_id=story.id).first().id)
    user_id, narr_id = str(uuid4()), str(uuid4())
    ai_text = "A shadow slid across the courtyard wall."
    ch.beats = [
        {"id": user_id, "parent_beat_id": None, "role": "user", "content": "Opening move"},
        {"id": narr_id, "parent_beat_id": None, "role": "narrator", "content": ai_text},
    ]
    ch.content = "Once upon a time...\n\n> Opening move\n\n" + f"\n\n{ai_text}\n\n"
    session.add(ch)
    session.commit()
    session.refresh(ch)
    return ch, user_id, narr_id


def test_update_beat_edits_prose_and_role(client, session, story_with_character):
    story, _ = story_with_character
    ch, user_id, _ = _beat_chapter(session, story)

    response = client.patch(
        f"/api/v2/stories/{story.id}/chapters/{ch.id}/beats/{user_id}",
        json={"content": "Revised opening", "role": "narrator"},
    )
    assert response.status_code == 200

    from core.entities import StoryChapter as SC
    session.expire_all()
    reloaded = session.get(SC, ch.id)
    beat = next(b for b in reloaded.beats if b["id"] == user_id)
    assert beat["content"] == "Revised opening"
    assert beat["role"] == "narrator"
    assert "> Revised opening" not in reloaded.content
    assert "\n\nRevised opening\n\n" in reloaded.content
    assert "> Opening move" not in reloaded.content


def test_update_beat_unknown_id_and_empty_body(client, session, story_with_character):
    story, _ = story_with_character
    ch, _, _ = _beat_chapter(session, story)

    missing = client.patch(
        f"/api/v2/stories/{story.id}/chapters/{ch.id}/beats/{uuid4()}",
        json={"content": "x"},
    )
    assert missing.status_code == 404

    no_changes = client.patch(
        f"/api/v2/stories/{story.id}/chapters/{ch.id}/beats/{uuid4()}",
        json={},
    )
    assert no_changes.status_code == 400


def test_update_beat_rejects_role_mismatch_and_empty(client, session, story_with_character):
    story, _ = story_with_character
    ch, user_id, _ = _beat_chapter(session, story)

    invalid_role = client.patch(
        f"/api/v2/stories/{story.id}/chapters/{ch.id}/beats/{user_id}",
        json={"role": "system_tts"},
    )
    assert invalid_role.status_code == 400

    empty = client.patch(
        f"/api/v2/stories/{story.id}/chapters/{ch.id}/beats/{user_id}",
        json={"content": "   "},
    )
    assert empty.status_code == 400


def test_delete_beat_removes_prose(client, session, story_with_character):
    story, _ = story_with_character
    ch, user_id, narr_id = _beat_chapter(session, story)
    ai_text = "A shadow slid across the courtyard wall."

    response = client.delete(f"/api/v2/stories/{story.id}/chapters/{ch.id}/beats/{narr_id}")
    assert response.status_code == 200

    from core.entities import StoryChapter as SC
    session.expire_all()
    reloaded = session.get(SC, ch.id)
    assert [b["id"] for b in reloaded.beats] == [user_id]
    assert ai_text not in reloaded.content
    assert "> Opening move" in reloaded.content


def test_revision_create_and_list(client, session, story_with_character):
    story, chapter = story_with_character
    from core.entities import StoryChapter as SC
    ch = session.get(SC, chapter.id)
    ch.content = "The harbor bells rang through the fog."
    session.add(ch)
    session.commit()

    created = client.post(f"/api/v2/stories/{story.id}/chapters/{ch.id}/revisions")
    assert created.status_code == 200
    body = created.json()
    assert body["source"] == "manual"
    assert body["word_count"] == 7
    assert "harbor bells" in body["preview"]

    listing = client.get(f"/api/v2/stories/{story.id}/chapters/{ch.id}/revisions")
    assert listing.status_code == 200
    items = listing.json()
    assert len(items) == 1
    assert items[0]["id"] == body["id"]

    rejected = client.post(
        f"/api/v2/stories/{story.id}/chapters/{ch.id}/revisions",
        json={"source": "pre_retry"},
    )
    assert rejected.status_code == 400


def test_restore_chapter_revision(client, session, story_with_character):
    story, chapter = story_with_character
    from core.entities import StoryChapter as SC
    ch = session.get(SC, chapter.id)
    original = "The gate creaked open onto an empty road."
    ch.content = original
    session.add(ch)
    session.commit()
    session.refresh(ch)

    snap = client.post(f"/api/v2/stories/{story.id}/chapters/{ch.id}/revisions")
    snap_id = snap.json()["id"]

    ch = session.get(SC, ch.id)
    ch.content = "Everything changed after that night."
    session.add(ch)
    session.commit()

    restored = client.post(f"/api/v2/stories/{story.id}/chapters/{ch.id}/revisions/{snap_id}/restore")
    assert restored.status_code == 200

    session.expire_all()
    reloaded = session.get(SC, ch.id)
    assert reloaded.content == original

    listing = client.get(f"/api/v2/stories/{story.id}/chapters/{ch.id}/revisions")
    sources = [r["source"] for r in listing.json()]
    assert "pre_restore" in sources
    assert sources[0] == "pre_restore"


def test_retry_last_creates_pre_retry_snapshot(client, session, story_with_character):
    story, _ = story_with_character
    ch, _, narr_id = _beat_chapter(session, story)

    response = client.post(f"/api/v2/stories/{story.id}/chapters/{ch.id}/retry-last")
    assert response.status_code == 200

    listing = client.get(f"/api/v2/stories/{story.id}/chapters/{ch.id}/revisions")
    sources = [r["source"] for r in listing.json()]
    assert "pre_retry" in sources


def test_beat_delete_creates_pre_delete_snapshot(client, session, story_with_character):
    story, _ = story_with_character
    ch, user_id, narr_id = _beat_chapter(session, story)

    response = client.delete(f"/api/v2/stories/{story.id}/chapters/{ch.id}/beats/{narr_id}")
    assert response.status_code == 200

    listing = client.get(f"/api/v2/stories/{story.id}/chapters/{ch.id}/revisions")
    assert any(r["source"] == "pre_beat_delete" for r in listing.json())


def test_revisions_cap_prunes_oldest(client, session, story_with_character):
    story, chapter = story_with_character
    from core.entities import StoryChapter as SC
    ch = session.get(SC, chapter.id)
    ch.content = f"content {chapter.id}"
    session.add(ch)
    session.commit()

    first_id = None
    for i in range(22):
        resp = client.post(f"/api/v2/stories/{story.id}/chapters/{ch.id}/revisions")
        if first_id is None:
            first_id = resp.json()["id"]

    listing = client.get(f"/api/v2/stories/{story.id}/chapters/{ch.id}/revisions").json()
    assert len(listing) <= 20
    assert all(r["id"] != first_id for r in listing)


def test_revision_endpoints_not_found(client, story_with_character):
    story, chapter = story_with_character
    assert client.get(f"/api/v2/stories/{story.id}/chapters/nope/revisions").status_code == 404
    assert client.post(f"/api/v2/stories/{story.id}/chapters/{chapter.id}/revisions/x/restore").status_code == 404


class TestStoryImageBudgetIsPersisted:
    """The "Autonomous Illustration" slider has to reach the budget.

    `max_agentic_images` was missing from `update_story`'s allow-list, so the
    PUT returned 200 and discarded it: the context panel's slider was inert and
    looked broken rather than ignored. Then even if it were stored,
    `_enqueue_story_continuation` only carried `max_agentic_depth`, so
    `get_max_agentic_images` fell through to the global default.
    """

    def test_update_story_persists_the_image_budget(self, client, session):
        world = World(name="W")
        session.add(world)
        session.commit()
        session.refresh(world)
        story = Story(title="s", world_id=world.id)
        session.add(story)
        session.commit()
        session.refresh(story)

        resp = client.put(f"/api/v2/stories/{story.id}", json={"max_agentic_images": 0})
        assert resp.status_code == 200, resp.text
        session.expire_all()
        assert session.get(Story, story.id).max_agentic_images == 0

    def test_zero_budget_turns_autonomous_illustration_off(self, client, session, monkeypatch):
        """0 is "off", not "unset" — the tools must not be attached at all.

        Otherwise the default of 2 still applies and the model keeps
        illustrating a story the user explicitly turned it off for.
        """
        world = World(name="W")
        session.add(world)
        session.commit()
        session.refresh(world)
        story = Story(title="s", world_id=world.id, max_agentic_depth=5, max_agentic_images=0)
        session.add(story)
        session.commit()
        session.refresh(story)
        chapter = StoryChapter(story_id=story.id, chapter_number=1, title="c1", content="text")
        session.add(chapter)
        session.commit()
        session.refresh(chapter)

        submitted = {}

        class _Submitted:
            id = "j1"

        async def _capture(_self, workflow, metadata=None, task_type=None, preferred_provider_id=None):
            submitted["workflow"] = workflow
            submitted["metadata"] = metadata
            return _Submitted()

        monkeypatch.setattr(
            "services.job_submission_service.JobSubmissionService.create_and_enqueue_job",
            _capture,
        )

        resp = client.post(f"/api/v2/stories/{story.id}/chapters/{chapter.id}/continue", json={})
        assert resp.status_code == 200, resp.text

        assert submitted["workflow"].get("tools", []) == []
        assert submitted["metadata"]["max_agentic_images"] == 0
        assert submitted["metadata"]["agentic"] is False
