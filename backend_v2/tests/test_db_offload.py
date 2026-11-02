"""The job path's database work must run on the offload pool, not the loop.

`job_service` is `async def` with sync SQLModel bodies, and `update_job` is
called on every progress frame. Each of those was a blocking `session.commit()`
on the event loop — roughly one per second per in-flight job — which stalled the
whole API rather than the job that caused it.

The fix is a dedicated pool, not `asyncio.to_thread`: the default executor is
`min(32, cpu+4)` threads, which on the 2-CPU box this runs on is six, and
funnelling every job's DB work through it just moves the stall into a queue.
These tests pin that the work reaches the *named* pool.
"""


import pytest

from core.entities import JobStatus
from infrastructure import db_executor


@pytest.fixture
def offload_threads():
    """Thread names the offload pool has created so far."""
    return set(getattr(db_executor.executor, "_threads", ()) or ())


class TestOffloadPool:
    def test_it_is_not_the_loop_default_executor(self):
        """The whole point: a dedicated pool, sized to the DB pool."""
        assert db_executor.executor._max_workers > 1
        assert "db-offload" in db_executor.executor._thread_name_prefix

    def test_it_is_sized_to_the_database_pool(self):
        """Matched so offloading cannot queue inside SQLAlchemy."""
        from infrastructure.database import get_db_pool_size

        assert db_executor._POOL_SIZE == get_db_pool_size() or db_executor._POOL_SIZE == 1
        # 1 is the SQLite case (NullPool, one connection); never larger.
        assert db_executor._POOL_SIZE <= get_db_pool_size()

    @pytest.mark.asyncio
    async def test_update_job_runs_on_a_db_offload_thread(self, session, monkeypatch):
        """`update_job` ROUTES its database work through `run_db`.

        Asserts the seam, not the thread it lands on. Where it lands is decided by
        `run_db` — on a worker when the pool gives each checkout its own
        connection, on the loop when the pool shares one — so asserting a thread
        here couples this test to whichever engine the suite happens to build.
        `test_the_queue_pool_shape_does_run_on_a_worker` and
        `test_a_shared_connection_runs_inline` cover that decision together.
        """
        import services.job_service as job_service_mod
        from services.job_service import JobService

        calls = []
        real_run_db = job_service_mod.run_db

        async def _spy(fn, *args):
            calls.append(fn)
            return await real_run_db(fn, *args)

        monkeypatch.setattr(job_service_mod, "run_db", _spy)

        service = JobService(session)
        job = await service.create_job(task_type="image", workflow={"1": {}}, metadata={})
        calls.clear()

        if "update_job" == "update_job":
            await service.update_job(job.id, status=JobStatus.PRE_GENERATION)
        else:
            await service.get_job(job.id)

        assert calls, f"{'update_job'} did not route its database work through run_db"

    @pytest.mark.asyncio
    async def test_get_job_runs_on_a_db_offload_thread(self, session, monkeypatch):
        """`get_job` ROUTES its database work through `run_db`.

        Asserts the seam, not the thread it lands on. Where it lands is decided by
        `run_db` — on a worker when the pool gives each checkout its own
        connection, on the loop when the pool shares one — so asserting a thread
        here couples this test to whichever engine the suite happens to build.
        `test_the_queue_pool_shape_does_run_on_a_worker` and
        `test_a_shared_connection_runs_inline` cover that decision together.
        """
        import services.job_service as job_service_mod
        from services.job_service import JobService

        calls = []
        real_run_db = job_service_mod.run_db

        async def _spy(fn, *args):
            calls.append(fn)
            return await real_run_db(fn, *args)

        monkeypatch.setattr(job_service_mod, "run_db", _spy)

        service = JobService(session)
        job = await service.create_job(task_type="image", workflow={"1": {}}, metadata={})
        calls.clear()

        if "get_job" == "update_job":
            await service.update_job(job.id, status=JobStatus.PRE_GENERATION)
        else:
            await service.get_job(job.id)

        assert calls, f"{'get_job'} did not route its database work through run_db"

    @pytest.mark.asyncio
    async def test_a_transition_still_emits_its_event(self, session):
        """Offloading must not swallow the completion event.

        The emission stays on the loop while the write is on the pool, so it has
        to read the POST-WRITE `status`/`updates` — a closure that returned only
        the job would classify a completion as `JOB_UPDATED`.
        """
        import asyncio as _asyncio

        from core.events import event_bus
        from services.job_service import JobService

        service = JobService(session)
        job = await service.create_job(task_type="image", workflow={"1": {}}, metadata={})
        await service.update_job(job.id, status=JobStatus.SENT_TO_PROVIDER)

        seen = []

        async def _drain():
            async for event in event_bus.subscribe("job"):
                seen.append(event)

        consumer = _asyncio.create_task(_drain())
        await _asyncio.sleep(0)

        await service.update_job(
            job.id, status=JobStatus.COMPLETED, outputs=[{"filename": "a.png"}],
        )
        await _asyncio.sleep(0.05)
        consumer.cancel()

        completed = [e for e in seen if e.type == "job.completed"]
        assert completed, f"no completion event; got {[e.type for e in seen]}"
        assert completed[0].data["job"].get("status") == "completed"

    @pytest.mark.asyncio
    async def test_a_progress_update_still_emits_job_progress(self, session):
        """The other half of the event contract the closure could have broken."""
        import asyncio as _asyncio

        from core.events import event_bus
        from services.job_service import JobService

        service = JobService(session)
        job = await service.create_job(task_type="image", workflow={"1": {}}, metadata={})
        await service.update_job(job.id, status=JobStatus.SENT_TO_PROVIDER)

        seen = []

        async def _drain():
            async for event in event_bus.subscribe("job"):
                seen.append(event)

        consumer = _asyncio.create_task(_drain())
        await _asyncio.sleep(0)

        await service.update_job(job.id, progress=0.42)
        await _asyncio.sleep(0.05)
        consumer.cancel()

        assert any(e.type == "job.progress" for e in seen), (
            f"progress event lost; got {[e.type for e in seen]}"
        )

    @pytest.mark.asyncio
    async def test_a_rejected_transition_does_not_emit_a_terminal_event(self, session):
        """The FSM guard's post-write values must reach the emission too.

        A rejected transition pops `status` on its way out. If the emission
        re-derived the event type from the caller's argument instead of the
        value after the write, a rejected CANCELLED would still broadcast a
        cancellation that never happened.

        The transition used here has to be one the FSM still forbids.
        PENDING -> COMPLETED used to be the example and no longer is: a job
        that holds persisted outputs must be able to complete, and the edge
        was added for that. CANCELLED -> COMPLETED is still forbidden, and it
        is the more important one - a cancelled job must not come back to life.
        """
        from core.events import event_bus
        from services.job_service import JobService

        service = JobService(session)
        job = await service.create_job(task_type="image", workflow={"1": {}}, metadata={})
        await service.update_job(job.id, status=JobStatus.CANCELLED)

        seen = []
        event_bus.subscribe(lambda event: seen.append(event), "job")

        # CANCELLED -> COMPLETED is not an allowed transition.
        await service.update_job(job.id, status=JobStatus.COMPLETED, outputs=[])

        assert not any(e.type == "job.completed" for e in seen), (
            "an illegal transition emitted a completion event"
        )
        assert job.status == JobStatus.CANCELLED


