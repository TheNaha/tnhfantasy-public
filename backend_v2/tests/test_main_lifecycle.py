from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from api.lifecycle import recover_post_processing_jobs, requeue_inflight_jobs_for_shutdown
from core.entities import Job, JobStatus
from core.events import EventType


class TestMainLifecycle:
    def test_requeue_inflight_jobs_for_shutdown(self, session, monkeypatch):
        running_job = Job(
            status=JobStatus.GENERATING,
            workflow={"nodes": {}},
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            progress=72.5,
            overall_progress=45.0,
            message="Rendering",
            error="old-error",
        )
        post_processing_job = Job(
            status=JobStatus.POST_PROCESSING,
            workflow={"nodes": {}},
            outputs=[{"filename": "output.png", "relative_path": "2026/04/01/output.png"}],
            started_at=datetime.now(timezone.utc),
            progress=100.0,
            overall_progress=100.0,
            message="Finishing outputs",
        )
        completed_job = Job(
            status=JobStatus.COMPLETED,
            workflow={"nodes": {}},
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            progress=100.0,
            overall_progress=100.0,
            message="Done",
        )
        session.add(running_job)
        session.add(post_processing_job)
        session.add(completed_job)
        session.commit()

        running_job_id = running_job.id
        post_processing_job_id = post_processing_job.id
        completed_job_id = completed_job.id

        monkeypatch.setattr("api.lifecycle.get_session_sync", lambda: session)

        count = requeue_inflight_jobs_for_shutdown()

        refreshed_running = session.get(Job, running_job_id)
        refreshed_post_processing = session.get(Job, post_processing_job_id)
        refreshed_completed = session.get(Job, completed_job_id)

        assert count == 1

        assert refreshed_running.status == JobStatus.PENDING
        assert refreshed_running.started_at is None
        assert refreshed_running.completed_at is None
        assert refreshed_running.progress == 0.0
        assert refreshed_running.overall_progress == 0.0
        assert refreshed_running.message == "Requeued after server shutdown"
        assert refreshed_running.error is None

        assert refreshed_post_processing.status == JobStatus.POST_PROCESSING
        assert refreshed_post_processing.message == "Finishing outputs"

        assert refreshed_completed.status == JobStatus.COMPLETED
        assert refreshed_completed.progress == 100.0
        assert refreshed_completed.overall_progress == 100.0
        assert refreshed_completed.message == "Done"

    def test_requeue_inflight_jobs_for_shutdown_when_empty(self, session, monkeypatch):
        monkeypatch.setattr("api.lifecycle.get_session_sync", lambda: session)

        count = requeue_inflight_jobs_for_shutdown()

        assert count == 0

    @pytest.mark.asyncio
    async def test_recover_post_processing_jobs(self, session, monkeypatch):
        job = Job(
            status=JobStatus.POST_PROCESSING,
            workflow={"nodes": {}},
            outputs=[{"filename": "output.png", "relative_path": "2026/04/01/output.png"}],
            provider_id="provider-a",
        )
        session.add(job)
        session.commit()
        job_id = job.id

        finalize_mock = AsyncMock()
        monkeypatch.setattr("api.lifecycle.get_session_sync", lambda: session)
        monkeypatch.setattr("services.job_processing.finalize_persisted_job_outputs", finalize_mock)

        recovered = await recover_post_processing_jobs()

        assert recovered == 1
        finalize_mock.assert_awaited_once()
        assert finalize_mock.await_args.kwargs["job_id"] == job_id
        assert finalize_mock.await_args.kwargs["provider_id"] == "provider-a"

    @pytest.mark.asyncio
    async def test_the_recovery_waits_for_the_finalisation(self, session, monkeypatch):
        """The recovery must not return before the finalisation has finished.

        The finalisation used to be SCHEDULED and the recovery returned
        immediately. The startup sweep then ran, moved the still-POST_PROCESSING
        job to PENDING with the claim cleared - and PENDING-with-no-claim is
        the claim predicate, so a live worker picked the job up and ran the
        entire PAID generation a second time.

        `await_completion=True` is the fix, and this asserts it is passed.
        """
        job = Job(
            status=JobStatus.POST_PROCESSING,
            workflow={"nodes": {}},
            outputs=[{"filename": "output.png", "relative_path": "2026/04/01/output.png"}],
            provider_id="provider-a",
        )
        session.add(job)
        session.commit()

        finalize_mock = AsyncMock()
        monkeypatch.setattr("api.lifecycle.get_session_sync", lambda: session)
        monkeypatch.setattr("services.job_processing.finalize_persisted_job_outputs", finalize_mock)

        await recover_post_processing_jobs()

        assert finalize_mock.await_args.kwargs.get("await_completion") is True, (
            "the recovery scheduled the finalisation instead of awaiting it, "
            "so the sweep can re-queue a job that has already been paid for"
        )

    @pytest.mark.asyncio
    async def test_a_post_processing_job_with_no_outputs_is_failed_visibly(
        self, session, monkeypatch
    ):
        """A job in post-processing with no outputs cannot be finalised.

        It is failed through `mark_failed`, so the frontend gets the event.
        The direct row write it replaced emitted nothing, so the browser
        waited for a completion that was never announced.
        """
        job = Job(
            status=JobStatus.POST_PROCESSING,
            workflow={"nodes": {}},
            outputs=[],
            provider_id="provider-a",
        )
        session.add(job)
        session.commit()
        job_id = job.id

        monkeypatch.setattr("api.lifecycle.get_session_sync", lambda: session)

        with patch("services.job_service.emit_job_event", new_callable=AsyncMock) as mock_emit:
            recovered = await recover_post_processing_jobs()

        assert recovered == 0
        refreshed = session.get(Job, job_id)
        assert refreshed.status == JobStatus.FAILED
        assert refreshed.error is not None
        # The event is the point: a FAILED row nobody is told about is a job
        # the browser waits on forever.
        assert mock_emit.called
        assert mock_emit.call_args_list[0][0][0] == EventType.JOB_FAILED


