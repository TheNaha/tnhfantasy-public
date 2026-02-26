# Job Service Unit Tests
import pytest
from unittest.mock import AsyncMock, patch
from sqlmodel import Session

from services.job_service import JobService
from core.entities import Job, JobStatus
from core.dtos import JobQueueItem
from core.exceptions import NotFoundError


class TestJobServiceCreate:
    """Tests for JobService.create_job."""

    @pytest.mark.asyncio
    async def test_create_job_returns_job(self, session: Session, sample_workflow):
        """Creating a job returns a Job with pending status."""
        service = JobService(session)
        job = await service.create_job(
            workflow=sample_workflow,
            metadata={"prompt": "test"}
        )
        assert isinstance(job, Job)
        assert job.status == JobStatus.PENDING
        assert job.id is not None

    @pytest.mark.asyncio
    async def test_create_job_stores_metadata(self, session: Session, sample_workflow):
        """Job metadata is persisted."""
        service = JobService(session)
        meta = {"prompt": "a cat", "seed": 42}
        job = await service.create_job(workflow=sample_workflow, metadata=meta)
        assert job.metadata_["prompt"] == "a cat"
        assert job.metadata_["seed"] == 42

    @pytest.mark.asyncio
    async def test_create_job_emits_event(self, session: Session, sample_workflow):
        """Creating a job emits JOB_CREATED event."""
        with patch("services.job_service.emit_job_event", new_callable=AsyncMock) as mock_emit:
            service = JobService(session)
            await service.create_job(workflow=sample_workflow, metadata={})
            mock_emit.assert_called_once()
            args = mock_emit.call_args
            from core.events import EventType
            assert args[0][0] == EventType.JOB_CREATED


class TestJobServiceGet:
    """Tests for JobService.get_job."""

    @pytest.mark.asyncio
    async def test_get_existing_job(self, session: Session, sample_workflow):
        """Getting an existing job returns it."""
        service = JobService(session)
        created = await service.create_job(workflow=sample_workflow, metadata={})
        fetched = await service.get_job(created.id)
        assert fetched.id == created.id

    @pytest.mark.asyncio
    async def test_get_nonexistent_job_raises(self, session: Session):
        """Getting a non-existent job raises NotFoundError."""
        service = JobService(session)
        with pytest.raises(NotFoundError) as exc_info:
            await service.get_job("does-not-exist")
        assert "does-not-exist" in exc_info.value.message


