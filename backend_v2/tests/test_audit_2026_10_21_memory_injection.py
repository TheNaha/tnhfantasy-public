"""Character long-term memory must reach the model (audit-2026-10-21 §2.1).

`_q_vec` was assigned only inside the `if lorebook_ids:` block and read by
the character-memory block, which runs whenever the chat has a character. A
chat with a character and no lorebook is the default case, so the name was
unbound, the `NameError` was swallowed by the `except Exception` around the
memory block, and the memory feature was dead for every ordinary chat. The
only symptom was one WARNING line per turn.

The trigger is precise: the read is
`q_vec=_q_vec if _mem_query == _lorebook_query else None`, so the name is
only evaluated when the memory query and the lorebook query are the same
string - which is exactly what `build_chat_context_with_sections` does
(it passes `_memory_query=_lorebook_query or None`). With no lorebook the
`if lorebook_ids:` block never runs, and the name is never bound.
"""

import pytest

from core.entities import Character, Lorebook, LorebookEntry
from services import rag_pipeline
from services.context_builder import build_chat_context_with_sections


class _FakeMemory:
    def __init__(self, content: str):
        self.content = content


@pytest.fixture
def memory_spy(monkeypatch):
    """Record every `search_memories` call the context builder makes."""
    calls: list[dict] = []

    def _fake_search_memories(session, character_id, query, limit=None, **kwargs):
        calls.append({
            "character_id": character_id,
            "query": query,
            "limit": limit,
            **kwargs,
        })
        return [_FakeMemory("The user is afraid of thunder.")]

    monkeypatch.setattr(rag_pipeline, "search_memories", _fake_search_memories)
    return calls


def _seed_character(session) -> Character:
    char = Character(
        name="Aria",
        description="A mage",
        system_prompt="You are {{char}}.",
    )
    session.add(char)
    session.commit()
    session.refresh(char)
    return char


def _messages():
    return [
        {"role": "user", "content": "Tell me about the storm."},
        {"role": "char", "content": "The storm is close. I can taste the rain."},
    ]


def test_memories_are_injected_without_a_lorebook(session, memory_spy):
    """The default case: a character, a conversation, and no lorebook."""
    char = _seed_character(session)

    _prompt, _msgs, sections = build_chat_context_with_sections(
        session,
        _messages(),
        characters=[char],
        character_id=char.id,
        lorebook_ids=[],
        persona_name="Kai",
        story_location="Aetheria",
    )

    assert memory_spy, "search_memories was never called"
    assert memory_spy[0]["character_id"] == char.id

    by_key = {s["key"]: s for s in sections}
    assert "character_memories" in by_key
    assert "afraid of thunder" in by_key["character_memories"]["content"]


def test_memories_are_injected_with_a_lorebook_too(session, memory_spy):
    """The lorebook path still works - this is the case that used to pass."""
    lb = Lorebook(name="World", description="w")
    session.add(lb)
    session.commit()
    session.refresh(lb)
    session.add(LorebookEntry(lorebook_id=lb.id, keys=["moon"], content="The moon is cold."))
    session.commit()

    char = _seed_character(session)

    build_chat_context_with_sections(
        session,
        _messages(),
        characters=[char],
        character_id=char.id,
        lorebook_ids=[lb.id],
        persona_name="Kai",
        story_location="Aetheria",
    )

    assert memory_spy
    assert memory_spy[0]["character_id"] == char.id


def test_a_broken_memory_search_does_not_kill_the_rest_of_the_prompt(
    session, monkeypatch
):
    """The `except Exception` around the memory block must stay - but it must
    not be the thing that hides a NameError."""
    def _boom(*args, **kwargs):
        raise RuntimeError("embedding service is down")

    monkeypatch.setattr(rag_pipeline, "search_memories", _boom)

    char = _seed_character(session)
    _prompt, _msgs, sections = build_chat_context_with_sections(
        session,
        _messages(),
        characters=[char],
        character_id=char.id,
        lorebook_ids=[],
        persona_name="Kai",
    )

    by_key = {s["key"]: s for s in sections}
    assert f"character_{char.id}" in by_key
