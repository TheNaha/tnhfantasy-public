"""A cancelled caller must not de-register work that is still running.

`deduplicated` shields the shared task so that one waiter giving up cannot
cancel the work for every other waiter. The `finally`, though, ran on the
creator's cancellation as well as on completion — and it popped `_in_flight`
unconditionally. So:

  1. caller A starts the work and is cancelled
  2. the shielded task is still running
  3. `_in_flight` no longer has the entry
  4. caller B, asking for the same key, starts a SECOND copy

The dedup still "works" — both callers get a result — so nothing raises and no
log line says anything. It just stops deduplicating, which for a
`/api/statistics/detailed`-shaped call means two full aggregations where there
was one.
"""
import asyncio

import pytest

from infrastructure.request_dedup import (
    clear_dedup_cache,
    deduplicated,
    get_dedup_stats,
    is_in_flight,
)


@pytest.fixture(autouse=True)
def _clear():
    clear_dedup_cache()
    yield
    clear_dedup_cache()


async def test_a_cancelled_creator_does_not_evict_running_work():
    started = asyncio.Event()
    release = asyncio.Event()
    runs = 0

    async def slow():
        nonlocal runs
        runs += 1
        started.set()
        await release.wait()
        return "done"

    # 1. The creator is cancelled while the work is in flight.
    creator = asyncio.create_task(deduplicated("k", slow))
    await started.wait()
    creator.cancel()
    with pytest.raises(asyncio.CancelledError):
        await creator

    # 2. The shielded work is genuinely still running.
    assert runs == 1
    assert is_in_flight("k"), "the running task was evicted from _in_flight"

    # 3. A second caller joins the SAME task rather than starting a new one.
    follower = asyncio.create_task(deduplicated("k", slow))
    await asyncio.sleep(0)
    assert runs == 1, "a second concurrent copy of the work was started"

    # 4. When the work finishes, the entry retires itself.
    release.set()
    assert await follower == "done"
    await asyncio.sleep(0)
    assert not is_in_flight("k")
    assert get_dedup_stats()["in_flight_count"] == 0


async def test_a_waiter_being_cancelled_does_not_disturb_the_others():
    release = asyncio.Event()
    started = asyncio.Event()
    runs = 0

    async def slow():
        nonlocal runs
        runs += 1
        started.set()
        await release.wait()
        return runs

    creator = asyncio.create_task(deduplicated("k2", slow))
    await started.wait()

    # A second caller that is itself cancelled must not affect anything.
    quitter = asyncio.create_task(deduplicated("k2", slow))
    await asyncio.sleep(0)
    quitter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await quitter

    release.set()
    assert await creator == 1
    assert runs == 1


async def test_the_key_is_retired_after_completion_as_before():
    done = asyncio.Event()

    async def quick():
        done.set()
        return 1

    assert await deduplicated("k3", quick) == 1
    await asyncio.sleep(0)
    assert not is_in_flight("k3")
    # And the result cache still serves the second caller without re-running.
    assert await deduplicated("k3", quick) == 1
