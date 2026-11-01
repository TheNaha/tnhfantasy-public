"""Tests for job recovery/diagnostics: attempt history, failure kinds, retry
transition, cancellation and stale-job recovery."""
from datetime import datetime, timedelta, timezone

import pytest

from core.entities import Job, JobStatus
from core.events import EventType
from services.job_service import (
    FAILURE_FINALIZATION,
    FAILURE_NO_PROVIDERS,
    FAILURE_PROVIDER_ERROR,
    FAILURE_STALE,
    FAILURE_TIMEOUT,
    FAILURE_UNKNOWN,
    FAILURE_UNEXPECTED,
    JOB_DIAGNOSTICS_KEY,
    MAX_TRACKED_ATTEMPTS,
    STALE_JOB_ERROR,
    JobService,
    build_job_diagnostics,
    classify_job_error,
    is_job_retryable,
)


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


class TestDiagnostics:
    def test_job_dict_exposes_diagnostics_block(self, session):
        service = JobService(session)
        job = make_job(session, status=JobStatus.FAILED, error="All providers failed: p1")

        payload = service._job_to_dict(job)

        diagnostics = payload["diagnostics"]
        assert diagnostics["error_type"] == "providers_exhausted"
        assert diagnostics["error_message"] == "All providers failed: p1"
        assert diagnostics["model"] == "dreamshaper.safetensors"
        assert diagnostics["is_retryable"] is True
        assert diagnostics["attempt_count"] == 0

    def test_diagnostics_reports_model_from_alternate_metadata_keys(self):
        job = Job(task_type="llm", metadata_={"llm_model": "gpt-4o-mini"})
        assert build_job_diagnostics(job)["model"] == "gpt-4o-mini"

    def test_diagnostics_tolerates_job_without_metadata(self):
        job = Job(task_type="image", metadata_=None)
        diagnostics = build_job_diagnostics(job)
        assert diagnostics["model"] is None
        assert diagnostics["attempts"] == []

    def test_duration_uses_started_and_completed_timestamps(self):
        start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        job = Job(
            status=JobStatus.COMPLETED,
            started_at=start,
            completed_at=start + timedelta(seconds=12, milliseconds=500),
        )
        assert build_job_diagnostics(job)["duration_seconds"] == 12.5

    def test_duration_handles_naive_timestamps_from_database(self):
        """Columns are naive, so mixed naive/aware arithmetic must not raise."""
        start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        job = Job(
            status=JobStatus.FAILED,
            started_at=start,
            completed_at=start + timedelta(seconds=3),
        )
        assert build_job_diagnostics(job)["duration_seconds"] == 3.0

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            (None, None),
            ("", None),
            ("No available providers", FAILURE_NO_PROVIDERS),
            ("All providers failed: p1, p2", "providers_exhausted"),
            ("Provider timed out", FAILURE_TIMEOUT),
            (STALE_JOB_ERROR, FAILURE_STALE),
            ("something odd happened", FAILURE_UNKNOWN),
        ],
    )
    def test_classify_job_error(self, message, expected):
        assert classify_job_error(message) == expected

    def test_retryable_requires_failed_status_and_workflow(self):
        assert is_job_retryable(Job(status=JobStatus.FAILED, workflow={"nodes": {}})) is True
        assert is_job_retryable(Job(status=JobStatus.FAILED, workflow={})) is False
        assert is_job_retryable(Job(status=JobStatus.CANCELLED, workflow={"nodes": {}})) is False


