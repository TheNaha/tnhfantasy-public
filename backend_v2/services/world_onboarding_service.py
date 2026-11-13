"""World Architect & Onboarding Service (`services/world_onboarding_service.py`).

Powers:
1. SillyTavern Card (.png/.json/.charx) or Existing Character -> Full World Blueprint
   (Vision LLM portrait/outfit/backdrop extraction + Util LLM / heuristic world synthesis).
2. Story / PDF / Document (.pdf/.txt/.md/prose) -> Playable World Blueprint
   (Multi-character extraction, locations, lorebook entries, scenarios, and sandbox chapters).
3. World Crossover & Transmigration Studio ("Isekai / Portal Engine")
   (Merging traveler characters into a destination World with crossover physics & Turn-0 state).
4. Commit World Blueprint -> Atomic creation/merging of World, Characters, Locations,
   Lorebooks, Scenarios, Persona, WorldEdges, and optional Turn-0 Chat / Story.
5. Live World Vault & Statekeeper Operations:
   - Commit Chat to World Canon
   - Compile Chat to Story Chapter (Novelizer)
   - Living World Tick (Off-screen NPC autonomy)
   - Reverse Vision ("Image-to-State")
   - Fast-Travel Location Transition
   - 1-Click Inventory Item Visualizer
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlmodel import Session, select

import config as app_config
from core.character_cards import (
    CardParseError,
    lorebook_from_character_book,
    parse_card_file,
)
from core.entities import (
    Chat,
    Character,
    Collection,
    Location,
    Lorebook,
    LorebookEntry,
    Message,
    MessageKind,
    MessageRole,
    Persona,
    Provider,
    Scenario,
    Story,
    StoryChapter,
    World,
    WorldEdge,
)
from core.exceptions import NotFoundError, ValidationError
from infrastructure.logging import get_logger
from services.chat_utils import insert_world_state_marker, substitute_tavern_vars
from services.llm_config import model_for_kind, resolve_default_provider
from services.updater_service import (
    _extract_skills_from_text,
    _infer_activity_from_text,
    _infer_location_from_text,
    _infer_mood_from_text,
    _infer_outfit_from_text,
    _infer_relationship_from_text,
    _infer_time_from_text,
    seed_initial_state_snapshot,
)
from services.world_ownership import link_to_world

logger = get_logger("world_onboarding_service")


def _extract_json_object(raw_text: str) -> Optional[Dict[str, Any]]:
    """Extract a JSON object from an LLM response that may include markdown fences."""
    cleaned = (raw_text or "").strip()
    if not cleaned:
        return None
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = cleaned[start : end + 1]
    try:
        parsed = json.loads(snippet)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


async def _run_llm_completion(
    session: Session,
    *,
    kind: str,
    system_prompt: str,
    user_content: Any,
    max_output_tokens: int,
    temperature: float,
    timeout: float,
) -> tuple[Optional[str], str]:
    """Execute one LLM request and return `(raw_text_or_None, engine_label)`."""
    resolved = resolve_default_provider(session)
    if not resolved:
        return None, "heuristic"
    provider_id, _ = resolved
    provider = session.get(Provider, provider_id)
    if not provider or not provider.enabled:
        return None, "heuristic"

    try:
        from services.engines.engine_factory import get_engine

        engine = get_engine(provider.id, provider)
        if engine is None:
            return None, "heuristic"

        model_id = model_for_kind(kind, None, session)
        workflow = {
            "type": kind,
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        }
        full_text = ""
        async for event in engine.run_inference(workflow, timeout=timeout):
            if not isinstance(event, dict):
                continue
            event_kind = event.get("event")
            if event_kind == "delta":
                if event.get("text"):
                    full_text += str(event["text"])
            elif event_kind == "completed":
                outputs = event.get("outputs") or []
                first = outputs[0] if outputs and isinstance(outputs[0], dict) else {}
                content = first.get("content") or first.get("text")
                if content:
                    full_text = str(content)
            elif event_kind in ("failed", "error"):
                logger.debug(
                    "world_onboarding_llm_error_event",
                    kind=kind,
                    error=event.get("message") or event.get("error"),
                )
                return None, "heuristic"
            elif event_kind == "token" and event.get("text"):
                full_text += str(event["text"])
            elif event.get("status") == "success":
                output = event.get("output") or {}
                if isinstance(output, dict) and output.get("text"):
                    full_text = str(output["text"])
                elif event.get("text"):
                    full_text = str(event["text"])

        cleaned = full_text.strip()
        if cleaned:
            return cleaned, f"llm:{provider_id}:{model_id}"
    except Exception as exc:
        logger.debug("world_onboarding_llm_fallback", kind=kind, error=str(exc))

    return None, "heuristic"


async def _run_llm_json(
    session: Session,
    *,
    kind: str,
    system_prompt: str,
    user_content: Any,
    max_output_tokens: int = 1200,
    temperature: float = 0.2,
    timeout: float = 25.0,
) -> tuple[Optional[Dict[str, Any]], str]:
    """Run a structured JSON request against the active LLM provider for `kind`.

    Returns `(parsed_dict_or_None, engine_label)`. Never raises so callers can
    fall back cleanly to deterministic extraction when no provider is online.
    """
    raw_text, engine_label = await _run_llm_completion(
        session,
        kind=kind,
        system_prompt=system_prompt,
        user_content=user_content,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        timeout=timeout,
    )
    if raw_text is not None:
        parsed = _extract_json_object(raw_text)
        if parsed is not None:
            return parsed, engine_label
    return None, "heuristic"


async def _run_llm_text(
    session: Session,
    *,
    kind: str,
    system_prompt: str,
    user_content: Any,
    max_output_tokens: int = 1200,
    temperature: float = 0.4,
    timeout: float = 25.0,
) -> tuple[Optional[str], str]:
    """Run an LLM request returning raw text against the active LLM provider for `kind`.

    Returns `(text_or_None, engine_label)`. Never raises so callers fall back cleanly.
    """
    return await _run_llm_completion(
        session,
        kind=kind,
        system_prompt=system_prompt,
        user_content=user_content,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        timeout=timeout,
    )


async def _analyze_avatar_with_vision(
    session: Session,
    avatar_bytes: Optional[bytes],
    char_name: str,
    char_description: str,
    use_vision: bool = True,
) -> tuple[Dict[str, Any], bool]:
    """Analyze a character card's embedded portrait via Vision LLM if available."""
    if not avatar_bytes or not use_vision:
        return {}, False

    b64_img = base64.b64encode(avatar_bytes).decode("ascii")
    data_uri = f"data:image/png;base64,{b64_img}"
    blocks = app_config.get_system_prompt_blocks() or {}
    system_prompt = blocks.get("vision_avatar_analysis") or (
        "You are a visual character & world design analyzer. Inspect the character portrait "
        "and return ONLY a valid JSON object with these keys:\n"
        "- visual_tags: array of 8-12 concise Danbooru-style appearance tags (hair color/style, eye color, features, lighting)\n"
        "- outfit_description: concise description of the outfit worn in the image (max 80 chars)\n"
        "- wardrobe_presets: array of 2-3 objects `{\"name\": \"...\", \"outfit\": \"...\", \"visual_tags\": \"...\"}`\n"
        "- inferred_location: backdrop/setting visible in the image (max 60 chars)\n"
        "- inferred_time_of_day: lighting/time of day visible (e.g. 'Neon-lit Midnight', 'Golden Hour')\n"
        "- inferred_mood: facial expression/demeanor (max 40 chars)"
    )
    user_content = [
        {
            "type": "text",
            "text": f"Character Name: {char_name}\nCard context: {(char_description or '')[:500]}",
        },
        {"type": "image_url", "image_url": {"url": data_uri}},
    ]
    parsed, engine_label = await _run_llm_json(
        session,
        kind="vision",
        system_prompt=system_prompt,
        user_content=user_content,
        max_output_tokens=500,
        timeout=20.0,
    )
    if parsed and engine_label != "heuristic":
        return parsed, True
    return {}, False


def _extract_visual_tags_heuristic(text: str, existing_tags: Optional[List[str]] = None) -> List[str]:
    """Extract appearance/visual tags from character description when Vision LLM is offline."""
    tags: List[str] = []
    for t in existing_tags or []:
        t_clean = str(t).strip()
        if t_clean and t_clean not in tags:
            tags.append(t_clean)

    patterns = [
        r"\b((?:silver|golden|blonde|black|crimson|red|blue|white|violet|purple|emerald|amber|pink|brown|dark|long|short|braided|twin-tail)\s+(?:hair|eyes|locks|braids))\b",
        r"\b(elf ears|pointed ears|horns|wings|halo|cybernetic\s+\w+|glowing\s+\w+|heterochromia|glasses|eyepatch|scar|freckles|pale skin|tan skin)\b",
    ]
    for pat in patterns:
        for match in re.finditer(pat, text or "", flags=re.IGNORECASE):
            val = match.group(1).strip().lower()
            if val and val not in [x.lower() for x in tags]:
                tags.append(val)
            if len(tags) >= 12:
                break
    if not tags:
        tags = ["detailed portrait", "expressive eyes", "cinematic lighting"]
    return tags[:12]


