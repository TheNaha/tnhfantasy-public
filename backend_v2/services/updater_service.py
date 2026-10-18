"""Statekeeper ("Updater") Service — gated background World Vault state extractor.

Runs asynchronously after a turn ONLY when at least one of the System 1
Director's 5 `gate_*` probabilities (`gate_world_state`, `gate_character_state`,
`gate_inventory_or_items`, `gate_durable_memory`, `gate_lore_discovery`) crosses
threshold (`>= 0.55`), or when manually triggered from the UI.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlmodel import Session, select

from core.entities import (
    Character,
    Chat,
    Location,
    LorebookEntry,
    Message,
    MessageRole,
    Scenario,
    WorldEdge,
)
from infrastructure.logging import get_logger
from services.chat_utils import insert_world_state_marker
from services.decision_schema import UPDATER_GATE_KEYS, DirectorDecisionResult
from services.llm_config import model_for_kind
from services.memory_extraction import create_memories_from_extraction

logger = get_logger("updater_service")


def _extract_skills_from_text(text: Optional[str]) -> List[str]:
    """Extract RPG/roleplay skill tags from character or persona text."""
    if not text:
        return []
    t_low = text.lower()
    skills: List[str] = []
    skill_cues = (
        ("hack", "Netrunning / Hacking"),
        ("netrun", "Netrunning"),
        ("magic", "Arcane Magic"),
        ("spell", "Spellcasting"),
        ("pyroman", "Pyromancy"),
        ("sword", "Swordplay"),
        ("blade", "Blade Combat"),
        ("archery", "Archery"),
        ("bow", "Marksmanship"),
        ("sniper", "Precision Marksmanship"),
        ("stealth", "Stealth & Infiltration"),
        ("infiltrat", "Infiltration"),
        ("heal", "Healing Arts"),
        ("medic", "Field Medicine"),
        ("alchem", "Alchemy"),
        ("detective", "Investigation & Deduction"),
        ("engineer", "Engineering & Tech"),
        ("pilot", "Piloting"),
        ("bard", "Music & Performance"),
        ("diploma", "Diplomacy & Persuasion"),
        ("tactic", "Tactical Command"),
        ("guard", "Tactical Defense"),
    )
    for cue, label in skill_cues:
        if cue in t_low and label not in skills:
            skills.append(label)
    return skills[:6]


def _infer_outfit_from_text(*texts: Optional[str]) -> Optional[str]:
    combined = "\n".join(filter(None, texts))
    if not combined:
        return None
    m = re.search(
        r"(?:wearing|dressed in|clad in|wears|adjusts\s+(?:her|his|their))\s+([^.,;!\n*\"“”]{4,65})",
        combined,
        flags=re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    return None


def _infer_mood_from_text(*texts: Optional[str]) -> Optional[str]:
    combined = "\n".join(filter(None, texts)).lower()
    if not combined:
        return None
    if any(w in combined[:700] for w in ("glare", "scowl", "furious", "cold", "hostile", "suspicious", "guarded")):
        return "Guarded & watchful"
    if any(w in combined[:700] for w in ("smile", "grin", "warm", "welcome", "cheerful", "laugh")):
        return "Warm & welcoming"
    if any(w in combined[:700] for w in ("blush", "nervous", "shy", "fidget", "hesitate")):
        return "Flustered & hesitant"
    if any(w in combined[:700] for w in ("sigh", "sad", "tears", "lonely", "weary")):
        return "Melancholic & weary"
    return "Attentive & curious"


def _infer_activity_from_text(*texts: Optional[str]) -> Optional[str]:
    for t in texts:
        if not t:
            continue
        action_match = re.search(r"\*([^*]{8,95})\*", t)
        if action_match:
            return action_match.group(1).strip()[:85]
    return None


def _infer_location_from_text(*texts: Optional[str]) -> Optional[str]:
    combined = "\n".join(filter(None, texts))
    if not combined:
        return None
    patterns = [
        r"\b(?:inside|into|at|within|beneath|atop)\s+the\s+([A-Z][A-Za-z0-9\s\-']{3,45}?)(?=[.,;!\n*\"“”]|\s+(?:at|as|where|when|while)\b)",
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b",
    ]
    m = re.search(patterns[0], combined)
    if m:
        return m.group(1).strip()
    return None


def _infer_time_from_text(*texts: Optional[str]) -> Optional[str]:
    combined = "\n".join(filter(None, texts))
    if not combined:
        return None
    m = re.search(
        r"\b(Midnight|Dawn|Dusk|Twilight|Sunset|Sunrise|Morning|Afternoon|Evening|Late Night|Starlight Dusk|High Noon)\b",
        combined,
        flags=re.IGNORECASE,
    )
    if m:
        return m.group(1).title()
    return None


def _infer_relationship_from_text(*texts: Optional[str]) -> Optional[str]:
    combined = "\n".join(filter(None, texts)).lower()
    if not combined:
        return None
    if any(w in combined for w in ("enemy", "rival", "captive", "nemesis")):
        return "Tense rivals / adversaries"
    if any(w in combined for w in ("bodyguard", "protector", "knight", "companion")):
        return "Sworn companion / ally"
    if any(w in combined for w in ("childhood friend", "best friend", "old friend", "partner")):
        return "Close companions"
    if any(w in combined for w in ("wife", "husband", "lover", "girlfriend", "boyfriend", "fiance")):
        return "Romantic partners"
    if any(w in combined for w in ("master", "mentor", "commander", "employer", "boss")):
        return "Professional / hierarchical bond"
    return None


def seed_initial_state_snapshot(
    *,
    character: Optional[Character] = None,
    scenario: Optional[Scenario] = None,
    persona: Optional[Any] = None,
    first_mes: Optional[str] = None,
    override_greeting: Optional[str] = None,
    persona_name: Optional[str] = None,
    persona_description: Optional[str] = None,
    story_location: Optional[str] = None,
    story_time: Optional[str] = None,
    additional_characters: Optional[List[Character]] = None,
    existing_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a rich Turn-0 Statekeeper snapshot from character/scenario metadata & opening prose."""
    snap: Dict[str, Any] = dict(existing_snapshot or {})
    user_label = (persona_name or (getattr(persona, "name", None) if persona else None) or "User").strip() or "User"
    effective_persona_desc = persona_description or (getattr(persona, "description", None) if persona else None)
    effective_greeting = override_greeting or first_mes or (character.first_mes if character else None)

    # Check if card_metadata carries pre-extracted TNH onboarding blueprint data
    card_meta = (character.card_metadata or {}) if character else {}
    tnh_ext = (
        card_meta.get("data", {}).get("extensions", {}).get("tnh_onboarding")
        or card_meta.get("tnh_onboarding")
        or {}
    )
    if isinstance(tnh_ext, dict):
        for k in (
            "character_mood",
            "current_activity",
            "character_outfit",
            "relationship_status",
            "relationships",
            "character_skills",
            "user_skills",
            "wardrobe",
            "inventory",
            "world_clock",
        ):
            if k not in snap and tnh_ext.get(k):
                snap[k] = tnh_ext[k]

    scenario_text = (
        (getattr(scenario, "description", None) or getattr(scenario, "prompt_template", None))
        if scenario
        else (character.scenario if character else None)
    )
    prose = "\n".join(
        filter(
            None,
            [
                effective_greeting,
                scenario_text,
                character.description if character else None,
                character.personality if character else None,
            ],
        )
    )

    # 1. Outfit extraction from visual_tags or prose
    if not snap.get("character_outfit"):
        outfit_keywords = (
            "armor", "cloak", "dress", "robe", "jacket", "coat", "uniform", "suit",
            "hoodie", "kimono", "tunic", "gown", "leather", "shirt", "skirt", "cape",
        )
        visual_tags = list((character.visual_tags if character else None) or [])
        outfit_tags = [
            t for t in visual_tags
            if any(kw in t.lower() for kw in outfit_keywords)
        ]
        if outfit_tags:
            snap["character_outfit"] = ", ".join(outfit_tags[:4])
        else:
            inferred_outfit = _infer_outfit_from_text(prose)
            if inferred_outfit:
                snap["character_outfit"] = inferred_outfit
            elif character:
                snap["character_outfit"] = f"{character.name}'s signature attire"

    # 2. Wardrobe presets
    if not isinstance(snap.get("wardrobe"), list) or not snap.get("wardrobe"):
        default_outfit = snap.get("character_outfit") or "Signature attire"
        snap["wardrobe"] = [
            {"name": "Signature Attire", "outfit": default_outfit, "visual_tags": ", ".join((character.visual_tags or [])[:4]) if character else ""},
            {"name": "Casual / Rest", "outfit": f"Relaxed off-duty attire for {character.name if character else 'character'}", "visual_tags": "casual clothes, relaxed"},
        ]

    # 3. Mood extraction
    if not snap.get("character_mood"):
        snap["character_mood"] = _infer_mood_from_text(effective_greeting, character.personality if character else None, prose) or "Attentive & curious"

    # 4. Current activity extraction from opening greeting
    if not snap.get("current_activity"):
        inferred_act = _infer_activity_from_text(effective_greeting, scenario_text)
        if inferred_act:
            snap["current_activity"] = inferred_act
        elif story_location or (character and character.default_location):
            loc_str = story_location or character.default_location
            snap["current_activity"] = f"Present at {loc_str}"
        else:
            snap["current_activity"] = "Engaging in conversation"

    # 5. Multi-target Relationships & primary relationship_status
    if not snap.get("relationship_status"):
        snap["relationship_status"] = _infer_relationship_from_text(prose) or f"New encounter with {user_label}"

    if not isinstance(snap.get("relationships"), list) or not snap.get("relationships"):
        rels: List[Dict[str, Any]] = [
            {
                "target_name": user_label,
                "target_type": "user",
                "target_id": None,
                "status": snap["relationship_status"],
                "affinity": "neutral",
            }
        ]
        for add_char in additional_characters or []:
            if add_char and add_char.name:
                rels.append(
                    {
                        "target_name": add_char.name,
                        "target_type": "character",
                        "target_id": add_char.id,
                        "status": "Scene companion",
                        "affinity": "neutral",
                    }
                )
        snap["relationships"] = rels

    # 6. Character & User Skillsets
    if not isinstance(snap.get("character_skills"), list) or not snap.get("character_skills"):
        skills = _extract_skills_from_text(prose)
        snap["character_skills"] = skills or ["Observation", "Composure"]

    if not isinstance(snap.get("user_skills"), list) or not snap.get("user_skills"):
        u_skills = _extract_skills_from_text(effective_persona_desc or scenario_text)
        snap["user_skills"] = u_skills or ["Situational Awareness", "Resolve"]

    # 7. Inventory
    if not isinstance(snap.get("inventory"), list):
        snap["inventory"] = []

    # 8. Fate / Skill check settings (toggleable, default off with auto difficulty/outcome)
    snap.setdefault("fate_check_enabled", False)
    snap.setdefault("fate_difficulty", "auto")
    snap.setdefault("fate_outcome_override", "auto")

    # 9. Cohesive World Clock & Chronology Log
    loc_label = story_location or (character.default_location if character else None) or "Starting Scene"
    time_label = story_time or (character.default_time if character else None) or "Day 1 · Evening"
    if not isinstance(snap.get("world_clock"), dict):
        snap["world_clock"] = {
            "day": 1,
            "time_of_day": time_label,
            "location": loc_label,
            "chronology_log": [
                {
                    "day": 1,
                    "time": time_label,
                    "location": loc_label,
                    "event": f"Scene begins with {character.name if character else 'the cast'} at {loc_label}.",
                }
            ],
        }

    return snap


