"""Walks the roleplay chat pipeline as the manifest declares it.

The manifest in `services/chat_pipeline.py` names the function that performs
each stage, the order the stages run in, and the limits each one enforces.
This module is the thing that reads it and runs it.

Executors are resolved by dotted path at CALL time, not at import time. That
is what lets the manifest name a function in a module that imports the
manifest's own dependencies without an import cycle: `services.pipeline_stages`
calls into `services.decision_service`, `services.context_builder` and
`services.job_queue`, and none of them know about the runner.

The stage context is a plain dict, shared by reference across the stages of one
turn. It carries the things the stages need (session, job, chat, transcript)
and the things they learn (the audit decision, the updater job id). Two keys
have meaning to the runner itself:

  `halt`      — set by a stage that ends the turn. The walk stops.
  `updater_job_id` — set by the update stage. The chain stage reads it and
                declines to run, because when the Statekeeper ran, the chain
                is deferred to the updater job's completion hook so that its
                decision reads the state the Statekeeper just wrote.
"""

from __future__ import annotations

import importlib
from typing import Any, Awaitable, Callable

from services.chat_pipeline import PIPELINE_STAGES, PipelineStage

_STAGES_BY_ID: dict[str, PipelineStage] = {s.id: s for s in PIPELINE_STAGES}

# The stage id that means "hand control back to the user". It is not a stage
# and has no executor; the walk stops when it reaches it.
USER_STAGE = "user"


def stage(key: str) -> PipelineStage:
    """Look up a stage by id."""
    try:
        return _STAGES_BY_ID[key]
    except KeyError:
        raise KeyError(f"unknown pipeline stage {key!r}") from None


def limit(key: str, name: str, default: Any = None) -> Any:
    """Read a limit from a stage, falling back to `default`."""
    limits = stage(key).limits
    if name in limits:
        return limits[name]
    return default


def resolve_executor(key: str) -> Callable[[dict[str, Any]], Awaitable[Any]] | None:
    """Resolve a stage's executor function, or None for a stage that has none."""
    executor = stage(key).executor
    if not executor:
        return None
    module_path, _, attribute = executor.partition(":")
    if not module_path or not attribute:
        raise ValueError(f"malformed executor path {executor!r} for stage {key!r}")
    module = importlib.import_module(module_path)
    return getattr(module, attribute)


async def run_stage(key: str, ctx: dict[str, Any]) -> Any:
    """Run one stage and record its result in the context."""
    executor = resolve_executor(key)
    if executor is None:
        return None
    result = await executor(ctx)
    ctx[f"result:{key}"] = result
    return result


async def run_from(start_key: str, ctx: dict[str, Any]) -> dict[str, Any]:
    """Run `start_key` and then the stages that follow it, in manifest order.

    The walk is one level deep, not a recursive graph traversal, because the
    pipeline is a pipeline: `audit` declares what comes after it, and that is
    what runs. The `update -> chain` edge is not walked from `audit` — the
    chain runs after update in the same walk, and the chain executor defers
    itself when the Statekeeper ran.

    Returns the context, so the caller can read what the stages produced
    (`ctx["audit_decision"]`, `ctx["updater_job_id"]`).
    """
    await run_stage(start_key, ctx)
    if ctx.get("halt"):
        return ctx

    for next_key in stage(start_key).next_stages:
        if ctx.get("halt"):
            break
        if next_key == USER_STAGE:
            break
        await run_stage(next_key, ctx)
    return ctx