class TestAttemptHistory:
    @pytest.mark.asyncio
    async def test_record_attempt_appends_history(self, session):
        service = JobService(session)
        job = make_job(session)

        await service.record_attempt(
            job.id, provider_id="p1", attempt=1, outcome="error", error="OutOfMemory", duration_seconds=1.5
        )
        await service.record_attempt(
            job.id, provider_id="p1", attempt=2, outcome="completed", duration_seconds=9.0
        )

        diagnostics = build_job_diagnostics(service.repo.get(job.id))
        assert diagnostics["attempt_count"] == 2
        assert diagnostics["last_provider_id"] == "p1"
        assert diagnostics["last_outcome"] == "completed"
        assert [a["outcome"] for a in diagnostics["attempts"]] == ["error", "completed"]
        assert diagnostics["attempts"][0]["error"] == "OutOfMemory"
        assert diagnostics["attempts"][1]["error"] is None
        assert diagnostics["error_type"] == FAILURE_PROVIDER_ERROR

    @pytest.mark.asyncio
    async def test_record_attempt_caps_history_length(self, session):
        service = JobService(session)
        job = make_job(session)

        for index in range(MAX_TRACKED_ATTEMPTS + 5):
            await service.record_attempt(
                job.id, provider_id=f"p{index}", attempt=index, outcome="error"
            )

        diagnostics = build_job_diagnostics(service.repo.get(job.id))
        assert len(diagnostics["attempts"]) == MAX_TRACKED_ATTEMPTS
        # The counter keeps the true total even though history is trimmed.
        assert diagnostics["attempt_count"] == MAX_TRACKED_ATTEMPTS + 5
        assert diagnostics["attempts"][-1]["provider_id"] == f"p{MAX_TRACKED_ATTEMPTS + 4}"

    @pytest.mark.asyncio
    async def test_record_attempt_truncates_long_errors(self, session):
        service = JobService(session)
        job = make_job(session)

        await service.record_attempt(
            job.id, provider_id="p1", attempt=1, outcome="error", error="x" * 5000
        )

        attempt = build_job_diagnostics(service.repo.get(job.id))["attempts"][0]
        assert len(attempt["error"]) == 500

    @pytest.mark.asyncio
    async def test_record_attempt_on_missing_job_returns_none(self, session):
        service = JobService(session)
        assert await service.record_attempt(
            "nope", provider_id="p1", attempt=1, outcome="error"
        ) is None

    @pytest.mark.asyncio
    async def test_failed_transition_records_classified_cause(self, session):
        service = JobService(session)
        job = make_job(session)

        await service.update_job(
            job.id, status=JobStatus.SENT_TO_PROVIDER, provider_id="p1"
        )
        await service.update_job(
            job.id, status=JobStatus.FAILED, error="No available providers"
        )

        diagnostics = build_job_diagnostics(service.repo.get(job.id))
        assert diagnostics["error_type"] == FAILURE_NO_PROVIDERS
        assert diagnostics["is_retryable"] is True

    @pytest.mark.asyncio
    async def test_explicit_failure_kind_is_not_overwritten(self, session):
        """A caller-supplied diagnostics block wins over message classification."""
        service = JobService(session)
        job = make_job(session, status=JobStatus.GENERATING)

        await service.mark_failed(
            job.id, error="No available providers", error_type=FAILURE_FINALIZATION
        )

        diagnostics = build_job_diagnostics(service.repo.get(job.id))
        assert diagnostics["error_type"] == FAILURE_FINALIZATION

    @pytest.mark.asyncio
    async def test_mark_failed_records_explicit_cause(self, session):
        service = JobService(session)
        job = make_job(session, status=JobStatus.POST_PROCESSING)

        await service.mark_failed(
            job.id, error="reconcile blew up", error_type=FAILURE_FINALIZATION
        )

        diagnostics = build_job_diagnostics(service.repo.get(job.id))
        assert diagnostics["error_type"] == FAILURE_FINALIZATION
        assert diagnostics["error_message"] == "reconcile blew up"

    @pytest.mark.asyncio
    async def test_mark_failed_emits_failed_event(self, session, monkeypatch):
        from services import job_service as job_service_module

        events = []

        async def fake_emit(event_type, payload):
            events.append((event_type, payload))

        monkeypatch.setattr(job_service_module, "emit_job_event", fake_emit)

        service = JobService(session)
        job = make_job(session, status=JobStatus.GENERATING)
        await service.mark_failed(job.id, error="boom", error_type=FAILURE_UNEXPECTED)

        assert len(events) == 1
        assert events[0][0] == EventType.JOB_FAILED
        assert events[0][1]["diagnostics"]["error_type"] == FAILURE_UNEXPECTED


