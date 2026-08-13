# Job Service Unit Tests
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session

from core.dtos import JobQueueItem
from core.entities import Job, JobStatus
from core.exceptions import NotFoundError
from services.job_service import JobService


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


class TestJobServiceKeysetPagination:
    """Tests for cursor-based keyset pagination in list_jobs."""

    @pytest.mark.asyncio
    async def test_cursor_pagination_pages_through_all_jobs(self, session: Session, sample_workflow):
        """Keyset cursor walks the full job list with no overlap and no gaps."""
        service = JobService(session)
        for _ in range(5):
            await service.create_job(workflow=sample_workflow, metadata={})

        # Page 1: cursor-less (newest first)
        page1 = await service.list_jobs(limit=2)
        assert len(page1["jobs"]) == 2
        first_id = page1["jobs"][0]["id"]
        assert page1["total"] == 5

        # Build cursor from the last row of page 1
        last = page1["jobs"][-1]
        cursor = (datetime.fromisoformat(last["created_at"]), last["id"])

        # Page 2 via cursor
        page2 = await service.list_jobs(limit=2, cursor=cursor)
        assert len(page2["jobs"]) == 2
        page1_ids = {j["id"] for j in page1["jobs"]}
        assert not (page1_ids & {j["id"] for j in page2["jobs"]})

        # Page 3 via cursor from page 2's last row
        last2 = page2["jobs"][-1]
        cursor2 = (datetime.fromisoformat(last2["created_at"]), last2["id"])
        page3 = await service.list_jobs(limit=2, cursor=cursor2)
        assert len(page3["jobs"]) == 1
        assert all(j["id"] not in page1_ids | {j["id"] for j in page2["jobs"]} for j in page3["jobs"])

        # Exhausted: next page is empty
        last3 = page3["jobs"][-1]
        cursor3 = (datetime.fromisoformat(last3["created_at"]), last3["id"])
        page4 = await service.list_jobs(limit=2, cursor=cursor3)
        assert page4["jobs"] == []

        # Sanity: first page returned the newest job
        assert page1["jobs"][0]["id"] == first_id

    @pytest.mark.asyncio
    async def test_cursor_with_identical_created_at_breaks_ties_by_id(self, session: Session, sample_workflow):
        """Jobs sharing a created_at timestamp are still paginated without loss."""
        service = JobService(session)
        job = await service.create_job(workflow=sample_workflow, metadata={})
        job2 = await service.create_job(workflow=sample_workflow, metadata={})
        job2.created_at = job.created_at  # force identical timestamps
        session.add(job2)
        session.commit()

        page1 = await service.list_jobs(limit=1)
        assert len(page1["jobs"]) == 1
        last = page1["jobs"][-1]
        cursor = (datetime.fromisoformat(last["created_at"]), last["id"])
        page2 = await service.list_jobs(limit=5, cursor=cursor)
        assert len(page2["jobs"]) == 1
        assert page2["jobs"][0]["id"] != last["id"]


