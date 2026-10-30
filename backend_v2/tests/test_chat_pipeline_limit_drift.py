"""Contract drift test for the chat pipeline's numeric limits.

Pins the four limit sources so a change to one without the others fails CI:

  1. The manifest docstring in services/chat_pipeline.py (quoted values)
  2. The limits module core/pipeline_limits.py
  3. The Chat.max_autonomous_turns column default in core/entities.py
  4. No hardcoded numeric literals used as limits in pipeline_runner.py /
     pipeline_stages.py (they must import from core.pipeline_limits)
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1]

# (limit name, regex to find it in manifest docstrings, coercion type)
_MANIFEST_LIMITS = [
    ("MAX_AUTONOMOUS_TURNS", r"max_autonomous_turns[:=]\s*(\d+)", int),
    ("MAX_CONTINUATION_ATTEMPTS", r"max_continuation_attempts[:=]\s*(\d+)", int),
    ("MAX_AGENTIC_IMAGES", r"max_agentic_images[:=]\s*(\d+)", int),
    ("UPDATER_GATE_THRESHOLD", r"(?:updater_gate_threshold|gate_threshold)[:=]\s*([\d.]+)", float),
    ("IMAGE_TRIGGER_THRESHOLD", r"(?:image_threshold|trigger_image)[:=]\s*([\d.]+)", float),
]


def _limit_values() -> dict[str, object]:
    """Read the canonical limit values from core.pipeline_limits."""
    import core.pipeline_limits as limits

    return {
        "MAX_AUTONOMOUS_TURNS": limits.MAX_AUTONOMOUS_TURNS,
        "MAX_CONTINUATION_ATTEMPTS": limits.MAX_CONTINUATION_ATTEMPTS,
        "MAX_AGENTIC_IMAGES": limits.MAX_AGENTIC_IMAGES,
        "UPDATER_GATE_THRESHOLD": limits.UPDATER_GATE_THRESHOLD,
        "IMAGE_TRIGGER_THRESHOLD": limits.IMAGE_TRIGGER_THRESHOLD,
    }


def _manifest_quoted_values() -> dict[str, object]:
    """AST-parse the manifest and extract quoted limit numbers from its strings."""
    source = (SRC / "services" / "chat_pipeline.py").read_text()
    tree = ast.parse(source)
    found: dict[str, object] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for name, pattern, coerce in _MANIFEST_LIMITS:
                m = re.search(pattern, node.value)
                if m:
                    found[name] = coerce(m.group(1))
    return found


class TestManifestQuotedLimitsMatchLimitsModule:
    """Every limit quoted in the manifest must equal core.pipeline_limits."""

    def test_at_least_one_quoted_limit_exists(self):
        found = _manifest_quoted_values()
        assert found, (
            "no quoted limit values found in services/chat_pipeline.py docstrings; "
            "the manifest should quote at least one limit"
        )

    def test_every_quoted_manifest_limit_matches(self):
        expected = _limit_values()
        found = _manifest_quoted_values()
        for name, value in found.items():
            assert value == expected[name], (
                f"manifest quotes {name}={value}, but core/pipeline_limits.py has "
                f"{name}={expected[name]}"
            )


class TestEntityDefaultMatchesLimitsModule:
    """The entity column default must come from the same place as the limits module."""

    def test_max_autonomous_turns_default(self):
        expected = _limit_values()
        from core.entities import Chat

        assert Chat.model_fields["max_autonomous_turns"].default == expected[
            "MAX_AUTONOMOUS_TURNS"
        ]


class TestNoHardcodedLimitLiteralsInExecutors:
    """Executors must import limits from core.pipeline_limits, not hardcode them.

    A bare literal equal to a limit value is only a problem when it is used as
    a limit — i.e. in a comparison or assigned to a limit-named variable. A
    coincidental value match (e.g. a pacing speed of 2) is not a drift risk.
    """

    def test_no_hardcoded_limit_in_comparisons_or_assignments(self):
        expected = _limit_values()
        offenders: list[str] = []
        for rel in ("services/pipeline_runner.py", "services/pipeline_stages.py"):
            path = SRC / rel
            tree = ast.parse(path.read_text())
            offenders.extend(_hardcoded_limit_offenders(tree, expected, rel))
        assert not offenders, (
            "hardcoded limit literals found in executors (should import from "
            "core.pipeline_limits):\n" + "\n".join(offenders)
        )


def _hardcoded_limit_offenders(
    tree: ast.AST, expected: dict[str, object], rel: str
) -> list[str]:
    """Find literals used as limits (comparisons or limit-named assignments)."""
    offenders: list[str] = []
    # Build a parent map so we know the context of each literal.
    parent: dict[ast.AST, ast.AST] = {}
    for parent_node in ast.walk(tree):
        for child in ast.iter_child_nodes(parent_node):
            parent[child] = parent_node

    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(
            node.value, (int, float)
        ):
            continue
        value = node.value
        if value not in expected.values():
            continue
        p = parent.get(node)
        if isinstance(p, ast.Compare):
            # The literal is a comparator: `x < 4`, `4 == y`, etc.
            offenders.append(
                f"{rel}:{node.lineno}: hardcoded limit literal {value} in comparison"
            )
        elif isinstance(p, ast.Assign) and p.value is node:
            target_names = _assignment_target_names(p)
            if any(_is_limit_name(n) for n in target_names):
                offenders.append(
                    f"{rel}:{node.lineno}: hardcoded limit literal {value} assigned "
                    f"to {target_names}"
                )
    return offenders


def _assignment_target_names(assign: ast.Assign) -> list[str]:
    names: list[str] = []
    for target in assign.targets:
        names.extend(_name_from_target(target))
    return names


def _name_from_target(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Tuple):
        out: list[str] = []
        for elt in target.elts:
            out.extend(_name_from_target(elt))
        return out
    return []


def _is_limit_name(name: str) -> bool:
    lowered = name.lower()
    return any(
        key in lowered
        for key in (
            "max_autonomous_turns",
            "max_continuation_attempts",
            "max_agentic_images",
            "updater_gate_threshold",
            "image_trigger_threshold",
            "gate_threshold",
            "image_threshold",
        )
    )
