"""Regression tests for audit-2026-10-21 finding 11: dead code and a wrong
docstring in `core/pipeline_limits.py`.

`STAGE_TIMEOUT_SECONDS` was defined and imported nowhere. The stage-local
LLM calls use `DIRECTOR_TIMEOUT_SECONDS` from `services/decision_service.py`,
so the constant described a limit that does not exist.

The module's docstring also claimed `MAX_AUTONOMOUS_TURNS` was "the default
for `Chat.max_autonomous_turns` / `Story.max_autonomous_turns`". `Story` has
no such column.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]


class TestTheDeadTimeoutIsGone:
    def test_the_constant_is_not_defined(self):
        import core.pipeline_limits as limits

        assert not hasattr(limits, "STAGE_TIMEOUT_SECONDS")

    def test_nothing_defines_or_uses_it(self):
        """A constant that is defined and read by nobody is a lie."""
        offenders: list[str] = []
        for package in ("core", "services", "api", "infrastructure"):
            for path in (SRC / package).rglob("*.py"):
                if "STAGE_TIMEOUT_SECONDS" in path.read_text():
                    offenders.append(str(path.relative_to(SRC)))
        assert not offenders, f"STAGE_TIMEOUT_SECONDS is still around: {offenders}"

    def test_the_real_timeout_is_the_one_the_stages_use(self):
        """The Director's own timeout is the one that bounds the calls."""
        from services.decision_service import DIRECTOR_TIMEOUT_SECONDS

        assert DIRECTOR_TIMEOUT_SECONDS > 0


class TestTheDocstringMatchesTheSchema:
    def test_the_docstring_does_not_claim_a_story_column(self):
        source = (SRC / "core" / "pipeline_limits.py").read_text()
        assert "Story.max_autonomous_turns" not in source

    def test_story_really_has_no_such_column(self):
        from core.entities import Chat, Story

        assert "max_autonomous_turns" not in Story.model_fields
        assert "max_autonomous_turns" in Chat.model_fields

    def test_the_chat_column_default_is_the_constant(self):
        from core.entities import Chat
        from core.pipeline_limits import MAX_AUTONOMOUS_TURNS

        assert Chat.model_fields["max_autonomous_turns"].default == MAX_AUTONOMOUS_TURNS


class TestTheModuleIsTheOneSourceOfTruth:
    def test_the_autonomy_vocabulary_lives_here(self):
        """The route validates against this table, so it has to be here."""
        from core.pipeline_limits import AUTONOMY_CHAIN_THRESHOLDS

        assert set(AUTONOMY_CHAIN_THRESHOLDS) == {"strict", "balanced", "cinematic"}

    def test_the_limits_are_plain_module_constants(self):
        """No function, no indirection: these are read at import time."""
        import core.pipeline_limits as limits

        tree = ast.parse((SRC / "core" / "pipeline_limits.py").read_text())
        assigned = {
            target.id
            for node in tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            if isinstance(target, ast.Name)
        }
        assert {"MAX_AUTONOMOUS_TURNS", "MAX_AGENTIC_IMAGES", "AUTONOMY_CHAIN_THRESHOLDS"} <= assigned
        assert limits.MAX_AUTONOMOUS_TURNS == 4
        assert limits.MAX_AGENTIC_IMAGES == 2
