"""A dedicated thread pool for database work off the event loop.

Why this exists
───────────────
The job path is `async def` all the way down, but the actual database work is
sync SQLModel — `session.exec`, `session.commit`, `session.add` — inside those
async bodies. `_ImageReducer` calls `job_service.update_job` on every progress
frame, throttled to one per second, so each in-flight job issued roughly one
blocking commit per second *on the event loop*. The whole API stalls behind it,
not just the job.

Why not `asyncio.to_thread`
───────────────────────────
`asyncio.to_thread` uses the loop's default executor, which is
`min(32, cpu_count + 4)` — six threads on the 2-CPU box this is deployed on.
Offloading the job path onto that turns a serial stall into a queue of N jobs
contending for six threads, and the sixth one to arrive waits on all five. That
is the same latency, redistributed, and it is the reason this exists as its own
pool rather than as a one-line `await asyncio.to_thread(...)` change.

Why this size
─────────────
Matched to the database pool (`DB_POOL_SIZE + DB_MAX_OVERFLOW`), so the offload
pool can keep as many connections busy as the database will hand out. A larger
pool would queue on `pool_timeout` inside SQLAlchemy instead; a smaller one
leaves connections idle while jobs wait for a thread.

Session safety
──────────────
A SQLModel `Session` is a unit of work and is not safe for concurrent use. This
is only sound because a session here is owned by exactly one job: `execute_job`
opens one via `session_context_manager()` and every coroutine that touches it
awaits the next, so only one thread is ever inside it. Sharing a session across
concurrent coroutines would need one session per thread, which is a different
design.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any, Callable, TypeVar

from infrastructure.logging import get_logger

logger = get_logger("db_executor")

T = TypeVar("T")

#: The default, used when the DB pool is unknown or does not apply (tests, the
#: NullPool case, a missing config module). Deliberately small: this pool exists
#: to *bound* offloaded work, and a default that cannot over-subscribe is the
#: safe failure — while still being more than one thread, so it is a pool and not
#: a queue.
_DEFAULT_SIZE = 8


def default_pool_size() -> int:
    """The fallback size, exported so the DB module can report one number."""
    return _DEFAULT_SIZE


def _pool_size() -> int:
    """Read the database pool size the engine was actually built with."""
    try:
        from infrastructure.database import get_db_pool_size

        return get_db_pool_size()
    except Exception:
        return _DEFAULT_SIZE


_POOL_SIZE = _pool_size()

executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=_POOL_SIZE,
    thread_name_prefix="db-offload",
)

#: Lives for the process, like the database pool it matches. Not shut down by
#: the lifespan: the pool is created at import, and threading's atexit hook
#: joins the threads — an explicit shutdown would only add a place for it to
#: fail.
_executor_closed = False


async def run_db(fn: Callable[..., T], *args: Any) -> T:
    """Run sync database work on the offload pool.

    Returns the callable's result, or raises its exception — a caller cannot
    tell the difference from a direct call, which is what makes this a
    drop-in replacement for `await self.some_sync_thing()`.

    `functools.partial` or a lambda both work; keyword arguments need binding
    first, since `run_in_executor` takes positional args only.
    """
    if _executor_closed:
        # Degrade to the default executor rather than raising: an offload pool
        # that is gone should not take a job with it.
        return await asyncio.to_thread(fn, *args)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, fn, *args)


async def offload_sync(coro_factory: Callable[[], T]) -> T:
    """Run a zero-argument callable on the offload pool.

    The lambda-friendly form, for the common `k=lambda: self.session.commit()`
    case where binding keywords is noise.
    """
    return await run_db(coro_factory)


def shutdown_executor(wait: bool = True) -> None:
    """Stop accepting work. Safe to call twice; never raises."""
    global _executor_closed
    if _executor_closed:
        return
    _executor_closed = True
    try:
        executor.shutdown(wait=wait)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("db_executor_shutdown_failed", error=str(exc))


def stats() -> dict[str, Any]:
    """For the diagnostics endpoint: pool size and how busy it is."""
    return {
        "max_workers": _POOL_SIZE,
        "active": len(getattr(executor, "_threads", ()) or ()),
    }


__all__ = ["run_db", "offload_sync", "shutdown_executor", "stats", "executor"]
