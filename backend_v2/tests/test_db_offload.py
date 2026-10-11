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
        """Proved by the thread the work actually executed on.

        Not by diffing the pool's thread set: the pool creates threads lazily,
        so a test that runs after another has already spawned one sees an empty
        diff and passes for the wrong reason.
        """
        import threading

        import services.job_service as job_service_mod
        from services.job_service import JobService

        observed = []
        real_run_db = job_service_mod.run_db

        async def _spy(fn, *args):
            # Trace INSIDE the sync body. Recording the coroutine's own thread
            # always answers MainThread, which is the bug these tests exist to
            # catch — and it makes the test pass for the wrong reason.
            def _traced(*a, **kw):
                observed.append(threading.current_thread().name)
                return fn(*a, **kw)

            return await real_run_db(_traced, *args)

        monkeypatch.setattr(job_service_mod, "run_db", _spy)

        service = JobService(session)
        job = await service.create_job(task_type="image", workflow={"1": {}}, metadata={})
        observed.clear()

        await service.update_job(job.id, status=JobStatus.PRE_GENERATION)

        assert observed, "update_job did not route its DB work through run_db"
        assert all("db-offload" in name for name in observed), (
            f"DB work ran on {observed}"
        )

    @pytest.mark.asyncio
    async def test_get_job_runs_on_a_db_offload_thread(self, session, monkeypatch):
        import threading

        import services.job_service as job_service_mod
        from services.job_service import JobService

        observed = []
        real_run_db = job_service_mod.run_db

        async def _spy(fn, *args):
            # Trace INSIDE the sync body. Recording the coroutine's own thread
            # always answers MainThread, which is the bug these tests exist to
            # catch — and it makes the test pass for the wrong reason.
            def _traced(*a, **kw):
                observed.append(threading.current_thread().name)
                return fn(*a, **kw)

            return await real_run_db(_traced, *args)

        monkeypatch.setattr(job_service_mod, "run_db", _spy)

        service = JobService(session)
        job = await service.create_job(task_type="image", workflow={"1": {}}, metadata={})
        observed.clear()

        await service.get_job(job.id)

        assert observed and all("db-offload" in name for name in observed)

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
        """
        from core.events import event_bus
        from services.job_service import JobService

        service = JobService(session)
        job = await service.create_job(task_type="image", workflow={"1": {}}, metadata={})

        seen = []
        event_bus.subscribe(lambda event: seen.append(event), "job")

        # PENDING -> COMPLETED is not an allowed transition.
        await service.update_job(job.id, status=JobStatus.COMPLETED, outputs=[])

        assert not any(e.type == "job.completed" for e in seen), (
            "an illegal transition emitted a completion event"
        )
        assert job.status == JobStatus.PENDING
