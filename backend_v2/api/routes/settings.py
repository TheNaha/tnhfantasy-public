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
import asyncio
import json
import os
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session

import config as app_config
from api.deps import get_session
from core.exceptions import ComfyError, ValidationError
from infrastructure.logging import get_logger

logger = get_logger("settings_route")

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ============================================================================
# APPLICATION SETTINGS (from v1 config management)
# ============================================================================

@router.get("")
async def get_settings() -> dict[str, Any]:
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
        raise ComfyError(str(e))


def _default(path: str) -> Any:
    """Resolve a dotted path against `config.DEFAULT_CONFIG`.

    Every documented `default` is read from here instead of being retyped, so a
    changed default can never leave the schema advertising the old value — the
    four drifts this replaced (thumbnail_quality 85/90, blurhash_resize_max
    400/64, a phantom `thumb` thumbnail size, and a one-origin CORS default) were
    all literals that outlived the values they described.

    The schema is still hand-written: types, bounds, descriptions and the
    env-var / restart annotations are per-field judgement a generator cannot
    infer. `tests/test_settings_exposure.py` asserts that every key it documents
    exists in DEFAULT_CONFIG, so it cannot describe config that is not there.
    """
    node: Any = app_config.DEFAULT_CONFIG
    for part in path.split("."):
        node = node[part]
    return node


# Bound once while the ASGI app is constructed (api/app_setup.py: CORSMiddleware
# and GZipMiddleware), so changing them in config.json cannot take effect
# without a restart. Annotated so the UI can say so instead of implying the
# write was live.
RESTART_REQUIRED_PATHS = frozenset({"api.cors_origins", "api.gzip_minimum_size"})


