# Tests for services/context_builder.py (system prompt assembly + pruning)

from core.entities import (
    Character,
    Chat,
    Lorebook,
    LorebookEntry,
    Message,
    MessageKind,
    MessageRole,
)
from services.context_builder import (
    build_character_system_prompt,
    build_chat_context,
    build_system_prompt_sections,
    chat_context_kwargs,
    estimate_tokens,
    parse_mes_example,
    prune_context,
)
import pytest
from sqlmodel import Session


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


def test_prune_context_matches_by_content_not_identity():
    # Rebuild the list with fresh dict objects (simulates DB-reconstructed messages)
    rebuilt = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "hello", "_pinned": True},
        {"role": "user", "content": "world"},
    ]
    pruned = prune_context(rebuilt, "SYS", [], max_tokens=estimate_tokens("SYS") + 3)
    contents = [m["content"] for m in pruned]
    assert "hello" in contents
    assert "world" in contents


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
    char_key = f"character_{char.id}"
    assert char_key in by_key
    assert "{{char}}" not in by_key[char_key]["content"]
    assert "{user}" not in by_key[char_key]["content"]
    assert "Aria" in by_key[char_key]["content"]
    assert "Kai" in by_key[char_key]["content"]
    assert by_key[f"char_append_{char.id}"]["content"] == "Always mention the moon."


def test_sections_override_replaces_character(session):
    char = _seed_character(session)
    sections = build_system_prompt_sections(
        session, character=char, system_prompt_override="Custom prompt entirely"
    )
    by_key = {s["key"]: s for s in sections}
    assert "chat_prompt" in by_key
    assert by_key["chat_prompt"]["source"] == "override"
    assert by_key["chat_prompt"]["content"] == "Custom prompt entirely"
    # Override replaces the character card + char append blocks.
    assert f"character_{char.id}" not in by_key
    assert f"char_append_{char.id}" not in by_key


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


def test_sections_story_pov(session):
    sections = build_system_prompt_sections(
        session,
        story_genre="Fantasy",
        story_pov="second",
        include_roleplay_default=False,
    )
    by_key = {s["key"]: s for s in sections}
    assert "story_pov" in by_key
    assert "second person" in by_key["story_pov"]["content"]

    # Absent when not requested
    sections = build_system_prompt_sections(session, story_genre="Fantasy", include_roleplay_default=False)
    assert all(s["key"] != "story_pov" for s in sections)


# ── build_chat_context (DB) ─────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _chat_x_parent(session):
    """Every build_chat_context test seeds Message(chat_id="chat-x").

    The test engine now runs with PRAGMA foreign_keys=ON, so the parent Chat
    has to exist. Previously these rows were silently accepted by SQLite and
    the equivalent inserts would have been rejected by Postgres.
    """
    from core.entities import Chat as _Chat
    if session.get(_Chat, "chat-x") is None:
        session.add(_Chat(id="chat-x", name="Context Chat"))
        session.commit()


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
        session, messages, characters=[char], persona_name="Kai"
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


def test_build_chat_context_skips_world_state_source_for_dicts(session):
    messages = [
        {"role": "system", "content": "The world darkens.", "message_metadata": {"source": "world_state"}},
        {"role": "user", "content": "Continue"},
    ]

    _, all_msgs = build_chat_context(session, messages)
    contents = [m["content"] for m in all_msgs]
    assert "The world darkens." not in contents
    assert "Continue" in contents


def test_build_chat_context_pins_narrator_as_prunable(session):
    """A narrator turn is a conversation turn, not a system instruction.

    It used to go out as `role: "system"`, which made it exempt from pruning AND
    — on the Google provider, whose `translate_messages_google` concatenates every
    system message into the system prompt and drops it from the conversation —
    tore the narration out of its place in the dialogue and appended it to the
    end of the instructions, unmarked.

    `kind=NARRATOR` is what makes it prunable, so this asserts all three: it is
    present, it is labelled, and it is on the dialogue channel rather than the
    instruction one.
    """
    messages = [
        Message(chat_id="chat-x", role=MessageRole.SYSTEM, content="rain falls",
                kind=MessageKind.NARRATOR),
        Message(chat_id="chat-x", role=MessageRole.USER, content="I go inside"),
    ]
    session.add_all(messages)
    session.commit()

    _, all_msgs = build_chat_context(session, messages, max_context_tokens=100000)
    narrator = next(m for m in all_msgs if m["content"].endswith("rain falls"))

    # Labelled, so the model can tell narration from a character reply.
    assert narrator["content"] == "[Narration] rain falls"
    # On the dialogue channel, so its POSITION survives.
    assert narrator["role"] == "assistant"
    # And the last turn is still the user's, which is what the model answers.
    assert all_msgs[-1] == {"role": "user", "content": "I go inside"}


def test_a_narrator_turn_is_prunable_rather_than_exempt(session):
    """`_kind` is what makes it droppable; without it the old bug returns.

    A narrator turn is stored as `role=SYSTEM`, and `role == "system"` is on the
    never-prune list. The serialised `_kind` is the only thing that moves it off
    that list, so this goes straight to `prune_context` rather than through
    `build_chat_context` — the default system prompt there is large enough to
    swamp any budget a two-message fixture can set, whose floors then keep
    everything.

    A budget is chosen that comfortably clears those floors and still needs the
    narration dropped, which is the whole claim.
    """
    msgs = [
        {"role": "assistant", "content": "[Narration] " + ("rain falls " * 200),
         "_kind": "narrator", "_pinned": False},
    ] + [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}", "_pinned": False}
        for i in range(1, 5)
    ]

    pruned = prune_context(msgs, "SYS", [], max_tokens=200)

    contents = [m["content"] for m in pruned]
    assert not any("rain falls" in c for c in contents)
    assert contents == ["turn 1", "turn 2", "turn 3", "turn 4"]


