"""
Model Settings Parser
Extracts recommended generation settings from CivitAI model metadata.

This module parses model descriptions to extract recommended settings like
steps, CFG, sampler, etc. and provides base model defaults as fallbacks.
"""
import re
from typing import Any

# Base model default settings - curated from community best practices
BASE_MODEL_DEFAULTS = {
    "SDXL": {
        "steps": 30,
        "cfg": 7.0,
        "sampler": "dpmpp_2m",
        "scheduler": "karras",
        "width": 1024,
        "height": 1024,
        "clip_skip": 2
    },
    "SD 1.5": {
        "steps": 25,
        "cfg": 7.0,
        "sampler": "euler_ancestral",
        "scheduler": "normal",
        "width": 512,
        "height": 768,
        "clip_skip": 1
    },
    "SD 1.4": {
        "steps": 25,
        "cfg": 7.0,
        "sampler": "euler_ancestral",
        "scheduler": "normal",
        "width": 512,
        "height": 512,
        "clip_skip": 1
    },
    "Pony": {
        "steps": 25,
        "cfg": 6.0,
        "sampler": "dpmpp_2m",
        "scheduler": "karras",
        "width": 1024,
        "height": 1024,
        "clip_skip": 2
    },
    "Illustrious": {
        "steps": 25,
        "cfg": 6.0,
        "sampler": "euler_ancestral",
        "scheduler": "normal",
        "width": 1024,
        "height": 1024,
        "clip_skip": 2
    },
    "FLUX": {
        "steps": 20,
        "cfg": 1.0,
        "sampler": "euler",
        "scheduler": "normal",
        "width": 1024,
        "height": 1024,
        "clip_skip": 1
    },
    "SD 3": {
        "steps": 28,
        "cfg": 4.5,
        "sampler": "dpmpp_2m",
        "scheduler": "sgm_uniform",
        "width": 1024,
        "height": 1024,
        "clip_skip": 1
    }
}

# Map common sampler names to ComfyUI sampler names
SAMPLER_MAP = {
    'euler a': 'euler_ancestral',
    'euler_a': 'euler_ancestral',
    'euler ancestral': 'euler_ancestral',
    'euler': 'euler',
    'dpm++ 2m': 'dpmpp_2m',
    'dpmpp_2m': 'dpmpp_2m',
    'dpm++ 2m karras': 'dpmpp_2m',
    'dpm++ sde': 'dpmpp_sde',
    'dpmpp_sde': 'dpmpp_sde',
    'dpm++ 2s a': 'dpmpp_2s_ancestral',
    'dpm++ 3m': 'dpmpp_3m_sde',
    'ddim': 'ddim',
    'heun': 'heun',
    'lms': 'lms',
    'dpm2': 'dpm_2',
    'dpm2 a': 'dpm_2_ancestral',
    'uni_pc': 'uni_pc',
}


def parse_recommended_settings(description: str) -> dict[str, Any]:
    """
    Parse recommended settings from CivitAI HTML description.
    
    Common patterns found in model descriptions:
    - "Steps: 15-30" or "Steps: 25"
    - "CFG scale: 5-7" or "CFG: 7"
    - "Sampler: Euler a" or "Sampler: DPM++ 2M"
    - "Clip skip: 2"
    
    Args:
        description: HTML description from CivitAI model
        
    Returns:
        Dict with extracted settings, empty if none found
    """
    if not description:
        return {}
    
    settings = {}
    
    # Clean HTML tags for easier parsing
    clean_text = re.sub(r'<[^>]+>', ' ', description)
    clean_text = clean_text.replace('&nbsp;', ' ')
    clean_text = clean_text.replace('\\n', '\n')
    
    # Steps pattern: "Steps: 25" or "Steps: 15-30"
    steps_match = re.search(
        r'Steps?[:\s]+(\d+)(?:\s*[-–]\s*(\d+))?',
        clean_text,
        re.IGNORECASE
    )
    if steps_match:
        # If range, take the higher value for quality
        if steps_match.group(2):
            settings['steps'] = int(steps_match.group(2))
        else:
            settings['steps'] = int(steps_match.group(1))
    
    # CFG pattern: "CFG scale: 7" or "CFG: 5-7"
    cfg_match = re.search(
        r'CFG[\s]*(?:scale)?[:\s]+([\d.]+)(?:\s*[-–]\s*([\d.]+))?',
        clean_text,
        re.IGNORECASE
    )
    if cfg_match:
        if cfg_match.group(2):
            settings['cfg'] = float(cfg_match.group(2))
        else:
            settings['cfg'] = float(cfg_match.group(1))
    
    # Sampler pattern: "Sampler: Euler a"
    sampler_match = re.search(
        r'Sampler[:\s]+([\w\+\s]+?)(?:\.|,|<|\n|$)',
        clean_text,
        re.IGNORECASE
    )
    if sampler_match:
        sampler_raw = sampler_match.group(1).strip().lower()
        for key, value in SAMPLER_MAP.items():
            if key in sampler_raw:
                settings['sampler'] = value
                break
    
    # Clip skip pattern: "Clip skip: 2"
    clip_match = re.search(
        r'Clip[\s]*skip[:\s]+(\d+)',
        clean_text,
        re.IGNORECASE
    )
    if clip_match:
        settings['clip_skip'] = int(clip_match.group(1))
    
    # Resolution pattern: "1024x1024" or "size: 1024"
    size_match = re.search(
        r'(?:size|resolution)[:\s]*(\d{3,4})\s*[x×]\s*(\d{3,4})',
        clean_text,
        re.IGNORECASE
    )
    if size_match:
        settings['width'] = int(size_match.group(1))
        settings['height'] = int(size_match.group(2))
    
    return settings


