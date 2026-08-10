# Tests for services/orchestrator_service.py (agentic loop helpers)

import json
from unittest.mock import AsyncMock

import pytest

from services.orchestrator_service import (
    MAX_AGENTIC_DEPTH,
    can_continue_agentic,
    execute_tool,
    filter_agentic_tools,
    get_agentic_depth,
    has_tool_calls,
)


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "parameters": {}}}


# ── filter_agentic_tools ────────────────────────────────────────────────────

def test_filter_agentic_tools_none_returns_empty():
    assert filter_agentic_tools(None) == []
    assert filter_agentic_tools([]) == []


def test_filter_agentic_tools_keeps_all_by_default():
    tools = [_tool("generate_image"), _tool("narrate_scene"), _tool("update_world_state")]
    assert filter_agentic_tools(tools) == tools


def test_filter_agentic_tools_blocks_image_when_disallowed():
    tools = [_tool("generate_image"), _tool("update_world_state")]
    filtered = filter_agentic_tools(tools, allow_image=False)
    names = [t["function"]["name"] for t in filtered]
    assert names == ["update_world_state"]


def test_filter_agentic_tools_blocks_narration_when_disallowed():
    tools = [_tool("narrate_scene"), _tool("generate_image")]
    filtered = filter_agentic_tools(tools, allow_narration=False)
    names = [t["function"]["name"] for t in filtered]
    assert names == ["generate_image"]


# ── has_tool_calls / depth helpers ──────────────────────────────────────────

def test_has_tool_calls_true_and_false():
    assert has_tool_calls({"tool_calls": [{"id": "1"}]})
    assert not has_tool_calls({"tool_calls": []})
    assert not has_tool_calls({})


def test_get_agentic_depth_reads_metadata():
    assert get_agentic_depth(None) == 0
    assert get_agentic_depth({}) == 0
    assert get_agentic_depth({"orchestrator_depth": 3}) == 3


def test_can_continue_agentic_boundary():
    assert can_continue_agentic({"orchestrator_depth": MAX_AGENTIC_DEPTH - 1})
    assert not can_continue_agentic({"orchestrator_depth": MAX_AGENTIC_DEPTH})
    assert not can_continue_agentic({"orchestrator_depth": MAX_AGENTIC_DEPTH + 1})


# ── execute_tool dispatch ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_tool_unknown_returns_error():
    result = await execute_tool(_tool("no_such_tool"))
    assert result["status"] == "error"
    assert "Unknown tool" in result["error"]


@pytest.mark.asyncio
async def test_execute_tool_bad_json_arguments_defaults_empty(monkeypatch):
    gen = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr("services.orchestrator_service._tool_generate_image", gen)

    call = {"function": {"name": "generate_image", "arguments": "not json"}}
    result = await execute_tool(call, chat_id="c1", character_id="ch1", source_job_id="j1")
    assert result == {"status": "ok"}
    gen.assert_awaited_once()
    assert gen.await_args.args[0] == {}


@pytest.mark.asyncio
async def test_execute_tool_generate_image_dispatches(monkeypatch):
    gen = AsyncMock(return_value={"status": "ok", "image": "x.png"})
    monkeypatch.setattr("services.orchestrator_service._tool_generate_image", gen)

    call = {
        "function": {
            "name": "generate_image",
            "arguments": json.dumps({"prompt": "a dragon"}),
        }
    }
    result = await execute_tool(call, chat_id="c1", source_job_id="j1")
    assert result["image"] == "x.png"
    gen.assert_awaited_once()
    assert gen.await_args.args[0] == {"prompt": "a dragon"}


@pytest.mark.asyncio
async def test_execute_tool_narrate_scene_dispatches(monkeypatch):
    narr = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr("services.orchestrator_service._tool_narrate_scene", narr)

    call = {
        "function": {
            "name": "narrate_scene",
            "arguments": json.dumps({"direction": "storm rolls in"}),
        }
    }
    result = await execute_tool(call, chat_id="c1", source_job_id="j1")
    assert result == {"status": "ok"}
    narr.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_tool_update_world_state_dispatches(monkeypatch):
    # _tool_update_world_state is synchronous (unlike the async tools)
    calls = []
    def fake_update_world_state(args, **kwargs):
        calls.append((args, kwargs))
        return {"status": "ok"}
    monkeypatch.setattr("services.orchestrator_service._tool_update_world_state", fake_update_world_state)

    call = {
        "function": {
            "name": "update_world_state",
            "arguments": json.dumps({"time": "night"}),
        }
    }
    result = await execute_tool(call, chat_id="c1")
    assert result == {"status": "ok"}
    assert calls and calls[0][0] == {"time": "night"}
    assert calls[0][1] == {"chat_id": "c1", "source_job_id": None}