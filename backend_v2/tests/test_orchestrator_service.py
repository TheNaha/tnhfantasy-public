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
    tools = [_tool("generate_image"), _tool("other_tool"), _tool("another_tool")]
    assert filter_agentic_tools(tools) == tools


def test_filter_agentic_tools_blocks_image_when_disallowed():
    tools = [_tool("generate_image"), _tool("other_tool")]
    filtered = filter_agentic_tools(tools, allow_image=False)
    names = [t["function"]["name"] for t in filtered]
    assert names == ["other_tool"]


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
                                model, workspace, parent_job_id, extra_metadata, samplers=None,
                                story_id=None, chapter_id=None):
        wf = {"messages": messages, "type": type_, "model": model}
        if samplers:
            wf.update(samplers)
        return (wf, {"type": type_, "story_id": story_id})

    monkeypatch.setattr("services.llm_workflow.build_llm_workflow", fake_build_llm_workflow)

    class _FakeJobService:
        async def create_job(self, *, task_type, workflow, metadata):
            captured["workflow"] = workflow
            captured["metadata"] = metadata
            return _FakeJob(job_id="j2")

    async def fake_enqueue(job_id, **kw):
        captured["enqueued"].append(job_id)

    return process_tool_calls_and_chain, AGENTIC_TOOLS, captured, _FakeJobService(), fake_enqueue


@pytest.mark.asyncio
async def test_followup_workflow_tools_filtered_by_allowlist(monkeypatch):
    chain, AGENTIC_TOOLS, captured, job_service, enqueue = _chain_fixtures(
        monkeypatch,
        [_tool_call("generate_image", "c1"), _tool_call("other_tool", "c2")],
        allowed_tools={"other_tool"},
    )
    result = await chain(
        job=_FakeJob(),
        assistant_output={"tool_calls": [_tool_call("generate_image", "c1"), _tool_call("other_tool", "c2")]},
        final_result={},
        chat_id="c1",
        character_id=None,
        job_service=job_service,
        enqueue_fn=enqueue,
        allowed_tools={"other_tool"},
    )
    assert result is True
    tool_names = [t["function"]["name"] for t in captured["workflow"]["tools"]]
    # AGENTIC_TOOLS only offers generate_image now, so the allow-list leaves nothing to re-offer.
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
        allowed_tools={"other_tool"},
    )
    assert result is False
    assert captured["workflow"] is None
    assert captured["enqueued"] == []


# ── Story agentic mode ────────────────────────────────────────────────────────


def test_story_agentic_tools_only_image():
    from services.orchestrator_service import story_agentic_tools

    tools = story_agentic_tools()
    names = [t["function"]["name"] for t in tools]
    assert names == ["generate_image"]


@pytest.mark.asyncio
async def test_followup_story_mode_builds_story_continue(monkeypatch):
    chain, _AGENTIC_TOOLS, captured, job_service, enqueue = _chain_fixtures(
        monkeypatch, [_tool_call("generate_image", "c1")],
        allowed_tools={"generate_image"},
    )
    result = await chain(
        job=_FakeJob(),
        assistant_output={"tool_calls": [_tool_call("generate_image", "c1")]},
        final_result={},
        chat_id=None,
        character_id=None,
        job_service=job_service,
        enqueue_fn=enqueue,
        allowed_tools={"generate_image"},
        story_id="s1",
        chapter_id="ch1",
    )
    assert result is True
    wf = captured["workflow"]
    assert wf["type"] == "story_continue"
    tool_names = [t["function"]["name"] for t in wf["tools"]]
    assert tool_names == ["generate_image"]


@pytest.mark.asyncio
async def test_followup_story_mode_filters_chat_only_tools(monkeypatch):
    chain, _AGENTIC_TOOLS, captured, job_service, enqueue = _chain_fixtures(
        monkeypatch, [_tool_call("other_tool", "c1"), _tool_call("generate_image", "c2")],
        allowed_tools={"other_tool", "generate_image"},
    )
    result = await chain(
        job=_FakeJob(),
        assistant_output={
            "tool_calls": [_tool_call("other_tool", "c1"), _tool_call("generate_image", "c2")]
        },
        final_result={},
        chat_id=None,
        character_id=None,
        job_service=job_service,
        enqueue_fn=enqueue,
        allowed_tools={"other_tool", "generate_image"},
        story_id="s1",
        chapter_id="ch1",
    )
    # other_tool executed (parent allow-list) but the follow-up workflow
    # must only re-offer story-safe tools.
    assert result is True
    tool_names = [t["function"]["name"] for t in captured["workflow"]["tools"]]
    assert tool_names == ["generate_image"]