def record_director_decision(
    session: Session,
    chat_id: str,
    decision: DirectorDecisionResult,
) -> Dict[str, Any]:
    """Immediately persist the System 1 Director's instantaneous telemetry on `Chat.state_snapshot`."""
    chat = session.get(Chat, chat_id)
    if not chat:
        return {}

    now_iso = datetime.now(timezone.utc).isoformat()
    snapshot = dict(chat.state_snapshot or {})
    snapshot["scene_tension"] = decision.scene_tension
    snapshot["emotional_tone"] = decision.emotional_tone
    snapshot["character_expression"] = decision.character_expression
    snapshot["pacing_directive"] = decision.pacing_directive
    snapshot["pacing_speed"] = decision.pacing_speed
    snapshot["is_risky_action_probability"] = decision.is_risky_action_probability
    snapshot["action_difficulty"] = decision.action_difficulty
    snapshot["last_fate_outcome"] = decision.fate_outcome
    snapshot["last_fate_directive"] = decision.fate_directive
    snapshot["matched_skills"] = decision.matched_skills
    # Calculate real-time affinity delta from System 1 Director
    aff_delta = int(getattr(decision, "affinity_delta", 0))
    curr_aff = int(snapshot.get("character_affinity", 50))
    new_aff = max(0, min(100, curr_aff + aff_delta))
    snapshot["character_affinity"] = new_aff
    snapshot["last_affinity_delta"] = aff_delta
    snapshot["character_mood"] = getattr(decision, "character_mood", None) or snapshot.get("character_mood", "curious_attentive")
    snapshot["last_director_decision"] = decision.to_dict()
    snapshot["director_updated_at"] = now_iso

    chat.state_snapshot = snapshot
    chat.updated_at = datetime.now(timezone.utc)
    session.add(chat)
    session.commit()
    return snapshot


