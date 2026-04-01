from unittest.mock import AsyncMock

from datetime import datetime
import pytest

from core.entities import Job, JobStatus
from api.main import _requeue_inflight_jobs_for_shutdown
from api.lifecycle import recover_post_processing_jobs


class TestMainLifecycle:
    def test_requeue_inflight_jobs_for_shutdown(self, session, monkeypatch):
        running_job = Job(
            status=JobStatus.RUNNING,
            workflow={"nodes": {}},
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            progress=72.5,
            overall_progress=45.0,
            message="Rendering",
            error="old-error",
        )
        processing_job = Job(
            status=JobStatus.PROCESSING,
            workflow={"nodes": {}},
            started_at=datetime.utcnow(),
            progress=33.0,
            overall_progress=88.0,
            message="Post-processing",
        )
        post_processing_job = Job(
            status=JobStatus.POST_PROCESSING,
            workflow={"nodes": {}},
            outputs=[{"filename": "output.png", "relative_path": "2026/04/01/output.png"}],
            started_at=datetime.utcnow(),
            progress=100.0,
            overall_progress=100.0,
            message="Finishing outputs",
        )
        completed_job = Job(
            status=JobStatus.COMPLETED,
            workflow={"nodes": {}},
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            progress=100.0,
            overall_progress=100.0,
            message="Done",
        )
        session.add(running_job)
        session.add(processing_job)
        session.add(post_processing_job)
        session.add(completed_job)
        session.commit()

        running_job_id = running_job.id
        processing_job_id = processing_job.id
        post_processing_job_id = post_processing_job.id
        completed_job_id = completed_job.id

        monkeypatch.setattr("api.lifecycle.get_session_sync", lambda: session)

        count = _requeue_inflight_jobs_for_shutdown()

        refreshed_running = session.get(Job, running_job_id)
        refreshed_processing = session.get(Job, processing_job_id)
        refreshed_post_processing = session.get(Job, post_processing_job_id)
        refreshed_completed = session.get(Job, completed_job_id)

        assert count == 2

        assert refreshed_running.status == JobStatus.PENDING
        assert refreshed_running.started_at is None
        assert refreshed_running.completed_at is None
        assert refreshed_running.progress == 0.0
        assert refreshed_running.overall_progress == 0.0
        assert refreshed_running.message == "Requeued after server shutdown"
        assert refreshed_running.error is None

        assert refreshed_processing.status == JobStatus.PENDING
        assert refreshed_processing.started_at is None
        assert refreshed_processing.completed_at is None
        assert refreshed_processing.progress == 0.0
        assert refreshed_processing.overall_progress == 0.0
        assert refreshed_processing.message == "Requeued after server shutdown"
        assert refreshed_processing.error is None

        assert refreshed_post_processing.status == JobStatus.POST_PROCESSING
        assert refreshed_post_processing.message == "Finishing outputs"

        assert refreshed_completed.status == JobStatus.COMPLETED
        assert refreshed_completed.progress == 100.0
        assert refreshed_completed.overall_progress == 100.0
        assert refreshed_completed.message == "Done"

    def test_requeue_inflight_jobs_for_shutdown_when_empty(self, session, monkeypatch):
        monkeypatch.setattr("api.lifecycle.get_session_sync", lambda: session)

        count = _requeue_inflight_jobs_for_shutdown()

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
        monkeypatch.setattr("api.job_processing.finalize_persisted_job_outputs", finalize_mock)

        recovered = await recover_post_processing_jobs()

        assert recovered == 1
        finalize_mock.assert_awaited_once()
        assert finalize_mock.await_args.kwargs["job_id"] == job_id
        assert finalize_mock.await_args.kwargs["provider_id"] == "provider-a"
