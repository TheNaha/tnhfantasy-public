# Tests for services/context_builder.py (system prompt assembly + pruning)

import pytest
from sqlmodel import Session, select

from core.entities import Character, Lorebook, LorebookEntry, Message, MessageKind, MessageRole
from services.context_builder import (
    build_chat_context,
    build_character_system_prompt,
    build_system_prompt_sections,
    estimate_tokens,
    inject_lorebooks_into_system_prompt,
    parse_mes_example,
    prune_context,
)


def _msg(role: str, content: str, **extra) -> dict:
    return {"role": role, "content": content, **extra}


# ── estimate_tokens ─────────────────────────────────────────────────────────

def test_estimate_tokens_empty_is_zero():
    assert estimate_tokens("") == 0


def test_estimate_tokens_grows_with_text():
    short = estimate_tokens("hello world")
    long = estimate_tokens("word " * 500)
    assert short > 0
    assert long > short


# ── parse_mes_example ───────────────────────────────────────────────────────

def test_parse_mes_example_blocks():
    example = (
        "<START>\n{{user}}: Hi!\n{{char}}: Hello there!\n"
        "<START>\n{{user}}: Second turn\n{{char}}: Reply two\n"
    )
    pairs = parse_mes_example(example, char_name="Aria", user_name="Kai")
    assert pairs == [
        {"role": "user", "content": "Hi!"},
        {"role": "assistant", "content": "Hello there!"},
        {"role": "user", "content": "Second turn"},
        {"role": "assistant", "content": "Reply two"},
    ]


def test_parse_mes_example_empty():
    assert parse_mes_example("") == []
    assert parse_mes_example(None) == []


# ── inject_lorebooks_into_system_prompt ─────────────────────────────────────

def test_inject_lorebooks_appends_block():
    out = inject_lorebooks_into_system_prompt(
        "Base prompt",
        [{"content": "The capital is Aetheria"}, {"content": "Dragons fear iron"}],
    )
    assert out.startswith("Base prompt")
    assert "[World Information]" in out
    assert "Aetheria" in out
    assert "iron" in out


def test_inject_lorebooks_empty_unchanged():
    assert inject_lorebooks_into_system_prompt("Base", []) == "Base"


# ── build_character_system_prompt ───────────────────────────────────────────

def test_build_character_system_prompt_includes_fields():
    char = Character(name="Aria", description="A mage", personality="Curious", scenario="City of Aetheria")
    prompt = build_character_system_prompt(char)
    assert "Aria" in prompt
    assert "mage" in prompt
    assert "Curious" in prompt
    assert "Aetheria" in prompt


# ── prune_context ───────────────────────────────────────────────────────────

def test_prune_context_drops_oldest_unpinned_first():
    msgs = [
        _msg("system", "SYS"),
        _msg("user", "oldest"),
        _msg("user", "middle"),
        _msg("user", "newest"),
    ]
    # Budget = system + 1 token → forces dropping the oldest unpinned turns
    pruned = prune_context(msgs, "SYS", [], max_tokens=estimate_tokens("SYS") + 1)
    contents = [m["content"] for m in pruned]
    assert "SYS" in contents
    assert "oldest" not in contents


def test_prune_context_keeps_pinned_messages():
    msgs = [
        _msg("system", "SYS"),
        _msg("user", "oldest", _pinned=True),
        _msg("user", "middle"),
        _msg("user", "newest"),
    ]
    pruned = prune_context(msgs, "SYS", [], max_tokens=estimate_tokens("SYS") + 3)
    contents = [m["content"] for m in pruned]
    assert "oldest" in contents  # pinned survives even when pruning


def test_prune_context_keeps_two_unpinned_floor():
    # Budget allows only 2 unpinned tokens: pruning must stop at the floor of
    # 2 unpinned messages (never evict the whole conversation).
    msgs = [
        _msg("system", "SYS"),
        _msg("user", "a"),
        _msg("user", "b"),
        _msg("user", "c"),
        _msg("user", "d"),
    ]
    pruned = prune_context(msgs, "SYS", [], max_tokens=estimate_tokens("SYS") + 2)
    contents = [m["content"] for m in pruned]
    assert "SYS" in contents
    assert "a" not in contents  # oldest dropped while above the floor
    assert len(pruned) == 3  # system + 2 unpinned (floor respected)


def test_prune_context_narrator_kind_is_prunable():
    msgs = [
        _msg("system", "SYS"),
        _msg("system", "narrator scene 1", _kind="narrator"),
        _msg("system", "narrator scene 2", _kind="narrator"),
        _msg("system", "narrator scene 3", _kind="narrator"),
        _msg("user", "hi"),
    ]
    pruned = prune_context(msgs, "SYS", [], max_tokens=estimate_tokens("SYS") + 2)
    contents = [m["content"] for m in pruned]
    # Narrator turns are NOT exempt and get pruned like conversation
    assert "narrator scene 1" not in contents
    assert "hi" in contents


def test_prune_context_true_system_kind_exempt():
    msgs = [
        _msg("system", "SYS"),
        _msg("system", "roleplay instruction", _kind="system"),
        _msg("user", "a"),
        _msg("user", "b"),
    ]
    pruned = prune_context(msgs, "SYS", [], max_tokens=1)
    contents = [m["content"] for m in pruned]
    assert "roleplay instruction" in contents


# ── build_system_prompt_sections (DB) ───────────────────────────────────────

