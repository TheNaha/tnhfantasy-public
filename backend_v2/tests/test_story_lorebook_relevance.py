"""Lorebook relevance for the story paths, and a retrieval cutoff.

Two defects that only show up in the story sandbox.

1. `build_chat_context` has two kinds of caller and they disagree on the type of
   `messages`. The chat paths pass ORM `Message` rows. Both story paths pass a
   list of **dicts** — `stories.py` builds
   `[{"role": "user", "content": chapter.content}]`, because a story chapter is
   not a chat message and has no `Message` row to point at.

   The lorebook query was built with `getattr(m, 'role', None)`, which returns
   `None` for a dict. Not a loud failure: `None` is simply not in the role set,
   so `recent` came back empty and the query stayed `""`. `search_lorebook_entries`
   then skipped semantic search entirely and returned `entries[:limit]` — the
   five newest per lorebook, or on the constant path the five OLDEST. So story
   continuation got recency-ordered world info and the chapter the user had just
   written never selected any, while `story_illustrate_system_prompt` in the same
   file sliced the same content correctly and the two paths disagreed.

2. Neither semantic search had a distance cutoff: `ORDER BY cosine_distance
   LIMIT n`, so the top-N were injected whether or not they were related. It
   compounded a separate defect — `memory_extraction` inserts with no dedup, so
   near-identical copies are mutual nearest neighbours and a fixed top-N
   retrieved the same duplicates for every query.
"""

import pytest

from core.entities import Message, MessageRole
from services.context_builder import (
    LOREBOOK_QUERY_CHARS,
    _lorebook_query_text,
    _msg_field,
)
from services.rag_pipeline import _RAG_MAX_DISTANCE_FALLBACK, rag_max_distance


@pytest.fixture
def restore_default_config():
    """Snapshot and restore the module config, and never write config.json.

    `update_config` defaults to `persist=True`, so calling it plainly in a test
    rewrites the developer's settings file. Every call in this file therefore
    passes `persist=False`, and this fixture restores the in-memory module
    state so one test's value cannot leak into the next.
    """
    import copy

    import config as app_config

    before = copy.deepcopy(app_config.DEFAULT_CONFIG)
    before_current = copy.deepcopy(app_config.get_config())
    yield
    app_config.DEFAULT_CONFIG.clear()
    app_config.DEFAULT_CONFIG.update(copy.deepcopy(before))
    app_config._config.clear()
    app_config._config.update(copy.deepcopy(before_current))


class TestDualShapedMessages:
    """The bug lived entirely in the shape, so these are the shape."""

    def test_a_dict_and_a_row_are_read_identically(self):
        as_dict = {"role": "user", "content": "the drowned city"}
        as_orm = Message(role=MessageRole.USER, content="the drowned city", chat_id="c")
        assert _msg_field(as_dict, "role") == _msg_field(as_orm, "role")
        assert _msg_field(as_dict, "content") == _msg_field(as_orm, "content")

    def test_a_dicts_role_passes_the_user_and_char_filter(self):
        # This is the assertion that fails against the old code: `getattr` on a
        # dict returns None, so the story path was filtered out entirely.
        roles = (MessageRole.USER, MessageRole.CHAR)
        assert "user" in roles, "MessageRole is a str enum, so a dict compares equal"
        assert _msg_field({"role": "user", "content": "x"}, "role") in roles
        assert _msg_field({"role": "char", "content": "x"}, "role") in roles

    def test_system_messages_are_still_excluded_from_the_query(self):
        roles = (MessageRole.USER, MessageRole.CHAR)
        assert _msg_field({"role": "system", "content": "x"}, "role") not in roles

    def test_a_message_missing_either_field_does_not_raise(self):
        assert _msg_field({}, "role") is None
        assert _msg_field({"role": "user"}, "content", "") == ""
        assert _msg_field(object(), "role") is None

    def test_the_story_path_actually_produces_a_query(self):
        """The end-to-end shape of the bug: what `stories.py` passes."""
        chapter = "The water reached the third step of the temple."
        messages = [{"role": "user", "content": chapter}]
        roles = (MessageRole.USER, MessageRole.CHAR)
        recent = [m for m in messages[-6:] if _msg_field(m, "role") in roles]
        query = " ".join(t for t in (_lorebook_query_text(m) for m in recent) if t)
        assert query == chapter, "an empty query silently disables semantic search"

    def test_the_chat_path_still_produces_the_same_query(self):
        """The fix must not change the working path."""
        content = "The water reached the third step of the temple."
        row = Message(role=MessageRole.CHAR, content=content, chat_id="c")
        roles = (MessageRole.USER, MessageRole.CHAR)
        recent = [m for m in [row][-6:] if _msg_field(m, "role") in roles]
        assert " ".join(_lorebook_query_text(m) for m in recent) == content


