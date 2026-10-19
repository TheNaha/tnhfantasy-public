"""
Agentic Orchestrator Service

Executes tool calls from LLM responses and chains follow-up jobs.
Works as a post-completion processor inside job_processing.py:
  1. LLM returns tool_calls → execute tools (create sub-jobs, wait)
  2. Feed tool results back as a follow-up LLM job
  3. Repeat until plain text response (max depth enforced)
"""

import asyncio
import json
import os
from typing import Any

from infrastructure.logging import get_logger
from services.model_availability_service import ModelAvailabilityService

logger = get_logger("orchestrator")

MAX_AGENTIC_DEPTH = 5

# How many images one exchange may spend, when the chat/story sets no limit.
#
# The depth cap above counts LLM hops; a hop is cheap. An image is not, and
# `generate_image` was callable once per hop with nothing else in the way, so a
# single reply could chain five paid image jobs while the user asked for one.
# The cap that matters for cost is this one, not the hop count — and a user who
# turns agentic images ON is asking for "illustrate this", not "illustrate every
# beat".
# The cost caps.
#
# `MAX_AGENTIC_DEPTH` above bounds how many times the model may THINK. These
# bound what it may SPEND, which is a different question and was the one nobody
# asked: `generate_image` was callable once per hop with nothing in the way, so a
# single reply could chain `max_depth` paid image jobs while the user asked for
# one.
#
# `narrate_scene` is here for the same reason and it was the worse of the two.
# An image is a side effect the user may have wanted; a narration is always a
# whole extra LLM completion, it is the one tool the model is most likely to
# reach for, and it had no cap at all — so the single most expensive
# discretionary decision in the loop was also the only unbounded one.
MAX_AGENTIC_IMAGES_PER_EXCHANGE = 2
MAX_AGENTIC_NARRATIONS_PER_EXCHANGE = 1

IMAGE_TOOL_NAME = "generate_image"

# tool name -> (counter key in job metadata, per-entity column, global default).
#
# A table rather than two bespoke functions, because the next tool with a cost
# should be a row here and not another copy of the gate. `update_story_rewrites`
# and the chat/story routes read the column names from it.
TOOL_BUDGETS: dict[str, tuple[str, str, int]] = {
    IMAGE_TOOL_NAME: (
        "agentic_image_jobs",
        "max_agentic_images",
        MAX_AGENTIC_IMAGES_PER_EXCHANGE,
    ),
}

# Every tool that costs money when called. Used by the callers that stamp a
# chat's or story's settings onto the job, so a new row there is picked up.
COSTLY_TOOL_NAMES = frozenset(TOOL_BUDGETS)

# Top-level guard so a single misbehaving tool whose internal call does not
# enforce its own timeout cannot hang the agentic loop indefinitely. Inner
# per-call timeouts (call_llm_provider, wait_for_job_completion) are still
# kept; this is a safety net above them.
TOOL_TIMEOUT = int(os.getenv("COMFY_TOOL_TIMEOUT", "360"))

NARRATOR_SYSTEM_PROMPT = (
    "You are the Narrator of an interactive story — a separate role from the characters. "
    "Your job is to describe the world around the conversation from a third-person standpoint: "
    "the environment, the passage of time, off-screen events, and transitions between scenes. "
    "When the characters agree to meet somewhere, you narrate what happens between the decision "
    "and the meeting. Decide what the story needs most: continue the dialogue, add background "
    "information, or cut to a new scene. Write vivid, cinematic prose in the third person, "
    "present tense, describing actions, atmosphere, and surroundings — never speak as a "
    "character and never write dialogue. Keep it concise (2-5 sentences) unless a scene "
    "transition truly demands more."
)

