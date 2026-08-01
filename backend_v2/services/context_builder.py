"""
Context Builder Service
Assembles the final prompt context for LLM inference,
handling lorebook injection, character system prompts, and context pruning.
"""
import logging
from typing import Any

from sqlmodel import Session, select

from core.entities import LorebookEntry, MessageRole

logger = logging.getLogger("context_builder")

MAX_CHARS_APPROX = 3000  # Rough token limit approximation (chars / 4 ≈ tokens)

def build_character_system_prompt(character) -> str:
    """Build a SillyTavern-compatible system prompt from character fields."""
    parts = []
    if character.name:
        parts.append(f"You are {character.name}.")
    if character.description:
        parts.append(f"\n{character.description}")
    if character.personality:
        parts.append(f"\nPersonality: {character.personality}")
    if character.scenario:
        parts.append(f"\nScenario: {character.scenario}")
    if character.mes_example:
        parts.append(f"\nExample dialogue:\n{character.mes_example}")
    return "\n".join(parts)


def inject_lorebooks_into_system_prompt(
    system_prompt: str,
    lorebook_entries: list[dict],
    injection_mode: str = "system_prompt",  # "system_prompt" or "messages"
) -> str:
    """Inject relevant lorebook entries into system prompt."""
    if not lorebook_entries:
        return system_prompt
    lore_block = "\n\n[World Information]\n"
    for entry in lorebook_entries:
        lore_block += f"- {entry['content']}\n"
    return system_prompt + lore_block


def prune_context(
    messages: list[dict[str, Any]],
    system_prompt: str,
    lorebook_entries: list[dict],
    max_chars: int = MAX_CHARS_APPROX * 4,
) -> list[dict[str, Any]]:
    """
    Prune context to fit within limit.
    Priority (prune first to last):
    1. Oldest conversation messages
    2. Lorebook entries (reduce count)
    3. Character scenario (never prune name/personality/description)
    """
    system_msgs = [m for m in messages if m.get("role") == "system"]
    user_msgs = [m for m in messages if m.get("role") != "system"]
    
    total = sum(len(m.get("content", "")) for m in messages)
    
    while total > max_chars and len(user_msgs) > 2:
        removed = user_msgs.pop(0)
        total -= len(removed.get("content", ""))
    
    return system_msgs + user_msgs


def build_chat_context(
    session: Session,
    messages: list,  # DB Message objects
    character=None,
    lorebook_ids: list[str] = None,
    injection_mode: str = "system_prompt",
    max_context_chars: int = MAX_CHARS_APPROX * 4,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Build the complete chat context.
    Returns: (system_prompt, messages_list)
    """
    system_prompt = ""
    if character:
        if character.system_prompt:
            system_prompt = character.system_prompt
        else:
            system_prompt = build_character_system_prompt(character)
            
    if lorebook_ids:
        entries = []
        for lb_id in lorebook_ids:
            lb_entries = session.exec(
                select(LorebookEntry).where(LorebookEntry.lorebook_id == lb_id)
            ).all()
            entries.extend([{"content": e.content, "keys": e.keys} for e in lb_entries])
        
        if entries:
            system_prompt = inject_lorebooks_into_system_prompt(
                system_prompt, entries, injection_mode
            )
            
    msg_list = []
    for msg in messages:
        role = "user" if msg.role == MessageRole.USER else "assistant"
        msg_list.append({"role": role, "content": msg.content})
        
    if system_prompt:
        all_msgs = [{"role": "system", "content": system_prompt}] + msg_list
    else:
        all_msgs = msg_list
        
    all_msgs = prune_context(all_msgs, system_prompt, [], max_context_chars)
    
    return system_prompt, all_msgs
