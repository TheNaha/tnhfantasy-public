"""Context budget floors.

Three ways `prune_context` could hand a paid provider a prompt it would either
refuse or answer nonsensically, all of which were open because the function only
ever removed conversation messages and only while `len(unpinned_msgs) > 2`:

  1. `if remaining_budget <= 0: return system_msgs` — when the system block alone
     exceeded the budget the call returned the system prompt and NO conversation.
     The request was a character sheet with nothing to reply to, and it was paid
     for. The system prompt was also never shortened, so any large card or
     lorebook could trigger it.

  2. The `> 2` floor meant a history of one or two messages was never pruned no
     matter how large. A story continuation is exactly that shape — one message
     carrying a whole chapter.

  3. With the floor reached, the survivors were sent whole, so two 40,000-token
     messages went out at ~80,000 against a 4096 budget.

`MIN_UNPINNED_MESSAGES` stays authoritative for message COUNT, which the existing
tests in `test_context_builder.py` pin: a tight budget prunes to the floor and
stops, and does not then mangle what is left. Truncation is therefore scoped to
messages that are individually unsendable (`TRUNCATION_MIN_TOKENS`).
"""

import pytest

from services.context_builder import (
    MIN_UNPINNED_MESSAGES,
    SYSTEM_TOKEN_FLOOR,
    TRUNCATION_MIN_TOKENS,
    _estimate_cached,
    estimate_tokens,
    prune_context,
)


def _msg(role, content, **extra):
    return {"role": role, "content": content, **extra}


def _budget(pruned):
    return sum(_estimate_cached(m.get("content", "")) for m in pruned)


BUDGET = 4096
# Comfortably past both floors, so the pathological cases below are unambiguously
# in the territory truncation exists for.
CHAPTER = "The wind rose over the plain and the fires went out one by one. " * 5000


class TestOversizedSystemPrompt:
    def test_a_system_block_over_budget_still_returns_the_conversation(self):
        """The regression: this returned `[system_msgs]` and nothing else."""
        pruned = prune_context(
            [_msg("user", "hello")], "", [], max_tokens=4096
        )
        assert pruned == [{"role": "user", "content": "hello"}]

    def test_the_system_prompt_is_itself_capped(self):
        system = [_msg("system", "You are a vast archive. " * 20000)]
        pruned = prune_context(system + [_msg("user", "hello")], "", [], max_tokens=4096)
        system_tokens = sum(
            _estimate_cached(m["content"]) for m in pruned if m["role"] == "system"
        )
        assert system_tokens <= SYSTEM_TOKEN_FLOOR
        assert any(m["role"] != "system" for m in pruned)

    def test_a_system_prompt_under_the_floor_is_left_untouched(self):
        body = "You are Aria, a cartographer. " * 5
        pruned = prune_context(
            [_msg("system", body), _msg("user", "hi")], "", [], max_tokens=4096
        )
        assert pruned[0]["content"] == body

    def test_truncation_is_marked_so_the_model_can_see_it(self):
        system = [_msg("system", "You are a vast archive. " * 20000)]
        pruned = prune_context(system + [_msg("user", "hello")], "", [], max_tokens=4096)
        assert any("truncated" in m["content"] for m in pruned)


