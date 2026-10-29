"""Tests for job.metadata_['boot_seconds'] stamping (P1, every transport)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest

from core.entities import Job, JobStatus
from services import job_boot_metrics as jbm
from services.job_boot_metrics import stamp_boot_seconds


@pytest.fixture(autouse=True)
def _reset_guard():
    jbm._boot_stamped.clear()
    yield
    jbm._boot_stamped.clear()


def _make_job(boot_seconds_meta=None, started_offset=3.0):
    started_at = datetime.now(timezone.utc) - timedelta(seconds=started_offset)
    metadata = {"checkpoint": {"name": "x.safetensors"}}
    if boot_seconds_meta is not None:
        metadata["boot_seconds"] = boot_seconds_meta
    job = MagicMock()
    job.started_at = started_at
    job.metadata_ = metadata
    return job


class TestStampBootSeconds:
    async def test_stamps_once_on_first_call(self):
        job = _make_job()
        job_service = MagicMock()
        job_service.get_job = AsyncMock(return_value=job)
        job_service.update_job = AsyncMock(return_value=job)

        await stamp_boot_seconds(job_service, "job-1")

        args = job_service.update_job.await_args
        metadata = args.kwargs["metadata_"]
        assert metadata["boot_seconds"] == pytest.approx(3.0, abs=0.5)
        # MutableList gotcha: the ORIGINAL dict must never be mutated in place.
        assert "boot_seconds" not in job.metadata_
        assert metadata["checkpoint"] == {"name": "x.safetensors"}

    async def test_second_call_is_a_noop(self):
        """The guard prevents a second DB write on later frames."""
        job = _make_job()
        job_service = MagicMock()
        job_service.get_job = AsyncMock(return_value=job)
        job_service.update_job = AsyncMock(return_value=job)

        await stamp_boot_seconds(job_service, "job-1")
        await stamp_boot_seconds(job_service, "job-1")
        assert job_service.update_job.await_count == 1

    async def test_never_re_stamps_when_metadata_already_has_it(self):
        """A restart must not overwrite the first stamp either."""
        job = _make_job(boot_seconds_meta=1.2)
        job_service = MagicMock()
        job_service.get_job = AsyncMock(return_value=job)
        job_service.update_job = AsyncMock(return_value=job)

        await stamp_boot_seconds(job_service, "job-2")
        job_service.update_job.assert_not_awaited()

    async def test_missing_started_at_skips_without_error(self):
        job = _make_job()
        job.started_at = None
        job_service = MagicMock()
        job_service.get_job = AsyncMock(return_value=job)
        job_service.update_job = AsyncMock(return_value=job)

        await stamp_boot_seconds(job_service, "job-3")
        job_service.update_job.assert_not_awaited()

    async def test_missing_job_is_tolerated(self):
        from core.exceptions import NotFoundError

        job_service = MagicMock()
        job_service.get_job = AsyncMock(side_effect=NotFoundError("Job", "gone"))
        await stamp_boot_seconds(job_service, "gone")

    async def test_lookup_failure_does_not_poison_the_guard_forever(self):
        """A transient failure on the FIRST call leaves the job stampable."""
        from core.exceptions import NotFoundError

        job = _make_job()
        job_service = MagicMock()
        job_service.get_job = AsyncMock(
            side_effect=[NotFoundError("Job", "j"), job]
        )
        job_service.update_job = AsyncMock(return_value=job)

        await stamp_boot_seconds(job_service, "job-x")
        await stamp_boot_seconds(job_service, "job-x")
        assert job_service.update_job.await_count == 1


class TestReducerWiring:
    async def test_image_reducer_stamps_on_first_event(self, session, sample_workflow):
        """The in-process image path stamps through the reducer seam."""
        from services.job_service import JobService
        from services.provider_client import _ImageReducer

        job = Job(id="job-red", workflow=sample_workflow, task_type="image",
                  status=JobStatus.SENT_TO_PROVIDER,
                  started_at=datetime.now(timezone.utc) - timedelta(seconds=2.5))
        session.add(job)
        session.commit()

        svc = JobService(session)
        reducer = _ImageReducer("job-red", svc, total_nodes=2, provider_id="modal-x")
        await reducer({"event": "started"})  # first streaming frame from provider

        stamped = await svc.get_job("job-red")
        assert (stamped.metadata_ or {}).get("boot_seconds") is not None

    async def test_llm_reducer_stamps_on_first_event(self, session, sample_workflow):
        from services.job_service import JobService
        from services.provider_client import _LLMReducer

        job = Job(id="job-llm", workflow=sample_workflow, task_type="llm",
                  status=JobStatus.SENT_TO_PROVIDER,
                  started_at=datetime.now(timezone.utc) - timedelta(seconds=2.5))
        session.add(job)
        session.commit()

        svc = JobService(session)
        reducer = _LLMReducer("job-llm", svc, provider_id="remote-llm",
                              workflow={"model": "default"})
        await reducer({"event": "started"})

        stamped = await svc.get_job("job-llm")
        assert (stamped.metadata_ or {}).get("boot_seconds") is not None
