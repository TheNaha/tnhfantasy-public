# Request deduplication using in-flight tracking + short TTL cache
# Prevents duplicate work when multiple SSE clients or rapid refreshes hit same endpoints

from cachetools import TTLCache
import asyncio
from typing import Callable, Any, TypeVar, Coroutine
import hashlib

T = TypeVar('T')

# Track in-flight requests to deduplicate concurrent identical requests
_in_flight: dict[str, asyncio.Task] = {}

# Short-lived cache for completed requests (1 second TTL)
_result_cache = TTLCache(maxsize=100, ttl=1.0)


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
    # Check result cache first
    if key in _result_cache:
        return _result_cache[key]
    
    # Check if same request is already in-flight
    if key in _in_flight:
        return await _in_flight[key]
    
    # Create new task for this request
    task = asyncio.create_task(coro_factory())
    _in_flight[key] = task
    
    try:
        result = await task
        _result_cache[key] = result
        return result
    finally:
        _in_flight.pop(key, None)


def make_key(*args) -> str:
    """
    Create a cache key from arguments.
    
    Args:
        *args: Any hashable arguments
        
    Returns:
        16-character hex digest
    """
    return hashlib.md5(str(args).encode()).hexdigest()[:16]


def clear_dedup_cache():
    """Clear the deduplication cache. Useful for testing."""
    _result_cache.clear()
    # Note: in-flight tasks will complete naturally


def get_dedup_stats() -> dict:
    """Get statistics about the deduplication cache."""
    return {
        "cache_size": len(_result_cache),
        "cache_maxsize": _result_cache.maxsize,
        "cache_ttl": _result_cache.ttl,
        "in_flight_count": len(_in_flight),
    }