class TestJobServiceList:
    """Tests for JobService.list_jobs."""

    @pytest.mark.asyncio
    async def test_list_empty(self, session: Session):
        """Listing when empty returns empty list."""
        service = JobService(session)
        result = await service.list_jobs()
        assert result["jobs"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_list_returns_created_jobs(self, session: Session, sample_workflow):
        """Listing after creating jobs returns them."""
        service = JobService(session)
        await service.create_job(workflow=sample_workflow, metadata={})
        await service.create_job(workflow=sample_workflow, metadata={})
        result = await service.list_jobs()
        assert result["total"] == 2
        assert len(result["jobs"]) == 2

    @pytest.mark.asyncio
    async def test_list_pagination_limit(self, session: Session, sample_workflow):
        """Pagination limit is respected."""
        service = JobService(session)
        for _ in range(5):
            await service.create_job(workflow=sample_workflow, metadata={})
        result = await service.list_jobs(limit=2)
        assert len(result["jobs"]) == 2

    @pytest.mark.asyncio
    async def test_pending_jobs_have_queue_position(self, session: Session, sample_workflow):
        """Pending jobs include queue_position field."""
        service = JobService(session)
        await service.create_job(workflow=sample_workflow, metadata={})
        result = await service.list_jobs()
        pending = [j for j in result["jobs"] if j["status"] == "pending"]
        assert all("queue_position" in j for j in pending)


class TestJobServiceUpdate:
    """Tests for JobService.update_job."""

    @pytest.mark.asyncio
    async def test_update_status_to_running(self, session: Session, sample_workflow):
        """Updating status to running sets started_at timestamp."""
        service = JobService(session)
        job = await service.create_job(workflow=sample_workflow, metadata={})
        updated = await service.update_job(job.id, status=JobStatus.RUNNING)
        assert updated.status == JobStatus.RUNNING
        assert updated.started_at is not None

    @pytest.mark.asyncio
    async def test_update_status_to_completed(self, session: Session, sample_workflow):
        """Updating status to completed sets completed_at timestamp."""
        service = JobService(session)
        job = await service.create_job(workflow=sample_workflow, metadata={})
        await service.update_job(job.id, status=JobStatus.RUNNING)
        updated = await service.update_job(job.id, status=JobStatus.COMPLETED)
        assert updated.status == JobStatus.COMPLETED
        assert updated.completed_at is not None

    @pytest.mark.asyncio
    async def test_update_nonexistent_job_raises(self, session: Session):
        """Updating a non-existent job raises NotFoundError."""
        service = JobService(session)
        with pytest.raises(NotFoundError):
            await service.update_job("nonexistent", status=JobStatus.FAILED)

    @pytest.mark.asyncio
    async def test_update_progress_emits_progress_event(self, session: Session, sample_workflow):
        """Updating progress emits JOB_PROGRESS event."""
        from core.events import EventType
        with patch("services.job_service.emit_job_event", new_callable=AsyncMock) as mock_emit:
            service = JobService(session)
            job = await service.create_job(workflow=sample_workflow, metadata={})
            mock_emit.reset_mock()
            await service.update_job(job.id, progress=50.0)
            mock_emit.assert_called_once()
            assert mock_emit.call_args[0][0] == EventType.JOB_PROGRESS

    @pytest.mark.asyncio
    async def test_update_completed_emits_completed_event(self, session: Session, sample_workflow):
        """Updating to completed status emits JOB_COMPLETED event."""
        from core.events import EventType
        with patch("services.job_service.emit_job_event", new_callable=AsyncMock) as mock_emit:
            service = JobService(session)
            job = await service.create_job(workflow=sample_workflow, metadata={})
            mock_emit.reset_mock()
            await service.update_job(job.id, status=JobStatus.COMPLETED)
            mock_emit.assert_called_once()
            assert mock_emit.call_args[0][0] == EventType.JOB_COMPLETED

    @pytest.mark.asyncio
    async def test_update_failed_emits_failed_event(self, session: Session, sample_workflow):
        """Updating to failed status emits JOB_FAILED event."""
        from core.events import EventType
        with patch("services.job_service.emit_job_event", new_callable=AsyncMock) as mock_emit:
            service = JobService(session)
            job = await service.create_job(workflow=sample_workflow, metadata={})
            mock_emit.reset_mock()
            await service.update_job(job.id, status=JobStatus.FAILED, error="timeout")
            mock_emit.assert_called_once()
            assert mock_emit.call_args[0][0] == EventType.JOB_FAILED


class TestJobServiceDelete:
    """Tests for JobService.delete_job."""

    @pytest.mark.asyncio
    async def test_delete_existing_job(self, session: Session, sample_workflow):
        """Deleting an existing job returns True."""
        service = JobService(session)
        job = await service.create_job(workflow=sample_workflow, metadata={})
        result = await service.delete_job(job.id)
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_removes_job(self, session: Session, sample_workflow):
        """After deletion, job is no longer retrievable."""
        service = JobService(session)
        job = await service.create_job(workflow=sample_workflow, metadata={})
        await service.delete_job(job.id)
        with pytest.raises(NotFoundError):
            await service.get_job(job.id)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_raises(self, session: Session):
        """Deleting non-existent job raises NotFoundError."""
        service = JobService(session)
        with pytest.raises(NotFoundError):
            await service.delete_job("nonexistent")


class TestJobServiceClear:
    """Tests for JobService.clear_all_jobs."""

    @pytest.mark.asyncio
    async def test_clear_returns_count(self, session: Session, sample_workflow):
        """Clearing all jobs returns count of deleted jobs."""
        service = JobService(session)
        await service.create_job(workflow=sample_workflow, metadata={})
        await service.create_job(workflow=sample_workflow, metadata={})
        count = await service.clear_all_jobs()
        assert count == 2

    @pytest.mark.asyncio
    async def test_clear_empty_returns_zero(self, session: Session):
        """Clearing when no jobs returns 0."""
        service = JobService(session)
        count = await service.clear_all_jobs()
        assert count == 0


class TestJobServiceStats:
    """Tests for JobService statistics methods."""

    @pytest.mark.asyncio
    async def test_get_job_stats_returns_dict(self, session: Session):
        """get_job_stats returns a dict with status counts."""
        service = JobService(session)
        stats = service.get_job_stats()
        assert isinstance(stats, dict)

    @pytest.mark.asyncio
    async def test_get_average_duration_default(self, session: Session):
        """get_average_duration returns 30.0 when no completed jobs."""
        service = JobService(session)
        avg = service.get_average_duration()
        assert avg == 30.0

    @pytest.mark.asyncio
    async def test_get_pending_jobs_empty(self, session: Session):
        """get_pending_jobs returns empty list when no jobs."""
        service = JobService(session)
        result = service.get_pending_jobs()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_pending_jobs_with_data(self, session: Session, sample_workflow):
        """get_pending_jobs returns pending jobs."""
        service = JobService(session)
        await service.create_job(workflow=sample_workflow, metadata={})
        result = service.get_pending_jobs()
        assert len(result) == 1
        assert result[0].status == JobStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_running_jobs_empty(self, session: Session):
        """get_running_jobs returns empty when no running jobs."""
        service = JobService(session)
        result = service.get_running_jobs()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_job_stats_detailed(self, session: Session):
        """get_job_stats_detailed returns structured stats dict."""
        service = JobService(session)
        stats = service.get_job_stats_detailed()
        assert "by_status" in stats
        assert "total" in stats
        assert "avg_durations" in stats


class TestJobServiceQueueItems:
    """Tests for optimized queue retrieval methods."""

    @pytest.mark.asyncio
    async def test_get_queue_items_returns_lightweight_objects(self, session: Session, sample_workflow):
        """Test that get_queue_items returns JobQueueItem objects with correct data."""
        service = JobService(session)

        # Create a job with heavy workflow
        heavy_workflow = {"nodes": [{"id": i, "data": "x" * 1000} for i in range(100)]}
        metadata = {"prompt": "test prompt", "seed": 123}

        job = await service.create_job(workflow=heavy_workflow, metadata=metadata)

        # Fetch using new optimized method
        pending_items = service.get_pending_queue_items()

        assert len(pending_items) == 1
        item = pending_items[0]

        assert isinstance(item, JobQueueItem)
        assert item.id == job.id
        assert item.status == JobStatus.PENDING
        assert item.metadata_ == metadata
        assert item.created_at is not None

        # Ensure heavy workflow is NOT present in the DTO (it's not even a field)
        assert not hasattr(item, "workflow")

    @pytest.mark.asyncio
    async def test_get_queue_items_running(self, session: Session, sample_workflow):
        """Test retrieving running jobs."""
        service = JobService(session)
        job = await service.create_job(workflow=sample_workflow, metadata={})
        await service.update_job(job.id, status=JobStatus.RUNNING, overall_progress=50.0)

        running_items = service.get_running_queue_items()

        assert len(running_items) == 1
        item = running_items[0]
        assert item.status == JobStatus.RUNNING
        assert item.overall_progress == 50.0

    @pytest.mark.asyncio
    async def test_queue_ordering(self, session: Session, sample_workflow):
        """Test that queue items are ordered by created_at."""
        service = JobService(session)

        job1 = await service.create_job(workflow=sample_workflow, metadata={"i": 1})
        import asyncio
        await asyncio.sleep(0.01) # Ensure timestamp diff
        job2 = await service.create_job(workflow=sample_workflow, metadata={"i": 2})

        pending_items = service.get_pending_queue_items()

        assert len(pending_items) == 2
        assert pending_items[0].id == job1.id
        assert pending_items[1].id == job2.id
