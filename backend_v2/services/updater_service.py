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
)
from infrastructure.logging import get_logger
from services.chat_utils import insert_world_state_marker
from services.decision_schema import UPDATER_GATE_KEYS, DirectorDecisionResult
from services.llm_config import model_for_kind
from services.memory_extraction import create_memories_from_extraction

logger = get_logger("updater_service")


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
            '  "story_time": "updated time/weather if changed, else null"'
        )
    if "gate_character_state" in gates:
        schema_lines.append(
            f'  "character_mood": "concise current mood of {character_name} (e.g. \'Playful and curious\')",\n'
            f'  "current_activity": "what {character_name} is currently doing",\n'
            f'  "character_outfit": "current clothing/attire of {character_name} if known or changed, else null",\n'
            f'  "relationship_status": "current dynamic with {user_name} (e.g. \'Warming up — playful banter\')",\n'
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

    # 1. World State (location & time)
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
            if matched_loc is not None:
                chat.location_id = matched_loc.id
                world_updates["location_id"] = matched_loc.id

    new_time = deltas.get("story_time")
    if isinstance(new_time, str) and new_time.strip() and new_time.strip().lower() != "null":
        time_clean = new_time.strip()
        if time_clean != chat.story_time:
            chat.story_time = time_clean
            world_updates["time"] = time_clean

    # 2. Character & Scene State Snapshot
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
