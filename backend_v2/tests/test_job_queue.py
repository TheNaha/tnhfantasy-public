"""Tests for services/job_queue.py"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.job_queue import JobQueue


class TestJobQueueInit:
    def test_init_max_workers(self):
        q = JobQueue(max_workers=3)
        assert q.max_workers == 3

    def test_init_not_running(self):
        q = JobQueue()
        assert q._running is False

    def test_init_no_processor(self):
        q = JobQueue()
        assert q._processor is None

    def test_init_empty_workers(self):
        q = JobQueue()
        assert q._workers == []

    def test_init_empty_active_jobs(self):
        q = JobQueue()
        assert q._active_jobs == {}


class TestJobQueueSetProcessor:
    def test_set_processor(self):
        q = JobQueue()
        async def my_processor(job_id, provider_id):
            pass
        q.set_processor(my_processor)
        assert q._processor is my_processor


class TestJobQueueEnqueue:
    async def test_enqueue_adds_to_queue(self):
        q = JobQueue()
        await q.enqueue("job-1")
        assert not q._queue.empty()

    async def test_enqueue_with_provider(self):
        q = JobQueue()
        await q.enqueue("job-1", "modal-primary")
        item = await q._queue.get()
        assert item == ("job-1", "modal-primary")

    async def test_enqueue_without_provider(self):
        q = JobQueue()
        await q.enqueue("job-2")
        item = await q._queue.get()
        assert item == ("job-2", None)

    async def test_enqueue_multiple(self):
        q = JobQueue()
        await q.enqueue("job-1")
        await q.enqueue("job-2")
        await q.enqueue("job-3")
        # All 3 should be in queue
        count = 0
        while not q._queue.empty():
            await q._queue.get()
            count += 1
        assert count == 3


class TestJobQueueStartStop:
    async def test_start_sets_running(self):
        q = JobQueue(max_workers=1)
        async def dummy_processor(job_id, provider_id):
            await asyncio.sleep(0)
        q.set_processor(dummy_processor)
        try:
            await q.start()
            assert q._running is True
        finally:
            await q.stop()

    async def test_stop_sets_not_running(self):
        q = JobQueue(max_workers=1)
        async def dummy_processor(job_id, provider_id):
            await asyncio.sleep(0)
        q.set_processor(dummy_processor)
        await q.start()
        await q.stop()
        assert q._running is False

    async def test_start_creates_workers(self):
        q = JobQueue(max_workers=2)
        async def dummy_processor(job_id, provider_id):
            await asyncio.sleep(100)  # Never complete
        q.set_processor(dummy_processor)
        try:
            await q.start()
            assert len(q._workers) == 2
        finally:
            await q.stop()

    async def test_start_twice_is_safe(self):
        q = JobQueue(max_workers=1)
        async def dummy_processor(job_id, provider_id):
            await asyncio.sleep(100)
        q.set_processor(dummy_processor)
        try:
            await q.start()
            await q.start()  # Should be a no-op
            assert len(q._workers) == 1
        finally:
            await q.stop()

    async def test_stop_when_not_running_is_safe(self):
        q = JobQueue(max_workers=1)
        # Should not raise
        await q.stop()

    async def test_stop_allows_active_job_to_finish_before_cancelling(self):
        q = JobQueue(max_workers=1)
        started = asyncio.Event()
        finished = asyncio.Event()

        async def dummy_processor(job_id, provider_id):
            started.set()
            await asyncio.sleep(0.05)
            finished.set()

        q.set_processor(dummy_processor)
        await q.start()
        await q.enqueue("job-1")

        await asyncio.wait_for(started.wait(), timeout=1.0)
        await q.stop()

        assert finished.is_set() is True
        assert q.active_count == 0

    async def test_stop_cancels_stuck_workers_after_timeout(self):
        q = JobQueue(max_workers=1)
        started = asyncio.Event()

        async def dummy_processor(job_id, provider_id):
            started.set()
            await asyncio.sleep(10)

        q.set_processor(dummy_processor)
        await q.start()
        await q.enqueue("job-1")

        await asyncio.wait_for(started.wait(), timeout=1.0)

        original_wait_for = asyncio.wait_for

        async def immediate_timeout(awaitable, timeout):
            if timeout == 5.0:
                raise asyncio.TimeoutError()
            return await original_wait_for(awaitable, timeout)

        with patch("services.job_queue.asyncio.wait_for", side_effect=immediate_timeout):
            await q.stop()

        assert q._workers == []
        assert q.active_count == 0


class TestJobQueueSize:
    async def test_size_empty(self):
        q = JobQueue()
        assert q._queue.qsize() == 0

    async def test_size_after_enqueue(self):
        q = JobQueue()
        await q.enqueue("job-1")
        await q.enqueue("job-2")
        assert q._queue.qsize() == 2
