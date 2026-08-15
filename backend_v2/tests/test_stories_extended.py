"""Tests for Story publish, export, narrate, and branching endpoints."""
from uuid import uuid4

import pytest

from core.entities import Story, StoryChapter, Character

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
