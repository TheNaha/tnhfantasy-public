from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from core.entities import Provider
from infrastructure.logging import get_logger

logger = get_logger("provider_utils")

RECONCILIATION_STATE_KEY = "reconciliation_state"
RECONCILIATION_IN_PROGRESS_TTL = 10800  # 180 minutes in seconds
RECONCILIATION_IN_PROGRESS_STATUSES = {"queued", "reconciling"}
RECONCILIATION_TERMINAL_STATUSES = {"completed", "failed", "idle"}
RUNTIME_CONFIG_KEY = "runtime_config"
DEPLOY_CONFIG_KEY = "deploy_config"

# Engine-config keys that pre-overhaul rows may hold top-level on `config`
# (the old wizard wrote them there). Still honoured on read so old rows
# resolve identically; new writes go through `deploy_config`.
#
# `gateway_host`/`gateway_port`/`api_host`/`api_port`/`beta9_gateway_host`/
# `beta9_gateway_port` were removed: they named the Beta9 deployment and a
# generic gateway/api host-port pair, neither of which exists anywhere in the
# tree any more, and no engine read them.
LEGACY_DEPLOY_CONFIG_FIELDS = {
    "app_name",
    "enable_memory_snapshot",
    "gpu_url",
    "storage_url",
    "download_url",
    "gpu_type",
    # `direct_url` / `remote_comfy` engines resolve their ComfyUI root from the
    # provider row's `config` (`engine_factory.py` reads `config.get("comfy_url")`).
    # It was missing here, so the Providers page's Runtime tab read
    # `provider.config?.comfy_url` — a key the status card never emits — and
    # could not show it under any name.
    "comfy_url",
}


def utcnow_iso() -> str:
    """Return the current UTC time as an ISO 8601 string.

    `datetime.now(timezone.utc)` already produces a timezone-aware datetime,
    so calling `.replace(tzinfo=timezone.utc)` is a no-op — kept minimal.
    """
    return datetime.now(timezone.utc).isoformat()


def parse_utc_timestamp(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None
    try:
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def clean_dict(value: dict[str, Any] | None) -> dict[str, Any]:
    return deepcopy(value) if isinstance(value, dict) else {}


def mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}***{value[-3:]}"


def extract_runtime_config(config: dict[str, Any]) -> dict[str, Any] | None:
    """Legacy runtime placement, read-only.

    `runtime_config` is no longer written and no backend path consumes it;
    this preserves whatever an old row carries so the record round-trips
    without loss.
    """
    runtime_config = clean_dict(config.get(RUNTIME_CONFIG_KEY))
    return runtime_config or None


def extract_deploy_config(config: dict[str, Any]) -> dict[str, Any]:
    """Engine config for a provider: stored `deploy_config` plus legacy top-level keys."""
    deploy_config = clean_dict(config.get(DEPLOY_CONFIG_KEY))

    for key in LEGACY_DEPLOY_CONFIG_FIELDS:
        if key in config and deploy_config.get(key) in (None, ""):
            deploy_config[key] = config[key]

    functions_config = clean_dict(config.get("functions"))
    if functions_config and "functions" not in deploy_config:
        deploy_config["functions"] = functions_config
    return deploy_config


def compose_config(
    *,
    base_config: dict[str, Any] | None,
    runtime_config: dict[str, Any] | None,
    deploy_config: dict[str, Any],
    reconciliation_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = clean_dict(base_config)
    config[RUNTIME_CONFIG_KEY] = runtime_config or None
    config[DEPLOY_CONFIG_KEY] = deploy_config

    if runtime_config is not None and runtime_config.get("worker") is not None:
        config["worker"] = runtime_config.get("worker")

    functions_config = clean_dict(deploy_config.get("functions"))
    if functions_config:
        config["functions"] = functions_config

    for key in LEGACY_DEPLOY_CONFIG_FIELDS:
        if key in deploy_config:
            config[key] = deploy_config[key]

    if reconciliation_state is not None:
        config[RECONCILIATION_STATE_KEY] = reconciliation_state
    elif RECONCILIATION_STATE_KEY not in config:
        config[RECONCILIATION_STATE_KEY] = {"status": "idle"}

    return config


def read_reconciliation_state(provider: Provider) -> dict[str, Any]:
    config = provider.config if isinstance(provider.config, dict) else {}
    state = config.get(RECONCILIATION_STATE_KEY)
    return state if isinstance(state, dict) else {"status": "idle"}


def normalize_reconciliation_status(status: str | None) -> str:
    if status in {"started", "queued", "already_running", "pending"}:
        return "queued"
    if status in {"progress", "running", "reconciling"}:
        return "reconciling"
    if status in {"skipped", "ok", "not_supported", "already-reconciled"}:
        return "completed"
    if status in {"error"}:
        return "failed"
    if status in {"completed", "failed", "idle"}:
        return status
    return "idle"
