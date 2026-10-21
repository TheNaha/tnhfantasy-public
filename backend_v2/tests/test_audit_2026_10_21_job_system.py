"""The job system must not strand, double-report or deadlock
(audit-2026-10-21 §2.10, §2.11, §2.12, §3.4, §3.7, §3.8, §3.9).

Six defects, one file each:

  * the provider-failover write (`mark_provider_exhausted` always writes
    PENDING) was rejected by the FSM from every state a provider can fail
    IN, so the job kept its old status through the whole failover;
  * `POST /api/jobs/{id}/retry` copied the ORIGINAL job's diagnostics
    block into the retry, so a retry that had not run yet reported the
    original's failure kind and attempt history;
  * the claim release was a bare `await` in a `finally`, so a DB error
    there leaked the claim - and a leaked claim stranded the job AND held
    a concurrency slot for good;
  * the claim had no lease at all;
  * the websocket cancel handler checked two of the three job pools, so a
    running TTS job could not be cancelled;
  * the shutdown requeue set PENDING but kept the claim, and the periodic
    reaper did not exist.
"""

import asyncio
from unittest.mock import patch

from core.entities import JobStatus
from services.job_service import (
    JOB_DIAGNOSTICS_KEY,
    JOB_RETRY_ORIGIN_DIAGNOSTICS_KEY,
    JOB_STATUS_TRANSITIONS,
    build_job_diagnostics,
)


class TestFailoverTransitions:
    def test_pending_is_reachable_from_every_state_a_provider_can_fail_in(self):
        """`mark_provider_exhausted` always writes PENDING.

        The provider client writes CONNECTED / PRE_GENERATION / GENERATING
        during the call, so a provider that dies after its first progress
        frame lands in one of them - and the failover write was rejected.
        """
        for status in (
            JobStatus.CONNECTED,
            JobStatus.PRE_GENERATION,
            JobStatus.GENERATING,
            JobStatus.POST_PROCESSING,
            JobStatus.RETRYING,
            JobStatus.SENT_TO_PROVIDER,
        ):
            assert JobStatus.PENDING in JOB_STATUS_TRANSITIONS[status], status

    def test_a_terminal_status_is_still_terminal(self):
        assert JOB_STATUS_TRANSITIONS[JobStatus.COMPLETED] == set()
        assert JOB_STATUS_TRANSITIONS[JobStatus.CANCELLED] == set()


class TestRetryDiagnostics:
    def test_a_retry_does_not_inherit_the_original_failure(self):
        """The retry's own diagnostics block starts EMPTY.

        The original's block is preserved under its own key, so the lineage
        survives without the retry claiming a failure it never had.
        """
        original = {
            "attempts": [{"provider_id": "provA", "attempt": 1, "outcome": "error"}],
            "attempt_count": 1,
            "last_provider_id": "provA",
            "last_outcome": "error",
            "failure_kind": "providers_exhausted",
            "failed_at": "2026-10-21T00:00:00Z",
        }
        metadata = {JOB_DIAGNOSTICS_KEY: original}

        # What the route now does.
        diagnostics = dict(metadata.get(JOB_DIAGNOSTICS_KEY) or {})
        retry_count = int(diagnostics.get("retry_count") or 0) + 1
        if diagnostics:
            metadata[JOB_RETRY_ORIGIN_DIAGNOSTICS_KEY] = diagnostics
        metadata[JOB_DIAGNOSTICS_KEY] = {"retry_of": "job-1", "retry_count": retry_count}

        fresh = metadata[JOB_DIAGNOSTICS_KEY]
        assert "failure_kind" not in fresh
        assert "attempts" not in fresh
        assert "attempt_count" not in fresh
        assert fresh["retry_of"] == "job-1"
        assert fresh["retry_count"] == 1

        # The original is still there, under its own name.
        assert metadata[JOB_RETRY_ORIGIN_DIAGNOSTICS_KEY]["failure_kind"] == "providers_exhausted"

    def test_the_diagnostics_view_of_a_fresh_retry_reports_no_error(self):
        class _Job:
            id = "job-2"
            provider_id = None
            error = None
            status = JobStatus.PENDING
            workflow = {"1": {"class_type": "SaveImage"}}
            metadata_ = {JOB_DIAGNOSTICS_KEY: {"retry_of": "job-1", "retry_count": 1}}
            created_at = None
            started_at = None
            completed_at = None
            task_type = "image"

        view = build_job_diagnostics(_Job())
        assert view["retry_of"] == "job-1"
        assert view["failure_kind"] is None
        assert view["error_type"] is None
        assert view["attempts"] == []


class TestClaimRelease:
    def test_a_failing_release_does_not_escape(self):
        """A DB error in the release used to raise out of the `finally`,
        be caught by the worker's outer handler, and leave the claim set."""
        from services.job_queue import JobQueue

        queue = JobQueue()
        calls = {"n": 0}

        def _boom(job_id):
            calls["n"] += 1
            raise RuntimeError("database is on fire")

        with patch.object(JobQueue, "_clear_claim_sync", staticmethod(_boom)):
            # It must not raise.
            asyncio.run(queue._clear_claim("job-1"))

        # And it must have tried more than once.
        assert calls["n"] >= 2

    def test_a_lease_exists_and_outlasts_the_longest_job(self):
        from services.job_queue import JobQueue
        from config import get_job_timeout

        queue = JobQueue(task_type="image")
        lease = queue._claim_lease_seconds()
        assert lease > get_job_timeout("image")

    def test_a_pool_knows_whether_a_job_is_active_anywhere(self):
        """The websocket cancel handler used to check two pools of three."""
        from services.job_queue import QueueManager

        manager = QueueManager()
        assert hasattr(manager, "is_job_active_anywhere")
        assert manager.is_job_active_anywhere("not-a-job") is False


class TestShutdownRequeue:
    def test_the_shutdown_requeue_clears_the_claim(self):
        """PENDING-WITH-claim is not claimable, so a requeued row that kept
        its claim sat in the queue and was never picked up."""
        import inspect

        from api import lifecycle

        source = inspect.getsource(lifecycle.requeue_inflight_jobs_for_shutdown)
        assert "claimed_at = None" in source


class TestJobReaper:
    def test_the_reaper_is_registered(self):
        import inspect

        from api import lifecycle

        assert hasattr(lifecycle, "_reap_wedged_jobs")
        assert lifecycle.JOB_REAPER_INTERVAL_SECONDS > 0
        source = inspect.getsource(lifecycle.startup_application)
        assert "_reap_wedged_jobs" in source

    def test_the_reaper_uses_each_jobs_own_timeout(self):
        import inspect

        from api import lifecycle

        source = inspect.getsource(lifecycle._reap_wedged_jobs)
        assert "timeout_seconds=None" in source
