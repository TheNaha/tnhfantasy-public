"""The 6-stage roleplay chat pipeline, as an authoritative manifest.

This module is the single source of truth for the chat architecture:
  1. Triage (Laya System 1): Routes to appropriate agent/variant, evaluates
     pacing, and executes Fate & Skill Anti-Godmoding check.
  2. Act (Actor Agent): Generation by Character, Narrator, or Custom Agent with
     tailored system prompt, variant, and directive.
  3. Audit (Laya System 1): Evaluates completion and audits 16 fine-grained
     narrative state gates (mood, tone, gear, clock, etc.).
  4. Update (Statekeeper / Updater): Extracts JSON state deltas restricted strictly
     to the gates that fired (including character_expression under gate_character_mood).
  5. Illustrate (Illustrator Agent): Formulates ComfyUI visual prompts if visual
     threshold crossed.
  6. Chain (Laya System 1): Multi-turn conductor deciding next speaker (up to 4
     autonomous turns) or yielding back to the user.

It used to be a *description* of a pipeline that lived somewhere else. The
stage metadata was served to the LLM Studio UI, and the execution was hardcoded
in `services/job_processing.py` — nothing read this file, so the two could
disagree, and the limits did: the manifest quoted `max_autonomous_turns: 4`,
the `Chat.max_autonomous_turns` column defaulted to 4, the executor hardcoded
`continuation_count < 4`, and `UPDATER_GATE_THRESHOLD` was a fourth copy. Four
places, one fact, changed by hand together.

It is now authoritative. Each stage names the function that performs it, the
`next_stages` tuple declares the ORDER the stages run in, and every limit is
read from `core.pipeline_limits` — the leaf module the code itself imports.
`services/pipeline_runner.py` walks the graph; nothing walks it by hand.

The graph is not a tree. Two things make it awkward, and both are real:

  - The continuation is a branch OUT of the audit, not a sibling of it. A
    truncated reply is continued and the turn ends there; the illustrate,
    update and chain stages do not run. So the continuation is part of the
    audit executor, which is also what the audit's own description says.
  - The chain normally runs AFTER the update, but not in the same call. When
    the Statekeeper ran, the chain is deferred to the updater job's completion
    hook, because the chain's decision depends on the state the Statekeeper
    was about to write and reading the pre-update snapshot would be a stale
    read. The `update -> chain` edge below is that handoff.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from core.pipeline_limits import (
    IMAGE_TRIGGER_THRESHOLD,
    MAX_AGENTIC_IMAGES,
    MAX_AUTONOMOUS_TURNS,
    MAX_CONTINUATIONS,
    UPDATER_GATE_THRESHOLD,
)


@dataclass(frozen=True)
class PipelineStage:
    id: str
    name: str
    owner: str  # "laya" | "actor" | "updater" | "illustrator" | "user"
    description: str
    target_role: str  # "director" | "rp" | "util" | "client"
    input_type: str
    output_type: str
    limits: Dict[str, Any] = field(default_factory=dict)
    next_stages: tuple[str, ...] = ()
    # Dotted path to the function that performs this stage, resolved lazily at
    # call time so the manifest can name a function without importing its
    # module (and without the import cycle that would create). Empty for the
    # stages that ARE a job rather than a function — `act` is the generation
    # itself, and `update` is a job the executor enqueues.
    executor: str = ""
    # "inline" runs in the caller's turn. "job" is a job of its own, enqueued
    # by its executor and finalised separately.
    runs_as: str = "inline"


PIPELINE_STAGES: tuple[PipelineStage, ...] = (
    PipelineStage(
        id="triage",
        name="Stage 1: Pre-Generation Triage & Fate Check",
        owner="laya",
        description="Analyzes the user message and scene context to select the best agent, situational sub-variant, pacing speed/directive, and runs the Fate & Skill check.",
        target_role="director",
        input_type="transcript_and_context",
        output_type="triage_decision",
        limits={"timeout_ms": 15000},
        next_stages=("act",),
        executor="services.pipeline_stages:triage_stage",
    ),
    PipelineStage(
        id="act",
        name="Stage 2: Actor Persona Generation",
        owner="actor",
        description="Executes the active agent persona (Character, Narrator, or Custom Agent) with tailored prompt variant and pacing/fate directive.",
        target_role="rp",
        input_type="assembled_context",
        output_type="assistant_text",
        limits={"max_output_tokens": 1200},
        next_stages=("audit",),
        # The generation IS this stage. There is no function to call: the
        # route builds the workflow and the job queue runs it.
        executor="",
        runs_as="job",
    ),
    PipelineStage(
        id="audit",
        name="Stage 3: Post-Generation Audit & Gating",
        owner="laya",
        description="Audits the generated response for completion (triggering seamless continuation if cut off) and evaluates the 16 Statekeeper gates.",
        target_role="director",
        input_type="generated_text_and_snapshot",
        output_type="audit_decision",
        limits={
            "max_continuations": MAX_CONTINUATIONS,
            "timeout_ms": 15000,
            "gate_threshold": UPDATER_GATE_THRESHOLD,
        },
        next_stages=("illustrate", "update", "chain", "user"),
        executor="services.pipeline_stages:audit_stage",
    ),
    PipelineStage(
        id="update",
        name="Stage 4: Statekeeper World Vault Sync",
        owner="updater",
        description="Extracts factual state updates (inventory, clock, mood, avatar expression, relationships) strictly restricted to the gates that fired.",
        target_role="util",
        input_type="gated_schema_and_dialogue",
        output_type="state_deltas_json",
        limits={"max_output_tokens": 600},
        next_stages=("chain", "user"),
        executor="services.pipeline_stages:update_stage",
        runs_as="job",
    ),
    PipelineStage(
        id="illustrate",
        name="Stage 5: Autonomous Scene Illustration",
        owner="illustrator",
        description="Dispatches the Illustrator agent to synthesize scene facts into a ComfyUI visual prompt when a visual beat warrants an illustration.",
        target_role="util",
        input_type="scene_facts",
        output_type="comfyui_prompt",
        limits={"max_agentic_images": MAX_AGENTIC_IMAGES},
        next_stages=(),
        executor="services.pipeline_stages:illustrate_stage",
        runs_as="job",
    ),
    PipelineStage(
        id="chain",
        name="Stage 6: Multi-Turn Autonomous Chaining",
        owner="laya",
        description="Evaluates whether narrative momentum demands another autonomous turn (up to 4 turns) before yielding control back to the user.",
        target_role="director",
        input_type="updated_snapshot_and_history",
        output_type="chaining_decision",
        limits={"max_autonomous_turns": MAX_AUTONOMOUS_TURNS},
        next_stages=("triage", "user"),
        executor="services.pipeline_stages:chain_stage",
    ),
)


def get_pipeline_manifest() -> Dict[str, Any]:
    """Return serializable pipeline structure for LLM Studio visualization.

    The limits come from `core.pipeline_limits`, which the code also imports,
    so this manifest cannot quote a number the pipeline does not enforce.
    """
    return {
        "version": "2.0.0",
        "description": "Laya System 1 Multi-Agent Gated Chat Pipeline",
        "limits": {
            "max_autonomous_turns": MAX_AUTONOMOUS_TURNS,
            "max_turns": MAX_AUTONOMOUS_TURNS,
            "max_continuations": MAX_CONTINUATIONS,
            "max_agentic_images": MAX_AGENTIC_IMAGES,
            "gate_threshold": UPDATER_GATE_THRESHOLD,
            "image_threshold": IMAGE_TRIGGER_THRESHOLD,
        },
        "stages": [
            {
                "id": s.id,
                "name": s.name,
                "owner": s.owner,
                "description": s.description,
                "target_role": s.target_role,
                "input_type": s.input_type,
                "output_type": s.output_type,
                "limits": s.limits,
                "next_stages": list(s.next_stages),
                "runs_as": s.runs_as,
            }
            for s in PIPELINE_STAGES
        ],
    }
