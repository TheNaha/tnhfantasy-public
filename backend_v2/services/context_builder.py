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

    Priority (never pruned):
    1. System prompt messages
    2. Pinned messages (message_metadata.pinned == True, tracked via _pinned key)
    3. Example dialogue injection markers and pairs

    Priority (pruned first):
    1. Oldest non-pinned conversation messages
    """
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system_msgs = [m for m in messages if m.get("role") != "system"]

    system_tokens = sum(estimate_tokens(m.get("content", "")) for m in system_msgs)
    remaining_budget = max_tokens - system_tokens

    if remaining_budget <= 0:
        logger.warning("System prompt alone exceeds token budget")
        return system_msgs

    # Separate pinned from unpinned so we never drop pinned messages
    pinned_msgs = [m for m in non_system_msgs if m.get("_pinned")]
    unpinned_msgs = [m for m in non_system_msgs if not m.get("_pinned")]

    pinned_tokens = sum(estimate_tokens(m.get("content", "")) for m in pinned_msgs)
    remaining_budget -= pinned_tokens

    total_tokens = sum(estimate_tokens(m.get("content", "")) for m in unpinned_msgs)

    while total_tokens > remaining_budget and len(unpinned_msgs) > 2:
        removed = unpinned_msgs.pop(0)
        total_tokens -= estimate_tokens(removed.get("content", ""))

    # Reconstruct in original order: system → unpinned (oldest first) → pinned at end
    # Actually preserve original relative order for pinned messages
    result = []
    result.extend(system_msgs)
    # Merge back preserving original order
    pinned_set = {id(m) for m in pinned_msgs}
    unpinned_set = {id(m) for m in unpinned_msgs}
    for m in messages:
        if m.get("role") == "system":
            continue
        if id(m) in unpinned_set or id(m) in pinned_set:
            result.append(m)
    return result


def build_system_prompt_sections(
    session: Session,
    character=None,
    lorebook_ids: list[str] = None,
    persona_name: str | None = None,
    persona_description: str | None = None,
    story_time: str | None = None,
    story_location: str | None = None,
    system_prompt_override: str | None = None,
    append_system_prompt: str | None = None,
    include_roleplay_default: bool = True,
    _lorebook_query: str | None = None,
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

    Each section dict: {"key", "label", "content", "source"}
    source ∈ "override" | "character" | "char_append" | "chat_append" | "config" | "lorebook" | "world_state"
    """
    sections: list[dict[str, Any]] = []

    if character:
        char_prompt = character.system_prompt or build_character_system_prompt(character)
        if char_prompt:
            sections.append({
                "key": "character",
                "label": f"Character — {character.name or character.id}",
                "content": char_prompt,
                "source": "character",
            })
        # Per-character append (applies to every chat using this character)
        char_append = getattr(character, "append_system_prompt", None)
        if char_append and char_append.strip():
            sections.append({
                "key": "char_append",
                "label": f"Character extra — {character.name or character.id}",
                "content": char_append.strip(),
                "source": "char_append",
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

        substitutable = {"character", "override", "char_append", "chat_append", "persona"}
        for section in sections:
            if section["source"] in substitutable:
                section["content"] = re.sub(r"\{\{([^}]+)\}\}", _replace, section["content"])

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

        entries: list[dict] = []
        try:
            from services.embedding_service import EmbeddingService
            from sqlalchemy import text as _sql_text

            _svc = EmbeddingService()
            _TOP_K = 5  # max entries per lorebook when using semantic search

            for lb_id in lorebook_ids:
                lb_entries = session.exec(
                    select(LorebookEntry).where(LorebookEntry.lorebook_id == lb_id)
                ).all()

                if not lb_entries:
                    continue

                # Separate entries that have embeddings from those that don't
                embedded = [e for e in lb_entries if e.embedding is not None]
                keyword_only = [e for e in lb_entries if e.embedding is None]

                if embedded and _query_text.strip():
                    # Semantic: embed the query and sort by cosine distance
                    try:
                        q_vec = _svc.generate_embedding(_query_text.strip())
                        # pgvector cosine distance via raw SQL for reliability
                        from sqlalchemy import func, cast
                        from pgvector.sqlalchemy import Vector as _Vector

                        results = session.exec(
                            select(LorebookEntry)
                            .where(
                                LorebookEntry.lorebook_id == lb_id,
                                LorebookEntry.embedding.is_not(None),
                            )
                            .order_by(
                                LorebookEntry.embedding.cosine_distance(q_vec)
                            )
                            .limit(_TOP_K)
                        ).all()
                        entries.extend([{"content": e.content, "keys": e.keys} for e in results])
                    except Exception as _sem_err:
                        logger.warning(
                            "lorebook_semantic_fallback",
                            lorebook_id=lb_id,
                            error=str(_sem_err),
                        )
                        # Fall through to keyword matching
                        embedded = []
                        keyword_only = lb_entries

                if not embedded or not _query_text.strip():
                    # Keyword matching: check if any key appears in the query or recent context
                    for e in keyword_only[:_TOP_K]:
                        if not e.keys:
                            entries.append({"content": e.content, "keys": e.keys})
                            continue
                        query_lower = _query_text.lower() if _query_text else ""
                        if any(k.lower() in query_lower for k in e.keys):
                            entries.append({"content": e.content, "keys": e.keys})
                    # If nothing matched keywords, include first N entries as fallback
                    if not entries:
                        entries.extend(
                            [{"content": e.content, "keys": e.keys} for e in keyword_only[:_TOP_K]]
                        )

        except Exception as _lb_err:
            logger.warning("lorebook_injection_failed", error=str(_lb_err))
            # Absolute fallback: load all entries from all lorebooks (old behaviour)
            for lb_id in lorebook_ids:
                lb_entries = session.exec(
                    select(LorebookEntry).where(LorebookEntry.lorebook_id == lb_id)
                ).all()
                entries.extend([{"content": e.content, "keys": e.keys} for e in lb_entries])

        if entries:
            lore_block = "\n".join(f"- {e['content']}" for e in entries)
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

    return sections


def build_chat_context(
    session: Session,
    messages: list,
    character=None,
    lorebook_ids: list[str] = None,
    injection_mode: str = "system_prompt",
    max_context_tokens: int = DEFAULT_MAX_TOKENS,
    persona_name: str | None = None,
    persona_description: str | None = None,
    story_time: str | None = None,
    story_location: str | None = None,
    system_prompt_override: str | None = None,
    append_system_prompt: str | None = None,
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
        character=character,
        lorebook_ids=lorebook_ids,
        persona_name=persona_name,
        persona_description=persona_description,
        story_time=story_time,
        story_location=story_location,
        system_prompt_override=system_prompt_override,
        append_system_prompt=append_system_prompt,
        _lorebook_query=_lorebook_query or None,
    )
    system_prompt = "\n\n".join(s["content"] for s in sections)

    # ── Example dialogue (mes_example) → injected as real message history ──
    # Placed at the very start of the conversation so models treat them as
    # demonstrations of the character's voice, not as system instructions.
    # Wrapped in a lightweight "example session" marker so the model knows
    # these are illustrative, not real prior turns.
    example_messages: list[dict[str, str]] = []
    if character and not system_prompt_override and getattr(character, "mes_example", None):
        raw_examples = parse_mes_example(
            character.mes_example,
            char_name=character.name or "Character",
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
        meta = getattr(msg, "message_metadata", None) or {}
        if meta.get("source") == "world_state":
            # World-state divider markers are UI-only — world state lives in the
            # system prompt's [World State] section, so skip them in LLM context.
            continue
        if meta.get("pinned"):
            # Pinned messages are always included; they are handled separately
            # in prune_context so we still add them to the list here.
            pass
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
        is_pinned = bool(getattr(msg, "pinned", False) or meta.get("pinned"))
        msg_list.append({"role": role, "content": msg.content, "_pinned": is_pinned})

    if system_prompt:
        all_msgs = [{"role": "system", "content": system_prompt}] + example_messages + msg_list
    else:
        all_msgs = example_messages + msg_list

    all_msgs = prune_context(all_msgs, system_prompt, [], max_context_tokens)

    # Strip the internal _pinned helper key before returning
    for m in all_msgs:
        m.pop("_pinned", None)

    return system_prompt, all_msgs
