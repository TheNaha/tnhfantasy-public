# Beam.cloud Provider Type Configuration
# This module contains all Beam-specific logic, keeping it out of core backend

from typing import Dict, Any

from .provider_registry import ProviderTypeConfig, ProviderRegistry


def build_beam_env_vars(credentials: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, str]:
    """
    Build environment variables for Beam worker container.
    
    Args:
        credentials: Provider credentials (api_key, workspace_id, hf_token, civitai_token)
        config: Provider config (gpu_url, storage_url, gpu_type)
        
    Returns:
        Environment variables dict
    """
    env_vars = {}
    
    # Beam authentication
    if credentials.get("api_key"):
        env_vars["BEAM_API_KEY"] = credentials["api_key"]
    if credentials.get("workspace_id"):
        env_vars["BEAM_WORKSPACE_ID"] = credentials["workspace_id"]
    
    # Beam endpoint URLs (new dual-endpoint architecture)
    if config.get("gpu_url"):
        env_vars["BEAM_GPU_URL"] = config["gpu_url"]
    if config.get("storage_url"):
        env_vars["BEAM_STORAGE_URL"] = config["storage_url"]
    
    # GPU type for reference
    if config.get("gpu_type"):
        env_vars["BEAM_GPU_TYPE"] = config["gpu_type"]
    
    # Download tokens
    if credentials.get("hf_token"):
        env_vars["HF_TOKEN"] = credentials["hf_token"]
    if credentials.get("civitai_token"):
        env_vars["CIVITAI_TOKEN"] = credentials["civitai_token"]
    
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
    worker_image="comfy-provider-beam",
    
    # Default port for worker container
    default_port=8000,
)


# Auto-register Beam provider type on import
ProviderRegistry.register(BEAM_PROVIDER_CONFIG)