@router.get("/schema")
async def get_settings_schema() -> dict[str, Any]:
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
                    "default": _default("worker.poll_interval")
                },
                "retry_delay": {
                    "type": "integer",
                    "description": "Seconds to wait after error before retrying",
                    "min": 1,
                    "max": 60,
                    "default": _default("worker.retry_delay")
                },
                "poll_limit": {
                    "type": "integer",
                    "description": "Number of jobs worker fetches per iteration",
                    "min": 1,
                    "max": 200,
                    "default": _default("worker.poll_limit")
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
                    "default": _default("jobs.default_limit")
                },
                "max_in_memory": {
                    "type": "integer",
                    "description": "Maximum jobs to keep in memory for SSE",
                    "min": 10,
                    "max": 500,
                    "default": _default("jobs.max_in_memory")
                },
                "max_concurrent": {
                    "type": "integer",
                    "description": (
                        "In-flight job ceiling, applied per task type (image and LLM "
                        "are counted separately, so LLM work is never starved behind a "
                        "saturated image queue). Effective concurrency is also bounded "
                        "by the number of enabled providers, because the worker pool is "
                        "sized from it — so a value above the provider count has no "
                        "effect. Lower it to throttle dispatch rate on paid providers."
                    ),
                    "min": 1,
                    "max": 10,
                    "default": _default("jobs.max_concurrent")
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        "Seconds the backend waits for a job before giving up. Keep it "
                        "at or above the provider worker's own timeout: too low and the "
                        "backend abandons a workflow that is still legally running."
                    ),
                    "min": 60,
                    "max": 86400,
                    "default": _default("jobs.timeout"),
                    "env_var": app_config.ENV_VAR_OVERRIDES["jobs.timeout"]
                },
                "max_retries": {
                    "type": "integer",
                    "description": "Automatic retries after a failed attempt",
                    "min": 0,
                    "max": 10,
                    "default": _default("jobs.max_retries"),
                    "env_var": app_config.ENV_VAR_OVERRIDES["jobs.max_retries"]
                },
                "retry_base_delay": {
                    "type": "number",
                    "description": "Base delay of the exponential backoff between retries (seconds)",
                    "min": 0.1,
                    "max": 600,
                    "default": _default("jobs.retry_base_delay"),
                    "env_var": app_config.ENV_VAR_OVERRIDES["jobs.retry_base_delay"]
                },
                "retry_max_delay": {
                    "type": "number",
                    "description": "Ceiling for the exponential backoff between retries (seconds)",
                    "min": 1,
                    "max": 3600,
                    "default": _default("jobs.retry_max_delay"),
                    "env_var": app_config.ENV_VAR_OVERRIDES["jobs.retry_max_delay"]
                },
                # Per-task-type overrides merged over the values above by
                # config._job_config; dotted keys keep the schema flat and
                # machine-readable (the UI looks settings up by dotted path).
                "llm.timeout": {
                    "type": "integer",
                    "description": "LLM job timeout override (seconds)",
                    "min": 10,
                    "max": 3600,
                    "default": _default("jobs.llm.timeout")
                },
                "llm.max_retries": {
                    "type": "integer",
                    "description": "LLM job retry override",
                    "min": 0,
                    "max": 10,
                    "default": _default("jobs.llm.max_retries")
                },
                "llm.stagger_delay": {
                    "type": "number",
                    "description": "Seconds to wait before failing over to the next LLM provider",
                    "min": 0,
                    "max": 60,
                    "default": _default("jobs.llm.stagger_delay")
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
                    "default": _default("model_sync.interval")
                },
                "retry_delay": {
                    "type": "integer",
                    "description": "Seconds to wait after sync error",
                    "min": 1,
                    "max": 60,
                    "default": _default("model_sync.retry_delay")
                },
                "reconciliation_interval": {
                    "type": "integer",
                    "description": "Seconds between reconciliation checks",
                    "min": 60,
                    "max": 600,
                    "default": _default("model_sync.reconciliation_interval")
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
                    "default": _default("downloads.chunk_size")
                },
                "auto_remove_delay": {
                    "type": "integer",
                    "description": "Seconds before auto-removing completed downloads",
                    "min": 0,
                    "max": 300,
                    "default": _default("downloads.auto_remove_delay")
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
                    "default": _default("jobs_cleanup.max_age_hours")
                },
                "auto_cleanup": {
                    "type": "boolean",
                    "description": "Enable automatic cleanup of old jobs",
                    "default": _default("jobs_cleanup.auto_cleanup")
                },
                "cleanup_interval": {
                    "type": "integer",
                    "description": "Interval between auto-cleanup runs (seconds)",
                    "min": 60,
                    "max": 86400,
                    "default": _default("jobs_cleanup.cleanup_interval")
                }
            }
        },
        "image_processing": {
            "description": "Image thumbnail and BlurHash processing configuration",
            "fields": {
                "thumbnail_sizes": {
                    "type": "object",
                    "description": "Thumbnail size definitions {name: max_dimension}",
                    "default": _default("image_processing.thumbnail_sizes")
                },
                "thumbnail_quality": {
                    "type": "integer",
                    "description": "Encoder quality for generated thumbnails (1-100)",
                    "min": 1,
                    "max": 100,
                    "default": _default("image_processing.thumbnail_quality")
                },
                "output_date_hierarchy": {
                    "type": "boolean",
                    "description": "Write outputs into YYYY/MM/DD folders instead of one flat directory",
                    "default": _default("image_processing.output_date_hierarchy")
                },
                "embed_metadata_in_png": {
                    "type": "boolean",
                    "description": "Write generation parameters into the output file's metadata",
                    "default": _default("image_processing.embed_metadata_in_png")
                },
                "blurhash_components_x": {
                    "type": "integer",
                    "description": "BlurHash X components (higher = more detail)",
                    "min": 1,
                    "max": 9,
                    "default": _default("image_processing.blurhash_components_x")
                },
                "blurhash_components_y": {
                    "type": "integer",
                    "description": "BlurHash Y components (higher = more detail)",
                    "min": 1,
                    "max": 9,
                    "default": _default("image_processing.blurhash_components_y")
                },
                "blurhash_resize_max": {
                    "type": "integer",
                    "description": "Max dimension for BlurHash generation (smaller = faster)",
                    "min": 16,
                    "max": 1000,
                    "default": _default("image_processing.blurhash_resize_max")
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
                    "default": _default("modal.timeout")
                },
                "max_containers": {
                    "type": "integer",
                    "description": "Maximum number of containers",
                    "min": 1,
                    "max": 10,
                    "default": _default("modal.max_containers")
                },
                "scaledown_window": {
                    "type": "integer",
                    "description": "Scaledown window (seconds)",
                    "min": 0,
                    "max": 600,
                    "default": _default("modal.scaledown_window")
                }
            }
        },
        "api": {
            "description": "API server configuration",
            "fields": {
                "cors_origins": {
                    "type": "array",
                    "description": "Allowed CORS origins",
                    "default": _default("api.cors_origins"),
                    "env_var": app_config.ENV_VAR_OVERRIDES["api.cors_origins"]
                },
                "gzip_minimum_size": {
                    "type": "integer",
                    "description": "Minimum response size for gzip (bytes)",
                    "min": 0,
                    "max": 100000,
                    "default": _default("api.gzip_minimum_size"),
                    "env_var": app_config.ENV_VAR_OVERRIDES["api.gzip_minimum_size"]
                }
            }
        },
        # These two are writable and present in config.json, and `SettingsUpdate`
        # accepts them — but they were not documented here at all, so a UI built
        # from this endpoint could not discover or render the only two sections
        # that accept writes. The previous fix identified the drift and left the
        # documentation unchanged; `_annotate_writability` marks them writable,
        # but a section nobody can see is not discoverable.
        "generator": {
            "description": "Image generation defaults",
            "fields": {
                "default_checkpoint": {
                    "type": "string",
                    "description": (
                        "Server-side fallback checkpoint, used whenever a request does not "
                        "name one (agentic image generation, story illustrations, model "
                        "availability checks)"
                    ),
                    "default": _default("generator.default_checkpoint")
                }
            }
        },
        "ai": {
            "description": "LLM / assistant behaviour",
            "fields": {
                "maxContextTokens": {
                    "type": "integer",
                    "description": "Context window budget for chat replies",
                    "min": 1024,
                    "max": 32768,
                    "default": _default("ai.maxContextTokens")
                },
                "temperature": {
                    "type": "number",
                    "description": "Sampling temperature for LLM replies",
                    "min": 0,
                    "max": 2,
                    "default": _default("ai.temperature")
                },
                "ragEnabled": {
                    "type": "boolean",
                    "description": (
                        "Semantic retrieval of character memories and lorebook entries. "
                        "While off, retrieval returns nothing at all — it does not degrade "
                        "to a recency-based fallback."
                    ),
                    "default": _default("ai.ragEnabled")
                },
                "idleSimEnabled": {
                    "type": "boolean",
                    "description": "Let dormant chats receive proactive in-character messages",
                    "default": _default("ai.idleSimEnabled")
                },
                "idleSimIntervalSeconds": {
                    "type": "integer",
                    "description": "Seconds between idle-simulation updates",
                    "min": 30,
                    "max": 86400,
                    "default": _default("ai.idleSimIntervalSeconds")
                }
            }
        }
    }
    
    return {
        "status": "success",
        "schema": _annotate_writability(_annotate_restart_requirements(schema)),
        # Dotted config path -> env var name, for the overrides that are set in
        # this process's environment. Those fields are read-only in the UI: the
        # file value is ignored while the variable is present, so an editable
        # control would look like it worked and change nothing.
        "env_overrides": app_config.get_env_var_overrides(),
    }


