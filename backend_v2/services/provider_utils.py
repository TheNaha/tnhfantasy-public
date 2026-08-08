from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from core.entities import Provider

DEPLOY_STATE_KEY = "deploy_state"
DEPLOY_IN_PROGRESS_TTL = 1800  # 30 minutes in seconds
RECONCILIATION_STATE_KEY = "reconciliation_state"
RECONCILIATION_IN_PROGRESS_TTL = 10800  # 180 minutes in seconds
RECONCILIATION_IN_PROGRESS_STATUSES = {"queued", "reconciling"}
RECONCILIATION_TERMINAL_STATUSES = {"completed", "failed", "idle"}
RUNTIME_CONFIG_KEY = "runtime_config"
DEPLOY_CONFIG_KEY = "deploy_config"


def _get_supported_managed_deploy_types():
    """Lazily resolve supported deploy types from the provider registry."""
    from infrastructure.providers.provider_registry import ProviderRegistry
    return set(ProviderRegistry.get_all().keys())
LEGACY_DEPLOY_CONFIG_FIELDS = {
    "app_name",
    "enable_memory_snapshot",
    "gpu_url",
    "storage_url",
    "download_url",
    "gpu_type",
    "gateway_host",
    "gateway_port",
    "api_host",
    "api_port",
    "beta9_gateway_host",
    "beta9_gateway_port",
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=timezone.utc).isoformat()


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


def default_deploy_mode(provider_type: str) -> str:
    return "managed" if provider_type in _get_supported_managed_deploy_types() else "manual"


def default_deploy_targets(provider_type: str) -> list[dict[str, Any]]:
    if provider_type == "modal":
        return [
            {
                "name": "modal_app",
                "entrypoint": "/app/modal_app.py",
                "command": ["modal", "deploy", "/app/modal_app.py"],
            }
        ]
    if provider_type == "modal_llm":
        return [
            {
                "name": "modal_llm_app",
                "entrypoint": "/app/llm_worker/engines/modal/modal_app.py",
                "command": ["modal", "deploy", "/app/llm_worker/engines/modal/modal_app.py"],
            }
        ]
    if provider_type == "beam":
        return [
            {
                "name": "comfy_gpu",
                "entrypoint": "/app/beam_app.py:comfy_gpu",
                "command": ["beta9", "deploy", "beam_app.py:comfy_gpu"],
            },
            {
                "name": "comfy_storage",
                "entrypoint": "/app/beam_app.py:comfy_storage",
                "command": ["beta9", "deploy", "beam_app.py:comfy_storage"],
            },
            {
                "name": "comfy_download",
                "entrypoint": "/app/beam_app.py:comfy_download",
                "command": ["beta9", "deploy", "beam_app.py:comfy_download"],
            },
        ]
    return []


def normalize_beam_handler_spec(handler: str) -> str:
    if ":" not in handler:
        return handler

    module_path, object_name = handler.split(":", 1)
    if module_path.startswith("/app/"):
        module_path = module_path[len("/app/") :]
    elif module_path.startswith("./app/"):
        module_path = module_path[len("./app/") :]
    elif module_path.startswith("/"):
        module_path = module_path.lstrip("/")

    return f"{module_path}:{object_name}"


def normalize_deploy_step_command(provider_type: str, command: list[str]) -> list[str]:
    if provider_type != "beam" or not command:
        return command

    normalized_command = ["beta9", *command[1:]] if command[0] == "beam" else list(command)
    if len(normalized_command) < 3:
        return normalized_command

    if normalized_command[0] == "beta9" and normalized_command[1] == "deploy":
        for index in range(2, len(normalized_command)):
            token = normalized_command[index]
            if isinstance(token, str) and ":" in token and token.split(":", 1)[0].endswith(".py"):
                normalized_command[index] = normalize_beam_handler_spec(token)
                break

    return normalized_command


def extract_runtime_config(provider_type: str, container_config: Any, config: dict[str, Any]) -> dict[str, Any] | None:
    runtime_config = clean_dict(config.get(RUNTIME_CONFIG_KEY))
    if not runtime_config:
        runtime_config = clean_dict(container_config)
    if not runtime_config:
        return None

    worker_config = clean_dict(config.get("worker"))
    if worker_config and "worker" not in runtime_config:
        runtime_config["worker"] = worker_config

    runtime_config.setdefault("mode", "container")
    if provider_type in _get_supported_managed_deploy_types():
        runtime_config.setdefault("port", runtime_config.get("port", 8000))
    return runtime_config


def extract_deploy_config(provider_type: str, config: dict[str, Any]) -> dict[str, Any]:
    deploy_config = clean_dict(config.get(DEPLOY_CONFIG_KEY))

    for key in LEGACY_DEPLOY_CONFIG_FIELDS:
        if key in config and deploy_config.get(key) in (None, ""):
            deploy_config[key] = config[key]

    functions_config = clean_dict(config.get("functions"))
    if functions_config and "functions" not in deploy_config:
        deploy_config["functions"] = functions_config

    deploy_config.setdefault("deploy_mode", default_deploy_mode(provider_type))
    deploy_config.setdefault("targets", default_deploy_targets(provider_type))
    return deploy_config


def compose_config(
    *,
    base_config: dict[str, Any] | None,
    runtime_config: dict[str, Any] | None,
    deploy_config: dict[str, Any],
    deploy_state: dict[str, Any] | None = None,
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

    if deploy_state is not None:
        config[DEPLOY_STATE_KEY] = deploy_state
    elif DEPLOY_STATE_KEY not in config:
        config[DEPLOY_STATE_KEY] = {"status": "idle"}

    if reconciliation_state is not None:
        config[RECONCILIATION_STATE_KEY] = reconciliation_state
    elif RECONCILIATION_STATE_KEY not in config:
        config[RECONCILIATION_STATE_KEY] = {"status": "idle"}

    return config

def read_deploy_state(provider: Provider) -> dict[str, Any]:
    config = provider.config if isinstance(provider.config, dict) else {}
    state = config.get(DEPLOY_STATE_KEY)
    return state if isinstance(state, dict) else {"status": "idle"}

def read_reconciliation_state(provider: Provider) -> dict[str, Any]:
    config = provider.config if isinstance(provider.config, dict) else {}
    state = config.get(RECONCILIATION_STATE_KEY)
    return state if isinstance(state, dict) else {"status": "idle"}

def normalize_reconciliation_status(status: str | None) -> str:
    if status in {"started", "queued"}:
        return "queued"
    if status in {"progress", "running", "reconciling"}:
        return "reconciling"
    if status in {"completed", "failed", "idle"}:
        return status
    return "idle"
