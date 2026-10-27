"""Service for dynamic prompt syntax and wildcards expansion.

Supports:
1. Dynamic variant choices: `{optionA|optionB|optionC}`.
2. Nested variants: `{red|{light|dark} blue}`.
3. Weighted choices: `{2::optionA|optionB}`.
4. Wildcard files: `__wildcard_name__` reading from `data/wildcards/wildcard_name.txt`
   or `data/models/wildcards/wildcard_name.txt`.
5. Deterministic seeding via optional `seed`.
"""

import os
import re
import random
from typing import Optional


_BRACE_PATTERN = re.compile(r"\{([^{}]+)\}")
_WILDCARD_PATTERN = re.compile(r"__([a-zA-Z0-9_\-]+)__")
_MAX_EXPANSION_DEPTH = 6


def _resolve_wildcard_dirs() -> list[str]:
    from config import settings

    data_dir = os.path.dirname(os.path.abspath(settings.input_dir))
    return [
        os.path.join(data_dir, "wildcards"),
        os.path.join(data_dir, "models", "wildcards"),
        os.path.join(os.getcwd(), "data", "wildcards"),
        os.path.join(os.getcwd(), "models", "wildcards"),
    ]


def _read_wildcard_lines(name: str) -> list[str]:
    """Find and read non-empty, non-comment lines from a wildcard file."""
    for base_dir in _resolve_wildcard_dirs():
        candidate_paths = [
            os.path.join(base_dir, f"{name}.txt"),
            os.path.join(base_dir, name),
        ]
        for path in candidate_paths:
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        lines = [
                            line.strip()
                            for line in f
                            if line.strip() and not line.strip().startswith("#")
                        ]
                    if lines:
                        return lines
                except OSError:
                    continue
    return []


def _choose_option(raw_options: list[str], rng: random.Random) -> str:
    """Select one option from a list, supporting `weight::choice` format."""
    weights = []
    choices = []
    for opt in raw_options:
        opt_str = opt.strip()
        if "::" in opt_str:
            parts = opt_str.split("::", 1)
            try:
                w = float(parts[0])
                if w > 0:
                    weights.append(w)
                    choices.append(parts[1].strip())
                    continue
            except ValueError:
                pass
        weights.append(1.0)
        choices.append(opt_str)

    if not choices:
        return ""
    return rng.choices(choices, weights=weights, k=1)[0]


class WildcardService:
    @classmethod
    def expand_wildcards(cls, text: str, seed: Optional[int] = None) -> str:
        """Expand dynamic braces `{a|b}` and `__wildcard__` tokens in prompt text."""
        if not text or not isinstance(text, str):
            return ""

        # If text has neither braces nor wildcards, return early
        if "{" not in text and "__" not in text:
            return text

        rng = random.Random(seed) if seed is not None else random.Random()
        expanded = text
        depth = 0

        while depth < _MAX_EXPANSION_DEPTH:
            has_braces = bool(_BRACE_PATTERN.search(expanded))
            has_wildcards = bool(_WILDCARD_PATTERN.search(expanded))

            if not has_braces and not has_wildcards:
                break

            # 1. Expand innermost braces first
            if has_braces:
                expanded = _BRACE_PATTERN.sub(
                    lambda m: _choose_option(m.group(1).split("|"), rng),
                    expanded,
                )

            # 2. Expand wildcard file tokens
            if has_wildcards:
                def replace_wildcard(m):
                    tag = m.group(1)
                    lines = _read_wildcard_lines(tag)
                    if lines:
                        return rng.choice(lines)
                    # If wildcard file doesn't exist, leave the token as is
                    return m.group(0)

                new_expanded = _WILDCARD_PATTERN.sub(replace_wildcard, expanded)
                # If wildcard replacement did not change anything, break to prevent loop
                if new_expanded == expanded and not has_braces:
                    break
                expanded = new_expanded

            depth += 1

        return expanded
