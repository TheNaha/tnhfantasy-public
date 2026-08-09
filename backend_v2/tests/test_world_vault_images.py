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


def test_continue_story_queues_llm_job(client, session, monkeypatch):
    from unittest.mock import AsyncMock

    story_id = _seed_story(session)
    chapter_id = session.exec(select(StoryChapter)).first().id

    async def fake_build_chat_context_async(*args, **kwargs):
        return ("system prompt", [{"role": "user", "content": "the story so far"}])

    enqueue = AsyncMock(return_value=True)

    monkeypatch.setattr("services.context_builder.build_chat_context_async", fake_build_chat_context_async)
    monkeypatch.setattr("services.llm_config.get_default_llm_model", lambda: "test-model")
    monkeypatch.setattr("services.job_queue.queue_manager.enqueue", enqueue)

    resp = client.post(f"/api/v2/stories/{story_id}/chapters/{chapter_id}/continue", json={"prompt": "Go west"})
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]
    assert job_id

    enqueue.assert_awaited_once()
    assert enqueue.await_args.kwargs["task_type"] == "llm"

    from core.entities import Job

    job = session.get(Job, job_id)
    assert job is not None
    assert job.task_type == "llm"
    assert job.workflow["type"] == "story_continue"
    assert job.metadata_["workspace"] == "story"
    assert job.metadata_["story_id"] == story_id
    assert job.metadata_["chapter_id"] == chapter_id

    chapter = session.get(StoryChapter, chapter_id)
    assert chapter.beats[-1]["role"] == "user"
    assert chapter.beats[-1]["content"] == "Go west"
    assert chapter.beats[-1]["id"]
    assert chapter.beats[-1]["parent_beat_id"] is None
    assert "> Go west" in chapter.content


def test_continue_story_404(client, session):
    resp = client.post("/api/v2/stories/missing/chapters/missing/continue", json={"prompt": ""})
    assert resp.status_code == 404


def test_add_beat_assigns_ids_and_parent(client, session):
    story_id = _seed_story(session)
    chapter = session.exec(select(StoryChapter).where(StoryChapter.story_id == story_id).order_by(StoryChapter.chapter_number)).first()

    resp = client.post(
        f"/api/v2/stories/{story_id}/chapters/{chapter.id}/beats",
        json={"content": "first beat", "role": "user"},
    )
    assert resp.status_code == 200
    resp = client.post(
        f"/api/v2/stories/{story_id}/chapters/{chapter.id}/beats",
        json={"content": "second beat", "role": "user"},
    )
    assert resp.status_code == 200

    chapter = session.get(StoryChapter, chapter.id)
    assert len(chapter.beats) == 2
    assert chapter.beats[0]["id"]
    assert chapter.beats[0]["parent_beat_id"] is None
    assert chapter.beats[1]["id"]
    assert chapter.beats[1]["parent_beat_id"] == chapter.beats[0]["id"]


def test_branch_chapter_forks_history(client, session):
    story_id = _seed_story(session)
    chapter = session.exec(select(StoryChapter).where(StoryChapter.story_id == story_id).order_by(StoryChapter.chapter_number)).first()
    chapter.beats = [
        {"id": "b1", "parent_beat_id": None, "role": "narrator", "content": "The hero wakes up."},
        {"id": "b2", "parent_beat_id": "b1", "role": "user", "content": "He rides east."},
        {"id": "b3", "parent_beat_id": "b2", "role": "narrator", "content": "A storm gathers."},
    ]
    session.add(chapter)
    session.commit()

    resp = client.post(
        f"/api/v2/stories/{story_id}/chapters/{chapter.id}/branch",
        json={"from_beat_id": "b2", "prompt": "He rides west instead"},
    )
    assert resp.status_code == 200, resp.text
    branch = resp.json()
    assert branch["id"] != chapter.id
    assert branch["chapter_number"] == 2
    assert branch["title"].startswith("Branch from")

    beats = branch["beats"]
    assert [b["id"] for b in beats[:2]] == ["b1", "b2"]
    assert beats[-1]["id"]
    assert beats[-1]["id"] not in ("b1", "b2")
    assert beats[-1]["role"] == "user"
    assert beats[-1]["content"] == "He rides west instead"
    assert beats[-1]["parent_beat_id"] == "b2"
    assert "He rides east." in branch["content"]
    assert "He rides west instead" in branch["content"]
    assert "A storm gathers." not in branch["content"]

    db_branch = session.get(StoryChapter, branch["id"])
    assert db_branch is not None
    assert db_branch.story_id == story_id


