import os
from typing import Optional
from infrastructure.logging import get_logger

logger = get_logger("config_helpers")

def resolve_env_bool(env_name: str, default_value: bool) -> bool:
    """Resolve boolean config from env var."""
    raw_value = os.getenv(env_name)
    if raw_value is None:
        return default_value

    normalized = raw_value.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
        
    logger.warning(
        f"{env_name}_invalid",
        raw_value=raw_value,
        default_value=default_value,
    )
    return default_value


def resolve_env_int(env_name: str, default_value: int, min_value: Optional[int] = None) -> int:
    """Resolve integer config from env var with optional min limit."""
    raw_value = os.getenv(env_name)
    if raw_value is None:
        return default_value

    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        logger.warning(
            f"{env_name}_invalid",
            raw_value=raw_value,
            default_value=default_value,
        )
        return default_value

    if min_value is not None and parsed < min_value:
        logger.warning(
            f"{env_name}_below_min",
            raw_value=raw_value,
            min_value=min_value,
            default_value=default_value,
        )
        return default_value

    return parsed


def resolve_env_float(env_name: str, default_value: float, min_value: Optional[float] = None) -> float:
    """Resolve float config from env var with optional min limit."""
    raw_value = os.getenv(env_name)
    if raw_value is None:
        return default_value

    try:
        parsed = float(raw_value)
    except (TypeError, ValueError):
        logger.warning(
            f"{env_name}_invalid",
            raw_value=raw_value,
            default_value=default_value,
        )
        return default_value

    if min_value is not None and parsed < min_value:
        logger.warning(
            f"{env_name}_below_min",
            raw_value=raw_value,
            min_value=min_value,
            default_value=default_value,
        )
        return default_value

    return parsed
