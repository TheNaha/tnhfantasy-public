# Cache utilities using cachetools for in-memory TTL caching
# Provides lightweight caching for frequently accessed data like statistics and model metadata

from typing import Any, Callable, Optional
from functools import wraps
from cachetools import TTLCache, LRUCache
import asyncio

from infrastructure.logging import cache_logger
from infrastructure.metrics import metrics

logger = cache_logger()

# ============================================================================
# CACHE INSTANCES
# ============================================================================

# Statistics cache - 5 minute TTL, max 10 entries
_stats_cache = TTLCache(maxsize=10, ttl=300)

# Model metadata cache - 10 minute TTL, max 100 entries
_model_cache = TTLCache(maxsize=100, ttl=600)

# Search results cache - 2 minute TTL, max 50 entries
_search_cache = TTLCache(maxsize=50, ttl=120)

# Generic LRU cache for computed values (no TTL)
_lru_cache = LRUCache(maxsize=200)


# ============================================================================
# CACHE DECORATOR
# ============================================================================

def cached(cache_name: str = "stats", ttl: Optional[int] = None):
    """
    Decorator for caching function results.
    
    Args:
        cache_name: Which cache to use ('stats', 'model', 'search', 'lru')
        ttl: Optional TTL override (only used when creating a new cache instance)
        
    Usage:
        @cached("stats")
        async def get_statistics():
            ...
    """
    cache_map = {
        "stats": _stats_cache,
        "model": _model_cache,
        "search": _search_cache,
        "lru": _lru_cache,
    }
    
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Create cache key from function name and arguments
            key = _make_key(func.__name__, args, kwargs)
            cache = cache_map.get(cache_name, _stats_cache)
            
            # Check cache
            if key in cache:
                logger.debug("cache_hit", cache_name=cache_name, func=func.__name__)
                metrics.track_cache_hit(cache_name)
                return cache[key]
            
            logger.debug("cache_miss", cache_name=cache_name, func=func.__name__)
            metrics.track_cache_miss(cache_name)
            
            # Execute function
            result = await func(*args, **kwargs)
            
            # Store in cache
            cache[key] = result
            metrics.set_cache_size(cache_name, len(cache))
            return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            key = _make_key(func.__name__, args, kwargs)
            cache = cache_map.get(cache_name, _stats_cache)
            
            if key in cache:
                logger.debug("cache_hit", cache_name=cache_name, func=func.__name__)
                metrics.track_cache_hit(cache_name)
                return cache[key]
            
            logger.debug("cache_miss", cache_name=cache_name, func=func.__name__)
            metrics.track_cache_miss(cache_name)
            
            result = func(*args, **kwargs)
            cache[key] = result
            metrics.set_cache_size(cache_name, len(cache))
            return result
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def _make_key(func_name: str, args: tuple, kwargs: dict) -> str:
    """Create a cache key from function name and arguments."""
    # Convert args and kwargs to a string representation
    args_str = str(args) if args else ""
    kwargs_str = str(sorted(kwargs.items())) if kwargs else ""
    return f"{func_name}:{args_str}:{kwargs_str}"


# ============================================================================
# CACHE MANAGEMENT
# ============================================================================

def invalidate_cache(cache_name: str = "stats", key: Optional[str] = None):
    """
    Invalidate cache entries.
    
    Args:
        cache_name: Which cache to invalidate ('stats', 'model', 'search', 'lru', 'all')
        key: Optional specific key to invalidate (if None, clears entire cache)
    """
    cache_map = {
        "stats": _stats_cache,
        "model": _model_cache,
        "search": _search_cache,
        "lru": _lru_cache,
    }
    
    if cache_name == "all":
        for cn, cache in cache_map.items():
            cache.clear()
            metrics.set_cache_size(cn, 0)
        logger.info("cache_invalidated", cache_name="all")
        return
    
    cache = cache_map.get(cache_name)
    if cache is None:
        logger.warning("cache_invalidate_unknown", cache_name=cache_name)
        return
    
    if key is None:
        cache.clear()
        metrics.set_cache_size(cache_name, 0)
        logger.info("cache_invalidated", cache_name=cache_name)
    elif key in cache:
        del cache[key]
        metrics.set_cache_size(cache_name, len(cache))
        logger.debug("cache_key_invalidated", cache_name=cache_name, key=key)


def get_cache_stats() -> dict:
    """Get statistics about cache usage."""
    return {
        "stats": {
            "size": len(_stats_cache),
            "maxsize": _stats_cache.maxsize,
            "ttl": _stats_cache.ttl,
        },
        "model": {
            "size": len(_model_cache),
            "maxsize": _model_cache.maxsize,
            "ttl": _model_cache.ttl,
        },
        "search": {
            "size": len(_search_cache),
            "maxsize": _search_cache.maxsize,
            "ttl": _search_cache.ttl,
        },
        "lru": {
            "size": len(_lru_cache),
            "maxsize": _lru_cache.maxsize,
        }
    }


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def cache_stats(func: Callable) -> Callable:
    """Shorthand decorator for statistics caching (5 min TTL)."""
    return cached("stats")(func)


def cache_model(func: Callable) -> Callable:
    """Shorthand decorator for model metadata caching (10 min TTL)."""
    return cached("model")(func)


def cache_search(func: Callable) -> Callable:
    """Shorthand decorator for search results caching (2 min TTL)."""
    return cached("search")(func)