def test_branch_chapter_backfills_legacy_beat_ids(client, session):
    story_id = _seed_story(session)
    chapter = session.exec(select(StoryChapter).where(StoryChapter.story_id == story_id).order_by(StoryChapter.chapter_number)).first()
    chapter.beats = [
        {"role": "narrator", "content": "The hero wakes up."},
        {"role": "user", "content": "He rides east."},
    ]
    session.add(chapter)
    session.commit()

    # Lazy backfill happens on GET, giving the frontend ids to branch from
    resp = client.get(f"/api/v2/stories/{story_id}/chapters/{chapter.id}")
    assert resp.status_code == 200
    beats = resp.json()["beats"]
    assert all(b["id"] for b in beats)

    resp = client.post(
        f"/api/v2/stories/{story_id}/chapters/{chapter.id}/branch",
        json={"from_beat_id": beats[0]["id"]},
    )
    assert resp.status_code == 200, resp.text
    branch = resp.json()
    assert len(branch["beats"]) == 1
    assert branch["beats"][0]["id"] == beats[0]["id"]


def test_branch_chapter_404(client, session):
    story_id = _seed_story(session)
    chapter = session.exec(select(StoryChapter)).first()

    resp = client.post(
        f"/api/v2/stories/{story_id}/chapters/{chapter.id}/branch",
        json={"from_beat_id": "missing-beat"},
    )
    assert resp.status_code == 404

    resp = client.post(
        f"/api/v2/stories/missing/chapters/{chapter.id}/branch",
        json={"from_beat_id": "missing-beat"},
    )
    assert resp.status_code == 404


def test_illustrate_chat_queues_image_job(client, session, monkeypatch):
    from unittest.mock import AsyncMock

    from core.entities import Character, Job

    char = Character(name="Aria", checkpoint="aria_checkpoint.safetensors", lora="aria_lora")
    session.add(char)
    session.commit()
    session.refresh(char)
    chat = Chat(name="Illustrate Test", character_id=char.id)
    session.add(chat)
    session.commit()
    session.refresh(chat)

    enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr("services.job_queue.queue_manager.enqueue", enqueue)

    resp = client.post(f"/api/v2/chats/{chat.id}/illustrate", json={"image_prompt": "A dragon"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    job_id = body["job_id"]
    assert job_id

    enqueue.assert_awaited_once()
    assert enqueue.await_args.kwargs["task_type"] == "image"

    job = session.get(Job, job_id)
    assert job is not None
    assert job.task_type == "image"
    assert job.metadata_["source"] == "chat_image"
    assert job.metadata_["workspace"] == "roleplay"
    assert job.metadata_["chat_id"] == chat.id
    assert job.metadata_["checkpoint"] == "aria_checkpoint.safetensors"
    assert job.metadata_["loras"] == ["aria_lora"]
    assert job.workflow["6"]["inputs"]["text"] == "A dragon"


def test_illustrate_chat_falls_back_to_latest_reply(client, session, monkeypatch):
    from unittest.mock import AsyncMock

    from core.entities import Job

    chat = Chat(name="Fallback Test")
    session.add(chat)
    session.commit()
    session.refresh(chat)
    session.add_all(
        [
            Message(role=MessageRole.USER, content="Draw something", chat_id=chat.id),
            Message(role=MessageRole.CHAR, content="The heroine stares at the horizon.", chat_id=chat.id),
        ]
    )
    session.commit()

    enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr("services.job_queue.queue_manager.enqueue", enqueue)

    resp = client.post(f"/api/v2/chats/{chat.id}/illustrate", json={"image_prompt": ""})
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]
    job = session.get(Job, job_id)
    assert job.metadata_["prompt"] == "The heroine stares at the horizon."
    assert job.workflow["6"]["inputs"]["text"] == "The heroine stares at the horizon."


def test_illustrate_chat_without_prompt_or_reply_400(client, session):
    chat = Chat(name="Empty Test")
    session.add(chat)
    session.commit()
    session.refresh(chat)
    resp = client.post(f"/api/v2/chats/{chat.id}/illustrate", json={"image_prompt": ""})
    assert resp.status_code == 400


def test_illustrate_chat_disabled_400(client, session):
    chat = Chat(name="Disabled Test", allow_image_generation=False)
    session.add(chat)
    session.commit()
    session.refresh(chat)
    resp = client.post(f"/api/v2/chats/{chat.id}/illustrate", json={"image_prompt": "A dragon"})
    assert resp.status_code == 400


def test_illustrate_chat_404(client, session):
    resp = client.post("/api/v2/chats/missing-chat/illustrate", json={"image_prompt": "A dragon"})
    assert resp.status_code == 404
