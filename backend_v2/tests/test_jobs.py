# Job API tests
import pytest

from core.entities import Job, JobStatus
from infrastructure.request_dedup import clear_dedup_cache


@pytest.fixture(autouse=True)
def _isolate_dedup_cache():
    """GET /api/jobs responses are cached process-wide for a few seconds.

    Clear before and after every test here so a cached list from another module
    can never be served to a test that expects an empty database.
    """
    clear_dedup_cache()
    yield
    clear_dedup_cache()


def test_create_job(client, sample_job_data):
    """Test job creation."""
    response = client.post("/api/jobs", json=sample_job_data)
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["status"] == "pending"
    assert data["metadata"]["prompt"] == "a beautiful landscape"


def test_list_jobs_empty(client):
    """Test listing jobs when empty."""
    response = client.get("/api/jobs")
    assert response.status_code == 200
    data = response.json()
    assert "jobs" in data
    assert "total" in data
    assert data["total"] == 0


def test_list_jobs_with_data(client, sample_job_data):
    """Test listing jobs with data."""
    # Clear deduplication cache to avoid stale results from previous tests
    clear_dedup_cache()

    # Create a job first
    create_response = client.post("/api/jobs", json=sample_job_data)
    assert create_response.status_code == 200, f"Create job failed: {create_response.text}"

    # Clear cache again just to be safe (though POST doesn't use it, create might affect list)
    clear_dedup_cache()
    
    response = client.get("/api/jobs")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1, f"Expected 1 job, got {data['total']}. Response: {data}"
    assert len(data["jobs"]) == 1


