"""
Context Builder Service
Assembles the final prompt context for LLM inference,
handling lorebook injection, character system prompts, and context pruning.
"""
import logging
import re
from typing import Any

from sqlmodel import Session, select

from core.entities import Character, Location, LorebookEntry, MessageRole

logger = logging.getLogger("context_builder")

DEFAULT_MAX_TOKENS = 4096

# Approximate tokens-per-character ratio varies by language/content.
# English text averages ~1 token per 4 chars; code/special tokens are denser.
# We use a conservative 3.5 chars-per-token as default for mixed content.
CHARS_PER_TOKEN = 3.5


import tiktoken
from functools import lru_cache


@lru_cache(maxsize=4)
def _load_encoding(name: str):
    """Load and cache a tiktoken encoding by name (e.g. 'cl100k_base')."""
    return tiktoken.get_encoding(name)


def get_tokenizer():
    """Cache the tiktoken encoder to avoid reloading it."""
    return _load_encoding("cl100k_base")

def estimate_tokens(text: str) -> int:
    """Estimate token count from text using tiktoken.
    
    Uses cl100k_base (standard for GPT-3.5/4/Llama-3/Mistral compatible contexts).
    Falls back to a chars-per-token heuristic if tokenization fails.
    """
    if not text:
        return 0
    try:
        return len(get_tokenizer().encode(text, disallowed_special=()))
    except Exception as e:
        logger.warning(f"tiktoken failed, using heuristic: {e}")
        word_count = len(re.findall(r'\S+', text))
        char_estimate = len(text) / CHARS_PER_TOKEN
        return max(int(char_estimate), word_count)


@lru_cache(maxsize=2048)
def _cached_estimate_tokens(text: str) -> int:
    return estimate_tokens(text)


def build_character_system_prompt(character) -> str:
    """Build a SillyTavern-compatible system prompt from character fields.

    Note: mes_example is intentionally excluded here — it is injected as
    real user/assistant message pairs at the start of the chat context by
    build_chat_context so it is more "sticky" for instruction-following
    models than when placed in the system prompt.
    """
    parts = []
    if character.name:
        parts.append(f"You are {character.name}.")
    if character.description:
        parts.append(f"\n{character.description}")
    if character.personality:
        parts.append(f"\nPersonality: {character.personality}")
    if character.scenario:
        parts.append(f"\nScenario: {character.scenario}")
    return "\n".join(parts)


def parse_mes_example(mes_example: str, char_name: str = "Character", user_name: str = "User") -> list[dict[str, str]]:
    """Parse a SillyTavern mes_example block into alternating user/assistant messages.

    Handles both the classic <START> delimiter format and plain alternating lines.

    Example input:
        <START>
        {{user}}: Hello there.
        {{char}}: Why hello yourself.
        <START>
        {{user}}: How are you?
        {{char}}: Splendid, thanks!

    Returns a flat list of {"role": "user"|"assistant", "content": "..."} dicts.
    """
    if not mes_example or not mes_example.strip():
        return []

    messages: list[dict[str, str]] = []

    # Split on <START> separators (case-insensitive)
    blocks = re.split(r"<START>", mes_example, flags=re.IGNORECASE)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        for line in block.splitlines():
            line = line.strip()
            if not line:
                continue

            # Match "{{user}}: ..." or "User: ..." or "{{char}}: ..." or "Char: ..."
            user_match = re.match(r"^\{\{user\}\}\s*:\s*(.+)$", line, re.IGNORECASE)
            char_match = re.match(r"^\{\{char\}\}\s*:\s*(.+)$", line, re.IGNORECASE)
            named_user_match = re.match(rf"^{re.escape(user_name)}\s*:\s*(.+)$", line, re.IGNORECASE)
            named_char_match = re.match(rf"^{re.escape(char_name)}\s*:\s*(.+)$", line, re.IGNORECASE)

            if user_match:
                messages.append({"role": "user", "content": user_match.group(1).strip()})
            elif char_match:
                messages.append({"role": "assistant", "content": char_match.group(1).strip()})
            elif named_user_match:
                messages.append({"role": "user", "content": named_user_match.group(1).strip()})
            elif named_char_match:
                messages.append({"role": "assistant", "content": named_char_match.group(1).strip()})
            # Lines that don't match any speaker pattern are skipped (e.g. stage directions)

    return messages


