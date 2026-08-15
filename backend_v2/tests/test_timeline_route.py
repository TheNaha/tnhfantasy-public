"""Route tests for the World Timeline aggregation endpoint.

Verifies the unified chronological feed across messages, story chapters,
character memories, and image assets, plus the character/chat/location/story
filters and pagination.
"""

from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from core.entities import Asset, Character, CharacterMemory, Chat, Message, MessageKind, MessageRole, Story, StoryChapter


def _seed_chat_with_messages(session: Session, char: Character, content: str = "Hello there"):
    chat = Chat(name="Chat", character_id=char.id, story_location="Mistvale")
    session.add(chat)
    session.commit()
    session.refresh(chat)
    msg = Message(role=MessageRole.CHAR, content=content, chat_id=chat.id, kind=MessageKind.CHAR)
    session.add(msg)
    session.commit()
    session.refresh(msg)
    return chat, msg


def _seed_story_chapter(session: Session, title: str = "Chapter One"):
    story = Story(title="Tale")
    session.add(story)
    session.commit()
    session.refresh(story)
    chapter = StoryChapter(story_id=story.id, chapter_number=1, title=title, content="Once upon a time...")
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    return story, chapter


class TestTimelineAggregation:
    def test_timeline_contains_message_event(self, client, session):
        char = Character(name="Aria")
        session.add(char)
        session.commit()
        session.refresh(char)
        chat, msg = _seed_chat_with_messages(session, char)

        resp = client.get("/api/v2/timeline/timeline")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] >= 1
        events = body["events"]
        msg_events = [e for e in events if e["type"] == "message" and e["id"] == msg.id]
        assert len(msg_events) == 1
        event = msg_events[0]
        assert event["chat_id"] == chat.id
        assert event["character_id"] == char.id
        assert event["description"] == "Hello there"
        assert event["kind"] == MessageRole.CHAR.value

    def test_timeline_contains_chapter_event(self, client, session):
        story, chapter = _seed_story_chapter(session)

        resp = client.get("/api/v2/timeline/timeline")
        events = resp.json()["events"]
        chapter_events = [e for e in events if e["type"] == "chapter" and e["id"] == chapter.id]
        assert len(chapter_events) == 1
        assert chapter_events[0]["story_id"] == story.id
        assert chapter_events[0]["title"] == "Chapter 1: Chapter One"

    def test_timeline_contains_memory_event(self, client, session):
        char = Character(name="Kira")
        session.add(char)
        session.commit()
        session.refresh(char)
        memory = CharacterMemory(character_id=char.id, content="Remembers the old castle", importance=8)
        session.add(memory)
        session.commit()
        session.refresh(memory)

        resp = client.get("/api/v2/timeline/timeline")
        events = resp.json()["events"]
        memory_events = [e for e in events if e["type"] == "memory" and e["id"] == memory.id]
        assert len(memory_events) == 1
        assert memory_events[0]["character_id"] == char.id
        assert memory_events[0]["importance"] == 8

    def test_timeline_contains_asset_event(self, client, session):
        char = Character(name="Nova")
        session.add(char)
        session.commit()
        session.refresh(char)
        asset = Asset(filename="scene.png", relative_path="default_user/chat/2026/08/09/scene.png", character_id=char.id)
        session.add(asset)
        session.commit()
        session.refresh(asset)

        resp = client.get("/api/v2/timeline/timeline")
        events = resp.json()["events"]
        asset_events = [e for e in events if e["type"] == "asset" and e["id"] == asset.id]
        assert len(asset_events) == 1
        assert asset_events[0]["character_id"] == char.id
        assert asset_events[0]["kind"] == "image"
        assert asset_events[0]["title"] == f"Image: {asset.filename}"

    def test_timeline_sorted_descending(self, client, session):
        char = Character(name="Sort")
        session.add(char)
        session.commit()
        session.refresh(char)
        old_chat = Chat(name="Old", character_id=char.id)
        session.add(old_chat)
        session.commit()
        session.refresh(old_chat)
        base = datetime.now(timezone.utc) - timedelta(days=1)
        old_msg = Message(role=MessageRole.USER, content="old", chat_id=old_chat.id, created_at=base)
        session.add(old_msg)
        session.commit()
        new_chat, new_msg = _seed_chat_with_messages(session, char, content="new")

        events = client.get("/api/v2/timeline/timeline").json()["events"]
        new_idx = next(i for i, e in enumerate(events) if e["id"] == new_msg.id)
        old_idx = next(i for i, e in enumerate(events) if e["id"] == old_msg.id)
        assert new_idx < old_idx


