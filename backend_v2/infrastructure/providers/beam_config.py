# Beam.cloud Provider Type Configuration
# This module contains all Beam-specific logic, keeping it out of core backend

from typing import Any

from .beam_provider import BeamProvider
from .provider_registry import ProviderRegistry, ProviderTypeConfig
from .provider_registry import clean_registry_dict as clean_dict


def build_beam_env_vars(credentials: dict[str, Any], config: dict[str, Any]) -> dict[str, str]:
    """
    Build environment variables for Beam worker container.

    This is the single source of truth for Beam env vars.
    Called by provider_env_builder for container startup and by the registry for validation.

    Args:
        credentials: Provider credentials (api_key, workspace_id, hf_token, civitai_token)
        config: Provider config dict (may include nested runtime_config / deploy_config keys)

    Returns:
        Environment variables dict
    """
    env_vars: dict[str, str] = {}

    # Core config
    env_vars["ENGINE"] = "beam"
    if config.get("id"):
        env_vars["PROVIDER_ID"] = config["id"]
    from config import settings
    env_vars["BACKEND_URL"] = settings.worker_backend_url

    # Beam authentication
    if credentials.get("api_key"):
        env_vars["BEAM_API_KEY"] = credentials["api_key"]
    if credentials.get("workspace_id"):
        env_vars["BEAM_WORKSPACE_ID"] = credentials["workspace_id"]

    beta9_token = credentials.get("beta9_token") or credentials.get("api_key")
    if beta9_token:
        env_vars["BETA9_TOKEN"] = beta9_token
        env_vars["BEAM_TOKEN"] = beta9_token

    # Download tokens
    if credentials.get("hf_token"):
        env_vars["HF_TOKEN"] = credentials["hf_token"]
    if credentials.get("civitai_token"):
        env_vars["CIVITAI_TOKEN"] = credentials["civitai_token"]

    deploy = clean_dict(config.get("deploy_config") or config)

    beta9_gateway_host = (
        deploy.get("beta9_gateway_host")
        or deploy.get("gateway_host")
        or "gateway.beam.cloud"
    )
    beta9_gateway_port = (
        deploy.get("beta9_gateway_port")
        or deploy.get("gateway_port")
        or 443
    )
    env_vars["BETA9_GATEWAY_HOST"] = str(beta9_gateway_host)
    env_vars["BETA9_GATEWAY_PORT"] = str(beta9_gateway_port)
    env_vars["GATEWAY_HOST"] = str(beta9_gateway_host)
    env_vars["GATEWAY_PORT"] = str(beta9_gateway_port)

    beta9_api_host = deploy.get("api_host") or "app.beam.cloud"
    beta9_api_port = deploy.get("api_port") or 443
    env_vars["API_HOST"] = str(beta9_api_host)
    env_vars["API_PORT"] = str(beta9_api_port)

    if "gpu_url" in deploy:
        env_vars["BEAM_GPU_URL"] = deploy["gpu_url"]
    if "storage_url" in deploy:
        env_vars["BEAM_STORAGE_URL"] = deploy["storage_url"]
    if "download_url" in deploy:
        env_vars["BEAM_DOWNLOAD_URL"] = deploy["download_url"]
    if "gpu_type" in deploy:
        env_vars["BEAM_GPU_TYPE"] = deploy["gpu_type"]

    beam_functions = clean_dict(deploy.get("functions"))
    gpu_func = clean_dict(beam_functions.get("comfyui"))
    if "gpu_type" in gpu_func:
        env_vars["BEAM_GPU_TYPE"] = gpu_func["gpu_type"]
    if "cpu" in gpu_func:
        env_vars["BEAM_GPU_CPU"] = str(gpu_func["cpu"])
    if "memory" in gpu_func:
        env_vars["BEAM_GPU_MEMORY"] = str(gpu_func["memory"])
    if "timeout_seconds" in gpu_func:
        env_vars["BEAM_GPU_TIMEOUT"] = str(gpu_func["timeout_seconds"])
    if "keep_warm_seconds" in gpu_func:
        env_vars["BEAM_GPU_KEEP_WARM"] = str(gpu_func["keep_warm_seconds"])
    if "concurrent_requests" in gpu_func:
        env_vars["BEAM_GPU_CONCURRENT"] = str(gpu_func["concurrent_requests"])

    download = clean_dict(beam_functions.get("download"))
    if "cpu" in download:
        env_vars["BEAM_DOWNLOAD_CPU"] = str(download["cpu"])
    if "memory" in download:
        env_vars["BEAM_DOWNLOAD_MEMORY"] = str(download["memory"])
    if "timeout_seconds" in download:
        env_vars["BEAM_DOWNLOAD_TIMEOUT"] = str(download["timeout_seconds"])
    if "max_containers" in download:
        env_vars["BEAM_DOWNLOAD_MAX_CONTAINERS"] = str(download["max_containers"])

    storage = clean_dict(beam_functions.get("storage"))
    if "cpu" in storage:
        env_vars["BEAM_STORAGE_CPU"] = str(storage["cpu"])
    if "memory" in storage:
        env_vars["BEAM_STORAGE_MEMORY"] = str(storage["memory"])
    if "timeout_seconds" in storage:
        env_vars["BEAM_STORAGE_TIMEOUT"] = str(storage["timeout_seconds"])
    if "concurrent_requests" in storage:
        env_vars["BEAM_STORAGE_CONCURRENT"] = str(storage["concurrent_requests"])

    return env_vars


# Beam provider type configuration
BEAM_PROVIDER_CONFIG = ProviderTypeConfig(
    type_name="beam",
    
    # Required credentials for Beam
    required_credentials=["api_key"],
    optional_credentials=["workspace_id", "hf_token", "civitai_token"],
    
    # Required config: both endpoint URLs
    required_config=["gpu_url", "storage_url"],
    optional_config=["gpu_type"],
    
    # Environment variable builder
    env_builder=build_beam_env_vars,
    
    # Worker image name
    worker_image="comfy-provider-image-worker",
    
    # Default port for worker container
    default_port=8000,
    client_class=BeamProvider
)


# Auto-register Beam provider type on import
ProviderRegistry.register(BEAM_PROVIDER_CONFIG)