# Sections PUT /api/settings will accept, derived from the request model itself
# so the two can never drift again. Computed lazily: `SettingsUpdate` is defined
# further down this module.
def _writable_sections() -> frozenset[str]:
    return frozenset(SettingsUpdate.model_fields)


def _annotate_writability(schema: dict[str, Any]) -> dict[str, Any]:
    """Tag every documented section with whether it can actually be written.

    The schema advertised nine sections while `SettingsUpdate` accepted five,
    and one of the nine (`websocket`) was not a key of config.json at all: it
    documented `poll_interval`/`reconnect_delay`/`heartbeat_interval` for a
    section that cannot be written and does not exist. The real knobs are the
    `COMFY_WS_BROADCAST_QUEUE_SIZE` env var and hardcoded Socket.IO ping
    settings, neither of which is a config leaf. The section is gone; a UI built
    from this endpoint no longer offers controls that fail with "Unknown
    configuration section" on save, and the sections that *are* writable
    (`worker`, `jobs`, `api`, `image_processing`, `generator`, `ai`) are all
    documented.

    Rather than maintaining a third list, the writable set is read off
    `SettingsUpdate.model_fields`.
    """
    writable = _writable_sections()
    return {
        section: {
            "writable": section in writable,
            "described": True,
            **body,
        }
        for section, body in schema.items()
    }


