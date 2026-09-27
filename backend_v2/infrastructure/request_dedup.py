# Request deduplication using in-flight tracking + short TTL cache
# Prevents duplicate work when multiple SSE clients or rapid refreshes hit same endpoints

import asyncio
import os
import threading
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from cachetools import TTLCache

from infrastructure.logging import get_logger

logger = get_logger("request_dedup")

T = TypeVar('T')

# Track in-flight requests to deduplicate concurrent identical requests
_in_flight: dict[str, asyncio.Task] = {}
# NOTE: threading.Lock is intentional here. All protected operations are synchronous
# dict/cache mutations with no awaits inside the lock blocks. asyncio.Lock cannot be
# used because clear_dedup_cache/get_dedup_stats/is_in_flight are called from
# synchronous contexts (tests, health checks).
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
            # Only de-register the task when it is actually FINISHED.
            #
            # The `finally` runs on the CREATOR's cancellation too, not only on
            # completion — `asyncio.shield` protects `task` from that
            # cancellation, but this block still executes. So a caller who gave
            # up removed a task from `_in_flight` that was still running: the
            # next identical request found no entry, started a SECOND concurrent
            # copy of the work, and the dedup silently stopped deduplicating for
            # that key. Silent, and only visible under concurrency.
            #
            # So: if the task is still running, leave the entry alone and let a
            # `done_callback` remove it when it really finishes. `clear_dedup_cache`
            # remains the escape hatch.
            if task.done():
                with _in_flight_lock:
                    if _in_flight.get(key) is task:
                        _in_flight.pop(key, None)
            else:
                task.add_done_callback(_retire_when_done(key, task))


def _retire_when_done(key: str, task):
    """Remove `key` from `_in_flight` once `task` really finishes.

    Identity-checked on the way out, so a later task registered under the same
    key by a fresh request is not evicted by this one's completion.
    """

    def _retire(_task):
        with _in_flight_lock:
            if _in_flight.get(key) is task:
                _in_flight.pop(key, None)

    return _retire


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
