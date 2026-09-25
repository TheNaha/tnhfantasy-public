# Focused tests for the SillyTavern macro engine + chat lorebook linking.
#
# Split out from test_chat_utils.py so the extended macro surface
# (persona / original / roll / pick / newline / nesting) and the
# Character.embedded_lorebook_id auto-link stay in one reviewable place.

from datetime import datetime, timezone
from types import SimpleNamespace

from services.chat_utils import link_embedded_lorebook, substitute_tavern_vars


FIXED_NOW = datetime(2026, 9, 25, 14, 7, 3, tzinfo=timezone.utc)


def _sub(text: str, **kwargs) -> str:
    kwargs.setdefault("now", FIXED_NOW)
    return substitute_tavern_vars(text, **kwargs)


class TestPersonaAndOriginalMacros:
    def test_persona_expands_to_persona_description(self):
        out = _sub("You face {{persona}}.", persona_description="A wary smuggler")
        assert out == "You face A wary smuggler."

    def test_persona_is_case_insensitive(self):
        assert _sub("{{PERSONA}}", persona_description="Vex") == "Vex"

    def test_persona_intact_when_no_description(self):
        # No value to substitute -> token preserved, as with unknown macros.
        assert _sub("Hello {{persona}}") == "Hello {{persona}}"

    def test_original_expands_to_character_prompt(self):
        out = _sub("Override: {{original}}", original="You are Aria, a cartographer.")
        assert out == "Override: You are Aria, a cartographer."

    def test_original_intact_when_unavailable(self):
        assert _sub("{{original}}") == "{{original}}"

    def test_legacy_single_brace_persona(self):
        assert _sub("Hi {persona}", persona_description="Rook") == "Hi Rook"


class TestTimeDateDeterminism:
    def test_time_and_date_use_injected_now(self):
        out = _sub("{{time}} / {{date}}", now=FIXED_NOW)
        assert out == "14:07 / 2026-09-25"

    def test_legacy_single_brace_time(self):
        assert _sub("{time}", now=FIXED_NOW) == "14:07"

    def test_time_with_argument_left_intact(self):
        # Timezone-offset arguments are not supported -> not half-expanded.
        assert _sub("{{time::UTC+8}}", now=FIXED_NOW) == "{{time::UTC+8}}"


class TestRandomAndPick:
    def test_pick_selects_one_option(self):
        out = _sub("{{pick::red::green::blue}}")
        assert out in ("red", "green", "blue")

    def test_legacy_single_brace_random(self):
        out = _sub("colour {random::red::green::blue}")
        assert out.startswith("colour ") and out.split(" ", 1)[1] in ("red", "green", "blue")

    def test_random_with_no_options_left_intact(self):
        assert _sub("{{random::}}") == "{{random::}}"
        assert _sub("{{random}}") == "{{random}}"

    def test_random_ignores_empty_options(self):
        out = _sub("{{random::a::::b}}")
        assert out in ("a", "b")

    def test_random_expands_nested_macro_in_option(self):
        out = _sub("{{random::{{char}}::{{user}}}}", char="Aria", user="Vex")
        assert out in ("Aria", "Vex")

    def test_pick_expands_nested_random_option(self):
        # Regression: a nested macro inside a pick option must resolve before
        # the option list is built, not survive as literal "{{random::..}}".
        out = _sub("{{pick::{{random::Aria::Vex}}::Other}}")
        assert out in ("Aria", "Vex", "Other")
        assert "random" not in out

    def test_roll_expands_nested_char(self):
        out = _sub("{{roll::1d2}}+{{char}}", char="Aria")
        assert out.endswith("+Aria")
        assert 1 <= int(out[0]) <= 2


class TestRollMacro:
    def test_two_dice_sum_format(self):
        out = _sub("{{roll::2d20}}")
        left, total = out.rsplit(" = ", 1)
        a, b = (int(p.strip()) for p in left.split(" + "))
        assert 1 <= a <= 20 and 1 <= b <= 20
        assert int(total) == a + b

    def test_single_die_is_bare_number(self):
        out = _sub("{{roll::d6}}")
        assert 1 <= int(out) <= 6

    def test_bare_number_is_one_die(self):
        out = _sub("{{roll::20}}")
        assert 1 <= int(out) <= 20

    def test_modifier_is_applied(self):
        out = _sub("{{roll::2d6+3}}")
        terms, total = out.rsplit(" = ", 1)
        assert terms.endswith("+3")
        dice = [int(t) for t in terms.split(" + ")[:-1]]
        assert len(dice) == 2 and all(1 <= d <= 6 for d in dice)
        assert int(total) == sum(dice) + 3

    def test_negative_modifier(self):
        out = _sub("{{roll::1d6-2}}")
        terms, total = out.rsplit(" = ", 1)
        die = int(terms.split(" + ")[0])
        assert terms.endswith("-2")
        assert int(total) == die - 2

    def test_case_insensitive_d(self):
        assert _sub("{{roll::1D6}}").isdigit()

    def test_legacy_single_brace_roll(self):
        out = _sub("{roll:1d4}")
        assert 1 <= int(out) <= 4

    def test_invalid_expression_left_intact(self):
        assert _sub("{{roll::banana}}") == "{{roll::banana}}"
        assert _sub("{{roll::}}") == "{{roll::}}"

    def test_dice_count_capped(self):
        # Beyond the safety bound the token survives rather than emitting 1e6 rolls.
        assert _sub("{{roll::9999d6}}") == "{{roll::9999d6}}"