class TestTimelineFilters:
    def test_filter_by_character(self, client, session):
        char_a = Character(name="Alpha")
        char_b = Character(name="Beta")
        session.add(char_a)
        session.add(char_b)
        session.commit()
        session.refresh(char_a)
        session.refresh(char_b)
        chat_a, _ = _seed_chat_with_messages(session, char_a, content="from alpha")
        chat_b, _ = _seed_chat_with_messages(session, char_b, content="from beta")

        events = client.get("/api/v2/timeline/timeline", params={"character_id": char_a.id}).json()["events"]
        msg_events = [e for e in events if e["type"] == "message"]
        assert all(e["character_id"] == char_a.id for e in msg_events)
        assert any(e["chat_id"] == chat_a.id for e in msg_events)
        assert not any(e["chat_id"] == chat_b.id for e in msg_events)

    def test_filter_by_chat(self, client, session):
        char = Character(name="Chatty")
        session.add(char)
        session.commit()
        session.refresh(char)
        chat_a, _ = _seed_chat_with_messages(session, char, content="in chat a")
        chat_b, _ = _seed_chat_with_messages(session, char, content="in chat b")

        events = client.get("/api/v2/timeline/timeline", params={"chat_id": chat_a.id}).json()["events"]
        msg_events = [e for e in events if e["type"] == "message"]
        assert all(e["chat_id"] == chat_a.id for e in msg_events)

    def test_filter_by_location(self, client, session):
        char = Character(name="Loc")
        session.add(char)
        session.commit()
        session.refresh(char)
        chat_in = Chat(name="In", character_id=char.id, story_location="Mistvale")
        chat_out = Chat(name="Out", character_id=char.id, story_location="Desert")
        session.add(chat_in)
        session.add(chat_out)
        session.commit()
        session.refresh(chat_in)
        session.refresh(chat_out)
        session.add(Message(role=MessageRole.USER, content="here", chat_id=chat_in.id))
        session.add(Message(role=MessageRole.USER, content="elsewhere", chat_id=chat_out.id))
        session.commit()

        events = client.get("/api/v2/timeline/timeline", params={"location": "Mistvale"}).json()["events"]
        msg_events = [e for e in events if e["type"] == "message"]
        assert len(msg_events) == 1
        assert msg_events[0]["chat_id"] == chat_in.id

    def test_filter_by_story(self, client, session):
        story, chapter = _seed_story_chapter(session)
        other_story = Story(title="Other")
        session.add(other_story)
        session.commit()
        session.refresh(other_story)
        session.add(StoryChapter(story_id=other_story.id, chapter_number=1, title="Other Chapter", content="x"))
        session.commit()

        events = client.get("/api/v2/timeline/timeline", params={"story_id": story.id}).json()["events"]
        chapter_events = [e for e in events if e["type"] == "chapter"]
        assert len(chapter_events) == 1
        assert chapter_events[0]["id"] == chapter.id


class TestTimelinePagination:
    def test_limit_and_offset(self, client, session):
        char = Character(name="Page")
        session.add(char)
        session.commit()
        session.refresh(char)
        for i in range(5):
            chat = Chat(name=f"Chat {i}", character_id=char.id)
            session.add(chat)
            session.commit()
            session.refresh(chat)
            session.add(Message(role=MessageRole.USER, content=f"msg {i}", chat_id=chat.id))
        session.commit()

        body = client.get("/api/v2/timeline/timeline", params={"limit": 2, "offset": 0}).json()
        assert body["limit"] == 2
        assert body["offset"] == 0
        assert len(body["events"]) == 2
        assert body["total"] >= 5

        second = client.get("/api/v2/timeline/timeline", params={"limit": 2, "offset": 2}).json()
        assert second["events"][0]["id"] != body["events"][0]["id"]
        assert second["events"][0]["id"] != body["events"][1]["id"]

    def test_limit_capped(self, client):
        resp = client.get("/api/v2/timeline/timeline", params={"limit": 9999})
        assert resp.status_code == 422