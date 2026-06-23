# Pydantic Settings Configuration + Full Config Management
# Combines v2's Pydantic approach with v1's file-based config persistence
#
# CONFIG SYSTEM SPLIT:
# .env (via Pydantic Settings) — infrastructure/secrets, rarely changes:
#   COMFY_DATABASE_URL, OUTPUT_DIR, INPUT_DIR, COMFY_PREVIEW_CACHE_DIR
#   HF_TOKEN, CIVITAI_TOKEN, MODAL_TOKEN_*, BEAM_API_KEY
#   COMFY_CORS_ORIGINS, COMFY_WORKER_BACKEND_URL
# config.json — runtime app behavior, UI-editable without restart:
#   Job concurrency, timeouts, retry settings
#   Image processing / thumbnail settings
#   Scheduler intervals
#
# CONFIGURATION PRECEDENCE (highest to lowest):
# 1. Environment variables (COMFY_* prefix)
# 2. File-based config (config.json) - runtime editable via API
# 3. DEFAULT_CONFIG (fallback values)
#
# This allows:
# - Production deployments to use env vars for secrets and overrides
# - Runtime configuration updates via UI without restarts
# - Sensible defaults for quick setup
import os
import json
from typing import Dict, Any, List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field, model_validator
from functools import lru_cache

from infrastructure.logging import config_logger

_cfg_logger = config_logger()


# ============================================================================
# DEFAULT CONFIGURATION - Fallback if config.json doesn't exist
# ============================================================================
DEFAULT_CONFIG = {
    "worker": {
        "poll_interval": 0.3,
        "retry_delay": 5,
        "poll_limit": 50
    },
    "jobs": {
        "default_limit": 20,
        "max_in_memory": 100,
        "max_concurrent": 5,
        "timeout": 300,
        "max_retries": 3,
        "retry_base_delay": 1.0,
        "retry_max_delay": 60.0
    },
    "model_sync": {
        "interval": 300,
        "retry_delay": 10,
        "reconciliation_interval": 120
    },

    "downloads": {
        "chunk_size": 8192,
        "auto_remove_delay": 5
    },
    "modal": {
        "timeout": 300,
        "max_containers": 1,
        "scaledown_window": 5
    },
    "api": {
        "gzip_minimum_size": 1000,
        "cors_origins": ["*"]
    },
    "jobs_cleanup": {
        "max_age_hours": 24,
        "auto_cleanup": False,
        "cleanup_interval": 3600
    },
    "image_processing": {
        # Thumbnail for grid/list views (feed cards and lightbox use full images)
        "thumbnail_sizes": {
            "medium": 512  # Optimal size for grid thumbnails
        },
        "thumbnail_format": "webp",
        # High quality (90%) for best visual fidelity with smaller footprint
        # WebP at 90% is ~60-70% smaller than PNG while maintaining quality
        "thumbnail_quality": 90,
        "thumbnail_directory": "thumb",
        "output_date_hierarchy": True,
        "embed_metadata_in_png": True,
        "blurhash_components_x": 4,
        "blurhash_components_y": 3,
        "blurhash_resize_max": 400
    }

}


