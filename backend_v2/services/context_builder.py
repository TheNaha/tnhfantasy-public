"""
Context Builder Service
Assembles the final prompt context for LLM inference,
handling lorebook injection, character system prompts, and context pruning.
"""
import logging
import re
from functools import lru_cache
from typing import Any

import tiktoken
from cachetools import TTLCache
from core.entities import (
    Character,
    Location,
    LorebookEntry,
    MessageKind,
    MessageRole,
    Persona,
    Scenario,
    Story,
)
from sqlmodel import Session, select

logger = logging.getLogger("context_builder")

DEFAULT_MAX_TOKENS = 4096

# Bounds on the context trace stamped onto a message. A trace is per-row data,
# so it cannot be unbounded; these are chosen to cover a real conversation while
# keeping the stamp to a few KB.
TRACE_TURN_LIMIT = 60
TRACE_SECTION_LIMIT = 24
TRACE_CONTENT_PREVIEW = 48

# Floor for the *system* portion of the budget.
#
# `prune_context` only ever removed conversation messages, and only while more
# than two unpinned ones remained. So a prompt where the system block alone
# exceeds the budget came back as the system prompt and NOTHING else — a paid
# LLM call with no conversation in it. Worse, the system prompt itself was never
# shortened, so a large character card or lorebook could exceed any budget on its
# own and no amount of message pruning would have helped.
#
# The system block is now capped too, and the conversation is guaranteed at least
# this share of the budget when there is anything to guarantee it for. The
# system text is kept whole up to this cap because truncating mid-card produces
# a prompt that reads as broken; beyond it, the tail is dropped, which at least
# keeps the identity block and the instruction header.
SYSTEM_TOKEN_FLOOR = 512

# Minimum number of conversation messages that survive pruning, regardless of how
# much they exceed the budget. Two is enough for a user turn and the reply to it;
# below that the model has nothing to continue.
MIN_UNPINNED_MESSAGES = 2

# How much of a message contributes to the lorebook relevance query.
#
# The query is not the prompt — it is the text used to rank world-info entries by
# embedding similarity. Short turns contribute all of themselves. A long one is
# truncated from the END, not the start, because the end is what a continuation
# has to react to: a story chapter's opening is the setup that was already
# resolved, and `story_illustrate_system_prompt` in `stories.py` already slices
# the same way with `[-2000:]`. Taking `[:200]` for a 30,000-word chapter
# therefore threw away the entire scene the user had just written and searched
# on its preamble instead.
LOREBOOK_QUERY_CHARS = 500


def _msg_field(message: Any, field: str, default: Any = None) -> Any:
    """Read `field` off a message that may be a dict OR a SQLModel row.

    `build_chat_context` has two kinds of caller and they disagree on the type
    they pass. The chat paths (`chats.py`, `agent_simulation.py`,
    `world_integration_service.py`) pass ORM `Message` rows. Both story paths
    pass a list of **dicts** — `stories.py` builds
    `[{"role": "user", "content": chapter.content}]`, because a story chapter is
    not a chat message and has no `Message` row to point at.

    Reading those dicts with `getattr(m, 'role', None)` returns `None`, because a
    dict has no attribute `role`. That is not a loud failure: `None` is simply
    not in the role set, the list comes back empty, and the caller proceeds with
    whatever it has. That is exactly what happened — the story paths' lorebook
    query was always empty, so `search_lorebook_entries` skipped semantic search
    and returned `entries[:limit]`, i.e. the five newest (or, on the constant
    path, the five oldest) entries per lorebook. Story continuation got
    recency-ordered world info and the 30,000 words the user had just written
    never selected any.

    The message-list normalization lower down in this function already
    branches on `isinstance(msg, dict)`, so the two representations are a known
    part of the contract here rather than a surprise. This is the same branch,
    factored out, so the query and the list cannot disagree about what a message
    is.

    `MessageRole` is a `str` enum, so a dict's `"user"` compares equal to
    `MessageRole.USER` and no normalisation is needed on either side.
    """
    if isinstance(message, dict):
        return message.get(field, default)
    return getattr(message, field, default)


def _lorebook_query_text(message: Any) -> str:
    """The slice of one message that should feed the lorebook relevance query."""
    content = _msg_field(message, "content", "") or ""
    if not isinstance(content, str) or not content:
        return ""
    if len(content) <= LOREBOOK_QUERY_CHARS:
        return content
    return content[-LOREBOOK_QUERY_CHARS:]


# A message is only trimmed when it is at least this large AND alone over budget.
#
# `MIN_UNPINNED_MESSAGES` is authoritative for message COUNT, and it has been
# since it was introduced — the tests pin that a tight budget prunes the
# conversation down to the floor and then stops, rather than mangling what is
# left. Truncation must not quietly overturn that, so it is scoped to the case it
# exists for: a single turn so large that no provider would accept it. 8192 is
# below every real context window, so a message under it is sendable whatever
# `max_tokens` is configured to, and shrinking it would only lose content the
# caller asked for.
TRUNCATION_MIN_TOKENS = 8192

# How much of a message the escalation pass must be able to leave behind.
#
# `prune_context` guarantees a floor of `MIN_UNPINNED_MESSAGES` turns, and
# proportional trimming divides whatever budget is left between them. When the
# budget is smaller than this per message, the division produces one character
# plus a truncation marker per message — the request fits and the conversation is
# gone. A caller whose budget is that tight has a misconfiguration, not a
# request to shred, so the pass declines and says so.
MIN_RETAINED_TOKENS = 128

# Backstop on the trim loop. Each pass strictly shrinks the content, so two or
# three always converge; this only bounds the pathological case.
_TRIM_MAX_PASSES = 4


def _truncate_system_msgs(
    system_msgs: list[dict], budget_tokens: int
) -> list[dict]:
    """Shorten the system block to `budget_tokens`, keeping its order.

    The first system message carries the instruction header and the character's
    identity, so it is trimmed from the END of the combined text: whatever is
    dropped is the tail of the last block (a lorebook dump, an appended author's
    note), not the part that tells the model who it is.
    """
    if not system_msgs or budget_tokens <= 0:
        return system_msgs

    keep_chars = max(1, int(budget_tokens * CHARS_PER_TOKEN))
    out: list[dict] = []
    remaining = keep_chars
    for msg in system_msgs:
        if remaining <= 0:
            break
        content = msg.get("content", "") or ""
        if len(content) <= remaining:
            out.append(msg)
            remaining -= len(content)
            continue
        out.append({**msg, "content": content[:remaining] + "\n\n[...truncated to fit the context budget]"})
        remaining = 0
    return out

# Approximate tokens-per-character ratio varies by language/content.
# English text averages ~1 token per 4 chars; code/special tokens are denser.
# We use a conservative 3.5 chars-per-token as default for mixed content.
CHARS_PER_TOKEN = 3.5

# Bounds for the lorebook *fallback* path — the one used when semantic search
# itself is unavailable. It has no ranking to lean on, so it takes the oldest
# entries in insertion order, which is why it needs both a per-lorebook scan cap
# and a total entry cap. Without them, a world book of a few thousand entries
# went into the system prompt whole.
LOREBOOK_SCAN_CAP = 200
LOREBOOK_FALLBACK_ENTRIES = 50

