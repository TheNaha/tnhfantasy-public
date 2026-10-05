"""A cold cache key must be computed once, not once per concurrent caller.

`infrastructure/cache.py` decorated functions with check-then-compute-then-store
and nothing in between, so N simultaneous misses all missed and all ran the whole
computation. Measured on `/api/statistics/detailed` against live Postgres:

    one cold request                 10.9 s
    eight concurrent cold requests   58-71 s EACH
    the same key afterwards          0.0008 s

The stampede did not make eight answers cheaper — it made every one of them about
six times slower than the single request that would have populated the key. The
handler is `async def` calling `asyncio.to_thread`, so all eight land in the
thread pool together and compete for the same database connections.

This is the shape every TTL cache in the project has, and it is invisible to a
test that only ever makes one request at a time.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from infrastructure.cache import _INFLIGHT, cached, invalidate_cache


@cached("stats")
async def slow_double(value: int) -> int:
    """Counts its own invocations, so a stampede is observable without timing."""
    slow_double.calls += 1
    await asyncio.sleep(0.05)
    return value * 2


slow_double.calls = 0


@pytest.fixture(autouse=True)
def _reset():
    _INFLIGHT.clear()
    invalidate_cache("stats")
    slow_double.calls = 0
    yield
    _INFLIGHT.clear()
    invalidate_cache("stats")


class TestSingleFlight:
    @pytest.mark.asyncio
    async def test_eight_concurrent_misses_compute_once(self):
        results = await asyncio.gather(*[slow_double(21) for _ in range(8)])

        assert results == [42] * 8, "every caller must get the right answer"
        assert slow_double.calls == 1, (
            f"the wrapped function ran {slow_double.calls} times for one key"
        )

    @pytest.mark.asyncio
    async def test_waiters_get_the_stored_value_not_a_second_computation(self):
        first, second = await asyncio.gather(slow_double(7), slow_double(7))

        assert first == second == 14
        # And the key is now hot for a caller that arrives afterwards.
        assert await slow_double(7) == 14
        assert slow_double.calls == 1

    @pytest.mark.asyncio
    async def test_different_keys_do_not_serialise_each_other(self):
        started = time.monotonic()
        await asyncio.gather(
            slow_double(1), slow_double(2), slow_double(3), slow_double(4)
        )
        elapsed = time.monotonic() - started

        assert slow_double.calls == 4, "distinct keys must each be computed"
        # Four keys x 50ms of sleep would be 200ms if they serialised.
        assert elapsed < 0.15, f"distinct keys serialised: {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_the_lock_map_does_not_grow_with_the_keyspace(self):
        """One lock per key, removed once the result is stored. A map that only
        grows is a leak with a plausible-looking name."""
        for value in range(20):
            await slow_double(value)

        assert _INFLIGHT == {}, f"stale single-flight slots: {list(_INFLIGHT)}"

    @pytest.mark.asyncio
    async def test_a_raising_computation_does_not_poison_the_key(self):
        @cached("stats")
        async def boom(value: int) -> int:
            boom.calls += 1
            if boom.calls == 1:
                raise RuntimeError("first attempt fails")
            return value

        boom.calls = 0

        with pytest.raises(RuntimeError):
            await boom(1)

        # The lock is released on the way out, so the retry runs rather than
        # deadlocking against a lock nobody will ever release.
        assert await boom(1) == 1
        assert _INFLIGHT == {}
