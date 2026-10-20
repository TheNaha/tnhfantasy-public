"""Expanded 13-question System 1 Decision Schema for the Roleplay Director.

Evaluates turn routing, narrative pacing, visual illustration triggers, and
5 boolean Statekeeper (Updater) gates in a single parallel pass (~150ms on CPU).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from core.pipeline_limits import IMAGE_TRIGGER_THRESHOLD, UPDATER_GATE_THRESHOLD

__all__ = [
    "IMAGE_TRIGGER_THRESHOLD",
    "UPDATER_GATE_THRESHOLD",
]

# Completion confidence bands: Laya's `is_complete` probability is authoritative
# outside the uncertain band; the structural syntax check decides inside it.
COMPLETION_UNCERTAIN_LOW = 0.40
COMPLETION_UNCERTAIN_HIGH = 0.60

UPDATER_GATE_KEYS = (
    "gate_character_mood",
    "gate_scene_tone",
    "gate_relationship_dynamic",
    "gate_character_outfit",
    "gate_current_activity",
    "gate_physical_condition",
    "gate_inventory_or_items",
    "gate_world_clock",
    "gate_location_or_scene",
    "gate_weather_environment",
    "gate_character_skills",
    "gate_user_skills",
    "gate_durable_memory",
    "gate_lore_discovery",
    "gate_quests_or_goals",
    "gate_social_status",
    "gate_world_state",
    "gate_character_state",
)

GATE_LABELS: Dict[str, str] = {
    "gate_character_mood": "Character Mood",
    "gate_scene_tone": "Scene Tone / Atmosphere",
    "gate_relationship_dynamic": "Relationship Dynamic",
    "gate_character_outfit": "Outfit & Wardrobe",
    "gate_current_activity": "Current Activity / Action",
    "gate_physical_condition": "Physical Condition & Health",
    "gate_inventory_or_items": "Inventory & Items",
    "gate_world_clock": "World Clock & Time",
    "gate_location_or_scene": "Location & Scene Boundary",
    "gate_weather_environment": "Weather & Environment",
    "gate_character_skills": "Character Skills",
    "gate_user_skills": "User Skills",
    "gate_durable_memory": "Durable Memory",
    "gate_lore_discovery": "Lore Discovery",
    "gate_quests_or_goals": "Quests & Narrative Goals",
    "gate_social_status": "Social Status & Renown",
    "gate_world_state": "Location / Time (Legacy)",
    "gate_character_state": "Character State & Outfit (Legacy)",
}

# User-facing explanations for the 16 primary gates. Kept beside the labels so
# the LLM Studio gate registry is served from one place instead of a hand-kept
# frontend copy that had already drifted (it listed `gate_location`,
# `gate_weather`, `gate_character_activity`, and `gate_quests_and_goals`, none
# of which are the keys the Director emits).
GATE_DESCRIPTIONS: Dict[str, str] = {
    "gate_character_mood": "Emotional shift, vulnerability, hostility, or joy",
    "gate_scene_tone": "Environmental suspense, intimacy, danger, comedy",
    "gate_relationship_dynamic": "Trust, romantic intimacy, rivalry, or tension shift",
    "gate_character_outfit": "Armor damage, disrobing, disguise, clean clothes",
    "gate_current_activity": "Combat, crafting, traveling, dining, resting",
    "gate_physical_condition": "Injuries, exhaustion, poison, healing, cyberware strain",
    "gate_inventory_or_items": "Acquiring, losing, consuming, or equipping gear",
    "gate_world_clock": "Day advancement, nightfall, rest period duration",
    "gate_location_or_scene": "Fast-travel, entering a room, terrain change",
    "gate_weather_environment": "Rainstorm, fog, blizzard, scorching heat",
    "gate_character_skills": "New martial arts, spells, proficiencies demonstrated",
    "gate_user_skills": "User stat growth, training completion, reputation perks",
    "gate_quests_or_goals": "Mission progress, objectives completed, promises made",
    "gate_social_status": "Faction rank, bounty, outlaw status, aristocracy",
    "gate_durable_memory": "Key narrative revelation to store in episodic memory",
    "gate_lore_discovery": "Ancient history, world secrets, mythos unlocked",
}

# Grouping for the 16-Gate Studio. The tuple order is the display order.
GATE_CATEGORIES = (
    {
        "id": "affect",
        "title": "Psychological & Affect",
        "gates": ("gate_character_mood", "gate_scene_tone", "gate_relationship_dynamic"),
    },
    {
        "id": "embodiment",
        "title": "Embodiment & Gear",
        "gates": (
            "gate_character_outfit",
            "gate_current_activity",
            "gate_physical_condition",
            "gate_inventory_or_items",
        ),
    },
    {
        "id": "world",
        "title": "World & Environment",
        "gates": ("gate_world_clock", "gate_location_or_scene", "gate_weather_environment"),
    },
    {
        "id": "progression",
        "title": "Progression & Stats",
        "gates": (
            "gate_character_skills",
            "gate_user_skills",
            "gate_quests_or_goals",
            "gate_social_status",
        ),
    },
    {
        "id": "memory",
        "title": "Narrative Knowledge",
        "gates": ("gate_durable_memory", "gate_lore_discovery"),
    },
)

# Which Updater output fields each Director gate authorizes. This is the single
# source of truth for the Statekeeper prompt schema and for post-hoc filtering:
# a gate that did not fire may not mutate its fields.
GATE_FIELD_MAP: Dict[str, tuple] = {
    "gate_character_mood": ("character_mood", "character_expression"),
    "gate_scene_tone": ("emotional_tone",),
    "gate_relationship_dynamic": ("relationship_status", "relationships_update", "affinity_delta"),
    "gate_character_outfit": ("character_outfit",),
    "gate_current_activity": ("current_activity",),
    "gate_physical_condition": ("physical_condition",),
    "gate_inventory_or_items": ("inventory", "inventory_add", "inventory_remove"),
    "gate_world_clock": ("story_time", "clock_day_delta", "chronology_event"),
    "gate_location_or_scene": ("story_location",),
    "gate_weather_environment": ("weather",),
    "gate_character_skills": ("character_skills_add",),
    "gate_user_skills": ("user_skills_add",),
    "gate_durable_memory": ("new_memories",),
    "gate_lore_discovery": ("new_lore",),
    "gate_quests_or_goals": ("quests_and_goals",),
    "gate_social_status": ("social_status",),
    # Legacy coarse gates expand to their fine-grained equivalents.
    "gate_world_state": ("story_location", "story_time", "clock_day_delta", "chronology_event", "weather"),
    "gate_character_state": ("character_mood", "character_outfit", "current_activity", "physical_condition", "social_status"),
    # Legacy fine-grained aliases still present in stored job metadata.
    "gate_location_change": ("story_location",),
    "gate_weather_change": ("weather",),
    "gate_character_activity": ("current_activity",),
    "gate_quests_and_goals": ("quests_and_goals",),
}

ALWAYS_ALLOWED_UPDATER_FIELDS = ("scene_summary",)


def allowed_updater_fields(
    triggered_gates: Optional[List[str]],
    director_mode: Optional[str] = None,
) -> Optional[set]:
    """Resolve the Updater fields authorized by the fired gates.

    Returns ``None`` for unrestricted application (wild mode, or when gate
    information is unavailable such as legacy jobs). An empty trigger list
    authorizes only the always-allowed fields.
    """
    if triggered_gates is None or str(director_mode or "").lower() == "wild":
        return None
    allowed = set(ALWAYS_ALLOWED_UPDATER_FIELDS)
    for gate in triggered_gates:
        allowed.update(GATE_FIELD_MAP.get(gate, ()))
    return allowed


@dataclass
class DirectorDecisionResult:
    """Structured result from the Director / Laya classification pass."""

    # Category A: Turn Routing & Multi-Agent Chaining
    next_speaker: str = "character"
    selected_agent: str = "character"
    agent_slug: str = "character"
    next_speaker_probabilities: Dict[str, float] = field(default_factory=dict)
    continue_chain_probability: float = 0.2
    workflow_stage: str = "full"  # "triage", "audit", "chaining", "full"
    is_complete: bool = True
    is_complete_laya_prob: float = 0.5
    is_complete_syntax: bool = True
    completion_source: str = "syntax"  # "laya" | "syntax"

    # Category B: Narrative Direction & Pacing
    pacing_directive: str = "continue_conversation"
    pacing_directive_probabilities: Dict[str, float] = field(default_factory=dict)
    scene_tension: float = 2.0
    pacing_speed: float = 2.0
    emotional_tone: str = "warm_intimate"

    # Category C: Visual & Expression Triggers
    trigger_image_probability: float = 0.15
    should_trigger_image: bool = False
    image_threshold: float = IMAGE_TRIGGER_THRESHOLD

    # Category D: Statekeeper (Updater) Gates
    updater_gates: Dict[str, float] = field(default_factory=dict)
    triggered_gates: List[str] = field(default_factory=list)
    should_run_updater: bool = False
    updater_evaluation: Dict[str, Any] = field(default_factory=dict)
    questions_evaluated: List[Dict[str, Any]] = field(default_factory=list)

    # Sub-variant routing + user-authored custom questions (see laya_questions.py).
    selected_variant: Optional[str] = None
    custom_directives: List[Dict[str, Any]] = field(default_factory=list)
    # Raw typed answers as returned by the engine; not serialised (to_dict drops it).
    raw_answers: Dict[str, Any] = field(default_factory=dict, repr=False)

    # Category E: Toggleable Fate / Skill Check (Anti-Godmoding & Narrative Control)
    is_risky_action_probability: float = 0.15
    action_difficulty: float = 2.0
    fate_outcome: Optional[str] = None
    fate_directive: Optional[str] = None
    matched_skills: List[str] = field(default_factory=list)

    # Category F: Fine-Grained 16 Field Gates
    gate_character_mood: float = 0.2
    gate_scene_tone: float = 0.2
    gate_relationship_dynamic: float = 0.2
    gate_character_outfit: float = 0.2
    gate_current_activity: float = 0.2
    gate_physical_condition: float = 0.2
    gate_inventory_or_items: float = 0.2
    gate_world_clock: float = 0.2
    gate_location_or_scene: float = 0.2
    gate_weather_environment: float = 0.2
    gate_character_skills: float = 0.2
    gate_user_skills: float = 0.2
    gate_durable_memory: float = 0.2
    gate_lore_discovery: float = 0.2
    gate_quests_or_goals: float = 0.2
    gate_social_status: float = 0.2
    gate_world_state: float = 0.2
    gate_character_state: float = 0.2

    mood_shift_detected: bool = False
    tone_shift_detected: bool = False
    relationship_shift_detected: bool = False
    relationship_status: Optional[str] = None
    director_mode: str = "steered"
    user_directive: Optional[str] = None

    # Telemetry
    engine_used: str = "heuristic"
    model_id: str = "heuristic"
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("raw_answers", None)
        t_int = max(1, min(5, round(self.scene_tension)))
        tension_labels = {1: "calm", 2: "warm", 3: "rising", 4: "high", 5: "climactic"}
        s_int = max(1, min(3, round(self.pacing_speed)))
        speed_labels = {1: "slow-motion", 2: "real-time", 3: "fast-forward"}
        d_int = max(1, min(5, round(self.action_difficulty)))
        diff_labels = {1: "trivial", 2: "easy", 3: "moderate", 4: "hard", 5: "extreme"}
        data["provider_tier"] = self.engine_used
        data["scene_tension_label"] = tension_labels.get(t_int, "normal")
        data["pacing_speed_label"] = speed_labels.get(s_int, "real-time")
        data["action_difficulty_label"] = diff_labels.get(d_int, "moderate")
        data["continue_chain_prob"] = self.continue_chain_probability
        data["trigger_image_prob"] = self.trigger_image_probability
        data["is_risky_action_prob"] = self.is_risky_action_probability
        data["mood_shift_detected"] = self.mood_shift_detected
        data["relationship_shift_detected"] = self.relationship_shift_detected
        data["tone_shift_detected"] = self.tone_shift_detected
        data["gate_scene_tone"] = self.gate_scene_tone
        data["selected_agent"] = self.selected_agent
        data["agent_slug"] = self.agent_slug
        data["is_complete"] = self.is_complete
        data["workflow_stage"] = self.workflow_stage
        for k in UPDATER_GATE_KEYS:
            data[k] = getattr(self, k, self.updater_gates.get(k, 0.2))
        data["updater_evaluation"] = self.updater_evaluation
        data["questions_evaluated"] = self.questions_evaluated
        data["director_mode"] = self.director_mode
        data["user_directive"] = self.user_directive
        base_instruction = (
            f"Pacing: {self.pacing_directive} ({speed_labels.get(s_int, 'real-time')}) | "
            f"Tension: {self.scene_tension}/5 ({tension_labels.get(t_int, 'normal')}) | "
            f"Tone: {self.emotional_tone}"
        )
        if self.user_directive:
            base_instruction = f"[Player Directive: {self.user_directive}] | " + base_instruction
        if self.fate_directive:
            base_instruction += f" | Fate Check: {self.fate_outcome} ({self.fate_directive})"
        if self.custom_directives:
            base_instruction += " | " + " | ".join(d.get("directive", "") for d in self.custom_directives if d.get("directive"))
        data["director_instruction"] = base_instruction
        return data


def build_speaker_options(
    available_agents: Optional[List[Dict[str, Any]]] = None,
    *,
    has_secondary_character: bool = False,
    allow_narration: bool = True,
) -> Dict[str, str]:
    """Build speaker options including built-in and user-registered custom agents."""
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

    # Inject any custom agents passed in
    for agent in available_agents or []:
        slug = agent.get("slug")
        desc = agent.get("description") or agent.get("name")
        if slug and desc and slug not in speaker_options and slug != "user":
            speaker_options[slug] = desc

    speaker_options["user"] = (
        "The scene beat is complete and it is now the player's turn to respond."
    )
    return speaker_options


def build_pre_generation_triage_questions(
    available_agents: Optional[List[Dict[str, Any]]] = None,
    *,
    has_secondary_character: bool = False,
    allow_narration: bool = True,
) -> List[Dict[str, Any]]:
    """Build Stage 1 questions: agent routing, narrative pacing, and Fate/Skill checks."""
    speaker_options = build_speaker_options(
        available_agents,
        has_secondary_character=has_secondary_character,
        allow_narration=allow_narration,
    )
    return [
        {
            "key": "next_speaker",
            "type": "choice",
            "question": "Which agent or participant should take the immediate response in this roleplay scene?",
            "options": speaker_options,
        },
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
            "key": "is_risky_action",
            "type": "noul",
            "statement": (
                "The player or character is attempting a risky, contested, dangerous, or difficult "
                "physical, social, or magical feat where success is not automatically guaranteed."
            ),
        },
        {
            "key": "action_difficulty",
            "type": "score",
            "question": "If an action or feat is being attempted, how difficult is it to pull off?",
            "rubric": {
                1: "Trivial: everyday action that almost anyone can do effortlessly.",
                2: "Easy: requires basic competence or mild effort.",
                3: "Moderate: requires training, focus, or favorable circumstances.",
                4: "Hard: high risk of failure without specialized skill or equipment.",
                5: "Extreme: near-impossible feat against overwhelming odds.",
            },
        },
    ]


def build_post_generation_audit_questions() -> List[Dict[str, Any]]:
    """Build Stage 2 questions: text completion, illustration triggers, and 16 narrative state gates."""
    return [
        {
            "key": "is_complete",
            "type": "noul",
            "statement": "The speaker finished their complete sentence, dialog, thought, or scene beat naturally without being cut off mid-sentence.",
        },
        {
            "key": "trigger_image",
            "type": "noul",
            "statement": (
                "This moment features a striking visual change, new location, dramatic pose, "
                "or key emotional beat that warrants generating a scene illustration."
            ),
        },
        # --- The 16 Statekeeper Narrative Gates ---
        {
            "key": "gate_character_mood",
            "type": "noul",
            "statement": "The primary character's internal mood, emotional stance, or feelings shifted noticeably in this exchange.",
        },
        {
            "key": "gate_scene_tone",
            "type": "noul",
            "statement": "The scene's ambient atmosphere, emotional tone, or environmental mood shifted noticeably during this exchange.",
        },
        {
            "key": "gate_relationship_dynamic",
            "type": "noul",
            "statement": "The interpersonal dynamic, trust, boundary, affinity, or bond between characters shifted noticeably in this exchange.",
        },
        {
            "key": "gate_character_outfit",
            "type": "noul",
            "statement": "A character changed clothes, altered their outfit, removed attire, or had their clothing damaged/dirtied/soaked.",
        },
        {
            "key": "gate_current_activity",
            "type": "noul",
            "statement": "A character started, completed, or changed their primary physical activity or posture (e.g. sitting, running, resting).",
        },
        {
            "key": "gate_physical_condition",
            "type": "noul",
            "statement": "A character suffered an injury, wound, exhaustion, intoxication, illness, or experienced physical healing.",
        },
        {
            "key": "gate_inventory_or_items",
            "type": "noul",
            "statement": "An item, weapon, gift, potion, key, or piece of equipment was acquired, used, lost, crafted, or exchanged.",
        },
        {
            "key": "gate_world_clock",
            "type": "noul",
            "statement": "Narrative time advanced significantly (hours passed, dawn, noon, dusk, nightfall, or the next day arrived).",
        },
        {
            "key": "gate_location_or_scene",
            "type": "noul",
            "statement": "The characters moved to a new location, entered a building, traveled, or crossed a distinct scene boundary.",
        },
        {
            "key": "gate_weather_environment",
            "type": "noul",
            "statement": "The weather or ambient environmental conditions changed (e.g. began raining, storming, snow, fog, darkness).",
        },
        {
            "key": "gate_character_skills",
            "type": "noul",
            "statement": "A character demonstrated, practiced, unlocked, or improved a notable personal skill, spell, or technique.",
        },
        {
            "key": "gate_user_skills",
            "type": "noul",
            "statement": "The player character demonstrated, revealed, or applied a specialized personal skill, knowledge, or proficiency.",
        },
        {
            "key": "gate_durable_memory",
            "type": "noul",
            "statement": "A significant personal secret, promise, backstory reveal, or milestone occurred that should be saved to long-term memory.",
        },
        {
            "key": "gate_lore_discovery",
            "type": "noul",
            "statement": "A new named faction, historical event, deity, organization, or world rule was introduced that belongs in the Lorebook.",
        },
        {
            "key": "gate_quests_or_goals",
            "type": "noul",
            "statement": "A quest, mutual mission, objective, contract, or major goal was initiated, updated, completed, or failed.",
        },
        {
            "key": "gate_social_status",
            "type": "noul",
            "statement": "A character or player's social reputation, standing, bounty, noble title, or public perception shifted.",
        },
        # Legacy Aliases
        {
            "key": "gate_world_state",
            "type": "noul",
            "statement": "The location, setting, time of day, or weather changed during this exchange.",
        },
        {
            "key": "gate_character_state",
            "type": "noul",
            "statement": "A character's physical condition, clothing/outfit, current activity, or presence shifted during this exchange.",
        },
    ]


def build_turn_chaining_questions(
    available_agents: Optional[List[Dict[str, Any]]] = None,
    *,
    has_secondary_character: bool = False,
    allow_narration: bool = True,
) -> List[Dict[str, Any]]:
    """Build Stage 3 questions: who speaks next in autonomous scene chaining."""
    speaker_options = build_speaker_options(
        available_agents,
        has_secondary_character=has_secondary_character,
        allow_narration=allow_narration,
    )
    return [
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
                "After the current turn finishes, another AI agent (narrator or character) "
                "should immediately follow up before yielding control back to the player."
            ),
        },
    ]


def build_director_questions(
    *,
    has_secondary_character: bool = False,
    allow_narration: bool = True,
    available_agents: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Return unified System 1 questions combining triage, pacing, visual, and all 16 state gates."""
    triage = build_pre_generation_triage_questions(
        available_agents=available_agents,
        has_secondary_character=has_secondary_character,
        allow_narration=allow_narration,
    )
    audit = build_post_generation_audit_questions()

    # Include continue_chain and emotional_tone for complete backward compatibility
    extras = [
        {
            "key": "continue_chain",
            "type": "noul",
            "statement": (
                "After the next speaker finishes their turn, another AI agent (narrator or character) "
                "should immediately follow up before yielding control back to the player."
            ),
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
    ]

    # Combine ensuring keys are unique in order
    seen = set()
    combined = []
    for q in [triage[0], extras[0], *triage[1:], extras[1], *audit]:
        if q["key"] not in seen:
            seen.add(q["key"])
            combined.append(q)

    return combined


FATE_OUTCOME_DESCRIPTIONS: Dict[str, str] = {
    "critical_success": "Critical Success — the action succeeds brilliantly with an unexpected advantage or flair.",
    "success": "Clean Success — the attempted action succeeds as intended.",
    "success_with_cost": "Success with Cost — the action succeeds, but introduces a complication, toll, or partial setback.",
    "complication": "Complication / Partial Failure — the action falls short or goes sideways, creating new tension.",
    "failure": "Failure — the attempted feat fails and the character/player must deal with the consequences.",
}

DIFFICULTY_PRESET_MAP: Dict[str, float] = {
    "trivial": 1.0,
    "easy": 2.0,
    "moderate": 3.0,
    "hard": 4.0,
    "extreme": 5.0,
    "1": 1.0,
    "2": 2.0,
    "3": 3.0,
    "4": 4.0,
    "5": 5.0,
}


def resolve_fate_check(
    decision: DirectorDecisionResult,
    *,
    state_snapshot: Optional[Dict[str, Any]] = None,
    context_text: str = "",
) -> DirectorDecisionResult:
    """Apply toggleable Fate / Skill Check resolution onto `decision`.

    Honours user-editable settings stored in `state_snapshot`:
      - `fate_check_enabled`: bool (default False — opt-in so users who want pure freeform aren't restricted,
        unless `outcome_override` is explicitly set to a forced outcome)
      - `fate_difficulty`: "auto" | "trivial" | "easy" | "moderate" | "hard" | "extreme" (or 1..5)
      - `fate_outcome_override`: "auto" | "critical_success" | "success" | "success_with_cost" | "complication" | "failure"
      - `character_skills`: list[str]
      - `user_skills`: list[str]
    """
    snap = state_snapshot or {}
    fate_enabled = bool(snap.get("fate_check_enabled", False))
    diff_setting = str(snap.get("fate_difficulty") or "auto").strip().lower()
    outcome_override = str(snap.get("fate_outcome_override") or "auto").strip().lower()

    # Apply manual difficulty override if the user pinned one
    if diff_setting in DIFFICULTY_PRESET_MAP:
        decision.action_difficulty = DIFFICULTY_PRESET_MAP[diff_setting]

    # Match skills from character_skills and user_skills against recent text
    char_skills = [str(s).strip() for s in (snap.get("character_skills") or []) if str(s).strip()]
    user_skills = [str(s).strip() for s in (snap.get("user_skills") or []) if str(s).strip()]
    all_skills = char_skills + user_skills
    recent_lower = (context_text or "")[-600:].lower()
    matched: List[str] = []
    for skill in all_skills:
        # Match either the whole skill phrase or any significant word >= 4 chars
        s_low = skill.lower()
        words = [w for w in re.split(r"[^a-z0-9]+", s_low) if len(w) >= 4]
        if s_low in recent_lower or any(w in recent_lower for w in words):
            if skill not in matched:
                matched.append(skill)
    decision.matched_skills = matched

    # If the user forced a specific outcome, apply it even if fate_check_enabled was off
    if outcome_override in FATE_OUTCOME_DESCRIPTIONS:
        decision.fate_outcome = outcome_override
        skill_note = f" (Relevant skills: {', '.join(matched)})" if matched else ""
        decision.fate_directive = f"{FATE_OUTCOME_DESCRIPTIONS[outcome_override]}{skill_note}"
        return decision

    if not fate_enabled:
        decision.fate_outcome = None
        decision.fate_directive = None
        return decision

    # When enabled in auto mode, trigger when risky action >= 0.50 or user pinned a non-auto difficulty
    if decision.is_risky_action_probability < 0.50 and diff_setting == "auto":
        decision.fate_outcome = None
        decision.fate_directive = None
        return decision

    # Effective difficulty is reduced by matched skills (-0.75 per relevant skill, min 1.0)
    effective_diff = max(1.0, decision.action_difficulty - (0.75 * len(matched)))

    if effective_diff <= 1.6:
        outcome = "critical_success"
    elif effective_diff <= 2.6:
        outcome = "success"
    elif effective_diff <= 3.5:
        outcome = "success_with_cost"
    elif effective_diff <= 4.3:
        outcome = "complication"
    else:
        outcome = "failure"

    decision.fate_outcome = outcome
    skill_note = f" [Skills applied: {', '.join(matched)}]" if matched else ""
    decision.fate_directive = (
        f"Difficulty {decision.action_difficulty:.1f}/5 -> {FATE_OUTCOME_DESCRIPTIONS[outcome]}{skill_note}"
    )
    return decision


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
        rels = snap.get("relationships")
        if isinstance(rels, list) and rels:
            rel_parts = [
                f"{r.get('target_name', 'Unknown')}: {r.get('status', '')}"
                for r in rels
                if isinstance(r, dict) and r.get("status")
            ]
            if rel_parts:
                lines.append(f"Relationships: {' | '.join(rel_parts)}")
        char_skills = snap.get("character_skills")
        if isinstance(char_skills, list) and char_skills:
            lines.append(f"{character_name} Skillset: {', '.join(str(x) for x in char_skills)}")
        user_skills = snap.get("user_skills")
        if isinstance(user_skills, list) and user_skills:
            lines.append(f"{user_name} Skillset: {', '.join(str(x) for x in user_skills)}")
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


def build_evaluated_questions_trace(
    raw_answers: Dict[str, Any],
    result: DirectorDecisionResult,
    effective_threshold: float,
    *,
    has_secondary_character: bool = False,
    allow_narration: bool = True,
) -> List[Dict[str, Any]]:
    """Build a transparent diagnostic trace of all questions evaluated during the Director pass."""
    questions = build_director_questions(
        has_secondary_character=has_secondary_character,
        allow_narration=allow_narration,
    )
    evaluated: List[Dict[str, Any]] = []

    category_map = {
        "next_speaker": "Turn Routing",
        "continue_chain": "Turn Routing",
        "pacing_directive": "Narrative Pacing",
        "scene_tension": "Narrative Pacing",
        "pacing_speed": "Narrative Pacing",
        "emotional_tone": "Scene Atmosphere",
        "trigger_image": "Visual Illustration",
        "gate_world_state": "Statekeeper Gates",
        "gate_scene_tone": "Statekeeper Gates",
        "gate_character_state": "Statekeeper Gates",
        "gate_character_mood": "Statekeeper Gates",
        "gate_relationship_dynamic": "Statekeeper Gates",
        "gate_character_outfit": "Statekeeper Gates",
        "gate_current_activity": "Statekeeper Gates",
        "gate_physical_condition": "Statekeeper Gates",
        "gate_inventory_or_items": "Statekeeper Gates",
        "gate_world_clock": "Statekeeper Gates",
        "gate_location_or_scene": "Statekeeper Gates",
        "gate_location_change": "Statekeeper Gates",
        "gate_weather_environment": "Statekeeper Gates",
        "gate_weather_change": "Statekeeper Gates",
        "gate_character_skills": "Statekeeper Gates",
        "gate_user_skills": "Statekeeper Gates",
        "gate_durable_memory": "Statekeeper Gates",
        "gate_lore_discovery": "Statekeeper Gates",
        "gate_quests_or_goals": "Statekeeper Gates",
        "gate_quests_and_goals": "Statekeeper Gates",
        "gate_social_status": "Statekeeper Gates",
        "is_complete": "Completion Audit",
        "is_risky_action": "Fate & Skill Check",
        "action_difficulty": "Fate & Skill Check",
    }

    threshold_pct = int(round(effective_threshold * 100))

    for q in questions:
        key = q["key"]
        q_type = q["type"]
        category = category_map.get(key, "General")
        prompt_text = q.get("question") or q.get("statement") or ""
        options_or_rubric = q.get("options") or q.get("rubric") or {}

        val: Any = None
        status_text = ""
        prob_or_score: Optional[float] = None
        probabilities: Dict[str, float] = {}

        raw_entry = raw_answers.get(key)
        if isinstance(raw_entry, dict) and "probabilities" in raw_entry:
            probabilities = {
                str(k): round(float(v), 4)
                for k, v in raw_entry["probabilities"].items()
                if isinstance(v, (int, float))
            }

        if q_type == "choice":
            val = getattr(result, key, "")
            chosen_desc = options_or_rubric.get(val, "") if isinstance(options_or_rubric, dict) else ""
            status_text = f"Selected: {val}" + (f" ({chosen_desc})" if chosen_desc else "")
            if val in probabilities:
                prob_or_score = probabilities[val]
        elif q_type == "score":
            val = getattr(result, key, 0.0)
            prob_or_score = float(val)
            if key == "scene_tension":
                status_text = f"Tension: {val}/5 ({getattr(result, 'scene_tension_label', 'normal')})"
            elif key == "pacing_speed":
                status_text = f"Speed: {getattr(result, 'pacing_speed_label', 'real-time')} ({val}/3)"
            elif key == "action_difficulty":
                status_text = f"Difficulty: {getattr(result, 'action_difficulty_label', 'moderate')} ({val}/5)"
            else:
                status_text = f"Score: {val}"
        elif q_type == "noul":
            if key in UPDATER_GATE_KEYS:
                prob = result.updater_gates.get(key, 0.0)
                prob_or_score = prob
                pct = int(round(prob * 100))
                triggered = key in result.triggered_gates
                status_text = (
                    f"FIRED ({pct}% ≥ {threshold_pct}%)"
                    if triggered
                    else f"IDLE ({pct}% < {threshold_pct}%)"
                )
                val = triggered
            else:
                if key == "continue_chain":
                    prob = result.continue_chain_probability
                    status_text = f"Continue chain: {int(round(prob * 100))}%"
                elif key == "trigger_image":
                    prob = result.trigger_image_probability
                    image_threshold = getattr(result, "image_threshold", IMAGE_TRIGGER_THRESHOLD)
                    threshold_pct = int(round(image_threshold * 100))
                    status_text = (
                        f"Illustrate: {'YES' if result.should_trigger_image else 'NO'} "
                        f"({int(round(prob * 100))}% vs {threshold_pct}%)"
                    )
                elif key == "is_risky_action":
                    prob = result.is_risky_action_probability
                    status_text = f"Risky feat: {int(round(prob * 100))}%"
                elif key == "is_complete":
                    laya_prob = getattr(result, "is_complete_laya_prob", 0.5)
                    prob_or_score = laya_prob
                    status_text = (
                        f"Laya: {int(round(laya_prob * 100))}% | "
                        f"syntax: {'complete' if result.is_complete_syntax else 'incomplete'} | "
                        f"source: {result.completion_source} -> "
                        f"{'COMPLETE' if result.is_complete else 'CONTINUE'}"
                    )
                    val = result.is_complete
                else:
                    prob = 0.0
                    status_text = f"Probability: {int(round(prob * 100))}%"
                prob_or_score = prob
                val = prob >= 0.5

        evaluated.append({
            "key": key,
            "category": category,
            "type": q_type,
            "prompt": prompt_text,
            "options": options_or_rubric,
            "value": val,
            "probability_or_score": prob_or_score,
            "probabilities": probabilities,
            "status": status_text,
        })

    return evaluated


def parse_director_result(
    raw_answers: Dict[str, Any],
    *,
    engine_used: str = "system1_laya",
    model_id: str = "laya_multilingual",
    latency_ms: float = 0.0,
    allow_image_generation: bool = True,
    state_snapshot: Optional[Dict[str, Any]] = None,
    context_text: str = "",
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

    selected_variant: Optional[str] = None
    target_variant_key = f"{next_speaker}_variant"
    if target_variant_key in raw_answers:
        v_choice, _ = _choice(target_variant_key, "default")
        if v_choice and v_choice != "default":
            selected_variant = v_choice
    elif next_speaker == "narrator" and "narrator_variant" in raw_answers:
        v_choice, _ = _choice("narrator_variant", "default")
        if v_choice and v_choice != "default":
            selected_variant = v_choice
    elif "character_variant" in raw_answers and next_speaker not in ("narrator", "user"):
        v_choice, _ = _choice("character_variant", "default")
        if v_choice and v_choice != "default":
            selected_variant = v_choice

    snap = state_snapshot or {}

    trigger_img_prob = _noul("trigger_image", 0.15)
    raw_image_threshold = snap.get("image_threshold", IMAGE_TRIGGER_THRESHOLD)
    try:
        image_threshold = max(0.0, min(1.0, float(raw_image_threshold)))
    except (TypeError, ValueError):
        image_threshold = IMAGE_TRIGGER_THRESHOLD

    effective_threshold = float(snap.get("gate_threshold") or UPDATER_GATE_THRESHOLD)
    director_mode = str(snap.get("director_mode") or "steered").lower()

    gate_scene_tone = _noul("gate_scene_tone", 0.2)
    gate_mood = _noul("gate_character_mood", 0.2)
    gate_rel = _noul("gate_relationship_dynamic", 0.2)

    updater_gates: Dict[str, float] = {}
    triggered_gates: List[str] = []
    for gate_key in UPDATER_GATE_KEYS:
        if gate_key == "gate_scene_tone":
            prob = gate_scene_tone
        elif gate_key == "gate_character_mood":
            prob = gate_mood
        elif gate_key == "gate_relationship_dynamic":
            prob = gate_rel
        else:
            prob = _noul(gate_key, 0.2)
        updater_gates[gate_key] = prob
        if prob >= effective_threshold or director_mode == "wild":
            triggered_gates.append(gate_key)

    is_risky_prob = _noul("is_risky_action", 0.15)
    action_diff = _score("action_difficulty", 2.0, 1.0, 5.0)


    mood_shift = ("gate_character_mood" in triggered_gates) or ("gate_character_state" in triggered_gates) or (director_mode == "wild")
    tone_shift = ("gate_scene_tone" in triggered_gates) or ("gate_world_state" in triggered_gates) or (director_mode == "wild")
    rel_shift = ("gate_relationship_dynamic" in triggered_gates) or ("gate_character_state" in triggered_gates) or (director_mode == "wild")

    user_directive = snap.get("user_directive") or snap.get("last_user_directive")

    should_run_updater = bool(len(triggered_gates) > 0 or mood_shift or tone_shift or rel_shift or director_mode == "wild")

    top_gate_key = max(updater_gates.keys(), key=lambda k: updater_gates[k]) if updater_gates else "gate_world_state"
    top_gate_prob = updater_gates.get(top_gate_key, 0.0)
    top_gate_label = GATE_LABELS.get(top_gate_key, top_gate_key)
    threshold_pct = int(round(effective_threshold * 100))
    top_prob_pct = int(round(top_gate_prob * 100))

    if should_run_updater:
        if director_mode == "wild":
            diag_summary = "Statekeeper active (Wild director mode: all turns update)"
        else:
            triggered_details = [
                f"{GATE_LABELS.get(g, g)} ({int(round(updater_gates.get(g, 0.0) * 100))}% ≥ {threshold_pct}%)"
                for g in triggered_gates
            ]
            diag_summary = f"Statekeeper triggered by: {', '.join(triggered_details)}"
    else:
        diag_summary = f"Statekeeper idle: All gates below {threshold_pct}% activation threshold (highest: {top_gate_label} at {top_prob_pct}%)"

    updater_evaluation = {
        "should_run_updater": should_run_updater,
        "activation_threshold": effective_threshold,
        "activation_threshold_pct": threshold_pct,
        "director_mode": director_mode,
        "triggered_gates": triggered_gates,
        "highest_gate": {
            "key": top_gate_key,
            "label": top_gate_label,
            "probability": top_gate_prob,
            "probability_pct": top_prob_pct,
        },
        "diagnostic_summary": diag_summary,
        "gates": {
            k: {
                "label": GATE_LABELS.get(k, k),
                "probability": v,
                "probability_pct": int(round(v * 100)),
                "triggered": k in triggered_gates,
            }
            for k, v in updater_gates.items()
        },
    }

    # Completion check: Laya's confidence bands are authoritative when confident;
    # the structural punctuation syntax check is the fallback in the uncertain band.
    raw_tail = (context_text or "").strip()
    syntax_complete = True
    if raw_tail:
        dangling_words = {"and", "or", "the", "a", "an", "with", "to", "in", "of", "but", "that", "who", "which", "as", "if"}
        last_words = re.findall(r"\b\w+\b", raw_tail.lower())
        ends_dangling = bool(last_words and last_words[-1] in dangling_words)
        ends_punct = raw_tail.endswith((".", "!", "?", '"', '”', "'", "’", "*", "~", "\n"))
        if ends_dangling or not ends_punct:
            syntax_complete = False

    laya_complete_prob = _noul("is_complete", 0.5)
    completion_policy = str(snap.get("completion_policy") or "confidence_bands").strip().lower()
    if completion_policy == "syntax":
        is_complete_val = bool(syntax_complete)
        completion_source = "syntax"
    elif completion_policy == "laya":
        is_complete_val = laya_complete_prob >= 0.5
        completion_source = "laya"
    elif laya_complete_prob <= COMPLETION_UNCERTAIN_LOW:
        is_complete_val = False
        completion_source = "laya"
    elif laya_complete_prob >= COMPLETION_UNCERTAIN_HIGH:
        is_complete_val = True
        completion_source = "laya"
    else:
        is_complete_val = bool(syntax_complete)
        completion_source = "syntax"

    result = DirectorDecisionResult(
        next_speaker=next_speaker,
        selected_agent=next_speaker,
        agent_slug=next_speaker,
        is_complete=is_complete_val,
        next_speaker_probabilities=next_speaker_probs,
        continue_chain_probability=continue_chain_prob,
        pacing_directive=pacing_directive,
        pacing_directive_probabilities=pacing_probs,
        scene_tension=scene_tension,
        pacing_speed=pacing_speed,
        emotional_tone=emotional_tone,
        trigger_image_probability=trigger_img_prob,
        should_trigger_image=bool(allow_image_generation and trigger_img_prob >= image_threshold),
        image_threshold=image_threshold,
        updater_gates=updater_gates,
        triggered_gates=triggered_gates,
        should_run_updater=should_run_updater,
        updater_evaluation=updater_evaluation,
        is_risky_action_probability=is_risky_prob,
        action_difficulty=action_diff,
        gate_character_mood=gate_mood,
        gate_relationship_dynamic=gate_rel,
        gate_scene_tone=gate_scene_tone,
        gate_character_outfit=updater_gates.get("gate_character_outfit", 0.2),
        gate_current_activity=updater_gates.get("gate_current_activity", 0.2),
        gate_physical_condition=updater_gates.get("gate_physical_condition", 0.2),
        gate_inventory_or_items=updater_gates.get("gate_inventory_or_items", 0.2),
        gate_world_clock=updater_gates.get("gate_world_clock", 0.2),
        gate_location_or_scene=updater_gates.get("gate_location_or_scene", 0.2),
        gate_weather_environment=updater_gates.get("gate_weather_environment", 0.2),
        gate_character_skills=updater_gates.get("gate_character_skills", 0.2),
        gate_user_skills=updater_gates.get("gate_user_skills", 0.2),
        gate_durable_memory=updater_gates.get("gate_durable_memory", 0.2),
        gate_lore_discovery=updater_gates.get("gate_lore_discovery", 0.2),
        gate_quests_or_goals=updater_gates.get("gate_quests_or_goals", 0.2),
        gate_social_status=updater_gates.get("gate_social_status", 0.2),
        gate_world_state=updater_gates.get("gate_world_state", 0.2),
        gate_character_state=updater_gates.get("gate_character_state", 0.2),
        mood_shift_detected=mood_shift,
        tone_shift_detected=tone_shift,
        relationship_shift_detected=rel_shift,
        relationship_status=snap.get("relationship_status"),
        director_mode=director_mode,
        user_directive=user_directive,
        engine_used=engine_used,
        model_id=model_id,
        latency_ms=round(latency_ms, 1),
        is_complete_laya_prob=laya_complete_prob,
        is_complete_syntax=bool(syntax_complete),
        completion_source=completion_source,
        selected_variant=selected_variant,
        raw_answers=dict(raw_answers),
    )
    result.questions_evaluated = build_evaluated_questions_trace(
        raw_answers,
        result,
        effective_threshold,
    )
    return resolve_fate_check(result, state_snapshot=state_snapshot, context_text=context_text)


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
        '  "gate_character_mood": float 0.0 to 1.0,\n'
        '  "gate_scene_tone": float 0.0 to 1.0,\n'
        '  "gate_relationship_dynamic": float 0.0 to 1.0,\n'
        '  "gate_character_outfit": float 0.0 to 1.0,\n'
        '  "gate_current_activity": float 0.0 to 1.0,\n'
        '  "gate_physical_condition": float 0.0 to 1.0,\n'
        '  "gate_inventory_or_items": float 0.0 to 1.0,\n'
        '  "gate_world_clock": float 0.0 to 1.0,\n'
        '  "gate_location_or_scene": float 0.0 to 1.0,\n'
        '  "gate_weather_environment": float 0.0 to 1.0,\n'
        '  "gate_character_skills": float 0.0 to 1.0,\n'
        '  "gate_user_skills": float 0.0 to 1.0,\n'
        '  "gate_durable_memory": float 0.0 to 1.0,\n'
        '  "gate_lore_discovery": float 0.0 to 1.0,\n'
        '  "gate_quests_or_goals": float 0.0 to 1.0,\n'
        '  "gate_social_status": float 0.0 to 1.0,\n'
        '  "gate_world_state": float 0.0 to 1.0,\n'
        '  "gate_character_state": float 0.0 to 1.0,\n'
        '  "is_risky_action": float 0.0 to 1.0,\n'
        '  "action_difficulty": float 1.0 to 5.0,\n'
        '  "is_complete": float 0.0 to 1.0 (confidence that the latest character reply is a finished beat)\n'
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
    state_snapshot: Optional[Dict[str, Any]] = None,
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

    if any(w in recent_tail for w in ("scream", "blood", "attack", "sword", "gun", "danger", "furious", "fight")):
        tension = 4.2
        tone = "dramatic_conflict"
        directive = "escalate_tension"
    elif any(w in recent_tail for w in ("whisper", "shadow", "strange", "secret", "locked", "footsteps", "nervous")):
        tension = 3.3
        tone = "mysterious_tense"
        directive = "sensory_detail"
    elif any(w in recent_tail for w in ("kiss", "blush", "touch", "embrace", "heart", "close to", "lips")):
        tension = 3.1
        tone = "warm_intimate"
        directive = "sensory_detail"
    elif any(w in recent_tail for w in ("laugh", "grin", "tease", "joke", "smile", "chuckle")):
        tension = 1.8
        tone = "playful_humorous"
        directive = "continue_conversation"
    elif any(w in recent_tail for w in ("cry", "tears", "sigh", "sorry", "alone", "grief")):
        tension = 2.8
        tone = "melancholic_somber"
        directive = "de_escalate_reflect"

    # Evaluate Statekeeper gates heuristically on recent text
    gate_world = 0.68 if any(
        w in recent_tail
        for w in ("arrive at", "walk into", "enter the", "morning", "nightfall", "sunset", "rain", "bedroom", "tavern", "forest")
    ) else 0.22
    gate_scene_tone = 0.65 if any(
        w in recent_tail
        for w in ("rain", "storm", "dark", "silence", "tension", "chill", "cold", "warmth", "candlelight", "shadows", "ominous", "cheerful", "nightfall", "sunset")
    ) else 0.20
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

    gate_outfit = 0.70 if any(
        w in recent_tail
        for w in ("wear", "dress", "jacket", "shirt", "robe", "cloak", "armor", "uniform", "wet", "dirty", "stripped", "changed into")
    ) else 0.20
    gate_activity = 0.70 if any(
        w in recent_tail
        for w in ("sit", "stand", "running", "cooking", "eating", "reading", "sleeping", "training", "fleeing", "climbing")
    ) else 0.20
    gate_condition = 0.75 if any(
        w in recent_tail
        for w in ("wound", "blood", "injured", "bleed", "exhausted", "tired", "poison", "fainted", "healed", "struck", "pain")
    ) else 0.15
    gate_clock = 0.70 if any(
        w in recent_tail
        for w in ("morning", "evening", "night", "hours later", "next day", "dawn", "dusk", "midnight", "noon", "later that day")
    ) else 0.20
    gate_location = gate_world
    gate_weather = 0.70 if any(
        w in recent_tail
        for w in ("rain", "snow", "storm", "thunder", "wind", "fog", "sunlight", "freezing", "hot", "clouds")
    ) else 0.20
    gate_char_skills = 0.65 if any(
        w in recent_tail
        for w in ("cast", "spell", "technique", "swordplay", "skill", "mastery", "learned", "trained")
    ) else 0.20
    gate_user_skills = 0.65 if any(
        w in recent_tail
        for w in ("i shoot", "i cast", "i sneak", "i pick the lock", "i decipher", "my training")
    ) else 0.20
    gate_quests = 0.70 if any(
        w in recent_tail
        for w in ("quest", "mission", "objective", "task", "bounty", "contract", "we must find", "plan is")
    ) else 0.20
    gate_social = 0.65 if any(
        w in recent_tail
        for w in ("reputation", "outlaw", "hero", "villain", "noble", "knight", "ranked", "famous", "infamous")
    ) else 0.20

    is_risky = 0.72 if any(
        w in recent_tail
        for w in ("try to", "attempt", "hack", "dodge", "strike", "sneak", "pick the lock", "convince", "cast", "leap", "disarm")
    ) else 0.18
    action_diff = 3.5 if is_risky >= 0.5 else 2.0

    aff_delta = 0
    if any(w in recent_tail for w in ("thank", "love", "smile", "hug", "help", "care", "beautiful", "clever", "protect", "gentle", "sweet")):
        aff_delta = 1
        if any(w in recent_tail for w in ("deeply", "adore", "marry", "devoted", "my whole heart")):
            aff_delta = 2
    elif any(w in recent_tail for w in ("hate", "idiot", "kill you", "shut up", "ugly", "fool", "useless", "scum", "threat", "disgust")):
        aff_delta = -1
        if any(w in recent_tail for w in ("despise", "betray", "die", "bastard")):
            aff_delta = -2

    gate_mood = 0.70 if any(
        w in recent_tail
        for w in ("blush", "angry", "furious", "tear", "cry", "smile", "laugh", "sigh", "scared", "terrified", "pleased", "tender")
    ) else 0.25
    gate_rel = 0.65 if aff_delta != 0 or any(
        w in recent_tail
        for w in ("trust", "betray", "together", "closer", "step back", "confess", "promise", "secret")
    ) else 0.20

    raw_answers = {
        "next_speaker": {"choice": next_speaker, "probabilities": speaker_probs},
        "continue_chain": {"probability": continue_prob},
        "pacing_directive": {"choice": directive, "probabilities": {directive: 0.7}},
        "scene_tension": {"score": tension},
        "pacing_speed": {"score": 2.0},
        "emotional_tone": {"choice": tone},
        "trigger_image": {"probability": 0.68 if gate_world >= 0.6 else 0.22},
        "gate_world_state": {"probability": gate_world},
        "gate_scene_tone": {"probability": gate_scene_tone},
        "gate_character_state": {"probability": gate_char},
        "gate_character_mood": {"probability": gate_mood},
        "gate_relationship_dynamic": {"probability": gate_rel},
        "gate_inventory_or_items": {"probability": gate_items},
        "gate_durable_memory": {"probability": gate_memory},
        "gate_lore_discovery": {"probability": gate_lore},
        "gate_character_outfit": {"probability": gate_outfit},
        "gate_current_activity": {"probability": gate_activity},
        "gate_physical_condition": {"probability": gate_condition},
        "gate_world_clock": {"probability": gate_clock},
        "gate_location_or_scene": {"probability": gate_location},
        "gate_weather_environment": {"probability": gate_weather},
        "gate_character_skills": {"probability": gate_char_skills},
        "gate_user_skills": {"probability": gate_user_skills},
        "gate_quests_or_goals": {"probability": gate_quests},
        "gate_social_status": {"probability": gate_social},
        "is_risky_action": {"probability": is_risky},
        "action_difficulty": {"score": action_diff},
        "is_complete": {"probability": 0.5},
    }
    return parse_director_result(
        raw_answers,
        engine_used="heuristic",
        model_id="heuristic_rules",
        latency_ms=latency_ms,
        allow_image_generation=allow_image_generation,
        state_snapshot=state_snapshot,
        context_text=context_text,
    )
