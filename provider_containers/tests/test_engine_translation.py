"""Tests for tool-call translation in the anthropic + google LLM engines.

Agentic mode (backend orchestrator_service) sends OpenAI-style tools and
messages; these engines must translate to/from their native dialects so
function calling works end-to-end.
"""


from llm_worker.engines.anthropic.client import translate_tools, translate_messages as anthropic_translate
from llm_worker.engines.google.client import translate_tools as google_translate_tools, translate_messages as google_translate


OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Generate an image",
            "parameters": {"type": "object", "properties": {"prompt": {"type": "string"}}},
        },
    },
]


class TestAnthropicTranslation:
    def test_translate_tools(self):
        result = translate_tools(OPENAI_TOOLS)
        assert result == [{
            "name": "generate_image",
            "description": "Generate an image",
            "input_schema": {"type": "object", "properties": {"prompt": {"type": "string"}}},
        }]

    def test_translate_tools_empty(self):
        assert translate_tools(None) == []
        assert translate_tools([]) == []

    def test_translate_messages_plain(self):
        messages, system = anthropic_translate([
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ])
        assert system == "You are helpful.\n"
        assert messages == [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]

    def test_translate_assistant_tool_calls(self):
        messages, _ = anthropic_translate([
            {
                "role": "assistant",
                "content": "Let me do that.",
                "tool_calls": [
                    {"id": "call_1", "type": "function",
                     "function": {"name": "generate_image", "arguments": '{"prompt": "cat"}'}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "name": "generate_image", "content": '{"ok": true}'},
        ])
        assert messages == [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me do that."},
                    {"type": "tool_use", "id": "call_1", "name": "generate_image",
                     "input": {"prompt": "cat"}},
                ],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": '{"ok": true}'}],
            },
        ]

    def test_translate_messages_invalid_json_arguments(self):
        messages, _ = anthropic_translate([
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c", "type": "function", "function": {"name": "f", "arguments": "not-json"}},
            ]},
        ])
        assert messages[0]["content"][0]["input"] == "not-json"


class TestGoogleTranslation:
    def test_translate_tools(self):
        result = google_translate_tools(OPENAI_TOOLS)
        assert result == [{
            "functionDeclarations": [{
                "name": "generate_image",
                "description": "Generate an image",
                "parameters": {"type": "object", "properties": {"prompt": {"type": "string"}}},
            }],
        }]

    def test_translate_messages_plain(self):
        contents, system = google_translate([
            {"role": "system", "content": "Be nice."},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ])
        assert system == "Be nice.\n"
        assert contents == [
            {"role": "user", "parts": [{"text": "Hi"}]},
            {"role": "model", "parts": [{"text": "Hello"}]},
        ]

    def test_translate_assistant_tool_calls_and_results(self):
        contents, _ = google_translate([
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "generate_image", "arguments": '{"prompt": "cat"}'}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "name": "generate_image", "content": '{"ok": true}'},
        ])
        assert contents == [
            {"role": "model", "parts": [
                {"functionCall": {"name": "generate_image", "args": {"prompt": "cat"}}},
            ]},
            {"role": "user", "parts": [
                {"functionResponse": {"name": "generate_image", "response": {"ok": True}}},
            ]},
        ]

    def test_translate_messages_invalid_json_arguments_wrapped(self):
        contents, _ = google_translate([
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c", "type": "function", "function": {"name": "f", "arguments": "not-json"}},
            ]},
        ])
        args = contents[0]["parts"][0]["functionCall"]["args"]
        assert args == {"value": "not-json"}