class TestQuerySlice:
    def test_a_short_message_contributes_all_of_itself(self):
        text = "short message"
        assert _lorebook_query_text({"role": "user", "content": text}) == text

    def test_a_long_message_contributes_its_END_not_its_opening(self):
        """`[:200]` on a 30,000-word chapter threw away the whole scene and
        searched on the preamble. `story_illustrate_system_prompt` already slices
        the other way with `[-2000:]`."""
        # Distinct text at each end, so "the tail was taken" is actually testable
        # rather than satisfied by a repeated phrase.
        content = "OPENING_SETUP_MARKER " + ("filler word " * 2000) + "ENDING_SCENE_MARKER"
        out = _lorebook_query_text({"role": "user", "content": content})
        assert len(out) == LOREBOOK_QUERY_CHARS
        assert "ENDING_SCENE_MARKER" in out
        assert "OPENING_SETUP_MARKER" not in out

    def test_empty_and_non_string_content_are_safe(self):
        assert _lorebook_query_text({"role": "user", "content": ""}) == ""
        assert _lorebook_query_text({"role": "user", "content": None}) == ""
        assert _lorebook_query_text({"role": "user"}) == ""
        assert _lorebook_query_text({"role": "user", "content": 12345}) == ""


class TestRetrievalCutoff:
    def test_the_default_is_a_real_similarity_cutoff(self):
        """0.6 on pgvector's cosine distance (0 identical, 1 orthogonal)."""
        assert 0.0 < rag_max_distance() < 1.0
        assert rag_max_distance() == pytest.approx(0.6)

    def test_it_is_configurable_and_survives_nonsense(self, monkeypatch):
        import config as app_config

        monkeypatch.setattr(
            app_config, "get_config", lambda: {"ai": {"ragMaxDistance": 0.2}}
        )
        assert rag_max_distance() == pytest.approx(0.2)

        # Clamped, not propagated: a bad config must not make every retrieval
        # throw or silently disable the cutoff.
        monkeypatch.setattr(
            app_config, "get_config", lambda: {"ai": {"ragMaxDistance": 99}}
        )
        assert rag_max_distance() == 2.0
        monkeypatch.setattr(
            app_config, "get_config", lambda: {"ai": {"ragMaxDistance": -5}}
        )
        assert rag_max_distance() == 0.0

    def test_two_point_zero_disables_the_cutoff(self, monkeypatch):
        """Documented escape hatch back to unconditional top-N."""
        import config as app_config

        monkeypatch.setattr(
            app_config, "get_config", lambda: {"ai": {"ragMaxDistance": 2.0}}
        )
        assert rag_max_distance() == 2.0

    def test_a_missing_or_unreadable_config_falls_back_to_the_shipped_default(self, monkeypatch):
        import config as app_config

        monkeypatch.setattr(app_config, "get_config", lambda: {})
        assert rag_max_distance() == _RAG_MAX_DISTANCE_FALLBACK

        def boom():
            raise RuntimeError("config unreadable")

        monkeypatch.setattr(app_config, "get_config", boom)
        assert rag_max_distance() == _RAG_MAX_DISTANCE_FALLBACK

    def test_both_semantic_searches_apply_the_cutoff_in_sql(self):
        """A cutoff only in one of the two is worse than none: the other keeps
        injecting the noise, and `[World Information]` sits next to
        `[Relevant Memories]` in the same prompt."""
        import inspect

        from services import rag_pipeline

        src = inspect.getsource(rag_pipeline)
        # One per search: memories and lorebook entries.
        assert src.count("cosine_distance(q_vec) < rag_max_distance()") >= 2
        # Applied in the WHERE clause, not as a post-fetch Python filter.
        assert ".where(" in src