# How many lorebook entries reach the system prompt, per turn.
#
# Not a "nice" number — a budget. Every one of them is injected verbatim into a
# paid system prompt on every single turn, so this is the one knob that decides
# how much of a month's inference bill the World Vault spends. It was a bare `5`
# written at each call site, twice, in the same function, so the two paths could
# not be re-budgeted together and neither could be measured.
#
# The semantic path now appends always-on entries *within* this budget
# (`search_lorebook_entries` calls `_append_keyless`), so the ceiling holds
# across both sources rather than being a per-source allowance.
LOREBOOK_ENTRY_BUDGET = 5


_TOKEN_CACHE = TTLCache(maxsize=2048, ttl=300)

# Text longer than this is tokenised without being cached. See `_estimate_cached`.
# 64 KiB is well past any single chat message and comfortably inside one
# context window, so nothing that is re-read per turn loses its cache.
TOKEN_CACHE_MAX_CHARS = 64 * 1024


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


def _estimate_cached(text: str) -> int:
    """Token estimate with a 5-minute TTL cache (cachetools TTLCache).

    The plain lru_cache on full message text can grow unbounded across long
    campaigns, pinning large strings in memory. The TTL cache evicts entries
    after 5 minutes, bounding memory usage in long-running chats/stories.

    The bound is in **characters, not entries**. `TTLCache(maxsize=2048)` is 2048
    *values*, and the key here is the whole message text: 2048 short prompts is
    nothing, 2048 chapter-sized messages is hundreds of megabytes pinned for
    five minutes. One bound has to be in the dimension that actually grows, so
    long text skips the cache entirely rather than evicting everything else to
    make room for it.
    """
    if len(text) > TOKEN_CACHE_MAX_CHARS:
        return estimate_tokens(text)
    cached = _TOKEN_CACHE.get(text)
    if cached is not None:
        return cached
    result = estimate_tokens(text)
    _TOKEN_CACHE[text] = result
    return result


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

    system_tokens = sum(_estimate_cached(m.get("content", "")) for m in system_msgs)
    remaining_budget = max_tokens - system_tokens

    if remaining_budget <= 0:
        # The system block alone blew the budget. It used to `return
        # system_msgs` here — an untrimmed system prompt and no conversation at
        # all, so the caller's paid LLM request carried a character sheet and no
        # turn to answer. And because the system prompt itself was never
        # shortened, this was reachable on any large card or lorebook, not an
        # edge case.
        #
        # Reserve `SYSTEM_TOKEN_FLOOR` for it, truncate the system text to that
        # floor if it is still over, and carry on with whatever budget is left
        # for the conversation. The caller is not told, so this must not raise.
        system_budget = min(system_tokens, SYSTEM_TOKEN_FLOOR)
        remaining_budget = max(0, max_tokens - system_budget)
        if system_tokens > system_budget:
            logger.warning(
                "system_prompt_truncated: system=%d budget=%d max=%d",
                system_tokens, system_budget, max_tokens,
            )
            system_msgs = _truncate_system_msgs(system_msgs, system_budget)

    # Separate pinned from unpinned so we never drop pinned messages
    pinned_msgs = [m for m in non_system_msgs if m.get("_pinned")]
    unpinned_msgs = [m for m in non_system_msgs if not m.get("_pinned")]

    pinned_tokens = sum(_estimate_cached(m.get("content", "")) for m in pinned_msgs)
    remaining_budget -= pinned_tokens

    total_tokens = sum(_estimate_cached(m.get("content", "")) for m in unpinned_msgs)

    # The loop used to be `while ... and len(unpinned_msgs) > 2`, so a history of
    # one or two messages was never pruned no matter how large. A story
    # continuation is exactly that shape — a single message carrying a
    # 30,000-word chapter — and it went to the provider whole against a 4096
    # budget. The floor is now a named constant rather than a magic 2.
    while total_tokens > remaining_budget and len(unpinned_msgs) > MIN_UNPINNED_MESSAGES:
        removed = unpinned_msgs.pop(0)
        total_tokens -= _estimate_cached(removed.get("content", ""))

    # Still over budget once the floor is reached: the remaining turns are
    # themselves enormous. The story-continuation shape — one message carrying a
    # whole chapter — and a freshly-imported SillyTavern chat both land here.
    # Neither dropping them (nothing left to continue) nor handing the provider a
    # prompt it will refuse is acceptable, so the oversized messages are trimmed
    # from the end, keeping their beginnings, which is where the instruction and
    # the scene setup live.
    #
    # This runs AFTER the ordering rebuild. Doing it before meant substituting a
    # new dict, and the merge keys surviving messages by `id()`, so a substituted
    # object was no longer found in the original list.
    over_budget = total_tokens > remaining_budget
    # ...but only actionable while there is budget left to trim into. Pinned
    # messages are subtracted first, so a pinned block larger than the whole
    # budget drives `remaining_budget` to zero or below and no amount of
    # trimming the unpinned remainder can fix it. That case used to be silent.
    trimmable = over_budget and remaining_budget > 0
    if over_budget and not trimmable:
        logger.warning(
            "conversation_over_budget_untrimmable: total=%d budget=%d pinned=%d "
            "pinned_tokens=%d — pinned messages alone exceed the budget",
            total_tokens, max_tokens, len(pinned_msgs), pinned_tokens,
        )

    # Reconstruct in original order: system → unpinned (oldest first) → pinned at end
    # Actually preserve original relative order for pinned messages
    result = []
    result.extend(system_msgs)
    # Merge back preserving original order using a collision-resistant key.
    # Prefer the message's `_id` (a UUID propagated from the DB or dict) so that
    # two messages with identical role+content-prefix never silently merge.
    # Fallback includes the message's original list position as a tiebreaker.
    def _msg_key(m: dict, idx: int = 0) -> tuple:
        mid = m.get("_id")
        if mid is not None:
            return ("_id", mid)
        return (m.get("role"), m.get("content", "")[:200], idx)

    msg_index = {id(m): i for i, m in enumerate(messages)}
    pinned_keys = {_msg_key(m, msg_index[id(m)]) for m in pinned_msgs}
    unpinned_keys = {_msg_key(m, msg_index[id(m)]) for m in unpinned_msgs}
    for i, m in enumerate(messages):
        if _is_exempt_system(m):
            continue
        key = _msg_key(m, i)
        if key in unpinned_keys or key in pinned_keys:
            result.append(m)

    if trimmable:
        # Scale every remaining conversation message by the same ratio, rather
        # than spending the whole budget on the largest one and leaving the rest
        # to overflow. Per-message trimming does not compose: filling the budget
        # with message A leaves nothing for message B, so a two-message history
        # of 40,000 tokens each still went out at 47,180.
        marker = "\n\n[...truncated to fit the context budget]"
        marker_tokens = _estimate_cached(marker)

        def _truncation_candidates(seq: list[dict], only_individually_oversized: bool) -> list[int]:
            """Indices of messages this pass is allowed to shorten.

            `only_individually_oversized` is the conservative gate: a message
            qualifies only if it is at or above `TRUNCATION_MIN_TOKENS` *and* on
            its own larger than the whole remaining budget. The escalation pass
            drops both conditions — the total is over budget, and proportional
            trimming is the only arithmetic that composes — but it still leaves
            system and pinned messages alone.
            """
            out = []
            for i, m in enumerate(seq):
                if _is_exempt_system(m) or m.get("_pinned"):
                    continue
                tokens = _estimate_cached(m.get("content", ""))
                if only_individually_oversized and not (
                    tokens >= TRUNCATION_MIN_TOKENS and tokens > remaining_budget
                ):
                    continue
                out.append(i)
            return out

        # Two gates, and the second one is the point.
        #
        # The conservative gate keeps the documented behaviour: only a message
        # that is individually unsendable is shortened, so an ordinary turn the
        # caller asked for survives whole. But "individually unsendable" is not
        # the same condition as "the request fits". Two mid-size turns of ~5.2k
        # tokens each are both perfectly sendable, and their SUM is 10,503 tokens
        # against a 4,096 budget — measured, and it shipped, silently, with no
        # `conversation_truncated` line, because the candidate list came back
        # empty and the loop gave up. The budget is both what the caller
        # configured and what the provider refuses to exceed, so a total overflow
        # has to be resolved even when no single message is at fault.
        #
        # The escalation gate is therefore "every unpinned turn, no size floor".
        for only_individually_oversized in (True, False):
            indices = _truncation_candidates(result, only_individually_oversized)
            if not indices:
                continue

            # Share the budget proportionally across the candidates. Repeating
            # until it fits matters: `_estimate_cached` splits on whitespace, so
            # cutting at a raw character offset can change the word count in
            # either direction and a single pass left the result 12 tokens over a
            # 4096 budget — which is a failure the existing tests correctly
            # reject. Each pass strictly shrinks the content, so this converges;
            # the iteration cap is a backstop, not the mechanism.
            def _body(i: int) -> str:
                """Message content with any marker from a previous pass removed.

                Without this the loop appends a second marker on top of the first,
                so the content grows on every pass and the estimate drifts
                upward — which is how the repeat-to-converge version ended up
                stacking `\\n\\n[\\n\\n[\\n\\n[…` and finishing 20 tokens OVER.
                """
                content = result[i].get("content", "") or ""
                return content[: -len(marker)] if content.endswith(marker) else content

            for _ in range(_TRIM_MAX_PASSES):
                bodies = {i: _body(i) for i in indices}
                current = sum(_estimate_cached(b) for b in bodies.values())
                if current <= 0:
                    break
                usable = max(0, remaining_budget - marker_tokens * len(indices))
                if not only_individually_oversized and usable < MIN_RETAINED_TOKENS * len(indices):
                    logger.warning(
                        "conversation_over_budget_budget_too_small: budget=%d "
                        "needed_for_markers_and_content=%d messages=%d",
                        remaining_budget, MIN_RETAINED_TOKENS * len(indices), len(indices),
                    )
                    break
                ratio = usable / current
                for i, body in bodies.items():
                    keep = max(1, int(len(body) * ratio))
                    if keep < len(body):
                        result[i] = {**result[i], "content": body[:keep] + marker}
                landed = sum(
                    _estimate_cached(_body(i)) + marker_tokens for i in indices
                )
                if landed <= remaining_budget:
                    break

            logger.warning(
                "conversation_truncated: tokens=%d budget=%d messages=%d escalated=%s",
                current, remaining_budget, len(indices), not only_individually_oversized,
            )
    return result