class TestStaleRecovery:
    @pytest.mark.asyncio
    async def test_fails_jobs_wedged_past_timeout(self, session):
        service = JobService(session)
        old_started = datetime.now(timezone.utc) - timedelta(seconds=600)
        stuck = make_job(session, status=JobStatus.GENERATING, started_at=old_started)
        healthy = make_job(
            session, status=JobStatus.GENERATING, started_at=datetime.now(timezone.utc)
        )

        failed = await service.fail_stale_running_jobs(timeout_seconds=300)

        assert [job.id for job in failed] == [stuck.id]
        refreshed = service.repo.get(stuck.id)
        assert refreshed.status == JobStatus.FAILED
        assert refreshed.error == STALE_JOB_ERROR
        assert refreshed.completed_at is not None
        diagnostics = build_job_diagnostics(refreshed)
        assert diagnostics["error_type"] == FAILURE_STALE
        assert diagnostics["is_stale"] is True
        assert diagnostics["stale_seconds"] >= 600
        # The healthy job is untouched.
        assert service.repo.get(healthy.id).status == JobStatus.GENERATING

    @pytest.mark.asyncio
    async def test_handles_naive_started_at_from_database(self, session):
        """Naive timestamps must not raise TypeError during recovery."""
        service = JobService(session)
        naive_started = datetime.now(timezone.utc) - timedelta(seconds=900)
        job = make_job(session, status=JobStatus.SENT_TO_PROVIDER, started_at=naive_started)

        failed = await service.fail_stale_running_jobs(timeout_seconds=300)

        assert [j.id for j in failed] == [job.id]
        assert service.repo.get(job.id).status == JobStatus.FAILED

    @pytest.mark.asyncio
    async def test_leaves_jobs_without_started_at_alone(self, session):
        """A job picked up but never stamped with started_at is not yet stale."""
        service = JobService(session)
        job = make_job(session, status=JobStatus.SENT_TO_PROVIDER, started_at=None)

        assert await service.fail_stale_running_jobs(timeout_seconds=300) == []
        assert service.repo.get(job.id).status == JobStatus.SENT_TO_PROVIDER

    @pytest.mark.asyncio
    async def test_queue_manager_recover_reports_summary(self, session):
        from services.job_queue import QueueManager

        service = JobService(session)
        stuck = make_job(
            session,
            status=JobStatus.GENERATING,
            started_at=datetime.now(timezone.utc) - timedelta(seconds=900),
        )
        waiting = make_job(session, status=JobStatus.PENDING)

        manager = QueueManager()
        summary = await manager.recover(service, timeout_seconds=300)

        assert summary["failed"] == 1
        assert summary["failed_job_ids"] == [stuck.id]
        # Pending work is re-queued in in-memory mode.
        assert summary["recovered"] >= 1
        assert waiting.id in {job_id for job_id in _queued_ids(manager)}
        assert summary["mode"] == "in_memory"


def _queued_ids(manager) -> set[str]:
    ids: set[str] = set()
    for queue in (manager.image, manager.llm):
        while True:
            try:
                job_id, _provider_id = queue._queue.get_nowait()
            except Exception:
                break
            ids.add(job_id)
    return ids


class TestFailedJobListing:
    @pytest.mark.asyncio
    async def test_lists_failed_jobs_with_diagnostics_and_summary(self, session):
        service = JobService(session)
        make_job(session, status=JobStatus.FAILED, error="No available providers", provider_id="p1")
        make_job(session, status=JobStatus.FAILED, error="Provider timed out", provider_id="p2")
        make_job(session, status=JobStatus.COMPLETED)

        jobs, total = await service.get_failed_jobs()

        assert total == 2
        assert len(jobs) == 2
        assert {job["diagnostics"]["error_type"] for job in jobs} == {
            FAILURE_NO_PROVIDERS,
            FAILURE_TIMEOUT,
        }

        summary = service.summarize_failed_jobs(jobs)
        assert summary["by_error_type"] == {FAILURE_NO_PROVIDERS: 1, FAILURE_TIMEOUT: 1}
        assert summary["by_provider"] == {"p1": 1, "p2": 1}
        assert summary["by_task_type"] == {"image": 2}
        assert summary["retryable"] == 2

    @pytest.mark.asyncio
    async def test_filters_failed_jobs_by_task_type(self, session):
        service = JobService(session)
        make_job(session, status=JobStatus.FAILED, task_type="image")
        make_job(session, status=JobStatus.FAILED, task_type="llm")

        jobs, total = await service.get_failed_jobs(task_type="llm")

        assert total == 1
        assert jobs[0]["task_type"] == "llm"

    @pytest.mark.asyncio
    async def test_summary_counts_unknown_error_type(self, session):
        service = JobService(session)
        make_job(session, status=JobStatus.FAILED, error="mystery")

        jobs, _total = await service.get_failed_jobs()

        summary = service.summarize_failed_jobs(jobs)
        assert summary["by_error_type"] == {FAILURE_UNKNOWN: 1}
        assert summary["by_provider"] == {"(unassigned)": 1}
        assert jobs[0]["diagnostics"]["failure_kind"] is None


