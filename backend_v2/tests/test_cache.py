
from unittest.mock import Mock

import pytest

from infrastructure.cache import (
    _lru_cache,
    _model_cache,
    _search_cache,
    _stats_cache,
    cache_model,
    cache_search,
    cache_stats,
    cached,
    get_cache_stats,
    invalidate_cache,
)


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear all caches before each test."""
    invalidate_cache("all")
    yield
    invalidate_cache("all")

def test_cached_sync_function():
    """Test caching for synchronous functions."""
    mock_func = Mock(return_value="result")

    @cached("stats")
    def sync_func(arg):
        return mock_func(arg)

    # First call - should execute function
    assert sync_func("test") == "result"
    assert mock_func.call_count == 1

    # Second call - should use cache
    assert sync_func("test") == "result"
    assert mock_func.call_count == 1

    # Different arg - should execute function
    assert sync_func("other") == "result"
    assert mock_func.call_count == 2

@pytest.mark.asyncio
async def test_cached_async_function():
    """Test caching for asynchronous functions."""
    mock_func = Mock(return_value="result")

    @cached("stats")
    async def async_func(arg):
        return mock_func(arg)

    # First call - should execute function
    assert await async_func("test") == "result"
    assert mock_func.call_count == 1

    # Second call - should use cache
    assert await async_func("test") == "result"
    assert mock_func.call_count == 1

    # Different arg - should execute function
    assert await async_func("other") == "result"
    assert mock_func.call_count == 2

def test_cached_args_kwargs():
    """Test caching with various argument combinations."""
    mock_func = Mock(side_effect=lambda *args, **kwargs: f"{args}-{kwargs}")

    @cached("stats")
    def complex_func(*args, **kwargs):
        return mock_func(*args, **kwargs)

    # Args only
    res1 = complex_func(1, 2)
    res2 = complex_func(1, 2)
    assert res1 == res2
    assert mock_func.call_count == 1

    # Kwargs only
    res3 = complex_func(a=1, b=2)
    res4 = complex_func(a=1, b=2)
    assert res3 == res4
    assert mock_func.call_count == 2

    # Mixed
    res5 = complex_func(1, b=2)
    res6 = complex_func(1, b=2)
    assert res5 == res6
    assert mock_func.call_count == 3

    # Empty
    res7 = complex_func()
    res8 = complex_func()
    assert res7 == res8
    assert mock_func.call_count == 4

def test_cache_selection():
    """Test that the correct cache is used based on cache_name."""

    @cached("model")
    def model_func():
        return "model"

    @cached("search")
    def search_func():
        return "search"

    @cached("lru")
    def lru_func():
        return "lru"

    # Execute functions to populate caches
    model_func()
    search_func()
    lru_func()

    # Verify entries exist in correct caches
    assert len(_model_cache) == 1
    assert len(_search_cache) == 1
    assert len(_lru_cache) == 1
    assert len(_stats_cache) == 0

def test_invalidate_cache():
    """Test cache invalidation functionality."""

    @cached("stats")
    def cached_func(x):
        return x * 2

    # Populate cache
    cached_func(1)
    cached_func(2)
    assert len(_stats_cache) == 2

    # Invalidate specific key is tricky because key generation is internal.
    # We can test invalidating the whole cache or "all".

    # Invalidate specific cache
    invalidate_cache("stats")
    assert len(_stats_cache) == 0

    # Populate again
    cached_func(1)
    cached_func(2)
    assert len(_stats_cache) == 2

    # Invalidate all
    invalidate_cache("all")
    assert len(_stats_cache) == 0

def test_invalidate_specific_key():
    """Test invalidating a specific key if we can reconstruct it."""
    # We need to know how _make_key works or import it.
    # Since it's internal, we might rely on implementation details or skip specific key invalidation test if too fragile.
    # However, let's try to verify the logic from invalidation perspective.

    from infrastructure.cache import _make_key

    @cached("stats")
    def func(x): return x

    func(1)
    key = _make_key("func", (1,), {})

    assert key in _stats_cache

    invalidate_cache("stats", key)
    assert key not in _stats_cache

def test_get_cache_stats():
    """Test retrieval of cache statistics."""
    # Ensure empty state
    invalidate_cache("all")

    stats = get_cache_stats()
    assert stats["stats"]["size"] == 0
    assert stats["model"]["size"] == 0

    @cached("stats")
    def func(x): return x

    func(1)

    stats = get_cache_stats()
    assert stats["stats"]["size"] == 1
    assert stats["stats"]["maxsize"] == _stats_cache.maxsize
    assert stats["stats"]["ttl"] == _stats_cache.ttl

def test_convenience_decorators():
    """Test the convenience decorators (cache_stats, etc.)."""

    mock_stats = Mock(return_value="stats")
    @cache_stats
    def stats_func():
        return mock_stats()

    mock_model = Mock(return_value="model")
    @cache_model
    def model_func():
        return mock_model()

    mock_search = Mock(return_value="search")
    @cache_search
    def search_func():
        return mock_search()

    # Execute
    stats_func()
    model_func()
    search_func()

    # Verify call counts (sanity check)
    assert mock_stats.call_count == 1
    assert mock_model.call_count == 1
    assert mock_search.call_count == 1

    # Verify correct caches used
    assert len(_stats_cache) == 1
    assert len(_model_cache) == 1
    assert len(_search_cache) == 1