class TestJobServiceUpdate:
    """Tests for JobService.update_job."""

    @pytest.mark.asyncio
    async def test_update_status_to_running(self, session: Session, sample_workflow):
        """Updating status to running sets started_at timestamp."""
        service = JobService(session)
        job = await service.create_job(workflow=sample_workflow, metadata={})
        await service.update_job(job.id, status=JobStatus.SENT_TO_PROVIDER)
        await service.update_job(job.id, status=JobStatus.CONNECTED)
        updated = await service.update_job(job.id, status=JobStatus.GENERATING, progress=50.0)
        assert updated.status == JobStatus.GENERATING
        assert updated.started_at is not None

    @pytest.mark.asyncio
    async def test_update_status_to_completed(self, session: Session, sample_workflow):
        """Updating status to completed sets completed_at timestamp."""
        service = JobService(session)
        job = await service.create_job(workflow=sample_workflow, metadata={})
        await service.update_job(job.id, status=JobStatus.SENT_TO_PROVIDER)
        await service.update_job(job.id, status=JobStatus.CONNECTED)
        await service.update_job(job.id, status=JobStatus.GENERATING)
        await service.update_job(job.id, status=JobStatus.POST_PROCESSING)
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
            await service.update_job(job.id, status=JobStatus.SENT_TO_PROVIDER)
            await service.update_job(job.id, status=JobStatus.CONNECTED)
            await service.update_job(job.id, status=JobStatus.GENERATING)
            await service.update_job(job.id, status=JobStatus.POST_PROCESSING)
            mock_emit.reset_mock()
            await service.update_job(job.id, status=JobStatus.COMPLETED)
            mock_emit.assert_called_once()
            assert mock_emit.call_args[0][0] == EventType.JOB_COMPLETED

    @pytest.mark.asyncio
    async def test_update_failed_emits_failed_event(self, session: Session, sample_workflow):
        """Updating to failed status (from SENT_TO_PROVIDER) emits JOB_FAILED event."""
        from core.events import EventType
        with patch("services.job_service.emit_job_event", new_callable=AsyncMock) as mock_emit:
            service = JobService(session)
            job = await service.create_job(workflow=sample_workflow, metadata={})
            mock_emit.reset_mock()
            # PENDING->FAILED is allowed so the runner can fail jobs with no
            # remaining providers; here we exercise FAILED from SENT_TO_PROVIDER.
            await service.update_job(job.id, status=JobStatus.SENT_TO_PROVIDER)
            mock_emit.reset_mock()
            await service.update_job(job.id, status=JobStatus.FAILED, error="timeout")
            mock_emit.assert_called_once()
            assert mock_emit.call_args[0][0] == EventType.JOB_FAILED

    @pytest.mark.asyncio
    async def test_update_cancelled_sets_completed_timestamp_and_emits_cancelled(self, session: Session, sample_workflow):
        """Updating to cancelled status should mark terminal timestamp and emit JOB_CANCELLED."""
        from core.events import EventType

        with patch("services.job_service.emit_job_event", new_callable=AsyncMock) as mock_emit:
            service = JobService(session)
            job = await service.create_job(workflow=sample_workflow, metadata={})
            mock_emit.reset_mock()

            updated = await service.update_job(job.id, status=JobStatus.CANCELLED, message="Cancelled by user")

            assert updated.status == JobStatus.CANCELLED
            assert updated.completed_at is not None
            mock_emit.assert_called_once()
            assert mock_emit.call_args[0][0] == EventType.JOB_CANCELLED


class TestJobServiceFsm:
    """FSM retry/failover transitions — the job_runner resets in-flight jobs
    back to PENDING during retries and provider failover."""

    @pytest.mark.asyncio
    async def test_in_flight_cannot_reset_to_pending(self, session: Session, sample_workflow):
        service = JobService(session)
        job = await service.create_job(workflow=sample_workflow, metadata={})
        await service.update_job(job.id, status=JobStatus.SENT_TO_PROVIDER)
        updated = await service.update_job(job.id, status=JobStatus.PENDING, message="Retrying...")
        assert updated.status == JobStatus.SENT_TO_PROVIDER

    @pytest.mark.asyncio
    async def test_generating_cannot_reset_to_pending(self, session: Session, sample_workflow):
        service = JobService(session)
        job = await service.create_job(workflow=sample_workflow, metadata={})
        await service.update_job(job.id, status=JobStatus.SENT_TO_PROVIDER)
        await service.update_job(job.id, status=JobStatus.CONNECTED)
        await service.update_job(job.id, status=JobStatus.GENERATING)
        updated = await service.update_job(job.id, status=JobStatus.PENDING)
        assert updated.status == JobStatus.GENERATING

    @pytest.mark.asyncio
    async def test_pending_cannot_fail_directly(self, session: Session, sample_workflow):
        service = JobService(session)
        job = await service.create_job(workflow=sample_workflow, metadata={})
        updated = await service.update_job(job.id, status=JobStatus.FAILED, error="No available providers")
        assert updated.status == JobStatus.PENDING

    @pytest.mark.asyncio
    async def test_completed_is_terminal(self, session: Session, sample_workflow):
        service = JobService(session)
        job = await service.create_job(workflow=sample_workflow, metadata={})
        await service.update_job(job.id, status=JobStatus.SENT_TO_PROVIDER)
        await service.update_job(job.id, status=JobStatus.COMPLETED)
        updated = await service.update_job(job.id, status=JobStatus.PENDING, message="should be ignored")
        assert updated.status == JobStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_cancelled_is_terminal(self, session: Session, sample_workflow):
        service = JobService(session)
        job = await service.create_job(workflow=sample_workflow, metadata={})
        updated = await service.update_job(job.id, status=JobStatus.CANCELLED)
        assert updated.status == JobStatus.CANCELLED


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
        await service.update_job(job.id, status=JobStatus.SENT_TO_PROVIDER)
        await service.update_job(job.id, status=JobStatus.CONNECTED)
        await service.update_job(job.id, status=JobStatus.GENERATING, overall_progress=50.0)

        running_items = service.get_running_queue_items()

        assert len(running_items) == 1
        item = running_items[0]
        assert item.status == JobStatus.GENERATING
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


