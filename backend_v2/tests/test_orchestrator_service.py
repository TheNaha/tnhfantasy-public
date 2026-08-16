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
    # _tool_update_world_state is async (opens its own DB session), so the
    # mock must be a coroutine function — execute_tool awaits it.
    calls = []
    async def fake_update_world_state(args, **kwargs):
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

# ── process_tool_calls_and_chain: follow-up tool gating (Batch 1.5) ──────────

class _FakeJob:
    """Minimal stand-in for a Job row used by the chain helper."""

    def __init__(self, job_id="j1", messages=None):
        self.id = job_id
        self.workflow = {"messages": messages or [{"role": "user", "content": "hi"}], "model": "m1"}
        self.metadata_ = {
            "agentic": True,
            "orchestrator_depth": 1,
            "max_agentic_depth": 3,
            "original_messages": [{"role": "user", "content": "hi"}],
        }


def _tool_call(name, call_id="c1"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": "{}"}}


async def _fake_execute_tool(tc, **kwargs):
    return {"status": "ok"}


def _chain_fixtures(monkeypatch, assistant_tool_calls, allowed_tools=None):
    from services.orchestrator_service import AGENTIC_TOOLS, process_tool_calls_and_chain

    monkeypatch.setattr("services.orchestrator_service.execute_tool", _fake_execute_tool)

    captured = {"workflow": None, "enqueued": []}

    def fake_build_llm_workflow(*, messages, type_, chat_id, character_id, character_system_prompt,
                                model, workspace, parent_job_id, extra_metadata):
        return ({"messages": messages, "type": type_, "model": model}, {"type": type_})

    monkeypatch.setattr("services.llm_workflow.build_llm_workflow", fake_build_llm_workflow)

    class _FakeJobService:
        async def create_job(self, *, task_type, workflow, metadata):
            captured["workflow"] = workflow
            return _FakeJob(job_id="j2")

    async def fake_enqueue(job_id, **kw):
        captured["enqueued"].append(job_id)

    return process_tool_calls_and_chain, AGENTIC_TOOLS, captured, _FakeJobService(), fake_enqueue


@pytest.mark.asyncio
async def test_followup_workflow_tools_filtered_by_allowlist(monkeypatch):
    chain, AGENTIC_TOOLS, captured, job_service, enqueue = _chain_fixtures(
        monkeypatch,
        [_tool_call("generate_image", "c1"), _tool_call("narrate_scene", "c2")],
        allowed_tools={"narrate_scene"},
    )
    result = await chain(
        job=_FakeJob(),
        assistant_output={"tool_calls": [_tool_call("generate_image", "c1"), _tool_call("narrate_scene", "c2")]},
        final_result={},
        chat_id="c1",
        character_id=None,
        job_service=job_service,
        enqueue_fn=enqueue,
        allowed_tools={"narrate_scene"},
    )
    assert result is True
    tool_names = [t["function"]["name"] for t in captured["workflow"]["tools"]]
    assert "narrate_scene" in tool_names
    assert "generate_image" not in tool_names
    assert captured["enqueued"] == ["j2"]


@pytest.mark.asyncio
async def test_followup_workflow_full_tools_when_no_allowlist(monkeypatch):
    chain, AGENTIC_TOOLS, captured, job_service, enqueue = _chain_fixtures(
        monkeypatch, [_tool_call("generate_image", "c1")],
    )
    result = await chain(
        job=_FakeJob(),
        assistant_output={"tool_calls": [_tool_call("generate_image", "c1")]},
        final_result={},
        chat_id="c1",
        character_id=None,
        job_service=job_service,
        enqueue_fn=enqueue,
        allowed_tools=None,
    )
    assert result is True
    assert captured["workflow"]["tools"] == AGENTIC_TOOLS


@pytest.mark.asyncio
async def test_followup_all_tools_filtered_returns_false(monkeypatch):
    chain, AGENTIC_TOOLS, captured, job_service, enqueue = _chain_fixtures(
        monkeypatch, [_tool_call("generate_image", "c1")],
    )
    result = await chain(
        job=_FakeJob(),
        assistant_output={"tool_calls": [_tool_call("generate_image", "c1")]},
        final_result={},
        chat_id="c1",
        character_id=None,
        job_service=job_service,
        enqueue_fn=enqueue,
        allowed_tools={"narrate_scene"},
    )
    assert result is False
    assert captured["workflow"] is None
    assert captured["enqueued"] == []
