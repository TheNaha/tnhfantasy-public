"""Expanded 13-question System 1 Decision Schema for the Roleplay Director.

Evaluates turn routing, narrative pacing, visual illustration triggers, and
5 boolean Statekeeper (Updater) gates in a single parallel pass (~150ms on CPU).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

UPDATER_GATE_THRESHOLD = 0.55

UPDATER_GATE_KEYS = (
    "gate_world_state",
    "gate_character_state",
    "gate_inventory_or_items",
    "gate_durable_memory",
    "gate_lore_discovery",
)


@dataclass
class DirectorDecisionResult:
    """Structured result from the 13-question Director pass."""

    # Category A: Turn Routing & Multi-Agent Chaining
    next_speaker: str = "character"
    next_speaker_probabilities: Dict[str, float] = field(default_factory=dict)
    continue_chain_probability: float = 0.2

    # Category B: Narrative Direction & Pacing
    pacing_directive: str = "continue_conversation"
    pacing_directive_probabilities: Dict[str, float] = field(default_factory=dict)
    scene_tension: float = 2.0
    pacing_speed: float = 2.0
    emotional_tone: str = "warm_intimate"

    # Category C: Visual & Expression Triggers
    trigger_image_probability: float = 0.15
    should_trigger_image: bool = False
    image_focus: str = "character_portrait"
    character_expression: str = "neutral"

    # Category D: Statekeeper (Updater) Gates
    updater_gates: Dict[str, float] = field(default_factory=dict)
    triggered_gates: List[str] = field(default_factory=list)
    should_run_updater: bool = False

    # Telemetry
    engine_used: str = "heuristic"
    model_id: str = "heuristic"
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        t_int = max(1, min(5, round(self.scene_tension)))
        tension_labels = {1: "calm", 2: "warm", 3: "rising", 4: "high", 5: "climactic"}
        s_int = max(1, min(3, round(self.pacing_speed)))
        speed_labels = {1: "slow-motion", 2: "real-time", 3: "fast-forward"}
        data["provider_tier"] = self.engine_used
        data["scene_tension_label"] = tension_labels.get(t_int, "normal")
        data["pacing_speed_label"] = speed_labels.get(s_int, "real-time")
        data["continue_chain_prob"] = self.continue_chain_probability
        data["trigger_image_prob"] = self.trigger_image_probability
        data["director_instruction"] = (
            f"Pacing: {self.pacing_directive} ({speed_labels.get(s_int, 'real-time')}) | "
            f"Tension: {self.scene_tension}/5 ({tension_labels.get(t_int, 'normal')}) | "
            f"Tone: {self.emotional_tone} | Expression: {self.character_expression}"
        )
        return data


def build_director_questions(
    *,
    has_secondary_character: bool = False,
    allow_narration: bool = True,
) -> List[Dict[str, Any]]:
    """Return the 13 typed System 1 questions for Laya / `/v1/decisions`."""
    speaker_options: Dict[str, str] = {
        "character": "The primary character should speak or react directly in dialogue and action.",
    }
    if allow_narration:
        speaker_options["narrator"] = (
            "The omniscient scene narrator should describe the environment, atmosphere, sensory details, or passage of time."
        )
    if has_secondary_character:
        speaker_options["secondary_character"] = (
            "A secondary companion or NPC present in the scene should interject or respond."
        )
    speaker_options["user"] = (
        "The scene beat is complete and it is now the player's turn to respond."
    )

    return [
        # --- Category A: Turn Routing & Multi-Agent Chaining ---
        {
            "key": "next_speaker",
            "type": "choice",
            "question": "Who should take the very next turn in this roleplay scene?",
            "options": speaker_options,
        },
        {
            "key": "continue_chain",
            "type": "noul",
            "statement": (
                "After the next speaker finishes their turn, another AI agent (narrator or character) "
                "should immediately follow up before yielding control back to the player."
            ),
        },
        # --- Category B: Narrative Direction & Pacing ---
        {
            "key": "pacing_directive",
            "type": "choice",
            "question": "What narrative pacing direction should guide the next response?",
            "options": {
                "continue_conversation": "Continue the current dialogue and interaction naturally.",
                "sensory_detail": "Slow down and emphasize rich sensory, physical, and atmospheric detail.",
                "escalate_tension": "Escalate dramatic tension, stakes, conflict, or emotional intensity.",
                "advance_time_or_scene": "Advance the scene forward in time or transition to the next beat.",
                "de_escalate_reflect": "Slow the pace down for emotional reflection, comfort, or aftermath.",
            },
        },
        {
            "key": "scene_tension",
            "type": "score",
            "question": "What is the current level of dramatic, emotional, or physical tension in the scene?",
            "rubric": {
                1: "Calm, relaxed, everyday conversation with no conflict.",
                2: "Mild curiosity, playful banter, or light emotional warmth.",
                3: "Noticeable emotional stakes, romantic tension, or growing suspense.",
                4: "High drama, urgent conflict, intense intimacy, or danger.",
                5: "Climactic confrontation, life-or-death stakes, or overwhelming passion.",
            },
        },
        {
            "key": "pacing_speed",
            "type": "score",
            "question": "How fast should narrative time flow in the next turn?",
            "rubric": {
                1: "Slow-motion: focus on split-second micro-expressions, breathing, and immediate sensations.",
                2: "Real-time: standard conversational and action pacing.",
                3: "Fast-forward: summarize transitional actions and move briskly to the next key moment.",
            },
        },
        {
            "key": "emotional_tone",
            "type": "choice",
            "question": "What is the dominant emotional tone of the current scene?",
            "options": {
                "warm_intimate": "Warm, affectionate, intimate, or tender.",
                "playful_humorous": "Playful, teasing, lighthearted, or comedic.",
                "mysterious_tense": "Mysterious, suspenseful, guarded, or uneasy.",
                "dramatic_conflict": "Confrontational, angry, urgent, or high-stakes.",
                "melancholic_somber": "Sad, reflective, bittersweet, or vulnerable.",
            },
        },
        # --- Category C: Visual & Expression Triggers ---
        {
            "key": "trigger_image",
            "type": "noul",
            "statement": (
                "This moment features a striking visual change, new location, dramatic pose, "
                "or key emotional beat that warrants generating a scene illustration."
            ),
        },
        {
            "key": "image_focus",
            "type": "choice",
            "question": "If an illustration is generated right now, what should the camera focus on?",
            "options": {
                "character_portrait": "Close-up portrait focusing on the character's face, expression, and upper body.",
                "action_pose": "Dynamic medium or full-body shot capturing physical action, posture, and attire.",
                "environment_wide": "Wide cinematic establishing shot showcasing the location, lighting, and atmosphere.",
                "intimate_closeup": "Intimate close-up highlighting proximity, touch, or emotional connection.",
            },
        },
        {
            "key": "character_expression",
            "type": "choice",
            "question": "Which facial expression best matches the primary character's current emotional state?",
            "options": {
                "neutral": "Calm, composed, neutral expression.",
                "happy": "Smiling, cheerful, warm, or delighted.",
                "blushing": "Flustered, shy, affectionate, or aroused.",
                "sad": "Downcast, tearful, hurt, or melancholic.",
                "angry": "Fierce, scowling, annoyed, or defiant.",
                "surprised": "Wide-eyed, startled, or taken aback.",
                "seductive": "Alluring, confident, half-lidded, or inviting.",
            },
        },
        # --- Category D: Statekeeper (Updater) Gates ---
        {
            "key": "gate_world_state",
            "type": "noul",
            "statement": "The location, setting, time of day, or weather changed during this exchange.",
        },
        {
            "key": "gate_character_state",
            "type": "noul",
            "statement": (
                "A character's mood, physical condition, clothing/outfit, current activity, "
                "or relationship dynamic shifted during this exchange."
            ),
        },
        {
            "key": "gate_inventory_or_items",
            "type": "noul",
            "statement": "An item, weapon, gift, clue, or piece of equipment was acquired, used, lost, or exchanged.",
        },
        {
            "key": "gate_durable_memory",
            "type": "noul",
            "statement": (
                "A significant personal fact, promise, secret, backstory detail, or memorable event "
                "occurred that should be saved to long-term memory."
            ),
        },
        {
            "key": "gate_lore_discovery",
            "type": "noul",
            "statement": (
                "A new named location, faction, artifact, or world-building rule was introduced "
                "that belongs in the World Vault lorebook."
            ),
        },
    ]


def format_director_context(
    *,
    character_name: str,
    user_name: str = "User",
    story_location: Optional[str] = None,
    story_time: Optional[str] = None,
    state_snapshot: Optional[Dict[str, Any]] = None,
    recent_messages: Optional[List[Dict[str, str]]] = None,
    last_speaker: str = "user",
) -> str:
    """Build a compact context string for the System 1 Director (~500-900 tokens)."""
    lines: List[str] = [
        "=== SCENE OVERVIEW ===",
        f"Primary Character: {character_name}",
        f"Player / User: {user_name}",
        f"Current Location: {story_location or 'Unspecified'}",
        f"Current Time: {story_time or 'Unspecified'}",
        f"Last Turn Completed By: {last_speaker}",
    ]

    snap = state_snapshot or {}
    if snap:
        lines.append("\n=== CURRENT STATE SNAPSHOT ===")
        for label, key in (
            ("Character Mood", "character_mood"),
            ("Current Activity", "current_activity"),
            ("Character Outfit", "character_outfit"),
            ("Relationship Status", "relationship_status"),
            ("Scene Summary", "scene_summary"),
        ):
            val = snap.get(key)
            if val:
                lines.append(f"{label}: {val}")
        inv = snap.get("inventory")
        if isinstance(inv, list) and inv:
            lines.append(f"Notable Inventory/Items: {', '.join(str(x) for x in inv)}")

    if recent_messages:
        lines.append("\n=== RECENT TRANSCRIPT ===")
        for msg in recent_messages[-6:]:
            role = msg.get("role", "user")
            speaker = msg.get("speaker") or (
                user_name if role == "user" else (character_name if role == "char" else "Narrator")
            )
            content = (msg.get("content") or "").strip()
            if len(content) > 600:
                content = content[:597] + "..."
            lines.append(f"[{speaker}]: {content}")

    return "\n".join(lines)


def parse_director_result(
    raw_answers: Dict[str, Any],
    *,
    engine_used: str = "system1_laya",
    model_id: str = "laya_multilingual",
    latency_ms: float = 0.0,
    allow_image_generation: bool = True,
) -> DirectorDecisionResult:
    """Normalize raw output from Laya / `/v1/decisions` into `DirectorDecisionResult`."""

    def _choice(key: str, default: str) -> tuple[str, Dict[str, float]]:
        entry = raw_answers.get(key)
        if isinstance(entry, dict):
            selected = str(entry.get("choice") or entry.get("selected") or default)
            probs = entry.get("probabilities") or {}
            clean_probs = {str(k): round(float(v), 4) for k, v in probs.items() if isinstance(v, (int, float))}
            return selected, clean_probs
        if isinstance(entry, str) and entry:
            return entry, {entry: 1.0}
        return default, {default: 1.0}

    def _score(key: str, default: float, low: float, high: float) -> float:
        entry = raw_answers.get(key)
        val = default
        if isinstance(entry, dict):
            raw_val = entry.get("score", entry.get("expected", default))
            try:
                val = float(raw_val)
            except (TypeError, ValueError):
                val = default
        elif isinstance(entry, (int, float)):
            val = float(entry)
        return round(max(low, min(high, val)), 2)

    def _noul(key: str, default: float = 0.0) -> float:
        entry = raw_answers.get(key)
        val = default
        if isinstance(entry, dict):
            raw_val = entry.get("probability", entry.get("true_probability", entry.get("yes", default)))
            try:
                val = float(raw_val)
            except (TypeError, ValueError):
                val = default
        elif isinstance(entry, (int, float)):
            val = float(entry)
        elif isinstance(entry, bool):
            val = 0.85 if entry else 0.15
        return round(max(0.0, min(1.0, val)), 4)

    next_speaker, next_speaker_probs = _choice("next_speaker", "character")
    continue_chain_prob = _noul("continue_chain", 0.2)
    pacing_directive, pacing_probs = _choice("pacing_directive", "continue_conversation")
    scene_tension = _score("scene_tension", 2.0, 1.0, 5.0)
    pacing_speed = _score("pacing_speed", 2.0, 1.0, 3.0)
    emotional_tone, _ = _choice("emotional_tone", "warm_intimate")

    trigger_img_prob = _noul("trigger_image", 0.15)
    image_focus, _ = _choice("image_focus", "character_portrait")
    char_expr, _ = _choice("character_expression", "neutral")

    updater_gates: Dict[str, float] = {}
    triggered_gates: List[str] = []
    for gate_key in UPDATER_GATE_KEYS:
        prob = _noul(gate_key, 0.2)
        updater_gates[gate_key] = prob
        if prob >= UPDATER_GATE_THRESHOLD:
            triggered_gates.append(gate_key)

    return DirectorDecisionResult(
        next_speaker=next_speaker,
        next_speaker_probabilities=next_speaker_probs,
        continue_chain_probability=continue_chain_prob,
        pacing_directive=pacing_directive,
        pacing_directive_probabilities=pacing_probs,
        scene_tension=scene_tension,
        pacing_speed=pacing_speed,
        emotional_tone=emotional_tone,
        trigger_image_probability=trigger_img_prob,
        should_trigger_image=bool(allow_image_generation and trigger_img_prob >= 0.65),
        image_focus=image_focus,
        character_expression=char_expr,
        updater_gates=updater_gates,
        triggered_gates=triggered_gates,
        should_run_updater=len(triggered_gates) > 0,
        engine_used=engine_used,
        model_id=model_id,
        latency_ms=round(latency_ms, 1),
    )


def build_generative_fallback_prompt(
    context_text: str,
    *,
    has_secondary_character: bool = False,
    allow_narration: bool = True,
) -> str:
    """Build a compact JSON-only prompt for Tier 3 (`same_as_util`) generative fallback."""
    speakers = ["character", "user"]
    if allow_narration:
        speakers.insert(1, "narrator")
    if has_secondary_character:
        speakers.insert(-1, "secondary_character")

    return (
        "You are the System 1 Roleplay Director. Analyze the scene context below and respond with "
        "ONLY a valid JSON object matching this exact schema (no markdown fences, no commentary):\n"
        "{\n"
        f'  "next_speaker": one of {json.dumps(speakers)},\n'
        '  "continue_chain": float 0.0 to 1.0,\n'
        '  "pacing_directive": one of ["continue_conversation", "sensory_detail", "escalate_tension", "advance_time_or_scene", "de_escalate_reflect"],\n'
        '  "scene_tension": float 1.0 to 5.0,\n'
        '  "pacing_speed": float 1.0 to 3.0,\n'
        '  "emotional_tone": one of ["warm_intimate", "playful_humorous", "mysterious_tense", "dramatic_conflict", "melancholic_somber"],\n'
        '  "trigger_image": float 0.0 to 1.0,\n'
        '  "image_focus": one of ["character_portrait", "action_pose", "environment_wide", "intimate_closeup"],\n'
        '  "character_expression": one of ["neutral", "happy", "blushing", "sad", "angry", "surprised", "seductive"],\n'
        '  "gate_world_state": float 0.0 to 1.0,\n'
        '  "gate_character_state": float 0.0 to 1.0,\n'
        '  "gate_inventory_or_items": float 0.0 to 1.0,\n'
        '  "gate_durable_memory": float 0.0 to 1.0,\n'
        '  "gate_lore_discovery": float 0.0 to 1.0\n'
        "}\n\n"
        f"{context_text}"
    )


def parse_generative_fallback_json(raw_text: str) -> Dict[str, Any]:
    """Extract a JSON object from an LLM completion for `parse_director_result`."""
    cleaned = (raw_text or "").strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1)
    else:
        brace_start = cleaned.find("{")
        brace_end = cleaned.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            cleaned = cleaned[brace_start : brace_end + 1]
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Generative Director fallback did not return a JSON object")
    return data


def heuristic_director_decision(
    context_text: str,
    *,
    last_speaker: str = "user",
    has_secondary_character: bool = False,
    allow_image_generation: bool = True,
    allow_narration: bool = True,
    latency_ms: float = 0.5,
) -> DirectorDecisionResult:
    """Tier 4 deterministic heuristic fallback when Laya and remote workers are offline."""
    lower = (context_text or "").lower()

    # Determine next speaker based on who just spoke and cues in the transcript
    if last_speaker == "user":
        if allow_narration and any(
            w in lower[-350:]
            for w in ("look around", "examine the room", "enter the", "walk into", "describe the", "hours later")
        ):
            next_speaker = "narrator"
            speaker_probs = {"narrator": 0.62, "character": 0.33, "user": 0.05}
        else:
            next_speaker = "character"
            speaker_probs = {"character": 0.78, "narrator": 0.17 if allow_narration else 0.0, "user": 0.05}
        continue_prob = 0.25
    elif last_speaker == "narrator":
        next_speaker = "character"
        speaker_probs = {"character": 0.74, "user": 0.26}
        continue_prob = 0.20
    else:
        # Character just spoke -> usually yield back to user unless strong cliffhanger
        next_speaker = "user"
        speaker_probs = {"user": 0.76, "narrator": 0.14 if allow_narration else 0.0, "character": 0.10}
        continue_prob = 0.18

    # Detect tension & tone keywords
    recent_tail = lower[-500:]
    tension = 2.0
    tone = "warm_intimate"
    directive = "continue_conversation"
    expression = "neutral"

    if any(w in recent_tail for w in ("scream", "blood", "attack", "sword", "gun", "danger", "furious", "fight")):
        tension = 4.2
        tone = "dramatic_conflict"
        directive = "escalate_tension"
        expression = "angry"
    elif any(w in recent_tail for w in ("whisper", "shadow", "strange", "secret", "locked", "footsteps", "nervous")):
        tension = 3.3
        tone = "mysterious_tense"
        directive = "sensory_detail"
        expression = "surprised"
    elif any(w in recent_tail for w in ("kiss", "blush", "touch", "embrace", "heart", "close to", "lips")):
        tension = 3.1
        tone = "warm_intimate"
        directive = "sensory_detail"
        expression = "blushing"
    elif any(w in recent_tail for w in ("laugh", "grin", "tease", "joke", "smile", "chuckle")):
        tension = 1.8
        tone = "playful_humorous"
        directive = "continue_conversation"
        expression = "happy"
    elif any(w in recent_tail for w in ("cry", "tears", "sigh", "sorry", "alone", "grief")):
        tension = 2.8
        tone = "melancholic_somber"
        directive = "de_escalate_reflect"
        expression = "sad"

    # Evaluate Statekeeper gates heuristically on recent text
    gate_world = 0.68 if any(
        w in recent_tail
        for w in ("arrive at", "walk into", "enter the", "morning", "nightfall", "sunset", "rain", "bedroom", "tavern", "forest")
    ) else 0.22
    gate_char = 0.72 if any(
        w in recent_tail
        for w in ("wear", "dress", "jacket", "shirt", "blush", "angry", "smile", "sit down", "stand up", "trust", "love", "hate")
    ) else 0.35
    gate_items = 0.70 if any(
        w in recent_tail
        for w in ("take the", "hand you", "gives", "pocket", "sword", "key", "potion", "letter", "ring", "drink", "bag")
    ) else 0.15
    gate_memory = 0.66 if any(
        w in recent_tail
        for w in ("promise", "remember", "never told", "secret", "my past", "years ago", "swore", "name is")
    ) else 0.25
    gate_lore = 0.62 if any(
        w in recent_tail
        for w in ("kingdom", "ancient", "guild", "order of", "artifact", "legend", "empire", "magic", "district")
    ) else 0.18

    raw_answers = {
        "next_speaker": {"choice": next_speaker, "probabilities": speaker_probs},
        "continue_chain": {"probability": continue_prob},
        "pacing_directive": {"choice": directive, "probabilities": {directive: 0.7}},
        "scene_tension": {"score": tension},
        "pacing_speed": {"score": 2.0},
        "emotional_tone": {"choice": tone},
        "trigger_image": {"probability": 0.68 if gate_world >= 0.6 else 0.22},
        "image_focus": {"choice": "environment_wide" if gate_world >= 0.6 else "character_portrait"},
        "character_expression": {"choice": expression},
        "gate_world_state": {"probability": gate_world},
        "gate_character_state": {"probability": gate_char},
        "gate_inventory_or_items": {"probability": gate_items},
        "gate_durable_memory": {"probability": gate_memory},
        "gate_lore_discovery": {"probability": gate_lore},
    }
    return parse_director_result(
        raw_answers,
        engine_used="heuristic",
        model_id="heuristic_rules",
        latency_ms=latency_ms,
        allow_image_generation=allow_image_generation,
    )