class TestJobMetadataBreakdown:
    """Tests for JobService.get_metadata_key_counts (JSONB/JSON1 aggregation)."""

    @pytest.mark.asyncio
    async def test_breakdown_aggregates_by_key(self, session: Session, sample_workflow):
        service = JobService(session)
        await service.create_job(workflow=sample_workflow, metadata={"model": "sd15"})
        await service.create_job(workflow=sample_workflow, metadata={"model": "sd15"})
        await service.create_job(workflow=sample_workflow, metadata={"model": "xl"})
        await service.create_job(workflow=sample_workflow, metadata={"prompt": "cat"})

        breakdown = await service.get_metadata_key_counts("model")
        assert {"value": "sd15", "count": 2} in breakdown
        assert {"value": "xl", "count": 1} in breakdown
        assert len(breakdown) == 2

    @pytest.mark.asyncio
    async def test_breakdown_respects_status_filter(self, session: Session, sample_workflow):
        service = JobService(session)
        completed = await service.create_job(workflow=sample_workflow, metadata={"model": "a"})
        failed = await service.create_job(workflow=sample_workflow, metadata={"model": "b"})
        completed.status = JobStatus.COMPLETED
        failed.status = JobStatus.FAILED
        session.add_all([completed, failed])
        session.commit()

        breakdown = await service.get_metadata_key_counts(
            "model", statuses=[JobStatus.COMPLETED]
        )
        assert breakdown == [{"value": "a", "count": 1}]

    @pytest.mark.asyncio
    async def test_breakdown_unknown_key_returns_empty(self, session: Session, sample_workflow):
        service = JobService(session)
        await service.create_job(workflow=sample_workflow, metadata={"model": "sd15"})
        breakdown = await service.get_metadata_key_counts("nope")
        assert breakdown == []


class TestJobServiceSearch:
    """Tests for JobService.search_jobs (tsvector on Postgres, LIKE on SQLite)."""

    @pytest.mark.asyncio
    async def test_search_finds_prompt_match(self, session: Session, sample_workflow):
        service = JobService(session)
        await service.create_job(workflow=sample_workflow, metadata={"prompt": "a majestic dragon over a castle"})
        await service.create_job(workflow=sample_workflow, metadata={"prompt": "a cozy kitchen interior"})

        results = await service.search_jobs("dragon")
        assert len(results) == 1
        assert "dragon" in results[0]["metadata"]["prompt"]

    @pytest.mark.asyncio
    async def test_search_empty_query_returns_nothing(self, session: Session, sample_workflow):
        service = JobService(session)
        await service.create_job(workflow=sample_workflow, metadata={"prompt": "a cat"})
        results = await service.search_jobs("")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_no_match_returns_empty(self, session: Session, sample_workflow):
        service = JobService(session)
        await service.create_job(workflow=sample_workflow, metadata={"prompt": "a cat"})
        results = await service.search_jobs("elephant")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, session: Session, sample_workflow):
        service = JobService(session)
        for i in range(3):
            await service.create_job(workflow=sample_workflow, metadata={"prompt": f"dragon variant {i}"})
        results = await service.search_jobs("dragon", limit=2)
        assert len(results) == 2