class TestCancelJob:
    @pytest.mark.asyncio
    async def test_cancels_pending_job(self, session):

        service = JobService(session)
        job = make_job(session, status=JobStatus.PENDING)

        cancelled = await service.cancel_job(job.id)

        assert cancelled.status == JobStatus.CANCELLED
        assert cancelled.message == "Cancelled by user"

    @pytest.mark.asyncio
    async def test_cancels_in_flight_job(self, session):
        service = JobService(session)
        job = make_job(session, status=JobStatus.GENERATING)

        cancelled = await service.cancel_job(job.id, reason="user stopped it")

        assert cancelled.status == JobStatus.CANCELLED
        assert cancelled.message == "user stopped it"

    @pytest.mark.asyncio
    async def test_rejects_cancel_of_terminal_jobs(self, session):
        from core.exceptions import ValidationError

        service = JobService(session)
        for status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            job = make_job(session, status=status)
            with pytest.raises(ValidationError):
                await service.cancel_job(job.id)

    @pytest.mark.asyncio
    async def test_cancel_unknown_job_raises_not_found(self, session):
        from core.exceptions import NotFoundError

        service = JobService(session)
        with pytest.raises(NotFoundError):
            await service.cancel_job("missing")


class TestCancelJobProcessing:
    @pytest.mark.asyncio
    async def test_cancel_marks_job_cancelled_and_reports_provider(self, session, monkeypatch):
        from services import job_processing

        signalled = {}

        async def fake_signal(*, runtime, provider_id, job_id):
            signalled["provider_id"] = provider_id
            signalled["job_id"] = job_id
            return True

        monkeypatch.setattr(job_processing, "logger", job_processing.logger)
        monkeypatch.setattr("services.job_runner.signal_provider_cancellation", fake_signal)

        class StubProviderService:
            def __init__(self, _session):
                pass

            async def get_provider(self, provider_id):
                return type("P", (), {"id": provider_id})()

        monkeypatch.setattr("services.provider_service.ProviderService", StubProviderService)
        monkeypatch.setattr(
            "services.provider_runtime.resolve_provider_runtime",
            lambda provider: type("R", (), {"mode": "container_http", "worker_url": "http://x"})(),
        )

        service = JobService(session)
        job = make_job(session, status=JobStatus.GENERATING, provider_id="p1")

        result = await job_processing.cancel_job(job_service=service, job_id=job.id)

        assert result["job_status"] == "cancelled"
        assert result["provider_signalled"] is True
        assert signalled["provider_id"] == "p1"
        assert service.repo.get(job.id).status == JobStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_still_succeeds_when_provider_signal_fails(self, session, monkeypatch):
        from services import job_processing

        class BrokenProviderService:
            def __init__(self, _session):
                pass

            async def get_provider(self, provider_id):
                raise RuntimeError("provider record gone")

        monkeypatch.setattr("services.provider_service.ProviderService", BrokenProviderService)

        service = JobService(session)
        job = make_job(session, status=JobStatus.PENDING, provider_id="p1")

        result = await job_processing.cancel_job(job_service=service, job_id=job.id)

        assert result["provider_signalled"] is False
        assert service.repo.get(job.id).status == JobStatus.CANCELLED


class TestAttemptTracking:
    @pytest.mark.asyncio
    async def test_track_attempt_records_outcome_and_duration(self, session):
        from services.job_runner import track_attempt

        service = JobService(session)
        job = make_job(session)

        record = track_attempt(service, job.id, provider_id="p1", attempt=1)
        await record("timeout", "provider hung")

        attempt = build_job_diagnostics(service.repo.get(job.id))["attempts"][0]
        assert attempt["outcome"] == "timeout"
        assert attempt["error"] == "provider hung"
        assert attempt["duration_seconds"] >= 0
        assert attempt["provider_id"] == "p1"
        assert attempt["attempt"] == 1

    @pytest.mark.asyncio
    async def test_track_attempt_swallows_record_failures(self, session):
        from services.job_runner import track_attempt

        class BrokenService:
            async def record_attempt(self, *args, **kwargs):
                raise RuntimeError("db down")

        record = track_attempt(BrokenService(), "job-1", provider_id="p1", attempt=1)
        await record("completed")

    @pytest.mark.asyncio
    async def test_diagnostics_metadata_key_is_reserved(self, session):
        service = JobService(session)
        job = make_job(session)
        await service.record_attempt(job.id, provider_id="p1", attempt=1, outcome="error")

        stored = service.repo.get(job.id).metadata_
        assert JOB_DIAGNOSTICS_KEY in stored
        # The user-facing metadata is otherwise untouched.
        assert stored["prompt"] == "a cat"
