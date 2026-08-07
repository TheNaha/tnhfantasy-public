# Tests for the workspace-scoped gallery endpoints
# (GET /api/v2/chats/{id}/images and GET /api/v2/stories/{id}/images)

from sqlmodel import Session, select

from core.entities import Chat, Message, MessageRole, Story, StoryChapter


def _seed_chat(session: Session) -> str:
    chat = Chat(name="Test Chat")
    session.add(chat)
    session.commit()
    session.refresh(chat)
    for content, path in [
        ("First", "2026/08/07/first.png"),
        ("Second", None),
        ("Third", "2026/08/07/third.png"),
    ]:
        msg = Message(
            role=MessageRole.SYSTEM,
            content=content,
            image_path=path,
            chat_id=chat.id,
        )
        session.add(msg)
    session.commit()
    return chat.id


def _seed_story(session: Session) -> str:
    story = Story(title="Test Story")
    session.add(story)
    session.commit()
    session.refresh(story)
    ch1 = StoryChapter(title="Ch 1", story_id=story.id, content="a", image_paths=["2026/08/07/a.png"])
    ch2 = StoryChapter(title="Ch 2", story_id=story.id, content="b", image_paths=["2026/08/07/b.png", "2026/08/07/c.png"])
    ch3 = StoryChapter(title="Ch 3", story_id=story.id, content="c", image_paths=[])
    session.add_all([ch1, ch2, ch3])
    session.commit()
    return story.id


def test_list_chat_images(client, session):
    chat_id = _seed_chat(session)
    resp = client.get(f"/api/v2/chats/{chat_id}/images")
    assert resp.status_code == 200
    images = resp.json()
    paths = [img["path"] for img in images]
    assert "2026/08/07/third.png" in paths
    assert "2026/08/07/first.png" in paths
    assert len(images) == 2
    # newest first
    assert images[0]["path"] == "2026/08/07/third.png"


def test_list_chat_images_404(client, session):
    resp = client.get("/api/v2/chats/missing-chat/images")
    assert resp.status_code == 404


def test_list_story_images(client, session):
    story_id = _seed_story(session)
    resp = client.get(f"/api/v2/stories/{story_id}/images")
    assert resp.status_code == 200
    images = resp.json()
    paths = [img["path"] for img in images]
    assert paths == ["2026/08/07/a.png", "2026/08/07/b.png", "2026/08/07/c.png"]
    assert images[1]["chapter_id"] is not None
    assert images[1]["chapter_title"] == "Ch 2"


def test_list_story_images_404(client, session):
    resp = client.get("/api/v2/stories/missing-story/images")
    assert resp.status_code == 404