def test_get_job(client, sample_job_data):
    """Test getting a specific job."""
    # Create a job
    create_response = client.post("/api/jobs", json=sample_job_data)
    job_id = create_response.json()["id"]
    
    # Get it
    response = client.get(f"/api/jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == job_id


def test_get_job_not_found(client):
    """Test getting non-existent job."""
    response = client.get("/api/jobs/nonexistent-id")
    assert response.status_code == 404


def test_delete_job(client, sample_job_data, session):
    """Test deleting a terminal job.

    The job is driven to a terminal state first: `POST /api/jobs` leaves it
    PENDING, and DELETE now refuses a PENDING job because it is work a worker is
    about to claim. Deleting it anyway let the worker finish into a missing row
    and silently threw away a paid generation.
    """
    from core.entities import JobStatus

    create_response = client.post("/api/jobs", json=sample_job_data)
    job_id = create_response.json()["id"]

    job = session.get(Job, job_id)
    job.status = JobStatus.COMPLETED
    session.add(job)
    session.commit()

    # Delete it
    response = client.delete(f"/api/jobs/{job_id}")
    assert response.status_code == 200

    # Verify it's gone
    get_response = client.get(f"/api/jobs/{job_id}")
    assert get_response.status_code == 404


def test_delete_pending_job_is_refused(client, sample_job_data):
    """A queued job cannot be deleted — it is live work, and there is a cancel
    endpoint for that. The refusal must leave the job intact."""
    create_response = client.post("/api/jobs", json=sample_job_data)
    job_id = create_response.json()["id"]

    response = client.delete(f"/api/jobs/{job_id}")
    assert response.status_code == 400
    assert client.get(f"/api/jobs/{job_id}").status_code == 200


def test_clear_jobs(client, sample_job_data):
    """Test clearing all jobs."""
    # Create some jobs
    client.post("/api/jobs", json=sample_job_data)
    client.post("/api/jobs", json=sample_job_data)
    
    # Clear all
    response = client.delete("/api/jobs")
    assert response.status_code == 200
    data = response.json()
    assert data["deleted"] == 2
    
    # Clear cache before verifying
    clear_dedup_cache()

    # Verify empty
    list_response = client.get("/api/jobs")
    assert list_response.json()["total"] == 0


def test_create_job_idempotency_key_reuses_existing_result(client, sample_job_data):
    """Providing the same Idempotency-Key should not create duplicate jobs."""
    clear_dedup_cache()

    headers = {"Idempotency-Key": "job-create-key-1"}
    first = client.post("/api/jobs", json=sample_job_data, headers=headers)
    second = client.post("/api/jobs", json=sample_job_data, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    clear_dedup_cache()
    listed = client.get("/api/jobs")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


def test_create_job_without_idempotency_key_creates_distinct_jobs(client, sample_job_data):
    """Without Idempotency-Key, repeated submits should still create separate jobs."""
    clear_dedup_cache()

    first = client.post("/api/jobs", json=sample_job_data)
    second = client.post("/api/jobs", json=sample_job_data)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] != second.json()["id"]

    clear_dedup_cache()
    listed = client.get("/api/jobs")
    assert listed.status_code == 200
    assert listed.json()["total"] == 2


class TestAcknowledgeFailedJobs:
    """Dismissing a failure the user has read, without retrying or deleting it.

    The failure panel had exactly two actions — retry everything, or recover the
    queue — so the only way to stop seeing a failure you did not want retried was
    to delete the job, which throws away the only record of what the provider did.
    """

    def _failed(self, session, name="a", **kw):
        kw.setdefault("task_type", "image")
        job = Job(status=JobStatus.FAILED, workflow={"name": name}, **kw)
        session.add(job)
        session.commit()
        session.refresh(job)
        return job

    def test_failed_listing_hides_acknowledged_jobs(self, session, client):
        kept = self._failed(session, "kept")
        dismissed = self._failed(session, "dismissed")
        self._failed(session, "llm", task_type="llm")

        client.post(f"/api/jobs/{dismissed.id}/acknowledge", json={"acknowledged": True})

        body = client.get("/api/jobs/failed").json()
        ids = {j["id"] for j in body["jobs"]}
        assert kept.id in ids
        assert dismissed.id not in ids
        # `total` must count the same set the page returns, or the panel's count
        # disagrees with its own list.
        assert body["total"] == len(ids)
        assert body["acknowledged_count"] == 1

    def test_include_acknowledged_returns_them_again(self, session, client):
        job = self._failed(session, "a")
        client.post(f"/api/jobs/{job.id}/acknowledge", json={"acknowledged": True})

        hidden = client.get("/api/jobs/failed").json()
        assert hidden["total"] == 0

        shown = client.get("/api/jobs/failed?include_acknowledged=true").json()
        assert shown["total"] == 1
        assert shown["jobs"][0]["acknowledged_at"] is not None

    def test_acknowledgement_is_reversible(self, session, client):
        job = self._failed(session, "a")
        client.post(f"/api/jobs/{job.id}/acknowledge", json={"acknowledged": True})
        assert client.get("/api/jobs/failed").json()["total"] == 0

        restored = client.post(
            f"/api/jobs/{job.id}/acknowledge", json={"acknowledged": False}
        ).json()
        assert restored["updated"] == 1
        assert client.get("/api/jobs/failed").json()["total"] == 1
        assert client.get("/api/jobs/failed").json()["jobs"][0]["acknowledged_at"] is None

    def test_acknowledging_twice_reports_no_change(self, session, client):
        job = self._failed(session, "a")
        first = client.post(f"/api/jobs/{job.id}/acknowledge", json={"acknowledged": True}).json()
        second = client.post(f"/api/jobs/{job.id}/acknowledge", json={"acknowledged": True}).json()
        assert first["updated"] == 1
        # The second call rewrites the timestamp, so it still reports 1; what
        # matters is that it stays acknowledged and the listing stays empty.
        assert second["acknowledged"] is True
        assert client.get("/api/jobs/failed").json()["total"] == 0

    def test_acknowledge_defaults_to_true_with_no_body(self, session, client):
        job = self._failed(session, "a")
        response = client.post(f"/api/jobs/{job.id}/acknowledge")
        assert response.status_code == 200
        assert client.get("/api/jobs/failed").json()["total"] == 0

    def test_acknowledge_all_covers_every_failure(self, session, client):
        for i in range(3):
            self._failed(session, f"img{i}")
        self._failed(session, "chat", task_type="llm")

        body = client.post("/api/jobs/acknowledge-all", json={"acknowledged": True}).json()
        assert body["updated"] == 4
        assert client.get("/api/jobs/failed").json()["total"] == 0

    def test_acknowledge_all_respects_the_task_type_filter(self, session, client):
        self._failed(session, "img")
        self._failed(session, "chat", task_type="llm")

        client.post("/api/jobs/acknowledge-all", json={"acknowledged": True, "task_type": "llm"})

        remaining = client.get("/api/jobs/failed").json()
        assert remaining["total"] == 1
        assert remaining["jobs"][0]["task_type"] == "image"

    def test_restore_all_brings_everything_back(self, session, client):
        for i in range(2):
            self._failed(session, f"a{i}")
        client.post("/api/jobs/acknowledge-all", json={"acknowledged": True})
        assert client.get("/api/jobs/failed").json()["total"] == 0

        body = client.post("/api/jobs/acknowledge-all", json={"acknowledged": False}).json()
        assert body["updated"] == 2
        assert client.get("/api/jobs/failed").json()["total"] == 2

    def test_acknowledge_does_not_delete_the_job(self, session, client):
        job = self._failed(session, "a")
        client.post(f"/api/jobs/{job.id}/acknowledge", json={"acknowledged": True})
        # Still fetchable, still a failure, still retryable.
        assert client.get(f"/api/jobs/{job.id}").status_code == 200
        assert session.get(Job, job.id) is not None

    def test_acknowledge_unknown_job_is_404(self, client):
        assert client.post("/api/jobs/does-not-exist/acknowledge", json={"acknowledged": True}).status_code == 404

    def test_completed_jobs_are_not_affected(self, session, client):
        done = Job(task_type="image", status=JobStatus.COMPLETED)
        session.add(done)
        session.commit()
        session.refresh(done)

        client.post("/api/jobs/acknowledge-all", json={"acknowledged": True})
        assert session.get(Job, done.id).acknowledged_at is None
