"""
Shared chat utility functions.

Centralizes helpers that were previously duplicated between
world_integration_service.py and api/routes/world_vault/chats.py.
"""
import logging
import random
import re
from datetime import datetime, timezone

from sqlmodel import Session

from core.entities import Message, MessageRole

logger = logging.getLogger("chat_utils")


# ---------------------------------------------------------------------------
# Context token resolution
# ---------------------------------------------------------------------------

_DEFAULT_CONTEXT_TOKENS = 4096


def resolve_context_tokens(chat) -> int:
    """Return the effective max context tokens for a chat.

    Priority:
    1. Per-chat ``max_context_tokens`` field (explicit override).
    2. Global config ``ai.maxContextTokens`` / ``ai.max_context_tokens``.
    3. Hard fallback: 4096.

    Previously two divergent copies existed — one in world_integration_service
    (missing the global config lookup) and one in chats.py (correct).
    This is the single canonical implementation.
    """
    if getattr(chat, "max_context_tokens", None) and chat.max_context_tokens > 0:
        return chat.max_context_tokens
    try:
        from config import get_config
        cfg = get_config() or {}
        ai_cfg = cfg.get("ai", {})
        val = ai_cfg.get("maxContextTokens") or ai_cfg.get("max_context_tokens")
        if val and int(val) > 0:
            return int(val)
    except Exception as exc:
        logger.debug("max_context_tokens_config_parse_failed", error=str(exc))
    return _DEFAULT_CONTEXT_TOKENS


# ---------------------------------------------------------------------------
# SillyTavern template variable substitution
# ---------------------------------------------------------------------------

# Macro bodies are scanned by hand (rather than a flat regex) so that macros
# nest the way SillyTavern's engine does: {{random::{{char}}}} resolves the
# inner macro first, and an unknown macro keeps its literal braces while any
# nested macro inside it still expands.
_MAX_MACRO_DEPTH = 4
# Longest run of characters scanned while looking for a macro's closing "}}".
_MAX_MACRO_SCAN = 2000
# Bounds on argument-driven output so a hostile card cannot inflate a prompt.
_MAX_ROLL_DICE = 100
_MAX_NEWLINES = 10

# droll syntax: [N]dM, optionally followed by a +/- modifier.
_ROLL_DICE_PATTERN = re.compile(r"^(\d{1,3})?\s*[dD]\s*(\d{1,4})$")
_ROLL_BARE_PATTERN = re.compile(r"^\+?(\d{1,4})$")
_ROLL_MODIFIER_PATTERN = re.compile(r"^(.*?)\s*([+-])\s*(\d{1,4})$")

# Macros whose value is fixed for the current call; they take no arguments, so
# "{{time::UTC+8}}" and friends stay untouched rather than half-expanding.
_FIXED_MACROS = ("char", "user", "persona", "original", "time", "date")


def _split_macro(raw: str) -> tuple[str, list[str]]:
    """Split a macro body into ``(name, args)``.

    SillyTavern argument syntax in precedence order: ``::`` separators, a
    single ``:`` (legacy, still used by ST cards), then a plain space for
    single-argument macros. The name is trimmed and lowercased — ST macro
    names are case-insensitive.
    """
    if "::" in raw:
        parts = [p.strip() for p in raw.split("::")]
        return parts[0].lower(), parts[1:]
    if ":" in raw:
        name, _, rest = raw.partition(":")
        return name.strip().lower(), [rest.strip()]
    head, sep, rest = raw.strip().partition(" ")
    return head.lower(), [rest.strip()] if sep else []


