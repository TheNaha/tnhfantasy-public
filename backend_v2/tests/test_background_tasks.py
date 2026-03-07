import asyncio

import pytest

from infrastructure.background_tasks import cancel_background_tasks, start_background_task


@pytest.fixture(autouse=True)
async def cleanup_background_tasks_fixture():
    yield
    await cancel_background_tasks()


@pytest.mark.asyncio
async def test_start_background_task_completes_and_unregisters():
    results = []

    async def worker():
        results.append("done")
        return 123

    task = start_background_task(worker(), task_name="test_complete")

    assert await task == 123
    assert results == ["done"]
    assert await cancel_background_tasks() == 0


@pytest.mark.asyncio
async def test_cancel_background_tasks_cancels_pending_tasks():
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def worker():
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = start_background_task(worker(), task_name="test_cancel")
    await started.wait()

    cancelled_count = await cancel_background_tasks()
    await asyncio.sleep(0)

    assert cancelled_count >= 1
    assert task.cancelled()
    assert cancelled.is_set()