def inject_lorebooks_into_system_prompt(
    system_prompt: str,
    lorebook_entries: list[dict],
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

    Priority (never pruned):
    1. System prompt messages
    2. Pinned messages (message_metadata.pinned == True, tracked via _pinned key)
    3. Example dialogue injection markers and pairs

    Priority (pruned first):
    1. Oldest non-pinned conversation messages
    """
    # Exempt from pruning only *true* system messages (kind == "system", or
    # None which covers the assembled system prompt and example-dialogue
    # markers). Narrator / image / tool messages are stored with role="system"
    # for rendering but carry a distinct `kind`, so they must remain prunable
    # like normal conversation turns — otherwise they accumulate unchecked and
    # eventually evict the entire real conversation.
    def _is_exempt_system(m: dict) -> bool:
        if m.get("role") != "system":
            return False
        return m.get("_kind") in (None, "system")

    system_msgs = [m for m in messages if _is_exempt_system(m)]
    non_system_msgs = [m for m in messages if not _is_exempt_system(m)]

    system_tokens = sum(_cached_estimate_tokens(m.get("content", "")) for m in system_msgs)
    remaining_budget = max_tokens - system_tokens

    if remaining_budget <= 0:
        logger.warning("System prompt alone exceeds token budget")
        return system_msgs

    # Separate pinned from unpinned so we never drop pinned messages
    pinned_msgs = [m for m in non_system_msgs if m.get("_pinned")]
    unpinned_msgs = [m for m in non_system_msgs if not m.get("_pinned")]

    pinned_tokens = sum(_cached_estimate_tokens(m.get("content", "")) for m in pinned_msgs)
    remaining_budget -= pinned_tokens

    total_tokens = sum(_cached_estimate_tokens(m.get("content", "")) for m in unpinned_msgs)

    while total_tokens > remaining_budget and len(unpinned_msgs) > 2:
        removed = unpinned_msgs.pop(0)
        total_tokens -= _cached_estimate_tokens(removed.get("content", ""))

    # Reconstruct in original order: system → unpinned (oldest first) → pinned at end
    # Actually preserve original relative order for pinned messages
    result = []
    result.extend(system_msgs)
    # Merge back preserving original order using content-based keys so fresh
    # DB-reconstructed objects still match their filtered counterparts.
    def _msg_key(m: dict) -> tuple:
        return (m.get("role"), m.get("content", "")[:200])

    pinned_keys = {_msg_key(m) for m in pinned_msgs}
    unpinned_keys = {_msg_key(m) for m in unpinned_msgs}
    for m in messages:
        if _is_exempt_system(m):
            continue
        key = _msg_key(m)
        if key in unpinned_keys or key in pinned_keys:
            result.append(m)
    return result


def build_system_prompt_sections(
    session: Session,
    character=None,
    characters: list = None,
    lorebook_ids: list[str] = None,
    persona_name: str | None = None,
    persona_description: str | None = None,
    story_time: str | None = None,
    story_location: str | None = None,
    location_id: str | None = None,
    system_prompt_override: str | None = None,
    append_system_prompt: str | None = None,
    include_roleplay_default: bool = True,
    _lorebook_query: str | None = None,
    story_genre: str | None = None,
    story_memory: str | None = None,
    story_scenario: str | None = None,
    story_character_ids: list[str] | None = None,
    active_character_id: str | None = None,
    character_id: str | None = None,
    _memory_query: str | None = None,
    location_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Build the ordered list of system-prompt sections that make up a chat context.

    Priority / assembly order
    ─────────────────────────
    1. If ``system_prompt_override`` is set it REPLACES everything character-related
       (char card + char.append_system_prompt) but the remaining blocks (lorebook,
       world-state, roleplay_default) still apply unless also overridden.

    2. Otherwise the character block is assembled in order:
         a. character.system_prompt  (or auto-built from char fields)
         b. character.append_system_prompt  (per-character extra instructions)

    3. Per-chat append (``append_system_prompt`` arg — comes from chat.append_system_prompt)
       is injected after the character block.

    4. Global ``roleplay_default`` config block.

    5. Lorebook entries (world information).

    6. World-state (time / location).

    7. Story-specific blocks (genre, memory, characters) when provided.

    Each section dict: {"key", "label", "content", "source"}
    source ∈ "override" | "character" | "char_append" | "chat_append" | "config" | "lorebook" | "world_state" | "story_genre" | "story_memory" | "story_scenario" | "story_characters"
    """
    sections: list[dict[str, Any]] = []

    chars_to_process = characters if characters is not None else ([character] if character else [])
    primary_char = chars_to_process[0] if chars_to_process else (character if character else None)

    active_char = None
    if active_character_id:
        for c in chars_to_process:
            if c.id == active_character_id:
                active_char = c
                break

    if active_char:
        sections.append({
            "key": "active_character",
            "label": f"Speaking as — {active_char.name or active_char.id}",
            "content": f"[You are currently speaking as {active_char.name or active_char.id}. Stay in character and respond from their perspective.]",
            "source": "active_character"
        })

    for char in chars_to_process:
        if system_prompt_override and system_prompt_override.strip():
            # Override replaces the character card + append blocks entirely
            # (see priority note in the docstring above).
            break
        char_prompt = char.system_prompt or build_character_system_prompt(char)
        if char_prompt:
            sections.append({
                "key": f"character_{char.id}",
                "label": f"Character — {char.name or char.id}",
                "content": char_prompt,
                "source": "character"
            })
        if char.append_system_prompt:
            sections.append({
                "key": f"char_append_{char.id}",
                "label": f"Character Append — {char.name or char.id}",
                "content": char.append_system_prompt,
                "source": "char_append"
            })

    if system_prompt_override and system_prompt_override.strip():
        sections.append({
            "key": "chat_prompt",
            "label": "Chat System Prompt",
            "content": system_prompt_override.strip(),
            "source": "override",
        })

    # Per-chat append (legacy / extra instructions for this chat only)
    if append_system_prompt and append_system_prompt.strip():
        sections.append({
            "key": "chat_append",
            "label": "Per-chat extra instructions",
            "content": append_system_prompt.strip(),
            "source": "chat_append",
        })

    # User persona description — tells the LLM who the user's character is
    if persona_description and persona_description.strip():
        user_label = persona_name or "User"
        sections.append({
            "key": "persona",
            "label": f"User persona — {user_label}",
            "content": f"[About {user_label}]\n{persona_description.strip()}",
            "source": "persona",
        })

    if include_roleplay_default:
        from config import get_system_prompt_blocks
        roleplay_default = (get_system_prompt_blocks() or {}).get("roleplay_default", "")
        if roleplay_default:
            sections.append({
                "key": "roleplay_default",
                "label": "Roleplay instructions (global)",
                "content": roleplay_default,
                "source": "config",
            })

    if sections:
        # Apply SillyTavern template variable substitution to character/override blocks
        from services.chat_utils import substitute_tavern_vars

        substitutable = {"character", "override", "char_append", "chat_append", "persona"}
        for section in sections:
            if section["source"] in substitutable:
                section["content"] = substitute_tavern_vars(
                    section["content"],
                    char=(primary_char.name if primary_char else "") or "",
                    user=persona_name or "User",
                )

    if lorebook_ids:
        # Build a query string from the most recent context for semantic matching.
        # We use this to find the most relevant lorebook entries rather than
        # dumping every entry from every active lorebook.
        _query_text = _lorebook_query or ""
        if not _query_text:
            if persona_name:
                _query_text += f"{persona_name} "
            if story_time:
                _query_text += f"{story_time} "
            if story_location:
                _query_text += f"{story_location} "

        try:
            from services.rag_pipeline import search_lorebook_entries

            entries = search_lorebook_entries(
                session, lorebook_ids, _query_text, limit=5
            )
        except Exception as _lb_err:
            logger.warning("lorebook_injection_failed: %s", str(_lb_err))
            # Absolute fallback: load all entries from all lorebooks (old behaviour)
            entries = []
            for lb_id in lorebook_ids:
                lb_entries = session.exec(
                    select(LorebookEntry).where(LorebookEntry.lorebook_id == lb_id)
                ).all()
                entries.extend(lb_entries)

        if entries:
            lore_block = "\n".join(f"- {e.content}" for e in entries)
            sections.append({
                "key": "lorebook",
                "label": f"World information ({len(entries)} entries)",
                "content": f"[World Information]\n{lore_block}",
                "source": "lorebook",
            })

    if story_time or story_location:
        world_state_parts = []
        if story_time:
            world_state_parts.append(f"Current Story Time: {story_time}")
        if story_location:
            world_state_parts.append(f"Current Location: {story_location}")
        sections.append({
            "key": "world_state",
            "label": "World state",
            "content": "\n".join(world_state_parts),
            "source": "world_state",
        })

    # Inject the linked Location entity's description into the system prompt
    # so the LLM has rich sensory details about the setting.
    if location_id:
        location = session.get(Location, location_id)
        if location:
            loc_parts = [f"[Location: {location.name}]"]
            if location.description:
                loc_parts.append(location.description)
            if location.atmosphere:
                loc_parts.append(f"Atmosphere: {location.atmosphere}")
            if location.tags:
                loc_parts.append(f"Tags: {', '.join(location.tags)}")
            sections.append({
                "key": "location_detail",
                "label": f"Location — {location.name}",
                "content": "\n".join(loc_parts),
                "source": "lorebook",  # treated as world information
            })

    # Inject multiple Location entities (for story continuation context)
    if location_ids:
        locations = session.exec(
            select(Location).where(Location.id.in_(location_ids))
        ).all()
        if locations:
            loc_parts = ["[Active Locations]"]
            for loc in locations:
                loc_parts.append(f"Location: {loc.name}")
                if loc.description:
                    loc_parts.append(f"  {loc.description}")
                if loc.atmosphere:
                    loc_parts.append(f"  Atmosphere: {loc.atmosphere}")
                if loc.tags:
                    loc_parts.append(f"  Tags: {', '.join(loc.tags)}")
            sections.append({
                "key": "story_locations",
                "label": f"Story locations ({len(locations)})",
                "content": "\n".join(loc_parts),
                "source": "lorebook",  # treated as world information
            })

    if story_genre:
        sections.append({
            "key": "story_genre",
            "label": "Story genre",
            "content": f"Genre: {story_genre}",
            "source": "story_genre",
        })

    if story_memory:
        sections.append({
            "key": "story_memory",
            "label": "Global story memory",
            "content": f"[Author's Note / Global Memory]\n{story_memory}",
            "source": "story_memory",
        })

    if story_scenario:
        sections.append({
            "key": "story_scenario",
            "label": "Story scenario",
            "content": f"[Scenario Directive]\n{story_scenario}",
            "source": "story_scenario",
        })

    if story_character_ids:
        characters_content = []
        chars = session.exec(
            select(Character).where(Character.id.in_(story_character_ids))
        ).all()
        char_map = {c.id: c for c in chars}
        for char_id in story_character_ids:
            char = char_map.get(char_id)
            if char:
                char_text = f"Character: {char.name}\n"
                if char.description:
                    char_text += f"Description: {char.description}\n"
                if char.personality:
                    char_text += f"Personality: {char.personality}\n"
                if char.scenario:
                    char_text += f"Scenario: {char.scenario}\n"
                characters_content.append(char_text)
        if characters_content:
            sections.append({
                "key": "story_characters",
            "label": f"Story characters ({len(characters_content)})",
            "content": "\n\n".join(characters_content),
            "source": "story_characters",
        })

    # Character long-term memories (semantic retrieval)
    if character_id:
        try:
            from services.rag_pipeline import search_memories

            _mem_query = _memory_query or _lorebook_query or ""
            _mem_top_k = 10

            _memories = search_memories(
                session, character_id, _mem_query, limit=_mem_top_k
            )
            if _memories:
                mem_block = "\n".join(f"- {m.content}" for m in _memories)
                sections.append({
                    "key": "character_memories",
                    "label": f"Character memories ({len(_memories)} retrieved)",
                    "content": f"[Relevant Memories]\n{mem_block}",
                    "source": "character_memories",
                })
        except Exception as _mem_err:
            logger.warning("character_memory_injection_failed: %s", str(_mem_err))

    return sections


def build_chat_context(
    session: Session,
    messages: list,
    characters: list = None,
    lorebook_ids: list[str] = None,
    max_context_tokens: int = DEFAULT_MAX_TOKENS,
    persona_name: str | None = None,
    persona_description: str | None = None,
    story_time: str | None = None,
    story_location: str | None = None,
    location_id: str | None = None,
    system_prompt_override: str | None = None,
    append_system_prompt: str | None = None,
    story_genre: str | None = None,
    story_memory: str | None = None,
    story_scenario: str | None = None,
    story_character_ids: list[str] | None = None,
    active_character_id: str | None = None,
    character_id: str | None = None,
    location_ids: list[str] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Build the complete chat context.
    Returns: (system_prompt, messages_list)

    Args:
        system_prompt_override: Replaces the character card entirely.
        append_system_prompt:   Extra instructions injected after the character
                                block (sourced from chat.append_system_prompt).
        persona_description:    Description of the user's persona — who they are
                                in this roleplay (sourced from chat.persona_description).
        max_context_tokens: Maximum token budget for the full context window.
    """
    # Build a lorebook query string from recent conversation for semantic matching
    _lorebook_query = ""
    if persona_name:
        _lorebook_query += f"{persona_name} "
    if story_location:
        _lorebook_query += f"{story_location} "
    if story_time:
        _lorebook_query += f"{story_time} "
    # Add the last few message contents for richer context
    if messages:
        recent = [m for m in messages[-6:] if getattr(m, 'role', None) in (MessageRole.USER, MessageRole.CHAR)]
        _lorebook_query += " ".join(m.content[:200] for m in recent if m.content)

    sections = build_system_prompt_sections(
        session,
        characters=characters,
        lorebook_ids=lorebook_ids,
        persona_name=persona_name,
        persona_description=persona_description,
        story_time=story_time,
        story_location=story_location,
        location_id=location_id,
        system_prompt_override=system_prompt_override,
        append_system_prompt=append_system_prompt,
        _lorebook_query=_lorebook_query or None,
        story_genre=story_genre,
        story_memory=story_memory,
        story_scenario=story_scenario,
        story_character_ids=story_character_ids,
        active_character_id=active_character_id,
        character_id=character_id,
        _memory_query=_lorebook_query or None,
        location_ids=location_ids,
    )
    system_prompt = "\n\n".join(s["content"] for s in sections)

    # ── Example dialogue (mes_example) → injected as real message history ──
    # Placed at the very start of the conversation so models treat them as
    # demonstrations of the character's voice, not as system instructions.
    # Wrapped in a lightweight "example session" marker so the model knows
    # these are illustrative, not real prior turns.
    example_messages: list[dict[str, str]] = []
    primary_char = (characters or [None])[0]
    if primary_char and not system_prompt_override and getattr(primary_char, "mes_example", None):
        raw_examples = parse_mes_example(
            primary_char.mes_example,
            char_name=primary_char.name or "Character",
            user_name=persona_name or "User",
        )
        if raw_examples:
            # Wrap with a system marker so the model understands these are
            # demonstrations, not real history.
            example_messages.append({
                "role": "system",
                "content": "[Example dialogue — the following exchanges demonstrate the character's voice and style. They are not part of the current conversation.]",
            })
            example_messages.extend(raw_examples)
            example_messages.append({
                "role": "system",
                "content": "[End of example dialogue. The actual conversation begins now.]",
            })

    msg_list = []
    for msg in messages:
        if isinstance(msg, dict):
            role = msg.get("role")
            content = msg.get("content", "")
            meta = msg.get("message_metadata", {})
            if meta.get("source") == "world_state":
                continue
        else:
            meta = getattr(msg, "message_metadata", None) or {}
            if meta.get("source") == "world_state":
                continue
            if msg.role == MessageRole.USER:
                role = "user"
            elif msg.role == MessageRole.CHAR:
                role = "assistant"
            elif msg.role == MessageRole.SYSTEM:
                role = "system"
            else:
                continue
            content = msg.content
            kind = getattr(msg, "kind", None)
            is_pinned = bool(getattr(msg, "pinned", False) or meta.get("pinned"))
            # Serialize `kind` so prune_context can treat narrator/image/tool
            # messages as prunable conversation turns instead of exempt
            # "system" messages (role stays 'system' for rendering).
            msg_list.append({
                "role": role,
                "content": content,
                "_pinned": is_pinned,
                "_kind": kind.value if kind else None,
            })
            continue

        if meta.get("source") == "world_state":
            continue
        if role == "user" or role == "assistant" or role == "system":
            is_pinned = bool(meta.get("pinned"))
            msg_list.append({"role": role, "content": content, "_pinned": is_pinned})

    if system_prompt:
        all_msgs = [{"role": "system", "content": system_prompt}] + example_messages + msg_list
    else:
        all_msgs = example_messages + msg_list

    all_msgs = prune_context(all_msgs, system_prompt, [], max_context_tokens)

    # Strip the internal _pinned/_kind helper keys before returning so
    # unknown fields never leak into provider-bound LLM payloads.
    for m in all_msgs:
        m.pop("_pinned", None)
        m.pop("_kind", None)

    return system_prompt, all_msgs


async def build_chat_context_async(
    messages: list,
    **kwargs: Any,
) -> tuple[str, list[dict[str, Any]]]:
    """Run build_chat_context off the event loop with a dedicated session.

    The context build runs local SBERT embedding (CPU-bound) plus pgvector
    semantic queries; executing it on the event loop stalls every other
    request. A fresh session is opened inside the worker thread so no
    request-scoped session is ever touched from another thread — callers
    must NOT pass their own session here.
    """
    import asyncio

    from infrastructure.database import get_session_sync

    def _run() -> tuple[str, list[dict[str, Any]]]:
        with get_session_sync() as ctx_session:
            return build_chat_context(ctx_session, messages, **kwargs)

    return await asyncio.to_thread(_run)


async def build_system_prompt_sections_async(
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Run build_system_prompt_sections off the event loop with a dedicated session."""
    import asyncio

    from infrastructure.database import get_session_sync

    def _run() -> list[dict[str, Any]]:
        with get_session_sync() as ctx_session:
            return build_system_prompt_sections(ctx_session, **kwargs)

    return await asyncio.to_thread(_run)