class TestStartupRecoveryOrder:
    """Mid-finalisation recovery must run before the claim sweep.

    `QueueManager.recover`'s Postgres path runs `_reset_claims_and_requeue_sync`,
    whose UPDATE includes POST_PROCESSING (it is in `ACTIVE_JOB_STATUSES`) and sets
    those rows back to PENDING with no claim markers — and PENDING-with-no-claim
    is the claim predicate. Run the sweep first and `recover_post_processing_jobs`
    then queries `status == POST_PROCESSING` and finds nothing: the job that had
    already paid for its images is queued and regenerated from scratch, and the
    outputs the first finalization was mid-way through writing get overwritten.

    Shutdown deliberately protects these rows on the way out
    (`requeue_inflight_jobs_for_shutdown` excludes POST_PROCESSING/RETRYING), so
    starting in the wrong order undoes that protection on every single boot.
    """

    @pytest.mark.asyncio
    async def test_post_processing_recovery_runs_before_the_claim_sweep(self, monkeypatch):
        import api.lifecycle as lifecycle

        order = []

        async def _fake_post_processing(*args, **kwargs):
            order.append("post_processing")
            return 0

        async def _fake_pending(*args, **kwargs):
            order.append("claim_sweep")
            return 0

        monkeypatch.setattr(
            lifecycle, "recover_post_processing_jobs", _fake_post_processing
        )
        monkeypatch.setattr(lifecycle, "recover_pending_jobs", _fake_pending)

        await lifecycle._run_job_recovery_phase()

        assert order == ["post_processing", "claim_sweep"], (
            "the claim sweep resets POST_PROCESSING rows to PENDING, so running it "
            f"first empties the post-processing recovery pass (got {order})"
        )

    def test_the_claim_sweep_really_does_include_post_processing(self):
        """The premise of the ordering, asserted directly rather than assumed.

        If POST_PROCESSING is ever dropped from ACTIVE_JOB_STATUSES the ordering
        stops mattering — and the comment above the call would be lying, which is
        the failure mode this whole pass exists to catch.
        """
        from core.entities import ACTIVE_JOB_STATUSES, JobStatus

        assert JobStatus.POST_PROCESSING in ACTIVE_JOB_STATUSES
