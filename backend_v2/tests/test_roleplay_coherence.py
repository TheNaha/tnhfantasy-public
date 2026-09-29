"""Integration tests for the roleplay coherence work.

These pin the changes that make the World a real grouping, the chat path match
the story path, and the prompt stop duplicating and dropping content. Every one
was run against the pre-fix code and observed to fail.
"""

import pytest

from core.entities import (
    Message,
    Chat,
    Character,
    Location,
    Lorebook,
    LorebookEntry,
    Scenario,
    Story,
    StoryChapter,
    World,
)
from services.context_builder import (
    build_system_prompt_sections,
    chat_context_kwargs,
)


def _seed(session, **kw):
    entity = kw.pop("_cls", Character)(**kw)
    session.add(entity)
    session.commit()
    session.refresh(entity)
    return entity


def _prompt(session, chat, characters=None):
    kwargs = chat_context_kwargs(chat, characters=characters, session=session)
    return build_system_prompt_sections(session, **kwargs)


# ---------------------------------------------------------------------------
# The World is a real grouping, not a label
# ---------------------------------------------------------------------------


class TestWorldReachesThePrompt:
    def test_a_chat_with_a_world_gets_its_description(self, session):
        world = _seed(session, _cls=World, name="Drowned Bell", description="A tavern at the end of a pier.")
        chat = _seed(session, _cls=Chat, name="c", chat_type="chat", world_id=world.id)

        keys = {s["key"] for s in _prompt(session, chat)}
        assert "world" in keys

    def test_the_world_block_carries_its_prose(self, session):
        world = _seed(session, _cls=World, name="Drowned Bell", description="A tavern at the end of a pier.")
        chat = _seed(session, _cls=Chat, name="c", chat_type="chat", world_id=world.id)

        block = next(s for s in _prompt(session, chat) if s["key"] == "world")
        assert "Drowned Bell" in block["content"]
        assert "end of a pier" in block["content"]

    def test_the_worlds_lorebooks_are_injected(self, session):
        lorebook = _seed(session, _cls=Lorebook, name="Pier", description="d")
        entry = _seed(session, _cls=LorebookEntry, lorebook_id=lorebook.id, content="The tide is wrong.", keys=["tide"])
        assert entry.id
        world = _seed(session, _cls=World, name="W", description="d", lorebook_ids=[lorebook.id])
        chat = _seed(session, _cls=Chat, name="c", chat_type="chat", world_id=world.id)

        block = next(s for s in _prompt(session, chat) if s["key"] == "lorebook")
        assert "The tide is wrong." in block["content"]

    def test_the_chats_own_lorebooks_still_win_and_come_first(self, session):
        mine = _seed(session, _cls=Lorebook, name="Mine")
        _seed(session, _cls=LorebookEntry, lorebook_id=mine.id, content="MINE", keys=["m"])
        theirs = _seed(session, _cls=Lorebook, name="Theirs")
        _seed(session, _cls=LorebookEntry, lorebook_id=theirs.id, content="THEIRS", keys=["t"])

        world = _seed(session, _cls=World, name="W", description="d", lorebook_ids=[theirs.id])
        chat = _seed(
            session, _cls=Chat, name="c", chat_type="chat",
            world_id=world.id, active_lorebook_ids=[mine.id],
        )

        merged = chat_context_kwargs(chat, session=session)["lorebook_ids"]
        assert merged == [mine.id, theirs.id]

    def test_the_worlds_locations_are_injected(self, session):
        loc = _seed(session, _cls=Location, name="The Cellar", description="Damp.")
        world = _seed(session, _cls=World, name="W", description="d", location_ids=[loc.id])
        chat = _seed(session, _cls=Chat, name="c", chat_type="chat", world_id=world.id)

        prompt = "\n\n".join(s["content"] for s in _prompt(session, chat))
        assert "The Cellar" in prompt

    def test_the_worlds_scenario_becomes_a_directive(self, session):
        scenario = _seed(session, _cls=Scenario, name="Storm", prompt_template="A storm breaks.")
        world = _seed(session, _cls=World, name="W", description="d", scenario_ids=[scenario.id])
        chat = _seed(session, _cls=Chat, name="c", chat_type="chat", world_id=world.id)

        block = next(s for s in _prompt(session, chat) if s["key"] == "story_scenario")
        assert "A storm breaks." in block["content"]

    def test_the_world_scenario_does_not_override_one_the_chat_owns(self, session):
        scenario = _seed(session, _cls=Scenario, name="Storm", prompt_template="WORLD ONE")
        world = _seed(session, _cls=World, name="W", description="d", scenario_ids=[scenario.id])
        chat = _seed(session, _cls=Chat, name="c", chat_type="chat", world_id=world.id)

        kwargs = chat_context_kwargs(chat, session=session, story_scenario="CHAT ONE")
        assert kwargs["story_scenario"] == "CHAT ONE"

    def test_a_chat_with_no_world_is_byte_identical_to_before(self, session):
        """A missing World must never be worse than the behaviour that existed
        before Worlds were wired to anything."""
        chat = _seed(session, _cls=Chat, name="c", chat_type="chat")
        keys = {s["key"] for s in _prompt(session, chat)}
        assert "world" not in keys
        assert "lorebook" not in keys

    def test_a_world_whose_entities_were_deleted_does_not_crash(self, session):
        world = _seed(
            session,
            _cls=World,
            name="W",
            description="d",
            lorebook_ids=["gone-lorebook"],
            location_ids=["gone-location"],
            scenario_ids=["gone-scenario"],
        )
        chat = _seed(session, _cls=Chat, name="c", chat_type="chat", world_id=world.id)
        _prompt(session, chat)  # must not raise


