
import os

from core.entities import Provider
from infrastructure.providers.provider_registry import ProviderRegistry
from services.provider_utils import (
    clean_dict,
    extract_deploy_config,
    extract_runtime_config,
)


def build_provider_environment(provider: Provider) -> dict[str, str]:
    """Build environment variables for a provider worker container.

    Common env vars (PROVIDER_ID, BACKEND_URL, worker config, shared tokens)
    are built here.  Provider-type-specific env vars are delegated to the
    registry's ``env_builder`` callback so that each provider owns its own
    mapping in one place.
    """
    runtime_config = extract_runtime_config(
        provider.type, provider.container_config, provider.config or {}
    ) or {}
    deploy_config = extract_deploy_config(provider.type, provider.config or {}, provider.worker_type or "image")
    credentials = clean_dict(provider.credentials)

    # ── Common env vars ──────────────────────────────────────────────
    env_vars: dict[str, str] = {}
    env_vars["PROVIDER_ID"] = provider.id

    from config import get_worker_backend_url
    env_vars["BACKEND_URL"] = get_worker_backend_url()

    worker_config = clean_dict(runtime_config.get("worker"))
    if "max_concurrent_downloads" in worker_config:
        env_vars["MAX_CONCURRENT_DOWNLOADS"] = str(worker_config["max_concurrent_downloads"])
    if "reconciliation_interval_seconds" in worker_config:
        env_vars["RECONCILIATION_INTERVAL_SECONDS"] = str(
            int(float(worker_config["reconciliation_interval_seconds"]))
        )
    elif "reconciliation_interval_hours" in worker_config:
        env_vars["RECONCILIATION_INTERVAL_SECONDS"] = str(
            int(float(worker_config["reconciliation_interval_hours"]) * 3600)
        )
    if "reconciliation_startup_delay_seconds" in worker_config:
        env_vars["RECONCILIATION_STARTUP_DELAY_SECONDS"] = str(
            int(float(worker_config["reconciliation_startup_delay_seconds"]))
        )
    if "validation_timeout_seconds" in worker_config:
        env_vars["VALIDATION_TIMEOUT_SECONDS"] = str(worker_config["validation_timeout_seconds"])

    # Shared download tokens
    if "hf_token" in credentials:
        env_vars["HF_TOKEN"] = credentials["hf_token"]
    if "civitai_token" in credentials:
        env_vars["CIVITAI_TOKEN"] = credentials["civitai_token"]

    # Shared auth tokens.  The provider container FAILS CLOSED without
    # PROVIDER_WORKER_TOKEN (every management route answers 503), and
    # COMFY_DISCOVERY_TOKEN is what the container presents when it
    # self-registers.  Both were previously omitted here, so a
    # backend-autostarted provider came up with no way to authenticate.
    for env_name in ("PROVIDER_WORKER_TOKEN", "COMFY_DISCOVERY_TOKEN"):
        value = os.getenv(env_name, "").strip()
        if value:
            env_vars[env_name] = value

    # ── Provider-type-specific env vars (via registry) ───────────────
    type_config = ProviderRegistry.get(provider.type)
    if type_config and type_config.env_builder:
        # Build a config dict that includes deploy_config so the callback
        # can access nested deploy settings (functions.comfyui, etc.)
        merged_config = {"id": provider.id, **deploy_config}
        if provider.config:
            merged_config.setdefault("deploy_config", {})
            merged_config["deploy_config"] = deploy_config
        type_vars = type_config.env_builder(credentials, merged_config)
        env_vars.update(type_vars)

    return env_vars