def build_state_updater_prompt(
    *,
    character_name: str,
    user_name: str,
    current_location: Optional[str],
    current_time: Optional[str],
    state_snapshot: Dict[str, Any],
    recent_lines: List[str],
    triggered_gates: List[str],
) -> str:
    """Build a focused JSON-only delta extraction prompt for the `util` model."""
    gates = set(triggered_gates or UPDATER_GATE_KEYS)
    schema_lines: List[str] = []

    if "gate_world_state" in gates:
        schema_lines.append(
            '  "story_location": "updated location name if changed, else null",\n'
            '  "story_time": "updated time/weather if changed, else null",\n'
            '  "clock_day_delta": "integer days elapsed (0 if same day, 1 if next day, etc.)",\n'
            '  "chronology_event": "1 concise sentence logging any canon timeline milestone or location/time transition, else null"'
        )
    if "gate_character_state" in gates:
        schema_lines.append(
            f'  "character_mood": "concise current mood of {character_name} (e.g. \'Playful and curious\')",\n'
            f'  "current_activity": "what {character_name} is currently doing",\n'
            f'  "character_outfit": "current clothing/attire of {character_name} if known or changed, else null",\n'
            f'  "relationship_status": "current dynamic with {user_name} (e.g. \'Warming up — playful banter\')",\n'
            '  "relationships_update": [{"target_name": "name of person/character", "target_type": "user|character", "status": "updated dynamic", "affinity": 50}],\n'
            '  "character_skills_add": ["any newly demonstrated skill or ability of the character"],\n'
            '  "user_skills_add": ["any newly demonstrated skill or ability of the player/user"],\n'
            '  "scene_summary": "1-2 sentence factual summary of the current scene state"'
        )
    if "gate_inventory_or_items" in gates:
        schema_lines.append(
            '  "inventory_add": ["newly acquired/held item names"],\n'
            '  "inventory_remove": ["consumed/dropped/given-away item names"]'
        )
    if "gate_durable_memory" in gates:
        schema_lines.append(
            '  "new_memories": ["1-3 concise single-sentence durable facts worth remembering long-term"]'
        )
    if "gate_lore_discovery" in gates:
        schema_lines.append(
            '  "new_lore": [{"keys": ["keyword1", "keyword2"], "category": "location|faction|item|lore", "content": "1-2 sentence factual world-building entry"}]'
        )

    schema_block = "{\n" + ",\n".join(schema_lines) + "\n}"
    current_state_summary = {
        "story_location": current_location,
        "story_time": current_time,
        "character_mood": state_snapshot.get("character_mood"),
        "current_activity": state_snapshot.get("current_activity"),
        "character_outfit": state_snapshot.get("character_outfit"),
        "relationship_status": state_snapshot.get("relationship_status"),
        "relationships": state_snapshot.get("relationships") or [],
        "character_skills": state_snapshot.get("character_skills") or [],
        "user_skills": state_snapshot.get("user_skills") or [],
        "inventory": state_snapshot.get("inventory") or [],
        "scene_summary": state_snapshot.get("scene_summary"),
    }

    return (
        "You are the World Vault Statekeeper (Updater). Read the current state and the recent "
        "conversation transcript, then extract ONLY factual updates that occurred.\n"
        "Respond with ONLY a valid JSON object matching this exact schema (no markdown fences, no commentary):\n"
        f"{schema_block}\n\n"
        f"Current State:\n{json.dumps(current_state_summary, ensure_ascii=False)}\n\n"
        "Recent Conversation:\n"
        + "\n".join(recent_lines)
    )


