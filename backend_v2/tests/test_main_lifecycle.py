from datetime import datetime

from core.entities import Job, JobStatus
from api.main import _requeue_inflight_jobs_for_shutdown


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
        session.add(completed_job)
        session.commit()

        running_job_id = running_job.id
        processing_job_id = processing_job.id
        completed_job_id = completed_job.id

        monkeypatch.setattr("api.lifecycle.get_session_sync", lambda: session)

        count = _requeue_inflight_jobs_for_shutdown()

        refreshed_running = session.get(Job, running_job_id)
        refreshed_processing = session.get(Job, processing_job_id)
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

        assert refreshed_completed.status == JobStatus.COMPLETED
        assert refreshed_completed.progress == 100.0
        assert refreshed_completed.overall_progress == 100.0
        assert refreshed_completed.message == "Done"

    def test_requeue_inflight_jobs_for_shutdown_when_empty(self, session, monkeypatch):
        monkeypatch.setattr("api.lifecycle.get_session_sync", lambda: session)

        count = _requeue_inflight_jobs_for_shutdown()

        assert count == 0