def test_tool_generate_image_story_mode_routes_to_story_workspace():
    import inspect

    from services.orchestrator_service import _tool_generate_image

    src = inspect.getsource(_tool_generate_image)
    assert 'workspace="story"' in src
    assert "StoryAgenticGen" in src


class TestImageToolDoesNotBlock:
    """`_tool_generate_image` must submit, not wait.

    It used to `await wait_for_job_completion(job.id, timeout=330.0)` — blocking
    the single LLM worker for up to five and a half minutes inside one tool call.
    Because the reply `Message` is written only once the parent job's
    JOB_COMPLETED arrives and the parent cannot finalise until every chained hop
    is enqueued, a user who typed one line waited on an image they never asked
    for, and the reply was not in the database yet either — so a reload in that
    window lost a paid generation.

    The image does not need waiting for: it lands on its own JOB_COMPLETED, where
    `world_integration_service._handle_chat_image` appends an IMAGE message to
    the same chat (that path already special-cases `source == "agentic_tool"`).
    """

    def _submit(self, monkeypatch, **kw):
        """Drive `_tool_generate_image` past availability with a fake submit."""
        from services import orchestrator_service as orch

        captured = {}

        async def fake_submit(session, *, prompt, **kwargs):
            from types import SimpleNamespace

            captured.update(kwargs)
            return SimpleNamespace(id="job-image-1")

        monkeypatch.setattr("services.image_submission.submit_image_job", fake_submit)
        monkeypatch.setattr(
            "services.model_availability_service.ModelAvailabilityService"
            ".get_available_checkpoint",
            lambda self, name=None: "sd-comfy.safetensors",
        )
        monkeypatch.setattr(
            "services.model_availability_service.ModelAvailabilityService"
            ".get_available_lora",
            lambda self, name=None: None,
        )
        return orch, captured

    async def _run(self, monkeypatch, **kw):

        from services import orchestrator_service as orch

        # A session so `get_session_context()` works without the app lifespan.
        from sqlmodel import Session, SQLModel, create_engine

        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        class _Ctx:
            async def __aenter__(self):
                return Session(engine)

            async def __aexit__(self, *exc):
                return False

        # `get_session_context` is imported INSIDE the function body, so the
        # patch has to target `infrastructure.deps`, not this module.
        monkeypatch.setattr("infrastructure.deps.get_session_context", lambda: _Ctx())
        self._submit(monkeypatch, **kw)
        return await orch._tool_generate_image(
            {"prompt": "a castle at dusk"}, chat_id="chat-1", character_id=None,
            source_job_id=None,
        )

    @pytest.mark.asyncio
    async def test_returns_queued_without_waiting(self, monkeypatch):

        waited = []

        def _boom(*a, **kw):
            waited.append(True)
            raise AssertionError("the tool must not wait for the image job")

        monkeypatch.setattr("core.events.wait_for_job_completion", _boom)

        result = await self._run(monkeypatch)

        assert result["status"] == "queued", result
        assert result["job_id"] == "job-image-1"
        assert "background" in result["note"], (
            "the model must be told not to claim the image exists yet"
        )
        assert not waited, "the tool waited for the image job"

    @pytest.mark.asyncio
    async def test_does_not_reference_the_blocking_waiter_at_all(self, monkeypatch):
        """Structural: the waiter is gone, not merely unused.

        A dead import would keep the failure one git-revert away.
        """
        import ast
        import inspect

        import services.orchestrator_service as orch

        fn = orch._tool_generate_image
        # Check the executed statements, not the text: the explanatory comment
        # quotes the old call, and a text match would flag its own prose.
        tree = ast.parse(inspect.getsource(fn))
        awaits = {
            ast.unparse(n)
            for n in ast.walk(tree)
            if isinstance(n, ast.Await) and isinstance(n.value, ast.Call)
        }
        blocking = [a for a in awaits if "wait_for_job_completion" in a]
        assert not blocking, f"the image tool still awaits: {blocking}"


