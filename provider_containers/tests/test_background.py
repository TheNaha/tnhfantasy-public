import pytest
import asyncio
from provider_core.background import JobCancellationTracker

@pytest.mark.asyncio
async def test_job_lifecycle():
    tracker = JobCancellationTracker()
    job_id = "job-123"

    # Start job
    await tracker.start_job(job_id)
    assert await tracker.is_active(job_id) is True
    assert await tracker.is_cancelled(job_id) is False

    # Cancel job
    result = await tracker.cancel_job(job_id)
    assert result is True
    assert await tracker.is_cancelled(job_id) is True
    assert await tracker.is_active(job_id) is True

    # End job
    await tracker.end_job(job_id)
    assert await tracker.is_active(job_id) is False
    assert await tracker.is_cancelled(job_id) is False

@pytest.mark.asyncio
async def test_cancel_non_existent_job():
    tracker = JobCancellationTracker()
    job_id = "non-existent-job"

    result = await tracker.cancel_job(job_id)
    assert result is False
    assert await tracker.is_cancelled(job_id) is False

@pytest.mark.asyncio
async def test_empty_job_id():
    tracker = JobCancellationTracker()

    # Empty job ID should not cause errors and return False
    await tracker.start_job("")
    assert await tracker.is_active("") is False

    result = await tracker.cancel_job("")
    assert result is False

    await tracker.end_job("")
    assert await tracker.is_active("") is False

@pytest.mark.asyncio
async def test_concurrency():
    tracker = JobCancellationTracker()
    job_count = 100

    async def run_job_lifecycle(i):
        job_id = f"job-{i}"
        await tracker.start_job(job_id)
        # Small sleep to allow context switching
        await asyncio.sleep(0.001)
        if i % 2 == 0:
            await tracker.cancel_job(job_id)
        await tracker.end_job(job_id)

    tasks = [run_job_lifecycle(i) for i in range(job_count)]
    await asyncio.gather(*tasks)

    # Verify all jobs are cleaned up
    for i in range(job_count):
        job_id = f"job-{i}"
        assert await tracker.is_active(job_id) is False
        assert await tracker.is_cancelled(job_id) is False