def _roll_dice(expr: str) -> str | None:
    """Evaluate a droll expression, e.g. ``2d20``, ``d6``, ``20``, ``2d6+3``.

    Returns the expanded form (``"3 + 4 = 7"``; a lone number for a single
    unmodified die) or ``None`` when the expression is unparseable or exceeds
    the safety bounds, in which case the token is left intact.
    """
    expr = expr.strip()
    if not expr:
        return None

    modifier = 0
    mod_match = _ROLL_MODIFIER_PATTERN.match(expr)
    if mod_match:
        expr = mod_match.group(1).strip()
        modifier = int(mod_match.group(3))
        if mod_match.group(2) == "-":
            modifier = -modifier

    dice_match = _ROLL_DICE_PATTERN.match(expr)
    if dice_match:
        count = int(dice_match.group(1) or 1)
        sides = int(dice_match.group(2))
    elif not expr and modifier:
        # A bare "+3" / "-3" is a constant roll.
        return str(modifier)
    else:
        bare_match = _ROLL_BARE_PATTERN.match(expr)
        if not bare_match:
            return None
        count, sides = 1, int(bare_match.group(1))

    if count < 1 or count > _MAX_ROLL_DICE or sides < 1:
        return None

    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + modifier
    if len(rolls) == 1 and modifier == 0:
        return str(rolls[0])
    terms = [str(r) for r in rolls]
    if modifier:
        terms.append(f"{modifier:+d}")
    return f"{' + '.join(terms)} = {total}"


def _resolve_macro(
    raw: str,
    *,
    char: str,
    user: str,
    persona_description: str,
    original: str,
    now: datetime,
) -> str | None:
    """Return the expansion for one macro body, or ``None`` when unknown.

    ``None`` means "no substitution available" — the caller keeps the token
    verbatim, which is how unknown macros behave in SillyTavern.
    """
    name, args = _split_macro(raw)

    if name in _FIXED_MACROS:
        # {{persona}} and {{original}} stay intact when the caller has no
        # value for them, matching the pre-existing unknown-macro behaviour
        # instead of silently deleting the token's content.
        if args:
            return None
        if name == "char":
            return char
        if name == "user":
            return user
        if name == "persona":
            return persona_description or None
        if name == "original":
            return original or None
        if name == "time":
            return now.strftime("%H:%M")
        return now.strftime("%Y-%m-%d")

    if name == "newline":
        if not args:
            return "\n"
        try:
            count = int(args[0])
        except ValueError:
            return None
        if count < 1:
            return None
        return "\n" * min(count, _MAX_NEWLINES)

    if name in ("random", "pick"):
        options = [a for a in args if a]
        # {{random}} re-rolls per expansion and {{pick}} is ST's sticky
        # per-chat variant; without persisted pick state both are plain
        # random choices here.
        return random.choice(options) if options else None

    if name == "roll":
        return _roll_dice(args[0]) if args else None

    return None


def _find_macro_end(text: str, start: int) -> int | None:
    """Index of the ``}}`` closing the ``{{`` opened before ``start``.

    Nested ``{{`` / ``}}`` pairs are counted so a macro argument may itself
    contain a macro. The scan is bounded both by the next ``}}`` in the string
    and by ``_MAX_MACRO_SCAN`` characters, so pathological input (thousands of
    unbalanced ``{{``) cannot turn a prompt build into quadratic work. Returns
    ``None`` when the token is unterminated.
    """
    close = text.find("}}", start)
    if close == -1 or close + 2 > start + _MAX_MACRO_SCAN:
        # No "}}" anywhere near the opener: treat as unterminated rather than
        # scanning the rest of a long prompt for every stray "{{".
        return None
    depth = 1
    i = start
    n = min(start + _MAX_MACRO_SCAN, len(text))
    while i < n:
        if text.startswith("{{", i):
            depth += 1
            i += 2
        elif text.startswith("}}", i):
            depth -= 1
            if depth == 0:
                return i
            i += 2
        else:
            i += 1
    return None


def _expand_macros(text: str, depth: int, ctx: dict) -> str:
    """Walk ``text`` once, expanding every macro token it can resolve."""
    if depth > _MAX_MACRO_DEPTH:
        return text
    out: list[str] = []
    i = 0
    n = len(text)
    # Computed once so the unterminated-token retry path below stays O(1)
    # instead of rescanning the tail for every stray "{{".
    has_closing_brace = "}}" in text
    while i < n:
        if text[i] != "{":
            out.append(text[i])
            i += 1
            continue

        if text.startswith("{{", i):
            end = _find_macro_end(text, i + 2)
            if end is not None:
                body = _expand_macros(text[i + 2:end], depth + 1, ctx)
                resolved = _resolve_macro(body, **ctx)
                if resolved is not None:
                    out.append(resolved)
                else:
                    # Unknown/unresolvable macro: keep the token (with any
                    # nested macro already expanded inside it).
                    out.append("{{" + body + "}}")
                i = end + 2
                continue
            if has_closing_brace:
                # Unterminated "{{": keep both braces and continue after them,
                # so no text is lost and nothing is half-expanded.
                out.append("{{")
                i += 2
                continue
            # Nothing closable remains — copy the tail verbatim.
            out.append(text[i:])
            break

        end = text.find("}", i + 1)
        if end != -1:
            body = text[i + 1:end]
            if "{" not in body:
                resolved = _resolve_macro(_expand_macros(body, depth + 1, ctx), **ctx)
                if resolved is not None:
                    out.append(resolved)
                    i = end + 1
                    continue
        out.append("{")
        i += 1
    return "".join(out)


