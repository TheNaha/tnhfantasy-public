"""Shared LLM configuration helpers used by chats, stories, and world integration."""

import json
import os
from typing import Any

from sqlmodel import Session, select

from core.entities import Provider
from infrastructure.logging import get_logger

_CONFIG_PATH = os.path.join(os.environ.get("DATA_DIR", "/data"), "llm_config.json")

_DEFAULT_MODEL_FALLBACK = "default"

# Cache for _read_config(). get_default_llm_model() runs inside async handlers on
# every chat message, story continue, suggest and impersonate, and each call was
# a blocking open()+json.load() on the event loop. The file only changes when the
# user picks a different default, which goes through set_default_provider() and
# invalidates the cache, so a stat()-based mtime check is enough to stay correct
# if anything else writes the file.
_read_cache: dict[str, Any] = {"mtime": None, "data": None}

logger = get_logger("llm_config")


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
    except Exception as exc:
        # Degrades rather than destroys, so this is not the `favorites.json`
        # case: a corrupt file reads as "no default provider chosen" and
        # `job_submission_service` silently drops `preferred_provider_id`, so
        # every LLM job falls back to load-balancer choice. Worth warning about —
        # it used to log nothing at all, at any level.
        logger.warning(
            "llm_config_read_failed", path=_CONFIG_PATH, error=str(exc)
        )
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
        logger.warning("config_default_llm_read_failed", error=str(exc))
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
    if provider and provider.enabled and (provider.worker_type in ("llm", "hybrid") or (hasattr(provider, "serves") and provider.serves("llm"))):
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
        .where(Provider.worker_type.in_(["llm", "hybrid"]), Provider.enabled == True)  # noqa: E712
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
            (p for p in providers if p.type in ("direct_url", "openai_compat", "remote_hybrid", "remote_llm") or "local" in p.id.lower()),
            None,
        )
        or providers[0]
    )
    return selected.id, get_default_llm_model()


# ---------------------------------------------------------------------------
# Job-kind aware model resolution (the rp/util router).
#
# `get_default_llm_model()` answers "which model serves LLM work", which was the
# whole story when there was one model. With a two-role registry the right
# question is "which *kind* of work is this", because an rp model is chosen for
# prose and a util model for structure, and neither is good at the other's job.
#
# This is deliberately layered on top of the existing single-model answer rather
# than replacing it: a deployment with one provider and no per-role setup keeps
# resolving exactly as it did, and the router only takes over once a provider
# actually serves the model the registry names.
# ---------------------------------------------------------------------------
def _served_models(session: Session) -> set[str]:
    """Model ids an enabled LLM provider is willing to serve.

    Read from each provider's `config.default_model`, which is what the engine
    actually sends upstream. A model no provider declares cannot be routed to,
    so the caller falls back to the single-model answer instead of dispatching a
    job to a model nothing serves.
    """
    served: set[str] = set()
    try:
        providers = session.exec(
            select(Provider).where(
                Provider.worker_type.in_(["llm", "hybrid"]),
                Provider.enabled == True,  # noqa: E712
            )
        ).all()
    except Exception as exc:
        logger.warning("llm_served_models_query_failed", error=str(exc))
        return served
    for provider in providers:
        config = getattr(provider, "config", None) or {}
        for key in (
            "default_model",
            "model",
            "default_rp_model",
            "default_util_model",
            "active_rp",
            "active_util",
        ):
            value = config.get(key)
            if value:
                served.add(str(value))
        for key in ("served_models", "models"):
            value = config.get(key)
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    if item:
                        served.add(str(item))
        if getattr(provider, "type", None) in ("modal_llm", "modal_vllm"):
            try:
                from services.llm_router import get_router

                reg = get_router().registry
                for m in reg.models.values():
                    if m.enabled:
                        served.add(m.id)
            except Exception:
                pass
    return served


