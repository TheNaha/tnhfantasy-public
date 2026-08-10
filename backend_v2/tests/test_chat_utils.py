# Tests for the canonical chat utilities (services/chat_utils.py).
#
# These lock down the tavern-variable substitution contract shared by
# context_builder.py and the world_vault chat routes, and the context-token
# resolution chain (chat override > global config > 4096 fallback).

from types import SimpleNamespace

from services.chat_utils import resolve_context_tokens, substitute_tavern_vars


class TestSubstituteTavernVars:
    def test_double_brace_forms(self):
        out = substitute_tavern_vars("Hello {{char}}, I am {{user}}!", char="Alice", user="Bob")
        assert out == "Hello Alice, I am Bob!"

    def test_legacy_single_brace_forms(self):
        out = substitute_tavern_vars("Hello {char}, I am {user}!", char="Alice", user="Bob")
        assert out == "Hello Alice, I am Bob!"

    def test_mixed_brace_forms(self):
        out = substitute_tavern_vars("{user} calls {{char}}!", char="Alice", user="Bob")
        assert out == "Bob calls Alice!"

    def test_time_and_date(self):
        out = substitute_tavern_vars("At {{time}} on {{date}}", char="Alice", user="Bob")
        assert "{{time}}" not in out and "{{date}}" not in out
        assert ":" in out

    def test_random_variable(self):
        out = substitute_tavern_vars("Pick: {{random::one::two::three}}")
        assert out in ("Pick: one", "Pick: two", "Pick: three")

    def test_unknown_variables_left_untouched(self):
        assert substitute_tavern_vars("{{unknown}} {also_unknown}", user="Bob") == "{{unknown}} {also_unknown}"

    def test_json_like_braces_untouched(self):
        assert substitute_tavern_vars('{"a": 1}', user="Bob") == '{"a": 1}'

    def test_no_braces_passthrough(self):
        assert substitute_tavern_vars("plain text", user="Bob") == "plain text"

    def test_empty_passthrough(self):
        assert substitute_tavern_vars("") == ""
        assert substitute_tavern_vars(None) is None


class TestResolveContextTokens:
    def test_chat_override_wins(self):
        chat = SimpleNamespace(max_context_tokens=1234)
        assert resolve_context_tokens(chat) == 1234

    def test_zero_chat_override_falls_through(self):
        chat = SimpleNamespace(max_context_tokens=0)
        # Falls through to config/default rather than returning 0.
        assert resolve_context_tokens(chat) >= 4096

    def test_no_chat_override_uses_default(self):
        chat = SimpleNamespace(max_context_tokens=None)
        assert resolve_context_tokens(chat) == 4096