class TestWorldMembershipIsWritable:
    def test_a_world_accepts_its_membership_on_create(self, client, session):
        lorebook = _seed(session, _cls=Lorebook, name="L", description="d")
        scenario = _seed(session, _cls=Scenario, name="S", prompt_template="p")
        loc = _seed(session, _cls=Location, name="Loc", description="d")

        response = client.post(
            "/api/v2/worlds",
            json={
                "name": "W",
                "lorebook_ids": [lorebook.id],
                "scenario_ids": [scenario.id],
                "location_ids": [loc.id],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["lorebook_ids"] == [lorebook.id]
        assert body["scenario_ids"] == [scenario.id]

    def test_an_unknown_member_is_a_404_not_a_stored_dangling_id(self, client):
        response = client.post(
            "/api/v2/worlds", json={"name": "W", "lorebook_ids": ["does-not-exist"]}
        )
        assert response.status_code == 404

    def test_membership_can_be_updated(self, client, session):
        world = _seed(session, _cls=World, name="W", description="d")
        lorebook = _seed(session, _cls=Lorebook, name="L", description="d")
        response = client.put(
            f"/api/v2/worlds/{world.id}", json={"lorebook_ids": [lorebook.id]}
        )
        assert response.status_code == 200
        assert response.json()["lorebook_ids"] == [lorebook.id]


# ---------------------------------------------------------------------------
# Character -> lorebook, the one missing link
# ---------------------------------------------------------------------------


class TestCharacterLorebooks:
    def test_a_characters_lorebooks_reach_the_prompt(self, session):
        lorebook = _seed(session, _cls=Lorebook, name="L", description="d")
        _seed(session, _cls=LorebookEntry, lorebook_id=lorebook.id, content="She was a doctor.", keys=["doctor"])
        char = _seed(session, name="Ada", description="a doctor", lorebook_ids=[lorebook.id])
        chat = _seed(session, _cls=Chat, name="c", chat_type="chat", character_id=char.id)

        block = next(s for s in _prompt(session, chat, characters=[char]) if s["key"] == "lorebook")
        assert "She was a doctor." in block["content"]

    def test_the_chats_own_lorebooks_come_first(self, session):
        mine = _seed(session, _cls=Lorebook, name="Mine")
        _seed(session, _cls=LorebookEntry, lorebook_id=mine.id, content="MINE", keys=["m"])
        char_book = _seed(session, _cls=Lorebook, name="Char")
        _seed(session, _cls=LorebookEntry, lorebook_id=char_book.id, content="CHAR", keys=["c"])

        char = _seed(session, name="Ada", description="d", lorebook_ids=[char_book.id])
        chat = _seed(
            session, _cls=Chat, name="c", chat_type="chat",
            character_id=char.id, active_lorebook_ids=[mine.id],
        )
        merged = chat_context_kwargs(chat, characters=[char], session=session)["lorebook_ids"]
        assert merged == [mine.id, char_book.id]

    def test_it_is_resolved_on_every_build_not_snapshotted_at_creation(self, session):
        """The point of the field: a chat that already exists picks up a book
        attached to its character afterwards."""
        char = _seed(session, name="Ada", description="d")
        chat = _seed(session, _cls=Chat, name="c", chat_type="chat", character_id=char.id)
        assert chat_context_kwargs(chat, characters=[char], session=session)["lorebook_ids"] is None

        book = _seed(session, _cls=Lorebook, name="Late", description="d")
        char.lorebook_ids = [book.id]
        session.add(char)
        session.commit()
        session.refresh(char)

        assert chat_context_kwargs(chat, characters=[char], session=session)["lorebook_ids"] == [book.id]

    def test_it_can_be_written_through_the_api(self, client, session):
        book = _seed(session, _cls=Lorebook, name="L", description="d")
        char = _seed(session, name="Ada", description="d")

        assert client.patch(
            f"/api/v2/characters/{char.id}", json={"lorebook_ids": [book.id]}
        ).status_code == 200
        session.expire_all()
        assert session.get(Character, char.id).lorebook_ids == [book.id]

        assert client.put(
            f"/api/v2/characters/{char.id}", json={"lorebook_ids": []}
        ).status_code == 200
        session.expire_all()
        assert session.get(Character, char.id).lorebook_ids == []

    def test_an_unknown_lorebook_is_a_404(self, client, session):
        char = _seed(session, name="Ada", description="d")
        assert client.patch(
            f"/api/v2/characters/{char.id}", json={"lorebook_ids": ["nope"]}
        ).status_code == 404

    def test_deleting_a_lorebook_scrubs_the_character_link(self, client, session):
        book = _seed(session, _cls=Lorebook, name="L", description="d")
        char = _seed(session, name="Ada", description="d", lorebook_ids=[book.id])
        session.commit()

        assert client.delete(f"/api/v2/lorebooks/{book.id}").status_code == 200
        session.expire_all()
        assert session.get(Character, char.id).lorebook_ids == []


# ---------------------------------------------------------------------------
# The prompt was paying for the same prose twice
# ---------------------------------------------------------------------------


class TestNoDuplicateInjection:
    def test_a_character_is_not_rendered_as_both_a_card_and_a_story_block(self, session):
        char = _seed(session, name="Ada", description="A DISTINCTIVE DESCRIPTION", personality="kindly")
        chat = _seed(session, _cls=Chat, name="c", chat_type="chat", character_id=char.id)

        prompt = "\n\n".join(s["content"] for s in _prompt(session, chat, characters=[char]))
        assert prompt.count("A DISTINCTIVE DESCRIPTION") == 1

    def test_a_story_still_gets_its_characters(self, session):
        """The dedupe must not empty the block that exists for stories."""
        other = _seed(session, name="Bo", description="A SECOND DESCRIPTION")

        sections = build_system_prompt_sections(
            session, story_character_ids=[other.id], character_id=None
        )
        prompt = "\n\n".join(s["content"] for s in sections)
        assert "A SECOND DESCRIPTION" in prompt

    def test_a_story_with_a_loaded_character_card_still_shows_the_other_one(self, session):
        char = _seed(session, name="Ada", description="PRIMARY")
        other = _seed(session, name="Bo", description="SECONDARY")
        sections = build_system_prompt_sections(
            session, characters=[char], story_character_ids=[char.id, other.id], character_id=None
        )
        prompt = "\n\n".join(s["content"] for s in sections)
        assert prompt.count("PRIMARY") == 1
        assert "SECONDARY" in prompt


# ---------------------------------------------------------------------------
# Content that was authored and silently dropped
# ---------------------------------------------------------------------------


class TestNothingSilentlyDropped:
    def test_a_scenario_template_gets_its_macros_expanded(self, session):
        """`{{user}}` in a scenario reached the model as literal braces: the
        substitution loop ran before this section was even built, and its
        allowlist did not include it."""
        scenario = _seed(
            session, _cls=Scenario, name="S", prompt_template="{{user}} meets {{char}} at the pier."
        )
        char = _seed(session, name="Ada", description="d")
        sections = build_system_prompt_sections(
            session,
            characters=[char],
            story_scenario=scenario.prompt_template,
            persona_name="Rin",
        )
        block = next(s for s in sections if s["key"] == "story_scenario")
        assert "{{user}}" not in block["content"]
        assert "Rin meets Ada" in block["content"]

    def test_a_lorebook_entry_gets_its_macros_expanded_too(self, session):
        char = _seed(session, name="Ada", description="d")
        sections = build_system_prompt_sections(
            session, characters=[char], persona_name="Rin",
            lorebook_ids=[], world_description="{{char}} rules {{user}}'s pier",
        )
        block = next(s for s in sections if s["key"] == "world")
        assert "{{char}}" not in block["content"]

    def test_applying_a_scenario_to_a_chat_keeps_the_character_card(self, client, session):
        """One click on the Scenarios page used to delete the character's
        description, personality, system_prompt, append block and example
        dialogue from every subsequent turn, with nothing shown to the user."""
        # No `system_prompt`, so the card is the auto-built one and carries the
        # description — that is what has to survive.
        char = _seed(session, name="Ada", description="A DISTINCTIVE DESCRIPTION", personality="kindly")
        chat = _seed(session, _cls=Chat, name="c", chat_type="chat", character_id=char.id)
        scenario = _seed(session, _cls=Scenario, name="S", prompt_template="A storm breaks.")

        response = client.post(
            f"/api/v2/scenarios/{scenario.id}/apply",
            json={"target_type": "chat", "target_id": chat.id},
        )
        assert response.status_code == 200, response.text

        session.expire_all()
        refreshed = session.get(Chat, chat.id)
        assert refreshed.system_prompt_override is None
        assert "A storm breaks." in (refreshed.append_system_prompt or "")

        prompt = "\n\n".join(
            s["content"] for s in _prompt(session, refreshed, characters=[session.get(Character, char.id)])
        )
        assert "A DISTINCTIVE DESCRIPTION" in prompt
        assert "A storm breaks." in prompt

    def test_applying_the_same_scenario_twice_does_not_duplicate_it(self, client, session):
        chat = _seed(session, _cls=Chat, name="c", chat_type="chat")
        scenario = _seed(session, _cls=Scenario, name="S", prompt_template="A storm breaks.")
        for _ in range(2):
            client.post(
                f"/api/v2/scenarios/{scenario.id}/apply",
                json={"target_type": "chat", "target_id": chat.id},
            )
        session.expire_all()
        assert session.get(Chat, chat.id).append_system_prompt.count("A storm breaks.") == 1

    def test_a_chat_context_budget_cannot_be_set_outside_the_global_range(self, client, session):
        """The global setting is range-checked 1024-32768; the per-chat override
        bypassed it, and the value is a paid prompt size."""
        chat = _seed(session, _cls=Chat, name="c", chat_type="chat")
        assert client.patch(
            f"/api/v2/chats/{chat.id}", json={"max_context_tokens": 10**7}
        ).status_code == 400
        assert client.patch(
            f"/api/v2/chats/{chat.id}", json={"max_context_tokens": 16}
        ).status_code == 400
        assert client.patch(
            f"/api/v2/chats/{chat.id}", json={"max_context_tokens": 8192}
        ).status_code == 200


class TestLorebookQueryKeysOnTheLatestTurn:
    def test_the_newest_turn_comes_first_in_the_embedding_query(self, session, monkeypatch):
        """Ordered oldest-first, the 512-token truncation meant the embedding
        was of the oldest of the last six messages and never contained the
        user's actual turn."""
        from services import context_builder

        seen: list[str] = []
        original = context_builder.build_system_prompt_sections

        def _capture(_session, *, _lorebook_query=None, **kwargs):
            seen.append(_lorebook_query or "")
            return original(_session, _lorebook_query=_lorebook_query, **kwargs)

        monkeypatch.setattr(context_builder, "build_system_prompt_sections", _capture)
        context_builder.build_chat_context_with_sections(
            session,
            [
                {"role": "user", "content": "OLDEST MARKER"},
                {"role": "char", "content": "oldest reply"},
                {"role": "user", "content": "NEWEST MARKER"},
            ],
        )
        assert seen
        query = seen[0]
        assert query.index("NEWEST MARKER") < query.index("OLDEST MARKER")


# ---------------------------------------------------------------------------
# The story path had dropped the premise and every earlier chapter
# ---------------------------------------------------------------------------


class TestStoryContinuation:
    """The story path dropped the premise, every earlier chapter, and the real
    token budget, and injected the chat-formatting block into prose."""

    def _build(self, session, story, chapter, **kw):
        from unittest.mock import patch

        from api.routes.world_vault import stories as stories_module

        captured: dict = {}

        async def _fake(messages, **kwargs):
            captured["messages"] = [m["content"] for m in messages]
            captured.update(kwargs)
            return "SYSTEM", [{"role": "user", "content": "x"}]

        with patch("services.context_builder.build_chat_context_async", _fake):
            import asyncio

            asyncio.run(
                stories_module._enqueue_story_continuation(
                    session=session, story=story, chapter=chapter
                )
            )
        return captured

    def test_the_premise_reaches_the_continuation(self, session):
        story = _seed(
            session, _cls=Story, title="S",
            description="A lighthouse keeper who cannot leave.",
        )
        chapter = _seed(
            session, _cls=StoryChapter, story_id=story.id, title="One",
            content="text", chapter_number=1,
        )
        captured = self._build(session, story, chapter)
        assert "lighthouse keeper" in captured["system_prompt_override"]

    def test_earlier_chapters_reach_the_continuation(self, session):
        story = _seed(session, _cls=Story, title="S", description="d")
        _seed(session, _cls=StoryChapter, story_id=story.id, title="One",
              content="CHAPTER ONE MARKER", chapter_number=1)
        _seed(session, _cls=StoryChapter, story_id=story.id, title="Two",
              content="CHAPTER TWO MARKER", chapter_number=2)
        third = _seed(session, _cls=StoryChapter, story_id=story.id, title="Three",
                      content="current text", chapter_number=3)

        captured = self._build(session, story, third)
        joined = " ".join(captured["messages"])
        assert "CHAPTER ONE MARKER" in joined
        assert "CHAPTER TWO MARKER" in joined
        # The current chapter is last, and is the user turn.
        assert captured["messages"][-1] == "current text"

    def test_prior_chapters_are_bounded(self, session):
        """A chapter is potentially the user's most expensive input."""
        from api.routes.world_vault.stories import PRIOR_CHAPTER_LIMIT

        story = _seed(session, _cls=Story, title="S", description="d")
        for n in range(PRIOR_CHAPTER_LIMIT + 3):
            _seed(session, _cls=StoryChapter, story_id=story.id, title=f"C{n}",
                  content=f"MARKER {n}", chapter_number=n + 1)
        last = _seed(session, _cls=StoryChapter, story_id=story.id, title="last",
                     content="current", chapter_number=PRIOR_CHAPTER_LIMIT + 4)

        captured = self._build(session, story, last)
        assert len(captured["messages"]) - 1 <= PRIOR_CHAPTER_LIMIT

    def test_the_chat_formatting_block_is_not_injected_into_prose(self, session):
        story = _seed(session, _cls=Story, title="S", description="d")
        chapter = _seed(session, _cls=StoryChapter, story_id=story.id, title="One",
                        content="t", chapter_number=1)
        captured = self._build(session, story, chapter)
        assert captured["include_roleplay_default"] is False

    def test_the_storys_world_contributes(self, session):
        world = _seed(session, _cls=World, name="Drowned Bell", description="A WORLD DESCRIPTION")
        story = _seed(session, _cls=Story, title="S", description="d", world_id=world.id)
        chapter = _seed(session, _cls=StoryChapter, story_id=story.id, title="One",
                        content="t", chapter_number=1)
        captured = self._build(session, story, chapter)
        assert captured["world_name"] == "Drowned Bell"
        assert "A WORLD DESCRIPTION" in captured["world_description"]

    def test_the_storys_own_lorebooks_still_come_first(self, session):
        mine = _seed(session, _cls=Lorebook, name="Mine")
        world = _seed(session, _cls=World, name="W", description="d", lorebook_ids=["other"])
        story = _seed(session, _cls=Story, title="S", description="d",
                      world_id=world.id, lorebook_ids=[mine.id])
        chapter = _seed(session, _cls=StoryChapter, story_id=story.id, title="One",
                        content="t", chapter_number=1)
        captured = self._build(session, story, chapter)
        assert captured["lorebook_ids"][0] == mine.id


class TestTimelineScope:
    def test_a_world_filter_narrows_messages_and_chapters(self, client, session):
        world = _seed(session, _cls=World, name="W", description="d")
        chat = _seed(session, _cls=Chat, name="c", chat_type="chat", world_id=world.id)
        other = _seed(session, _cls=Chat, name="other", chat_type="chat")
        _seed(session, _cls=Message, name="mine", chat_id=chat.id, role="user", content="IN SCOPE")
        _seed(session, _cls=Message, name="theirs", chat_id=other.id, role="user", content="OUT OF SCOPE")
        session.commit()

        body = client.get(f"/api/v2/timeline?world_id={world.id}&types=message").json()
        contents = {e.get("description") for e in body["events"]}
        assert "IN SCOPE" in contents
        assert "OUT OF SCOPE" not in contents

    def test_the_character_filter_matches_the_speaker_not_the_chats_primary(self, client, session):
        """A group chat: filtering by the second character used to return the
        first character's lines and omit the second's own."""
        ada = _seed(session, name="Ada", description="d")
        bo = _seed(session, name="Bo", description="d")
        chat = _seed(session, _cls=Chat, name="group", chat_type="chat", character_id=ada.id)
        _seed(session, _cls=Message, name="bo", chat_id=chat.id, role="char", content="BO SAID THIS", character_id=bo.id)
        _seed(session, _cls=Message, name="ada", chat_id=chat.id, role="char", content="ADA SAID THIS", character_id=ada.id)
        session.commit()

        body = client.get(f"/api/v2/timeline?character_id={bo.id}&types=message").json()
        contents = {e.get("description") for e in body["events"]}
        assert "BO SAID THIS" in contents
        assert "ADA SAID THIS" not in contents


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run(coro):
    import asyncio

    return asyncio.run(coro)


pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")
