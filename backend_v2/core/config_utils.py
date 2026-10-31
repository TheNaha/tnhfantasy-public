"""Centralized configuration parsing utilities."""


def parse_positive_float(raw_value: str | None, default: float) -> float:
    """Parse a string to a positive float, returning default if invalid or non-positive."""
    try:
        parsed = float(raw_value) if raw_value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return parsed if parsed > 0 else default


def parse_positive_int(raw_value: str | None, default: int) -> int:
    """Parse a string to a positive int, returning default if invalid or non-positive."""
    try:
        parsed = int(raw_value) if raw_value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return parsed if parsed > 0 else default
