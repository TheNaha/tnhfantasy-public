"""Shared LLM configuration helpers used by chats, stories, and world integration."""

import json
import os
from typing import Any

from sqlmodel import Session, select

from core.entities import Provider

_CONFIG_PATH = os.path.join(os.environ.get("DATA_DIR", "/data"), "llm_config.json")

_DEFAULT_MODEL_FALLBACK = "default"

# Cache for _read_config(). get_default_llm_model() runs inside async handlers on
# every chat message, story continue, suggest and impersonate, and each call was
# a blocking open()+json.load() on the event loop. The file only changes when the
# user picks a different default, which goes through set_default_provider() and
# invalidates the cache, so a stat()-based mtime check is enough to stay correct
# if anything else writes the file.
_read_cache: dict[str, Any] = {"mtime": None, "data": None}


def _read_config() -> dict[str, Any] | None:
    """Read the user-selected default LLM provider/model from llm_config.json."""
    try:
        mtime = os.path.getmtime(_CONFIG_PATH)
    except OSError:
        # Missing or unreadable: treat as absent and drop any cached value.
        _read_cache["mtime"] = None
        _read_cache["data"] = None
        return None

    if _read_cache["mtime"] == mtime:
        return _read_cache["data"]

    try:
        with open(_CONFIG_PATH) as f:
            data = json.load(f)
        data = data if isinstance(data, dict) else None
    except Exception:
        return None

    _read_cache["mtime"] = mtime
    _read_cache["data"] = data
    return data


def _invalidate_cache() -> None:
    _read_cache["mtime"] = None
    _read_cache["data"] = None


def get_default_llm_model() -> str:
    """Resolve the user-selected LLM model id.

    Precedence: llm_config.json model_id -> settings.default_llm_model -> 'default'.
    """
    data = _read_config()
    if data:
        model_id = data.get("model_id")
        if model_id:
            return model_id
    try:
        from config import settings
        configured = getattr(settings, "default_llm_model", None)
        if configured:
            return configured
    except Exception as exc:
        import logging
        logging.getLogger("llm_config").debug("config_default_llm_read_failed", error=str(exc))
    return _DEFAULT_MODEL_FALLBACK


def _stored_provider_override(session: Session) -> tuple[str, str] | None:
    """Return (provider_id, model_id) from llm_config.json if the provider still exists."""
    data = _read_config()
    if not data:
        return None
    provider_id = data.get("provider_id")
    model_id = data.get("model_id")
    if not provider_id or not model_id:
        return None
    provider = session.get(Provider, provider_id)
    if provider and provider.enabled and provider.worker_type == "llm":
        return provider_id, model_id
    return None


def resolve_default_provider(session: Session) -> tuple[str, str] | None:
    """Resolve the default LLM provider.

    Precedence: explicit llm_config.json override (verified against DB) ->
    auto-select from enabled LLM providers (local/direct_url/openai_compat
    preferred, then the first available). Returns None if no LLM provider exists.
    """
    stored = _stored_provider_override(session)
    if stored:
        return stored

    providers = session.exec(
        select(Provider)
        .where(Provider.worker_type == "llm", Provider.enabled == True)  # noqa: E712
        # No ORDER BY means Postgres makes no ordering promise, so `providers[0]`
        # — the fallback whenever no provider matches the preferred-type test —
        # was whatever the plan happened to return. `resolve_default_provider()`
        # could then pick a different provider for two consecutive chat messages
        # with identical configuration, and every caller would have no way to
        # tell it was not a stable choice. A tie on `priority` breaks on `id`,
        # which is unique, so the fallback is deterministic.
        .order_by(Provider.priority, Provider.id)
    ).all()

    if not providers:
        return None

    selected = (
        next(
            (p for p in providers if p.type in ("direct_url", "openai_compat") or "local" in p.id.lower()),
            None,
        )
        or providers[0]
    )
    return selected.id, get_default_llm_model()


def set_default_provider(provider_id: str, model_id: str) -> None:
    """Persist the user-selected default LLM provider/model to llm_config.json.

    Writes to a temp file and renames, so a concurrent reader can never observe
    a truncated/partial JSON document. The previous truncate-then-write left a
    window where get_default_llm_model() — called on every chat message — could
    parse a half-written file and silently fall back to the default model.
    """
    import tempfile

    directory = os.path.dirname(_CONFIG_PATH)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".llm_config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump({"provider_id": provider_id, "model_id": model_id}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, _CONFIG_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    _invalidate_cache()