AGENTIC_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": (
                "Generate an image based on a detailed prompt. "
                "Use this when the conversation calls for visual content: "
                "scene illustrations, character portraits, action shots, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": (
                            "A detailed image generation prompt using comma-separated tags "
                            "(Danbooru style). Include subject, pose, lighting, camera angle, "
                            "style, and quality tags."
                        ),
                    },
                    "negative_prompt": {
                        "type": "string",
                        "description": "Negative prompt to avoid unwanted features.",
                    },
                },
                "required": ["prompt"],
            },
        },
    },
]


def filter_agentic_tools(
    tools: list[dict[str, Any]] | None,
    allow_image: bool = True,
    allow_narration: bool = True,
) -> list[dict[str, Any]]:
    """Return the subset of AGENTIC_TOOLS the chat is permitted to use.

    AGENTIC_TOOLS is a list of dicts, so it must never be passed through
    ``set()`` (dicts are unhashable -> TypeError). Filter with a list
    comprehension instead.
    """
    if not tools:
        return []
    allowed: list[dict[str, Any]] = []
    for tool in tools:
        name = tool.get("function", {}).get("name")
        if name == "generate_image" and not allow_image:
            continue
        allowed.append(tool)
    return allowed


def story_agentic_tools() -> list[dict[str, Any]]:
    """Tool subset available to story continuations.

    Stories have no chat entity, so narration/world-state/expression/memory
    tools (all of which persist to chats) are excluded; only image generation
    is offered, letting the model illustrate its own scenes. Generated images
    land in the story workspace and attach to the chapter.
    """
    return [t for t in AGENTIC_TOOLS if t.get("function", {}).get("name") == "generate_image"]


def has_tool_calls(assistant_output: dict[str, Any]) -> bool:
    """Check if an LLM output dict contains tool calls."""
    return bool(assistant_output.get("tool_calls"))


def get_agentic_depth(metadata: dict[str, Any] | None) -> int:
    """Read the current agentic loop depth from job metadata."""
    if not metadata:
        return 0
    return metadata.get("orchestrator_depth", 0)


def get_max_agentic_depth(chat_or_story=None, metadata: dict[str, Any] | None = None) -> int:
    """Resolve the max agentic depth: per-entity override > metadata > global default."""
    if chat_or_story is not None and getattr(chat_or_story, "max_agentic_depth", None) is not None:
        return int(chat_or_story.max_agentic_depth)
    if metadata and metadata.get("max_agentic_depth") is not None:
        return int(metadata["max_agentic_depth"])
    return MAX_AGENTIC_DEPTH


def budget_metadata_for(chat_or_story) -> dict[str, int]:
    """A member's costed-tool caps, as `{column: value}`, ready to stamp onto a job.

    One place, read from `TOOL_BUDGETS`, because these were being written out by
    hand at four sites — three chat routes and one story route — and a new
    costed tool would have needed all four to know. It did not: the image budget
    was added to the chat routes and the story route kept only the depth cap, so
    a story's autonomous illustration ran at the global default no matter what
    the panel said.

    Only columns that are actually SET are included. An absent column reads as
    the global default downstream, whereas an explicit `None` would be recorded
    as "deliberately unset" and shadow the default.
    """
    if chat_or_story is None:
        return {}
    stamped: dict[str, int] = {}
    for _name, (_counter, column, _default) in TOOL_BUDGETS.items():
        value = getattr(chat_or_story, column, None)
        if value is not None:
            stamped[column] = int(value)
    return stamped


def can_continue_agentic(metadata: dict[str, Any] | None, chat_or_story=None) -> bool:
    """Whether the orchestrator should process another iteration."""
    return get_agentic_depth(metadata) < get_max_agentic_depth(chat_or_story, metadata)


def _budget_for(tool_name: str) -> tuple[str, str, int]:
    """The `(counter key, column, default)` for a costed tool.

    An unknown tool name is a bug in the caller, and returning
    `("","",0)` rather than raising is deliberate: the gate that reads this runs
    on every hop of every agentic reply, and a KeyError there would take down a
    reply that had already been paid for.
    """
    return TOOL_BUDGETS.get(tool_name, ("", "", 0))


