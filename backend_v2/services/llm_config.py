"""Shared LLM configuration helpers used by chats, stories, and world integration."""

import json
import os
from typing import Any

from sqlmodel import Session, select

from core.entities import Provider

_CONFIG_PATH = os.path.join(os.environ.get("DATA_DIR", "/data"), "llm_config.json")

_DEFAULT_MODEL_FALLBACK = "default"


def _read_config() -> dict[str, Any] | None:
    """Read the user-selected default LLM provider/model from llm_config.json."""
    if not os.path.exists(_CONFIG_PATH):
        return None
    try:
        with open(_CONFIG_PATH) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else None
    except Exception:
        return None


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
    except Exception:
        pass
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
        select(Provider).where(Provider.worker_type == "llm", Provider.enabled == True)  # noqa: E712
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
    """Persist the user-selected default LLM provider/model to llm_config.json."""
    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    with open(_CONFIG_PATH, "w") as f:
        json.dump({"provider_id": provider_id, "model_id": model_id}, f)
