"""A deadline-bounded, cancellable ranged read from a remote storage container.

Both Modal clients stream a volume file out slice by slice (`file_size`, then
`read_file_range` in a loop) because a `@modal.method` serialises its return
value across the RPC boundary — a 7 GB checkpoint is 7 GB in the container and
again in the worker before the response is even built. The loop is therefore
several hundred RPCs, and two things were missing from it:

* **No deadline.** Modal's client retries a dropped connection, so a storage
  container that never comes back reads as a stream that never ends. The request
  then holds a connection, a billed container and the caller's worker for as long
  as the peer is willing to say nothing.
* **No way to cancel it.** The worker lifespan teardown looks for
  `hasattr(client, "close")`; neither Modal client defined one, so a SIGTERM had
  to wait the whole thing out.

The read runs in a task the caller owns, which is what makes cancellation
possible at all: an async generator cannot be reliably `aclose()`d from another
task while it is executing, so `close()` cancelling a generator was never going to
work. The consumer side drains a small bounded queue, so peak memory stays one
slice plus a queue slot.

Completion is detected by watching the *task*, not by a sentinel in the queue:
signalling a cancelled task from its own `finally` cannot be done reliably (an
`await` in a cancelled task's `finally` raises again), and a consumer left waiting
on a queue nobody will ever write to is exactly the hang this module exists to
remove.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, Set


class RangedReader:
    """One in-flight ranged read.

    Args:
        read_size: ``(path) -> total bytes``. May raise ``FileNotFoundError``.
        read_range: ``(path, offset, length) -> bytes``. May raise
            ``FileNotFoundError``; an empty result means end-of-file (a short
            read at the end, or a concurrent delete).
        registry: the client's set of in-flight read tasks, so ``close()`` can
            cancel them. Nothing is added when it is ``None``.
    """

    def __init__(
        self,
        *,
        read_size: Callable[[str], Awaitable[int]],
        read_range: Callable[[str, int, int], Awaitable[bytes]],
        path: str,
        range_bytes: int,
        timeout_seconds: float,
        registry: Optional[Set[Any]] = None,
    ) -> None:
        self._read_size = read_size
        self._read_range = read_range
        self._path = path
        self._range_bytes = range_bytes
        self._timeout_seconds = timeout_seconds
        self._registry = registry
        self._total: Optional[int] = None

    async def prepare(self) -> None:
        """Probe the file size and verify existence before streaming starts."""
        self._total = await self._read_size(self._path)

    async def _pump(self, queue: "asyncio.Queue[bytes]") -> None:
        total = self._total if self._total is not None else await self._read_size(self._path)
        offset = 0
        while offset < total:
            chunk = await self._read_range(self._path, offset, self._range_bytes)
            if not chunk:
                # A short file between calls, or a concurrent delete. Either way
                # there is nothing more to send, and hanging would be worse.
                return
            offset += len(chunk)
            await queue.put(chunk)

    async def stream(self) -> AsyncIterator[bytes]:
        """Yield the file's slices until exhausted, or until the deadline hits.

        The deadline covers the *transfer*, not the consumer: a caller reading the
        response body slowly must not trip it. On expiry the result is a plain
        ``TimeoutError`` naming the path — a ``StreamingResponse`` has already
        committed 200 by then and no status can be invented, so the operator gets
        a traceback, which beats a stream that never ends.
        """
        queue: "asyncio.Queue[bytes]" = asyncio.Queue(maxsize=2)
        task = asyncio.create_task(self._pump(queue))
        if self._registry is not None:
            self._registry.add(task)
        try:
            async with asyncio.timeout(self._timeout_seconds):
                while True:
                    getter = asyncio.create_task(queue.get())
                    done, _ = await asyncio.wait(
                        {getter, task}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if getter in done:
                        yield getter.result()
                        continue
                    # The pump finished (or failed) with nothing left queued.
                    getter.cancel()
                    if task.cancelled():
                        raise asyncio.CancelledError()
                    failure = task.exception()
                    if failure is not None:
                        raise failure
                    return
        except TimeoutError:
            raise TimeoutError(
                f"ranged read of {self._path!r} exceeded "
                f"{self._timeout_seconds:g}s on the remote storage container"
            ) from None
        finally:
            if not task.done():
                task.cancel()
            if self._registry is not None:
                self._registry.discard(task)
            await asyncio.gather(task, return_exceptions=True)


async def cancel_ranged_reads(tasks: Set[Any]) -> None:
    """Cancel every in-flight read and wait for them to actually stop.

    Cancelling the task is what makes the underlying RPC future stop being
    awaited; gathering is what guarantees it is no longer holding a connection
    when this returns, which is the whole point of calling it during teardown.
    """
    pending = [task for task in list(tasks) if not task.done()]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    tasks.clear()
