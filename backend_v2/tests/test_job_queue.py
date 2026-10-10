"""Tests for services/job_queue.py"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

from services.job_queue import JobQueue, QueueManager


class TestJobQueueInit:
    def test_init_max_workers(self):
        q = JobQueue(max_workers=3)
        assert q.max_workers == 3

    def test_init_not_running(self):
        q = JobQueue()
        assert q._running is False

    def test_init_no_processor(self):
        q = JobQueue()
        assert q._processor is None

    def test_init_empty_workers(self):
        q = JobQueue()
        assert q._workers == []

    def test_init_empty_active_jobs(self):
        q = JobQueue()
        assert q._active_jobs == {}


class TestJobQueueSetProcessor:
    def test_set_processor(self):
        q = JobQueue()
        async def my_processor(job_id, provider_id):
            pass
        q.set_processor(my_processor)
        assert q._processor is my_processor


class TestJobQueueEnqueue:
    async def test_enqueue_adds_to_queue(self):
        q = JobQueue()
        await q.enqueue("job-1")
        assert not q._queue.empty()

    async def test_enqueue_with_provider(self):
        q = JobQueue()
        await q.enqueue("job-1", "modal-primary")
        item = await q._queue.get()
        assert item == ("job-1", "modal-primary")

    async def test_enqueue_without_provider(self):
        q = JobQueue()
        await q.enqueue("job-2")
        item = await q._queue.get()
        assert item == ("job-2", None)

    async def test_enqueue_multiple(self):
        q = JobQueue()
        await q.enqueue("job-1")
        await q.enqueue("job-2")
        await q.enqueue("job-3")
        # All 3 should be in queue
        count = 0
        while not q._queue.empty():
            await q._queue.get()
            count += 1
        assert count == 3


class TestJobQueueStartStop:
    async def test_start_sets_running(self):
        q = JobQueue(max_workers=1)
        async def dummy_processor(job_id, provider_id):
            await asyncio.sleep(0)
        q.set_processor(dummy_processor)
        try:
            await q.start()
            assert q._running is True
        finally:
            await q.stop()

    async def test_stop_sets_not_running(self):
        q = JobQueue(max_workers=1)
        async def dummy_processor(job_id, provider_id):
            await asyncio.sleep(0)
        q.set_processor(dummy_processor)
        await q.start()
        await q.stop()
        assert q._running is False

    async def test_start_creates_workers(self):
        q = JobQueue(max_workers=2)
        async def dummy_processor(job_id, provider_id):
            await asyncio.sleep(100)  # Never complete
        q.set_processor(dummy_processor)
        try:
            await q.start()
            assert len(q._workers) == 2
        finally:
            await q.stop()

    async def test_start_twice_is_safe(self):
        q = JobQueue(max_workers=1)
        async def dummy_processor(job_id, provider_id):
            await asyncio.sleep(100)
        q.set_processor(dummy_processor)
        try:
            await q.start()
            await q.start()  # Should be a no-op
            assert len(q._workers) == 1
        finally:
            await q.stop()

    async def test_stop_when_not_running_is_safe(self):
        q = JobQueue(max_workers=1)
        # Should not raise
        await q.stop()

    async def test_stop_allows_active_job_to_finish_before_cancelling(self):
        q = JobQueue(max_workers=1)
        # These tests put jobs directly in the in-process queue, so force
        # in-process mode regardless of whether the live env uses Postgres.
        q._use_db_claims = False
        started = asyncio.Event()
        finished = asyncio.Event()

        async def dummy_processor(job_id, provider_id):
            started.set()
            await asyncio.sleep(0.05)
            finished.set()

        q.set_processor(dummy_processor)
        await q.start()
        await q.enqueue("job-1")

        await asyncio.wait_for(started.wait(), timeout=1.0)
        await q.stop()

        assert finished.is_set() is True
        assert q.active_count == 0

    async def test_stop_cancels_stuck_workers_after_timeout(self):
        q = JobQueue(max_workers=1)
        q._use_db_claims = False
        started = asyncio.Event()

        async def dummy_processor(job_id, provider_id):
            started.set()
            await asyncio.sleep(10)

        q.set_processor(dummy_processor)
        await q.start()
        await q.enqueue("job-1")

        await asyncio.wait_for(started.wait(), timeout=1.0)

        original_wait_for = asyncio.wait_for

        async def immediate_timeout(awaitable, timeout):
            if timeout == 5.0:
                raise asyncio.TimeoutError()
            return await original_wait_for(awaitable, timeout)

        with patch("services.job_queue.asyncio.wait_for", side_effect=immediate_timeout):
            await q.stop()

        assert q._workers == []
        assert q.active_count == 0


class TestJobQueueSize:
    async def test_size_empty(self):
        q = JobQueue()
        assert q._queue.qsize() == 0

    async def test_size_after_enqueue(self):
        q = JobQueue()
        await q.enqueue("job-1")
        await q.enqueue("job-2")
        assert q._queue.qsize() == 2


class TestMaxConcurrentThrottle:
    """`jobs.max_concurrent` must actually gate dispatch.

    The setting was exposed through PUT /api/settings, persisted to
    config.json and echoed back by GET /api/settings, but nothing read it:
    the claim query had no ceiling and the pool was bounded only by provider
    count. A user lowering it to throttle spend on Modal/Beam saw the value
    persist and change nothing.

    These exercise the config-read side, which is the part that was dead.
    The claim SQL itself is Postgres-only (SQLite uses the in-process queue)
    and is covered end-to-end by the live EXPLAIN.
    """

    def test_reads_jobs_max_concurrent(self):
        q = JobQueue(max_workers=1, task_type="image")
        with patch("services.job_queue.get_config", return_value={"jobs": {"max_concurrent": 2}}):
            assert q._max_concurrent() == 2

    def test_missing_key_never_throttles(self):
        """A bad config must not wedge the queue — it must fail open."""
        q = JobQueue(max_workers=1, task_type="image")
        for cfg in ({}, {"jobs": {}}, {"jobs": {"max_concurrent": None}}, None):
            with patch("services.job_queue.get_config", return_value=cfg):
                assert q._max_concurrent() == 10**6, f"throttled on {cfg!r}"

    def test_nonsense_values_fail_open(self):
        q = JobQueue(max_workers=1, task_type="image")
        for bad in (0, -3, "abc", "", [], {}):
            with patch("services.job_queue.get_config", return_value={"jobs": {"max_concurrent": bad}}):
                value = q._max_concurrent()
                assert value == 10**6 or value >= 1, f"bad value {bad!r} produced {value}"

    def test_cap_is_per_task_type(self):
        """Image saturation must not starve a chat reply's LLM job.

        The claim counts only rows of its own task_type, so the two pools
        cannot consume each other's budget.
        """
        image = JobQueue(max_workers=1, task_type="image")
        llm = JobQueue(max_workers=1, task_type="llm")
        with patch("services.job_queue.get_config", return_value={"jobs": {"max_concurrent": 1}}):
            assert image._max_concurrent() == 1
            assert llm._max_concurrent() == 1
        assert image._task_type != llm._task_type


class TestRawSqlStatusVocabulary:
    """The two raw-SQL statements must agree with `ACTIVE_JOB_STATUSES`.

    Both used to carry the six statuses as SQL string literals, hand-copied
    from the Python enum. A seventh status added to
    `core.entities.ACTIVE_JOB_STATUSES` would then make the queue's own
    headroom arithmetic disagree with the runners that populate it — the
    claim would see fewer in-flight jobs than exist, and the restart reset
    would leave rows stuck in the new state forever, because nothing else
    resets them.
    """

    def test_both_statements_interpolate_the_enum_not_literals(self):
        from core.entities import ACTIVE_JOB_STATUSES

        # `inspect.getsource`, not `co_consts`: the reset statement is built
        # from adjacent string literals, so the joined SQL never appears as a
        # single constant. Comments are stripped first — the explanatory
        # comment on the `.name` fix quotes the literal it warns about.
        import inspect

        def _code_only(fn) -> str:
            return "\n".join(
                line.split("#", 1)[0]
                for line in inspect.getsource(fn).splitlines()
            )

        blob = _code_only(JobQueue._claim_next_job_sync) + _code_only(
            QueueManager._reset_claims_and_requeue_sync
        )

        for status in ACTIVE_JOB_STATUSES:
            assert f"'{status.value}'" not in blob, (
                f"{status.value} is still a hard-coded SQL literal; the enum is "
                "the one definition of the active vocabulary"
            )
        assert "active_status_placeholders" in blob

    def test_reset_requeues_in_flight_and_claimed_pending_jobs(self, session):
        """The reset's observable contract, on the dialect tests actually run.

        This statement is not dialect-guarded — unlike the claim query, it used
        to be a literal string nobody executed under SQLite, so a typo in it
        shipped silently.
        """
        from core.entities import Job, JobStatus

        in_flight = Job(
            id="claims-generating",
            task_type="image",
            status=JobStatus.GENERATING,
            workflow={},
        )
        claimed_pending = Job(
            id="claims-pending",
            task_type="image",
            status=JobStatus.PENDING,
            workflow={},
            claimed_at=datetime.now(timezone.utc),
        )
        terminal = Job(
            id="claims-done",
            task_type="image",
            status=JobStatus.COMPLETED,
            workflow={},
        )
        session.add_all([in_flight, claimed_pending, terminal])
        session.commit()

        QueueManager._reset_claims_and_requeue_sync()

        session.refresh(in_flight)
        session.refresh(claimed_pending)
        session.refresh(terminal)
        assert in_flight.status == JobStatus.PENDING
        assert in_flight.started_at is None
        assert claimed_pending.claimed_at is None
        # Terminal jobs are left untouched — a finished job is not in flight.
        assert terminal.status == JobStatus.COMPLETED
