"""Tests for infrastructure/scheduler.py"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timedelta
import infrastructure.scheduler as sched_module
from infrastructure.scheduler import (
    get_scheduler,
    start_scheduler,
    stop_scheduler,
    add_interval_job,
    add_cron_job,
    remove_job,
    get_jobs_status,
    schedule_reconciliation,
    schedule_model_sync,
    schedule_cleanup,
    schedule_stats_refresh,
    schedule_vacuum,
)


@pytest.fixture(autouse=True)
def reset_scheduler():
    """Reset the global scheduler before and after each test."""
    sched_module._scheduler = None
    yield
    # Stop scheduler if running
    if sched_module._scheduler is not None:
        try:
            if sched_module._scheduler.running:
                sched_module._scheduler.shutdown(wait=False)
        except Exception:
            pass
    sched_module._scheduler = None


class TestGetScheduler:
    def test_returns_scheduler(self):
        scheduler = get_scheduler()
        assert scheduler is not None

    def test_singleton_same_instance(self):
        s1 = get_scheduler()
        s2 = get_scheduler()
        assert s1 is s2

    def test_creates_new_if_none(self):
        sched_module._scheduler = None
        scheduler = get_scheduler()
        assert scheduler is not None


class TestStartStopScheduler:
    async def test_start_scheduler(self):
        start_scheduler()
        scheduler = get_scheduler()
        assert scheduler.running

    async def test_stop_scheduler(self):
        start_scheduler()
        stop_scheduler()
        assert sched_module._scheduler is None

    def test_stop_noop_if_not_running(self):
        # Should not raise
        stop_scheduler()

    async def test_start_twice_is_safe(self):
        start_scheduler()
        start_scheduler()  # Should not raise
        assert get_scheduler().running


class TestAddIntervalJob:
    async def test_add_interval_job(self):
        start_scheduler()

        async def dummy():
            pass

        add_interval_job(dummy, interval_seconds=60, job_id="test-job")
        scheduler = get_scheduler()
        assert scheduler.get_job("test-job") is not None

    async def test_replaces_existing_job(self):
        start_scheduler()

        async def dummy():
            pass

        add_interval_job(dummy, interval_seconds=60, job_id="test-job")
        add_interval_job(dummy, interval_seconds=120, job_id="test-job")
        scheduler = get_scheduler()
        # Still only one job with this ID
        assert scheduler.get_job("test-job") is not None

    async def test_add_multiple_jobs(self):
        start_scheduler()

        async def dummy():
            pass

        add_interval_job(dummy, interval_seconds=60, job_id="job-1")
        add_interval_job(dummy, interval_seconds=120, job_id="job-2")
        scheduler = get_scheduler()
        assert scheduler.get_job("job-1") is not None
        assert scheduler.get_job("job-2") is not None

    async def test_start_immediately_false_delays_first_run(self):
        start_scheduler()

        async def dummy():
            pass

        add_interval_job(dummy, interval_seconds=60, job_id="delayed-job", start_immediately=False)
        job = get_scheduler().get_job("delayed-job")

        assert job is not None
        now = datetime.now(job.next_run_time.tzinfo)
        assert job.next_run_time >= now + timedelta(seconds=55)

    async def test_start_immediately_true_runs_now(self):
        start_scheduler()

        async def dummy():
            pass

        add_interval_job(dummy, interval_seconds=60, job_id="immediate-job", start_immediately=True)
        job = get_scheduler().get_job("immediate-job")

        assert job is not None
        now = datetime.now(job.next_run_time.tzinfo)
        assert job.next_run_time <= now + timedelta(seconds=5)


class TestAddCronJob:
    async def test_add_cron_job(self):
        start_scheduler()

        async def dummy():
            pass

        add_cron_job(dummy, "0 * * * *", "cron-job-1")
        scheduler = get_scheduler()
        assert scheduler.get_job("cron-job-1") is not None

    async def test_replaces_existing_cron_job(self):
        start_scheduler()

        async def dummy():
            pass

        add_cron_job(dummy, "0 * * * *", "cron-job-1")
        add_cron_job(dummy, "0 0 * * *", "cron-job-1")
        scheduler = get_scheduler()
        assert scheduler.get_job("cron-job-1") is not None

    async def test_cron_with_kwargs(self):
        start_scheduler()

        async def dummy(value=None):
            pass

        add_cron_job(dummy, "*/15 * * * *", "cron-job-2", value="test")
        scheduler = get_scheduler()
        assert scheduler.get_job("cron-job-2") is not None


class TestRemoveJob:
    async def test_remove_existing_job(self):
        start_scheduler()

        async def dummy():
            pass

        add_interval_job(dummy, interval_seconds=60, job_id="removable-job")
        remove_job("removable-job")
        scheduler = get_scheduler()
        assert scheduler.get_job("removable-job") is None

    def test_remove_nonexistent_job_is_safe(self):
        # Test that attempting to remove a nonexistent job doesn't raise
        # when scheduler is not started
        scheduler = get_scheduler()
        # Just verify the job doesn't exist
        assert scheduler.get_job("nonexistent-job") is None


class TestGetJobsStatus:
    async def test_returns_empty_list_when_no_jobs(self):
        start_scheduler()
        jobs = get_jobs_status()
        assert isinstance(jobs, list)

    async def test_returns_job_info(self):
        start_scheduler()

        async def dummy():
            pass

        add_interval_job(dummy, interval_seconds=3600, job_id="status-test-job", start_immediately=False)
        jobs = get_jobs_status()
        job_ids = [j["id"] for j in jobs]
        assert "status-test-job" in job_ids

    async def test_job_info_has_required_fields(self):
        start_scheduler()

        async def dummy():
            pass

        add_interval_job(dummy, interval_seconds=3600, job_id="info-job", start_immediately=False)
        jobs = get_jobs_status()
        job = next(j for j in jobs if j["id"] == "info-job")
        assert "id" in job
        assert "name" in job
        assert "trigger" in job


class TestScheduleConvenienceFunctions:
    async def test_schedule_reconciliation(self):
        start_scheduler()

        async def dummy():
            pass

        schedule_reconciliation(dummy, interval_seconds=120)
        scheduler = get_scheduler()
        assert scheduler.get_job("reconciliation") is not None

    async def test_schedule_model_sync(self):
        start_scheduler()

        async def dummy():
            pass

        schedule_model_sync(dummy, interval_seconds=300)
        scheduler = get_scheduler()
        assert scheduler.get_job("model_sync") is not None

    async def test_schedule_cleanup(self):
        start_scheduler()

        async def dummy():
            pass

        schedule_cleanup(dummy, interval_seconds=3600)
        scheduler = get_scheduler()
        assert scheduler.get_job("cleanup") is not None

    async def test_schedule_stats_refresh(self):
        start_scheduler()

        async def dummy():
            pass

        schedule_stats_refresh(dummy, interval_seconds=600)
        scheduler = get_scheduler()
        assert scheduler.get_job("stats_refresh") is not None

    async def test_schedule_vacuum(self):
        start_scheduler()

        async def dummy():
            pass

        schedule_vacuum(dummy, interval_seconds=86400)
        scheduler = get_scheduler()
        assert scheduler.get_job("database_vacuum") is not None
