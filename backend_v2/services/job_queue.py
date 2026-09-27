# Job Queue - Async job processing with worker pool
import asyncio
import hashlib
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from config import get_config
from infrastructure.background_tasks import start_background_task
from infrastructure.database import database_url
from infrastructure.logging import get_logger
from services.job_service import STALE_JOB_TIMEOUT_SECONDS

logger = get_logger("job_queue")

# Postgres-backed claim queue mode (SELECT ... FOR UPDATE SKIP LOCKED).
# SQLite (tests / local file dev) keeps the pure in-memory queue behavior.
_DB_CLAIMS_ENABLED = database_url.startswith("postgresql")

_NOTIFY_CHANNEL = "job_queue_wake"


class _PgNotifyListener:
    """Dedicated thread that LISTENs on the Postgres notify channel.

    LISTEN can only run on a real (thread-owned) connection, so the worker
    loops on the event loop never poll the DB: this thread pushes wakeups
    into their asyncio queues via call_soon_threadsafe.
    """

    def __init__(self, queues: tuple[asyncio.Queue, ...], loop: asyncio.AbstractEventLoop):
        self._queues = queues
        self._loop = loop
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="pg-notify-listener",
            daemon=True,
        )
        self._thread.start()
        logger.info("pg_notify_listener_started", channel=_NOTIFY_CHANNEL)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("pg_notify_listener_stopped")

    def _wake(self) -> None:
        for q in self._queues:
            self._loop.call_soon_threadsafe(q.put_nowait, (None, None))

    def _run(self) -> None:
        import select

        try:
            import psycopg2

            conn = psycopg2.connect(database_url)
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute(f"LISTEN {_NOTIFY_CHANNEL}")
            logger.info("pg_notify_listener_listening", channel=_NOTIFY_CHANNEL)
        except Exception as exc:
            logger.warning("pg_notify_listener_connect_failed", error=str(exc))
            return

        try:
            while not self._stop_event.is_set():
                if select.select([conn], [], [], 1.0)[0]:
                    conn.poll()
                    while conn.notifies:
                        conn.notifies.pop(0)
                        self._wake()
        except Exception as exc:
            logger.warning("pg_notify_listener_error", error=str(exc))
        finally:
            try:
                conn.close()
            except Exception as exc:
                logger.debug("pg_notify_listener_close_failed", error=str(exc))