def substitute_tavern_vars(
    text: str,
    *,
    char: str = "",
    user: str = "User",
    persona_description: str = "",
    original: str = "",
    now: datetime | None = None,
) -> str:
    """Apply SillyTavern-compatible template variable substitution.

    Handles both brace forms: ``{{char}}`` and the legacy single-brace
    ``{char}`` variant. Supported macros:

    ==================== =====================================================
    ``{{char}}``         character name
    ``{{user}}``         user / persona name
    ``{{persona}}``      user persona description
    ``{{original}}``     original character prompt (what a prompt override replaces)
    ``{{time}}``         current UTC time, ``HH:MM``
    ``{{date}}``         current UTC date, ``YYYY-MM-DD``
    ``{{random::a::b}}`` random pick of the ``::``-separated options
    ``{{pick::a::b}}``   same as ``random`` (ST keeps it sticky per chat)
    ``{{roll::2d20}}``   dice roll, droll syntax, rendered ``"3 + 4 = 7"``
    ``{{newline}}``      a literal newline (optionally ``{{newline::3}}``)
    ==================== =====================================================

    Macro names are case-insensitive, arguments may be separated by ``::``
    (preferred), a legacy single ``:``, or a space, and macros nest. Unknown
    macros are left untouched.

    ``now`` is injectable for deterministic tests.
    """
    if not text:
        return text

    ctx = {
        "char": char,
        "user": user,
        "persona_description": persona_description,
        "original": original,
        "now": now or datetime.now(timezone.utc),
    }
    return _expand_macros(text, 0, ctx)


def render_agent_template(
    template: str,
    *,
    character_name: str = "Character",
    user_name: str = "User",
    story_location: str = "",
    story_time: str = "",
) -> str:
    """Render an ``AgentProfile.system_prompt_template`` with scene placeholders.

    Supports both the seeded SillyTavern-style ``{{char}}``/``{{user}}`` macros
    and the explicit ``{character_name}``/``{user_name}``/``{story_location}``/
    ``{story_time}`` placeholders used by custom agents.
    """
    if not template:
        return ""
    rendered = substitute_tavern_vars(str(template), char=character_name, user=user_name)
    return (
        rendered.replace("{character_name}", character_name)
        .replace("{user_name}", user_name)
        .replace("{story_location}", story_location or "")
        .replace("{story_time}", story_time or "")
    )


# ---------------------------------------------------------------------------
# Character → chat link resolution
# ---------------------------------------------------------------------------


def link_embedded_lorebook(active_lorebook_ids: list[str] | None, character) -> list[str]:
    """Merge a character's embedded lorebook into a chat's active lorebooks.

    SillyTavern card "character_book" lorebooks are stored as a Lorebook owned
    by the character and are active in every chat with that character. Read
    defensively via ``getattr`` so this stays a no-op until the
    ``Character.embedded_lorebook_id`` column exists.

    Order is preserved (requested ids first, embedded appended) and duplicates
    are dropped, so re-running this is idempotent.
    """
    merged = [lid for lid in (active_lorebook_ids or []) if lid]
    embedded_id = getattr(character, "embedded_lorebook_id", None)
    if embedded_id and embedded_id not in merged:
        merged.append(embedded_id)
    return merged



