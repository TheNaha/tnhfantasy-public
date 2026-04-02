import pytest
import asyncio
from infrastructure.request_dedup import deduplicated, make_key, clear_dedup_cache, get_dedup_stats

@pytest.fixture(autouse=True)
async def cleanup_dedup_cache():
    """Clear the deduplication cache before and after each test."""
    clear_dedup_cache()
    yield
    clear_dedup_cache()

def test_make_key_consistency():
    """Test that make_key produces consistent keys for the same arguments."""
    key1 = make_key("test", 1, {"a": 1})
    key2 = make_key("test", 1, {"a": 1})
    assert key1 == key2

def test_make_key_distinctness():
    """Test that make_key produces different keys for different arguments."""
    key1 = make_key("test", 1)
    key2 = make_key("test", 2)
    assert key1 != key2

def test_make_key_types():
    """Test that make_key handles various types correctly."""
    key = make_key(1, "string", [1, 2], {"key": "value"})
    assert isinstance(key, str)
    assert key == "1:string:[1, 2]:{'key': 'value'}"

def test_make_key_empty_args():
    """Test that make_key handles empty arguments."""
    key = make_key()
    assert key == ""

def test_make_key_falsy_values():
    """Test that make_key filters out falsy values like None, empty string, 0."""
    key = make_key("a", None, "", 0, False, "b")
    assert key == "a:b"

def test_make_key_ordering():
    """Test that argument order matters."""
    key1 = make_key("a", "b")
    key2 = make_key("b", "a")
    assert key1 == "a:b"
    assert key2 == "b:a"
    assert key1 != key2

def test_make_key_similar_types():
    """Test that different types with similar string representations generate same keys."""
    # Since str(1) == "1", they will produce the same key if used directly.
    # The current implementation joins string representations, so 1 and "1" produce the same result.
    key1 = make_key(1)
    key2 = make_key("1")
    assert key1 == key2
    assert key1 == "1"

@pytest.mark.asyncio
async def test_deduplicated_basic():
    """Test basic execution of a deduplicated coroutine."""
    async def simple_coro():
        return "result"

    result = await deduplicated("key1", simple_coro)
    assert result == "result"

    # Verify it's cached
    stats = get_dedup_stats()
    assert stats["cache_size"] == 1
    assert stats["in_flight_count"] == 0

@pytest.mark.asyncio
async def test_deduplicated_concurrency():
    """Test that concurrent requests with the same key are deduplicated."""
    execution_count = 0

    async def slow_coro():
        nonlocal execution_count
        execution_count += 1
        await asyncio.sleep(0.1)
        return "slow_result"

    # Create tasks for concurrent execution
    t1 = asyncio.create_task(deduplicated("key_concurrent", slow_coro))
    t2 = asyncio.create_task(deduplicated("key_concurrent", slow_coro))
    t3 = asyncio.create_task(deduplicated("key_concurrent", slow_coro))

    # Wait for all to complete
    results = await asyncio.gather(t1, t2, t3)

    # All should return the same result
    assert all(r == "slow_result" for r in results)

    # The coroutine should have executed only once
    assert execution_count == 1

    # Should be cached now
    stats = get_dedup_stats()
    assert stats["cache_size"] == 1

@pytest.mark.asyncio
async def test_deduplicated_caching():
    """Test that subsequent requests return the cached result."""
    execution_count = 0

    async def counting_coro():
        nonlocal execution_count
        execution_count += 1
        return f"count_{execution_count}"

    # First call
    result1 = await deduplicated("key_cache", counting_coro)
    assert result1 == "count_1"
    assert execution_count == 1

    # Second call (should use cache)
    result2 = await deduplicated("key_cache", counting_coro)
    assert result2 == "count_1"  # Returns cached result
    assert execution_count == 1  # No new execution

@pytest.mark.asyncio
async def test_deduplicated_isolation():
    """Test that requests with different keys are not deduplicated against each other."""
    execution_count = 0

    async def specific_coro(val):
        nonlocal execution_count
        execution_count += 1
        await asyncio.sleep(0.05)
        return val

    # Launch two tasks with different keys
    t1 = asyncio.create_task(deduplicated("key_A", lambda: specific_coro("A")))
    t2 = asyncio.create_task(deduplicated("key_B", lambda: specific_coro("B")))

    results = await asyncio.gather(t1, t2)

    assert results == ["A", "B"]
    assert execution_count == 2

    stats = get_dedup_stats()
    assert stats["cache_size"] == 2

