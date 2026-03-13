# Settings routes - Runtime configuration management
#
# Allows reading and updating backend configuration at runtime without
# restarting the server.  Settings are persisted to `config.json` so they
# survive restarts.  Environment variables (COMFY_*) take precedence.
#
# KEY ENDPOINTS:
#   GET  /api/settings           – Read current configuration
#   PUT  /api/settings           – Update configuration (partial update)
#   POST /api/settings/reset     – Reset to compiled-in defaults
#   GET  /api/settings/branding  – Read UI branding configuration
#   PUT  /api/settings/branding  – Update branding (name, logo, theme)
import os
import json
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from sqlmodel import Session

import config as app_config
from api.deps import get_session
from services.model_service import ModelService
from infrastructure.logging import get_logger

logger = get_logger("settings_route")

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ============================================================================
# APPLICATION SETTINGS (from v1 config management)
# ============================================================================

@router.get("")
async def get_settings() -> Dict[str, Any]:
    """
    Get current application settings.
    
    Returns:
        Current configuration dictionary
    """
    try:
        return {
            "status": "success",
            "settings": app_config.get_config()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schema")
async def get_settings_schema() -> Dict[str, Any]:
    """
    Get settings schema with descriptions and types.
    Useful for building dynamic UI.
    
    Returns:
        Settings schema dictionary
    """
    schema = {
        "worker": {
            "description": "Background worker configuration",
            "fields": {
                "poll_interval": {
                    "type": "number",
                    "description": "Seconds between job checks",
                    "min": 0.1,
                    "max": 10,
                    "default": 0.3
                },
                "retry_delay": {
                    "type": "integer",
                    "description": "Seconds to wait after error before retrying",
                    "min": 1,
                    "max": 60,
                    "default": 5
                },
                "poll_limit": {
                    "type": "integer",
                    "description": "Number of jobs worker fetches per iteration",
                    "min": 1,
                    "max": 200,
                    "default": 50
                }
            }
        },
        "jobs": {
            "description": "Job management configuration",
            "fields": {
                "default_limit": {
                    "type": "integer",
                    "description": "Default number of jobs to return in API",
                    "min": 1,
                    "max": 100,
                    "default": 20
                },
                "max_in_memory": {
                    "type": "integer",
                    "description": "Maximum jobs to keep in memory for SSE",
                    "min": 10,
                    "max": 500,
                    "default": 100
                },
                "max_concurrent": {
                    "type": "integer",
                    "description": "Maximum concurrent jobs to process",
                    "min": 1,
                    "max": 10,
                    "default": 5
                }
            }
        },
        "model_sync": {
            "description": "Model synchronization configuration",
            "fields": {
                "interval": {
                    "type": "integer",
                    "description": "Seconds between model syncs",
                    "min": 60,
                    "max": 3600,
                    "default": 300
                },
                "retry_delay": {
                    "type": "integer",
                    "description": "Seconds to wait after sync error",
                    "min": 1,
                    "max": 60,
                    "default": 10
                },
                "reconciliation_interval": {
                    "type": "integer",
                    "description": "Seconds between reconciliation checks",
                    "min": 60,
                    "max": 600,
                    "default": 120
                }
            }
        },
        "sse": {
            "description": "Server-Sent Events configuration",
            "fields": {
                "poll_interval": {
                    "type": "number",
                    "description": "Seconds between SSE updates",
                    "min": 0.1,
                    "max": 5,
                    "default": 0.5
                },
                "error_retry_delay": {
                    "type": "integer",
                    "description": "Seconds to wait after SSE error",
                    "min": 1,
                    "max": 30,
                    "default": 1
                },
                "heartbeat_interval": {
                    "type": "integer",
                    "description": "Seconds between heartbeat pings",
                    "min": 10,
                    "max": 120,
                    "default": 30
                }
            }
        },
        "downloads": {
            "description": "Download management configuration",
            "fields": {
                "chunk_size": {
                    "type": "integer",
                    "description": "Bytes per download chunk",
                    "min": 1024,
                    "max": 1048576,
                    "default": 8192
                },
                "auto_remove_delay": {
                    "type": "integer",
                    "description": "Seconds before auto-removing completed downloads",
                    "min": 0,
                    "max": 300,
                    "default": 5
                }
            }
        },
        "jobs_cleanup": {
            "description": "Job cleanup configuration",
            "fields": {
                "max_age_hours": {
                    "type": "integer",
                    "description": "Maximum age in hours for completed jobs",
                    "min": 1,
                    "max": 168,
                    "default": 24
                },
                "auto_cleanup": {
                    "type": "boolean",
                    "description": "Enable automatic cleanup of old jobs",
                    "default": False
                },
                "cleanup_interval": {
                    "type": "integer",
                    "description": "Interval between auto-cleanup runs (seconds)",
                    "min": 60,
                    "max": 86400,
                    "default": 3600
                }
            }
        },
        "image_processing": {
            "description": "Image thumbnail and BlurHash processing configuration",
            "fields": {
                "thumbnail_sizes": {
                    "type": "object",
                    "description": "Thumbnail size definitions {name: max_dimension}",
                    "default": {"thumb": 256, "medium": 512}
                },
                "thumbnail_quality": {
                    "type": "integer",
                    "description": "JPEG quality for thumbnails (1-100)",
                    "min": 1,
                    "max": 100,
                    "default": 85
                },
                "blurhash_components_x": {
                    "type": "integer",
                    "description": "BlurHash X components (higher = more detail)",
                    "min": 1,
                    "max": 9,
                    "default": 4
                },
                "blurhash_components_y": {
                    "type": "integer",
                    "description": "BlurHash Y components (higher = more detail)",
                    "min": 1,
                    "max": 9,
                    "default": 3
                },
                "blurhash_resize_max": {
                    "type": "integer",
                    "description": "Max dimension for BlurHash generation (smaller = faster)",
                    "min": 100,
                    "max": 1000,
                    "default": 400
                }
            }
        },
        "modal": {
            "description": "Modal.com infrastructure configuration (read-only)",
            "readonly": True,
            "fields": {
                "timeout": {
                    "type": "integer",
                    "description": "Timeout for Modal function calls (seconds)",
                    "min": 60,
                    "max": 3600,
                    "default": 300
                },
                "max_containers": {
                    "type": "integer",
                    "description": "Maximum number of containers",
                    "min": 1,
                    "max": 10,
                    "default": 1
                },
                "scaledown_window": {
                    "type": "integer",
                    "description": "Scaledown window (seconds)",
                    "min": 0,
                    "max": 600,
                    "default": 5
                }
            }
        },
        "api": {
            "description": "API server configuration",
            "fields": {
                "cors_origins": {
                    "type": "array",
                    "description": "Allowed CORS origins",
                    "default": ["http://localhost:5173", "http://localhost:5174"]
                },
                "gzip_minimum_size": {
                    "type": "integer",
                    "description": "Minimum response size for gzip (bytes)",
                    "min": 0,
                    "max": 10000,
                    "default": 1000
                }
            }
        }
    }
    
    return {
        "status": "success",
        "schema": schema
    }


@router.put("")
async def update_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update application settings.
    
    Args:
        updates: Dictionary with configuration updates
        
    Returns:
        Updated configuration
        
    Raises:
        HTTPException: If validation fails
    """
    try:
        # Don't allow updating Modal settings
        if "modal" in updates:
            raise ValueError("Modal.com settings are read-only and require redeployment")
        
        updated_config = app_config.update_config(updates, persist=True)
        return {
            "status": "success",
            "message": "Settings updated successfully",
            "settings": updated_config
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset")
async def reset_settings() -> Dict[str, Any]:
    """
    Reset all settings to defaults.
    
    Returns:
        Default configuration
    """
    try:
        default_config = app_config.reset_config()
        return {
            "status": "success",
            "message": "Settings reset to defaults",
            "settings": default_config
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# BRANDING CONFIGURATION
# ============================================================================

BRANDING_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../../data/branding.json")

def get_branding_config() -> Dict[str, Any]:
    """Load branding configuration from JSON file."""
    default_branding = {
        "appName": "TNH-Comfy",
        "logoUrl": "/logo.png",
        "faviconUrl": "/favicon.ico"
    }
    
    # Ensure data directory exists
    os.makedirs(os.path.dirname(BRANDING_CONFIG_PATH), exist_ok=True)
    
    if os.path.exists(BRANDING_CONFIG_PATH):
        try:
            with open(BRANDING_CONFIG_PATH, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error("branding_config_load_failed", error=str(e))
            return default_branding
    else:
        save_branding_config(default_branding)
        return default_branding


def save_branding_config(config: Dict[str, Any]):
    """Save branding configuration to JSON file."""
    os.makedirs(os.path.dirname(BRANDING_CONFIG_PATH), exist_ok=True)
    with open(BRANDING_CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)


class BrandingRequest(BaseModel):
    appName: str
    logoUrl: Optional[str] = "/logo.png"
    faviconUrl: Optional[str] = "/favicon.ico"


@router.get("/branding")
async def get_branding():
    """Get current branding settings."""
    return get_branding_config()


@router.post("/branding")
async def update_branding(request: BrandingRequest):
    """Update branding settings."""
    config = {
        "appName": request.appName,
        "logoUrl": request.logoUrl,
        "faviconUrl": request.faviconUrl
    }
    save_branding_config(config)
    return {"status": "success", "branding": config}


# ============================================================================
# SESSION MANAGEMENT
# ============================================================================

@router.post("/session")
async def start_session():
    """Start a session (for compatibility)."""
    return {"status": "ready"}


@router.get("/session")
async def get_session_status():
    """Get session status."""
    return {"status": "active"}


# ============================================================================
# PRESETS - Curated model list
# ============================================================================

PRESETS = [
    # Checkpoints
    {
        "name": "Nova Anime XL v13",
        "type": "checkpoints",
        "filename": "Nova-Anime-XL_v13.0.safetensors",
        "url": "https://civitai.com/api/download/models/2392184?type=Model&format=SafeTensor&size=pruned&fp=fp16",
        "description": "High quality anime style (SDXL)."
    },
    {
        "name": "Pony Diffusion V6 XL",
        "type": "checkpoints",
        "filename": "PonyDiffusionV6XL.safetensors",
        "url": "https://civitai.com/api/download/models/290640?type=Model&format=SafeTensor&size=pruned&fp=fp16",
        "description": "Versatile, high quality art style (SDXL)."
    },
    {
        "name": "WAI-illustrious-SDXL v15",
        "type": "checkpoints",
        "filename": "WAI-illustrious-SDXL-v15.safetensors",
        "url": "https://civitai.com/api/download/models/2167369?type=Model&format=SafeTensor&size=pruned&fp=fp16",
        "description": "Illustrious style (SDXL)."
    },
    # Upscalers
    {
        "name": "4x-UltraSharp",
        "type": "upscale_models",
        "filename": "4x-UltraSharp.pth",
        "url": "https://huggingface.co/lokCX/4x-Ultrasharp/resolve/main/4x-UltraSharp.pth",
        "description": "General purpose upscaler, high detail."
    },
    {
        "name": "4x_foolhardy_Remacri",
        "type": "upscale_models",
        "filename": "4x_foolhardy_Remacri.pth",
        "url": "https://huggingface.co/Facehugger/4x-foolhardy-Remacri/resolve/main/4x_foolhardy_Remacri.pth",
        "description": "Balanced upscaler with good detail."
    },
    # LoRAs
    {
        "name": "Detail Tweaker XL",
        "type": "loras",
        "filename": "DetailTweakerXL.safetensors",
        "url": "https://civitai.com/api/download/models/135867?type=Model&format=SafeTensor",
        "description": "Add or remove detail from your generations."
    },
]


@router.get("/presets")
async def get_presets(session: Session = Depends(get_session)):
    """Returns a list of curated models with installation status."""
    model_service = ModelService(session)
    
    presets = []
    for preset in PRESETS:
        directory = f"models/{preset['type']}"
        
        # Check if model is installed
        model = await model_service.get_model_by_name(preset["filename"], directory)
        installed = model is not None
        
        presets.append({
            **preset,
            "installed": installed
        })
    
    return {"presets": presets}