def _annotate_restart_requirements(schema: dict[str, Any]) -> dict[str, Any]:
    """Tag the fields that are bound once at app construction.

    `api.cors_origins` and `api.gzip_minimum_size` are read by
    `api/app_setup.configure_app` while the CORSMiddleware and GZipMiddleware
    are added, so a later config.json change is never picked up. The UI has to
    say so, or it presents a dead toggle as live.
    """
    for section, body in schema.items():
        fields = body.get("fields", {})
        for name, spec in fields.items():
            if f"{section}.{name}" in RESTART_REQUIRED_PATHS:
                spec["restart_required"] = True
    return schema


class SettingsUpdate(BaseModel):
    """Pydantic model for settings updates to ensure type safety.

    `image_processing` was missing while being the section holding the
    thumbnail and output settings; a UI can only expose what this model accepts,
    so it was the reason those controls could not be written at all.

    `extra="forbid"` because pydantic's default is to ignore unknown keys: a PUT
    naming a section this endpoint does not accept (as the retired `websocket`
    documentation invited) was dropped and answered `200
    {"message": "No settings to update"}`. A control that reports success while
    changing nothing is worse than one that fails.
    """
    model_config = ConfigDict(extra="forbid")

    worker: dict[str, Any] | None = None
    jobs: dict[str, Any] | None = None
    api: dict[str, Any] | None = None
    generator: dict[str, Any] | None = None
    ai: dict[str, Any] | None = None
    image_processing: dict[str, Any] | None = None


@router.put("")
async def update_settings(updates: SettingsUpdate) -> dict[str, Any]:
    """
    Update application settings.
    
    Args:
        updates: SettingsUpdate with configuration updates
        
    Returns:
        Updated configuration
    """
    try:
        filtered = {k: v for k, v in updates.model_dump(exclude_none=True).items() if v is not None}
        if not filtered:
            return {
                "status": "success",
                "message": "No settings to update",
                "settings": app_config.get_config()
            }
        
        updated_config = await asyncio.to_thread(app_config.update_config, filtered, True)
        return {
            "status": "success",
            "message": "Settings updated successfully",
            "settings": updated_config
        }
    except ValueError as e:
        raise ValidationError(str(e))
    except Exception as e:
        raise ComfyError(str(e))


# Sourced from config so the route's filter and `_validate_config`'s leaf
# allow-list for `system_prompts` cannot disagree about what a prompt block is.
SYSTEM_PROMPT_BLOCK_KEYS = app_config.SYSTEM_PROMPT_KEYS

class SystemPromptsRequest(BaseModel):
    """Update the configurable system-prompt blocks."""
    blocks: dict[str, str]

@router.get("/system-prompts")
async def get_system_prompts() -> dict[str, Any]:
    """Return all configurable system-prompt blocks (roleplay, narrator, suggest)."""
    return {"blocks": app_config.get_system_prompt_blocks()}