class TestNewlineMacro:
    def test_bare_newline(self):
        assert _sub("a{{newline}}b") == "a\nb"

    def test_newline_with_count(self):
        assert _sub("a{{newline::3}}b") == "a\n\n\nb"

    def test_newline_count_capped(self):
        assert _sub("{{newline::50}}") == "\n" * 10

    def test_invalid_count_left_intact(self):
        assert _sub("{{newline::many}}") == "{{newline::many}}"


class TestUnknownTokensAndNesting:
    def test_unknown_macros_unchanged(self):
        assert _sub("{{unknown}} {also_unknown}") == "{{unknown}} {also_unknown}"

    def test_json_like_braces_unchanged(self):
        assert _sub('{"a": 1}') == '{"a": 1}'

    def test_unterminated_macro_unchanged(self):
        assert _sub("{{char and {user") == "{{char and {user"

    def test_nested_macro_inside_unknown_macro(self):
        out = _sub("{{unknown {{char}}}}", char="Aria")
        assert out == "{{unknown Aria}}"

    def test_json_still_untouched_alongside_macros(self):
        out = _sub('{"char": "{{char}"}', char="Aria")
        # The unterminated "{{char}" is preserved verbatim rather than
        # half-expanded into a stray "{Aria".
        assert out == '{"char": "{{char}"}'

    def test_single_brace_inside_braces_still_resolves(self):
        assert _sub("{ {user} }", user="Vex") == "{ Vex }"

    def test_repeated_mixed_forms(self):
        out = _sub("{{char}}/{user}/{char}", char="Aria", user="Vex")
        assert out == "Aria/Vex/Aria"

    def test_passthrough_cases(self):
        assert substitute_tavern_vars("") == ""
        assert substitute_tavern_vars(None) is None
        assert _sub("plain text") == "plain text"

    def test_pathological_unbalanced_braces_stay_linear(self):
        # Unbalanced "{{" everywhere plus one trailing "}": must terminate
        # quickly and must not drop or invent text.
        import time

        text = "{{" * 20000 + "}"
        start = time.monotonic()
        out = _sub(text)
        assert time.monotonic() - start < 5
        assert out.endswith("}")
        assert out.count("{") == text.count("{")

    def test_long_card_with_many_macros(self):
        card = ("Narrative line. {{char}} greets {{user}}.\n" * 5000) + "{{pick::a::b}}"
        out = _sub(card, char="Aria", user="Vex")
        assert out.count("Aria greets Vex.") == 5000
        assert out.endswith("a") or out.endswith("b")


class TestLinkEmbeddedLorebook:
    def test_appends_embedded_lorebook(self):
        char = SimpleNamespace(embedded_lorebook_id="lb-embedded")
        assert link_embedded_lorebook(["lb-manual"], char) == ["lb-manual", "lb-embedded"]

    def test_preserves_requested_order_and_dedupes(self):
        char = SimpleNamespace(embedded_lorebook_id="lb-embedded")
        assert link_embedded_lorebook(["lb-a", "lb-embedded", "lb-b"], char) == [
            "lb-a",
            "lb-embedded",
            "lb-b",
        ]

    def test_no_requested_lorebooks(self):
        char = SimpleNamespace(embedded_lorebook_id="lb-embedded")
        assert link_embedded_lorebook(None, char) == ["lb-embedded"]

    def test_missing_column_is_noop(self):
        # Character has no embedded_lorebook_id until the card-import column
        # exists — the helper must not raise or invent a link.
        assert link_embedded_lorebook(["lb-a"], SimpleNamespace()) == ["lb-a"]
        assert link_embedded_lorebook(["lb-a"], None) == ["lb-a"]
        assert link_embedded_lorebook(None, None) == []

    def test_empty_embedded_id_ignored(self):
        char = SimpleNamespace(embedded_lorebook_id=None)
        assert link_embedded_lorebook(["lb-a"], char) == ["lb-a"]
