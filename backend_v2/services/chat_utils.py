"""
Shared chat utility functions.

Centralizes helpers that were previously duplicated between
world_integration_service.py and api/routes/world_vault/chats.py.
"""
import logging
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

_SINGLE_BRACE_PATTERN = re.compile(r"\{([^{}]+)\}")
_DOUBLE_BRACE_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")


def substitute_tavern_vars(text: str, *, char: str = "", user: str = "User") -> str:
    """Apply SillyTavern-compatible template variable substitution.

    Handles both brace forms: ``{{char}}``/``{{user}}``/``{{time}}``/``{{date}}``/
    ``{{random::a::b::...}}`` and the legacy single-brace ``{user}``/``{char}``
    variants. Unknown variables are left untouched.

    Previously three independent implementations existed:
    - api/routes/world_vault/chats.py (_substitute_tavern_vars + inline .replace)
    - services/context_builder.py (inline _replace function)

    This is the single canonical version. All callers should import from here.
    """
    if not text:
        return text

    now = datetime.now(timezone.utc)
    replacements = {
        "char": char,
        "user": user,
        "time": now.strftime("%H:%M"),
        "date": now.strftime("%Y-%m-%d"),
    }

    def replace_match(m: re.Match) -> str:
        key = m.group(1).strip().lower()
        if key.startswith("random::"):
            import random
            options = [o.strip() for o in key[len("random::"):].split("::") if o.strip()]
            return random.choice(options) if options else m.group(0)
        return replacements.get(key, m.group(0))

    # Mask double-brace markers before the single-brace pass so the inner
    # "{user}" of a "{{user}}" token is not resolved prematurely (single-brace
    # resolution would leave a stray brace-wrapped name behind). Sentinels are
    # brace-free, so they survive the single-brace pass untouched.
    masked: list[str] = []
    def mask(m: re.Match) -> str:
        token = f"\x00{len(masked)}\x00"
        masked.append(m.group(0))
        return token

    if "{{" in text:
        text = _DOUBLE_BRACE_PATTERN.sub(mask, text)
    if "{" in text:
        text = _SINGLE_BRACE_PATTERN.sub(replace_match, text)
    for i, original in enumerate(masked):
        text = text.replace(f"\x00{i}\x00", original)
    return _DOUBLE_BRACE_PATTERN.sub(replace_match, text)


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
