# Modal Provider Type Configuration
# This module contains all Modal-specific logic, keeping it out of core backend

from typing import Dict, Any

from .provider_registry import ProviderTypeConfig, ProviderRegistry
from .modal_provider import ModalProvider


def build_modal_env_vars(credentials: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, str]:
    """
    Build environment variables for Modal worker container.
    
    Args:
        credentials: Provider credentials (token_id, token_secret, username)
        config: Provider config (app_name, etc.)
        
    Returns:
        Environment variables dict
    """
    env_vars = {}
    
    # Core config
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
    
    # Optional: Memory snapshot setting (passed to worker for dynamic control)
    if config.get("enable_memory_snapshot") is not None:
        env_vars["ENABLE_MEMORY_SNAPSHOT"] = str(config["enable_memory_snapshot"]).lower()
    
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
    worker_image="comfy-provider-modal",
    
    # Default port
    default_port=8000,
    client_class=ModalProvider
)


# Auto-register Modal provider type on import
ProviderRegistry.register(MODAL_PROVIDER_CONFIG)