def _extract_locations_from_card(
    char_name: str,
    description: str,
    scenario_text: str,
    first_mes: str,
    alternate_greetings: List[str],
    character_book: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Deterministically extract candidate World Vault Locations from card text & greetings."""
    locations: List[Dict[str, Any]] = []
    seen_names: set[str] = set()

    def _add_loc(name: str, desc: str, tags: Optional[List[str]] = None, time_str: Optional[str] = None) -> None:
        clean_name = re.sub(r"^[\s\-•*]+|[\s.,;:!?]+$", "", (name or "").strip())
        if not clean_name or len(clean_name) < 3 or len(clean_name) > 75:
            return
        key = clean_name.lower()
        if key in seen_names:
            return
        seen_names.add(key)
        locations.append(
            {
                "name": clean_name[:75],
                "description": (desc or f"Key setting associated with {char_name}.")[:400],
                "tags": tags or [" atmospheric lighting", "detailed background"],
                "default_time": time_str or "Evening",
                "selected": True,
            }
        )

    primary_loc = _infer_location_from_text(first_mes, scenario_text, description)
    primary_time = _infer_time_from_text(first_mes, scenario_text, description) or "Evening"
    if primary_loc:
        _add_loc(
            primary_loc,
            scenario_text[:280] if scenario_text else f"The primary opening setting where {char_name} is encountered.",
            tags=["primary setting", "cinematic environment"],
            time_str=primary_time,
        )

    for idx, alt in enumerate(alternate_greetings or []):
        alt_loc = _infer_location_from_text(alt)
        alt_time = _infer_time_from_text(alt) or primary_time
        if alt_loc:
            _add_loc(
                alt_loc,
                f"Setting from alternate greeting #{idx + 1}: {alt[:180]}...",
                tags=["alternate scenario setting"],
                time_str=alt_time,
            )

    # Scan character_book entries for place/location keywords
    if isinstance(character_book, dict):
        raw_entries = character_book.get("entries")
        entry_list = list(raw_entries.values()) if isinstance(raw_entries, dict) else (raw_entries if isinstance(raw_entries, list) else [])
        place_Words = ("city", "kingdom", "realm", "district", "tower", "castle", "academy", "station", "sector", "tavern", "sanctuary", "temple", "forest", "ruins", "manor", "palace", "lab", "citadel", "alley", "vault")
        for entry in entry_list[:30]:
            if not isinstance(entry, dict):
                continue
            comment = str(entry.get("comment") or entry.get("name") or "").strip()
            keys = entry.get("keys") or entry.get("key") or []
            first_key = str(keys[0]).strip() if isinstance(keys, list) and keys else ""
            title = comment or first_key
            content = str(entry.get("content") or "").strip()
            combined = f"{title} {content[:120]}".lower()
            if title and any(pw in combined for pw in place_Words):
                _add_loc(title, content[:320], tags=["lorebook location"])

    if not locations:
        _add_loc(
            f"{char_name}'s Domain",
            scenario_text[:280] if scenario_text else f"The primary world setting surrounding {char_name}.",
            tags=["signature setting", "atmospheric lighting"],
            time_str=primary_time,
        )
    return locations[:8]


def _derive_scenario_title(text: str, idx: int, loc: Optional[str] = None) -> str:
    """Derive a punchy, evocative scenario title from greeting text and location."""
    clean = re.sub(r"[*_#\"“”\[\]\(\)]", "", (text or "").strip())
    clean = re.sub(r"!https?://\S+", "", clean).strip()
    first_non_empty = [line.strip() for line in clean.splitlines() if line.strip()]
    first_line = first_non_empty[0] if first_non_empty else ""

    # Check for quotes naming a tavern, forge, institution, etc.
    m_name = re.search(r"['\"‘“]([^'\"’”]{3,35})['\"’”]", text or "")
    if m_name:
        spot = m_name.group(1).strip()
        if loc and spot.lower() in loc.lower():
            return f"At {spot}"
        return f"{spot} Encounter"

    if loc and len(loc) <= 30 and loc.lower() not in ("starting area", "unknown", "domain"):
        if idx == 0:
            return f"Arrival at {loc}"
        return f"Encounter at {loc}"

    words = first_line.split()[:6]
    derived = " ".join(words).rstrip(".,;:-!?—")
    if derived and len(derived) >= 5:
        return derived[:60]
    return f"Scenario #{idx + 1}"


def _build_scenarios_from_greetings(
    char_name: str,
    scenario_text: str,
    first_mes: str,
    alternate_greetings: List[str],
    default_location: str,
    default_time: str,
) -> List[Dict[str, Any]]:
    """Turn `first_mes` + `alternate_greetings` into selectable World Vault Scenario blueprints."""
    scenarios: List[Dict[str, Any]] = []
    if first_mes and first_mes.strip():
        loc = _infer_location_from_text(first_mes, scenario_text) or default_location
        tim = _infer_time_from_text(first_mes, scenario_text) or default_time
        title = _derive_scenario_title(first_mes, 0, loc)
        scenarios.append(
            {
                "id": "scenario_0",
                "title": title[:80] or f"{char_name} — Canonical Opening",
                "description": (scenario_text or first_mes[:240]).strip()[:500],
                "first_mes": first_mes.strip(),
                "location_name": loc,
                "story_time": tim,
                "is_primary": True,
                "selected": True,
            }
        )

    for idx, alt in enumerate(alternate_greetings or []):
        alt_clean = (alt or "").strip()
        if not alt_clean:
            continue
        loc = _infer_location_from_text(alt_clean, scenario_text) or default_location
        tim = _infer_time_from_text(alt_clean) or default_time
        title = _derive_scenario_title(alt_clean, idx + 1, loc)
        scenarios.append(
            {
                "id": f"scenario_{idx + 1}",
                "title": title[:80],
                "description": f"Alternate opening scenario for {char_name}: {alt_clean[:220]}",
                "first_mes": alt_clean,
                "location_name": loc,
                "story_time": tim,
                "is_primary": False,
                "selected": True,
            }
        )
    return scenarios[:30]


def _infer_persona_from_card(
    char_name: str,
    description: str,
    scenario_text: str,
    first_mes: str,
    suggested_persona: Optional[str] = None,
) -> Dict[str, Any]:
    """Infer a suggested User Persona (`{{user}}`) and skillset from the card's opening."""
    combined = "\n".join(filter(None, [suggested_persona, scenario_text, first_mes, description[:600]]))
    role_title = "Protagonist / Companion"
    role_desc = (suggested_persona or "").strip()

    role_patterns = [
        r"\{\{user\}\}\s+is\s+([^\n.!?;]{5,110})",
        r"\byou\s+are\s+(?:a|an|the)\s+([^\n.!?;]{5,90})",
        r"\bas\s+(?:her|his|their)\s+([a-zA-Z\s\-]{4,40}),\s+you\b",
    ]
    if not role_desc:
        for pat in role_patterns:
            m = re.search(pat, combined, flags=re.IGNORECASE)
            if m:
                extracted = m.group(1).strip()
                role_desc = f"Role inferred from {char_name}'s scenario: {extracted}."
                words = extracted.split()[:4]
                if words:
                    role_title = " ".join(w.capitalize() for w in words).strip(",.")
                break

    if not role_desc:
        role_desc = f"The central counterpart interacting with {char_name} in this world."

    user_skills = _extract_skills_from_text(role_desc)
    if not user_skills:
        user_skills = ["Situational Awareness", "Persuasion", "Resolve"]

    return {
        "create": False,
        "name": role_title[:60],
        "description": role_desc[:500],
        "skills": user_skills[:6],
    }


def _build_wardrobe_presets(
    char_name: str,
    default_outfit: str,
    visual_tags: List[str],
    vision_wardrobe: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Build 2-4 named Wardrobe presets for 1-click outfit switching."""
    presets: List[Dict[str, Any]] = []
    seen: set[str] = set()

    if isinstance(vision_wardrobe, list):
        for item in vision_wardrobe:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            outfit = str(item.get("outfit") or "").strip()
            if name and outfit and name.lower() not in seen:
                seen.add(name.lower())
                presets.append(
                    {
                        "name": name[:40],
                        "outfit": outfit[:160],
                        "visual_tags": str(item.get("visual_tags") or ", ".join(visual_tags[:4]))[:160],
                    }
                )

    base_outfit = default_outfit or f"{char_name}'s signature attire"
    if "signature attire" not in seen and "default" not in seen:
        presets.insert(
            0,
            {
                "name": "Signature Attire",
                "outfit": base_outfit,
                "visual_tags": ", ".join(visual_tags[:5]),
            },
        )
    if len(presets) < 3:
        presets.append(
            {
                "name": "Casual / Rest",
                "outfit": f"Relaxed off-duty attire suited to {char_name}'s style",
                "visual_tags": "casual clothes, relaxed posture, soft lighting",
            }
        )
        presets.append(
            {
                "name": "Action / Expedition",
                "outfit": f"Practical travel cloak and reinforced gear for {char_name}",
                "visual_tags": "travel cloak, action pose, dramatic lighting",
            }
        )
    return presets[:5]


def _detect_and_extract_multi_characters(
    primary_name: str,
    description: str,
    personality: str,
    avatar_b64: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Detect cards defining multiple characters (e.g. duo cards like Fuwawa & Mococo)."""
    if not description:
        return None

    char_blocks = list(
        re.finditer(
            r"([A-Za-z0-9\s\-]+)\s*=\s*\{Character\([\"']?([^\"')]+)[\"']?\)(.*?)(?=(?:[A-Za-z0-9\s\-]+\s*=\s*\{Character|\Z))",
            description,
            flags=re.DOTALL | re.IGNORECASE,
        )
    )
    if len(char_blocks) >= 2:
        extracted = []
        for match in char_blocks:
            c_name = match.group(2).strip() or match.group(1).strip()
            c_body = match.group(3).strip()
            app_match = re.search(r"Appearance\(([^)]+)\)", c_body, flags=re.IGNORECASE)
            per_match = re.search(r"Personality\(([^)]+)\)", c_body, flags=re.IGNORECASE)
            vis_tags = []
            if app_match:
                vis_tags = [
                    re.sub(r"[\'\"+]", "", s).strip()
                    for s in app_match.group(1).split("+")
                    if s.strip()
                ]
            extracted.append(
                {
                    "name": c_name,
                    "description": c_body[:1500],
                    "personality": per_match.group(1).strip() if per_match else "",
                    "visual_tags": vis_tags or ["character portrait", "detailed"],
                    "avatar_base64": avatar_b64,
                    "character_skills": ["Coordination", "Agility", "Companion Resolve"],
                    "selected": True,
                }
            )
        return extracted

    return None



async def analyze_card_for_onboarding(
    session: Session,
    *,
    file_bytes: bytes,
    filename: str,
    use_vision: bool = True,
) -> Dict[str, Any]:
    """Parse a SillyTavern card (.png/.json/.charx) and synthesize a rich WorldOnboardingBlueprint."""
    if not file_bytes:
        raise ValidationError("Character card file is empty")

    is_png = file_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    try:
        char_data, avatar_bytes, _archive_members = parse_card_file(file_bytes, filename or "card.png")
    except CardParseError as exc:
        raise ValidationError(str(exc)) from exc

    char_name = str(char_data.get("name") or "").strip()
    if not char_name:
        raise ValidationError("Character card must have a name")

    return await _synthesize_card_blueprint(
        session,
        char_data=char_data,
        avatar_bytes=avatar_bytes,
        source_format="png" if is_png else ("charx" if (filename or "").lower().endswith(".charx") else "json"),
        use_vision=use_vision,
        existing_character_id=None,
    )


async def analyze_existing_character_for_onboarding(
    session: Session,
    *,
    character_id: str,
    use_vision: bool = True,
) -> Dict[str, Any]:
    """Build a WorldOnboardingBlueprint from an already-imported Character in the DB."""
    character = session.get(Character, character_id)
    if not character:
        raise NotFoundError("Character", character_id)

    avatar_bytes: Optional[bytes] = None
    if character.avatar_path and os.path.exists(character.avatar_path):
        try:
            with open(character.avatar_path, "rb") as f:
                avatar_bytes = f.read()
        except OSError:
            avatar_bytes = None

    char_data = character.model_dump()
    if character.embedded_lorebook_id:
        book = session.get(Lorebook, character.embedded_lorebook_id)
        if book:
            entries = session.exec(
                select(LorebookEntry).where(LorebookEntry.lorebook_id == book.id)
            ).all()
            char_data["character_book"] = {
                "name": book.name,
                "description": book.description,
                "entries": [
                    {
                        "keys": e.keys,
                        "content": e.content,
                        "enabled": e.enabled,
                        "constant": e.constant,
                        "comment": e.insertion_order,
                    }
                    for e in entries
                ],
            }

    return await _synthesize_card_blueprint(
        session,
        char_data=char_data,
        avatar_bytes=avatar_bytes,
        source_format="existing_character",
        use_vision=use_vision,
        existing_character_id=character.id,
    )


async def _synthesize_card_blueprint(
    session: Session,
    *,
    char_data: Dict[str, Any],
    avatar_bytes: Optional[bytes],
    source_format: str,
    use_vision: bool,
    existing_character_id: Optional[str],
) -> Dict[str, Any]:
    char_name = str(char_data.get("name") or "Character").strip()
    description = str(char_data.get("description") or "").strip()
    personality = str(char_data.get("personality") or "").strip()
    scenario_text = str(char_data.get("scenario") or "").strip()
    first_mes = str(char_data.get("first_mes") or "").strip()
    alternate_greetings = list(char_data.get("alternate_greetings") or [])
    character_book = char_data.get("character_book")

    # 1. Optional Vision LLM pass on embedded avatar portrait
    vision_data, vision_used = await _analyze_avatar_with_vision(
        session,
        avatar_bytes=avatar_bytes,
        char_name=char_name,
        char_description=description,
        use_vision=use_vision,
    )

    # 2. Optional Util LLM pass for World & Statekeeper blueprint enrichment
    blocks = app_config.get_system_prompt_blocks() or {}
    llm_system = blocks.get("world_onboarding") or (
        "You are the World Architect for an AI Fantasy & Roleplay Engine. "
        "Given a character card's text, synthesize a cohesive World Blueprint as a single JSON object:\n"
        "{\n"
        '  "world_name": "Evocative name for the world/setting",\n'
        '  "world_description": "2-3 sentence overview of the world, atmosphere, and core conflict",\n'
        '  "default_location": "Specific starting location name",\n'
        '  "default_time": "Starting time of day / era",\n'
        '  "character_mood": "Initial emotional state",\n'
        '  "current_activity": "What the character is doing at Turn 0",\n'
        '  "character_outfit": "Detailed current outfit description",\n'
        '  "relationship_status": "Initial stance toward {{user}}",\n'
        '  "character_skills": ["Skill 1", "Skill 2", "Skill 3", "Skill 4"],\n'
        '  "user_skills": ["User Skill 1", "User Skill 2", "User Skill 3"],\n'
        '  "inventory": ["Item 1", "Item 2"],\n'
        '  "secondary_npcs": [{"name": "...", "role": "...", "relationship_status": "...", "affinity": "neutral"}],\n'
        '  "extra_locations": [{"name": "...", "description": "...", "tags": ["tag1", "tag2"], "default_time": "Night"}]\n'
        "}\n"
        "Return valid JSON only."
    )
    llm_user = (
        f"Character Name: {char_name}\n"
        f"Description: {description[:1500]}\n"
        f"Personality: {personality[:600]}\n"
        f"Scenario: {scenario_text[:800]}\n"
        f"Opening Greeting: {first_mes[:1000]}\n"
        f"Vision Analysis: {json.dumps(vision_data) if vision_data else 'N/A'}"
    )
    llm_blueprint, engine_used = await _run_llm_json(
        session,
        kind="world_onboarding",
        system_prompt=llm_system,
        user_content=llm_user,
        max_output_tokens=900,
    )
    llm_bp = llm_blueprint or {}

    # 3. Combine Vision + LLM + Heuristic fallbacks
    visual_tags = (
        vision_data.get("visual_tags")
        if isinstance(vision_data.get("visual_tags"), list) and vision_data.get("visual_tags")
        else _extract_visual_tags_heuristic(description, char_data.get("visual_tags"))
    )
    default_location = (
        str(llm_bp.get("default_location") or "").strip()
        or str(vision_data.get("inferred_location") or "").strip()
        or str(char_data.get("default_location") or "").strip()
        or _infer_location_from_text(first_mes, scenario_text, description)
        or f"{char_name}'s Sanctum"
    )
    default_time = (
        str(llm_bp.get("default_time") or "").strip()
        or str(vision_data.get("inferred_time_of_day") or "").strip()
        or str(char_data.get("default_time") or "").strip()
        or _infer_time_from_text(first_mes, scenario_text, description)
        or "Evening"
    )
    outfit = (
        str(vision_data.get("outfit_description") or "").strip()
        or str(llm_bp.get("character_outfit") or "").strip()
        or _infer_outfit_from_text(description, first_mes)
        or f"{char_name}'s signature attire"
    )
    mood = (
        str(llm_bp.get("character_mood") or "").strip()
        or str(vision_data.get("inferred_mood") or "").strip()
        or _infer_mood_from_text(first_mes, personality, description)
        or "Attentive and in-character"
    )
    activity = (
        str(llm_bp.get("current_activity") or "").strip()
        or _infer_activity_from_text(first_mes, scenario_text)
        or f"Engaging with {{{{user}}}} in {default_location}"
    )
    rel_status = (
        str(llm_bp.get("relationship_status") or "").strip()
        or _infer_relationship_from_text(scenario_text, description, first_mes)
        or "New acquaintance"
    )

    char_skills = (
        [str(s).strip() for s in (llm_bp.get("character_skills") or []) if str(s).strip()]
        or _extract_skills_from_text(f"{description}\n{personality}\n{scenario_text}")
        or ["Observation", "Composure", "Tactical Intuition"]
    )
    persona_bp = _infer_persona_from_card(
        char_name,
        description,
        scenario_text,
        first_mes,
        char_data.get("suggested_persona"),
    )
    if isinstance(llm_bp.get("user_skills"), list) and llm_bp.get("user_skills"):
        persona_bp["skills"] = [str(s).strip() for s in llm_bp["user_skills"] if str(s).strip()][:8]

    wardrobe = _build_wardrobe_presets(
        char_name,
        outfit,
        visual_tags,
        vision_data.get("wardrobe_presets") if isinstance(vision_data.get("wardrobe_presets"), list) else None,
    )

    locations = _extract_locations_from_card(
        char_name=char_name,
        description=description,
        scenario_text=scenario_text,
        first_mes=first_mes,
        alternate_greetings=alternate_greetings,
        character_book=character_book,
    )
    if isinstance(llm_bp.get("extra_locations"), list):
        existing_loc_names = {loc["name"].lower() for loc in locations}
        for eloc in llm_bp["extra_locations"]:
            if isinstance(eloc, dict) and eloc.get("name"):
                ename = str(eloc["name"]).strip()
                if ename.lower() not in existing_loc_names:
                    existing_loc_names.add(ename.lower())
                    locations.append(
                        {
                            "name": ename[:75],
                            "description": str(eloc.get("description") or f"Region in {char_name}'s world.")[:400],
                            "tags": eloc.get("tags") if isinstance(eloc.get("tags"), list) else ["world location"],
                            "default_time": str(eloc.get("default_time") or default_time),
                            "selected": True,
                        }
                    )

    scenarios = _build_scenarios_from_greetings(
        char_name=char_name,
        scenario_text=scenario_text,
        first_mes=first_mes,
        alternate_greetings=alternate_greetings,
        default_location=default_location,
        default_time=default_time,
    )

    # Relationships (Multi-target: {{user}} + any secondary NPCs)
    relationships: List[Dict[str, Any]] = [
        {
            "target_name": "{{user}}",
            "target_type": "user",
            "status": rel_status,
            "affinity": "neutral",
            "notes": f"Opening dynamic in {default_location}",
        }
    ]
    if isinstance(llm_bp.get("secondary_npcs"), list):
        for npc in llm_bp["secondary_npcs"][:5]:
            if isinstance(npc, dict) and npc.get("name"):
                relationships.append(
                    {
                        "target_name": str(npc["name"]).strip(),
                        "target_type": "character",
                        "status": str(npc.get("relationship_status") or npc.get("role") or "Known figure").strip(),
                        "affinity": str(npc.get("affinity") or "neutral").strip(),
                        "notes": str(npc.get("role") or "").strip(),
                    }
                )

    inventory = [
        str(i).strip()
        for i in (llm_bp.get("inventory") or [])
        if str(i).strip()
    ]

    world_name = (
        str(llm_bp.get("world_name") or "").strip()
        or (str(character_book.get("name")).strip() if isinstance(character_book, dict) and character_book.get("name") else "")
        or f"Chronicles of {char_name}"
    )
    world_description = (
        str(llm_bp.get("world_description") or "").strip()
        or scenario_text
        or description[:400]
        or f"The world and canonical setting of {char_name}."
    )

    lorebook_bp: Dict[str, Any] = {
        "create": False,
        "name": f"{world_name} Lorebook",
        "description": f"World lore and codex entries for {world_name}.",
        "entries": [],
    }
    mapped_book = lorebook_from_character_book(character_book) if character_book else None
    if mapped_book:
        book_kwargs, entry_kwargs = mapped_book
        lorebook_bp = {
            "create": True,
            "name": book_kwargs.get("name") or f"{char_name} Lorebook",
            "description": book_kwargs.get("description") or f"Embedded lorebook from {char_name}'s card.",
            "entries": [
                {
                    "keys": e.get("keys") or [],
                    "content": e.get("content") or "",
                    "enabled": e.get("enabled", True),
                    "constant": e.get("constant", False),
                }
                for e in entry_kwargs[:50]
            ],
        }

    initial_state_snapshot = {
        "character_mood": mood,
        "current_activity": activity,
        "character_outfit": outfit,
        "wardrobe": wardrobe,
        "relationship_status": rel_status,
        "relationships": relationships,
        "character_skills": char_skills,
        "user_skills": persona_bp["skills"],
        "inventory": inventory,
        "scene_tension": 2.0,
        "emotional_tone": "neutral",
        "character_expression": "neutral",
        "fate_check_enabled": False,
        "fate_difficulty": "auto",
        "fate_outcome_override": "auto",
        "world_clock": {
            "day": 1,
            "time_of_day": default_time,
            "location": default_location,
            "chronology_log": [
                {
                    "day": 1,
                    "time": default_time,
                    "location": default_location,
                    "event": f"Opening scene with {char_name} at {default_location}.",
                }
            ],
        },
    }

    avatar_b64 = base64.b64encode(avatar_bytes).decode("ascii") if avatar_bytes else None

    multi_chars = _detect_and_extract_multi_characters(
        char_name, description, personality, avatar_b64=avatar_b64
    )

    source_card = {
        "name": char_name,
        "card_spec": char_data.get("card_spec") or "chara_card_v2",
        "card_spec_version": char_data.get("card_spec_version") or "2.0",
        "creator": char_data.get("creator") or "",
        "character_version": char_data.get("character_version") or "",
        "description": description,
        "personality": personality,
        "scenario": scenario_text,
        "first_mes": first_mes,
        "alternate_greetings": alternate_greetings,
        "group_greetings": char_data.get("group_greetings") or [],
        "system_prompt": char_data.get("system_prompt") or "",
        "post_history_instructions": char_data.get("post_history_instructions") or "",
        "creator_notes": char_data.get("creator_notes") or "",
        "mes_example": char_data.get("mes_example") or "",
        "tags": char_data.get("tags") or [],
        "character_book": character_book,
        "extensions": char_data.get("extensions") or {},
        "avatar_base64": avatar_b64,
    }

    return {
        "source_type": "character_card",
        "source_card": source_card,
        "world": {
            "mode": "create",
            "existing_world_id": char_data.get("world_id"),
            "name": world_name,
            "description": world_description,
        },
        "characters": [
            {
                "existing_character_id": existing_character_id,
                "name": char_name,
                "description": description,
                "personality": personality,
                "scenario": scenario_text,
                "first_mes": first_mes,
                "alternate_greetings": alternate_greetings,
                "mes_example": char_data.get("mes_example") or "",
                "system_prompt": char_data.get("system_prompt") or "",
                "append_system_prompt": char_data.get("append_system_prompt") or "",
                "creator_notes": char_data.get("creator_notes") or "",
                "suggested_persona": persona_bp["description"],
                "visual_tags": visual_tags,
                "default_location": default_location,
                "default_time": default_time,
                "character_skills": char_skills,
                "wardrobe": wardrobe,
                "avatar_base64": avatar_b64,
                "card_spec": char_data.get("card_spec"),
                "card_spec_version": char_data.get("card_spec_version"),
                "card_metadata": char_data.get("card_metadata"),
                "selected": True,
            }
        ],
        "multi_characters_detected": bool(multi_chars),
        "available_multi_characters": multi_chars or [],
        "locations": locations,
        "scenarios": scenarios,
        "persona": persona_bp,
        "lorebook": lorebook_bp,
        "relationships": relationships,
        "initial_state_snapshot": initial_state_snapshot,
        "analysis_meta": {
            "engine_used": engine_used,
            "vision_used": vision_used,
            "source_format": source_format,
            "greetings_count": 1 + len(alternate_greetings),
            "locations_count": len(locations),
            "lore_entries_count": len(lorebook_bp["entries"]),
            "multi_characters_count": len(multi_chars) if multi_chars else 1,
        },
    }


def _extract_text_from_document_bytes(file_bytes: bytes, filename: str) -> str:
    """Extract plain text from .pdf, .txt, or .md bytes."""
    lower = (filename or "").lower()
    if lower.endswith(".pdf") or file_bytes[:4] == b"%PDF":
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(file_bytes))
            pages_text: List[str] = []
            for idx, page in enumerate(reader.pages[:60]):
                txt = (page.extract_text() or "").strip()
                if txt:
                    pages_text.append(f"--- Page {idx + 1} ---\n{txt}")
            extracted = "\n\n".join(pages_text).strip()
            if not extracted:
                raise ValidationError("PDF contains no extractable text (it may be scanned images only)")
            return extracted
        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError(f"Failed to parse PDF document: {exc}") from exc

    try:
        return file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return file_bytes.decode("latin-1", errors="replace")


def _heuristic_extract_cast_and_world_from_prose(text: str, title: str) -> Dict[str, Any]:
    """Deterministic fallback extractor when ingesting a story/PDF without an active LLM."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 30]
    opening_prose = "\n\n".join(paragraphs[:3])[:1200] if paragraphs else text[:1000]

    # Find capitalized names that appear frequently or near dialogue verbs
    stop_words = {
        "The", "And", "But", "For", "Nor", "Yet", "With", "From", "Into", "Upon", "Over",
        "After", "Before", "While", "When", "Where", "What", "Which", "Who", "Whom", "Whose",
        "This", "That", "These", "Those", "There", "Their", "They", "Them", "Then", "Than",
        "His", "Her", "Hers", "Him", "She", "He", "You", "Your", "Yours", "Our", "Ours",
        "Chapter", "Page", "Part", "Book", "Prologue", "Epilogue", "One", "Two", "Three",
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    }
    name_counts: Dict[str, int] = {}
    for match in re.finditer(r"\b([A-Z][a-z]{2,18})\b", text[:25000]):
        candidate = match.group(1)
        if candidate not in stop_words:
            name_counts[candidate] = name_counts.get(candidate, 0) + 1

    sorted_names = [
        name for name, count in sorted(name_counts.items(), key=lambda kv: (-kv[1], kv[0])) if count >= 2
    ][:4]
    if not sorted_names:
        sorted_names = ["Protagonist", "Deuteragonist"]

    default_loc = _infer_location_from_text(opening_prose, text[:4000]) or f"{title} — Central Setting"
    default_time = _infer_time_from_text(opening_prose, text[:4000]) or "Day 1, Dusk"

    characters: List[Dict[str, Any]] = []
    for idx, cname in enumerate(sorted_names[:3]):
        # Grab sentences mentioning this character
        char_sentences = [
            s.strip()
            for s in re.split(r"(?<=[.!?])\s+", text[:15000])
            if re.search(rf"\b{re.escape(cname)}\b", s)
        ][:5]
        char_desc = " ".join(char_sentences)[:600] or f"Key character from '{title}'."
        skills = _extract_skills_from_text(char_desc) or ["Determination", "Observation", "Adaptability"]
        outfit = _infer_outfit_from_text(char_desc) or f"{cname}'s signature attire"
        characters.append(
            {
                "name": cname,
                "description": char_desc,
                "personality": f"Character from {title}. Expressive, story-driven demeanor.",
                "scenario": f"Adapted from the story '{title}' at {default_loc}.",
                "first_mes": opening_prose if idx == 0 else (char_sentences[0] if char_sentences else opening_prose),
                "alternate_greetings": paragraphs[3:5] if len(paragraphs) > 4 else [],
                "visual_tags": _extract_visual_tags_heuristic(char_desc),
                "default_location": default_loc,
                "default_time": default_time,
                "character_skills": skills,
                "wardrobe": _build_wardrobe_presets(cname, outfit, ["story character", "cinematic lighting"]),
                "selected": True,
            }
        )

    return {
        "world_name": title,
        "world_description": f"Interactive world adapted from '{title}'. {opening_prose[:280]}",
        "default_location": default_loc,
        "default_time": default_time,
        "characters": characters,
        "locations": [
            {
                "name": default_loc,
                "description": opening_prose[:320],
                "tags": ["story setting", "atmospheric"],
                "default_time": default_time,
                "selected": True,
            }
        ],
        "lore_entries": [
            {
                "keys": [title.split()[0].lower(), "chronicle", "premise"],
                "content": opening_prose[:600],
                "enabled": True,
                "constant": True,
            }
        ],
    }


async def analyze_document_for_world(
    session: Session,
    *,
    file_bytes: Optional[bytes] = None,
    filename: Optional[str] = None,
    raw_text: Optional[str] = None,
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """Ingest a story PDF, Markdown/TXT file, or pasted prose and produce a Playable World Blueprint."""
    if file_bytes:
        extracted_text = _extract_text_from_document_bytes(file_bytes, filename or "story.txt")
    elif raw_text and raw_text.strip():
        extracted_text = raw_text.strip()
    else:
        raise ValidationError("Provide either a story file (.pdf, .txt, .md) or raw story text")

    if len(extracted_text.strip()) < 20:
        raise ValidationError("Story text is too short to extract a world blueprint")

    inferred_title = (
        (title or "").strip()
        or (os.path.splitext(os.path.basename(filename))[0].replace("_", " ").replace("-", " ").title() if filename else "")
        or "Imported Story World"
    )

    heuristic_bp = _heuristic_extract_cast_and_world_from_prose(extracted_text, inferred_title)

    llm_system = (
        "You are a Literary World Extractor for an interactive AI Roleplay & Story Engine. "
        "Read the provided story excerpt and extract a playable World Blueprint as valid JSON only:\n"
        "{\n"
        '  "world_name": "Title of the world/setting",\n'
        '  "world_description": "2-3 sentence summary of the setting, tone, and central conflict",\n'
        '  "default_location": "Starting location name",\n'
        '  "default_time": "Starting time/era",\n'
        '  "characters": [\n'
        "    {\n"
        '      "name": "Character Name",\n'
        '      "description": "Rich appearance, backstory, and role",\n'
        '      "personality": "Personality traits and speech style",\n'
        '      "first_mes": "In-character opening scene from the story",\n'
        '      "visual_tags": ["tag1", "tag2", "tag3"],\n'
        '      "character_skills": ["Skill 1", "Skill 2", "Skill 3"],\n'
        '      "outfit": "Current outfit"\n'
        "    }\n"
        "  ],\n"
        '  "locations": [{"name": "...", "description": "...", "tags": ["tag1", "tag2"], "default_time": "..."}],\n'
        '  "lore_entries": [{"keys": ["keyword1", "keyword2"], "content": "World lore / faction / magic rule"}],\n'
        '  "persona": {"name": "Reader / Counterpart Role", "description": "...", "skills": ["Skill 1", "Skill 2"]},\n'
        '  "relationships": [{"target_name": "{{user}}", "target_type": "user", "status": "Companion", "affinity": "friendly"}]\n'
        "}"
    )
    llm_parsed, engine_used = await _run_llm_json(
        session,
        kind="story_ingest",
        system_prompt=llm_system,
        user_content=f"Story Title: {inferred_title}\n\nStory Excerpt:\n{extracted_text[:6000]}",
        max_output_tokens=1400,
        timeout=30.0,
    )

    bp = llm_parsed or heuristic_bp
    world_name = str(bp.get("world_name") or heuristic_bp["world_name"]).strip()
    world_desc = str(bp.get("world_description") or heuristic_bp["world_description"]).strip()
    default_loc = str(bp.get("default_location") or heuristic_bp["default_location"]).strip()
    default_time = str(bp.get("default_time") or heuristic_bp["default_time"]).strip()

    characters: List[Dict[str, Any]] = []
    raw_chars = bp.get("characters") if isinstance(bp.get("characters"), list) and bp.get("characters") else heuristic_bp["characters"]
    for c in raw_chars[:6]:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        cname = str(c["name"]).strip()
        cdesc = str(c.get("description") or f"Character from {world_name}.").strip()
        vtags = c.get("visual_tags") if isinstance(c.get("visual_tags"), list) else _extract_visual_tags_heuristic(cdesc)
        cskills = c.get("character_skills") if isinstance(c.get("character_skills"), list) else ["Storycraft", "Resolve"]
        coutfit = str(c.get("outfit") or _infer_outfit_from_text(cdesc) or f"{cname}'s signature attire").strip()
        characters.append(
            {
                "name": cname,
                "description": cdesc,
                "personality": str(c.get("personality") or "Expressive and grounded in the story world.").strip(),
                "scenario": f"Adapted from {world_name} at {default_loc}.",
                "first_mes": str(c.get("first_mes") or extracted_text[:800]).strip(),
                "alternate_greetings": c.get("alternate_greetings") if isinstance(c.get("alternate_greetings"), list) else [],
                "visual_tags": vtags,
                "default_location": default_loc,
                "default_time": default_time,
                "character_skills": cskills,
                "wardrobe": _build_wardrobe_presets(cname, coutfit, vtags),
                "selected": True,
            }
        )

    if not characters:
        characters = heuristic_bp["characters"]

    primary_char = characters[0]
    locations = bp.get("locations") if isinstance(bp.get("locations"), list) and bp.get("locations") else heuristic_bp["locations"]
    for loc in locations:
        if isinstance(loc, dict):
            loc.setdefault("selected", True)
            loc.setdefault("tags", ["story location"])
            loc.setdefault("default_time", default_time)

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", extracted_text) if len(p.strip()) > 40]
    opening_chunk = "\n\n".join(paragraphs[:3])[:1000] if paragraphs else extracted_text[:800]
    midpoint_chunk = "\n\n".join(paragraphs[len(paragraphs) // 2 : len(paragraphs) // 2 + 2])[:1000] if len(paragraphs) > 4 else ""

    scenarios = [
        {
            "title": f"Chapter 1 Opening: {default_loc}",
            "description": f"Begin at the canonical opening of '{world_name}'.",
            "first_mes": primary_char.get("first_mes") or opening_chunk,
            "location_name": default_loc,
            "story_time": default_time,
            "is_primary": True,
            "selected": True,
        }
    ]
    if midpoint_chunk:
        scenarios.append(
            {
                "title": "Mid-Story Divergence Point",
                "description": f"Enter '{world_name}' at a pivotal mid-story turning point and alter canon.",
                "first_mes": midpoint_chunk,
                "location_name": default_loc,
                "story_time": "Mid-Story Turning Point",
                "is_primary": False,
                "selected": True,
            }
        )

    persona_raw = bp.get("persona") if isinstance(bp.get("persona"), dict) else {}
    persona_bp = {
        "create": False,
        "name": str(persona_raw.get("name") or "Story Traveler").strip(),
        "description": str(persona_raw.get("description") or f"Active participant in the events of {world_name}.").strip(),
        "skills": persona_raw.get("skills") if isinstance(persona_raw.get("skills"), list) else ["Foresight", "Persuasion", "Tactical Adaptability"],
    }

    relationships = bp.get("relationships") if isinstance(bp.get("relationships"), list) and bp.get("relationships") else [
        {
            "target_name": "{{user}}",
            "target_type": "user",
            "status": "Story Counterpart",
            "affinity": "friendly",
            "notes": f"Central bond in {world_name}",
        }
    ]
    for other_char in characters[1:]:
        relationships.append(
            {
                "target_name": other_char["name"],
                "target_type": "character",
                "status": "Fellow Cast Member",
                "affinity": "neutral",
                "notes": f"Co-stars in {world_name}",
            }
        )

    lore_entries = bp.get("lore_entries") if isinstance(bp.get("lore_entries"), list) else heuristic_bp["lore_entries"]
    initial_state_snapshot = {
        "character_mood": "Focused",
        "current_activity": f"Unfolding the opening chapter at {default_loc}",
        "character_outfit": primary_char["wardrobe"][0]["outfit"] if primary_char.get("wardrobe") else f"{primary_char['name']}'s attire",
        "wardrobe": primary_char.get("wardrobe") or [],
        "relationship_status": relationships[0]["status"],
        "relationships": relationships,
        "character_skills": primary_char.get("character_skills") or ["Observation"],
        "user_skills": persona_bp["skills"],
        "inventory": [],
        "scene_tension": 2.2,
        "emotional_tone": "dramatic_intense",
        "character_expression": "neutral",
        "fate_check_enabled": False,
        "fate_difficulty": "auto",
        "fate_outcome_override": "auto",
        "world_clock": {
            "day": 1,
            "time_of_day": default_time,
            "location": default_loc,
            "chronology_log": [
                {
                    "day": 1,
                    "time": default_time,
                    "location": default_loc,
                    "event": f"Story world '{world_name}' initialized at {default_loc}.",
                }
            ],
        },
    }

    return {
        "source_type": "document_story",
        "world": {
            "mode": "create",
            "existing_world_id": None,
            "name": world_name,
            "description": world_desc,
        },
        "characters": characters,
        "locations": locations,
        "scenarios": scenarios,
        "persona": persona_bp,
        "lorebook": {
            "create": True,
            "name": f"{world_name} Codex",
            "description": f"Extracted lore and world rules from '{inferred_title}'.",
            "entries": lore_entries,
        },
        "relationships": relationships,
        "initial_state_snapshot": initial_state_snapshot,
        "story_seed_content": extracted_text[:12000],
        "analysis_meta": {
            "engine_used": engine_used,
            "vision_used": False,
            "source_format": (os.path.splitext(filename or "")[1].lstrip(".") or "text").lower(),
            "characters_count": len(characters),
            "locations_count": len(locations),
            "lore_entries_count": len(lore_entries),
            "extracted_chars": len(extracted_text),
        },
    }


async def extract_scenarios_from_card_data(
    session: Session,
    *,
    char_name: str,
    scenario_text: str = "",
    first_mes: str = "",
    alternate_greetings: Optional[List[str]] = None,
    default_location: str = "Starting Area",
    default_time: str = "Evening",
    use_llm: bool = True,
) -> Dict[str, Any]:
    """Extract and refine Scenarios from first_mes and alternate_greetings."""
    scenarios = _build_scenarios_from_greetings(
        char_name=char_name,
        scenario_text=scenario_text,
        first_mes=first_mes,
        alternate_greetings=alternate_greetings or [],
        default_location=default_location,
        default_time=default_time,
    )
    engine_used = "heuristic"

    if use_llm and scenarios:
        llm_system = (
            "You are a Narrative Scenario Architect for an AI RPG. "
            "Given character greetings, generate a punchy title (max 50 chars), inferred location name, "
            "and 1-2 sentence scenario premise for each greeting. Return valid JSON:\n"
            '{"scenarios": [{"id": "scenario_0", "title": "...", "location_name": "...", "story_time": "...", "description": "..."}]}'
        )
        sample_greetings = [
            {"id": s["id"], "preview": s["first_mes"][:300], "default_loc": s["location_name"]}
            for s in scenarios[:15]
        ]
        parsed, eng = await _run_llm_json(
            session,
            kind="scenario_refine",
            system_prompt=llm_system,
            user_content=f"Character: {char_name}\nContext: {scenario_text[:400]}\nGreetings:\n{json.dumps(sample_greetings)}",
            max_output_tokens=800,
        )
        if parsed and isinstance(parsed.get("scenarios"), list):
            engine_used = eng
            refined_by_id = {str(item.get("id")): item for item in parsed["scenarios"] if isinstance(item, dict)}
            for sc in scenarios:
                ref = refined_by_id.get(sc["id"])
                if ref:
                    if ref.get("title"):
                        sc["title"] = str(ref["title"]).strip()[:80]
                    if ref.get("location_name"):
                        sc["location_name"] = str(ref["location_name"]).strip()[:60]
                    if ref.get("story_time"):
                        sc["story_time"] = str(ref["story_time"]).strip()[:40]
                    if ref.get("description"):
                        sc["description"] = str(ref["description"]).strip()[:400]

    return {
        "scenarios": scenarios,
        "engine_used": engine_used,
        "total_count": len(scenarios),
    }


async def extract_visual_tags_section(
    session: Session,
    *,
    char_name: str,
    description: str = "",
    personality: str = "",
    avatar_base64: Optional[str] = None,
    existing_tags: Optional[List[str]] = None,
    use_vision: bool = True,
) -> Dict[str, Any]:
    """Generate image generation tags, wardrobe presets, and outfit description."""
    avatar_bytes = None
    if avatar_base64:
        try:
            b64_data = avatar_base64.split(",")[-1]
            avatar_bytes = base64.b64decode(b64_data)
        except Exception:
            avatar_bytes = None

    vision_data, vision_used = await _analyze_avatar_with_vision(
        session,
        avatar_bytes=avatar_bytes,
        char_name=char_name,
        char_description=description,
        use_vision=use_vision,
    )

    visual_tags = (
        vision_data.get("visual_tags")
        if isinstance(vision_data.get("visual_tags"), list) and vision_data.get("visual_tags")
        else _extract_visual_tags_heuristic(description, existing_tags)
    )

    outfit = (
        str(vision_data.get("outfit_description") or "").strip()
        or _infer_outfit_from_text(description)
        or f"{char_name}'s signature attire"
    )

    presets = _build_wardrobe_presets(
        char_name,
        outfit,
        visual_tags,
        vision_data.get("wardrobe_presets") if isinstance(vision_data.get("wardrobe_presets"), list) else None,
    )

    return {
        "visual_tags": visual_tags,
        "character_outfit": outfit,
        "wardrobe_presets": presets,
        "vision_used": vision_used,
        "engine_used": "vision" if vision_used else "heuristic",
    }


async def extract_statekeeper_turn0_section(
    session: Session,
    *,
    char_name: str,
    description: str = "",
    personality: str = "",
    scenario_text: str = "",
    first_mes: str = "",
    default_location: Optional[str] = None,
    default_time: Optional[str] = None,
    locked_fields: Optional[List[str]] = None,
    current_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Synthesize or refresh Turn-0 Statekeeper fields, strictly preserving locked fields."""
    locked_set = set(locked_fields or [])
    curr = current_state or {}

    loc = default_location or _infer_location_from_text(first_mes, scenario_text, description) or f"{char_name}'s Sanctum"
    tim = default_time or _infer_time_from_text(first_mes, scenario_text, description) or "Evening"

    llm_system = (
        "You are the Statekeeper & Director for an interactive AI RPG. "
        "Synthesize Turn-0 state snapshot for the starting scene as valid JSON:\n"
        "{\n"
        '  "character_mood": "Emotional state at start",\n'
        '  "current_activity": "Immediate action at start",\n'
        '  "character_outfit": "Detailed attire",\n'
        '  "scene_tension": 2.0,\n'
        '  "emotional_tone": "neutral",\n'
        '  "relationship_status": "Status toward {{user}}",\n'
        '  "character_skills": ["Skill 1", "Skill 2", "Skill 3"],\n'
        '  "user_skills": ["Skill 1", "Skill 2"],\n'
        '  "inventory": ["Item 1", "Item 2"]\n'
        "}"
    )
    llm_user = (
        f"Character: {char_name}\n"
        f"Description: {description[:600]}\n"
        f"Personality: {personality[:400]}\n"
        f"Scenario: {scenario_text[:500]}\n"
        f"Opening Greeting: {first_mes[:600]}\n"
        f"Location: {loc} ({tim})"
    )
    parsed, engine_used = await _run_llm_json(
        session,
        kind="statekeeper_turn0",
        system_prompt=llm_system,
        user_content=llm_user,
        max_output_tokens=700,
    )
    bp = parsed or {}

    mood = str(bp.get("character_mood") or _infer_mood_from_text(first_mes, personality, description) or "Composed").strip()
    activity = str(bp.get("current_activity") or _infer_activity_from_text(first_mes, scenario_text) or f"Meeting with {{{{user}}}} at {loc}").strip()
    outfit = str(bp.get("character_outfit") or _infer_outfit_from_text(description, first_mes) or f"{char_name}'s attire").strip()
    try:
        tension = float(bp.get("scene_tension", 2.0))
    except (ValueError, TypeError):
        tension = 2.0
    tone = str(bp.get("emotional_tone") or "neutral").strip()
    rel_status = str(bp.get("relationship_status") or _infer_relationship_from_text(scenario_text, description, first_mes) or "Acquaintance").strip()
    c_skills = (
        [str(s).strip() for s in (bp.get("character_skills") or []) if str(s).strip()]
        or _extract_skills_from_text(f"{description}\n{personality}")
        or ["Composure", "Intuition"]
    )
    persona = _infer_persona_from_card(char_name, description, scenario_text, first_mes)
    u_skills = (
        [str(s).strip() for s in (bp.get("user_skills") or []) if str(s).strip()]
        or persona.get("skills")
        or ["Situational Awareness", "Resolve"]
    )
    inv = [str(i).strip() for i in (bp.get("inventory") or []) if str(i).strip()]

    # Respect locked fields!
    if "character_mood" in locked_set and "character_mood" in curr:
        mood = curr["character_mood"]
    if "current_activity" in locked_set and "current_activity" in curr:
        activity = curr["current_activity"]
    if "character_outfit" in locked_set and "character_outfit" in curr:
        outfit = curr["character_outfit"]
    if "scene_tension" in locked_set and "scene_tension" in curr:
        try:
            tension = float(curr["scene_tension"])
        except (ValueError, TypeError):
            pass
    if "emotional_tone" in locked_set and "emotional_tone" in curr:
        tone = curr["emotional_tone"]
    if "relationship_status" in locked_set and "relationship_status" in curr:
        rel_status = curr["relationship_status"]
    if "character_skills" in locked_set and "character_skills" in curr:
        c_skills = curr["character_skills"]
    if "user_skills" in locked_set and "user_skills" in curr:
        u_skills = curr["user_skills"]
    if "inventory" in locked_set and "inventory" in curr:
        inv = curr["inventory"]

    snapshot = {
        "character_mood": mood,
        "current_activity": activity,
        "character_outfit": outfit,
        "wardrobe": curr.get("wardrobe") or _build_wardrobe_presets(char_name, outfit, []),
        "relationship_status": rel_status,
        "relationships": curr.get("relationships") or [
            {
                "target_name": "{{user}}",
                "target_type": "user",
                "status": rel_status,
                "affinity": "neutral",
                "notes": f"Opening dynamic at {loc}",
            }
        ],
        "character_skills": c_skills,
        "user_skills": u_skills,
        "inventory": inv,
        "scene_tension": tension,
        "emotional_tone": tone,
        "character_expression": curr.get("character_expression") or "neutral",
        "fate_check_enabled": curr.get("fate_check_enabled", False),
        "fate_difficulty": curr.get("fate_difficulty", "auto"),
        "fate_outcome_override": curr.get("fate_outcome_override", "auto"),
        "world_clock": curr.get("world_clock") or {
            "day": 1,
            "time_of_day": tim,
            "location": loc,
            "chronology_log": [
                {
                    "day": 1,
                    "time": tim,
                    "location": loc,
                    "event": f"Opening scene with {char_name} at {loc}.",
                }
            ],
        },
        "locked_fields": list(locked_set),
    }

    return {
        "initial_state_snapshot": snapshot,
        "engine_used": engine_used,
        "locked_fields_preserved": list(locked_set),
    }


async def extract_world_lore_section(
    session: Session,
    *,
    char_name: str,
    description: str = "",
    scenario_text: str = "",
    first_mes: str = "",
    character_book: Optional[Dict[str, Any]] = None,
    existing_locations: Optional[List[Dict[str, Any]]] = None,
    locked_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Generate World setting, locations, and lorebook codex entries."""
    locked_set = set(locked_fields or [])

    world_name = (
        (str(character_book.get("name")).strip() if isinstance(character_book, dict) and character_book.get("name") else "")
        or f"Chronicles of {char_name}"
    )
    world_desc = scenario_text or description[:400] or f"The world and setting of {char_name}."

    locations = _extract_locations_from_card(
        char_name=char_name,
        description=description,
        scenario_text=scenario_text,
        first_mes=first_mes,
        alternate_greetings=[],
        character_book=character_book,
    )

    lorebook_bp = {
        "create": False,
        "name": f"{world_name} Lorebook",
        "description": f"World lore and codex entries for {world_name}.",
        "entries": [],
    }
    mapped_book = lorebook_from_character_book(character_book) if character_book else None
    if mapped_book:
        book_kwargs, entry_kwargs = mapped_book
        lorebook_bp = {
            "create": True,
            "name": book_kwargs.get("name") or f"{char_name} Lorebook",
            "description": book_kwargs.get("description") or f"Embedded lorebook from {char_name}'s card.",
            "entries": [
                {
                    "keys": e.get("keys") or [],
                    "content": e.get("content") or "",
                    "enabled": e.get("enabled", True),
                    "constant": e.get("constant", False),
                }
                for e in entry_kwargs[:50]
            ],
        }

    blocks = app_config.get_system_prompt_blocks() or {}
    llm_system = blocks.get("world_lore_enrich") or (
        "You are the World Lore Architect. From the character info, generate a cohesive World setting "
        "with evocative name, 2-3 sentence overview, 2-4 key locations, and 2-4 codex lore entries as valid JSON:\n"
        "{\n"
        '  "world_name": "...",\n'
        '  "world_description": "...",\n'
        '  "locations": [{"name": "...", "description": "...", "tags": ["tag1"], "default_time": "..."}],\n'
        '  "lore_entries": [{"keys": ["keyword1"], "content": "..."}]\n'
        "}"
    )
    llm_user = (
        f"Character: {char_name}\n"
        f"Description: {description[:700]}\n"
        f"Scenario: {scenario_text[:500]}\n"
        f"Existing Lorebook: {len(lorebook_bp['entries'])} entries"
    )
    parsed, engine_used = await _run_llm_json(
        session,
        kind="world_lore_enrich",
        system_prompt=llm_system,
        user_content=llm_user,
        max_output_tokens=900,
    )
    if parsed:
        if "world_name" not in locked_set and parsed.get("world_name"):
            world_name = str(parsed["world_name"]).strip()
        if "world_description" not in locked_set and parsed.get("world_description"):
            world_desc = str(parsed["world_description"]).strip()

        if isinstance(parsed.get("locations"), list):
            loc_names = {l["name"].lower() for l in locations}
            for loc in parsed["locations"]:
                if isinstance(loc, dict) and loc.get("name"):
                    lname = str(loc["name"]).strip()
                    if lname.lower() not in loc_names:
                        loc_names.add(lname.lower())
                        locations.append(
                            {
                                "name": lname[:75],
                                "description": str(loc.get("description") or f"Area in {world_name}")[:400],
                                "tags": loc.get("tags") if isinstance(loc.get("tags"), list) else ["location"],
                                "default_time": str(loc.get("default_time") or "Day"),
                                "selected": True,
                            }
                        )

        if not lorebook_bp["entries"] and isinstance(parsed.get("lore_entries"), list):
            lorebook_bp["create"] = True
            lorebook_bp["entries"] = [
                {
                    "keys": [str(k).strip() for k in (e.get("keys") or []) if str(k).strip()],
                    "content": str(e.get("content") or "").strip(),
                    "enabled": True,
                    "constant": False,
                }
                for e in parsed["lore_entries"]
                if isinstance(e, dict) and e.get("content")
            ]

    if existing_locations:
        loc_names = {l["name"].lower() for l in locations}
        for el in existing_locations:
            if isinstance(el, dict) and el.get("name") and str(el["name"]).lower() not in loc_names:
                loc_names.add(str(el["name"]).lower())
                locations.append(el)

    return {
        "world_name": world_name,
        "world_description": world_desc,
        "locations": locations,
        "lorebook": lorebook_bp,
        "engine_used": engine_used,
    }


async def enrich_individual_field(
    session: Session,
    *,
    field_name: str,
    current_value: str,
    char_name: str = "",
    context: str = "",
    instruction: str = "Enrich and expand while maintaining core tone and voice.",
) -> Dict[str, Any]:
    """Enrich or expand a specific text field using LLM, with graceful heuristic fallback."""
    if not current_value.strip():
        return {
            "field_name": field_name,
            "enriched_value": current_value,
            "engine_used": "none",
        }

    llm_system = (
        "You are an expert creative editor and fiction author for an AI RPG & Story engine. "
        f"Your task is to rewrite and enrich the field '{field_name}'. "
        "Strictly adhere to the following instruction: "
        f"{instruction}\n"
        "Maintain all existing character names, relationships, personality traits, and lore integrity. "
        "Return ONLY the enriched field text. Do not include markdown code block quotes around the entire response, "
        "and do not include any preface, greeting, or conversational remarks."
    )
    llm_user = (
        f"Field: {field_name}\n"
        f"Character: {char_name or 'N/A'}\n"
        f"Context / Surrounding Lore: {context[:1000] if context else 'None provided'}\n\n"
        f"Current Content to Enrich:\n{current_value}"
    )

    enriched_text, engine_used = await _run_llm_text(
        session,
        kind="field_enrich",
        system_prompt=llm_system,
        user_content=llm_user,
        max_output_tokens=1500,
        temperature=0.4,
    )

    if enriched_text and len(enriched_text.strip()) > 10:
        return {
            "field_name": field_name,
            "enriched_value": enriched_text.strip(),
            "engine_used": engine_used,
        }

    cleaned = re.sub(r"\n{3,}", "\n\n", current_value).strip()
    return {
        "field_name": field_name,
        "enriched_value": cleaned,
        "engine_used": "heuristic",
    }


async def ingest_long_document_chained(
    session: Session,
    *,
    raw_text: str,
    title: Optional[str] = None,
    chunk_size_words: int = 3500,
    overlap_words: int = 200,
) -> Dict[str, Any]:
    """Sliding-window Map-Reduce story ingestion for long texts (up to 50k+ words)."""
    words = raw_text.split()
    total_words = len(words)
    if total_words < 20:
        raise ValidationError("Story text is too short to ingest")

    inferred_title = (title or "").strip() or "Epic Chronicle"

    if total_words <= chunk_size_words:
        bp = await analyze_document_for_world(
            session,
            raw_text=raw_text,
            title=inferred_title,
        )
        bp["total_words"] = total_words
        bp["chunk_count"] = 1
        bp["story_chapters"] = [
            {
                "chapter_index": 1,
                "title": f"{inferred_title} — Prologue",
                "synopsis": str(bp.get("world", {}).get("description") or raw_text[:300]).strip(),
                "word_count": total_words,
            }
        ]
        return bp

    step = max(100, chunk_size_words - overlap_words)
    chunks: List[str] = []
    for i in range(0, total_words, step):
        chunk_slice = words[i : i + chunk_size_words]
        if not chunk_slice:
            break
        chunks.append(" ".join(chunk_slice))
        if i + chunk_size_words >= total_words:
            break

    chunk_count = len(chunks)
    chapters: List[Dict[str, Any]] = []
    character_map: Dict[str, Dict[str, Any]] = {}
    location_map: Dict[str, Dict[str, Any]] = {}
    lore_entries: List[Dict[str, Any]] = []

    first_bp = await analyze_document_for_world(
        session,
        raw_text=chunks[0],
        title=f"{inferred_title} (Part 1)",
    )

    world_name = first_bp.get("world", {}).get("name") or inferred_title
    world_desc = first_bp.get("world", {}).get("description") or f"World of {inferred_title}."

    for c in first_bp.get("characters") or []:
        if c.get("name"):
            character_map[c["name"].lower()] = c
    for loc in first_bp.get("locations") or []:
        if loc.get("name"):
            location_map[loc["name"].lower()] = loc
    for le in (first_bp.get("lorebook", {}).get("entries") or []):
        lore_entries.append(le)

    chapters.append(
        {
            "chapter_index": 1,
            "title": "Chapter 1: The Beginning",
            "synopsis": (first_bp.get("characters", [{}])[0].get("first_mes") or chunks[0][:350]).strip(),
            "word_count": len(chunks[0].split()),
        }
    )

    for idx, chunk_text in enumerate(chunks[1:], start=2):
        chunk_words = len(chunk_text.split())
        lines = [l.strip() for l in chunk_text.splitlines() if l.strip()]
        first_few = " ".join(lines[:3])[:250] if lines else f"Chapter {idx} progression"

        names_found = re.findall(r"\b([A-Z][a-z]{2,15})\s+(?:said|replied|shouted|whispered|looked|stepped|drew)\b", chunk_text)
        for name in set(names_found):
            if name.lower() not in character_map and len(character_map) < 12:
                character_map[name.lower()] = {
                    "name": name,
                    "description": f"Encountered in Chapter {idx} of {world_name}.",
                    "personality": "Determined and impactful in the unfolding tale.",
                    "scenario": f"Active during Chapter {idx}.",
                    "first_mes": f"*{name} approaches amidst the events of Chapter {idx}.*",
                    "visual_tags": ["character", "story figure"],
                    "character_skills": ["Adaptability", "Resolve"],
                    "wardrobe": _build_wardrobe_presets(name, f"{name}'s attire", []),
                    "selected": True,
                }

        locs_found = re.findall(r"\b(?:at|in|near|toward)\s+the\s+([A-Z][a-z]{3,20}(?:\s+[A-Z][a-z]{3,20})?)\b", chunk_text)
        for loc in set(locs_found):
            if loc.lower() not in location_map and len(location_map) < 10:
                location_map[loc.lower()] = {
                    "name": f"The {loc}",
                    "description": f"Key location visited during Chapter {idx}.",
                    "tags": ["story location"],
                    "default_time": "Day",
                    "selected": True,
                }

        chapters.append(
            {
                "chapter_index": idx,
                "title": f"Chapter {idx}: The Journey Unfolds",
                "synopsis": first_few,
                "word_count": chunk_words,
            }
        )

    scenarios: List[Dict[str, Any]] = []
    for ch in chapters:
        scenarios.append(
            {
                "id": f"scenario_ch_{ch['chapter_index']}",
                "title": ch["title"],
                "description": ch["synopsis"][:400],
                "first_mes": ch["synopsis"],
                "location_name": list(location_map.values())[0]["name"] if location_map else "Starting Realm",
                "story_time": "Day",
                "is_primary": ch["chapter_index"] == 1,
                "selected": True,
            }
        )

    characters = list(character_map.values())[:8]
    locations = list(location_map.values())[:10]

    return {
        "source_type": "chained_long_document",
        "world": {
            "mode": "create",
            "existing_world_id": None,
            "name": world_name,
            "description": world_desc,
        },
        "characters": characters,
        "locations": locations,
        "scenarios": scenarios,
        "persona": first_bp.get("persona") or {
            "name": "Chronicle Protagonist",
            "description": f"The central figure traversing {world_name}.",
            "skills": ["Survival", "Perception", "Leadership"],
        },
        "lorebook": {
            "create": True,
            "name": f"{world_name} Archive",
            "description": f"Accumulated lore across {chunk_count} story chapters ({total_words:,} words).",
            "entries": lore_entries,
        },
        "relationships": first_bp.get("relationships") or [],
        "initial_state_snapshot": first_bp.get("initial_state_snapshot") or {},
        "story_chapters": chapters,
        "total_words": total_words,
        "chunk_count": chunk_count,
        "analysis_meta": {
            "engine_used": first_bp.get("analysis_meta", {}).get("engine_used", "chained_map_reduce"),
            "total_words": total_words,
            "chunk_count": chunk_count,
            "characters_count": len(characters),
            "locations_count": len(locations),
            "chapters_count": len(chapters),
        },
    }


CROSSOVER_ARCHETYPES: Dict[str, Dict[str, str]] = {
    "rift_portal": {
        "label": "Dimensional Rift / Portal",
        "summary": "A sudden spatial anomaly tears open, pulling the traveler(s) directly into the destination world with their original gear and powers intact.",
    },
    "reincarnation": {
        "label": "Isekai Reincarnation / Awakening",
        "summary": "The traveler awakens in the destination world with full memories of their origin world, adapting their signature skills to local laws.",
    },
    "world_collision": {
        "label": "Convergence / World Collision",
        "summary": "Districts and landmarks from both worlds fuse together in a cataclysmic convergence, forcing residents and travelers to coexist.",
    },
    "summoned_hero": {
        "label": "Arcane / Technological Summoning",
        "summary": "A ritual or quantum beacon in the destination world deliberately summons the traveler(s) to resolve an impending crisis.",
    },
}


async def generate_world_crossover(
    session: Session,
    *,
    traveler_character_ids: List[str],
    target_world_id: str,
    archetype: str = "rift_portal",
    target_location_id: Optional[str] = None,
    resident_character_ids: Optional[List[str]] = None,
    custom_premise: Optional[str] = None,
) -> Dict[str, Any]:
    """Synthesize a World Crossover / Transmigration Scenario, opening greeting, and Turn-0 state."""
    if not traveler_character_ids:
        raise ValidationError("Select at least one traveler character for the crossover")

    target_world = session.get(World, target_world_id)
    if not target_world:
        raise NotFoundError("World", target_world_id)

    travelers: List[Character] = []
    for cid in traveler_character_ids:
        c = session.get(Character, cid)
        if not c:
            raise NotFoundError("Character", cid)
        travelers.append(c)

    primary_traveler = travelers[0]
    origin_world = session.get(World, primary_traveler.world_id) if primary_traveler.world_id else None
    origin_world_name = origin_world.name if origin_world else f"{primary_traveler.name}'s Origin World"
    origin_world_desc = origin_world.description if origin_world and origin_world.description else (primary_traveler.scenario or primary_traveler.description or "")[:300]

    target_location: Optional[Location] = None
    if target_location_id:
        target_location = session.get(Location, target_location_id)
    if not target_location:
        target_location = session.exec(
            select(Location).where(Location.world_id == target_world.id)
        ).first()

    loc_name = target_location.name if target_location else f"{target_world.name} — Arrival Point"
    loc_time = (target_location.atmosphere if target_location and target_location.atmosphere else None) or "Dusk (Rift Anomaly)"

    residents: List[Character] = []
    if resident_character_ids:
        for rcid in resident_character_ids:
            rc = session.get(Character, rcid)
            if rc and rc.id not in {t.id for t in travelers}:
                residents.append(rc)
    else:
        residents = [
            rc
            for rc in session.exec(select(Character).where(Character.world_id == target_world.id)).all()
            if rc.id not in {t.id for t in travelers}
        ][:2]

    arch_info = CROSSOVER_ARCHETYPES.get(archetype) or CROSSOVER_ARCHETYPES["rift_portal"]
    traveler_names = ", ".join(t.name for t in travelers)
    resident_names = ", ".join(r.name for r in residents) if residents else "local inhabitants"

    blocks = app_config.get_system_prompt_blocks() or {}
    llm_system = blocks.get("world_crossover") or (
        "You are the World Crossover & Transmigration Architect. Create a thrilling crossover scenario "
        "where character(s) from Origin World A arrive in Destination World B. Return ONLY valid JSON:\n"
        "{\n"
        '  "scenario_title": "Evocative title for the crossover",\n'
        '  "scenario_description": "2-3 sentences explaining how their powers/tech interact with the destination world",\n'
        '  "first_mes": "Rich 2-3 paragraph in-character opening scene of the arrival/encounter",\n'
        '  "crossover_context": "Persistent world-rules note explaining Origin World vs Destination World physics/magic",\n'
        '  "character_mood": "Shocked, alert, or intrigued",\n'
        '  "current_activity": "Orienting after arriving in the new world"\n'
        "}"
    )
    llm_user = (
        f"Archetype: {arch_info['label']} ({arch_info['summary']})\n"
        f"Traveler(s): {traveler_names} (Origin: {origin_world_name} — {origin_world_desc[:300]})\n"
        f"Primary Traveler Description: {(primary_traveler.description or '')[:600]}\n"
        f"Destination World: {target_world.name} — {(target_world.description or '')[:500]}\n"
        f"Arrival Location: {loc_name}\n"
        f"Resident Character(s) Present: {resident_names}\n"
        f"Custom Premise: {custom_premise or 'None'}"
    )
    parsed, engine_used = await _run_llm_json(
        session,
        kind="world_crossover",
        system_prompt=llm_system,
        user_content=llm_user,
        max_output_tokens=900,
    )
    bp = parsed or {}

    scenario_title = str(
        bp.get("scenario_title")
        or f"Crossover: {primary_traveler.name} in {target_world.name} ({arch_info['label']})"
    ).strip()
    scenario_desc = str(
        bp.get("scenario_description")
        or f"{arch_info['summary']} {traveler_names} (from {origin_world_name}) arrives at {loc_name} in {target_world.name}."
    ).strip()
    crossover_context = str(
        bp.get("crossover_context")
        or (
            f"CROSSOVER CANON: {traveler_names} originated from '{origin_world_name}' and entered '{target_world.name}' "
            f"via {arch_info['label']}. {primary_traveler.name} retains their memories, personality, and signature skillset, "
            f"while navigating the unfamiliar laws, factions, and atmosphere of {target_world.name} ({loc_name})."
        )
    ).strip()
    first_mes = str(
        bp.get("first_mes")
        or (
            f"*The air at {loc_name} distorts with an otherworldly resonance as the boundary between {origin_world_name} "
            f"and {target_world.name} fractures. Stepping through the threshold, {primary_traveler.name} takes in the unfamiliar "
            f"skyline and strange atmosphere of {loc_name} for the first time.*\n\n"
            f"\"This definitely isn't {origin_world_name}...\" *{primary_traveler.name} murmurs, steadying their stance as they "
            f"notice {{{{user}}}} nearby.*"
        )
    ).strip()

    char_skills = _extract_skills_from_text(
        f"{primary_traveler.description or ''}\n{primary_traveler.personality or ''}\n{primary_traveler.scenario or ''}"
    ) or ["Dimensional Resilience", "Tactical Intuition", "Signature Mastery"]

    relationships: List[Dict[str, Any]] = [
        {
            "target_name": "{{user}}",
            "target_type": "user",
            "status": "Anchor / First Contact in New World",
            "affinity": "curious",
            "notes": f"Met upon arrival at {loc_name}",
        }
    ]
    for other_t in travelers[1:]:
        relationships.append(
            {
                "target_name": other_t.name,
                "target_id": other_t.id,
                "target_type": "character",
                "status": "Fellow Dimensional Traveler",
                "affinity": "trusted",
                "notes": f"Crossed over together from {origin_world_name}",
            }
        )
    for res_char in residents:
        relationships.append(
            {
                "target_name": res_char.name,
                "target_id": res_char.id,
                "target_type": "character",
                "status": f"Resident of {target_world.name}",
                "affinity": "wary",
                "notes": f"Encountered at {loc_name}",
            }
        )

    outfit = _infer_outfit_from_text(primary_traveler.description, primary_traveler.first_mes) or f"{primary_traveler.name}'s origin-world attire"
    wardrobe = _build_wardrobe_presets(primary_traveler.name, outfit, primary_traveler.visual_tags or [])
    wardrobe.append(
        {
            "name": f"{target_world.name} Disguise",
            "outfit": f"Local attire adapted to blend into {loc_name} in {target_world.name}",
            "visual_tags": f"local attire, {loc_name}, blending in",
        }
    )

    initial_state_snapshot = {
        "character_mood": str(bp.get("character_mood") or "Alert and awestruck by the unfamiliar world"),
        "current_activity": str(bp.get("current_activity") or f"Surveying {loc_name} after arriving from {origin_world_name}"),
        "character_outfit": outfit,
        "wardrobe": wardrobe,
        "relationship_status": "Anchor / First Contact in New World",
        "relationships": relationships,
        "character_skills": char_skills,
        "user_skills": ["World Lore Guide", "Adaptability", "Diplomacy"],
        "inventory": [f"Emblem of {origin_world_name}"],
        "scene_tension": 3.0,
        "emotional_tone": "mysterious_tense",
        "character_expression": "surprised",
        "fate_check_enabled": True,
        "fate_difficulty": "moderate",
        "fate_outcome_override": "auto",
        "crossover_context": crossover_context,
        "world_clock": {
            "day": 1,
            "time_of_day": loc_time,
            "location": loc_name,
            "chronology_log": [
                {
                    "day": 1,
                    "time": loc_time,
                    "location": loc_name,
                    "event": f"CROSSOVER EVENT: {traveler_names} arrived from {origin_world_name} into {target_world.name} ({loc_name}) via {arch_info['label']}.",
                }
            ],
        },
    }

    return {
        "archetype": archetype,
        "archetype_label": arch_info["label"],
        "origin_world_name": origin_world_name,
        "target_world": {"id": target_world.id, "name": target_world.name, "description": target_world.description},
        "target_location": {"id": target_location.id if target_location else None, "name": loc_name, "time": loc_time},
        "travelers": [{"id": t.id, "name": t.name} for t in travelers],
        "residents": [{"id": r.id, "name": r.name} for r in residents],
        "scenario": {
            "title": scenario_title,
            "description": scenario_desc,
            "first_mes": first_mes,
            "location_name": loc_name,
            "story_time": loc_time,
        },
        "crossover_context": crossover_context,
        "relationships": relationships,
        "initial_state_snapshot": initial_state_snapshot,
        "engine_used": engine_used,
    }


def commit_world_blueprint(
    session: Session,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Persist an onboarding or crossover World Blueprint into the World Vault.

    Creates or merges:
    - `World`
    - `Lorebook` + `LorebookEntry` rows
    - `Location` rows
    - `Character` rows (including saving decoded avatar PNGs and creating `Collection`s)
    - `Persona` row (optional)
    - `Scenario` rows
    - `WorldEdge` relationship rows
    - Optional Turn-0 `Chat` and/or `Story`
    """
    now = datetime.now(timezone.utc)
    world_cfg = payload.get("world") or {}
    mode = str(world_cfg.get("mode") or "create").lower()
    existing_world_id = world_cfg.get("existing_world_id")

    world: Optional[World] = None
    if mode == "merge" and existing_world_id:
        world = session.get(World, existing_world_id)
        if not world:
            raise NotFoundError("World", existing_world_id)
    if world is None:
        w_name = str(world_cfg.get("name") or "New Fantasy World").strip()
        w_desc = str(world_cfg.get("description") or "").strip() or None
        world = World(name=w_name, description=w_desc, created_at=now, updated_at=now)
        session.add(world)
        session.commit()
        session.refresh(world)

    # 1. Lorebook
    created_lorebook_id: Optional[str] = None
    lore_cfg = payload.get("lorebook") or {}
    if lore_cfg.get("create") and lore_cfg.get("name"):
        lorebook = Lorebook(
            name=str(lore_cfg["name"]).strip(),
            description=str(lore_cfg.get("description") or "").strip() or None,
            world_id=world.id,
            created_at=now,
            updated_at=now,
        )
        session.add(lorebook)
        session.commit()
        session.refresh(lorebook)
        created_lorebook_id = lorebook.id

        for idx, entry in enumerate(lore_cfg.get("entries") or []):
            if not isinstance(entry, dict) or not entry.get("content"):
                continue
            keys = entry.get("keys") if isinstance(entry.get("keys"), list) else []
            session.add(
                LorebookEntry(
                    lorebook_id=lorebook.id,
                    keys=[str(k).strip() for k in keys if str(k).strip()],
                    content=str(entry["content"]).strip(),
                    enabled=bool(entry.get("enabled", True)),
                    constant=bool(entry.get("constant", False)),
                    insertion_order=idx * 10,
                    created_at=now,
                    updated_at=now,
                )
            )
        session.commit()

    # 2. Locations
    locations_by_name: Dict[str, Location] = {}
    existing_locs = session.exec(select(Location).where(Location.world_id == world.id)).all()
    for el in existing_locs:
        locations_by_name[el.name.lower()] = el

    created_location_ids: List[str] = []
    for loc_bp in payload.get("locations") or []:
        if not isinstance(loc_bp, dict) or not loc_bp.get("selected", True):
            continue
        lname = str(loc_bp.get("name") or "").strip()
        if not lname:
            continue
        existing = locations_by_name.get(lname.lower())
        if existing:
            created_location_ids.append(existing.id)
            continue
        loc = Location(
            name=lname[:100],
            description=str(loc_bp.get("description") or "").strip() or None,
            atmosphere=str(loc_bp.get("default_time") or loc_bp.get("atmosphere") or "").strip() or None,
            tags=[str(t).strip() for t in (loc_bp.get("tags") or []) if str(t).strip()],
            world_id=world.id,
            created_at=now,
            updated_at=now,
        )
        session.add(loc)
        session.commit()
        session.refresh(loc)
        locations_by_name[lname.lower()] = loc
        created_location_ids.append(loc.id)

    # 3. Characters
    created_character_ids: List[str] = []
    characters_by_name: Dict[str, Character] = {}
    for char_bp in payload.get("characters") or []:
        if not isinstance(char_bp, dict) or not char_bp.get("selected", True):
            continue
        existing_cid = char_bp.get("existing_character_id")
        character: Optional[Character] = session.get(Character, existing_cid) if existing_cid else None
        cname = str(char_bp.get("name") or "Character").strip()

        if character:
            character.name = cname
            character.description = char_bp.get("description") or character.description
            character.personality = char_bp.get("personality") or character.personality
            character.scenario = char_bp.get("scenario") or character.scenario
            character.first_mes = char_bp.get("first_mes") or character.first_mes
            if char_bp.get("alternate_greetings") is not None:
                character.alternate_greetings = list(char_bp.get("alternate_greetings") or [])
            if char_bp.get("visual_tags"):
                character.visual_tags = [str(t).strip() for t in char_bp["visual_tags"] if str(t).strip()]
            character.default_location = char_bp.get("default_location") or character.default_location
            character.default_time = char_bp.get("default_time") or character.default_time
            character.suggested_persona = char_bp.get("suggested_persona") or character.suggested_persona
            # `world_id` is written through `link_to_world`, like every other
            # member. Assigning the column here made this the second writer,
            # which is the thing `world_ownership` exists to prevent: a member
            # linked here and unlinked elsewhere leaves the world counting a
            # member that does not belong to it.
            link_to_world(session, character, world.id)
            if created_lorebook_ids := ([created_lorebook_id] if created_lorebook_id else []):
                merged_lids = list(character.lorebook_ids or [])
                for lid in created_lorebook_ids:
                    if lid not in merged_lids:
                        merged_lids.append(lid)
                character.lorebook_ids = merged_lids
            character.updated_at = now
            session.add(character)
            session.commit()
            session.refresh(character)
        else:
            character = Character(
                name=cname,
                description=char_bp.get("description") or None,
                personality=char_bp.get("personality") or None,
                scenario=char_bp.get("scenario") or None,
                first_mes=char_bp.get("first_mes") or None,
                alternate_greetings=list(char_bp.get("alternate_greetings") or []) or None,
                mes_example=char_bp.get("mes_example") or None,
                system_prompt=char_bp.get("system_prompt") or None,
                append_system_prompt=char_bp.get("append_system_prompt") or None,
                creator_notes=char_bp.get("creator_notes") or None,
                suggested_persona=char_bp.get("suggested_persona") or None,
                visual_tags=[str(t).strip() for t in (char_bp.get("visual_tags") or []) if str(t).strip()],
                default_location=char_bp.get("default_location") or None,
                default_time=char_bp.get("default_time") or None,
                lorebook_ids=[created_lorebook_id] if created_lorebook_id else [],
                embedded_lorebook_id=created_lorebook_id,
                card_spec=char_bp.get("card_spec") or None,
                card_spec_version=char_bp.get("card_spec_version") or None,
                card_metadata=char_bp.get("card_metadata") or None,
                world_id=world.id,
                created_at=now,
                updated_at=now,
            )
            session.add(character)
            session.commit()
            session.refresh(character)

            if char_bp.get("avatar_base64"):
                try:
                    raw_avatar = base64.b64decode(char_bp["avatar_base64"])
                    os.makedirs(f"{app_config.settings.character_avatar_dir}/{character.id}", exist_ok=True)
                    avatar_path = f"{app_config.settings.character_avatar_dir}/{character.id}/avatar.png"
                    with open(avatar_path, "wb") as f:
                        f.write(raw_avatar)
                    character.avatar_path = avatar_path
                    session.add(character)
                    session.commit()
                    session.refresh(character)
                except Exception as exc:
                    logger.warning("onboarding_avatar_save_failed", error=str(exc))

            collection = Collection(
                name=f"{character.name}'s Gallery",
                color="#8B5CF6",
                description=f"Scene images generated for {character.name}",
                character_id=character.id,
            )
            session.add(collection)
            session.commit()
            session.refresh(character)

        created_character_ids.append(character.id)
        characters_by_name[character.name.lower()] = character

    primary_character = session.get(Character, created_character_ids[0]) if created_character_ids else None

    # 4. Persona
    created_persona_id: Optional[str] = None
    persona_cfg = payload.get("persona") or {}
    if persona_cfg.get("create") and persona_cfg.get("name"):
        persona = Persona(
            name=str(persona_cfg["name"]).strip(),
            description=str(persona_cfg.get("description") or "").strip() or None,
            created_at=now,
            updated_at=now,
        )
        session.add(persona)
        session.commit()
        session.refresh(persona)
        created_persona_id = persona.id

    # 5. Scenarios
    created_scenario_ids: List[str] = []
    primary_scenario: Optional[Scenario] = None
    for scen_bp in payload.get("scenarios") or []:
        if not isinstance(scen_bp, dict) or not scen_bp.get("selected", True):
            continue
        stitle = str(scen_bp.get("title") or scen_bp.get("name") or "").strip()
        if not stitle:
            continue
        desc_text = str(scen_bp.get("description") or "").strip()
        first_mes_text = str(scen_bp.get("first_mes") or desc_text).strip()
        scen = Scenario(
            name=stitle[:120],
            description=desc_text or None,
            prompt_template=first_mes_text or desc_text or stitle,
            world_id=world.id,
            created_at=now,
            updated_at=now,
        )
        session.add(scen)
        session.commit()
        session.refresh(scen)
        created_scenario_ids.append(scen.id)
        if primary_scenario is None or scen_bp.get("is_primary"):
            primary_scenario = scen

    # 6. WorldEdge graph links
    if primary_character:
        for loc_id in created_location_ids[:6]:
            _safe_create_world_edge(
                session,
                source_type="character",
                source_id=primary_character.id,
                target_type="location",
                target_id=loc_id,
                relation_type="frequents",
                label="inhabits",
            )
        for rel in payload.get("relationships") or []:
            if not isinstance(rel, dict) or rel.get("target_type") != "character":
                continue
            target_id = rel.get("target_id")
            if not target_id and rel.get("target_name"):
                tchar = characters_by_name.get(str(rel["target_name"]).strip().lower())
                if tchar:
                    target_id = tchar.id
            if target_id and target_id != primary_character.id:
                _safe_create_world_edge(
                    session,
                    source_type="character",
                    source_id=primary_character.id,
                    target_type="character",
                    target_id=target_id,
                    relation_type="relationship",
                    label=str(rel.get("status") or "connected")[:80],
                )

    # 7. Optional Turn-0 Chat creation
    created_chat_id: Optional[str] = None
    if payload.get("launch_chat", True) and primary_character:
        raw_snapshot = dict(payload.get("initial_state_snapshot") or {})
        start_loc = (
            raw_snapshot.get("world_clock", {}).get("location")
            if isinstance(raw_snapshot.get("world_clock"), dict)
            else None
        ) or primary_character.default_location or (locations_by_name[next(iter(locations_by_name))].name if locations_by_name else None)
        start_time = (
            raw_snapshot.get("world_clock", {}).get("time_of_day")
            if isinstance(raw_snapshot.get("world_clock"), dict)
            else None
        ) or primary_character.default_time or "Evening"
        matched_loc = locations_by_name.get(str(start_loc or "").lower())

        selected_scen_bp = next(
            (s for s in (payload.get("scenarios") or []) if isinstance(s, dict) and s.get("selected", True)),
            None,
        )
        override_greeting = (
            str(selected_scen_bp.get("first_mes")).strip()
            if isinstance(selected_scen_bp, dict) and selected_scen_bp.get("first_mes")
            else primary_character.first_mes
        )

        seeded_snapshot = seed_initial_state_snapshot(
            character=primary_character,
            scenario=primary_scenario,
            persona_name=persona_cfg.get("name") if persona_cfg.get("create") else None,
            story_location=start_loc,
            story_time=start_time,
            override_greeting=override_greeting,
            existing_snapshot=raw_snapshot,
        )

        chat = Chat(
            name=f"{primary_character.name} — {world.name}",
            world_id=world.id,
            character_id=primary_character.id,
            additional_character_ids=created_character_ids[1:],
            scenario_id=primary_scenario.id if primary_scenario else None,
            persona_id=created_persona_id,
            persona_name=str(persona_cfg.get("name") or "").strip() or None if persona_cfg.get("create") else None,
            persona_description=str(persona_cfg.get("description") or "").strip() or None if persona_cfg.get("create") else None,
            story_location=start_loc,
            story_time=start_time,
            location_id=matched_loc.id if matched_loc else (created_location_ids[0] if created_location_ids else None),
            active_lorebook_ids=[created_lorebook_id] if created_lorebook_id else list(primary_character.lorebook_ids or []),
            director_enabled=True,
            state_snapshot=seeded_snapshot,
            created_at=now,
            updated_at=now,
        )
        link_to_world(session, chat, world.id)
        session.add(chat)
        session.commit()
        session.refresh(chat)
        created_chat_id = chat.id

        if override_greeting:
            first_mes_rendered = substitute_tavern_vars(
                override_greeting,
                char=primary_character.name or "",
                user=chat.persona_name or "User",
                persona_description=chat.persona_description or "",
                original=primary_character.description or "",
            )
            session.add(
                Message(
                    chat_id=chat.id,
                    role=MessageRole.CHAR,
                    kind=MessageKind.CHAR,
                    character_id=primary_character.id,
                    content=first_mes_rendered,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()

    # 8. Optional Story Sandbox creation
    created_story_id: Optional[str] = None
    if payload.get("launch_story") and world:
        seed_prose = str(
            payload.get("story_seed_content")
            or (primary_character.first_mes if primary_character else "")
            or world.description
            or ""
        ).strip()
        story = Story(
            title=world.name,
            description=world.description or f"Story set in {world.name}.",
            world_id=world.id,
            character_ids=list(created_character_ids),
            lorebook_ids=[created_lorebook_id] if created_lorebook_id else [],
            location_ids=list(created_location_ids),
            scenario_id=primary_scenario.id if primary_scenario else None,
            created_at=now,
            updated_at=now,
        )
        link_to_world(session, story, world.id)
        session.add(story)
        session.commit()
        session.refresh(story)
        created_story_id = story.id

        chapter = StoryChapter(
            story_id=story.id,
            chapter_number=1,
            title="Chapter 1: Awakening",
            content=seed_prose,
        )
        session.add(chapter)
        session.commit()

    return {
        "world_id": world.id,
        "world_name": world.name,
        "character_ids": created_character_ids,
        "location_ids": created_location_ids,
        "scenario_ids": created_scenario_ids,
        "lorebook_id": created_lorebook_id,
        "persona_id": created_persona_id,
        "chat_id": created_chat_id,
        "story_id": created_story_id,
    }


def _safe_create_world_edge(
    session: Session,
    *,
    source_type: str,
    source_id: str,
    target_type: str,
    target_id: str,
    relation_type: str,
    label: str,
) -> None:
    existing = session.exec(
        select(WorldEdge).where(
            WorldEdge.source_entity_type == source_type,
            WorldEdge.source_entity_id == source_id,
            WorldEdge.target_entity_type == target_type,
            WorldEdge.target_entity_id == target_id,
            WorldEdge.relation_type == relation_type,
        )
    ).first()
    if existing:
        existing.label = label[:100]
        session.add(existing)
    else:
        session.add(
            WorldEdge(
                source_entity_type=source_type,
                source_entity_id=source_id,
                target_entity_type=target_type,
                target_entity_id=target_id,
                relation_type=relation_type,
                label=label[:100],
            )
        )
    session.commit()


def commit_chat_to_world_canon(
    session: Session,
    *,
    chat_id: str,
) -> Dict[str, Any]:
    """Promote a Chat's Statekeeper chronology, locations, and relationships to World Vault Canon."""
    chat = session.get(Chat, chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    now = datetime.now(timezone.utc)
    character = session.get(Character, chat.character_id) if chat.character_id else None
    char_name = character.name if character else "Character"

    # Ensure a parent World exists
    world: Optional[World] = session.get(World, chat.world_id) if chat.world_id else None
    if not world and character and character.world_id:
        world = session.get(World, character.world_id)
    if not world:
        world = World(
            name=f"World of {char_name}",
            description=f"Canonical world state evolved from roleplay sessions with {char_name}.",
            created_at=now,
            updated_at=now,
        )
        session.add(world)
        session.commit()
        session.refresh(world)

    if chat.world_id != world.id:
        link_to_world(session, chat, world.id)
    if character and character.world_id != world.id:
        link_to_world(session, character, world.id)

    snapshot = dict(chat.state_snapshot or {})
    wc = snapshot.get("world_clock") if isinstance(snapshot.get("world_clock"), dict) else {}
    chronology = wc.get("chronology_log") if isinstance(wc.get("chronology_log"), list) else []

    # Materialize current location if needed
    loc_created_or_linked: Optional[str] = None
    if chat.story_location:
        existing_loc = session.exec(
            select(Location).where(
                Location.world_id == world.id,
                func.lower(Location.name) == chat.story_location.strip().lower(),
            )
        ).first()
        if not existing_loc:
            existing_loc = Location(
                name=chat.story_location.strip()[:100],
                description=snapshot.get("scene_summary") or f"Canon location visited with {char_name}.",
                atmosphere=chat.story_time or wc.get("time_of_day") or "Evening",
                tags=["canon location"],
                world_id=world.id,
                created_at=now,
                updated_at=now,
            )
            session.add(existing_loc)
            session.commit()
            session.refresh(existing_loc)
        chat.location_id = existing_loc.id
        loc_created_or_linked = existing_loc.id

    # Find or create Canon Chronicle Lorebook for this World
    canon_book_name = f"{world.name} — Canon Chronicle"
    canon_book = session.exec(
        select(Lorebook).where(
            Lorebook.world_id == world.id,
            Lorebook.name == canon_book_name,
        )
    ).first()
    if not canon_book:
        canon_book = Lorebook(
            name=canon_book_name,
            description=f"Persistent canonical history, relationships, and world events committed from chats in {world.name}.",
            world_id=world.id,
            created_at=now,
            updated_at=now,
        )
        session.add(canon_book)
        session.commit()
        session.refresh(canon_book)

    active_lids = list(chat.active_lorebook_ids or [])
    if canon_book.id not in active_lids:
        active_lids.append(canon_book.id)
        chat.active_lorebook_ids = active_lids

    # Build a rich canon lorebook entry summarizing the current state & chronology
    lines = [f"[Canon Snapshot from '{chat.name}' with {char_name}]"]
    if chat.story_location or chat.story_time:
        lines.append(f"Current Location & Time: {chat.story_location or 'Unknown'} ({chat.story_time or 'Unknown'})")
    if snapshot.get("character_outfit"):
        lines.append(f"{char_name}'s Attire: {snapshot['character_outfit']}")
    if snapshot.get("relationship_status"):
        lines.append(f"Bond with User: {snapshot['relationship_status']}")
    if isinstance(snapshot.get("relationships"), list) and snapshot["relationships"]:
        rel_summary = "; ".join(
            f"{r.get('target_name')}: {r.get('status')} ({r.get('affinity', 'neutral')})"
            for r in snapshot["relationships"]
            if isinstance(r, dict) and r.get("target_name")
        )
        if rel_summary:
            lines.append(f"Relationship Network: {rel_summary}")
    if isinstance(snapshot.get("inventory"), list) and snapshot["inventory"]:
        lines.append(f"Key Items: {', '.join(str(i) for i in snapshot['inventory'][:10])}")
    if chronology:
        lines.append("Recent Canon Timeline:")
        for ev in chronology[-6:]:
            if isinstance(ev, dict) and ev.get("event"):
                lines.append(f"- Day {ev.get('day', 1)} ({ev.get('time', '')}): {ev['event']}")

    entry_content = "\n".join(lines)
    entry = LorebookEntry(
        lorebook_id=canon_book.id,
        keys=[char_name.lower(), "canon", "history", (chat.story_location or "world").lower()[:30]],
        content=entry_content,
        enabled=True,
        constant=True,
        created_at=now,
        updated_at=now,
    )
    session.add(entry)

    # Sync character-to-character relationships to WorldEdge
    edges_synced = 0
    if character and isinstance(snapshot.get("relationships"), list):
        for rel in snapshot["relationships"]:
            if not isinstance(rel, dict) or rel.get("target_type") != "character":
                continue
            tname = str(rel.get("target_name") or "").strip()
            if not tname:
                continue
            target_char = session.exec(
                select(Character).where(func.lower(Character.name) == tname.lower())
            ).first()
            if target_char and target_char.id != character.id:
                _safe_create_world_edge(
                    session,
                    source_type="character",
                    source_id=character.id,
                    target_type="character",
                    target_id=target_char.id,
                    relation_type="relationship",
                    label=str(rel.get("status") or "connected")[:80],
                )
                edges_synced += 1

    # Update character defaults to reflect current canon state
    if character:
        if chat.story_location:
            character.default_location = chat.story_location
        if chat.story_time:
            character.default_time = chat.story_time
        session.add(character)

    session.add(chat)
    session.commit()

    return {
        "world_id": world.id,
        "world_name": world.name,
        "lorebook_id": canon_book.id,
        "lore_entry_id": entry.id,
        "location_id": loc_created_or_linked,
        "edges_synced": edges_synced,
        "chronology_events_committed": len(chronology),
    }


async def compile_chat_to_story(
    session: Session,
    *,
    chat_id: str,
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """Compile a roleplay chat + Statekeeper timeline + generated images into a Story Sandbox chapter."""
    chat = session.get(Chat, chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    messages = session.exec(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
    ).all()
    character = session.get(Character, chat.character_id) if chat.character_id else None
    char_name = character.name if character else "Character"
    user_name = chat.persona_name or "User"

    transcript_lines: List[str] = []
    beats: List[Dict[str, Any]] = []
    for idx, msg in enumerate(messages):
        if msg.image_path:
            beats.append(
                {
                    "id": f"beat-img-{idx}",
                    "type": "image",
                    "image_path": msg.image_path,
                    "content": msg.content or f"Scene illustration with {char_name}",
                }
            )
        content = (msg.content or "").strip()
        if not content:
            continue
        role_val = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
        speaker = user_name if role_val == "user" else (char_name if role_val == "char" else "Narrator")
        transcript_lines.append(f"{speaker}: {content}")
        beats.append(
            {
                "id": f"beat-{idx}",
                "type": "narration" if role_val == "system" else "prose",
                "speaker": speaker,
                "content": content,
            }
        )

    raw_transcript = "\n\n".join(transcript_lines)
    # Try novelizing via RP LLM if online; otherwise format as clean literary prose
    novelized_prose = ""
    if raw_transcript:
        blocks = app_config.get_system_prompt_blocks() or {}
        compile_prompt = blocks.get("story_compile") or (
            "You are a literary fantasy & sci-fi novelist. Rewrite the provided roleplay transcript "
            "into cohesive, atmospheric third-person novel prose while preserving key dialogue and "
            "emotional beats. Return ONLY valid JSON: `{\"chapter_title\": \"...\", \"prose\": \"...\"}`"
        )
        llm_parsed, _ = await _run_llm_json(
            session,
            kind="story_compile",
            system_prompt=compile_prompt,
            user_content=f"Character: {char_name}\nCounterpart: {user_name}\nLocation: {chat.story_location or 'Unknown'}\n\nTranscript:\n{raw_transcript[:5000]}",
            max_output_tokens=1500,
            temperature=0.4,
        )
        if llm_parsed and llm_parsed.get("prose"):
            novelized_prose = str(llm_parsed["prose"]).strip()
            chapter_title = str(llm_parsed.get("chapter_title") or f"Chapter 1: {chat.story_location or 'The Encounter'}").strip()
        else:
            chapter_title = f"Chapter 1: {chat.story_location or 'The Encounter'}"
            prose_parts: List[str] = []
            for msg in messages:
                content = (msg.content or "").strip()
                if not content:
                    continue
                role_val = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
                if role_val == "user":
                    prose_parts.append(f"**{user_name}:** {content}")
                elif role_val == "char":
                    prose_parts.append(f"**{char_name}:** {content}")
                else:
                    prose_parts.append(f"*{content}*")
            novelized_prose = "\n\n".join(prose_parts)
    else:
        chapter_title = "Chapter 1: Opening"
        novelized_prose = f"*A story beginning at {chat.story_location or 'the crossroads'} with {char_name}.*"

    now = datetime.now(timezone.utc)
    story_title = (title or "").strip() or chat.name or f"Chronicle of {char_name}"
    char_ids = [chat.character_id] if chat.character_id else []
    for cid in chat.additional_character_ids or []:
        if cid and cid not in char_ids:
            char_ids.append(cid)

    story = Story(
        title=story_title,
        description=f"Compiled into a Story Sandbox chapter from chat '{chat.name}' with {char_name}.",
        world_id=chat.world_id,
        character_ids=char_ids,
        lorebook_ids=list(chat.active_lorebook_ids or []),
        location_ids=[chat.location_id] if chat.location_id else [],
        scenario_id=chat.scenario_id,
        llm_model=chat.llm_model,
        persona_name=chat.persona_name,
        persona_description=chat.persona_description,
        created_at=now,
        updated_at=now,
    )
    link_to_world(session, story, chat.world_id)
    session.add(story)
    session.commit()
    session.refresh(story)

    chapter = StoryChapter(
        story_id=story.id,
        chapter_number=1,
        title=chapter_title,
        content=novelized_prose,
        beats=beats,
    )
    session.add(chapter)
    session.commit()
    session.refresh(chapter)

    return {
        "story_id": story.id,
        "title": story.title,
        "chapter_id": chapter.id,
        "chapter_title": chapter.title,
        "beats_count": len(beats),
    }


async def run_world_tick(
    session: Session,
    *,
    world_id: str,
    time_advance_label: str = "+1 Day",
    active_chat_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Simulate off-screen NPC autonomy and living-world events across `world_id`."""
    world = session.get(World, world_id)
    if not world:
        raise NotFoundError("World", world_id)

    characters = session.exec(select(Character).where(Character.world_id == world_id)).all()
    locations = session.exec(select(Location).where(Location.world_id == world_id)).all()

    char_names = [c.name for c in characters[:8]] or ["Local Factions"]
    loc_names = [loc.name for loc in locations[:8]] or [f"{world.name} Hub"]

    blocks = app_config.get_system_prompt_blocks() or {}
    tick_prompt = blocks.get("world_tick") or (
        "You are the Living World Simulation Engine. Advance the world clock and generate "
        "2-4 off-screen autonomous NPC actions or world rumors. Return ONLY valid JSON:\n"
        '`{"events": [{"actor": "...", "location": "...", "event": "...", "rumor": "..."}], "new_time_of_day": "..."}`'
    )
    llm_parsed, engine_used = await _run_llm_json(
        session,
        kind="world_tick",
        system_prompt=tick_prompt,
        user_content=(
            f"World: {world.name} — {(world.description or '')[:400]}\n"
            f"Time Advance: {time_advance_label}\n"
            f"Characters in World: {', '.join(char_names)}\n"
            f"Locations in World: {', '.join(loc_names)}"
        ),
        max_output_tokens=500,
    )

    events: List[Dict[str, Any]] = []
    if llm_parsed and isinstance(llm_parsed.get("events"), list):
        for ev in llm_parsed["events"][:4]:
            if isinstance(ev, dict) and ev.get("event"):
                events.append(
                    {
                        "actor": str(ev.get("actor") or char_names[0]),
                        "location": str(ev.get("location") or loc_names[0]),
                        "event": str(ev["event"]),
                        "rumor": str(ev.get("rumor") or ev["event"]),
                    }
                )

    if not events:
        for idx, cname in enumerate(char_names[:3]):
            loc = loc_names[idx % len(loc_names)]
            events.append(
                {
                    "actor": cname,
                    "location": loc,
                    "event": f"{cname} pursued off-screen preparations at {loc} during {time_advance_label}.",
                    "rumor": f"Word spreads around {loc} of {cname}'s recent movements.",
                }
            )

    # Rotate character default_location to reflect off-screen movement
    for idx, c in enumerate(characters[:3]):
        if idx < len(events):
            c.default_location = events[idx]["location"]
            session.add(c)

    updated_snapshot: Optional[Dict[str, Any]] = None
    if active_chat_id:
        chat = session.get(Chat, active_chat_id)
        if chat:
            snap = dict(chat.state_snapshot or {})
            wc = dict(snap.get("world_clock") or {})
            day = int(wc.get("day") or 1)
            if "day" in time_advance_label.lower():
                day += 1
            new_tod = (
                str(llm_parsed.get("new_time_of_day")).strip()
                if llm_parsed and llm_parsed.get("new_time_of_day")
                else ("Morning" if wc.get("time_of_day") == "Night" else "Night")
            )
            log = list(wc.get("chronology_log") or [])
            for ev in events[:2]:
                log.append(
                    {
                        "day": day,
                        "time": new_tod,
                        "location": ev["location"],
                        "event": f"[Living World Tick] {ev['event']}",
                    }
                )
            wc["day"] = day
            wc["time_of_day"] = new_tod
            wc["chronology_log"] = log[-30:]
            snap["world_clock"] = wc
            chat.story_time = f"Day {day}, {new_tod}"
            chat.state_snapshot = snap
            session.add(chat)
            updated_snapshot = snap

    session.commit()
    return {
        "world_id": world.id,
        "world_name": world.name,
        "time_advance_label": time_advance_label,
        "events": events,
        "engine_used": engine_used,
        "state_snapshot": updated_snapshot,
    }


async def analyze_image_to_state(
    session: Session,
    *,
    chat_id: str,
    image_path: Optional[str] = None,
    image_base64: Optional[str] = None,
) -> Dict[str, Any]:
    """Reverse Vision ('Image-to-State'): Read an image and sync outfit, mood, activity, and location into `state_snapshot`."""
    chat = session.get(Chat, chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    character = session.get(Character, chat.character_id) if chat.character_id else None
    char_name = character.name if character else "Character"

    raw_bytes: Optional[bytes] = None
    fallback_caption = ""

    if image_base64:
        clean_b64 = re.sub(r"^data:image/[^;]+;base64,", "", image_base64.strip())
        try:
            raw_bytes = base64.b64decode(clean_b64)
        except Exception as exc:
            raise ValidationError(f"Invalid base64 image payload: {exc}") from exc
    else:
        target_path = image_path
        if not target_path:
            latest_img_msg = session.exec(
                select(Message)
                .where(Message.chat_id == chat_id, Message.image_path.is_not(None))
                .order_by(Message.created_at.desc())
                .limit(1)
            ).first()
            if latest_img_msg:
                target_path = latest_img_msg.image_path
                fallback_caption = latest_img_msg.content or ""
        if not target_path and character and character.avatar_path:
            target_path = character.avatar_path

        if target_path and os.path.exists(target_path):
            try:
                with open(target_path, "rb") as f:
                    raw_bytes = f.read()
            except OSError:
                raw_bytes = None

    vision_res, vision_used = await _analyze_avatar_with_vision(
        session,
        avatar_bytes=raw_bytes,
        char_name=char_name,
        char_description=fallback_caption or (character.description if character else ""),
        use_vision=True,
    )

    snap = dict(chat.state_snapshot or {})
    outfit = (
        str(vision_res.get("outfit_description") or "").strip()
        or _infer_outfit_from_text(fallback_caption, character.description if character else "")
        or snap.get("character_outfit")
        or f"{char_name}'s visual attire"
    )
    mood = (
        str(vision_res.get("inferred_mood") or "").strip()
        or _infer_mood_from_text(fallback_caption)
        or snap.get("character_mood")
        or "Expressive"
    )
    inferred_loc = str(vision_res.get("inferred_location") or "").strip() or _infer_location_from_text(fallback_caption)

    snap["character_outfit"] = outfit
    snap["character_mood"] = mood
    wardrobe = list(snap.get("wardrobe") or [])
    if outfit and not any(isinstance(w, dict) and w.get("outfit", "").lower() == outfit.lower() for w in wardrobe):
        wardrobe.append(
            {
                "name": f"Synced Look #{len(wardrobe) + 1}",
                "outfit": outfit,
                "visual_tags": ", ".join(vision_res.get("visual_tags") or [])[:120],
            }
        )
    snap["wardrobe"] = wardrobe[:10]
    if inferred_loc:
        chat.story_location = inferred_loc
        wc = dict(snap.get("world_clock") or {})
        wc["location"] = inferred_loc
        snap["world_clock"] = wc

    snap["statekeeper_updated_at"] = datetime.now(timezone.utc).isoformat()
    chat.state_snapshot = snap
    chat.updated_at = datetime.now(timezone.utc)
    session.add(chat)
    session.commit()
    session.refresh(chat)

    return {
        "chat_id": chat.id,
        "vision_used": vision_used,
        "character_outfit": outfit,
        "character_mood": mood,
        "story_location": chat.story_location,
        "state_snapshot": chat.state_snapshot,
    }


def fast_travel_chat(
    session: Session,
    *,
    chat_id: str,
    location_id: Optional[str] = None,
    location_name: Optional[str] = None,
    time_of_day: Optional[str] = None,
) -> Dict[str, Any]:
    """Transition a chat to a new World Vault Location and log it in the World Clock."""
    chat = session.get(Chat, chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    loc: Optional[Location] = None
    if location_id:
        loc = session.get(Location, location_id)
        if not loc:
            raise NotFoundError("Location", location_id)
    elif location_name and location_name.strip():
        loc_stmt = select(Location).where(func.lower(Location.name) == location_name.strip().lower())
        if chat.world_id:
            loc_stmt = loc_stmt.where(Location.world_id == chat.world_id)
        loc = session.exec(loc_stmt).first()
        if not loc:
            loc = Location(
                name=location_name.strip()[:100],
                description=f"Discovered during fast-travel in '{chat.name}'.",
                atmosphere=time_of_day or chat.story_time or "Evening",
                world_id=chat.world_id,
                tags=["fast travel"],
            )
            session.add(loc)
            session.commit()
            session.refresh(loc)
    else:
        raise ValidationError("Specify either location_id or location_name for fast-travel")

    new_loc_name = loc.name
    new_time = (time_of_day or "").strip() or loc.atmosphere or chat.story_time or "Evening"

    chat.location_id = loc.id
    chat.story_location = new_loc_name
    chat.story_time = new_time

    snap = dict(chat.state_snapshot or {})
    snap["current_activity"] = f"Arriving at {new_loc_name}"
    wc = dict(snap.get("world_clock") or {})
    day = int(wc.get("day") or 1)
    log = list(wc.get("chronology_log") or [])
    log.append(
        {
            "day": day,
            "time": new_time,
            "location": new_loc_name,
            "event": f"Traveled to {new_loc_name}.",
        }
    )
    wc["day"] = day
    wc["time_of_day"] = new_time
    wc["location"] = new_loc_name
    wc["chronology_log"] = log[-30:]
    snap["world_clock"] = wc
    snap["statekeeper_updated_at"] = datetime.now(timezone.utc).isoformat()

    chat.state_snapshot = snap
    chat.updated_at = datetime.now(timezone.utc)
    session.add(chat)
    insert_world_state_marker(
        session,
        chat.id,
        {"location": new_loc_name, "time": new_time, "location_id": loc.id},
    )
    session.commit()
    session.refresh(chat)

    return {
        "chat_id": chat.id,
        "location_id": loc.id,
        "story_location": chat.story_location,
        "story_time": chat.story_time,
        "state_snapshot": chat.state_snapshot,
    }