async def enqueue_state_updater_if_needed(
    session: Session,
    *,
    chat_id: str,
    character_id: Optional[str],
    decision: DirectorDecisionResult,
    job_service: Any,
    force: bool = False,
) -> Optional[str]:
    """Enqueue a background `state_updater` LLM job on the `util` role if gates fired."""
    if not force and not decision.should_run_updater:
        return None

    chat = session.get(Chat, chat_id)
    if not chat:
        return None

    character = session.get(Character, character_id) if character_id else None
    char_name = character.name if character else "Character"
    user_name = chat.persona_name or "User"

    recent_msgs = list(
        session.exec(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.desc())
            .limit(10)
        ).all()
    )
    if not recent_msgs:
        return None

    recent_lines: List[str] = []
    for msg in reversed(recent_msgs):
        if msg.role == MessageRole.SYSTEM:
            continue
        speaker = user_name if msg.role == MessageRole.USER else char_name
        content = (msg.content or "").strip()
        if content:
            recent_lines.append(f"{speaker}: {content}")

    if not recent_lines:
        return None

    triggered = list(decision.triggered_gates) if decision.triggered_gates else list(UPDATER_GATE_KEYS)
    prompt = build_state_updater_prompt(
        character_name=char_name,
        user_name=user_name,
        current_location=chat.story_location,
        current_time=chat.story_time,
        state_snapshot=dict(chat.state_snapshot or {}),
        recent_lines=recent_lines,
        triggered_gates=triggered,
    )

    from services.llm_workflow import build_llm_workflow

    workflow, metadata = build_llm_workflow(
        messages=[
            {
                "role": "system",
                "content": "You are a precise JSON-only roleplay state extractor. Output valid JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        type_="state_updater",
        chat_id=chat_id,
        character_id=character_id,
        workspace="chat",
        source="state_updater",
        model=model_for_kind("state_updater", None, session),
        temperature=0.2,
        max_output_tokens=600,
        background=True,
        extra_metadata={"triggered_gates": triggered},
    )

    try:
        job = await job_service.create_job(task_type="llm", workflow=workflow, metadata=metadata)
        from services.job_queue import queue_manager

        await queue_manager.enqueue(job.id, task_type="llm")
        logger.info(
            "state_updater_enqueued",
            chat_id=chat_id,
            job_id=job.id,
            triggered_gates=triggered,
        )
        return job.id
    except Exception as exc:
        logger.warning("state_updater_enqueue_failed", chat_id=chat_id, error=str(exc))
        return None


def parse_updater_json(raw_text: str) -> Dict[str, Any]:
    """Parse JSON object from the Statekeeper LLM completion."""
    if not raw_text:
        return {}
    cleaned = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1)
    else:
        brace_start = cleaned.find("{")
        brace_end = cleaned.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            cleaned = cleaned[brace_start : brace_end + 1]
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        logger.warning("state_updater_json_parse_failed", preview=raw_text[:120])
        return {}


def apply_updater_result(
    session: Session,
    *,
    chat_id: str,
    character_id: Optional[str],
    raw_text: str,
    triggered_gates: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Apply parsed Statekeeper JSON deltas to `Chat`, `CharacterMemory`, and `LorebookEntry`."""
    deltas = parse_updater_json(raw_text)
    if not deltas:
        return {"applied": False, "reason": "empty_or_invalid_json"}

    chat = session.get(Chat, chat_id)
    if not chat:
        return {"applied": False, "reason": "chat_not_found"}

    now = datetime.now(timezone.utc)
    snapshot = dict(chat.state_snapshot or {})
    world_updates: Dict[str, Any] = {}

    # 1. World State (location & time) + Auto-Materialize Location in World Vault
    new_loc = deltas.get("story_location")
    if isinstance(new_loc, str) and new_loc.strip() and new_loc.strip().lower() != "null":
        loc_clean = new_loc.strip()
        if loc_clean != chat.story_location:
            chat.story_location = loc_clean
            world_updates["location"] = loc_clean
            matched_loc = None
            if chat.world_id:
                matched_loc = session.exec(
                    select(Location)
                    .where(
                        Location.world_id == chat.world_id,
                        func.lower(Location.name) == loc_clean.lower(),
                    )
                    .limit(1)
                ).first()
            if matched_loc is None:
                matched_loc = session.exec(
                    select(Location)
                    .where(func.lower(Location.name) == loc_clean.lower())
                    .limit(1)
                ).first()
            if matched_loc is None and snapshot.get("auto_create_locations", True):
                # Materialize a new Location row in the World Vault automatically
                matched_loc = Location(
                    name=loc_clean,
                    description=deltas.get("scene_summary") or f"Discovered during roleplay in {chat.name}.",
                    atmosphere=deltas.get("story_time") or chat.story_time or "Atmospheric roleplay setting",
                    tags=["auto-discovered"],
                    world_id=chat.world_id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(matched_loc)
                session.flush()
            if matched_loc is not None:
                chat.location_id = matched_loc.id
                world_updates["location_id"] = matched_loc.id

    new_time = deltas.get("story_time")
    if isinstance(new_time, str) and new_time.strip() and new_time.strip().lower() != "null":
        time_clean = new_time.strip()
        if time_clean != chat.story_time:
            chat.story_time = time_clean
            world_updates["time"] = time_clean

    # 1b. Cohesive World Clock & Canon Chronology Log
    clock = dict(snapshot.get("world_clock") or {})
    cur_day = int(clock.get("day") or 1)
    try:
        day_delta = int(deltas.get("clock_day_delta") or 0)
    except (TypeError, ValueError):
        day_delta = 0
    if day_delta > 0:
        cur_day += day_delta
    clock["day"] = max(1, cur_day)
    clock["time_of_day"] = chat.story_time or clock.get("time_of_day") or "Day 1"
    clock["location"] = chat.story_location or clock.get("location") or "Scene"

    chronology_log: List[Dict[str, Any]] = list(clock.get("chronology_log") or [])
    chrono_event = deltas.get("chronology_event")
    if isinstance(chrono_event, str) and chrono_event.strip() and chrono_event.strip().lower() != "null":
        chronology_log.append(
            {
                "day": clock["day"],
                "time": clock["time_of_day"],
                "location": clock["location"],
                "event": chrono_event.strip(),
                "timestamp": now.isoformat(),
            }
        )
    elif world_updates:
        summary_ev = deltas.get("scene_summary") or f"Transitioned to {clock['location']} ({clock['time_of_day']})."
        chronology_log.append(
            {
                "day": clock["day"],
                "time": clock["time_of_day"],
                "location": clock["location"],
                "event": str(summary_ev).strip(),
                "timestamp": now.isoformat(),
            }
        )
    clock["chronology_log"] = chronology_log[-50:]
    snapshot["world_clock"] = clock

    # 2. Character & Scene State Snapshot + Wardrobe Presets
    for field_key in (
        "character_mood",
        "current_activity",
        "character_outfit",
        "relationship_status",
        "scene_summary",
    ):
        val = deltas.get(field_key)
        if isinstance(val, str) and val.strip() and val.strip().lower() != "null":
            snapshot[field_key] = val.strip()

    # Auto-save newly detected outfit into character's wardrobe presets
    new_outfit = snapshot.get("character_outfit")
    if isinstance(new_outfit, str) and new_outfit.strip():
        wardrobe: List[Dict[str, str]] = list(snapshot.get("wardrobe") or [])
        existing_descs = {str(w.get("description", "")).strip().lower() for w in wardrobe if isinstance(w, dict)}
        if new_outfit.strip().lower() not in existing_descs:
            label = f"Outfit #{len(wardrobe) + 1}" if wardrobe else "Default"
            wardrobe.append({"name": label, "description": new_outfit.strip()})
            snapshot["wardrobe"] = wardrobe[:20]

    # 2b. Multi-Target Relationships & WorldEdge Graph Sync
    user_label = (chat.persona_name or "User").strip() or "User"
    current_rels: List[Dict[str, Any]] = list(snapshot.get("relationships") or [])
    rel_by_target: Dict[str, Dict[str, Any]] = {}
    for r in current_rels:
        if isinstance(r, dict) and r.get("target_name"):
            rel_by_target[str(r["target_name"]).strip().lower()] = dict(r)

    # Keep primary user relationship synced if relationship_status changed
    if snapshot.get("relationship_status"):
        u_key = user_label.lower()
        existing_u = rel_by_target.get(u_key) or {
            "target_name": user_label,
            "target_type": "user",
            "target_id": chat.persona_id,
            "affinity": 50,
        }
        existing_u["status"] = snapshot["relationship_status"]
        rel_by_target[u_key] = existing_u

    rels_update = deltas.get("relationships_update")
    if isinstance(rels_update, list):
        for r_up in rels_update:
            if not isinstance(r_up, dict):
                continue
            t_name = str(r_up.get("target_name") or "").strip()
            t_status = str(r_up.get("status") or "").strip()
            if not t_name or not t_status or t_status.lower() == "null":
                continue
            t_key = t_name.lower()
            entry = rel_by_target.get(t_key) or {
                "target_name": t_name,
                "target_type": str(r_up.get("target_type") or ("user" if t_key == user_label.lower() else "character")),
                "target_id": r_up.get("target_id"),
                "affinity": 50,
            }
            entry["status"] = t_status
            if isinstance(r_up.get("affinity"), (int, float)):
                entry["affinity"] = max(0, min(100, int(r_up["affinity"])))
            rel_by_target[t_key] = entry

            # Sync character-to-character or character-to-chat relationship to WorldEdge
            if character_id:
                try:
                    target_char = session.exec(
                        select(Character).where(func.lower(Character.name) == t_key).limit(1)
                    ).first()
                    if target_char and target_char.id != character_id:
                        entry["target_id"] = target_char.id
                        entry["target_type"] = "character"
                        existing_edge = session.exec(
                            select(WorldEdge).where(
                                WorldEdge.source_entity_type == "character",
                                WorldEdge.source_entity_id == character_id,
                                WorldEdge.target_entity_type == "character",
                                WorldEdge.target_entity_id == target_char.id,
                                WorldEdge.relation_type == "relationship",
                            )
                        ).first()
                        if existing_edge:
                            existing_edge.label = t_status[:250]
                            existing_edge.updated_at = now
                            session.add(existing_edge)
                        else:
                            session.add(
                                WorldEdge(
                                    source_entity_type="character",
                                    source_entity_id=character_id,
                                    target_entity_type="character",
                                    target_entity_id=target_char.id,
                                    relation_type="relationship",
                                    label=t_status[:250],
                                    created_at=now,
                                    updated_at=now,
                                )
                            )
                except Exception as exc:
                    logger.debug("state_updater_world_edge_sync_skipped", error=str(exc))

    snapshot["relationships"] = list(rel_by_target.values())

    # 2c. Character & User Skillsets
    for delta_key, snap_key in (
        ("character_skills_add", "character_skills"),
        ("user_skills_add", "user_skills"),
    ):
        existing_skills: List[str] = [str(s).strip() for s in (snapshot.get(snap_key) or []) if str(s).strip()]
        seen_lower = {s.lower() for s in existing_skills}
        added = deltas.get(delta_key)
        if isinstance(added, list):
            for s in added:
                if isinstance(s, str) and s.strip() and s.strip().lower() not in seen_lower:
                    existing_skills.append(s.strip())
                    seen_lower.add(s.strip().lower())
        snapshot[snap_key] = existing_skills

    # 3. Inventory / Items
    current_inv: List[str] = list(snapshot.get("inventory") or [])
    inv_lower_map = {item.lower(): item for item in current_inv if isinstance(item, str)}

    inv_remove = deltas.get("inventory_remove")
    if isinstance(inv_remove, list):
        for rem in inv_remove:
            if isinstance(rem, str) and rem.strip():
                inv_lower_map.pop(rem.strip().lower(), None)

    inv_add = deltas.get("inventory_add")
    if isinstance(inv_add, list):
        for add in inv_add:
            if isinstance(add, str) and add.strip():
                clean_item = add.strip()
                inv_lower_map[clean_item.lower()] = clean_item

    snapshot["inventory"] = list(inv_lower_map.values())
    snapshot["statekeeper_updated_at"] = now.isoformat()
    snapshot["last_triggered_gates"] = list(triggered_gates or [])

    chat.state_snapshot = snapshot
    chat.updated_at = now
    session.add(chat)
    session.commit()

    if world_updates:
        try:
            insert_world_state_marker(session, chat_id, world_updates)
        except Exception as exc:
            logger.warning("state_updater_world_marker_failed", chat_id=chat_id, error=str(exc))

    # 4. Durable Character Memories
    memories_created = 0
    new_memories = deltas.get("new_memories")
    if character_id and isinstance(new_memories, list):
        clean_memories = [str(m).strip() for m in new_memories if isinstance(m, str) and str(m).strip()]
        if clean_memories:
            try:
                memories_created = create_memories_from_extraction(
                    session, character_id, clean_memories
                )
            except Exception as exc:
                logger.warning("state_updater_memory_creation_failed", chat_id=chat_id, error=str(exc))

    # 5. Lorebook Discovery
    lore_created = 0
    new_lore = deltas.get("new_lore")
    if isinstance(new_lore, list) and new_lore:
        target_lorebook_id = None
        if chat.active_lorebook_ids:
            target_lorebook_id = chat.active_lorebook_ids[0]
        elif character_id:
            char_obj = session.get(Character, character_id)
            if char_obj and char_obj.lorebook_ids:
                target_lorebook_id = char_obj.lorebook_ids[0]

        if target_lorebook_id:
            for item in new_lore[:3]:
                if not isinstance(item, dict):
                    continue
                content = str(item.get("content") or "").strip()
                raw_keys = item.get("keys") or []
                keys = [str(k).strip() for k in raw_keys if str(k).strip()] if isinstance(raw_keys, list) else []
                if not content or not keys:
                    continue
                entry = LorebookEntry(
                    lorebook_id=target_lorebook_id,
                    keys=keys,
                    content=content,
                    category=str(item.get("category") or "lore"),
                    tags=["auto-discovered"],
                    created_at=now,
                    updated_at=now,
                )
                session.add(entry)
                lore_created += 1
            if lore_created:
                session.commit()

    return {
        "applied": True,
        "chat_id": chat_id,
        "world_updates": world_updates,
        "memories_created": memories_created,
        "lore_created": lore_created,
        "state_snapshot": snapshot,
    }