def resolve_model_for_kind(
    kind: str | None,
    *,
    session: Session,
    override: str | None = None,
) -> str:
    """The model id a job of this kind should run on.

    Precedence, highest first:
      1. `override` — a per-chat or per-story pin. The user chose it, so it wins
         over every automatic decision, and it is honoured even if the registry
         disagrees.
      2. The rp/util router's primary model for the kind — but only when a real
         provider serves it. That condition is what keeps a one-provider
         deployment on its existing model instead of routing it to a model
         nothing can reach.
      3. `get_default_llm_model()` — the previous behaviour, unchanged.

    An unknown `kind` routes to the router's default role rather than raising,
    for the same reason the router does: a new workflow kind should still
    produce a reply.
    """
    if override:
        return override

    try:
        from services.llm_router import get_router

        router = get_router()
        model = router.primary_for_kind(kind)
        if model.id in _served_models(session):
            return model.id
    except Exception as exc:
        # The registry being absent or malformed must degrade to the old answer,
        # not break every chat message.
        logger.warning(
            "llm_router_resolution_failed",
            kind=kind,
            error=str(exc),
        )

    return get_default_llm_model()


def model_for_kind(kind: str | None, override: str | None, session) -> str:
    """The model id a job of `kind` should run on, honouring a pin.

    The single entry point for the whole roleplay surface. It used to be a
    wrapper re-declared verbatim in `api/routes/world_vault/chats.py` and
    `stories.py`, which is the shape that lets the two route files drift on
    precedence — and one of them already had, using `"suggest_reply"` for the
    primary reply path while every sibling path used `"chat_reply"`.

    Named so the call site says what is being decided (a *kind* of work) rather
    than which default was reached for.
    """
    return resolve_model_for_kind(kind, session=session, override=override)


def set_default_provider(provider_id: str, model_id: str) -> None:
    """Persist the user-selected default LLM provider/model to llm_config.json.

    Writes to a temp file and renames, so a concurrent reader can never observe
    a truncated/partial JSON document. The previous truncate-then-write left a
    window where get_default_llm_model() — called on every chat message — could
    parse a half-written file and silently fall back to the default model.
    """
    import tempfile

    current = _read_config() or {}
    payload = dict(current)
    payload["provider_id"] = provider_id
    payload["model_id"] = model_id

    directory = os.path.dirname(_CONFIG_PATH)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".llm_config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
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


def get_active_models(registry: Any = None) -> dict[str, str]:
    """Return active model IDs for rp, util, decisions, and image roles."""
    data = _read_config() or {}
    active_rp = data.get("active_rp")
    active_util = data.get("active_util")
    active_decisions = data.get("active_decisions")
    active_image = data.get("active_image") or data.get("default_image_model") or ""

    if not active_rp or not active_util or not active_decisions:
        try:
            if registry is None:
                from services.llm_router import get_router

                reg = get_router().registry
            else:
                reg = registry
            if not active_rp:
                active_rp = reg.primary("rp").id
            if not active_util:
                active_util = reg.primary("util").id
            if not active_decisions:
                try:
                    active_decisions = reg.primary("decisions").id
                except Exception:
                    active_decisions = "laya_multilingual"
        except Exception as exc:
            logger.debug("get_active_models_fallback_failed", error=str(exc))
            active_rp = active_rp or "artemis_31b"
            active_util = active_util or active_rp
            active_decisions = active_decisions or "laya_multilingual"

    return {
        "rp": active_rp,
        "util": active_util,
        "decisions": active_decisions,
        "image": active_image,
    }


def set_active_models(
    active_rp: str | None = None,
    active_util: str | None = None,
    active_decisions: str | None = None,
    active_image: str | None = None,
) -> dict[str, str]:
    """Persist active model choices in llm_config.json."""
    import tempfile

    current = _read_config() or {}
    updated = dict(current)
    if active_rp is not None:
        updated["active_rp"] = active_rp
    if active_util is not None:
        updated["active_util"] = active_util
    if active_decisions is not None:
        updated["active_decisions"] = active_decisions
    if active_image is not None:
        updated["active_image"] = active_image

    directory = os.path.dirname(_CONFIG_PATH)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".llm_config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(updated, f)
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
    return get_active_models()
