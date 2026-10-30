# Job Queue - Async job processing with worker pool
import asyncio
import hashlib
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from config import get_config
from core.entities import (
    ACTIVE_JOB_STATUSES,
    CATEGORY_CLAIM_TASK_TYPES,
    CATEGORY_IMAGE,
    CATEGORY_LLM,
    CATEGORY_TTS,
    JobStatus,
)
from infrastructure.background_tasks import start_background_task
from infrastructure.database import database_url
from infrastructure.logging import get_logger
from services.job_service import (
    STRANDED_PENDING_TIMEOUT_SECONDS,
)

logger = get_logger("job_queue")

# Postgres-backed claim queue mode (SELECT ... FOR UPDATE SKIP LOCKED).
# SQLite (tests / local file dev) keeps the pure in-memory queue behavior.
_DB_CLAIMS_ENABLED = database_url.startswith("postgresql")

_NOTIFY_CHANNEL = "job_queue_wake"

# Backoff between `_PgNotifyListener` reconnect attempts. Capped rather than
# exponential-and-forever: a database that is down for an hour should still be
# retried every 30 s, not drift out to minutes.
_RECONNECT_BACKOFF_SECONDS = (1.0, 2.0, 5.0, 10.0, 30.0)


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

    def _connect_and_listen(self):
        """Open a dedicated connection and `LISTEN`. Raises on failure."""
        import psycopg2

        conn = psycopg2.connect(database_url)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(f"LISTEN {_NOTIFY_CHANNEL}")
        logger.info("pg_notify_listener_listening", channel=_NOTIFY_CHANNEL)
        return conn

    def _pump(self, conn) -> None:
        """Drain notifications until the socket closes or `stop()` is called.

        Raises whatever psycopg2 raises once the connection is gone, which is
        the signal for `_run` to reconnect.
        """
        import select

        while not self._stop_event.is_set():
            if select.select([conn], [], [], 1.0)[0]:
                conn.poll()
                while conn.notifies:
                    conn.notifies.pop(0)
                    self._wake()

    def _run(self) -> None:
        """Connect, listen, and RECONNECT until stopped.

        The thread used to `return` on a connect failure and fall out of the
        loop on a runtime error, in both cases logging exactly one line. Nothing
        called `start()` again, so a single dropped connection silently ended
        cross-process wakeups for the rest of the container's life: workers still
        claimed jobs correctly (the Postgres claim query is independent) but
        every wakeup fell back to the 1 s timeout, so a single-process deployment
        looked fine and a multi-process one degraded with nothing but a warning
        to show for it.

        A bounded backoff rather than an external supervisor, because the failure
        mode is a dead thread and a dead thread cannot report itself. The delay
        list is capped so a database that is down for an hour is retried every
        30 s instead of backing off exponentially forever.

        `self._stop_event.wait(delay)` rather than `time.sleep`, so `stop()`
        stays responsive instead of waiting out the backoff.
        """
        attempt = 0
        while not self._stop_event.is_set():
            try:
                conn = self._connect_and_listen()
            except Exception as exc:
                delay = _RECONNECT_BACKOFF_SECONDS[
                    min(attempt, len(_RECONNECT_BACKOFF_SECONDS) - 1)
                ]
                attempt += 1
                logger.warning(
                    "pg_notify_listener_connect_failed",
                    error=str(exc),
                    attempt=attempt,
                    retry_in=delay,
                )
                self._stop_event.wait(delay)
                continue

            attempt = 0
            try:
                self._pump(conn)
                # A clean exit means `stop()` was called; nothing to do but stop.
                break
            except Exception as exc:
                logger.warning(
                    "pg_notify_listener_error",
                    error=str(exc),
                    reconnecting=True,
                )
            finally:
                try:
                    conn.close()
                except Exception as exc:
                    logger.debug("pg_notify_listener_close_failed", error=str(exc))
            # Back off a little even after a successful connect, so a database
            # that accepts connections and immediately drops them cannot spin
            # this thread at full speed.
            self._stop_event.wait(_RECONNECT_BACKOFF_SECONDS[0])