class TestBuildChatContextEndToEnd:
    """The assertion that actually catches the bug.

    Testing `_msg_field` and `_lorebook_query_text` directly does not: both still
    pass if the call site in `build_chat_context` is reverted to `getattr(m,
    'role', None)`, which is exactly the defect. This drives the real function
    and captures the `_lorebook_query` it hands to the section builder — the
    value that reaches `search_lorebook_entries`, and that is `None` (or empty)
    for every story turn when the bug is present.

    Verified to fail against the pre-fix code.
    """

    @staticmethod
    def _capture_query(monkeypatch, messages) -> str | None:
        """Run `build_chat_context` and return the lorebook query it produced."""
        from services import context_builder as cb

        captured: dict = {}

        def fake_sections(_session, **kwargs):
            captured["query"] = kwargs.get("_lorebook_query")
            return []

        monkeypatch.setattr(cb, "build_system_prompt_sections", fake_sections)
        cb.build_chat_context(
            None,
            messages,
            lorebook_ids=["lb-1"],
            system_prompt_override="ignore the card",
        )
        return captured.get("query")

    def test_a_story_chapter_dict_reaches_the_lorebook_query(self, monkeypatch):
        """What `stories.py:933` and `:1054` actually pass."""
        chapter = "The water reached the third step of the temple."
        query = self._capture_query(monkeypatch, [{"role": "user", "content": chapter}])
        assert query, "an empty query makes search_lorebook_entries skip semantic search"
        assert chapter in query

    def test_an_orm_message_reaches_the_lorebook_query_too(self, monkeypatch):
        row = Message(
            role=MessageRole.CHAR, content="The water reached the temple.", chat_id="c"
        )
        query = self._capture_query(monkeypatch, [row])
        assert query and "temple" in query

    def test_both_shapes_produce_a_comparable_query(self, monkeypatch):
        """The fix must not make the story path special: the chat path's result
        is unchanged, so a story and a chat about the same text rank the same
        entries."""
        text = "The drowned city of Vel Varren."
        from_dict = self._capture_query(monkeypatch, [{"role": "user", "content": text}])
        from_orm = self._capture_query(
            monkeypatch, [Message(role=MessageRole.USER, content=text, chat_id="c")]
        )
        assert from_dict == from_orm

    def test_system_only_messages_still_produce_an_empty_query(self, monkeypatch):
        """Nothing to rank against, and the caller turns "" into None, which is
        the documented 'no semantic search' signal."""
        query = self._capture_query(
            monkeypatch, [{"role": "system", "content": "instructions only"}]
        )
        assert not query

    def test_a_story_illustration_and_a_story_continuation_agree(self, monkeypatch):
        """`story_illustrate_system_prompt` already sliced the chapter's tail.
        After the fix both story paths rank world info from the same part of the
        text, instead of illustrate being relevance-based and continue being
        recency-based."""
        long_chapter = "resolved setup. " * 2000 + "the bell tolls at the drowned gate"
        from_continue = self._capture_query(
            monkeypatch, [{"role": "user", "content": long_chapter}]
        )
        # What stories.py:1551 does for the illustrate path.
        illustrate = (long_chapter or "")[-2000:]
        assert "drowned gate" in from_continue
        assert "drowned gate" in illustrate


class TestConfigLeaf:
    def test_rag_max_distance_is_a_real_documented_leaf(self):
        """It has to be writable, validated and in the allow-list, or the
        Settings UI would reject it as an unknown leaf."""
        import config as app_config

        assert "ragMaxDistance" in app_config.DEFAULT_CONFIG["ai"]
        assert "ragMaxDistance" in app_config.SECTION_LEAF_ALLOW_LISTS["ai"]

    def test_it_is_range_checked(self, restore_default_config):
        import config as app_config

        for bad in (-0.1, 2.1):
            with pytest.raises(ValueError, match="ragMaxDistance"):
                app_config.update_config({"ai": {"ragMaxDistance": bad}}, persist=False)

        # A non-numeric value is rejected by the number parser, not coerced.
        with pytest.raises(ValueError):
            app_config.update_config({"ai": {"ragMaxDistance": "not-a-number"}}, persist=False)

        assert app_config.update_config({"ai": {"ragMaxDistance": 0.4}}, persist=False)["ai"]["ragMaxDistance"] == 0.4
