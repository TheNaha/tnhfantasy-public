# Modal LLM Provider Type Configuration
# This module registers the 'modal_llm' provider type for LLM inference via vLLM on Modal.
# The backend dispatches LLM jobs directly to the worker's /inference endpoint via
# call_llm_provider(), so no client_class.run_inference is needed here.

from typing import Any

from .modal_provider import ModalProvider
from .provider_registry import ProviderRegistry, ProviderTypeConfig
from .provider_registry import clean_registry_dict as clean_dict


def build_modal_llm_env_vars(credentials: dict[str, Any], config: dict[str, Any]) -> dict[str, str]:
    """
    Build environment variables for Modal LLM worker container.

    Args:
        credentials: Provider credentials (token_id, token_secret, username)
        config: Provider config dict (may include nested runtime_config / deploy_config keys)

    Returns:
        Environment variables dict
    """
    env_vars: dict[str, str] = {}

    env_vars["ENGINE"] = "modal"
    if config.get("id"):
        env_vars["PROVIDER_ID"] = config["id"]
    from config import settings
    env_vars["BACKEND_URL"] = settings.worker_backend_url

    if credentials.get("token_id"):
        env_vars["MODAL_TOKEN_ID"] = credentials["token_id"]
    if credentials.get("token_secret"):
        env_vars["MODAL_TOKEN_SECRET"] = credentials["token_secret"]
    if credentials.get("username"):
        env_vars["MODAL_USERNAME"] = credentials["username"]

    if config.get("app_name"):
        env_vars["MODAL_APP_NAME"] = config["app_name"]

    if config.get("enable_memory_snapshot") is not None:
        env_vars["ENABLE_MEMORY_SNAPSHOT"] = str(config["enable_memory_snapshot"]).lower()

    deploy = clean_dict(config.get("deploy_config") or config)
    comfyui = clean_dict(clean_dict(deploy.get("functions")).get("vllm"))
    if "gpu_type" in comfyui:
        env_vars["MODAL_GPU_TYPE"] = comfyui["gpu_type"]
    if "timeout_seconds" in comfyui:
        env_vars["MODAL_GPU_TIMEOUT"] = str(comfyui["timeout_seconds"])
    if "max_containers" in comfyui:
        env_vars["MODAL_GPU_MAX_CONTAINERS"] = str(comfyui["max_containers"])
    if "scaledown_window_seconds" in comfyui:
        env_vars["MODAL_GPU_SCALEDOWN"] = str(comfyui["scaledown_window_seconds"])
    if "gpu_cpu" in comfyui:
        env_vars["MODAL_GPU_CPU"] = str(comfyui["gpu_cpu"])

    download = clean_dict(clean_dict(deploy.get("functions")).get("download"))
    if "timeout_seconds" in download:
        env_vars["MODAL_DOWNLOAD_TIMEOUT"] = str(max(int(download["timeout_seconds"]), 3600))
    if "max_containers" in download:
        env_vars["MODAL_DOWNLOAD_MAX_CONTAINERS"] = str(download["max_containers"])

    storage = clean_dict(clean_dict(deploy.get("functions")).get("storage"))
    if "timeout_seconds" in storage:
        env_vars["MODAL_STORAGE_TIMEOUT"] = str(storage["timeout_seconds"])
    if "max_containers" in storage:
        env_vars["MODAL_STORAGE_MAX_CONTAINERS"] = str(storage["max_containers"])

    return env_vars


MODAL_LLM_PROVIDER_CONFIG = ProviderTypeConfig(
    type_name="modal_llm",

    required_credentials=["token_id", "token_secret", "username"],
    optional_credentials=[],

    required_config=["app_name"],
    optional_config=["enable_memory_snapshot"],

    env_builder=build_modal_llm_env_vars,

    worker_image="comfy-provider-llm-worker",

    default_port=8000,
    client_class=ModalProvider,
)


ProviderRegistry.register(MODAL_LLM_PROVIDER_CONFIG)
