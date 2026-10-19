"""Declarative chat workflow pipeline definition and stage metadata.

This module is the canonical single source of truth for the 6-stage roleplay chat
architecture:
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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


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
    ),
    PipelineStage(
        id="audit",
        name="Stage 3: Post-Generation Audit & Gating",
        owner="laya",
        description="Audits the generated response for completion (triggering seamless continuation if cut off) and evaluates the 16 Statekeeper gates.",
        target_role="director",
        input_type="generated_text_and_snapshot",
        output_type="audit_decision",
        limits={"max_continuations": 4, "timeout_ms": 15000},
        next_stages=("act", "update", "illustrate", "chain", "user"),
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
    ),
    PipelineStage(
        id="illustrate",
        name="Stage 5: Autonomous Scene Illustration",
        owner="illustrator",
        description="Dispatches the Illustrator agent to synthesize scene facts into a ComfyUI visual prompt when a visual beat warrants an illustration.",
        target_role="util",
        input_type="scene_facts",
        output_type="comfyui_prompt",
        limits={"max_agentic_images": 2},
        next_stages=(),
    ),
    PipelineStage(
        id="chain",
        name="Stage 6: Multi-Turn Autonomous Chaining",
        owner="laya",
        description="Evaluates whether narrative momentum demands another autonomous turn (up to 4 turns) before yielding control back to the user.",
        target_role="director",
        input_type="updated_snapshot_and_history",
        output_type="chaining_decision",
        limits={"max_autonomous_turns": 4},
        next_stages=("triage", "user"),
    ),
)


def get_pipeline_manifest() -> Dict[str, Any]:
    """Return serializable pipeline structure for LLM Studio visualization."""
    return {
        "version": "2.0.0",
        "description": "Laya System 1 Multi-Agent Gated Chat Pipeline",
        "limits": {
            "max_autonomous_turns": 4,
            "max_turns": 4,
            "max_continuations": 4,
            "max_agentic_images": 2,
            "gate_threshold": 0.55,
            "image_threshold": 0.65,
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
            }
            for s in PIPELINE_STAGES
        ],
    }