class JobQueue:
    """
    Async job queue with configurable worker pool.
    Replaces the polling-based worker loop with a proper queue.
    """
    
    def __init__(self, max_workers: int = 2, task_type: str = "image"):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._running = False
        self.max_workers = max_workers
        self._task_type = task_type
        # Postgres mode: workers claim PENDING rows from the DB instead of
        # popping an in-process deque. In-process queue is wakeup-only then.
        self._use_db_claims = _DB_CLAIMS_ENABLED
        
        # Job processor callback - set by the API layer
        self._processor: Callable[[str, str | None], Awaitable[None]] | None = None
        
        # Track active jobs
        self._active_jobs: dict[str, asyncio.Task] = {}
        
        # Track workers that should stop after their current job (graceful shutdown)
        self._stopping_workers: set[asyncio.Task] = set()
        
        # Recovery lock to prevent race conditions on startup
    
    def set_processor(self, processor: Callable[[str, str | None], Awaitable[None]]):
        """
        Set the job processing callback.
        
        The callback receives (job_id, provider_id) and should process the job.
        """
        self._processor = processor
    
    async def enqueue(self, job_id: str, provider_id: str | None = None) -> None:
        """
        Add a job to the queue.
        
        Args:
            job_id: Job ID to process
            provider_id: Optional preferred provider ID

        In Postgres mode the payload is wakeup-only: workers claim the actual
        job row from the DB. A NOTIFY is also fired so other processes' workers
        wake up.
        """
        await self._queue.put((job_id, provider_id))
        if self._use_db_claims:
            self._schedule_notify()

    def _schedule_notify(self) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No running event loop (e.g. sync callers) — best-effort only.
            return
        # Tracked, not a bare `asyncio.create_task`: asyncio only holds a weak
        # reference to a running task, and `_notify_wake` immediately awaits
        # `asyncio.to_thread` — exactly the window in which the task is
        # collectable, so the NOTIFY was silently dropped under GC pressure.
        # `start_background_task` also names, logs and cancels it on shutdown.
        start_background_task(
            self._notify_wake(),
            task_name="queue_notify_wake",
            timeout=30.0,
        )

    async def _notify_wake(self) -> None:
        try:
            await asyncio.to_thread(self._notify_wake_sync)
        except Exception as exc:
            logger.debug("queue_notify_failed", error=str(exc))

    @staticmethod
    def _notify_wake_sync() -> None:
        from sqlalchemy import text

        from infrastructure.database import engine

        with engine.begin() as conn:
            conn.execute(text(f"NOTIFY {_NOTIFY_CHANNEL}"))

    def _advisory_key(self) -> int:
        """Stable `pg_advisory_xact_lock` key for this pool's claim section.

        Derived from the task type so the image and llm pools serialise
        independently, and folded into 63 bits because the function takes a
        signed bigint.
        """
        digest = hashlib.blake2b(self._task_type.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, "big") & ((1 << 63) - 1)

    def _max_concurrent(self) -> int:
        """In-flight ceiling for this pool, from `jobs.max_concurrent`.

        The setting was previously exposed and persisted but read by nothing,
        so throttling spend by lowering it silently did nothing. Returns a
        positive int; a missing or nonsensical value falls back to a bound that
        never throttles, so a bad config can never wedge the queue.
        """
        try:
            raw = (get_config() or {}).get("jobs", {}).get("max_concurrent")
            value = int(raw) if raw is not None else 0
        except (TypeError, ValueError):
            value = 0
        return value if value >= 1 else 10**6

    def _claim_next_job_sync(self) -> tuple[str, str | None] | None:
        """Claim the oldest PENDING job for this task_type (Postgres only).

        FOR UPDATE SKIP LOCKED makes concurrent workers/processes safe: each
        PENDING row is claimed exactly once. Runs in a worker thread.

        The ceiling needs two things, and originally had neither:

        * A claimed job keeps `status = 'PENDING'` (the worker transitions it
          when it actually starts), and PENDING was not in the in-flight status
          list, so a just-claimed row was invisible to the count.
        * The in-flight CTE and the UPDATE share one snapshot, so rows claimed
          concurrently by another worker are excluded from the count by
          construction. N workers polling in the same tick all computed
          `in_flight = 0` and all claimed, making the effective bound
          `max_concurrent + max_workers` — with `max_concurrent = 1` and three
          enabled image providers, three jobs reached paid providers.

        So claimed-but-still-PENDING rows are counted, and a transaction-scoped
        advisory lock serialises the count against the claim. The lock is what
        makes the ceiling exact; without it the count can only ever be a snapshot.
        It is Postgres-only, which this whole statement already is.

        Scope is per task_type, not global. The worker pool is already sized
        from the enabled provider count, so a global cap could let image
        saturation starve a chat reply's LLM job — the count would be consumed
        by whichever pool claimed first. Per-type means `max_concurrent` reads
        as "at most N in-flight of each kind", and setting it above the
        provider count is correctly a no-op.
        """
        from sqlalchemy import text

        from infrastructure.database import engine

        claim_sql = text(
            """
            SELECT pg_advisory_xact_lock(:advisory_key)
            """
            if engine.dialect.name == "postgresql"
            else "SELECT 1"
        )
        claim_job_sql = text(
            """
            WITH in_flight AS (
                SELECT count(*) AS n
                FROM jobs
                WHERE task_type = :task_type
                  AND (
                    status IN (
                      'SENT_TO_PROVIDER', 'CONNECTED', 'PRE_GENERATION',
                      'GENERATING', 'POST_PROCESSING', 'RETRYING'
                    )
                    -- A claim sets claimed_at but not status; without this the
                    -- row the previous claimer took is not yet counted.
                    OR (status = 'PENDING' AND claimed_at IS NOT NULL)
                  )
            ),
            candidate AS (
                SELECT id
                FROM jobs
                WHERE task_type = :task_type
                  AND status = 'PENDING'
                  AND claimed_at IS NULL
                ORDER BY created_at, id
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE jobs
            SET claimed_at = now()
            WHERE (SELECT n FROM in_flight) < :max_concurrent
              AND id = (SELECT id FROM candidate)
            RETURNING id, provider_id
            """
        )
        with engine.begin() as conn:
            conn.execute(
                claim_sql, {"advisory_key": self._advisory_key()}
            ).first()
            row = conn.execute(
                claim_job_sql,
                {"task_type": self._task_type, "max_concurrent": self._max_concurrent()},
            ).first()
        if row is None:
            return None
        return row[0], row[1]

    @staticmethod
    def _clear_claim_sync(job_id: str) -> None:
        from sqlalchemy import text

        from infrastructure.database import engine

        with engine.begin() as conn:
            conn.execute(
                text("UPDATE jobs SET claimed_at = NULL WHERE id = :job_id"),
                {"job_id": job_id},
            )

    async def _claim_next_job(self) -> tuple[str, str | None] | None:
        return await asyncio.to_thread(self._claim_next_job_sync)

    async def _clear_claim(self, job_id: str) -> None:
        await asyncio.to_thread(self._clear_claim_sync, job_id)

    async def _get_job_payload(self) -> tuple[str, str | None] | None:
        """Return the next (job_id, provider_id) to process.

        Postgres mode: claim from the DB, falling back to waiting on the
        in-process queue for a wakeup (NOTIFY from other processes, or local
        enqueue) and then re-claiming.
        SQLite mode: pop the in-process queue payload directly.
        """
        if not self._use_db_claims:
            try:
                return await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                return None

        claimed = await self._claim_next_job()
        if claimed is not None:
            # Claimed without a wakeup — drain stale wakeups so the in-process
            # queue can't grow unboundedly during long-running jobs.
            # In Postgres mode the queue is wakeup-only; we discard items
            # WITHOUT calling task_done() because the worker will not call it
            # either (task_done is only used in SQLite in-process mode).
            if self._use_db_claims:
                while True:
                    try:
                        self._queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
            else:
                while True:
                    try:
                        self._queue.get_nowait()
                        self._queue.task_done()
                    except asyncio.QueueEmpty:
                        break
            return claimed

        try:
            await asyncio.wait_for(self._queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            return None

        # Wakeup received — try to claim again.
        # In Postgres mode the queue item is a wakeup signal only;
        # we must not call task_done() (it would unbalance the counter
        # and the worker does not call it in DB-claim mode).
        if not self._use_db_claims:
            self._queue.task_done()
        return await self._claim_next_job()
    
    async def start(self) -> None:
        """Start the worker pool."""
        if self._running:
            return
        
        self._running = True
        
        for i in range(self.max_workers):
            task = asyncio.create_task(self._worker(i))
            self._workers.append(task)
        
        logger.info("job_queue_started", workers=self.max_workers)
    
    async def stop(self, timeout_seconds: float = 30.0) -> None:
        """Stop the worker pool gracefully, allowing active jobs to drain first."""
        if not self._running and not self._workers:
            return

        self._running = False

        if self._workers:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._workers, return_exceptions=True),
                    timeout=timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "job_queue_stop_timeout",
                    active_jobs=list(self._active_jobs.keys()),
                    worker_count=len(self._workers),
                )
                for worker in self._workers:
                    if not worker.done():
                        worker.cancel()

                await asyncio.gather(*self._workers, return_exceptions=True)
        
        self._workers.clear()
        self._stopping_workers.clear()
        logger.info("job_queue_stopped")

    async def resize(self, new_count: int) -> None:
        """
        Dynamically resize the worker pool.
        
        Args:
            new_count: New number of workers (must be >= 1)
        """
        new_count = max(new_count, 1)
            
        current_count = len(self._workers)
        if new_count == current_count:
            return
            
        logger.info("job_queue_resizing", from_count=current_count, to_count=new_count)
        self.max_workers = new_count
        
        if new_count > current_count:
            # Scale up
            to_add = new_count - current_count
            for i in range(to_add):
                # Worker IDs continue from where we left off (roughly)
                worker_id = current_count + i
                task = asyncio.create_task(self._worker(worker_id))
                self._workers.append(task)
            logger.info("job_queue_resized", from_count=current_count, to_count=new_count, added=to_add)
            
        else:
            # Scale down
            to_remove = current_count - new_count
            
            # Identify busy vs idle workers
            active_tasks = set(self._active_jobs.values())
            idle_workers = []
            busy_workers = []
            
            for task in self._workers:
                if task in active_tasks:
                    busy_workers.append(task)
                else:
                    idle_workers.append(task)
            
            removed_count = 0
            idle_cancelled = 0
            busy_draining = 0

            # 1. Prioritize removing idle workers (cancel immediately)
            while to_remove > 0 and idle_workers:
                task = idle_workers.pop()
                if task in self._workers:
                    self._workers.remove(task)
                    task.cancel()
                    removed_count += 1
                    idle_cancelled += 1
                    to_remove -= 1

            # 2. If still need to remove, mark busy workers to drain (graceful stop)
            while to_remove > 0 and busy_workers:
                task = busy_workers.pop()
                if task in self._workers:
                    self._workers.remove(task)
                    self._stopping_workers.add(task)
                    logger.debug("worker_draining", reason="pool_downsize")
                    removed_count += 1
                    busy_draining += 1
                    to_remove -= 1

            # Counted in the loops, not measured from the lists afterwards: both
            # lists are popped empty, so `len(...)` here always read 0 and the
            # log claimed nothing had been removed however many workers went.
            logger.info(
                "job_queue_resize_complete",
                removed=removed_count,
                idle_cancelled=idle_cancelled,
                busy_draining=busy_draining,
            )
    
    async def _worker(self, worker_id: int) -> None:
        """Worker coroutine that processes jobs from the queue."""
        logger.info("worker_started", worker_id=worker_id)
        
        while self._running:
            # Check if this worker has been marked for shutdown
            current_task = asyncio.current_task()
            if current_task in self._stopping_workers:
                logger.info("worker_stopping", worker_id=worker_id, reason="graceful_shutdown")
                self._stopping_workers.discard(current_task)
                break

            try:
                # Wait for a job with timeout to allow graceful shutdown checks
                payload = await self._get_job_payload()
                if payload is None:
                    continue

                job_id, provider_id = payload

                if not self._processor:
                    logger.warning("no_processor_set", job_id=job_id, worker_id=worker_id)
                    # SQLite mode: the queue item was popped by _get_job_payload
                    # without task_done; call it here. Postgres mode: queue is
                    # wakeup-only and task_done is not used.
                    if not self._use_db_claims:
                        self._queue.task_done()
                    else:
                        # The `finally` below never runs for this job, so the
                        # DB claim has to be released here. Leaving it set
                        # strands the row: `_claim_next_job_sync` requires
                        # `claimed_at IS NULL`, so the job stays PENDING and
                        # permanently unclaimable — silent job loss, with the
                        # only symptom being a job that never starts.
                        await self._clear_claim(job_id)
                    continue
                
                logger.info("job_processing", job_id=job_id, worker_id=worker_id)
                
                try:
                    # Track active job
                    self._active_jobs[job_id] = current_task
                    
                    # Process the job
                    await self._processor(job_id, provider_id)
                    
                except Exception as e:
                    logger.error("job_failed", job_id=job_id, worker_id=worker_id, error=str(e))
                    # Job failure handling should be done by the processor
                
                finally:
                    # Remove from active jobs
                    self._active_jobs.pop(job_id, None)
                    # SQLite mode: task_done was not called by _get_job_payload,
                    # so we must call it here. Postgres mode: the queue item was
                    # already consumed/discarded by _get_job_payload without
                    # task_done (wakeup-only queue), so we must NOT call it again.
                    if not self._use_db_claims:
                        self._queue.task_done()
                    # Release the DB claim so recovery/queueing stays consistent.
                    if self._use_db_claims:
                        await self._clear_claim(job_id)
                    
            except asyncio.CancelledError:
                logger.info("worker_cancelled", worker_id=worker_id)
                break
            except Exception as e:
                logger.error("worker_error", worker_id=worker_id, error=str(e))
                await asyncio.sleep(1)
        
        logger.info("worker_stopped", worker_id=worker_id)
    
    @property
    def pending_count(self) -> int:
        """Number of jobs waiting in queue."""
        return self._queue.qsize()
    
    @property
    def active_count(self) -> int:
        """Number of jobs currently being processed."""
        return len(self._active_jobs)
    
    def is_job_active(self, job_id: str) -> bool:
        """Check if a job is currently being processed."""
        return job_id in self._active_jobs
    
