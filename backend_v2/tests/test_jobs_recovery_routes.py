"""Route tests for the job recovery/diagnostics endpoints:
GET /api/jobs/failed, GET /api/jobs/{id}/diagnostics,
POST /api/jobs/recover, POST /api/jobs/{id}/cancel and the hardened retry."""
from datetime import datetime, timedelta, timezone

import pytest

from core.entities import Job, JobStatus
from core.events import EventType
from infrastructure.request_dedup import clear_dedup_cache


@pytest.fixture(autouse=True)
def _isolate_dedup_cache():
    """GET /api/jobs responses are cached process-wide for a few seconds.

    Clear before and after this module so its requests can never be served to
    (or poison) another test module running against a different database.
    """
    clear_dedup_cache()
    yield
    clear_dedup_cache()


def make_job(session, **overrides) -> Job:
    job = Job(
        task_type=overrides.pop("task_type", "image"),
        workflow=overrides.pop("workflow", {"nodes": {"1": {"class_type": "KSampler"}}}),
        metadata_=overrides.pop("metadata_", {"prompt": "a cat", "checkpoint": "dreamshaper.safetensors"}),
    )
    for key, value in overrides.items():
        setattr(job, key, value)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


class TestFailedJobsEndpoint:
    def test_lists_failed_jobs_with_diagnostics(self, client, session):
        make_job(session, status=JobStatus.FAILED, error="No available providers", provider_id="p1")
        make_job(session, status=JobStatus.GENERATING)

        response = client.get("/api/jobs/failed")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        job = data["jobs"][0]
        assert job["diagnostics"]["error_type"] == "no_providers"
        assert job["diagnostics"]["is_retryable"] is True
        assert job["diagnostics"]["model"] == "dreamshaper.safetensors"
        assert data["summary"]["by_error_type"] == {"no_providers": 1}
        assert data["summary"]["retryable"] == 1

    def test_empty_when_no_failures(self, client):
        response = client.get("/api/jobs/failed")

        assert response.status_code == 200
        assert response.json() == {
            "jobs": [],
            "total": 0,
            "limit": 25,
            "offset": 0,
            # How many failures are hidden because the user dismissed them. Zero
            # here; the failure panel uses it to offer a way back.
            "acknowledged_count": 0,
            "summary": {
                "by_error_type": {},
                "by_provider": {},
                "by_task_type": {},
                "retryable": 0,
            },
        }

    def test_clamps_limit_and_offset(self, client, session):
        make_job(session, status=JobStatus.FAILED, error="boom")

        response = client.get("/api/jobs/failed?limit=9999&offset=-5")

        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 100
        assert data["offset"] == 0

    def test_filters_by_task_type(self, client, session):
        make_job(session, status=JobStatus.FAILED, error="boom", task_type="llm")
        make_job(session, status=JobStatus.FAILED, error="boom", task_type="image")

        response = client.get("/api/jobs/failed?task_type=llm")

        assert response.json()["total"] == 1
        assert response.json()["jobs"][0]["task_type"] == "llm"


class TestJobDiagnosticsEndpoint:
    def test_returns_attempt_history(self, client, session):
        job = make_job(session, status=JobStatus.SENT_TO_PROVIDER)
        client.post(f"/api/jobs/{job.id}/retry")  # 400: not failed yet

        from services.job_service import JobService

        service = JobService(session)
        job.status = JobStatus.FAILED
        session.add(job)
        session.commit()

        import asyncio

        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            service.record_attempt(job.id, provider_id="p1", attempt=1, outcome="error", error="OOM")
        )

        response = client.get(f"/api/jobs/{job.id}/diagnostics")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == job.id
        assert data["attempts"][0]["provider_id"] == "p1"
        assert data["attempts"][0]["error"] == "OOM"
        assert data["diagnostics"]["attempt_count"] == 1

    def test_unknown_job_returns_404(self, client):
        assert client.get("/api/jobs/nope/diagnostics").status_code == 404


class TestRecoverEndpoint:
    def test_fails_stale_jobs_and_reports_summary(self, client, session):
        """`force=true` fails the stale jobs.

        The window is given explicitly, because the default is now each
        job's own task-type timeout - and the image timeout is 3600s, so a
        1200-second-old job is NOT stale by default.
        """
        stuck = make_job(
            session,
            status=JobStatus.GENERATING,
            started_at=datetime.now(timezone.utc) - timedelta(seconds=1200),
        )
        make_job(session, status=JobStatus.PENDING)

        response = client.post("/api/jobs/recover?force=true&timeout_seconds=600")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["failed"] == 1
        assert data["failed_job_ids"] == [stuck.id]

        refreshed = session.get(Job, stuck.id)
        assert refreshed.status == JobStatus.FAILED
        assert refreshed.error is not None

    def test_the_default_does_not_fail_a_job_that_is_within_its_timeout(
        self, client, session
    ):
        """A 1200-second-old image job is inside the 3600-second image timeout.

        The old global window was 300 seconds, so the dashboard's "Recover"
        button failed every generation still running after five minutes.
        """
        running = make_job(
            session,
            status=JobStatus.GENERATING,
            started_at=datetime.now(timezone.utc) - timedelta(seconds=1200),
        )

        response = client.post("/api/jobs/recover?force=true")

        assert response.status_code == 200
        data = response.json()
        assert data["failed"] == 0
        assert session.get(Job, running.id).status == JobStatus.GENERATING

    def test_is_safe_with_nothing_to_recover(self, client):
        response = client.post("/api/jobs/recover")

        assert response.status_code == 200
        data = response.json()
        assert data["recovered"] == 0
        assert data["failed"] == 0

    def test_clamps_timeout(self, client, session):
        response = client.post("/api/jobs/recover?timeout_seconds=1")

        # Below the 30s floor the request is clamped rather than rejected.
        assert response.status_code == 200
        assert "failed" in response.json()