class JobQueue:
    """
    Async job queue with configurable worker pool.
    Replaces the polling-based worker loop with a proper queue.
    """
    
    def __init__(
        self,
        max_workers: int = 2,
        task_type: str = "image",
        claim_task_types: frozenset[str] | None = None,
    ):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._running = False
        self.max_workers = max_workers
        self._task_type = task_type
        # Which `jobs.task_type` values this pool is allowed to claim. A pool is
        # a *physical* grouping — one worker loop, one `max_concurrent` budget,
        # one advisory lock — so it can serve more than one task type. This was
        # the bug behind TTS jobs hanging forever: `tts` routed to the image
        # pool (`get_queue`), but the claim query bound the single
        # `self._task_type == "image"`, so a `tts` row could never be a
        # candidate. The wakeup on the in-process queue is only a hint; the
        # worker re-claims from the DB by this predicate, so the job sat
        # PENDING forever with no error written.
        self._claim_task_types = frozenset(claim_task_types or (task_type,))
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

        This is the single funnel every dispatch path goes through — 20 call
        sites, from `/api/generate` to the idle simulator — so it is also where
        `enqueued_at` is stamped. The claim query requires that column, which
        is what keeps a job that was created to be run *inline* (the agentic
        narrator, which holds its parent's queue slot) from also being claimed
        and dispatched a second time.
        """
        await asyncio.to_thread(self._mark_enqueued, job_id)
        await self._queue.put((job_id, provider_id))
        if self._use_db_claims:
            self._schedule_notify()

    def _mark_enqueued(self, job_id: str) -> None:
        """Stamp `enqueued_at` so the claim query can see this row.

        Best-effort and idempotent: the `IS NULL` predicate means a retry or a
        duplicate enqueue cannot move the stamp.

        The failure mode splits on `_use_db_claims`, which is why this used to
        be wrong in the one direction that mattered. On SQLite the stamp cannot
        succeed at all — SQLite has no `now()` function, so the statement below
        raises every single time — and there is no claim query, so a job already
        sitting in the in-process queue runs regardless. Swallowing is the
        documented and correct behaviour there. On Postgres the claim query
        requires `enqueued_at IS NOT NULL`, so a swallowed failure leaves a row
        that is PENDING, never claimable, never failed, and not covered by
        `recover`: counted in `summary["pending"]` forever with no owner. So
        there the error propagates, which is what lets
        `JobSubmissionService.submit_job` reach its compensating delete — a
        delete that is unreachable for every other reason, because this was the
        only failure that stranded a row.
        """
        from infrastructure.database import engine
        from sqlmodel import Session, text

        # Portable stamp: production (Postgres, `_use_db_claims`) uses `now()`,
        # which the claim query's `IS NOT NULL` predicate relies on. On SQLite
        # (the unit-test / dev engine, where claims are off) `now()` does not
        # exist, so use SQLite's own `datetime('now')` instead — otherwise
        # every enqueue on a SQLite-backed stack would fail to stamp and, when
        # claims happen to be forced on (the propagation test), would mask the
        # real failure mode the test exists to exercise.
        _stamp_fn = "now()" if self._use_db_claims else "datetime('now')"
        try:
            with Session(engine) as session:
                session.execute(
                    text(f"UPDATE jobs SET enqueued_at = {_stamp_fn} WHERE id = :id AND enqueued_at IS NULL"),
                    {"id": job_id},
                )
                session.commit()
        except Exception as exc:
            logger.error("job_enqueue_stamp_failed", job_id=job_id, error=str(exc))
            if self._use_db_claims:
                raise

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

    def _claim_lease_seconds(self) -> int:
        """How long a claim may be held before it counts as leaked.

        A claim is taken when the worker picks the job up and released when
        the job finishes, so it is held for the whole run of the job - which
        may be as long as that task type's timeout. The lease therefore has
        to EXCEED the longest legal run of this pool, or a slow-but-healthy
        job would be reclaimed and paid for twice.

        It exists because the claim had no expiry at all: `claimed_at` was
        written, cleared and read only as a NULL / non-NULL flag, and the
        release was a bare `await` in a `finally` whose DB error escaped into
        the worker's outer handler. One leaked claim stranded a PENDING job
        forever AND permanently consumed one of the pool's concurrency slots,
        so five leaks deadlocked the pool.
        """
        from config import get_job_timeout

        longest = 0
        for task_type in self._claim_task_types:
            try:
                longest = max(longest, int(get_job_timeout(task_type)))
            except Exception:
                continue
        if longest <= 0:
            longest = 3600
        # A margin, so a job that finishes at exactly its timeout does not
        # race the lease.
        return longest + 300

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

        Scope is per pool, not global. The worker pool is already sized
        from the enabled provider count, so a global cap could let image
        saturation starve a chat reply's LLM job — the count would be consumed
        by whichever pool claimed first. Per-pool means `max_concurrent` reads
        as "at most N in-flight of each pool", and setting it above the
        provider count is correctly a no-op.

        A pool claims every task type in `self._claim_task_types`, not just its
        own name, and counts them together in the ceiling: image and tts share
        one Modal container budget, so an image job in flight has to count
        against a tts job's cap or the container is oversubscribed.

        The task-type predicate is rendered as an expanded `IN` list rather
        than `= ANY(:param)`: `ANY` needs a driver-level array adapter, which
        the SQLite path used by the test suite does not provide, and a claim
        that only works on one dialect is a claim that only gets tested on one.
        """
        from sqlalchemy import text

        from infrastructure.database import engine

        task_types = sorted(self._claim_task_types)
        type_predicate = "task_type IN (" + ", ".join(f":tt_{i}" for i in range(len(task_types))) + ")"
        type_params = {f"tt_{i}": value for i, value in enumerate(task_types)}
        # The status list is interpolated from the same `ACTIVE_JOB_STATUSES`
        # the Python paths use, not re-typed as SQL string literals: a seventh
        # status added to the enum would otherwise make the queue's own
        # headroom arithmetic disagree with the runners that populate it.
        active_status_placeholders = "(" + ", ".join(
            f":as_{i}" for i in range(len(ACTIVE_JOB_STATUSES))
        ) + ")"
        # `.name`, not `.value`: SQLAlchemy persists a Python Enum under its
        # NAME ('GENERATING'), and these literals were originally written by
        # hand as the uppercase name. Reading `.value` here would send
        # 'generating', match nothing, and report a clean queue that is
        # saturated — silently, on the one statement no test executed.
        type_params.update(
            {f"as_{i}": status.name for i, status in enumerate(ACTIVE_JOB_STATUSES)}
        )

        claim_sql = text(
            """
            SELECT pg_advisory_xact_lock(:advisory_key)
            """
            if engine.dialect.name == "postgresql"
            else "SELECT 1"
        )
        claim_job_sql = text(
            f"""
            WITH in_flight AS (
                SELECT count(*) AS n
                FROM jobs
                WHERE {type_predicate}
                  AND (
                    status IN {active_status_placeholders}
                    -- A claim sets claimed_at but not status; without this the
                    -- row the previous claimer took is not yet counted.
                    -- An EXPIRED claim is not counted either: a leaked claim
                    -- used to hold a concurrency slot forever.
                    OR (
                        status = 'PENDING'
                        AND claimed_at IS NOT NULL
                        AND claimed_at >= now() - make_interval(secs => :lease_seconds)
                    )
                  )
            ),
            candidate AS (
                SELECT id
                FROM jobs
                WHERE {type_predicate}
                  AND status = 'PENDING'
                  AND (
                    claimed_at IS NULL
                    OR claimed_at < now() - make_interval(secs => :lease_seconds)
                  )
                  -- Only rows that were actually handed to the queue. A job row
                  -- can exist purely as an event carrier for work its creator
                  -- runs inline (the agentic narrator holds its parent's queue
                  -- slot, so a queued narrator job could never be claimed).
                  -- Without this predicate the LLM worker claimed those too:
                  -- two paid calls per narration and the same paragraph
                  -- inserted into the chat twice.
                  AND enqueued_at IS NOT NULL
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
                {
                    **type_params,
                    "max_concurrent": self._max_concurrent(),
                    "lease_seconds": self._claim_lease_seconds(),
                },
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
        """Release the DB claim, and never let a failure here leak it.

        The release is the LAST thing the worker does with a job, and it used
        to be a bare `await` in a `finally`. A DB error there raised out of
        the `finally`, was caught by the worker's outer handler, and the
        worker carried on - WITH THE CLAIM STILL SET. The job was then
        PENDING-with-claim forever: `_claim_next_job_sync` requires
        `claimed_at IS NULL`, so it was never claimed again, never ran, and
        never failed. It also counted in the in-flight CTE, so it held one
        of the pool's concurrency slots for good.

        So the release is retried once and, if it still fails, logged at
        ERROR rather than being allowed to escape: the lease (see
        `_claim_lease_seconds`) is the backstop for a claim that really
        cannot be released.
        """
        for attempt in (1, 2):
            try:
                await asyncio.to_thread(self._clear_claim_sync, job_id)
                return
            except Exception as exc:
                if attempt == 2:
                    logger.error(
                        "job_claim_release_failed",
                        job_id=job_id,
                        error=str(exc),
                    )
                    return
                logger.warning(
                    "job_claim_release_retry",
                    job_id=job_id,
                    error=str(exc),
                )

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
            # Unreachable to test: the `not self._use_db_claims` early return
            # above means only the DB-claims mode reaches here.
            while True:
                try:
                    self._queue.get_nowait()
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

    #: One pool per provider CATEGORY, and each pool claims only its own task
    #: type. Before this, there were two pools and `tts` was squeezed into the
    #: image one: pool sizing counted every non-`llm` provider as an image worker,
    #: while `ENGINE_TASK_TYPES = {image, tts}` let tts jobs claim from it. The
    #: result was the ambiguity the provider page could never explain — a "TTS
    #: worker" that sized as image capacity and were served by a pool named
    #: "image". One category, one pool, one claim set.
    POOLS = (
        (CATEGORY_IMAGE, CATEGORY_IMAGE),
        (CATEGORY_LLM, CATEGORY_LLM),
        (CATEGORY_TTS, CATEGORY_TTS),
    )

    def __init__(self) -> None:
        self.pools: dict[str, JobQueue] = {
            name: JobQueue(
                max_workers=1,
                task_type=name,
                claim_task_types=CATEGORY_CLAIM_TASK_TYPES[name],
            )
            for name in (CATEGORY_IMAGE, CATEGORY_LLM, CATEGORY_TTS)
        }
        # Attribute access kept for every existing caller, including tests that
        # reach for `queue_manager.image`. The tts pool is the new one.
        self.image = self.pools[CATEGORY_IMAGE]
        self.llm = self.pools[CATEGORY_LLM]
        self.tts = self.pools[CATEGORY_TTS]
        self._processor: Callable[[str, str | None], Awaitable[None]] | None = None
        self._notify_listener: _PgNotifyListener | None = None
        # In-flight pool resizes. Held so `stop()` can drain them: a resize that
        # is still pending when shutdown starts would otherwise land after the
        # workers were cancelled and leave the pool at the wrong size (or
        # resurrect a worker task on a closed loop).
        self._resize_tasks: set[asyncio.Task[Any]] = set()

    def set_processor(self, processor: Callable[[str, str | None], Awaitable[None]]) -> None:
        """Register the same processor on every queue."""
        self._processor = processor
        for queue in self.pools.values():
            queue.set_processor(processor)

    def get_queue(self, task_type: str) -> "JobQueue":
        """Return the queue that serves a task type.

        One queue per category, so a task type maps to exactly one pool and an
        unknown type has nowhere to land rather than defaulting onto the image
        pool by omission — which is what "anything that isn't llm" used to mean,
        and how a fourth category would have quietly shared image capacity.
        """
        if task_type in self.pools:
            return self.pools[task_type]
        raise KeyError(f"no job pool for task type {task_type!r}")

    def is_job_active_anywhere(self, job_id: str) -> bool:
        """Is this job being processed by ANY of the pools?

        `JobQueue.is_job_active` is per-pool, so a caller that remembered
        two of the three pools silently could not cancel the third. The
        websocket cancel handler checked the image and LLM pools and not the
        TTS pool, so a running TTS generation answered "cannot cancel" and
        the provider kept working - and billing.
        """
        return any(pool.is_job_active(job_id) for pool in self.pools.values())


    async def enqueue(self, job_id: str, provider_id: str | None = None, task_type: str = "image") -> None:
        """Enqueue a job into the correct typed queue."""
        await self.get_queue(task_type).enqueue(job_id, provider_id)

    async def start(self) -> None:
        """Start every queue."""
        for queue in self.pools.values():
            await queue.start()
        if _DB_CLAIMS_ENABLED:
            self._notify_listener = _PgNotifyListener(
                tuple(queue._queue for queue in self.pools.values()),
                asyncio.get_running_loop(),
            )
            self._notify_listener.start()
        logger.info(
            "queue_manager_started",
            workers={name: queue.max_workers for name, queue in self.pools.items()},
        )

    async def stop(self, timeout_seconds: float = 30.0) -> None:
        """Stop every queue."""
        if self._notify_listener:
            self._notify_listener.stop()
            self._notify_listener = None
        await self._drain_resize_tasks()
        for queue in self.pools.values():
            await queue.stop(timeout_seconds=timeout_seconds)
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

    def resize(self, **workers_by_category: int) -> None:
        """Resize any subset of the category pools.

        Pre-start (during startup_helpers.configure_worker_pool): updates
        max_workers so ``start()`` spawns the right number of workers.

        Post-start (provider changes at runtime): spawns async resize tasks
        that actually add/remove worker coroutines. Those are tracked in
        ``_resize_tasks`` (and drained by ``stop()``) rather than left to
        ``asyncio.create_task`` — an untracked task mutates ``queue._workers``
        and asyncio only holds a weak reference to it, so it could be collected
        mid-flight and silently leave the pool at the old size.

        Keyword form so a caller resizes the pool it changed and the others keep
        their size: the old positional pair forced every caller — including the
        provider monitor — to decide all three counts at once, which is how the
        tts pool came to be invisible to the sizing logic entirely.
        """
        for name, count in workers_by_category.items():
            if name not in self.pools:
                raise KeyError(f"unknown job pool {name!r}")
            self.pools[name].max_workers = max(1, int(count))

        for name, queue in self.pools.items():
            if name not in workers_by_category or not queue._running:
                continue
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                continue
            task = start_background_task(
                queue.resize(self.pools[name].max_workers),
                task_name=f"queue_resize:{name}",
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
        timeout_seconds: int | None = None,
        stranded_timeout_seconds: int = STRANDED_PENDING_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Requeue interrupted work and fail jobs wedged past the stale timeout.

        Used at startup and by `POST /api/jobs/recover`, so an operator can run
        the exact same recovery on a live instance when a worker dies without
        taking the queue down. Returns a summary instead of raising.

        `timeout_seconds=None` means "use each job's own task-type timeout".
        A single global window was 300 seconds, against a legal image timeout
        of 3600, so recovery failed generations that were still running.
        """
        stale_jobs = await job_service.fail_stale_running_jobs(timeout_seconds=timeout_seconds)
        stale_ids = {job.id for job in stale_jobs}

        # A PENDING row with no `enqueued_at` can never be claimed (the claim
        # query requires the stamp) and nothing else touches it, so it used to
        # be counted in `summary["pending"]` on every recovery run, forever.
        # `_mark_enqueued` propagating makes a new one impossible on Postgres;
        # this makes an existing one visible and terminal.
        stranded_jobs = await job_service.fail_stranded_pending_jobs(
            timeout_seconds=stranded_timeout_seconds
        )
        stranded_ids = {job.id for job in stranded_jobs}

        # `fail_stranded_pending_jobs` already marked them FAILED, so a count
        # taken now excludes them. No further subtraction of `stranded_ids`.
        pending_total = job_service.count_pending_jobs()
        running = list(job_service.get_running_jobs())
        recoverable_running = [job for job in running if job.id not in stale_ids]
        recoverable_running_ids = {job.id for job in recoverable_running}

        summary: dict[str, Any] = {
            "mode": "db_claims" if _DB_CLAIMS_ENABLED else "in_memory",
            "recovered": 0,
            "failed": len(stale_jobs) + len(stranded_jobs),
            "failed_job_ids": [job.id for job in stale_jobs]
            + [job.id for job in stranded_jobs],
            "failed_stranded_job_ids": [job.id for job in stranded_jobs],
            "pending": pending_total,
            "running": len(recoverable_running),
        }

        if _DB_CLAIMS_ENABLED:
            # DB mode: claims are stale after a restart. Reset every active job
            # back to PENDING (same semantic as lifecycle requeue) and clear all
            # claims so workers can re-claim them from the DB.
            await asyncio.to_thread(self._reset_claims_and_requeue_sync)
            summary["recovered"] = pending_total + len(recoverable_running)
            for queue in self.pools.values():
                queue._schedule_notify()
            logger.info("queue_manager_recovery_db_reset", pending=pending_total, running=len(recoverable_running))
            return summary

        pending = [
            job
            for job in job_service.get_pending_jobs()
            if job.id not in stranded_ids
        ]

        for job in [*pending, *recoverable_running]:
            task_type = getattr(job, "task_type", "image") or "image"
            # In-memory mode: a job that was ACTIVE when the process died is
            # still in its active status, and `execute_job` refuses to run
            # anything that is not PENDING - it logs `job_not_pending` at DEBUG
            # and returns. So the job was re-enqueued, popped, skipped, and
            # left "generating" until the next boot's stale sweep.
            #
            # The DB branch resets those rows; this branch has to as well.
            if job.id in recoverable_running_ids:
                await job_service.update_job(
                    job.id,
                    status=JobStatus.PENDING,
                    claimed_at=None,
                    started_at=None,
                )
            await self.get_queue(task_type).enqueue(job.id, job.provider_id)
            summary["recovered"] += 1

        if summary["recovered"] > 0 or summary["failed"] > 0:
            logger.info("queue_manager_recovery_complete", recovered=summary["recovered"], failed=summary["failed"])

        return summary

    @staticmethod
    def _reset_claims_and_requeue_sync() -> None:
        """Reset active jobs to PENDING and clear claim markers (Postgres only).

        Runs after a backend restart: in-flight jobs were interrupted and their
        claim markers are stale. Terminal jobs (COMPLETED/FAILED/CANCELLED) are
        left untouched.

        POST_PROCESSING is EXCLUDED, and that exclusion is the second guard
        against paying twice for the same image.

        A job in POST_PROCESSING has already been generated and paid for; it
        is writing its outputs. PENDING-with-no-claim IS the claim predicate,
        so a POST_PROCESSING job that this sweep moved to PENDING would be
        picked up by a live worker and the entire generation would run again.

        The first guard is the ordering in `_run_job_recovery_phase`: the
        post-processing jobs are finished BEFORE this sweep runs. That guard
        depends on the finalisation actually completing, which is why the
        recovery path awaits it rather than scheduling it. This one does not
        depend on anything: even if the ordering is broken, a
        POST_PROCESSING job is not re-queued.
        """
        from sqlalchemy import text

        from core.entities import ACTIVE_JOB_STATUSES
        from infrastructure.database import engine

        # Same expanding-placeholder form as the claim query, and for the same
        # documented reason: a bound list needs an array adapter SQLite's
        # driver does not provide, and a reset that only runs on Postgres is a
        # reset that never gets tested.
        placeholders = "(" + ", ".join(f":as_{i}" for i in range(len(ACTIVE_JOB_STATUSES))) + ")"
        params = {
            f"as_{i}": status.name for i, status in enumerate(ACTIVE_JOB_STATUSES)
        }

        with engine.begin() as conn:
            conn.execute(text(
                """
                UPDATE jobs
                SET status = 'PENDING', started_at = NULL, claimed_at = NULL
                WHERE (status IN """
                f"{placeholders}"
                """
                   AND status != 'POST_PROCESSING')
                   OR (status = 'PENDING' AND claimed_at IS NOT NULL)
                """
            ), params)

    # ---- Delegate properties for backwards-compat callers ----

    @property
    def pending_count(self) -> int:
        return sum(queue.pending_count for queue in self.pools.values())

    @property
    def active_count(self) -> int:
        return sum(queue.active_count for queue in self.pools.values())


# ---------------------------------------------------------------------------
# Global singletons
# ---------------------------------------------------------------------------

# Typed queue manager — primary entry point for all new job submissions.
queue_manager = QueueManager()