def get_tool_count(metadata: dict[str, Any] | None, tool_name: str) -> int:
    """How many times this exchange has already spent `tool_name`."""
    counter_key = _budget_for(tool_name)[0]
    if not counter_key or not metadata:
        return 0
    try:
        return int(metadata.get(counter_key) or 0)
    except (TypeError, ValueError):
        return 0


def get_tool_max(tool_name: str, chat_or_story=None, metadata: dict[str, Any] | None = None) -> int:
    """Resolve one tool's budget: per-entity override > metadata > global default.

    Same precedence as the depth cap, and deliberately the same shape, because
    the two answer different questions and should be tuned separately: depth is
    "how many more times should the model think", this is "how much am I willing
    to spend on one exchange".

    A stored 0 means "not at all" rather than "unset" — an explicit zero is how a
    user turns a tool off without also turning off the rest of the agentic loop,
    so `is None` is the unset test and not falsiness.
    """
    _counter, column, default = _budget_for(tool_name)
    for source in (chat_or_story, metadata or {}):
        value = (
            source.get(column) if isinstance(source, dict)
            else getattr(source, column, None)
        )
        if value is not None:
            return int(value)
    return default


def tool_budget_remaining(
    tool_name: str, metadata: dict[str, Any] | None, chat_or_story=None
) -> int:
    """How many more of `tool_name` this exchange may spend."""
    return max(
        0,
        get_tool_max(tool_name, chat_or_story, metadata)
        - get_tool_count(metadata, tool_name),
    )


# ── the image-specific names, kept as thin wrappers ─────────────────────────
#
# Their callers and tests are unchanged; adding a second costed tool should not
# have meant renaming half of them.

def get_agentic_image_count(metadata: dict[str, Any] | None) -> int:
    """How many images this exchange has already spent."""
    return get_tool_count(metadata, IMAGE_TOOL_NAME)


def get_max_agentic_images(chat_or_story=None, metadata: dict[str, Any] | None = None) -> int:
    """Resolve the image budget."""
    return get_tool_max(IMAGE_TOOL_NAME, chat_or_story, metadata)


def image_budget_remaining(metadata: dict[str, Any] | None, chat_or_story=None) -> int:
    """How many more images this exchange may spend."""
    return tool_budget_remaining(IMAGE_TOOL_NAME, metadata, chat_or_story)


def budget_exhausted_tool_result(tool_call_id: str, tool_name: str = IMAGE_TOOL_NAME) -> dict[str, Any]:
    """A tool result the model can read when a costed tool was refused.

    A dropped tool call with no result is an error to the model — it produces a
    malformed follow-up or loops asking again. This keeps the conversation
    well-formed and tells it why, so its final turn is a text reply instead of
    another request for the same thing.

    `tool_name` is on the result so the model can see WHICH budget it hit. With
    two costed tools, "you are out of budget" is ambiguous — it might otherwise
    conclude narration is unavailable and stop offering scene descriptions
    entirely, which is a worse outcome than the refusal.
    """
    if tool_name == IMAGE_TOOL_NAME:
        detail = (
            "This exchange has already used its image budget, so the image was "
            "not generated. Reply in text without calling generate_image again."
        )
    else:  # pragma: no cover - defensive; an unknown tool has no budget row
        detail = (
            f"This exchange has already used its budget for {tool_name}, so it "
            "was not run. Reply in text without calling it again."
        )
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": tool_name,
        "content": detail,
    }