@router.put("/system-prompts")
async def update_system_prompts(request: SystemPromptsRequest) -> dict[str, Any]:
    """Persist edited system-prompt blocks to config.json."""
    try:
        current = app_config.get_system_prompt_blocks()
        updates = {}
        for key, value in request.blocks.items():
            if key not in SYSTEM_PROMPT_BLOCK_KEYS:
                continue
            stripped = (value or "").strip()
            if stripped:
                updates[key] = stripped
        merged = {**current, **updates}
        await asyncio.to_thread(app_config.update_config, {"system_prompts": merged}, True)
        return {"status": "success", "blocks": merged}
    except Exception as e:
        raise ComfyError(str(e))


@router.post("/reset")
async def reset_settings() -> dict[str, Any]:
    """
    Reset all settings to defaults.
    
    Returns:
        Default configuration
    """
    try:
        default_config = await asyncio.to_thread(app_config.reset_config)
        return {
            "status": "success",
            "message": "Settings reset to defaults",
            "settings": default_config
        }
    except Exception as e:
        raise ComfyError(str(e))


# ============================================================================
# BRANDING CONFIGURATION
# ============================================================================

BRANDING_CONFIG_PATH = os.path.join(os.environ.get("DATA_DIR", "/data"), "branding.json")

def get_branding_config() -> dict[str, Any]:
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


def save_branding_config(config: dict[str, Any]):
    """Save branding configuration to JSON file."""
    os.makedirs(os.path.dirname(BRANDING_CONFIG_PATH), exist_ok=True)
    with open(BRANDING_CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)


class BrandingRequest(BaseModel):
    appName: str
    logoUrl: str | None = "/logo.png"
    faviconUrl: str | None = "/favicon.ico"


@router.get("/branding")
async def get_branding():
    """Get current branding settings."""
    return await asyncio.to_thread(get_branding_config)


@router.post("/branding")
async def update_branding(request: BrandingRequest):
    """Update branding settings."""
    config = {
        "appName": request.appName,
        "logoUrl": request.logoUrl,
        "faviconUrl": request.faviconUrl
    }
    await asyncio.to_thread(save_branding_config, config)
    return {"status": "success", "branding": config}


# ============================================================================
# SESSION MANAGEMENT
# ============================================================================

FAVORITES_CONFIG_PATH = os.path.join(os.environ.get("DATA_DIR", "/data"), "favorites.json")

def get_favorites_list() -> list:
    os.makedirs(os.path.dirname(FAVORITES_CONFIG_PATH), exist_ok=True)
    if os.path.exists(FAVORITES_CONFIG_PATH):
        try:
            with open(FAVORITES_CONFIG_PATH, 'r') as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_favorites_list(favorites: list):
    os.makedirs(os.path.dirname(FAVORITES_CONFIG_PATH), exist_ok=True)
    with open(FAVORITES_CONFIG_PATH, 'w') as f:
        json.dump(favorites, f, indent=2)

class FavoritesRequest(BaseModel):
    favorites: list[str]

@router.get("/favorites")
async def get_favorites():
    return {"status": "success", "favorites": await asyncio.to_thread(get_favorites_list)}

@router.post("/favorites")
async def update_favorites(request: FavoritesRequest):
    await asyncio.to_thread(save_favorites_list, request.favorites)
    return {"status": "success", "favorites": request.favorites}

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
def get_presets(session: Session = Depends(get_session)):
    """Returns a list of curated models with installation status."""
    from api.deps import get_model_repo_v2
    repo = get_model_repo_v2(session)
    
    preset_filenames = [p['filename'] for p in PRESETS]
    installed_filenames = set(repo.get_existing_filenames(preset_filenames))
    
    presets = []
    for preset in PRESETS:
        presets.append({
            **preset,
            "installed": preset['filename'] in installed_filenames
        })
    
    return {"presets": presets}
