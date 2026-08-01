# Modal Provider Type Configuration
# This module contains all Modal-specific logic, keeping it out of core backend

from typing import Dict, Any

from .provider_registry import ProviderTypeConfig, ProviderRegistry, clean_registry_dict as clean_dict
from .modal_provider import ModalProvider


def build_modal_env_vars(credentials: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, str]:
    """
    Build environment variables for Modal worker container.

    This is the single source of truth for Modal env vars.
    Called by provider_env_builder for container startup and by the registry for validation.

    Args:
        credentials: Provider credentials (token_id, token_secret, username)
        config: Provider config dict (may include nested runtime_config / deploy_config keys)

    Returns:
        Environment variables dict
    """
    env_vars: Dict[str, str] = {}

    # Core config
    env_vars["ENGINE"] = "modal"
    if config.get("id"):
        env_vars["PROVIDER_ID"] = config["id"]
    from config import settings
    env_vars["BACKEND_URL"] = settings.worker_backend_url

    # Modal authentication
    if credentials.get("token_id"):
        env_vars["MODAL_TOKEN_ID"] = credentials["token_id"]
    if credentials.get("token_secret"):
        env_vars["MODAL_TOKEN_SECRET"] = credentials["token_secret"]
    if credentials.get("username"):
        env_vars["MODAL_USERNAME"] = credentials["username"]

    # Modal app configuration
    if config.get("app_name"):
        env_vars["MODAL_APP_NAME"] = config["app_name"]

    # Memory snapshot setting
    if config.get("enable_memory_snapshot") is not None:
        env_vars["ENABLE_MEMORY_SNAPSHOT"] = str(config["enable_memory_snapshot"]).lower()

    # Nested deploy_config: functions.comfyui
    deploy = clean_dict(config.get("deploy_config") or config)
    comfyui = clean_dict(clean_dict(deploy.get("functions")).get("comfyui"))
    if "gpu_type" in comfyui:
        env_vars["MODAL_GPU_TYPE"] = comfyui["gpu_type"]
    if "cpu" in comfyui:
        env_vars["MODAL_GPU_CPU"] = str(comfyui["cpu"])
    if "timeout_seconds" in comfyui:
        env_vars["MODAL_GPU_TIMEOUT"] = str(comfyui["timeout_seconds"])
    if "max_containers" in comfyui:
        env_vars["MODAL_GPU_MAX_CONTAINERS"] = str(comfyui["max_containers"])
    if "scaledown_window_seconds" in comfyui:
        env_vars["MODAL_GPU_SCALEDOWN"] = str(comfyui["scaledown_window_seconds"])
    if "stall_timeout_seconds" in comfyui:
        env_vars["MODAL_COMFYUI_STALL_TIMEOUT_SECONDS"] = str(comfyui["stall_timeout_seconds"])
    if "max_runs_before_restart" in comfyui:
        env_vars["MODAL_COMFYUI_MAX_RUNS_BEFORE_RESTART"] = str(comfyui["max_runs_before_restart"])
    if "healthcheck_timeout_seconds" in comfyui:
        env_vars["MODAL_COMFYUI_HEALTHCHECK_TIMEOUT_SECONDS"] = str(comfyui["healthcheck_timeout_seconds"])
    if "capture_stall_diagnostics" in comfyui:
        env_vars["MODAL_COMFYUI_CAPTURE_STALL_DIAGNOSTICS"] = str(bool(comfyui["capture_stall_diagnostics"])).lower()
    if "stall_diagnostics_timeout_seconds" in comfyui:
        env_vars["MODAL_COMFYUI_STALL_DIAGNOSTICS_TIMEOUT_SECONDS"] = str(comfyui["stall_diagnostics_timeout_seconds"])
    if "stall_diagnostics_max_chars" in comfyui:
        env_vars["MODAL_COMFYUI_STALL_DIAGNOSTICS_MAX_CHARS"] = str(comfyui["stall_diagnostics_max_chars"])

    # Nested deploy_config: functions.download
    download = clean_dict(clean_dict(deploy.get("functions")).get("download"))
    if "timeout_seconds" in download:
        env_vars["MODAL_DOWNLOAD_TIMEOUT"] = str(download["timeout_seconds"])
    if "max_containers" in download:
        env_vars["MODAL_DOWNLOAD_MAX_CONTAINERS"] = str(download["max_containers"])

    # Nested deploy_config: functions.storage
    storage = clean_dict(clean_dict(deploy.get("functions")).get("storage"))
    if "timeout_seconds" in storage:
        env_vars["MODAL_STORAGE_TIMEOUT"] = str(storage["timeout_seconds"])
    if "max_containers" in storage:
        env_vars["MODAL_STORAGE_MAX_CONTAINERS"] = str(storage["max_containers"])

    return env_vars


# Modal provider type configuration
MODAL_PROVIDER_CONFIG = ProviderTypeConfig(
    type_name="modal",
    
    # Required credentials for Modal
    required_credentials=["token_id", "token_secret", "username"],
    optional_credentials=[],
    
    # Required config for Modal
    required_config=["app_name"],
    optional_config=["enable_memory_snapshot"],
    
    # Environment variable builder
    env_builder=build_modal_env_vars,
    
    # Worker image name
    worker_image="comfy-provider-image-worker",
    
    # Default port
    default_port=8000,
    client_class=ModalProvider
)


# Auto-register Modal provider type on import
ProviderRegistry.register(MODAL_PROVIDER_CONFIG)