def test_a_pinned_narrator_turn_is_never_pruned():
    """`_pinned` still wins over `_kind`, in both directions.

    The pin check is ordered before the kind check, so a pin survives — and a
    narrator that is pinned must not be droppable just because of its kind.
    """
    msgs = [
        {"role": "assistant", "content": "[Narration] rain falls",
         "_kind": "narrator", "_pinned": True},
        {"role": "user", "content": "I go inside", "_pinned": False},
    ]
    budget = estimate_tokens("SYS") + estimate_tokens("I go inside")
    pruned = prune_context(msgs, "SYS", [], max_tokens=budget)

    contents = [m["content"] for m in pruned]
    assert any("rain falls" in c for c in contents)


def test_build_chat_context_strips_internal_keys(session):
    """The _pinned/_kind helper keys must never leak into provider-bound payloads."""
    msg = Message(
        chat_id="chat-x",
        role=MessageRole.SYSTEM,
        content="Narrator: storm brewing",
        kind=MessageKind.NARRATOR,
        pinned=True,
    )
    user_msg = Message(chat_id="chat-x", role=MessageRole.USER, content="I stay inside")
    session.add_all([msg, user_msg])
    session.commit()

    _, all_msgs = build_chat_context(session, [msg, user_msg], max_context_tokens=100000)
    for m in all_msgs:
        assert "_pinned" not in m
        assert "_kind" not in m


def test_prune_context_uses_message_id_not_content_prefix():
    """Two messages with identical role + identical first 200 chars but
    different _id values must both survive — they are distinct messages."""
    shared_prefix = "The dragon soars overhead, its wings casting shadows across the valley."
    msg_a = {"role": "user", "content": shared_prefix + " Message A", "_id": "uuid-a1"}
    msg_b = {"role": "user", "content": shared_prefix + " Message B", "_id": "uuid-b2"}

    pruned = prune_context([msg_a, msg_b], "", [], max_tokens=100000)
    contents = [m["content"] for m in pruned]
    assert any("Message A" in c for c in contents)
    assert any("Message B" in c for c in contents)
    assert len(pruned) == 2


def test_prune_context_id_based_keys_prevent_resurrection():
    """When pruning removes a message, it must not be 'resurrected' by
    another message sharing the same content-prefix key. With _id, each
    message has a distinct key so the set-based membership check is precise."""
    shared = "x" * 200
    msg_a = {"role": "user", "content": f"{shared}A", "_id": "uuid-a"}
    msg_b = {"role": "user", "content": f"{shared}B", "_id": "uuid-b"}
    msg_c = {"role": "user", "content": f"{shared}C", "_id": "uuid-c"}

    # Tight budget: prune_context keeps at least 2 (len > 2 guard).
    # Without _id, all three share the same key and the set membership
    # would resurrect the pruned one. With _id, only the 2 that remain
    # in unpinned_msgs are kept.
    pruned = prune_context([msg_a, msg_b, msg_c], "", [], max_tokens=5)
    assert len(pruned) == 2


def test_build_chat_context_propagates_id_for_prune_dedup(session):
    """SQLModel Message ids become _id in the context dict so prune_context
    can distinguish messages with identical content prefixes."""
    msg_a = Message(chat_id="chat-x", role=MessageRole.USER, content="The castle gate rumbles open and")
    msg_b = Message(chat_id="chat-x", role=MessageRole.USER, content="The castle gate rumbles open and I step through")
    session.add_all([msg_a, msg_b])
    session.commit()

    _, all_msgs = build_chat_context(session, [msg_a, msg_b], max_context_tokens=100000)
    # Both user messages survive even though first ~35 chars match (same role).
    user_msgs = [m for m in all_msgs if m["role"] == "user"]
    assert len(user_msgs) == 2


# ── chat_context_kwargs ───────────────────────────────────────────────────────


def test_chat_context_kwargs_maps_chat_fields(session):
    """chat_context_kwargs should map Chat entity fields to context_builder kwargs."""
    chat = Chat(
        persona_name="Kai",
        story_location="The Shire",
        story_time="dusk",
        active_lorebook_ids=["lore-1", "lore-2"],
    )
    session.add(chat)
    session.commit()

    kwargs = chat_context_kwargs(chat)
    assert kwargs["persona_name"] == "Kai"
    assert kwargs["story_location"] == "The Shire"
    assert kwargs["story_time"] == "dusk"
    assert kwargs["lorebook_ids"] == ["lore-1", "lore-2"]
    assert "characters" in kwargs
    assert "active_character_id" not in kwargs


def test_chat_context_kwargs_with_overrides(session):
    """Overrides should take precedence over chat defaults."""
    chat = Chat(active_lorebook_ids=["default-lb"])
    session.add(chat)
    session.commit()

    kwargs = chat_context_kwargs(chat, lorebook_ids=["override-lb"], characters=[], max_context_tokens=1024)
    assert kwargs["lorebook_ids"] == ["override-lb"]
    assert kwargs["max_context_tokens"] == 1024
    assert kwargs["characters"] == []