async def execute_tool(
    tool_call: dict[str, Any],
    *,
    chat_id: str | None = None,
    character_id: str | None = None,
    story_id: str | None = None,
    chapter_id: str | None = None,
    source_job_id: str | None = None,
    branch_id: str | None = None,
) -> dict[str, Any]:
    """
    Execute a single tool call and return the result dict.

    A top-level ``asyncio.wait_for`` guard bounds the whole tool execution so a
    misbehaving tool whose internal call does not enforce its own timeout cannot
    hang the agentic loop indefinitely. Inner per-call timeouts are still kept;
    this is purely a safety net. On timeout a graceful error result is returned
    rather than crashing the loop.
    """
    function = tool_call.get("function", {})
    name = function.get("name", "")
    try:
        args = json.loads(function.get("arguments", "{}"))
    except (json.JSONDecodeError, TypeError):
        args = {}

    async def _run():
        if name == "generate_image":
            return await _tool_generate_image(
                args,
                chat_id=chat_id,
                character_id=character_id,
                story_id=story_id,
                chapter_id=chapter_id,
                source_job_id=source_job_id,
                branch_id=branch_id,
            )

        return {"status": "error", "error": f"Unknown tool: {name}"}

    try:
        return await asyncio.wait_for(_run(), timeout=TOOL_TIMEOUT)
    except asyncio.TimeoutError:
        logger.error(
            "execute_tool_timed_out",
            tool=name,
            chat_id=chat_id,
            source_job_id=source_job_id,
            timeout=TOOL_TIMEOUT,
        )
        return {
            "status": "error",
            "error": f"Tool '{name}' timed out after {TOOL_TIMEOUT}s",
        }