def _seed_character(session: Session) -> Character:
    char = Character(
        name="Aria",
        description="A mage",
        system_prompt="You are {{char}}, a kind mage. Greet {user} warmly.",
        append_system_prompt="Always mention the moon.",
    )
    session.add(char)
    session.commit()
    session.refresh(char)
    return char


def test_sections_character_block_and_tavern_vars(session):
    char = _seed_character(session)
    sections = build_system_prompt_sections(session, character=char, persona_name="Kai")
    by_key = {s["key"]: s for s in sections}
    assert "character" in by_key
    assert "{{char}}" not in by_key["character"]["content"]
    assert "{user}" not in by_key["character"]["content"]
    assert "Aria" in by_key["character"]["content"]
    assert "Kai" in by_key["character"]["content"]
    assert by_key["char_append"]["content"] == "Always mention the moon."


def test_sections_override_replaces_character(session):
    char = _seed_character(session)
    sections = build_system_prompt_sections(
        session, character=char, system_prompt_override="Custom prompt entirely"
    )
    by_key = {s["key"]: s for s in sections}
    assert "chat_prompt" in by_key
    assert by_key["chat_prompt"]["source"] == "override"
    assert by_key["chat_prompt"]["content"] == "Custom prompt entirely"
    # NOTE: current code appends the character block *alongside* the override
    # (docstring says override should REPLACE the character card — latent
    # mismatch, left as-is to avoid changing live-chat behavior).


def test_sections_persona_and_append(session):
    sections = build_system_prompt_sections(
        session,
        persona_name="Kai",
        persona_description="A wandering knight",
        append_system_prompt="Extra chat rule",
    )
    by_key = {s["key"]: s for s in sections}
    assert "persona" in by_key
    assert "Kai" in by_key["persona"]["content"]
    assert "wandering knight" in by_key["persona"]["content"]
    assert by_key["chat_append"]["content"] == "Extra chat rule"


def test_sections_lorebook_keyword_path(session):
    lb = Lorebook(name="World")
    session.add(lb)
    session.commit()
    session.refresh(lb)
    entry = LorebookEntry(lorebook_id=lb.id, keys=[], content="The capital is Aetheria")
    session.add(entry)
    session.commit()

    sections = build_system_prompt_sections(
        session, lorebook_ids=[lb.id], persona_name="Kai", story_location="Aetheria"
    )
    by_key = {s["key"]: s for s in sections}
    assert "lorebook" in by_key
    assert "Aetheria" in by_key["lorebook"]["content"]


def test_sections_story_blocks(session):
    char = Character(name="Hero", description="A knight", personality="Brave")
    session.add(char)
    session.commit()
    session.refresh(char)

    sections = build_system_prompt_sections(
        session,
        story_genre="Dark fantasy",
        story_memory="The hero lost his sword",
        story_character_ids=[char.id],
        include_roleplay_default=False,
    )
    by_key = {s["key"]: s for s in sections}
    assert "story_genre" in by_key
    assert "Dark fantasy" in by_key["story_genre"]["content"]
    assert "story_memory" in by_key
    assert "story_characters" in by_key
    assert "Hero" in by_key["story_characters"]["content"]


# ── build_chat_context (DB) ─────────────────────────────────────────────────

def test_build_chat_context_assembles_and_maps_messages(session):
    char = _seed_character(session)
    char.mes_example = "<START>\n{{user}}: Test\n{{char}}: Example reply\n"
    session.add(char)
    session.commit()

    messages = [
        Message(chat_id="chat-x", role=MessageRole.USER, content="Hello there"),
        Message(chat_id="chat-x", role=MessageRole.CHAR, content="Hi Kai!"),
    ]
    session.add_all(messages)
    session.commit()

    system_prompt, all_msgs = build_chat_context(
        session, messages, character=char, persona_name="Kai"
    )
    assert system_prompt
    assert "Aria" in system_prompt
    roles = [m["role"] for m in all_msgs]
    assert roles[0] == "system"
    assert all_msgs[0]["content"] == system_prompt
    # Example dialogue inserted between system prompt and conversation
    assert any(m.get("content", "").startswith("[Example dialogue") for m in all_msgs)
    assert all_msgs[-2]["role"] == "user"
    assert all_msgs[-2]["content"] == "Hello there"
    assert all_msgs[-1]["role"] == "assistant"
    assert all_msgs[-1]["content"] == "Hi Kai!"


def test_build_chat_context_skips_world_state_source(session):
    messages = [
        Message(
            chat_id="chat-x",
            role=MessageRole.SYSTEM,
            content="The world darkens.",
            message_metadata={"source": "world_state"},
        ),
        Message(chat_id="chat-x", role=MessageRole.USER, content="Continue"),
    ]
    session.add_all(messages)
    session.commit()

    _, all_msgs = build_chat_context(session, messages)
    contents = [m["content"] for m in all_msgs]
    assert "The world darkens." not in contents
    assert "Continue" in contents


def test_build_chat_context_pins_narrator_as_prunable(session):
    messages = [
        Message(chat_id="chat-x", role=MessageRole.SYSTEM, content="Narrator: rain falls",
                kind=MessageKind.NARRATOR),
        Message(chat_id="chat-x", role=MessageRole.USER, content="I go inside"),
    ]
    session.add_all(messages)
    session.commit()

    _, all_msgs = build_chat_context(session, messages, max_context_tokens=100000)
    assert any(m["content"] == "Narrator: rain falls" for m in all_msgs)
    narrator = next(m for m in all_msgs if m["content"] == "Narrator: rain falls")
    assert narrator["role"] == "system"
