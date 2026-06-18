from typing import Dict
from core.entities import Provider

from infrastructure.providers.provider_registry import ProviderRegistry
from services.provider_utils import (
    ensure_provider_v2_shape,
    extract_runtime_config,
    extract_deploy_config,
    clean_dict,
)


def build_provider_environment(provider: Provider) -> Dict[str, str]:
    """Build environment variables for a provider worker container.

    Common env vars (PROVIDER_ID, BACKEND_URL, worker config, shared tokens)
    are built here.  Provider-type-specific env vars are delegated to the
    registry's ``env_builder`` callback so that each provider owns its own
    mapping in one place.
    """
    provider = ensure_provider_v2_shape(provider)
    runtime_config = extract_runtime_config(
        provider.type, provider.container_config, provider.config or {}
    ) or {}
    deploy_config = extract_deploy_config(provider.type, provider.config or {})
    credentials = clean_dict(provider.credentials)

    # ── Common env vars ──────────────────────────────────────────────
    env_vars: Dict[str, str] = {}
    env_vars["PROVIDER_ID"] = provider.id

    from config import settings
    env_vars["BACKEND_URL"] = settings.worker_backend_url

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
