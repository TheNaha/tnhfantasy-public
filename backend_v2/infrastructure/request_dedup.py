# Request deduplication using in-flight tracking + short TTL cache
# Prevents duplicate work when multiple SSE clients or rapid refreshes hit same endpoints

from cachetools import TTLCache
import asyncio
import threading
import os
from typing import Callable, Any, TypeVar, Coroutine

from infrastructure.logging import get_logger

logger = get_logger("request_dedup")

T = TypeVar('T')

# Track in-flight requests to deduplicate concurrent identical requests
_in_flight: dict[str, asyncio.Task] = {}
_in_flight_lock = threading.Lock()


def _resolve_result_cache_ttl_seconds() -> float:
    default_ttl_seconds = 3.0
    raw_value = os.getenv("COMFY_REQUEST_DEDUP_TTL_SECONDS")
    if raw_value is None:
        return default_ttl_seconds

    try:
        parsed = float(raw_value)
    except (TypeError, ValueError):
        logger.warning(
            "request_dedup_ttl_invalid",
            raw_value=raw_value,
            fallback_ttl=default_ttl_seconds,
        )
        return default_ttl_seconds

    if parsed <= 0:
        logger.warning(
            "request_dedup_ttl_non_positive",
            raw_value=raw_value,
            fallback_ttl=default_ttl_seconds,
        )
        return default_ttl_seconds

    return parsed


# Short-lived cache for completed requests (default 3s TTL)
_result_cache = TTLCache(maxsize=100, ttl=_resolve_result_cache_ttl_seconds())


async def deduplicated(key: str, coro_factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """
    Deduplicate concurrent identical requests.
    
    If the same key is requested while a previous request is still in-flight,
    wait for that request instead of starting a new one.
    
    Args:
        key: Unique identifier for this request
        coro_factory: Function that returns the coroutine to execute
        
    Returns:
        The result of the coroutine
        
    Usage:
        result = await deduplicated(
            make_key("list_jobs", limit, offset),
            lambda: service.list_jobs(limit, offset)
        )
    """
    with _in_flight_lock:
        # Check result cache first
        if key in _result_cache:
            logger.debug("dedup_cache_hit", key=key)
            return _result_cache[key]

        # Check if same request is already in-flight
        task = _in_flight.get(key)
        created_task = False
        if task is None:
            task = asyncio.create_task(coro_factory(), name=f"dedup:{key}")
            _in_flight[key] = task
            created_task = True
        else:
            logger.debug("dedup_in_flight", key=key)

    try:
        # Shield shared work from caller cancellation so one waiter cannot
        # cancel the underlying request for every other waiter.
        result = await asyncio.shield(task)
        if created_task:
            with _in_flight_lock:
                _result_cache[key] = result
        return result
    finally:
        if created_task:
            with _in_flight_lock:
                if _in_flight.get(key) is task:
                    _in_flight.pop(key, None)


def make_key(*args) -> str:
    """
    Create a cache key from arguments.
    
    Args:
        *args: Any hashable arguments
        
    Returns:
        String joined by colons
    """
    return ":".join(str(arg) for arg in args if arg)


def clear_dedup_cache():
    """Clear the deduplication cache. Useful for testing."""
    with _in_flight_lock:
        _result_cache.clear()
    done_keys = [key for key, task in _in_flight.items() if task.done()]
    for key in done_keys:
        _in_flight.pop(key, None)


def get_dedup_stats() -> dict:
    """Get statistics about the deduplication cache."""
    with _in_flight_lock:
        return {
        "cache_size": len(_result_cache),
        "cache_maxsize": _result_cache.maxsize,
        "cache_ttl": _result_cache.ttl,
        "in_flight_count": len(_in_flight),
    }


def is_in_flight(key: str) -> bool:
    """Return True when a dedup key currently has a running task."""
    with _in_flight_lock:
        task = _in_flight.get(key)
    return task is not None and not task.done()
