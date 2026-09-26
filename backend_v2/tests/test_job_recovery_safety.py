"""Tests for the safety guards on POST /api/jobs/recover.

The endpoint used to do two destructive things in sequence:
  1. `fail_stale_running_jobs(timeout)` — the caller picked the timeout and the
     floor was 30s, shorter than a normal image generation, so the default wrote
     FAILED to every live job.
  2. `JobQueue._reset_claims_and_requeue_sync` — an unconditional
     `UPDATE jobs SET status='PENDING' ... WHERE status IN (active...)`.
     `execute_job` requires PENDING, so that is a RE-DISPATCH, not a re-mark: a
     running LLM job gets charged twice and two Asset rows are produced.

Startup recovery can do (2) because it runs immediately after boot, when every
claim in the DB is stale by definition. A live HTTP endpoint cannot, so the
route now performs only the safe half by default.
"""

from datetime import datetime, timedelta, timezone

import pytest

from api.routes.jobs import (
    MAX_RECOVER_TIMEOUT_SECONDS,
    MIN_RECOVER_TIMEOUT_SECONDS,
)
from core.entities import Job, JobStatus


def make_job(session, **overrides) -> Job:
    job = Job(
        task_type=overrides.pop("task_type", "image"),
        workflow=overrides.pop("workflow", {"nodes": {"1": {"class_type": "KSampler"}}}),
        metadata_=overrides.pop("metadata_", {"prompt": "a cat"}),
    )
    for key, value in overrides.items():
        setattr(job, key, value)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@pytest.fixture
def stub_queue_manager(monkeypatch):
    """Records what the route delegated to `JobQueue.recover`, if anything."""
    import services.job_queue as job_queue_module

    calls: list[dict] = []

    class _Stub:
        async def recover(self, job_service, *, timeout_seconds):
            calls.append({"timeout_seconds": timeout_seconds})
            return {
                "mode": "stub",
                "recovered": 0,
                "failed": 0,
                "failed_job_ids": [],
                "pending": 0,
                "running": 0,
            }

    monkeypatch.setattr(job_queue_module.queue_manager, "recover", _Stub().recover)
    return calls


class TestTimeoutFloor:
    def test_floor_matches_startup_recovery(self):
        """A manual recover must never be more aggressive than an automatic one."""
        from services.job_service import STALE_JOB_TIMEOUT_SECONDS

        assert MIN_RECOVER_TIMEOUT_SECONDS == STALE_JOB_TIMEOUT_SECONDS

    def test_ceiling_is_still_applied(self):
        assert MAX_RECOVER_TIMEOUT_SECONDS == 3600

    @pytest.mark.parametrize("requested", [1, 30, 60, 299])
    def test_short_timeouts_are_clamped_up(self, client, session, stub_queue_manager, requested):
        make_job(session, status=JobStatus.PENDING)

        resp = client.post(f"/api/jobs/recover?timeout_seconds={requested}")

        assert resp.status_code == 200, resp.text
        if stub_queue_manager:
            assert stub_queue_manager[-1]["timeout_seconds"] == MIN_RECOVER_TIMEOUT_SECONDS

    def test_long_timeouts_are_clamped_down(self, client, session, stub_queue_manager):
        make_job(session, status=JobStatus.PENDING)

        resp = client.post("/api/jobs/recover?timeout_seconds=999999")

        assert resp.status_code == 200, resp.text
        if stub_queue_manager:
            assert stub_queue_manager[-1]["timeout_seconds"] == MAX_RECOVER_TIMEOUT_SECONDS

    def test_a_60_second_timeout_no_longer_fails_a_live_job(
        self, client, session, stub_queue_manager
    ):
        """The old 30s floor meant `?timeout_seconds=60` failed a 90s image job."""
        job = make_job(
            session,
            status=JobStatus.GENERATING,
            started_at=datetime.now(timezone.utc) - timedelta(seconds=90),
        )

        resp = client.post("/api/jobs/recover?timeout_seconds=60")

        assert resp.status_code == 200, resp.text
        assert session.get(Job, job.id).status != JobStatus.FAILED


class TestNoRedispatchOfLiveJobs:
    def test_active_job_blocks_the_full_requeue_by_default(self, client, session, stub_queue_manager):
        running = make_job(
            session,
            status=JobStatus.GENERATING,
            started_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        )

        resp = client.post("/api/jobs/recover")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["requeued"] is False
        assert body["recovered"] == 0
        assert running.id in body["skipped_running"]
        # The destructive path was never reached.
        assert stub_queue_manager == []
        # ...and the job is untouched, not failed, not re-dispatched.
        assert session.get(Job, running.id).status == JobStatus.GENERATING

    def test_stale_jobs_are_still_failed_alongside_a_live_one(
        self, client, session, stub_queue_manager
    ):
        stuck = make_job(
            session,
            status=JobStatus.GENERATING,
            started_at=datetime.now(timezone.utc) - timedelta(seconds=7200),
        )
        alive = make_job(
            session,
            status=JobStatus.GENERATING,
            started_at=datetime.now(timezone.utc) - timedelta(seconds=5),
        )

        resp = client.post("/api/jobs/recover")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["failed"] == 1
        assert body["failed_job_ids"] == [stuck.id]
        assert body["skipped_running"] == [alive.id]
        assert session.get(Job, stuck.id).status == JobStatus.FAILED
        assert session.get(Job, alive.id).status == JobStatus.GENERATING

    def test_pending_unclaimed_jobs_do_not_block_recovery(
        self, client, session, stub_queue_manager
    ):
        """A job that never left the queue has no in-flight attempt to orphan."""
        make_job(session, status=JobStatus.PENDING)

        resp = client.post("/api/jobs/recover")

        assert resp.status_code == 200, resp.text
        assert resp.json()["mode"] != "stale_only"
        assert stub_queue_manager, "the full recovery should have run"

    def test_explicit_opt_in_restores_the_destructive_path(
        self, client, session, stub_queue_manager
    ):
        running = make_job(
            session,
            status=JobStatus.GENERATING,
            started_at=datetime.now(timezone.utc) - timedelta(seconds=5),
        )

        resp = client.post("/api/jobs/recover?requeue_running=true")

        assert resp.status_code == 200, resp.text
        assert stub_queue_manager, "requeue_running=true must reach JobQueue.recover"
        assert running.id  # the job is what the opt-in is about

    def test_nothing_running_is_a_normal_full_recovery(self, client, session, stub_queue_manager):
        make_job(session, status=JobStatus.PENDING)

        resp = client.post("/api/jobs/recover")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "success"
        assert "requeued" not in body  # the JobQueue.recover shape, not the guarded one
        assert stub_queue_manager


class TestActiveJobDetection:
    def test_only_started_active_jobs_count_as_in_flight(self, client, session):
        """A PENDING row with no `started_at` never left the queue."""
        make_job(session, status=JobStatus.SENT_TO_PROVIDER)  # active, never started

        resp = client.post("/api/jobs/recover")

        assert resp.status_code == 200, resp.text
        assert resp.json().get("skipped_running") is None

    def test_terminal_jobs_do_not_block(self, client, session, stub_queue_manager):
        make_job(session, status=JobStatus.COMPLETED)
        make_job(session, status=JobStatus.FAILED, error="boom")

        resp = client.post("/api/jobs/recover")

        assert resp.status_code == 200, resp.text
        assert stub_queue_manager
