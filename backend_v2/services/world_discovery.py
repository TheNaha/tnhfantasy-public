"""World discovery service: detect new locations, factions, lore items, and characters
from story prose and chat conversations to grow the World Vault organically.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Set

from infrastructure.logging import get_logger

logger = get_logger("world_discovery")

# Common words and pronouns that look like capitalized entities but are not
STOPWORDS: Set[str] = {
    "The", "A", "An", "In", "On", "At", "To", "From", "By", "With", "About",
    "Into", "Through", "After", "Before", "During", "Without", "Under", "Over",
    "Between", "Among", "Out", "Off", "Down", "Up", "Then", "There", "Here",
    "When", "Where", "Why", "How", "What", "Who", "Which", "This", "That",
    "These", "Those", "My", "Your", "His", "Her", "Its", "Our", "Their",
    "He", "She", "It", "They", "We", "You", "I", "Me", "Him", "Us", "Them",
    "Yes", "No", "Not", "Never", "Always", "Suddenly", "Meanwhile", "Perhaps",
    "However", "Although", "Because", "Since", "Unless", "Until", "While",
    "Chapter", "Prologue", "Epilogue", "Part", "Section", "Book", "Scene",
}

# Indicators for categories
LOCATION_KEYWORDS = {
    "keep", "citadel", "castle", "fortress", "palace", "tower", "dungeon",
    "tavern", "inn", "pub", "bar", "hall", "sanctuary", "temple", "shrine",
    "forest", "woods", "grove", "swamp", "marsh", "mountain", "valley",
    "canyon", "cavern", "cave", "grotto", "lake", "river", "ocean", "sea",
    "island", "bay", "haven", "harbor", "port", "city", "town", "village",
    "outpost", "ruins", "gate", "bridge", "realm", "domain", "empire", "kingdom",
}

FACTION_KEYWORDS = {
    "order", "guild", "clan", "coven", "cult", "brotherhood", "sisterhood",
    "syndicate", "alliance", "coalition", "legion", "corps", "guard", "knights",
    "circle", "fellowship", "house", "dynasty", "sect", "tribe", "covenant",
}

LORE_KEYWORDS = {
    "artifact", "relic", "orb", "crystal", "amulet", "ring", "tome", "grimoire",
    "scroll", "blade", "sword", "staff", "scepter", "crown", "chalice", "sigil",
    "rune", "shard", "elixir", "potion", "curse", "prophecy", "ritual", "spell",
}

CHARACTER_PREFIXES = {
    "lord", "lady", "sir", "dame", "king", "queen", "prince", "princess",
    "duke", "duchess", "baron", "baroness", "captain", "commander", "general",
    "admiral", "master", "grandmaster", "archmage", "mage", "priest", "priestess",
    "elder", "doctor", "professor",
}


def _clean_name(name: str) -> str:
    """Normalize extracted entity name by stripping punctuation and leading determiners."""
    name = re.sub(r"^[Tt]he\s+", "", name.strip())
    name = re.sub(r"['\’]s\b", "", name)
    name = re.sub(r"[,.:;!?]+$", "", name)
    return name.strip()


def extract_world_entities(
    text: str,
    existing_names: Set[str] | None = None,
    max_results: int = 10,
) -> List[Dict[str, Any]]:
    """Scan prose text for candidate locations, factions, lore artifacts, and characters.

    Filters out known entities present in `existing_names` (case-insensitive)
    and returns categorized discoveries with descriptive context.
    """
    if not text or not text.strip():
        return []

    existing_lower = {n.strip().lower() for n in (existing_names or set()) if n}
    discoveries: Dict[str, Dict[str, Any]] = {}

    sentences = re.split(r"(?<=[.!?])\s+", text)

    for sentence in sentences:
        clean_sentence = sentence.strip()
        if not clean_sentence:
            continue

        # 1. Pattern: "The [Adjective]? [Location/Faction/Lore Keyword]"
        # e.g. "The Obsidian Citadel", "The Crimson Guild", "The Silver Blade"
        pattern_the = re.finditer(
            r"\b[Tt]he\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b",
            clean_sentence,
        )
        for match in pattern_the:
            candidate = _clean_name(match.group(1))
            cand_lower = candidate.lower()
            words = cand_lower.split()
            if not words or candidate in STOPWORDS or cand_lower in existing_lower:
                continue

            category = "lore"
            tags = ["discovered"]
            suggested_action = "create_lorebook_entry"

            if any(w in LOCATION_KEYWORDS for w in words):
                category = "location"
                tags.extend(["location", "world"])
                suggested_action = "create_location"
            elif any(w in FACTION_KEYWORDS for w in words):
                category = "faction"
                tags.extend(["faction", "organization"])
            elif any(w in LORE_KEYWORDS for w in words):
                category = "lore"
                tags.extend(["artifact", "lore"])

            if category in ("location", "faction", "lore") and candidate not in discoveries:
                discoveries[candidate] = {
                    "name": candidate,
                    "category": category,
                    "summary": clean_sentence,
                    "tags": tags,
                    "suggested_action": suggested_action,
                }

        # 2. Pattern: "[Title] [Capitalized Name]"
        # e.g. "Captain Valen", "Archmage Ronald", "Lady Eleanor"
        pattern_chars = re.finditer(
            r"\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\b",
            clean_sentence,
        )
        for match in pattern_chars:
            title = match.group(1).lower()
            cand_name = match.group(2)
            if title in CHARACTER_PREFIXES:
                full_name = f"{match.group(1)} {cand_name}"
                if full_name.lower() not in existing_lower and cand_name.lower() not in existing_lower:
                    if full_name not in discoveries:
                        discoveries[full_name] = {
                            "name": full_name,
                            "category": "character",
                            "summary": clean_sentence,
                            "tags": ["discovered", "npc", title],
                            "suggested_action": "create_lorebook_entry",
                        }

        # 3. Pattern: "[Capitalized Name] of [Capitalized Name]"
        # e.g. "Sword of Elidyr", "Tears of Lys", "Heart of the Mountain"
        pattern_of = re.finditer(
            r"\b([A-Z][a-z]+\s+of\s+(?:the\s+)?[A-Z][a-z]+)\b",
            clean_sentence,
        )
        for match in pattern_of:
            cand_of = _clean_name(match.group(1))
            cand_lower = cand_of.lower()
            if cand_lower not in existing_lower and cand_of not in discoveries:
                discoveries[cand_of] = {
                    "name": cand_of,
                    "category": "lore",
                    "summary": clean_sentence,
                    "tags": ["discovered", "lore"],
                    "suggested_action": "create_lorebook_entry",
                }

    results = list(discoveries.values())
    return results[:max_results]