class TestMinimumMessageFloor:
    def test_a_single_enormous_message_is_no_longer_untouchable(self):
        """The story-continuation shape: one message carrying a chapter."""
        pruned = prune_context([_msg("user", CHAPTER)], "", [], max_tokens=BUDGET)
        assert _budget(pruned) <= BUDGET
        assert len(pruned) == 1, "the floor must not mean 'send it anyway'"

    def test_two_enormous_messages_are_bounded_together(self):
        """Per-message trimming does not compose: budgeting for the first leaves
        nothing for the second, which is how this stayed at ~80,000 tokens."""
        pruned = prune_context(
            [_msg("user", "a " * 40000), _msg("assistant", "b " * 40000)],
            "", [], max_tokens=BUDGET,
        )
        assert _budget(pruned) <= BUDGET
        assert len(pruned) == MIN_UNPINNED_MESSAGES

    def test_many_enormous_messages_are_bounded(self):
        msgs = [_msg("user" if i % 2 == 0 else "assistant", "x " * 40000) for i in range(4)]
        assert _budget(prune_context(msgs, "", [], max_tokens=BUDGET)) <= BUDGET

    def test_a_long_imported_history_is_pruned_to_the_floor(self):
        """200 turns of ~1800 tokens each. The floor keeps 2, so ~3600 tokens go
        out — over the 4096 budget once both are counted, but each is far below
        any provider's window, and `MIN_UNPINNED_MESSAGES` owns the count.

        This is the documented trade rather than a gap: truncation is scoped to
        messages that are individually unsendable, so a floor of ordinary turns
        is honoured intact. `test_two_enormous_messages_are_bounded_together`
        covers the case where the floor is reached and the survivors ARE too big.
        """
        msgs = [_msg("user", f"turn {i}. " * 900) for i in range(200)]
        pruned = prune_context(msgs, "", [], max_tokens=BUDGET)
        assert len(pruned) == MIN_UNPINNED_MESSAGES
        # The survivors are the most recent, not the oldest.
        assert "turn 199." in pruned[-1]["content"]
        # And nothing individually unsendable survived.
        assert all(
            _estimate_cached(m["content"]) < TRUNCATION_MIN_TOKENS for m in pruned
        )


class TestWhatMustNotChange:
    def test_the_floor_still_owns_message_count(self):
        """Regression guard: the pre-existing tests pin that a tight budget
        prunes to the floor and then stops. Truncation must not override it for
        messages that are small enough to actually send."""
        msgs = [_msg("system", "SYS")] + [_msg("user", c) for c in ("a", "b", "c", "d")]
        pruned = prune_context(
            msgs, "SYS", [], max_tokens=estimate_tokens("SYS") + 2
        )
        assert [m["content"] for m in pruned] == ["SYS", "c", "d"]
        assert "a" not in [m["content"] for m in pruned]

    def test_normal_conversations_are_untouched(self):
        msgs = [
            _msg("system", "You are A."),
            _msg("user", "hi"),
            _msg("assistant", "hello"),
        ]
        pruned = prune_context(msgs, "", [], max_tokens=BUDGET)
        assert [m["content"] for m in pruned] == [m["content"] for m in msgs]

    def test_pinned_messages_are_never_dropped(self):
        msgs = [_msg("user", "PINNED " * 20000, _pinned=True)] + [
            _msg("user", "chatter " * 20000) for _ in range(5)
        ]
        pruned = prune_context(msgs, "", [], max_tokens=BUDGET)
        assert any(m.get("_pinned") for m in pruned)

    def test_system_messages_survive_pruning(self):
        msgs = [_msg("system", "SYS " * 20000)] + [
            _msg("user", "chatter " * 20000) for _ in range(5)
        ]
        assert any(m["role"] == "system" for m in prune_context(msgs, "", [], max_tokens=BUDGET))

    def test_empties_and_tiny_messages_do_not_crash(self):
        assert prune_context([_msg("user", "")], "", [], max_tokens=BUDGET) is not None
        assert prune_context([_msg("user", "a")] * 10, "", [], max_tokens=BUDGET) is not None
        assert prune_context([], "", [], max_tokens=BUDGET) == []

    def test_a_zero_budget_does_not_hang(self):
        # remaining_budget is 0, so `over_budget` is False and the
        # truncation pass is skipped. Nothing should raise.
        assert prune_context([_msg("user", CHAPTER)], "", [], max_tokens=0) is not None


@pytest.mark.parametrize("content_tokens", [1, 100, 4000, TRUNCATION_MIN_TOKENS - 1])
def test_messages_below_the_truncation_floor_are_sent_whole(content_tokens):
    """A message no provider would reject must not be shortened just because the
    configured budget is smaller than the content."""
    content = "w " * content_tokens
    pruned = prune_context([_msg("user", content)], "", [], max_tokens=BUDGET)
    assert len(pruned) == 1