@pytest.mark.asyncio
async def test_deduplicated_exception_handling():
    """Test that exceptions are propagated and in-flight status is cleared."""
    async def failing_coro():
        raise ValueError("Something went wrong")

    # Verify exception is raised
    with pytest.raises(ValueError, match="Something went wrong"):
        await deduplicated("key_fail", failing_coro)

    # Verify cleanup
    stats = get_dedup_stats()
    assert stats["in_flight_count"] == 0
    # Should not be in cache (or depends on implementation, likely not)
    # The implementation doesn't cache exceptions explicitly, just successful results
    # checking the code: _result_cache[key] = result is inside try block, so exception skips it.
    assert stats["cache_size"] == 0

@pytest.mark.asyncio
async def test_deduplicated_cache_expiration():
    """Test that the cache expires after the configured TTL."""
    execution_count = 0

    async def counting_coro():
        nonlocal execution_count
        execution_count += 1
        return f"count_{execution_count}"

    # First call
    result1 = await deduplicated("key_ttl", counting_coro)
    assert result1 == "count_1"
    assert execution_count == 1

    ttl_seconds = get_dedup_stats()["cache_ttl"]

    # Wait for TTL to expire with a small buffer.
    await asyncio.sleep(ttl_seconds + 0.1)

    # Second call (should execute again)
    result2 = await deduplicated("key_ttl", counting_coro)
    assert result2 == "count_2"
    assert execution_count == 2

@pytest.mark.asyncio
async def test_deduplicated_cancellation_cleanup():
    """Test that cancellation cleans up the in-flight tracking."""
    async def slow_coro():
        await asyncio.sleep(1.0)
        return "slow_result"

    # Start a request
    task = asyncio.create_task(deduplicated("key_cancel", slow_coro))

    # Let it start
    await asyncio.sleep(0.1)

    # Verify it is in-flight
    stats = get_dedup_stats()
    assert stats["in_flight_count"] == 1

    # Cancel the request
    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass

    # Verify it is removed from in-flight
    stats = get_dedup_stats()
    assert stats["in_flight_count"] == 0

@pytest.mark.asyncio
async def test_deduplicated_factory_error():
    """Test behavior when coro_factory raises an exception."""
    def failing_factory():
        raise ValueError("Factory failed")

    with pytest.raises(ValueError, match="Factory failed"):
        await deduplicated("key_factory_fail", failing_factory)

    # Verify cleanup
    stats = get_dedup_stats()
    assert stats["in_flight_count"] == 0

@pytest.mark.asyncio
async def test_deduplicated_concurrent_failure():
    """Test that concurrent requests waiting for a failing request also fail."""
    async def failing_coro():
        await asyncio.sleep(0.1)
        raise ValueError("Concurrent failure")

    # Start primary request
    t1 = asyncio.create_task(deduplicated("key_concurrent_fail", failing_coro))

    # Start secondary request (should wait for t1)
    t2 = asyncio.create_task(deduplicated("key_concurrent_fail", failing_coro))

    # Both should fail with same error
    with pytest.raises(ValueError, match="Concurrent failure"):
        await t1

    with pytest.raises(ValueError, match="Concurrent failure"):
        await t2

    # Verify cleanup
    stats = get_dedup_stats()
    assert stats["in_flight_count"] == 0

@pytest.mark.asyncio
async def test_waiter_cancellation_does_not_cancel_shared_task():
    execution_count = 0
    ready = asyncio.Event()

    async def slow_coro():
        nonlocal execution_count
        execution_count += 1
        ready.set()
        await asyncio.sleep(0.05)
        return "shared_result"

    primary = asyncio.create_task(deduplicated("key_waiter_cancel", slow_coro))
    await ready.wait()
    waiter = asyncio.create_task(deduplicated("key_waiter_cancel", slow_coro))
    await asyncio.sleep(0)

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    result = await primary

    assert result == "shared_result"
    assert execution_count == 1

    stats = get_dedup_stats()
    assert stats["cache_size"] == 1
    assert stats["in_flight_count"] == 0

def test_get_dedup_stats_structure():
    """Test the structure and default values of get_dedup_stats."""
    clear_dedup_cache()
    stats = get_dedup_stats()

    assert isinstance(stats, dict)
    assert "cache_size" in stats
    assert "cache_maxsize" in stats
    assert "cache_ttl" in stats
    assert "in_flight_count" in stats

    assert stats["cache_size"] == 0
    assert stats["in_flight_count"] == 0
    assert stats["cache_maxsize"] == 100
    assert stats["cache_ttl"] > 0