# ── Agentic image budget ─────────────────────────────────────────────────────
#
# The depth cap counts LLM hops. A hop is cheap, an image is not, and
# `generate_image` was callable once per hop, so one reply could chain five paid
# image jobs while the user asked for one. The budget is the cap that answers
# "how much am I spending on this exchange".


def test_the_default_budget_is_not_the_depth_cap():
    """Two different limits, because they answer different questions."""
    from services.orchestrator_service import MAX_AGENTIC_IMAGES_PER_EXCHANGE

    assert MAX_AGENTIC_IMAGES_PER_EXCHANGE != MAX_AGENTIC_DEPTH


def test_budget_remaining_defaults_to_two_images():
    from services.orchestrator_service import (
        MAX_AGENTIC_IMAGES_PER_EXCHANGE,
        image_budget_remaining,
    )

    assert image_budget_remaining({}) == MAX_AGENTIC_IMAGES_PER_EXCHANGE
    assert image_budget_remaining(None) == MAX_AGENTIC_IMAGES_PER_EXCHANGE


def test_budget_remaining_is_never_negative():
    from services.orchestrator_service import image_budget_remaining

    assert image_budget_remaining({"agentic_image_jobs": 99}) == 0


def test_an_explicit_zero_means_no_images_rather_than_unset():
    """`is None`, not falsiness.

    A user who wants the agentic loop minus images turns the tool off by setting
    0. If falsiness were the unset test, the 0 would fall through to the global
    default and they would get two images anyway.
    """
    from services.orchestrator_service import get_max_agentic_images, image_budget_remaining

    class _Entity:
        max_agentic_images = 0

    assert get_max_agentic_images(_Entity()) == 0
    assert image_budget_remaining({}, _Entity()) == 0


def test_entity_override_beats_metadata_and_global_default():
    from services.orchestrator_service import get_max_agentic_images

    class _Entity:
        max_agentic_images = 1

    assert get_max_agentic_images(_Entity(), {"max_agentic_images": 7}) == 1
    assert get_max_agentic_images(None, {"max_agentic_images": 7}) == 7
    assert get_max_agentic_images(None, None) != 7


def test_budget_is_carried_across_hops_not_reset_per_hop():
    """The carry is what makes it per-exchange.

    Dropping `agentic_image_jobs` from the chained job's metadata would make the
    cap "one image per hop" — four more images than the user asked for.
    """

    from services.orchestrator_service import get_agentic_image_count

    def _image_calls(n, start=0):
        return [_tool_call("generate_image", f"c{start + i}") for i in range(n)]

    async def _fake_execute(tc, **kwargs):
        return {"status": "ok"}

    import services.orchestrator_service as orch

    class _Job:
        id = "j1"
        workflow = {"messages": [{"role": "user", "content": "hi"}], "model": "m"}
        metadata_ = {
            "agentic": True,
            "orchestrator_depth": 0,
            "max_agentic_depth": 5,
            # Already spent one image on an earlier hop.
            "agentic_image_jobs": 1,
            "max_agentic_images": 2,
            "original_messages": [{"role": "user", "content": "hi"}],
        }

    captured = {}

    class _JobService:
        async def create_job(self, *, task_type, workflow, metadata):
            captured["metadata"] = metadata
            captured["workflow"] = workflow
            return _Job()

    async def _enqueue(job_id, **kw):
        captured["enqueued"] = job_id

    from unittest.mock import patch

    with patch.object(orch, "execute_tool", _fake_execute):
        import asyncio

        result = asyncio.run(
            orch.process_tool_calls_and_chain(
                job=_Job(),
                assistant_output={"tool_calls": _image_calls(3)},
                final_result={},
                chat_id="c1",
                character_id=None,
                job_service=_JobService(),
                enqueue_fn=_enqueue,
                allowed_tools=None,
            )
        )

    # One image granted, two refused as the budget is already half spent.
    assert result is True
    assert get_agentic_image_count(captured["metadata"]) == 2


