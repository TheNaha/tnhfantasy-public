"""
Context Builder Service
Assembles the final prompt context for LLM inference,
handling lorebook injection, character system prompts, and context pruning.
"""
import logging
import re
from typing import Any

from sqlmodel import Session, select

from core.entities import LorebookEntry, MessageRole

logger = logging.getLogger("context_builder")

DEFAULT_MAX_TOKENS = 4096

# Approximate tokens-per-character ratio varies by language/content.
# English text averages ~1 token per 4 chars; code/special tokens are denser.
# We use a conservative 3.5 chars-per-token as default for mixed content.
CHARS_PER_TOKEN = 3.5


def estimate_tokens(text: str) -> int:
    """Estimate token count from text using a simple heuristic.
    
    Uses word-boundary splitting + character length to approximate tokenization
    without requiring a tokenizer dependency. For English/mixed content:
    - Splits on whitespace/punctuation to get rough word count
    - Applies chars-per-token ratio as a secondary signal
    - Returns the higher of the two estimates for safety
    """
    if not text:
        return 0
    word_count = len(re.findall(r'\S+', text))
    char_estimate = len(text) / CHARS_PER_TOKEN
    return max(int(char_estimate), word_count)


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
    injection_mode: str = "system_prompt",
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
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[dict[str, Any]]:
    """
    Prune context to fit within token budget.
    
    Priority (keep first):
    1. System prompt (never pruned)
    2. Most recent messages
    3. Lorebook entries (reduce count if needed)
    
    Priority (prune first):
    1. Oldest conversation messages
    2. Lorebook entries (reduce count)
    3. Character scenario (never prune name/personality/description)
    """
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system_msgs = [m for m in messages if m.get("role") != "system"]

    system_tokens = sum(estimate_tokens(m.get("content", "")) for m in system_msgs)
    remaining_budget = max_tokens - system_tokens

    if remaining_budget <= 0:
        logger.warning("System prompt alone exceeds token budget")
        return system_msgs

    total_tokens = sum(estimate_tokens(m.get("content", "")) for m in non_system_msgs)

    while total_tokens > remaining_budget and len(non_system_msgs) > 2:
        removed = non_system_msgs.pop(0)
        total_tokens -= estimate_tokens(removed.get("content", ""))

    return system_msgs + non_system_msgs


def build_chat_context(
    session: Session,
    messages: list,
    character=None,
    lorebook_ids: list[str] = None,
    injection_mode: str = "system_prompt",
    max_context_tokens: int = DEFAULT_MAX_TOKENS,
    persona_name: str | None = None,
    story_time: str | None = None,
    story_location: str | None = None,
    system_prompt_override: str | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Build the complete chat context.
    Returns: (system_prompt, messages_list)
    
    Args:
        max_context_tokens: Maximum token budget for the full context window.
        system_prompt_override: Per-chat override that wins over character.system_prompt.
    """
    system_prompt = ""
    if system_prompt_override:
        system_prompt = system_prompt_override
    elif character:
        if character.system_prompt:
            system_prompt = character.system_prompt
        else:
            system_prompt = build_character_system_prompt(character)

    if system_prompt:
        # Apply SillyTavern template variable substitution
        import re
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        _replacements = {
            "char": (character.name if character else "") or "",
            "user": persona_name or "User",
            "time": now.strftime("%H:%M"),
            "date": now.strftime("%Y-%m-%d"),
        }

        def _replace(m):
            key = m.group(1).strip().lower()
            if key.startswith("random::"):
                import random
                opts = [o.strip() for o in key[len("random::"):].split("::") if o.strip()]
                return random.choice(opts) if opts else m.group(0)
            return _replacements.get(key, m.group(0))

        system_prompt = re.sub(r"\{\{([^}]+)\}\}", _replace, system_prompt)
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

    if story_time or story_location:
        world_state_parts = []
        if story_time:
            world_state_parts.append(f"Current Story Time: {story_time}")
        if story_location:
            world_state_parts.append(f"Current Location: {story_location}")
        
        system_prompt += f"\n\n[World State]\n" + "\n".join(world_state_parts)

    msg_list = []
    for msg in messages:
        if msg.role == MessageRole.USER:
            role = "user"
        elif msg.role == MessageRole.CHAR:
            role = "assistant"
        elif msg.role == MessageRole.SYSTEM:
            # System-injected messages (tool results, narration) go as system role
            role = "system"
        else:
            # STORY role beats are internal narrative metadata — skip in LLM context
            continue
        msg_list.append({"role": role, "content": msg.content})

    if system_prompt:
        all_msgs = [{"role": "system", "content": system_prompt}] + msg_list
    else:
        all_msgs = msg_list

    all_msgs = prune_context(all_msgs, system_prompt, [], max_context_tokens)

    return system_prompt, all_msgs
