"""Tests for Story publish, export, narrate, and branching endpoints."""
from uuid import uuid4

import pytest
from PIL import Image as PILImage

import config as app_config
from api.routes.world_vault.stories import (
    _collect_story_illustration_assets,
    _resolve_story_image_path,
)
from core.entities import Story, StoryChapter, Character, Asset, AssetKind

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
        memory="Written by TNHComfy",
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


def test_narrate_chapter(client, session, story_with_character):
    story, chapter = story_with_character
    response = client.post(f"/api/v2/stories/{story.id}/chapters/{chapter.id}/narrate")
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data


def test_narrate_chapter_not_found(client):
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


def test_retry_last_trims_beat_and_content_then_requeues(client, session, story_with_character):
    story, chapter = story_with_character
    from core.entities import StoryChapter as SC
    ch = session.get(SC, chapter.id)
    ai_text = "A shadow slid across the courtyard wall."
    ch.beats = [
        {"id": str(uuid4()), "parent_beat_id": None, "role": "user", "content": "Opening move"},
        {"id": str(uuid4()), "parent_beat_id": None, "role": "narrator", "content": ai_text},
    ]
    ch.content = "Once upon a time...\n\n> Opening move\n\n" + f"\n\n{ai_text}\n\n"
    session.add(ch)
    session.commit()
    session.refresh(ch)

    response = client.post(f"/api/v2/stories/{story.id}/chapters/{ch.id}/retry-last")
    assert response.status_code == 200
    assert response.json()["job_id"]

    session.expire_all()
    reloaded = session.get(SC, ch.id)
    assert len(reloaded.beats) == 1
    assert reloaded.beats[0]["role"] == "user"
    assert ai_text not in reloaded.content
    assert "Opening move" in reloaded.content


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

    # absolute existing path resolves as-is
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