# ============================================================================
# PYDANTIC SETTINGS (Environment Variable Support)
# ============================================================================
class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    # Database
    database_url: str = "sqlite:///./data/db/comfy.db"
    
    # Worker / Job Queue (overrides from env)
    worker_poll_interval: float = 0.3
    max_concurrent_jobs: int = 5
    job_retry_delay: float = 5.0
    
    # Job settings (consolidated from file config)
    job_timeout: int = 300
    job_max_retries: int = 3
    job_retry_base_delay: float = 1.0
    job_retry_max_delay: float = 60.0
    
    # Downloads
    download_chunk_size: int = 8192
    download_auto_remove_delay: int = 5
    
    # Modal
    modal_timeout: int = 300
    modal_max_containers: int = 1
    modal_scaledown_window: int = 5
    
    # API
    # Default: accept all origins ('*') for easier development
    # Override via COMFY_CORS_ORIGINS environment variable for production
    cors_origins: List[str] = ["*"]
    gzip_minimum_size: int = 1000
    worker_backend_url: str = "http://backend_v2:8002"
    
    # Model Sync
    model_sync_interval: int = 300
    reconciliation_interval: int = 120

    # Directories
    output_dir: str = os.path.abspath(os.path.join(os.path.dirname(__file__), "../output"))
    input_dir: str = os.path.abspath(os.path.join(os.path.dirname(__file__), "../input"))

    @model_validator(mode="before")
    @classmethod
    def load_directories_with_fallback(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "output_dir" not in data or data.get("output_dir") is None:
                comfy_out = os.environ.get("COMFY_OUTPUT_DIR")
                if comfy_out is not None:
                    data["output_dir"] = comfy_out
                else:
                    out = os.environ.get("OUTPUT_DIR")
                    if out is not None:
                        data["output_dir"] = out
            if "input_dir" not in data or data.get("input_dir") is None:
                comfy_in = os.environ.get("COMFY_INPUT_DIR")
                if comfy_in is not None:
                    data["input_dir"] = comfy_in
                else:
                    in_dir = os.environ.get("INPUT_DIR")
                    if in_dir is not None:
                        data["input_dir"] = in_dir
        return data

    class Config:
        env_prefix = "COMFY_"
        env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()


# ============================================================================
# FILE-BASED CONFIG MANAGEMENT (from v1)
# ============================================================================

# Global configuration instance
_config: Dict[str, Any] = None
_config_path = os.path.join(os.path.dirname(__file__), "config.json")


def load_config(config_path: str = None) -> Dict[str, Any]:
    """
    Load configuration from JSON file.
    Creates default config.json if it doesn't exist.
    
    Args:
        config_path: Optional path to config file. Defaults to backend_v2/config.json
        
    Returns:
        Configuration dictionary
    """
    global _config, _config_path
    
    if config_path:
        _config_path = config_path
    
    # If config exists, load it
    if os.path.exists(_config_path):
        try:
            with open(_config_path, 'r') as f:
                loaded_config = json.load(f)
                # Merge with defaults to ensure all keys exist
                _config = _deep_merge(DEFAULT_CONFIG.copy(), loaded_config)
                _cfg_logger.info("config_loaded", path=_config_path)
                return _config
        except Exception as e:
            _cfg_logger.warning("config_load_failed", path=_config_path, error=str(e))
    
    # Create default config file
    _config = DEFAULT_CONFIG.copy()
    try:
        os.makedirs(os.path.dirname(_config_path), exist_ok=True)
        with open(_config_path, 'w') as f:
            json.dump(_config, f, indent=2)
        _cfg_logger.info("config_created_default", path=_config_path)
    except Exception as e:
        _cfg_logger.warning("config_create_failed", error=str(e))
    
    return _config


def get_config() -> Dict[str, Any]:
    """
    Get current configuration.
    Loads config if not already loaded.
    
    Returns:
        Configuration dictionary
    """
    global _config
    if _config is None:
        load_config()
    return _config


def update_config(updates: Dict[str, Any], persist: bool = True) -> Dict[str, Any]:
    """
    Update configuration with new values.
    
    Args:
        updates: Dictionary with configuration updates (nested structure)
        persist: Whether to save changes to config.json
        
    Returns:
        Updated configuration dictionary
        
    Raises:
        ValueError: If validation fails
    """
    global _config
    
    if _config is None:
        load_config()
    
    # Validate updates before applying
    _validate_config(updates)
    
    # Deep merge updates into current config
    _config = _deep_merge(_config, updates)
    
    # Persist to file if requested
    if persist:
        try:
            with open(_config_path, 'w') as f:
                json.dump(_config, f, indent=2)
            _cfg_logger.info("config_saved", path=_config_path)
        except Exception as e:
            _cfg_logger.error("config_save_failed", error=str(e))
            raise
    
    return _config


def reset_config() -> Dict[str, Any]:
    """
    Reset configuration to defaults.
    
    Returns:
        Default configuration dictionary
    """
    global _config
    _config = DEFAULT_CONFIG.copy()
    
    try:
        with open(_config_path, 'w') as f:
            json.dump(_config, f, indent=2)
        _cfg_logger.info("config_reset")
    except Exception as e:
        _cfg_logger.warning("config_reset_save_failed", error=str(e))
    
    return _config


def _deep_merge(base: Dict, updates: Dict) -> Dict:
    """
    Deep merge two dictionaries.
    
    Args:
        base: Base dictionary
        updates: Updates to merge in
        
    Returns:
        Merged dictionary
    """
    result = base.copy()
    for key, value in updates.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _validate_config(config: Dict[str, Any]) -> None:
    """
    Validate configuration values.
    
    Args:
        config: Configuration dictionary to validate
        
    Raises:
        ValueError: If validation fails
    """
    # Worker validations
    if "worker" in config:
        worker = config["worker"]
        if "poll_interval" in worker and worker["poll_interval"] <= 0:
            raise ValueError("worker.poll_interval must be > 0")
        if "retry_delay" in worker and worker["retry_delay"] < 0:
            raise ValueError("worker.retry_delay must be >= 0")
        if "poll_limit" in worker and worker["poll_limit"] <= 0:
            raise ValueError("worker.poll_limit must be > 0")
    
    # Jobs validations
    if "jobs" in config:
        jobs = config["jobs"]
        if "default_limit" in jobs and jobs["default_limit"] <= 0:
            raise ValueError("jobs.default_limit must be > 0")
        if "max_in_memory" in jobs and jobs["max_in_memory"] <= 0:
            raise ValueError("jobs.max_in_memory must be > 0")
        if "max_concurrent" in jobs and jobs["max_concurrent"] <= 0:
            raise ValueError("jobs.max_concurrent must be > 0")
        if "timeout" in jobs and jobs["timeout"] <= 0:
            raise ValueError("jobs.timeout must be > 0")
        if "max_retries" in jobs and jobs["max_retries"] < 0:
            raise ValueError("jobs.max_retries must be >= 0")
        if "retry_base_delay" in jobs and jobs["retry_base_delay"] <= 0:
            raise ValueError("jobs.retry_base_delay must be > 0")
        if "retry_max_delay" in jobs and jobs["retry_max_delay"] <= 0:
            raise ValueError("jobs.retry_max_delay must be > 0")
    
    # Model sync validations
    if "model_sync" in config:
        sync = config["model_sync"]
        if "interval" in sync and sync["interval"] <= 0:
            raise ValueError("model_sync.interval must be > 0")
        if "retry_delay" in sync and sync["retry_delay"] < 0:
            raise ValueError("model_sync.retry_delay must be >= 0")
    

    
    # Download validations
    if "downloads" in config:
        downloads = config["downloads"]
        if "chunk_size" in downloads and downloads["chunk_size"] <= 0:
            raise ValueError("downloads.chunk_size must be > 0")
        if "auto_remove_delay" in downloads and downloads["auto_remove_delay"] < 0:
            raise ValueError("downloads.auto_remove_delay must be >= 0")
    
    # Modal validations
    if "modal" in config:
        modal = config["modal"]
        if "timeout" in modal and modal["timeout"] <= 0:
            raise ValueError("modal.timeout must be > 0")
        if "max_containers" in modal and modal["max_containers"] <= 0:
            raise ValueError("modal.max_containers must be > 0")
        if "scaledown_window" in modal and modal["scaledown_window"] < 0:
            raise ValueError("modal.scaledown_window must be >= 0")
    
    # API validations
    if "api" in config:
        api = config["api"]
        if "gzip_minimum_size" in api and api["gzip_minimum_size"] < 0:
            raise ValueError("api.gzip_minimum_size must be >= 0")
        if "cors_origins" in api and not isinstance(api["cors_origins"], list):
            raise ValueError("api.cors_origins must be a list")
    
    # Jobs cleanup validations
    if "jobs_cleanup" in config:
        cleanup = config["jobs_cleanup"]
        if "max_age_hours" in cleanup and cleanup["max_age_hours"] <= 0:
            raise ValueError("jobs_cleanup.max_age_hours must be > 0")
        if "cleanup_interval" in cleanup and cleanup["cleanup_interval"] <= 0:
            raise ValueError("jobs_cleanup.cleanup_interval must be > 0")
    
    # Image processing validations
    if "image_processing" in config:
        img = config["image_processing"]
        if "thumbnail_quality" in img and not (1 <= img["thumbnail_quality"] <= 100):
            raise ValueError("image_processing.thumbnail_quality must be between 1 and 100")
        if "blurhash_components_x" in img and not (1 <= img["blurhash_components_x"] <= 9):
            raise ValueError("image_processing.blurhash_components_x must be between 1 and 9")
        if "blurhash_components_y" in img and not (1 <= img["blurhash_components_y"] <= 9):
            raise ValueError("image_processing.blurhash_components_y must be between 1 and 9")
        if "blurhash_resize_max" in img and img["blurhash_resize_max"] <= 0:
            raise ValueError("image_processing.blurhash_resize_max must be > 0")


# ============================================================================
# CONVENIENCE FUNCTIONS for accessing common settings
# ============================================================================

# Worker settings
def get_worker_poll_interval() -> float:
    """Get worker poll interval in seconds."""
    return get_config()["worker"]["poll_interval"]


def get_worker_retry_delay() -> int:
    """Get worker retry delay in seconds."""
    return get_config()["worker"]["retry_delay"]


def get_worker_poll_limit() -> int:
    """Get worker poll limit."""
    return get_config()["worker"]["poll_limit"]


# Jobs settings
def get_default_jobs_limit() -> int:
    """Get default jobs limit."""
    return get_config()["jobs"]["default_limit"]


def get_max_jobs_in_memory() -> int:
    """Get max jobs in memory."""
    return get_config()["jobs"]["max_in_memory"]


def get_max_concurrent_jobs() -> int:
    """Get max concurrent jobs."""
    return get_config()["jobs"]["max_concurrent"]


def _env_var_is_set(env_name: str) -> bool:
    """Check if an environment variable is explicitly set (with COMFY_ prefix)."""
    return os.environ.get(f"COMFY_{env_name}") is not None


def _normalize_worker_backend_url(url: Optional[str]) -> str:
    """Normalize legacy or empty worker backend URL values."""
    default_url = "http://backend_v2:8002"
    candidate = (url or "").strip()

    if not candidate:
        return default_url

    if "comfy-backend-v2" in candidate:
        normalized = candidate.replace("comfy-backend-v2", "backend_v2")
        _cfg_logger.warning(
            "worker_backend_url_normalized_legacy_host",
            original=candidate,
            normalized=normalized,
        )
        return normalized

    return candidate


def get_job_timeout() -> int:
    """Get job timeout in seconds. Prefers env var (settings), falls back to file config."""
    # Use Pydantic settings if explicitly set via env var, else use file config for runtime updates
    return settings.job_timeout if _env_var_is_set("JOB_TIMEOUT") else get_config()["jobs"]["timeout"]


def get_job_max_retries() -> int:
    """Get maximum number of job retries. Prefers env var, falls back to file config."""
    return settings.job_max_retries if _env_var_is_set("JOB_MAX_RETRIES") else get_config()["jobs"]["max_retries"]


def get_job_retry_base_delay() -> float:
    """Get base delay for exponential backoff in seconds. Prefers env var, falls back to file config."""
    return settings.job_retry_base_delay if _env_var_is_set("JOB_RETRY_BASE_DELAY") else get_config()["jobs"]["retry_base_delay"]


def get_job_retry_max_delay() -> float:
    """Get maximum delay for exponential backoff in seconds. Prefers env var, falls back to file config."""
    return settings.job_retry_max_delay if _env_var_is_set("JOB_RETRY_MAX_DELAY") else get_config()["jobs"]["retry_max_delay"]


# Model sync settings
def get_model_sync_interval() -> int:
    """Get model sync interval in seconds."""
    return get_config()["model_sync"]["interval"]


def get_model_sync_retry_delay() -> int:
    """Get model sync retry delay in seconds."""
    return get_config()["model_sync"]["retry_delay"]


def get_reconciliation_interval() -> int:
    """Get reconciliation interval in seconds."""
    return get_config()["model_sync"]["reconciliation_interval"]


def get_worker_backend_url() -> str:
    """Get backend URL exposed to provider containers. Prefers env var, falls back to file config."""
    default_url = "http://backend_v2:8002"
    configured_url = (
        settings.worker_backend_url
        if _env_var_is_set("WORKER_BACKEND_URL")
        else get_config()["api"].get("worker_backend_url", default_url)
    )
    return _normalize_worker_backend_url(configured_url)





# Download settings
def get_download_chunk_size() -> int:
    """Get download chunk size in bytes."""
    return get_config()["downloads"]["chunk_size"]


def get_download_auto_remove_delay() -> int:
    """Get download auto-remove delay in seconds."""
    return get_config()["downloads"]["auto_remove_delay"]


# Modal settings
def get_modal_timeout() -> int:
    """Get Modal timeout in seconds."""
    return get_config()["modal"]["timeout"]


def get_modal_max_containers() -> int:
    """Get Modal max containers."""
    return get_config()["modal"]["max_containers"]


def get_modal_scaledown_window() -> int:
    """Get Modal scaledown window in seconds."""
    return get_config()["modal"]["scaledown_window"]


# API settings
def get_cors_origins() -> List[str]:
    """Get CORS origins list."""
    if _env_var_is_set("CORS_ORIGINS"):
        return settings.cors_origins
    api_config = get_config().get("api", {})
    return api_config.get("cors_origins", settings.cors_origins)


def get_gzip_minimum_size() -> int:
    """Get GZip minimum size in bytes."""
    return get_config()["api"]["gzip_minimum_size"]


# Jobs cleanup settings
def get_jobs_cleanup_max_age() -> int:
    """Get max age for job cleanup in hours."""
    return get_config()["jobs_cleanup"]["max_age_hours"]


def get_jobs_cleanup_auto() -> bool:
    """Get whether auto cleanup is enabled."""
    return get_config()["jobs_cleanup"]["auto_cleanup"]


def get_jobs_cleanup_interval() -> int:
    """Get cleanup interval in seconds."""
    return get_config()["jobs_cleanup"]["cleanup_interval"]


# Image processing settings
def get_thumbnail_sizes() -> dict:
    """Get thumbnail sizes configuration."""
    return get_config()["image_processing"]["thumbnail_sizes"]


def get_thumbnail_quality() -> int:
    """Get thumbnail JPEG quality (1-100)."""
    return get_config()["image_processing"]["thumbnail_quality"]


def get_blurhash_components():
    """Get blurhash components as (x, y) tuple."""
    cfg = get_config()["image_processing"]
    return (cfg["blurhash_components_x"], cfg["blurhash_components_y"])


def get_blurhash_resize_max() -> int:
    """Get blurhash resize max dimension."""
    return get_config()["image_processing"]["blurhash_resize_max"]


def get_thumbnail_format() -> str:
    """Get thumbnail format (webp, png, jpg)."""
    return get_config()["image_processing"].get("thumbnail_format", "webp")


def get_thumbnail_directory() -> str:
    """Get thumbnail subdirectory name."""
    return get_config()["image_processing"].get("thumbnail_directory", "thumb")


def get_output_date_hierarchy() -> bool:
    """Get whether to use date-based output hierarchy (YYYY/MM/DD/)."""
    return get_config()["image_processing"].get("output_date_hierarchy", True)


def get_embed_metadata_in_png() -> bool:
    """Get whether to embed metadata directly in PNG files."""
    return get_config()["image_processing"].get("embed_metadata_in_png", True)