async def _tool_generate_image(
    args: dict[str, Any],
    *,
    chat_id: str | None = None,
    character_id: str | None = None,
    story_id: str | None = None,
    chapter_id: str | None = None,
    source_job_id: str | None = None,
    branch_id: str | None = None,
) -> dict[str, Any]:
    """Generate an image via the job pipeline, without waiting for it.

    Returns immediately with `status: "queued"`; the image lands on its own
    JOB_COMPLETED. See the comment at the return for why blocking here was
    worse than it looks.
    """
    from infrastructure.deps import get_session_context

    prompt = args.get("prompt", "a beautiful fantasy landscape")
    negative = args.get("negative_prompt", "worst quality, low quality, bad anatomy")

    logger.info("tool_generate_image", prompt=prompt[:80], chat_id=chat_id)

    async with get_session_context() as session:
        # 1. Start with system default checkpoint
        ckpt_name = None
        lora_name = None

        # 2. Override with frontend user setting if provided via the parent LLM job metadata
        if source_job_id:
            from core.entities import Job
            source_job = session.get(Job, source_job_id)
            if source_job and getattr(source_job, "metadata_", None):
                frontend_ckpt = source_job.metadata_.get("generator_checkpoint")
                if frontend_ckpt:
                    ckpt_name = frontend_ckpt

        # 3. Override with character's preferred models if set
        if character_id:
            from core.entities import Character
            char = session.get(Character, character_id)
            if char:
                if char.checkpoint:
                    ckpt_name = char.checkpoint
                if char.lora:
                    lora_name = char.lora
                if char.visual_tags:
                    tags = ", ".join(char.visual_tags)
                    prompt = f"{prompt}, {tags}" if prompt else tags

        # 3b. Enrich prompt with live Statekeeper outfit, expression, and location tags
        if chat_id:
            from core.entities import Chat, Location
            chat_row = session.get(Chat, chat_id)
            if chat_row:
                snap = chat_row.state_snapshot if isinstance(chat_row.state_snapshot, dict) else {}
                extra_visual_parts: list[str] = []
                outfit = str(snap.get("character_outfit") or "").strip()
                if outfit and outfit.lower() not in (prompt or "").lower():
                    extra_visual_parts.append(f"wearing {outfit}")
                expr = str(snap.get("character_expression") or "").strip()
                if expr and expr not in ("neutral", "none") and expr.lower() not in (prompt or "").lower():
                    extra_visual_parts.append(f"{expr} expression")
                if chat_row.location_id:
                    loc_row = session.get(Location, chat_row.location_id)
                    if loc_row and loc_row.tags:
                        loc_tags = ", ".join(loc_row.tags[:4])
                        if loc_tags and loc_tags.lower() not in (prompt or "").lower():
                            extra_visual_parts.append(loc_tags)
                elif chat_row.story_location:
                    loc_str = str(chat_row.story_location).strip()
                    if loc_str and loc_str.lower() not in (prompt or "").lower():
                        extra_visual_parts.append(f"in {loc_str}")
                if extra_visual_parts:
                    suffix = ", ".join(extra_visual_parts)
                    prompt = f"{prompt}, {suffix}" if prompt else suffix

        # 4. Ensure the chosen models are actually installed on an enabled provider
        availability = ModelAvailabilityService(session)
        resolved_ckpt = availability.get_available_checkpoint(ckpt_name)
        if not resolved_ckpt:
            logger.error(
                "tool_generate_image_no_checkpoint",
                preferred=ckpt_name,
            )
            return {
                "status": "error",
                "error": (
                    "No image checkpoints are installed on any provider. "
                    "Install a checkpoint before using the image generation tool."
                ),
            }
        if resolved_ckpt != (ckpt_name or ""):
            logger.warning("tool_generate_image_ckpt_fallback", preferred=ckpt_name, used=resolved_ckpt)
        resolved_lora = availability.get_available_lora(lora_name)
        if lora_name and resolved_lora is None:
            logger.warning("tool_generate_image_lora_unavailable", preferred=lora_name)

        is_story_tool = bool(story_id and chapter_id)

        # Shared submission helper (checkpoint re-resolution inside is
        # idempotent — resolved_ckpt is already confirmed available).
        from services.image_submission import submit_image_job

        try:
            job = await submit_image_job(
                session,
                prompt=prompt,
                negative_prompt=negative,
                checkpoint=resolved_ckpt,
                lora=resolved_lora,
                filename_prefix="StoryAgenticGen" if is_story_tool else "AgenticGen",
                source="agentic_tool",
                workspace="story" if is_story_tool else "chat",
                chat_id=None if is_story_tool else chat_id,
                character_id=None if is_story_tool else character_id,
                story_id=story_id if is_story_tool else None,
                chapter_id=chapter_id if is_story_tool else None,
                parent_job_id=source_job_id,
                # The thread the reply that called the tool lives on. Without it
                # an agentic image from a forked branch is filed into the
                # original thread, where the user reading the fork never sees it.
                branch_id=None if is_story_tool else branch_id,
                # The prompt travels with the job, because that is what the
                # IMAGE message is built from: without it `_handle_chat_image`
                # has nothing to say about what the image depicts and stores the
                # literal string "[Image generated by generate_image]" instead.
                extra_metadata={
                    "tool_name": "generate_image",
                    "image_context": args.get("prompt", ""),
                },
            )
        except Exception as e:
            logger.error("tool_generate_image_failed", error=str(e))
            return {"status": "error", "error": str(e)}

    # Submit, do not wait.
    #
    # This tool used to `await wait_for_job_completion(job.id, timeout=330.0)` —
    # blocking the single LLM worker for up to five and a half minutes inside
    # one tool call. Because the reply `Message` is only written once the parent
    # job's JOB_COMPLETED arrives, and the parent cannot finalise until every
    # chained hop is enqueued, a user who typed one line was waiting on an image
    # they never asked for. The reply was not in the database yet either, so a
    # reload in that window lost a paid generation.
    #
    # The image does not need waiting for. It lands on its own JOB_COMPLETED,
    # where `world_integration_service._handle_chat_image` appends an IMAGE
    # message to this same chat — that path already exists and already
    # special-cases `source == "agentic_tool"`. So the tool returns immediately,
    # the follow-up LLM hop runs at once, the reply is persisted, and the image
    # appears beside it whenever it finishes.
    return {
        "status": "queued",
        "job_id": job.id,
        "prompt_used": prompt,
        "note": (
            "Image generation started in the background and will appear in the "
            "conversation when it finishes. Do not claim it exists yet."
        ),
    }