def insert_world_state_marker(session: Session, chat_id: str, changed: dict) -> None:
    """Insert a UI-only world-state divider marker message after a time/location change.

    Supports 'time', 'location', 'expression', and 'expression_avatar' keys.
    If none of the recognized fields are present, no marker is inserted.
    """
    parts = []
    if changed.get("location"):
        parts.append(f"Location: {changed['location']}")
    if changed.get("time"):
        parts.append(f"Time: {changed['time']}")
    if changed.get("location_id"):
        parts.append(f"Linked Location: {changed['location_id']}")
    if changed.get("expression"):
        parts.append(f"Expression: {changed['expression']}")
    if not parts:
        return
    marker = Message(
        chat_id=chat_id,
        role=MessageRole.SYSTEM,
        content="\n".join(parts),
        message_metadata={"source": "world_state", **changed},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(marker)
    session.commit()


# ---------------------------------------------------------------------------
# LLM output extraction
# ---------------------------------------------------------------------------


def extract_persistable_text(job_data: dict) -> str | None:
    """`extract_first_text`, but None when there is nothing worth persisting.

    A whitespace-only turn is not prose. The plain extractor returns it as-is
    because `"   \n "` is truthy, and every downstream guard is `if not content`
    — so a model that emits nothing but blank lines alongside a tool call gets a
    message written for it, and on the story side a beat whose `content` is
    whitespace renders as a bare separator in the chapter text.

    `.strip()` on the value AND the empty case are separate: `""` and `"\n"` both
    mean "no turn", and a returned `None` is what the existing guards already
    test for.
    """
    text = extract_first_text(job_data)
    if text is None:
        return None
    return text if text.strip() else None


def extract_first_text(job_data: dict) -> str | None:
    """Extract reply text from a completion payload.

    LLM job outputs are ``[{'role': 'assistant', 'content': ...}]`` — the text
    lives under ``content``, not ``text``. Fall back to the event_extra fields
    (some branches complete with ``outputs=[]`` and carry text top-level).

    Previously duplicated in world_integration_service.py (_first_text) and
    three inline copies in job_processing.py.
    """
    if not isinstance(job_data, dict):
        return None
    outputs = job_data.get("outputs") or []
    if outputs and isinstance(outputs[0], dict):
        v = outputs[0].get("content") or outputs[0].get("text")
        if v:
            return v
    return job_data.get("content") or job_data.get("prompt")


# ---------------------------------------------------------------------------
# TTS voice resolution
# ---------------------------------------------------------------------------


def resolve_voice_for_character(session: Session, char) -> tuple:
    """Resolve the TTS voice for a character.

    Priority: attached ``VoiceModel`` (voice_profile or name + language) →
    legacy ``voice_profile`` string field.

    Returns ``(voice_profile, voice_model_id, language)``, all ``None`` when
    ``char`` is falsy or has no voice configured. Previously duplicated in
    ``chats.py`` (narrate_message) and ``stories.py`` (narrate_chapter).
    """
    if not char:
        return None, None, None
    voice_profile = None
    voice_model_id = getattr(char, "voice_model_id", None)
    language = None
    if voice_model_id:
        from core.entities import VoiceModel
        vm = session.get(VoiceModel, voice_model_id)
        if vm:
            voice_profile = vm.voice_profile or vm.name
            language = vm.language
    if not voice_profile:
        voice_profile = getattr(char, "voice_profile", None)
    return voice_profile, voice_model_id, language


def resolve_scenario_defaults(
    session: Session, entity
) -> tuple[str | None, str | None]:
    """Resolve ``(default_checkpoint, default_voice_profile)`` from an entity's Scenario.

    Checks ``entity.scenario_id`` first, then falls back to the owning World's
    scenario via :func:`services.world_ownership.world_scenario`.
    """
    if not entity or session is None:
        return None, None
    from core.entities import Scenario
    from services.world_ownership import world_scenario

    scenario = None
    scenario_id = getattr(entity, "scenario_id", None)
    if scenario_id:
        scenario = session.get(Scenario, scenario_id)
    if scenario is None:
        world_id = getattr(entity, "world_id", None)
        if world_id:
            scenario = world_scenario(session, world_id)
    if scenario is None:
        return None, None
    return (
        (scenario.default_checkpoint or "").strip() or None,
        (scenario.default_voice_profile or "").strip() or None,
    )