# ---------------------------------------------------------------------------
# QueueManager — typed queues for image and LLM jobs
# ---------------------------------------------------------------------------

class QueueManager:
    """
    Holds separate JobQueue instances for image and LLM task types.
    
    This prevents image generation workers and LLM inference workers from
    competing for the same queue slots.  Each queue is sized independently
    based on the number of enabled providers of that type.
    """

    def __init__(self) -> None:
        self.image: JobQueue = JobQueue(max_workers=1, task_type="image")
        self.llm: JobQueue = JobQueue(max_workers=1, task_type="llm")
        self._processor: Callable[[str, str | None], Awaitable[None]] | None = None
        self._notify_listener: _PgNotifyListener | None = None
        # In-flight pool resizes. Held so `stop()` can drain them: a resize that
        # is still pending when shutdown starts would otherwise land after the
        # workers were cancelled and leave the pool at the wrong size (or
        # resurrect a worker task on a closed loop).
        self._resize_tasks: set[asyncio.Task[Any]] = set()

    def set_processor(self, processor: Callable[[str, str | None], Awaitable[None]]) -> None:
        """Register the same processor on both queues."""
        self._processor = processor
        self.image.set_processor(processor)
        self.llm.set_processor(processor)

    def get_queue(self, task_type: str) -> "JobQueue":
        """Return the appropriate queue for a task type."""
        if task_type == "llm":
            return self.llm
        return self.image

    async def enqueue(self, job_id: str, provider_id: str | None = None, task_type: str = "image") -> None:
        """Enqueue a job into the correct typed queue."""
        await self.get_queue(task_type).enqueue(job_id, provider_id)

    async def start(self) -> None:
        """Start both queues."""
        await self.image.start()
        await self.llm.start()
        if _DB_CLAIMS_ENABLED:
            self._notify_listener = _PgNotifyListener(
                (self.image._queue, self.llm._queue),
                asyncio.get_running_loop(),
            )
            self._notify_listener.start()
        logger.info("queue_manager_started", image_workers=self.image.max_workers, llm_workers=self.llm.max_workers)

    async def stop(self, timeout_seconds: float = 30.0) -> None:
        """Stop both queues."""
        if self._notify_listener:
            self._notify_listener.stop()
            self._notify_listener = None
        await self._drain_resize_tasks()
        await self.image.stop(timeout_seconds=timeout_seconds)
        await self.llm.stop(timeout_seconds=timeout_seconds)
        logger.info("queue_manager_stopped")

    async def _drain_resize_tasks(self) -> None:
        """Cancel and await any in-flight pool resizes."""
        pending = list(self._resize_tasks)
        if not pending:
            return
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        self._resize_tasks.clear()

    def resize(self, image_workers: int, llm_workers: int) -> None:
        """Resize both queues.

        Pre-start (during startup_helpers.configure_worker_pool): updates
        max_workers so ``start()`` spawns the right number of workers.

        Post-start (provider changes at runtime): spawns async resize tasks
        that actually add/remove worker coroutines. Those are tracked in
        ``_resize_tasks`` (and drained by ``stop()``) rather than left to
        ``asyncio.create_task`` — an untracked task mutates ``queue._workers``
        and asyncio only holds a weak reference to it, so it could be collected
        mid-flight and silently leave the pool at the old size.
        """
        self.image.max_workers = max(1, image_workers)
        self.llm.max_workers = max(1, llm_workers)

        for queue, count in ((self.image, image_workers), (self.llm, llm_workers)):
            if not queue._running:
                continue
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                continue
            task = start_background_task(
                queue.resize(count),
                task_name=f"queue_resize:{queue._task_type}",
                timeout=60.0,
            )
            self._resize_tasks.add(task)
            task.add_done_callback(self._resize_tasks.discard)

    async def recover_pending_jobs(self, job_service) -> tuple:
        """Recover pending jobs, routing each to the correct queue by task_type."""

        summary = await self.recover(job_service)
        return summary["recovered"], summary["failed"]

    async def recover(
        self,
        job_service,
        *,
        timeout_seconds: int = STALE_JOB_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Requeue interrupted work and fail jobs wedged past the stale timeout.

        Used at startup and by `POST /api/jobs/recover`, so an operator can run
        the exact same recovery on a live instance when a worker dies without
        taking the queue down. Returns a summary instead of raising.
        """
        stale_jobs = await job_service.fail_stale_running_jobs(timeout_seconds=timeout_seconds)
        stale_ids = {job.id for job in stale_jobs}

        pending = list(job_service.get_pending_jobs())
        running = list(job_service.get_running_jobs())
        recoverable_running = [job for job in running if job.id not in stale_ids]

        summary: dict[str, Any] = {
            "mode": "db_claims" if _DB_CLAIMS_ENABLED else "in_memory",
            "recovered": 0,
            "failed": len(stale_jobs),
            "failed_job_ids": [job.id for job in stale_jobs],
            "pending": len(pending),
            "running": len(recoverable_running),
        }

        if _DB_CLAIMS_ENABLED:
            # DB mode: claims are stale after a restart. Reset every active job
            # back to PENDING (same semantic as lifecycle requeue) and clear all
            # claims so workers can re-claim them from the DB.
            await asyncio.to_thread(self._reset_claims_and_requeue_sync)
            summary["recovered"] = len(pending) + len(recoverable_running)
            self.image._schedule_notify()
            self.llm._schedule_notify()
            logger.info("queue_manager_recovery_db_reset", pending=len(pending), running=len(recoverable_running))
            return summary

        for job in [*pending, *recoverable_running]:
            task_type = getattr(job, "task_type", "image") or "image"
            await self.get_queue(task_type).enqueue(job.id, job.provider_id)
            summary["recovered"] += 1

        if summary["recovered"] > 0 or summary["failed"] > 0:
            logger.info("queue_manager_recovery_complete", recovered=summary["recovered"], failed=summary["failed"])

        return summary

    @staticmethod
    def _reset_claims_and_requeue_sync() -> None:
        """Reset all jobs to PENDING and clear claim markers (Postgres only).

        Runs after a backend restart: in-flight jobs were interrupted and their
        claim markers are stale. Terminal jobs (COMPLETED/FAILED/CANCELLED) are
        left untouched.
        """
        from sqlalchemy import text

        from infrastructure.database import engine

        with engine.begin() as conn:
            conn.execute(text(
                """
                UPDATE jobs
                SET status = 'PENDING', started_at = NULL, claimed_at = NULL
                WHERE status IN ('SENT_TO_PROVIDER', 'CONNECTED', 'PRE_GENERATION', 'GENERATING', 'POST_PROCESSING', 'RETRYING')
                   OR (status = 'PENDING' AND claimed_at IS NOT NULL)
                """
            ))

    # ---- Delegate properties for backwards-compat callers ----

    @property
    def pending_count(self) -> int:
        return self.image.pending_count + self.llm.pending_count

    @property
    def active_count(self) -> int:
        return self.image.active_count + self.llm.active_count


# ---------------------------------------------------------------------------
# Global singletons
# ---------------------------------------------------------------------------

# Typed queue manager — primary entry point for all new job submissions.
queue_manager = QueueManager()