def detect_base_model(metadata: dict[str, Any]) -> str | None:
    """
    Detect the base model from metadata.
    
    Args:
        metadata: Model metadata from CivitAI or database
        
    Returns:
        Base model name or None if not detected
    """
    if not isinstance(metadata, dict):
        return None
    
    # Direct baseModel field (most reliable)
    base_model = metadata.get('baseModel')
    if base_model:
        return base_model
    
    # Nested in modelVersions (CivitAI API response)
    model_versions = metadata.get('modelVersions', [])
    if model_versions and isinstance(model_versions[0], dict):
        base_model = model_versions[0].get('baseModel')
        if base_model:
            return base_model
    
    # Check model name for hints
    name = metadata.get('name', '').lower()
    if name:
        if 'flux' in name:
            return 'FLUX'
        elif 'sd3' in name or 'sd 3' in name:
            return 'SD 3'
        elif 'illustrious' in name or 'ill-' in name or 'illu' in name:
            return 'Illustrious'
        elif 'pony' in name:
            return 'Pony'
        elif 'sdxl' in name or 'xl' in name:
            return 'SDXL'
        elif 'sd1.5' in name or 'sd 1.5' in name or 'sd15' in name:
            return 'SD 1.5'
    
    return None


def get_base_model_defaults(base_model: str) -> dict[str, Any]:
    """
    Get default settings for a base model.
    
    Args:
        base_model: Base model name (e.g., "SDXL", "Illustrious")
        
    Returns:
        Dict with default settings, empty if base model not recognized
    """
    if not base_model:
        return {}
    
    base_model_lower = base_model.lower()
    
    for key, defaults in BASE_MODEL_DEFAULTS.items():
        if key.lower() in base_model_lower or base_model_lower in key.lower():
            return defaults.copy()
    
    return {}


def get_model_settings(metadata: dict[str, Any]) -> dict[str, Any]:
    """
    Get recommended settings for a model based on its metadata.
    
    Priority:
    1. Parsed recommended settings from description
    2. Base model defaults (SDXL, SD1.5, Pony, Illustrious, etc.)
    3. Empty dict (caller uses their own defaults)
    
    Args:
        metadata: Model metadata from database or API
        
    Returns:
        Dict with recommended settings and '_source' field indicating origin
    """
    settings = {}
    source = None
    
    # Detect base model
    base_model = detect_base_model(metadata)
    
    # Apply base model defaults first
    if base_model:
        defaults = get_base_model_defaults(base_model)
        if defaults:
            settings.update(defaults)
            source = f'baseModel:{base_model}'
    
    # Try to parse description for specific recommendations (overrides defaults)
    description = metadata.get('description', '') if isinstance(metadata, dict) else ''
    if description:
        parsed = parse_recommended_settings(description)
        if parsed:
            settings.update(parsed)
            source = 'parsed_description'
    
    if source:
        settings['_source'] = source
        settings['_baseModel'] = base_model
    
    return settings


def get_settings_summary(settings: dict[str, Any]) -> str:
    """
    Get a human-readable summary of the settings.
    
    Args:
        settings: Settings dict from get_model_settings
        
    Returns:
        Summary string like "Illustrious: 25 steps, CFG 6.0, euler_ancestral"
    """
    if not settings:
        return "No settings"
    
    parts = []
    base_model = settings.get('_baseModel', 'Unknown')
    
    if 'steps' in settings:
        parts.append(f"{settings['steps']} steps")
    if 'cfg' in settings:
        parts.append(f"CFG {settings['cfg']}")
    if 'sampler' in settings:
        parts.append(settings['sampler'])
    if 'width' in settings and 'height' in settings:
        parts.append(f"{settings['width']}x{settings['height']}")
    
    return f"{base_model}: {', '.join(parts)}" if parts else base_model
