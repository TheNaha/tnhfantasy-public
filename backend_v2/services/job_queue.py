# Job Queue - Async job processing with worker pool
import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from core.entities import JobStatus
from core.events import EventType, emit_job_event
from infrastructure.logging import get_logger

logger = get_logger("job_queue")


class JobQueue:
    """
    Async job queue with configurable worker pool.
    Replaces the polling-based worker loop with a proper queue.
    """
    
    def __init__(self, max_workers: int = 2):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._running = False
        self.max_workers = max_workers
        
        # Job processor callback - set by the API layer
        self._processor: Callable[[str, str | None], Awaitable[None]] | None = None
        
        # Track active jobs
        self._active_jobs: dict[str, asyncio.Task] = {}
        
        # Track workers that should stop after their current job (graceful shutdown)
        self._stopping_workers: set[asyncio.Task] = set()
        
        # Recovery lock to prevent race conditions on startup
        self._recovery_lock: asyncio.Lock = asyncio.Lock()
        self._recovering: bool = False
    
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
        """
        await self._queue.put((job_id, provider_id))
    
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
            
            # 1. Prioritize removing idle workers (cancel immediately)
            while to_remove > 0 and idle_workers:
                task = idle_workers.pop()
                if task in self._workers:
                    self._workers.remove(task)
                    task.cancel()
                    removed_count += 1
                    to_remove -= 1
            
            # 2. If still need to remove, mark busy workers to drain (graceful stop)
            while to_remove > 0 and busy_workers:
                task = busy_workers.pop()
                if task in self._workers:
                    self._workers.remove(task)
                    self._stopping_workers.add(task)
                    logger.debug("worker_draining", reason="pool_downsize")
                    removed_count += 1
                    to_remove -= 1
            
            logger.info("job_queue_resize_complete", idle_cancelled=len(idle_workers), busy_draining=len(busy_workers))
    
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
                try:
                    job_id, provider_id = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                if not self._processor:
                    logger.warning("no_processor_set", job_id=job_id, worker_id=worker_id)
                    self._queue.task_done()
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
                    self._queue.task_done()
                    
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
    
    async def recover_pending_jobs(self, job_service, timeout_seconds: int = 300) -> tuple:
        """
        Recover pending/running jobs from database on startup.
        Should be called once during application startup after workers are started.
        Uses a lock to prevent concurrent recovery attempts.
        
        Args:
            job_service: JobService instance for querying/updating jobs
            timeout_seconds: Consider jobs running longer than this as stuck (default 5 min)
            
        Returns:
            Tuple of (recovered_count, failed_count)
        """
        # Acquire recovery lock to prevent race conditions
        async with self._recovery_lock:
            if self._recovering:
                logger.warning("job_recovery_already_running")
                return (0, 0)
            
            self._recovering = True
            logger.info("job_recovery_start")
            
            try:
                return await self._do_recovery(job_service, timeout_seconds)
            finally:
                self._recovering = False
    
    async def _do_recovery(self, job_service, timeout_seconds: int) -> tuple:
        """Internal recovery implementation."""
        recovered_count = 0
        failed_count = 0

        pending = list(job_service.get_pending_jobs())
        running = list(job_service.get_running_jobs())

        stale_running = []
        recoverable_running = []
        for job in running:
            if job.started_at:
                elapsed = (datetime.now(timezone.utc) - job.started_at).total_seconds()
                if elapsed > timeout_seconds:
                    stale_running.append((job, elapsed))
                    continue
            recoverable_running.append(job)

        if stale_running:
            failed_count = await self._mark_recovery_timeouts_atomically(
                job_service=job_service,
                stale_running=stale_running,
            )

        for job in pending:
            await self.enqueue(job.id, job.provider_id)
            recovered_count += 1

        # Re-enqueue non-stale running jobs. Since the backend restarted, internal
        # async tasks waiting for these provider jobs were destroyed. We must re-enqueue
        # them so they are tracked again and don't become zombies.
        for job in recoverable_running:
            await self.enqueue(job.id, job.provider_id)
            recovered_count += 1
        
        if recovered_count > 0 or failed_count > 0:
            logger.info("job_recovery_complete", recovered=recovered_count, failed=failed_count)
        else:
            logger.info("job_recovery_none")
        
        return recovered_count, failed_count

    async def _mark_recovery_timeouts_atomically(self, job_service, stale_running) -> int:
        """Mark stale running jobs failed in one transaction to avoid partial state updates."""
        session = getattr(job_service, "session", None)
        if session is None:
            raise RuntimeError("Job recovery requires a JobService with an active session")

        error_message = "Server restart during processing - job timed out"
        now = datetime.now(timezone.utc)

        try:
            for job, _elapsed in stale_running:
                job.status = JobStatus.FAILED
                job.error = error_message
                job.completed_at = now
                job.updated_at = now
                session.add(job)
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.error(
                "job_recovery_atomic_update_failed",
                error=str(exc),
                stale_jobs=[job.id for job, _elapsed in stale_running],
            )
            raise

        failed_count = 0
        for job, elapsed in stale_running:
            failed_count += 1
            logger.warning("job_recovery_timeout", job_id=job.id, elapsed=f"{elapsed:.0f}s")
            try:
                await emit_job_event(EventType.JOB_FAILED, job_service._job_to_dict(job))
            except Exception as exc:
                logger.warning("job_recovery_emit_failed", job_id=job.id, error=str(exc))

        return failed_count


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
        self.image: JobQueue = JobQueue(max_workers=1)
        self.llm: JobQueue = JobQueue(max_workers=1)
        self._processor: Callable[[str, str | None], Awaitable[None]] | None = None

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
        logger.info("queue_manager_started", image_workers=self.image.max_workers, llm_workers=self.llm.max_workers)

    async def stop(self, timeout_seconds: float = 30.0) -> None:
        """Stop both queues."""
        await self.image.stop(timeout_seconds=timeout_seconds)
        await self.llm.stop(timeout_seconds=timeout_seconds)
        logger.info("queue_manager_stopped")

    def resize(self, image_workers: int, llm_workers: int) -> None:
        """Resize both queues synchronously (size is applied on next start)."""
        self.image.max_workers = max(1, image_workers)
        self.llm.max_workers = max(1, llm_workers)

    async def recover_pending_jobs(self, job_service) -> tuple:
        """Recover pending jobs, routing each to the correct queue by task_type."""
        from core.entities import Job, JobStatus
        from sqlmodel import select

        session = getattr(job_service, "session", None)
        total_recovered = 0
        total_failed = 0

        pending = list(job_service.get_pending_jobs())
        running = list(job_service.get_running_jobs())

        timeout_seconds = 300
        now = datetime.now(timezone.utc)
        stale_running = []
        recoverable_running = []
        for job in running:
            if job.started_at:
                elapsed = (now - job.started_at).total_seconds()
                if elapsed > timeout_seconds:
                    stale_running.append((job, elapsed))
                    continue
            recoverable_running.append(job)

        # Mark stale jobs failed
        if stale_running and session is not None:
            error_message = "Server restart during processing - job timed out"
            try:
                for job, _elapsed in stale_running:
                    job.status = JobStatus.FAILED
                    job.error = error_message
                    job.completed_at = now
                    job.updated_at = now
                    session.add(job)
                session.commit()
                for job, elapsed in stale_running:
                    total_failed += 1
                    logger.warning("job_recovery_timeout", job_id=job.id, elapsed=f"{elapsed:.0f}s")
                    try:
                        await emit_job_event(EventType.JOB_FAILED, job_service._job_to_dict(job))
                    except Exception as exc:
                        logger.warning("job_recovery_emit_failed", job_id=job.id, error=str(exc))
            except Exception as exc:
                if session:
                    session.rollback()
                logger.error("job_recovery_atomic_update_failed", error=str(exc))

        for job in pending:
            task_type = getattr(job, "task_type", "image") or "image"
            await self.get_queue(task_type).enqueue(job.id, job.provider_id)
            total_recovered += 1

        for job in recoverable_running:
            task_type = getattr(job, "task_type", "image") or "image"
            await self.get_queue(task_type).enqueue(job.id, job.provider_id)
            total_recovered += 1

        if total_recovered > 0 or total_failed > 0:
            logger.info("queue_manager_recovery_complete", recovered=total_recovered, failed=total_failed)

        return total_recovered, total_failed

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

# Legacy singleton kept for backwards-compatibility with any code paths that
# have not yet been migrated to queue_manager.  New code should prefer
# queue_manager.enqueue(job_id, task_type=...).
job_queue = JobQueue()

# Typed queue manager — primary entry point for all new job submissions.
queue_manager = QueueManager()