class TestTheOffloadDeclinesWhenItWouldRace:
    """Offloading a shared connection is a race, not an optimisation.

    The `session` fixture's engine is `StaticPool` — one SQLite connection behind
    every session, which is what lets a whole suite share an in-memory database.
    Moving a session's work to a worker thread while the loop can still reach
    that same connection is two threads on one connection, and SQLite connections
    are not safe for concurrent use.

    This cost an intermittent failure where a job finalised at
    `post-processing` instead of `completed` — the two writers interleaving.
    Production Postgres uses QueuePool, a connection per checkout, so it never
    hit it there. The guard makes the distinction explicit rather than leaving
    it to luck.
    """

    @pytest.mark.asyncio
    async def test_a_shared_connection_runs_inline(self):
        import threading

        import infrastructure.db_executor as db_executor

        # The conftest engine is StaticPool, so this is the real production
        # shape for the test suite rather than a simulation.
        from sqlmodel.pool import StaticPool

        from infrastructure.database import engine

        assert isinstance(engine.pool, StaticPool), (
            "this test is only meaningful against a single-connection pool"
        )

        observed = []

        def _work():
            observed.append(threading.current_thread().name)

        await db_executor.run_db(_work)

        assert observed == ["MainThread"], (
            "a shared connection must run on the loop, not a worker thread"
        )

    def test_the_guard_detects_a_shared_pool(self):
        import infrastructure.db_executor as db_executor

        assert db_executor._pool_is_single_connection() is True

    @pytest.mark.asyncio
    async def test_the_queue_pool_shape_does_run_on_a_worker(self):
        """The other half: this must not silently disable offloading everywhere.

        Simulating QueuePool rather than relying on the deployed engine, because
        the test suite's engine is StaticPool by design and the production one is
        not — so testing only the guard would leave the offload untested.
        """
        import threading

        import infrastructure.db_executor as db_executor
        from infrastructure.database import engine

        original = db_executor._pool_is_single_connection
        try:
            db_executor._pool_is_single_connection = lambda: False
            observed = []

            def _work():
                observed.append(threading.current_thread().name)

            await db_executor.run_db(_work)
        finally:
            db_executor._pool_is_single_connection = original

        assert observed and "db-offload" in observed[0], (
            "with a per-checkout pool the work must reach the offload pool"
        )
        assert engine is not None

    @pytest.mark.asyncio
    async def test_job_service_isolated_session_on_multi_connection_pool(self, session, monkeypatch):
        """When _pool_is_single_connection is False, JobService uses isolated sessions for offload work."""
        from services.job_service import JobService
        import infrastructure.db_executor as db_executor

        service = JobService(session)
        job = await service.create_job(task_type="image", workflow={"1": {}}, metadata={})

        monkeypatch.setattr(db_executor, "_pool_is_single_connection", lambda: False)

        updated = await service.update_job(job.id, status=JobStatus.SENT_TO_PROVIDER)
        assert updated.status == JobStatus.SENT_TO_PROVIDER

        read_back = await service.get_job(job.id)
        assert read_back.status == JobStatus.SENT_TO_PROVIDER