class TestCancelEndpoint:
    def test_cancels_pending_job(self, client, session):
        job = make_job(session, status=JobStatus.PENDING)

        response = client.post(f"/api/jobs/{job.id}/cancel")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["job_status"] == "cancelled"
        assert data["provider_signalled"] is False
        assert session.get(Job, job.id).status == JobStatus.CANCELLED

    def test_accepts_custom_reason(self, client, session):
        job = make_job(session, status=JobStatus.GENERATING)

        response = client.post(
            f"/api/jobs/{job.id}/cancel", json={"reason": "user stopped it"}
        )

        assert response.status_code == 200
        assert session.get(Job, job.id).message == "user stopped it"

    def test_rejects_terminal_job(self, client, session):
        job = make_job(session, status=JobStatus.COMPLETED)

        response = client.post(f"/api/jobs/{job.id}/cancel")

        assert response.status_code == 400

    def test_unknown_job_returns_404(self, client):
        assert client.post("/api/jobs/nope/cancel").status_code == 404


class TestRetryEndpoint:
    def test_retry_links_new_job_to_original(self, client, session):
        original = make_job(session, status=JobStatus.FAILED, error="Provider timed out")

        response = client.post(f"/api/jobs/{original.id}/retry")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["new_job_id"] != original.id
        assert data["new_job"]["diagnostics"]["retry_of"] == original.id
        # The retried job is itself retryable bookkeeping-wise and queued.
        assert session.get(Job, data["new_job_id"]).status == JobStatus.PENDING

    def test_retry_drops_stale_preferred_provider_by_default(self, client, session):
        original = make_job(
            session,
            status=JobStatus.FAILED,
            metadata_={"prompt": "x", "preferred_provider_id": "dead-provider"},
        )

        response = client.post(f"/api/jobs/{original.id}/retry")

        assert response.status_code == 200
        new_job = session.get(Job, response.json()["new_job_id"])
        assert "preferred_provider_id" not in new_job.metadata_
        assert new_job.metadata_["prompt"] == "x"

    def test_retry_can_keep_provider(self, client, session):
        original = make_job(
            session,
            status=JobStatus.FAILED,
            metadata_={"prompt": "x", "preferred_provider_id": "sticky-provider"},
        )

        response = client.post(
            f"/api/jobs/{original.id}/retry", json={"keep_provider": True}
        )

        assert response.status_code == 200
        new_job = session.get(Job, response.json()["new_job_id"])
        assert new_job.metadata_["preferred_provider_id"] == "sticky-provider"

    def test_retry_rejects_non_failed_job(self, client, session):
        job = make_job(session, status=JobStatus.PENDING)

        response = client.post(f"/api/jobs/{job.id}/retry")

        assert response.status_code == 400

    def test_retry_rejects_job_without_workflow(self, client, session):
        job = make_job(session, status=JobStatus.FAILED, workflow={})

        response = client.post(f"/api/jobs/{job.id}/retry")

        assert response.status_code == 400

    def test_retry_unknown_job_returns_404(self, client):
        assert client.post("/api/jobs/nope/retry").status_code == 404


class TestJobPayloadDiagnostics:
    def test_get_job_includes_diagnostics(self, client, session):
        job = make_job(session, status=JobStatus.FAILED, error="boom")

        response = client.get(f"/api/jobs/{job.id}")

        assert response.status_code == 200
        assert "diagnostics" in response.json()
        assert response.json()["diagnostics"]["error_message"] == "boom"

    def test_list_jobs_includes_diagnostics(self, client, session):
        make_job(session, status=JobStatus.PENDING)

        response = client.get("/api/jobs")

        assert response.status_code == 200
        assert "diagnostics" in response.json()["jobs"][0]

    def test_active_jobs_include_diagnostics(self, client, session):
        make_job(session, status=JobStatus.PENDING)

        response = client.get("/api/jobs/active")

        assert response.status_code == 200
        assert "diagnostics" in response.json()["jobs"][0]

    def test_failed_event_payload_carries_diagnostics(self, client, session, monkeypatch):
        """The WS JOB_FAILED payload (used by the UI) includes diagnostics."""
        from services import job_service as job_service_module
        from services.job_service import JobService

        events = []

        async def fake_emit(event_type, payload):
            events.append((event_type, payload))

        monkeypatch.setattr(job_service_module, "emit_job_event", fake_emit)

        import asyncio

        job = make_job(session, status=JobStatus.GENERATING, provider_id="p1")
        service = JobService(session)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                service.mark_failed(job.id, error="All providers failed: p1")
            )
        finally:
            loop.close()

        assert events[0][0] == EventType.JOB_FAILED
        assert events[0][1]["diagnostics"]["error_type"] == "providers_exhausted"