async def process_tool_calls_and_chain(
    *,
    job,
    assistant_output: dict[str, Any],
    final_result: dict[str, Any],
    chat_id: str | None,
    character_id: str | None,
    job_service,
    enqueue_fn,
    allowed_tools: set[str] | None = None,
    story_id: str | None = None,
    chapter_id: str | None = None,
) -> bool:
    """
    Detect tool_calls in an LLM response and chain follow-up jobs.

    When ``story_id`` is provided the follow-up is a story continuation
    (workspace "story") instead of a chat reply; only story-safe tools
    (image generation) are re-attached.

    Returns True if a follow-up job was enqueued (caller should NOT finalize).
    Returns False if there are no tool_calls (caller should finalize normally).
    """
    tool_calls = assistant_output.get("tool_calls", [])
    if not tool_calls:
        return False

    if allowed_tools:
        filtered = []
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            if name in allowed_tools:
                filtered.append(tc)
        if not filtered:
            logger.info("agentic_tools_all_filtered", job_id=job.id)
            return False
        tool_calls = filtered

    metadata = job.metadata_ or {}
    depth = get_agentic_depth(metadata)
    max_depth = get_max_agentic_depth(metadata=metadata)
    if not can_continue_agentic(metadata):
        logger.warning(
            "agentic_depth_exceeded",
            job_id=job.id,
            depth=depth,
            max=max_depth,
        )
        return False

    # Image budget, applied before any of them are spent. The depth cap bounds
    # hops, not cost, so without this a single reply could chain up to
    # `max_depth` paid image jobs. Counted across the whole exchange, carried in
    # the chained job's metadata, so five separate replies asking for one image
    # each are unaffected while one reply asking for five images is not.
    # Remaining budget per costed tool, resolved once before anything is spent.
    #
    # Each tool has its OWN budget, so a chat that asks for four images and one
    # narration gets four images and one narration — they are different columns
    # answering different questions, and one shared pool would mean raising the
    # image cap silently lowered the narration cap.
    remaining = {
        name: tool_budget_remaining(name, metadata)
        for name in TOOL_BUDGETS
    }

    granted: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    for tc in tool_calls:
        name = tc.get("function", {}).get("name")
        if name in remaining:
            already_spent = sum(
                1 for g in granted if g.get("function", {}).get("name") == name
            )
            if already_spent >= remaining[name]:
                refused.append(tc)
                continue
        granted.append(tc)

    refused_by_tool: dict[str, int] = {}
    for tc in refused:
        name = tc.get("function", {}).get("name", "?")
        refused_by_tool[name] = refused_by_tool.get(name, 0) + 1

    for name, count in refused_by_tool.items():
        logger.warning(
            "agentic_tool_budget_exhausted",
            job_id=job.id,
            depth=depth,
            tool=name,
            remaining=remaining.get(name, 0),
            refused=count,
            budget=get_tool_max(name, metadata=metadata),
        )

    # One result per refused call, naming the tool, so the model can tell which
    # budget it hit rather than concluding narration is unavailable entirely.
    tool_results = [
        budget_exhausted_tool_result(tc.get("id", ""), tc.get("function", {}).get("name"))
        for tc in refused
    ]
    for tc in granted:
        result = await execute_tool(
            tc,
            chat_id=chat_id,
            character_id=character_id,
            story_id=story_id,
            chapter_id=chapter_id,
            source_job_id=job.id,
            # Carried from the parent job so a tool-spawned image is filed on the
            # same thread as the reply that asked for it.
            branch_id=metadata.get("branch_id"),
        )
        tool_results.append({
            "role": "tool",
            "tool_call_id": tc.get("id", ""),
            "name": tc.get("function", {}).get("name", ""),
            "content": json.dumps(result),
        })

    spent_by_tool = {
        name: sum(
            1 for tc in granted if tc.get("function", {}).get("name") == name
        )
        for name in TOOL_BUDGETS
    }

    original_messages = metadata.get("original_messages", [])
    context = list(original_messages) if original_messages else []
    if not context:
        wf = job.workflow if isinstance(job.workflow, dict) else {}
        context = wf.get("messages", [])

    context.append(assistant_output)
    context.extend(tool_results)

    from services.llm_workflow import SAMPLER_KEYS, build_llm_workflow

    prev_workflow = job.workflow if isinstance(job.workflow, dict) else {}
    followup_model = prev_workflow.get("model")
    # Carry the original job's sampling overrides through every chained hop.
    followup_samplers = {k: prev_workflow[k] for k in SAMPLER_KEYS if prev_workflow.get(k) is not None}

    is_story_chain = bool(story_id)
    followup_workflow, followup_metadata = build_llm_workflow(
        messages=context,
        type_="story_continue" if is_story_chain else "chat_reply",
        chat_id=None if is_story_chain else chat_id,
        story_id=story_id or None,
        chapter_id=chapter_id,
        character_id=character_id,
        character_system_prompt=metadata.get("character_system_prompt"),
        model=followup_model,
        workspace="story" if is_story_chain else "chat",
        parent_job_id=job.id,
        samplers=followup_samplers or None,
        extra_metadata={
            "agentic": True,
            "orchestrator_depth": depth + 1,
            "original_messages": context,
            "max_agentic_depth": metadata.get("max_agentic_depth"),
            # The running total per costed tool, not the count this hop spent, so
            # each budget is per exchange rather than per hop. Dropping the carry
            # would make the cap "one image per hop" — four more images than the
            # user asked for — and the same is true of narration, which is why
            # this is built from the table rather than written out per tool.
            **{
                counter: get_tool_count(metadata, name)
                + spent_by_tool.get(name, 0)
                for name, (counter, _column, _default) in TOOL_BUDGETS.items()
            },
            # The caps travel with the totals. Without them the second hop falls
            # back to the global default, so a chat that set its own budget is
            # capped by the default from hop two onward.
            **{
                column: metadata.get(column)
                for name, (_counter, column, _default) in TOOL_BUDGETS.items()
            },
            # Every hop of the chain writes its reply onto the thread the
            # question was asked on. `metadata` is the PARENT job's, so the
            # branch is inherited rather than re-derived — a chained reply that
            # dropped it would land in the original thread and leave the fork
            # the user is reading stuck mid-exchange.
            "branch_id": metadata.get("branch_id"),
        },
    )
    tool_pool = story_agentic_tools() if is_story_chain else AGENTIC_TOOLS
    if allowed_tools is not None:
        followup_workflow["tools"] = [
            t
            for t in tool_pool
            if t.get("function", {}).get("name") in allowed_tools
        ]
    else:
        # No explicit allow-list was provided.  This branch is only hit
        # when the caller (job_processing.py) omits allowed_tools —
        # normally the parent job's already-filtered tool list is passed
        # through, so this is just a safe fallback to the full tool set.
        followup_workflow["tools"] = tool_pool

    try:
        followup_job = await job_service.create_job(
            task_type="llm",
            workflow=followup_workflow,
            metadata=followup_metadata,
        )
        if enqueue_fn is not None:
            await enqueue_fn(followup_job.id)
        else:
            from services.job_queue import queue_manager
            await queue_manager.enqueue(followup_job.id, task_type="llm")
        logger.info(
            "agentic_followup_enqueued",
            parent_job_id=job.id,
            followup_job_id=followup_job.id,
            depth=depth + 1,
            tool_count=len(tool_calls),
        )
        return True
    except Exception as e:
        logger.error("agentic_followup_failed", error=str(e))
        return False
