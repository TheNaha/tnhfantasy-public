import asyncio
from typing import Awaitable, Set, Any

from infrastructure.logging import get_logger

logger = get_logger("background_tasks")
_background_tasks: Set[asyncio.Task[Any]] = set()


def start_background_task(
    coro: Awaitable[Any],
    *,
    task_name: str,
):
    """Start a background task with exception logging and lifecycle tracking."""
    task = asyncio.create_task(coro, name=task_name)
    _background_tasks.add(task)

    def _on_done(done_task: asyncio.Task[Any]) -> None:
        _background_tasks.discard(done_task)
        try:
            done_task.result()
        except asyncio.CancelledError:
            logger.debug("background_task_cancelled", task_name=task_name)
        except Exception as exc:
            logger.error("background_task_failed", task_name=task_name, error=str(exc))

    task.add_done_callback(_on_done)
    return task


async def cancel_background_tasks(timeout: float = 5.0) -> int:
    """Cancel all tracked background tasks and wait for them to finish."""
    tasks = list(_background_tasks)
    if not tasks:
        return 0

    for task in tasks:
        task.cancel()

    try:
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("background_task_cancel_timeout", remaining=len(_background_tasks))

    return len(tasks)