@pytest.mark.asyncio
async def test_the_second_hop_refuses_and_keeps_the_conversation_well_formed(monkeypatch):
    """A refused call still gets a tool result.

    Dropping it without a result is an error to the model — it produces a
    malformed follow-up or loops asking again, and the loop still costs an LLM
    hop per retry.
    """

    import services.orchestrator_service as orch

    seen = []

    async def _fake_execute(tc, **kwargs):
        seen.append(tc.get("id"))
        return {"status": "ok"}

    class _Job:
        id = "j1"
        workflow = {"messages": [{"role": "user", "content": "hi"}], "model": "m"}
        metadata_ = {
            "agentic": True,
            "orchestrator_depth": 0,
            "max_agentic_depth": 5,
            "max_agentic_images": 0,  # off
            "original_messages": [{"role": "user", "content": "hi"}],
        }

    captured = {}

    class _JobService:
        async def create_job(self, *, task_type, workflow, metadata):
            captured["messages"] = workflow["messages"]
            return _Job()

    async def _enqueue(job_id, **kw):
        pass

    monkeypatch.setattr(orch, "execute_tool", _fake_execute)

    await orch.process_tool_calls_and_chain(
        job=_Job(),
        assistant_output={"tool_calls": [_tool_call("generate_image", "c1")]},
        final_result={},
        chat_id="c1",
        character_id=None,
        job_service=_JobService(),
        enqueue_fn=_enqueue,
        allowed_tools=None,
    )

    # No image was generated, and the follow-up context carries a tool result so
    # the model's final turn is a text reply rather than a malformed one.
    assert seen == []
    messages = captured["messages"]
    # `context.append(assistant_output)` appends the whole assistant message
    # object, and the tool results follow it.
    tool = [m for m in messages if m.get("role") == "tool"][-1]
    assert tool["name"] == "generate_image"
    assert "budget" in tool["content"]
    assert messages[-1] is tool


# ── Tool budgets ─────────────────────────────────────────────────────────────


def test_budget_metadata_for_stamps_every_costed_tool():
    """One place, read from the table, so a new tool needs one row not four edits.

    This used to be written out by hand at four sites. The image budget was added
    to the chat routes and the story route kept only the depth cap, so a story's
    autonomous illustration ran at the global default whatever its panel said.
    """
    from services.orchestrator_service import COSTLY_TOOL_NAMES, budget_metadata_for

    assert budget_metadata_for(None) == {}

    class _Entity:
        max_agentic_images = 3
        max_agentic_narrations = 0

    stamped = budget_metadata_for(_Entity())
    assert stamped["max_agentic_images"] == 3
    # `max_agentic_narrations` remains a DB column for compat but is no longer
    # a costed tool, so it is not stamped.
    assert "max_agentic_narrations" not in stamped
    # Everything the table declares, so a new costed tool shows up here without
    # a test change — which is the point of reading the table.
    from services.orchestrator_service import TOOL_BUDGETS

    assert set(stamped) == {column for _c, column, _d in TOOL_BUDGETS.values()}
    assert COSTLY_TOOL_NAMES == {"generate_image"}


def test_budget_metadata_for_skips_unset_columns():
    """An absent column reads as the global default; an explicit None would shadow it."""
    from services.orchestrator_service import budget_metadata_for

    class _Entity:
        max_agentic_images = None
        max_agentic_narrations = None

    assert budget_metadata_for(_Entity()) == {}


# ── one resolver for the depth cap ───────────────────────────────────────────
#
# The cap used to be applied twice with different values: `job_processing` read
# the bare MAX_AGENTIC_DEPTH literal for a chat job and the resolved value for a
# story one. Since the routes stamp the configured cap onto the job's metadata,
# a chat set to 8 was silently capped at 5 — and which cap applied depended only
# on which branch of that ternary the job took.


def test_the_depth_cap_is_resolved_from_metadata_not_a_literal():
    import inspect

    from services import job_processing

    source = inspect.getsource(job_processing._finalize_llm_job)
    assert "get_max_agentic_depth(" in source
    # The literal constant has no business in this file's cap expression: its
    # own docstring says the routes stamp the configured value.
    assert "else MAX_AGENTIC_DEPTH" not in source
    assert "is_story_job\n                else MAX_AGENTIC_DEPTH" not in source


def test_a_chat_depth_above_the_global_default_is_honoured():
    from services.orchestrator_service import get_max_agentic_depth

    # A chat that set its own depth gets it, rather than the global constant.
    assert get_max_agentic_depth(metadata={"max_agentic_depth": 8}) == 8
    # Unset still falls back to the global default.
    assert get_max_agentic_depth(metadata={}) == 5