def _load_constant_lorebook_entries(
    session: Session,
    lorebook_ids: list[str],
    limit: int = 5,
) -> list[LorebookEntry]:
    """Load keyless ("constant") lorebook entries, which are always active.

    SillyTavern world-book entries without keys need no keyword match to fire,
    and that is exactly what a ``character_book`` imported with a character card
    produces. Semantic search already prefers them, but it yields nothing when
    RAG is disabled or the query matches nothing, so this is the fallback that
    keeps imported lorebook context in the prompt.
    """
    entries: list[LorebookEntry] = []
    try:
        for lb_id in lorebook_ids:
            rows = session.exec(
                select(LorebookEntry)
                .where(LorebookEntry.lorebook_id == lb_id)
                .order_by(LorebookEntry.created_at)
                .limit(limit * 2)
            ).all()
            entries.extend(e for e in rows if not e.keys)
            if len(entries) >= limit:
                break
    except Exception as exc:  # pragma: no cover - defensive, never breaks a chat
        logger.warning("lorebook_constant_fallback_failed: %s", str(exc))
        return []
    return entries[:limit]


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
    # Author's note is a message-level injection (build_chat_context) — accepted
    # here so chat_context_kwargs can feed both builders uniformly; unused.
    authors_note: str | None = None,
    authors_note_depth: int | None = None,
    _lorebook_query: str | None = None,
    story_genre: str | None = None,
    story_memory: str | None = None,
    story_pov: str | None = None,
    story_scenario: str | None = None,
    story_character_ids: list[str] | None = None,
    active_character_id: str | None = None,
    character_id: str | None = None,
    _memory_query: str | None = None,
    location_ids: list[str] | None = None,
    world_name: str | None = None,
    world_description: str | None = None,
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

    `world_name` / `world_description` carry the owning World. The World
    entity is the one grouping in this system that used to reach none of this:
    `Chat.world_id` and `Story.world_id` were written and maintained by
    `world_ownership.py` and read by nothing, so filing a cast under a World
    changed nothing about what the model was told. Its membership is merged into
    `lorebook_ids` / `location_ids` / `story_scenario` by the *caller*
    (`chat_context_kwargs`), which is where the ids are resolved; the World only
    contributes its own prose here, so a World with an empty description still
    behaves exactly as before.
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

    if world_name or world_description:
        world_parts = [f"[Setting: {world_name}]" if world_name else "[Setting]"]
        if world_description:
            world_parts.append(world_description.strip())
        sections.append({
            "key": "world",
            "label": f"World — {world_name or 'setting'}",
            "content": "\n".join(world_parts),
            "source": "world",
        })

    # Character ids already emitted as a `character_<id>` card. `story_characters`
    # re-renders name/description/personality/scenario for the same characters,
    # so on a chat with a primary card both fired and the same prose was paid
    # for twice on every single turn.
    emitted_character_ids: set[str] = set()

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
            emitted_character_ids.add(char.id)
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

        # One embedding for the whole turn.
        #
        # Lorebook retrieval and memory retrieval query the SAME string, and
        # each used to run its own `_try_embedding` — two MiniLM forward passes,
        # serially, on the critical path of every chat turn. MiniLM is small but
        # it is a GPU/CPU forward on ~3 KB of text, and it was paid twice for
        # identical input.
        #
        # Computed once here and handed to both. `search_lorebook_entries` now
        # takes the same precomputed-vector parameter `search_memories` already
        # had, so the two retrieval paths are symmetric.
        from services.rag_pipeline import _is_postgres, _try_embedding, rag_enabled

        _q_vec = (
            _try_embedding(_query_text)
            if (rag_enabled() and _query_text and _is_postgres(session))
            else None
        )

        try:
            from services.rag_pipeline import search_lorebook_entries

            entries = search_lorebook_entries(
                session, lorebook_ids, _query_text,
                limit=LOREBOOK_ENTRY_BUDGET,
                q_vec=_q_vec,
                q_vec_computed=True,
            )
        except Exception as _lb_err:
            logger.warning("lorebook_injection_failed: %s", str(_lb_err))
            # Absolute fallback: search the lorebooks directly, when the
            # semantic search itself is what broke.
            #
            # This used to load EVERY entry of EVERY lorebook with no `LIMIT`
            # and paste them all into the system prompt. It is the one path in
            # this file with *less* bounding than the two paths around it:
            # `search_lorebook_entries` scans `max(limit, 50)` rows and
            # `_load_constant_lorebook_entries` takes `limit * 2` per lorebook
            # and stops early. A SillyTavern world book with a few thousand
            # entries went wholesale into the prompt, which is both an
            # unbounded token bill and a prompt the model cannot use.
            entries = []
            for lb_id in lorebook_ids:
                lb_entries = session.exec(
                    select(LorebookEntry)
                    .where(LorebookEntry.lorebook_id == lb_id)
                    .order_by(LorebookEntry.created_at)
                    .limit(LOREBOOK_SCAN_CAP)
                ).all()
                entries.extend(lb_entries)
                if len(entries) >= LOREBOOK_FALLBACK_ENTRIES:
                    break
            entries = entries[:LOREBOOK_FALLBACK_ENTRIES]

        if not entries:
            # Semantic search returns nothing when RAG is off or nothing
            # matched; constant (keyless) entries are still always-on lore.
            entries = _load_constant_lorebook_entries(
                session, lorebook_ids, limit=LOREBOOK_ENTRY_BUDGET
            )

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
        # `chat_context_kwargs` sets BOTH `location_id` and `location_ids` from
        # the single `Chat.location_id` column, so a chat with a linked location
        # rendered the same description twice — once as `[Location: X]` and again
        # inside `[Active Locations]` — on every turn, for every message. The
        # single-id block above is the richer one, so the list block is the
        # right place to drop the overlap.
        extra_ids = [lid for lid in location_ids if lid != location_id]
        if extra_ids:
            locations = session.exec(
                select(Location).where(Location.id.in_(extra_ids))
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

    if story_pov:
        sections.append({
            "key": "story_pov",
            "label": "Narration perspective",
            "content": f"Narration perspective: write in {story_pov} person. Maintain this perspective consistently.",
            "source": "story_pov",
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
            # Skip anyone already emitted as a full card above. This block
            # re-renders the same four fields, so on any chat with a primary
            # character it was duplicating that character's prose in the paid
            # system prompt. The card is the richer rendering (it honours
            # `system_prompt`), so it wins.
            if not char or char.id in emitted_character_ids:
                continue
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
                session, character_id, _mem_query, limit=_mem_top_k,
                q_vec=_q_vec if _mem_query == _lorebook_query else None,
                q_vec_computed=_mem_query == _lorebook_query,
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

    # Template substitution runs LAST, over every section. It used to run right
    # after the character/override blocks — before the lorebook, world-state,
    # location, scenario and character sections were appended — and to be limited
    # to a five-`source` allowlist. So twelve of the seventeen sections, and in
    # particular `story_scenario` (the one template that is *written* with
    # `{{user}}`), reached the model with its macros unexpanded.
    if sections:
        from services.chat_utils import substitute_tavern_vars

        # {{original}} is ST's "prompt an override would replace" macro, so it
        # resolves to the primary character's assembled prompt.
        original_prompt = ""
        if primary_char is not None:
            original_prompt = primary_char.system_prompt or build_character_system_prompt(primary_char) or ""

        for section in sections:
            section["content"] = substitute_tavern_vars(
                section["content"],
                char=(primary_char.name if primary_char else "") or "",
                user=persona_name or "User",
                persona_description=persona_description or "",
                original=original_prompt,
            )

    return sections


def speaker_context(messages: list, session=None) -> tuple[dict[str, str], int]:
    """Who is speaking in this transcript, as `(id -> name, distinct speakers)`.

    Both answers come from the messages themselves rather than from the chat's
    character list, because that is what actually determines whether an
    `assistant` turn is ambiguous: a group chat stores `character_id` per
    message, and a CHAR row for a character that is not the chat's primary is
    indistinguishable from one that is unless the name is sent with it.

    Derived from the data rather than passed in, so every caller gets it for
    free — the four copies of the turn mapping this replaces each had the
    messages in hand and none of them used them.

    One extra query, and only when there is more than one distinct speaker,
    which is the only case the result is needed for.
    """
    ids: set[str] = set()
    for msg in messages or []:
        if isinstance(msg, dict):
            value = msg.get("character_id")
        else:
            value = getattr(msg, "character_id", None)
        if value:
            ids.add(value)

    names: dict[str, str] = {}
    if len(ids) > 1 and session is not None:
        from core.entities import Character

        rows = session.exec(select(Character).where(Character.id.in_(list(ids)))).all()
        for row in rows:
            if row.name:
                names[row.id] = row.name
    return names, len(ids)


def context_trace_digest(
    *,
    system_prompt: str,
    sections: list[dict[str, Any]],
    turns: list[dict[str, Any]],
    input_messages: list,
    speaker_names: dict[str, str] | None,
    speaker_total: int,
    roleplay_config: dict | None,
    max_context_tokens: int,
) -> dict[str, Any]:
    """A compact record of what a context build actually produced.

    Size counts and labels, never the text itself. A digest rather than a full
    copy of the payload is deliberate — this is stamped onto a message row, and
    a chapter of prose per turn would multiply every reply's storage by the
    length of the conversation. What the inspector needs to answer "why did it
    reply like that?" is WHICH turns were present, WHICH were dropped, and what
    each one WAS — and none of that needs the words.

    Caps on the lists keep a pathological chat from writing an unbounded blob
    onto one row. A truncated trace says so rather than pretending to be
    complete, which is the whole point of it existing.
    """
    from config import get_roleplay_context_config

    if roleplay_config is None:
        roleplay_config = get_roleplay_context_config()

    # Which stored messages became turns at all, and which were skipped, is a
    # per-input record rather than something recoverable from the output: a
    # skipped turn leaves no row to count.
    dropped: list[str] = []
    seen_ids = {t.get("_id") for t in turns}
    for msg in input_messages or []:
        msg_id = msg.get("id") if isinstance(msg, dict) else getattr(msg, "id", None)
        if not msg_id or msg_id in seen_ids:
            continue
        meta = (
            msg.get("message_metadata", {})
            if isinstance(msg, dict)
            else (getattr(msg, "message_metadata", None) or {})
        )
        # `world_state` is derived state, rebuilt from the world on every build,
        # so its absence from the turns is correct and reporting it would make
        # every trace claim something was dropped. Anything else disappearing is
        # worth showing.
        if meta.get("source") == "world_state":
            continue
        dropped.append(meta.get("source") or "unknown")

    capped_turns = turns[-TRACE_TURN_LIMIT:]
    capped_sections = sections[:TRACE_SECTION_LIMIT]

    trace: dict[str, Any] = {
        "v": 1,
        "config": {
            "label_speakers": bool(roleplay_config.get("label_speakers", True)),
            "narrator_prefix": roleplay_config.get("narrator_prefix", "[Narration]"),
            "image_prefix": roleplay_config.get("image_prefix", "[Scene]"),
        },
        "speakers": {
            "count": max(speaker_total, 1),
            "named": sorted({n for n in (speaker_names or {}).values() if n}),
        },
        "sections": [
            {
                "label": sec.get("label"),
                "source": sec.get("source"),
                "chars": len(sec.get("content") or ""),
            }
            for sec in capped_sections
        ],
        "turns": [
            {
                "role": t.get("role"),
                # The LABEL the payload carries, which is the field the mapping
                # decides and the thing a user cannot otherwise verify: whether a
                # narration was labelled, and whether a speaker was named.
                "label": (
                    (t.get("content") or "")[:TRACE_CONTENT_PREVIEW]
                    if t.get("role") == "assistant"
                    else None
                ),
                "kind": t.get("_kind"),
                "pinned": bool(t.get("_pinned")),
                "chars": len(t.get("content") or ""),
            }
            for t in capped_turns
        ],
        "dropped": dropped,
        "budget_tokens": max_context_tokens,
        "system_prompt_chars": len(system_prompt or ""),
        "truncated": len(turns) > TRACE_TURN_LIMIT or len(sections) > TRACE_SECTION_LIMIT,
    }
    return trace


def llm_turn_for(
    msg,
    *,
    speaker_names: dict[str, str] | None = None,
    participants: int = 1,
    roleplay_config: dict | None = None,
    as_user: bool = False,
) -> dict[str, Any] | None:
    """The LLM-payload turn for one stored message, or None to skip it.

    One implementation, and the reason it is a function is that it used to be
    four copies of the same if/elif — `build_chat_context_with_sections` at 1144,
    `chats.py`'s suggest assembly at 2075, its import path at 1929, and
    `orchestrator_service.py`'s follow-up rebuild at 529. They had already
    drifted: one mapped narrator to `system`, one dropped it, one wrapped system
    messages in brackets, and NONE of them carried the speaker. So a group chat
    reached the model as a wall of anonymous `assistant` turns, and the
    `MessageKind` refinement — the thing that fixed the pruning exemption — was
    computed, used for pruning, and then stripped before the payload went out.

    The rules, in order:

    * `kind` decides the channel, not `role`. A narrator turn and an image turn
      are stored as `role=SYSTEM` for rendering, and sending them as
      `role: "system"` is the bug: on the Google path, `translate_messages_google`
      concatenates EVERY system message into the system prompt and drops it from
      the conversation, so a narration is torn out of its chronological place
      and appended to the end of the instructions, unmarked. Both are now
      `assistant` turns with a label, which keeps their position and tells the
      model what they are.
    * The speaker's name prefixes their turn whenever a chat has more than one
      participant. In a single-character chat the character's name is the whole
      subject of the system prompt, so labelling every turn is noise.
    * `world_state` markers are dropped — they are derived state, rebuilt from
      the world on every context build, and re-sending them makes the model
      treat its own summary as history.

    `as_user` mirrors the two speaking channels instead of mapping them
    straight. The suggest-reply and impersonate paths ask the model to write as
    the USER, so from its perspective a prior user message is `assistant` and a
    character message is the `user` it is replying to. That is the same rule with
    two labels swapped, so it is a parameter here rather than a fourth copy of
    the if/elif — which is what it was, and the copies had already drifted on
    how they treated narrator turns.

    `participants` is a COUNT, not a list, so a caller that only knows how many
    characters are in play can call this without loading them.
    """
    import config as app_config

    if roleplay_config is None:
        roleplay_config = app_config.get_roleplay_context_config()

    if isinstance(msg, dict):
        role = msg.get("role")
        content = msg.get("content", "")
        meta = msg.get("message_metadata", {}) or {}
        kind = msg.get("kind")
        character_id = msg.get("character_id")
    else:
        role = getattr(msg, "role", None)
        content = getattr(msg, "content", "") or ""
        meta = getattr(msg, "message_metadata", None) or {}
        kind = getattr(msg, "kind", None)
        character_id = getattr(msg, "character_id", None)

    role_value = getattr(role, "value", role)
    kind_value = getattr(kind, "value", kind)

    if meta.get("source") == "world_state":
        return None

    label_speakers = bool(roleplay_config.get("label_speakers", True))

    if role_value == MessageRole.USER.value:
        if not content:
            return None
        # Mirrored only when the model is the one speaking as the user.
        return {"role": "assistant" if as_user else "user", "content": content}

    if role_value == MessageRole.CHAR.value:
        if not content:
            return None
        if as_user:
            return {"role": "user", "content": content}
        if label_speakers and participants > 1:
            name = (speaker_names or {}).get(character_id) if character_id else None
            if name:
                return {"role": "assistant", "content": f"{name}: {content}"}
        return {"role": "assistant", "content": content}

    if role_value == MessageRole.SYSTEM.value:
        if not content:
            return None
        if kind_value == MessageKind.NARRATOR.value:
            prefix = roleplay_config.get("narrator_prefix", "[Narration]")
            # An empty prefix means "send it bare", which is what a caller who
            # has taught the model the convention wants.
            return {
                "role": "assistant",
                "content": f"{prefix} {content}" if prefix else content,
            }
        if kind_value == MessageKind.IMAGE.value:
            prefix = roleplay_config.get("image_prefix", "[Scene]")
            return {
                "role": "assistant",
                "content": f"{prefix} {content}" if prefix else content,
            }
        if meta.get("source") == "narrator":
            # A narrator row written before `kind` existed. Same treatment, so
            # an old transcript does not silently keep the hoisting bug.
            prefix = roleplay_config.get("narrator_prefix", "[Narration]")
            return {
                "role": "assistant",
                "content": f"{prefix} {content}" if prefix else content,
            }
        # A plain system turn (an injected note, an imported marker) is the one
        # case that really is an instruction.
        return {"role": "system", "content": content}

    return None


def build_chat_context(
    session: Session,
    messages: list,
    **kwargs: Any,
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
    system_prompt, all_msgs, _sections = build_chat_context_with_sections(
        session, messages, **kwargs
    )
    return system_prompt, all_msgs


def build_chat_context_with_sections(
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
    authors_note: str | None = None,
    authors_note_depth: int | None = None,
    story_genre: str | None = None,
    story_memory: str | None = None,
    story_pov: str | None = None,
    story_scenario: str | None = None,
    story_character_ids: list[str] | None = None,
    active_character_id: str | None = None,
    character_id: str | None = None,
    location_ids: list[str] | None = None,
    world_name: str | None = None,
    world_description: str | None = None,
    include_roleplay_default: bool = True,
    trace_out: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Build the complete chat context AND the sections it was assembled from.

    ``trace_out`` is an out-param, not a return value. Pass a dict and it is
    filled with a digest of exactly what was assembled — which sections, which
    turns, what was dropped and why, and which speaker each one is — taken
    BEFORE the internal ``_pinned`` / ``_kind`` / ``_id`` keys are stripped, so
    it is the only place that information still exists. An out-param rather
    than a fourth return element because this function has two async wrappers
    and a dozen callers, and a reply inspector is not a reason to touch all of
    them.

    Same function as :func:`build_chat_context`, returning a third element: the
    per-section breakdown. It exists because a caller that wanted both used to
    pay for two assemblies — `build_system_prompt_sections` runs an embedding
    forward pass and two pgvector queries, and `build_chat_context` runs it again
    internally. `GET /chats/{id}/system-prompt` did exactly that, and the
    breakdown it returned was the one built WITHOUT `messages` (so with a
    lorebook query that had no conversation in it) and was then discarded, while
    the prompt beside it came from the second pass. One pass, one answer.
    """
    # Build a lorebook query string from recent conversation for semantic matching
    _lorebook_query = ""
    if persona_name:
        _lorebook_query += f"{persona_name} "
    if story_location:
        _lorebook_query += f"{story_location} "
    if story_time:
        _lorebook_query += f"{story_time} "
    # Add the last few message contents for richer context.
    #
    # Reads through `_msg_field` so the two story paths, which pass dicts, are
    # included. This single `getattr` was the whole bug: for a dict it returned
    # None, `recent` was always empty, and the query stayed "" — see
    # `_msg_field`. The tail-biased slice is `_lorebook_query_text`.
    if messages:
        recent = [
            m for m in messages[-6:]
            if _msg_field(m, "role") in (MessageRole.USER, MessageRole.CHAR)
        ]
        # Newest FIRST, joined with a separator the embedding model actually
        # tokenises. This looks like a cosmetic change and is not: the six
        # message tails total ~3 KB, `EmbeddingService` calls `model.encode`
        # with no `max_seq_length`, and sentence-transformers silently truncates
        # to 512 tokens. Ordered oldest-first — as this was — the embedding was
        # of the *oldest* of the last six messages and never contained the
        # user's actual turn, so on a long chat lorebook activation keyed on
        # stale context.
        _lorebook_query += " ".join(
            text
            for text in (_lorebook_query_text(m) for m in reversed(recent))
            if text
        )

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
        story_pov=story_pov,
        story_scenario=story_scenario,
        story_character_ids=story_character_ids,
        active_character_id=active_character_id,
        character_id=character_id,
        _memory_query=_lorebook_query or None,
        location_ids=location_ids,
        world_name=world_name,
        world_description=world_description,
        include_roleplay_default=include_roleplay_default,
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

    speaker_names, speaker_total = speaker_context(messages, session)

    # Read once per context build rather than per message: it is a config read
    # behind a `get_config()` merge, and the loop below touches it per turn.
    import config as app_config

    roleplay_config = app_config.get_roleplay_context_config()

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
            turn = llm_turn_for(
                msg,
                speaker_names=speaker_names,
                participants=max(speaker_total, 1),
                roleplay_config=roleplay_config,
            )
            if turn is None:
                continue
            kind = getattr(msg, "kind", None)
            is_pinned = bool(getattr(msg, "pinned", False) or meta.get("pinned"))
            # Serialize `kind` so prune_context can treat narrator/image/tool
            # messages as prunable conversation turns instead of exempt
            # "system" messages. The turn's own `role` is what goes to the
            # provider; this is the pruning hint, and it is no longer derived
            # from the role — see `llm_turn_for`.
            msg_list.append({
                **turn,
                "_pinned": is_pinned,
                "_kind": kind.value if kind else None,
                "_id": getattr(msg, "id", None),
            })
            continue

        if meta.get("source") == "world_state":
            continue
        if role == "user" or role == "assistant" or role == "system":
            is_pinned = bool(meta.get("pinned"))
            msg_list.append({"role": role, "content": content, "_pinned": is_pinned, "_id": msg.get("id")})

    if system_prompt:
        all_msgs = [{"role": "system", "content": system_prompt}] + example_messages + msg_list
    else:
        all_msgs = example_messages + msg_list

    all_msgs = prune_context(all_msgs, system_prompt, [], max_context_tokens)

    # Author's Note — deliberately injected AFTER pruning so a note the user
    # wrote always survives, even in long chats. Depth N places it N messages
    # from the tail (SillyTavern convention); depth 0 pins it to the very end.
    if authors_note and authors_note.strip():
        depth = max(0, authors_note_depth if authors_note_depth is not None else 4)
        floor = 1 if all_msgs and all_msgs[0].get("role") == "system" else 0
        insert_at = max(floor, len(all_msgs) - min(depth, len(all_msgs)))
        all_msgs.insert(insert_at, {
            "role": "system",
            "content": f"[Author's Note]\n{authors_note.strip()}",
        })

    if isinstance(trace_out, dict):
        trace_out.update(
            context_trace_digest(
                system_prompt=system_prompt,
                sections=sections,
                turns=all_msgs,
                input_messages=messages,
                speaker_names=speaker_names,
                speaker_total=speaker_total,
                roleplay_config=roleplay_config,
                max_context_tokens=max_context_tokens,
            )
        )

    # Strip the internal _pinned/_kind/_id helper keys before returning so
    # unknown fields never leak into provider-bound LLM payloads.
    for m in all_msgs:
        m.pop("_pinned", None)
        m.pop("_kind", None)
        m.pop("_id", None)

    return system_prompt, all_msgs, sections


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
    system_prompt, msg_list, _sections = await build_chat_context_with_sections_async(
        messages, **kwargs
    )
    return system_prompt, msg_list


async def build_chat_context_with_sections_async(
    messages: list,
    **kwargs: Any,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """`build_chat_context` off the event loop, plus its section breakdown.

    See :func:`build_chat_context_with_sections` for why the third element is
    worth a separate entrypoint rather than a flag on `build_chat_context_async`.
    """
    import asyncio

    from infrastructure.database import get_session_sync

    def _run() -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
        with get_session_sync() as ctx_session:
            return build_chat_context_with_sections(ctx_session, messages, **kwargs)

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


def _chat_story_character_ids(chat) -> list[str] | None:
    """Every character id a chat involves: the primary one plus any extras.

    Returns None when the chat has no character at all, which is what
    `build_chat_context` treats as "no story character block".
    """
    if chat is None:
        return None
    ids: list[str] = []
    primary = getattr(chat, "character_id", None)
    if primary:
        ids.append(primary)
    for extra in getattr(chat, "additional_character_ids", None) or []:
        if extra and extra not in ids:
            ids.append(extra)
    return ids or None


def _merge_ordered(*groups) -> list[str]:
    """Union of id lists, first occurrence wins, order preserved.

    Membership is additive everywhere it is merged — a chat's own picks, then
    its characters', then the World's — so a user who attached a lorebook
    explicitly always gets it first and nothing is ever silently reordered.
    """
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group or []:
            if value and value not in seen:
                seen.add(value)
                out.append(value)
    return out


def _character_lorebook_ids(characters, *, include_embedded: bool = False) -> list[str]:
    out: list[str] = []
    for character in characters or []:
        for lid in getattr(character, "lorebook_ids", None) or []:
            if lid and lid not in out:
                out.append(lid)
        if include_embedded:
            embedded_lid = getattr(character, "embedded_lorebook_id", None)
            if embedded_lid and embedded_lid not in out:
                out.append(embedded_lid)
    return out


def _resolve_world(chat, session):
    """The World that owns this chat, or `None`.

    Needs a session because the id lives on the row. Callers that cannot pass
    one (the impersonation path, historically) get the chat's own context
    unchanged rather than an error — a missing World must never be worse than
    the behaviour before Worlds existed.
    """
    world_id = getattr(chat, "world_id", None)
    if not world_id or session is None:
        return None
    from core.entities import World

    return session.get(World, world_id)


def _world_contribution(session, world) -> tuple[list[str], list[str], str | None]:
    """What `world` adds to a prompt: its lorebooks, its locations, its scenario.

    Read through the FKs. This used to be three id arrays on the `worlds` row,
    and the reason it is not any more is that those arrays were a second
    description of a relationship the member tables already owned: they were
    only ever written by one route, had no scrub path on entity delete, and a
    world's lorebooks could therefore list a book that no longer existed.

    The queries are indexed lookups on `world_id`, which is what the arrays
    were a cache of. `world_lorebook_ids` is deliberately ordered by
    `created_at, id` rather than by whatever the array used to hold — see
    `world_ownership.world_scenario` for why a set needs an explicit order.
    """
    from core.entities import Lorebook, Location

    from services.world_ownership import members_of, world_scenario

    world_lorebook_ids = [b.id for b in members_of(session, world.id, Lorebook)]
    world_location_ids = [l.id for l in members_of(session, world.id, Location)]
    scenario = world_scenario(session, world.id)
    world_scenario_text = (
        scenario.prompt_template if scenario is not None and scenario.prompt_template else None
    )
    return world_lorebook_ids, world_location_ids, world_scenario_text


def chat_context_kwargs(chat, *, characters=None, session=None, **overrides) -> dict[str, Any]:
    """Build common kwargs for build_chat_context_async / build_system_prompt_sections_async
    from a Chat entity.

    Centralising this mapping here means route handlers (chats.py, stories.py)
    and services (agent_simulation.py, orchestrator_service.py) all use the
    same field-to-kwarg mapping — no per-caller copies to drift.

    Pass `session` to enable persona-library resolution: when chat.persona_id
    is set, the Persona row fills any per-chat persona string that is unset.
    """
    persona_name = getattr(chat, "persona_name", None)
    persona_description = getattr(chat, "persona_description", None)
    persona_id = getattr(chat, "persona_id", None)
    if persona_id and session is not None:
        persona = session.get(Persona, persona_id)
        if persona:
            persona_name = persona_name or persona.name
            persona_description = persona_description or persona.description

    # A None override means "caller had no opinion" (e.g. the optional
    # lorebook_ids field on a send-message request) and must not shadow the
    # chat's own active lorebooks, or their context silently never loads.
    # An explicit `[]` is a deliberate clear, so it is tracked separately —
    # `or None` at the end would erase it and make "clear them" identical to
    # "I had no opinion".
    explicit_lorebooks = overrides.get("lorebook_ids")
    lorebook_ids = explicit_lorebooks
    if lorebook_ids is None:
        lorebook_ids = getattr(chat, "active_lorebook_ids", None) or None

    # `Character.lorebook_ids` are the vault's own library books that character
    # draws on, as opposed to `embedded_lorebook_id` — the SillyTavern
    # `character_book` that arrived inside an imported card. Resolved on every
    # prompt build rather than snapshotted at chat creation, so the link is true
    # for conversations that already exist. Without this the column is one more
    # write-only field, which is the defect class this schema has too many of.
    lorebook_ids = _merge_ordered(lorebook_ids, _character_lorebook_ids(characters, include_embedded=True))

    # The World is the owning container, so its membership is additive on top
    # of whatever the chat picked for itself. It was the one grouping in this
    # system that reached nothing at all: `chat.world_id` was written and
    # maintained and read by no prompt path, so filing a cast under a World
    # changed nothing about what the model was told.
    world = overrides.get("world") if "world" in overrides else _resolve_world(chat, session)
    world_lorebook_ids: list[str] = []
    world_location_ids: list[str] = []
    world_scenario: str | None = None
    if world is not None:
        world_lorebook_ids, world_location_ids, world_scenario = _world_contribution(session, world)

    merged_lorebook_ids = _merge_ordered(lorebook_ids, world_lorebook_ids)

    chat_location_id = getattr(chat, "location_id", None)
    location_ids = _merge_ordered(
        [chat_location_id] if chat_location_id else None, world_location_ids
    )

    chat_scenario: str | None = None
    has_chat_scenario = False
    chat_scenario_id = getattr(chat, "scenario_id", None)
    if chat_scenario_id and session is not None:
        _chat_scenario_row = session.get(Scenario, chat_scenario_id)
        if _chat_scenario_row and _chat_scenario_row.prompt_template:
            has_chat_scenario = True
            tpl = _chat_scenario_row.prompt_template.strip()
            existing_append = getattr(chat, "append_system_prompt", None) or ""
            if tpl and tpl not in existing_append:
                chat_scenario = _chat_scenario_row.prompt_template

    kwargs: dict[str, Any] = {
        "characters": characters,
        "character_id": overrides.get("character_id", getattr(chat, "character_id", None)),
        # Chat has `character_id` (singular) and `additional_character_ids` —
        # there is no `character_ids`. The old `getattr(chat, "character_ids",
        # None)` therefore always returned None (the getattr default hid it) and
        # the per-character story block was never emitted for chats.
        "story_character_ids": _chat_story_character_ids(chat),
        "location_ids": location_ids or None,
        "lorebook_ids": merged_lorebook_ids if (merged_lorebook_ids or explicit_lorebooks is not None) else None,
        "persona_name": persona_name,
        "persona_description": persona_description,
        "story_time": getattr(chat, "story_time", None),
        "story_location": getattr(chat, "story_location", None),
        "location_id": chat_location_id,
        "world_name": world.name if world is not None else None,
        "world_description": world.description if world is not None else None,
        "system_prompt_override": getattr(chat, "system_prompt_override", None),
        "append_system_prompt": getattr(chat, "append_system_prompt", None),
        "authors_note": getattr(chat, "authors_note", None),
        "authors_note_depth": getattr(chat, "authors_note_depth", None),
    }
    if chat_scenario:
        kwargs["story_scenario"] = chat_scenario
    elif world_scenario and not has_chat_scenario and not kwargs.get("story_scenario"):
        kwargs["story_scenario"] = world_scenario
    # A caller's own `story_scenario` must survive. It was silently dropped
    # unless a World happened to supply one — so on every World-less chat, the
    # scenario a caller resolved itself never reached the prompt. Same shape of
    # bug as the `None`-override-shadowing case above.
    if overrides.get("story_scenario") is not None:
        kwargs["story_scenario"] = overrides["story_scenario"]
    if "max_context_tokens" in overrides:
        kwargs["max_context_tokens"] = overrides["max_context_tokens"]
    if "include_roleplay_default" in overrides:
        kwargs["include_roleplay_default"] = overrides["include_roleplay_default"]
    if overrides.get("active_character_id"):
        kwargs["active_character_id"] = overrides["active_character_id"]
    if "trace_out" in overrides:
        kwargs["trace_out"] = overrides["trace_out"]
    return kwargs


def story_context_kwargs(
    story: Story | None,
    *,
    characters: list = None,
    session: Session = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Build kwargs for :func:`build_context` from a Story entity.

    Mirrors `chat_context_kwargs`: resolves the library Persona, merges World
    membership (lorebooks, locations, scenario), and pulls the story's own
    writing preferences (genre, memory, pov, character_ids, location_ids).

    All fields are nullable — an unset field reads as "inherit global" and the
    context builder simply omits that section.
    """
    if story is None:
        story = Story()

    persona_name = story.persona_name
    persona_description = story.persona_description
    persona_id = story.persona_id
    if persona_id and session is not None:
        persona = session.get(Persona, persona_id)
        if persona:
            persona_name = persona_name or persona.name
            persona_description = persona_description or persona.description

    # World contribution — lorebooks, locations, scenario, name, description.
    world = overrides.get("world") if "world" in overrides else None
    world_id = story.world_id
    if world is None and world_id and session is not None:
        from core.entities import World

        world = session.get(World, world_id)

    world_lorebook_ids: list[str] = []
    world_location_ids: list[str] = []
    world_scenario: str | None = None
    world_name = None
    world_description = None
    if world is not None:
        world_name = world.name
        world_description = world.description
        from core.entities import Lorebook as _Lorebook, Location as _Location
        from services.world_ownership import members_of as _members_of
        from services.world_ownership import world_scenario as _world_scenario

        world_lorebook_ids = [b.id for b in _members_of(session, world.id, _Lorebook)]
        world_location_ids = [l.id for l in _members_of(session, world.id, _Location)]
        _scenario = _world_scenario(session, world.id)
        world_scenario = (
            _scenario.prompt_template if _scenario and _scenario.prompt_template else None
        )

    # Scenario: story's own scenario_id first, then world fallback, then override.
    story_scenario = overrides.get("story_scenario")
    if story_scenario is None:
        scenario_id = story.scenario_id
        if scenario_id and session is not None:
            _scenario_row = session.get(Scenario, scenario_id)
            if _scenario_row:
                story_scenario = _scenario_row.prompt_template or None
        if story_scenario is None and world_scenario:
            story_scenario = world_scenario

    # Resolve story characters so their attached and embedded lorebooks reach the
    # story prompt just as they do in chats.
    story_char_ids = list(story.character_ids or [])
    story_characters = characters
    if story_characters is None and story_char_ids and session is not None:
        rows = session.exec(select(Character).where(Character.id.in_(story_char_ids))).all()
        by_id = {c.id: c for c in rows}
        story_characters = [by_id[cid] for cid in story_char_ids if cid in by_id]

    # Lorebooks: story's own + character lorebooks + world's, merged in order.
    explicit_lorebooks = overrides.get("lorebook_ids")
    lorebook_ids = explicit_lorebooks
    if lorebook_ids is None:
        lorebook_ids = list(story.lorebook_ids or []) or None
        lorebook_ids = _merge_ordered(
            lorebook_ids,
            _character_lorebook_ids(story_characters, include_embedded=True),
        )
    else:
        lorebook_ids = _merge_ordered(
            lorebook_ids,
            _character_lorebook_ids(story_characters, include_embedded=True),
        )
    lorebook_ids = _merge_ordered(lorebook_ids, world_lorebook_ids)

    # Locations: story's own + world's, merged in order.
    location_ids = list(story.location_ids or []) or None
    location_ids = _merge_ordered(location_ids, world_location_ids)

    # system_prompt_override: an explicit override passed in wins; otherwise the
    # story's own. (Stories don't have append_system_prompt on the entity —
    # that's a chat field — but the context builder accepts it.)
    system_prompt_override = overrides.get("system_prompt_override")
    if system_prompt_override is None:
        system_prompt_override = getattr(story, "system_prompt_override", None)

    primary_character_id = overrides.get("character_id") or (
        story_char_ids[0] if story_char_ids else None
    )

    kwargs: dict[str, Any] = {
        "lorebook_ids": (
            lorebook_ids if (lorebook_ids or explicit_lorebooks is not None) else None
        ),
        "location_ids": location_ids or None,
        "persona_name": persona_name,
        "persona_description": persona_description,
        "story_genre": story.genre,
        "story_memory": story.memory,
        "story_pov": story.pov,
        "story_scenario": story_scenario,
        "story_character_ids": story_char_ids or None,
        "world_name": world_name,
        "world_description": world_description,
        "system_prompt_override": system_prompt_override,
        "append_system_prompt": getattr(story, "append_system_prompt", None),
    }
    if primary_character_id:
        kwargs["character_id"] = primary_character_id
    if "max_context_tokens" in overrides:
        kwargs["max_context_tokens"] = overrides["max_context_tokens"]
    if "include_roleplay_default" in overrides:
        kwargs["include_roleplay_default"] = overrides["include_roleplay_default"]
    if overrides.get("active_character_id"):
        kwargs["active_character_id"] = overrides["active_character_id"]
    return kwargs


def build_context(
    session: Session,
    workspace: str,
    entity,
    messages: list = None,
    sections_only: bool = False,
    **overrides: Any,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Unified context assembly for chat and story workspaces.

    `workspace` is `"chat"` or `"story"`. `entity` is the owning Chat or Story
    row. `messages` is the optional input transcript — ORM Message rows for
    chat, beat/prior-chapter dicts for story.

    Builds the workspace-specific kwargs (chat_context_kwargs or
    story_context_kwargs), applies caller overrides, then runs a single pass
    through `build_chat_context_with_sections` for the system prompt, message
    list, and section breakdown.

    When `sections_only` is True, only the system-prompt sections are built
    (no message assembly, no pruning) and the joined section text is returned
    as the first element with an empty message list — for paths like
    `/suggest` and `/impersonate` that assemble their own message list.

    Returns: (system_prompt_or_sections_text, messages_list, sections)
    """
    if workspace == "chat":
        kwargs = chat_context_kwargs(
            entity,
            characters=overrides.pop("characters", None),
            session=session,
            **overrides,
        )
    elif workspace == "story":
        kwargs = story_context_kwargs(
            entity,
            characters=overrides.pop("characters", None),
            session=session,
            **overrides,
        )
    else:
        from core.exceptions import ValidationError

        raise ValidationError(f"Unknown workspace: {workspace!r}")

    if sections_only:
        sections = build_system_prompt_sections(session, **kwargs)
        sections_text = "\n\n".join(s["content"] for s in sections)
        return sections_text, [], sections

    return build_chat_context_with_sections(
        session,
        messages or [],
        **kwargs,
    )
