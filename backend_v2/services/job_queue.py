# Job Queue - Async job processing with worker pool
import asyncio
from typing import Optional, Callable, Awaitable, Dict, Any, List
from datetime import datetime

from core.entities import JobStatus
from core.events import emit_job_event, EventType
from infrastructure.logging import get_logger

logger = get_logger("job_queue")


class JobQueue:
    """
    Async job queue with configurable worker pool.
    Replaces the polling-based worker loop with a proper queue.
    """
    
    def __init__(self, max_workers: int = 2):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._workers: List[asyncio.Task] = []
        self._running = False
        self.max_workers = max_workers
        
        # Job processor callback - set by the API layer
        self._processor: Optional[Callable[[str, Optional[str]], Awaitable[None]]] = None
        
        # Track active jobs
        self._active_jobs: Dict[str, asyncio.Task] = {}
        
        # Track workers that should stop after their current job (graceful shutdown)
        self._stopping_workers: set[asyncio.Task] = set()
        
        # Recovery lock to prevent race conditions on startup
        self._recovery_lock: asyncio.Lock = asyncio.Lock()
        self._recovering: bool = False
    
    def set_processor(self, processor: Callable[[str, Optional[str]], Awaitable[None]]):
        """
        Set the job processing callback.
        
        The callback receives (job_id, provider_id) and should process the job.
        """
        self._processor = processor
    
    async def enqueue(self, job_id: str, provider_id: Optional[str] = None) -> None:
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
    
    async def stop(self) -> None:
        """Stop the worker pool gracefully."""
        self._running = False
        
        # Cancel all workers
        for worker in self._workers:
            worker.cancel()
        
        # Wait for workers to finish
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        
        self._workers.clear()
        logger.info("job_queue_stopped")

    async def resize(self, new_count: int) -> None:
        """
        Dynamically resize the worker pool.
        
        Args:
            new_count: New number of workers (must be >= 1)
        """
        if new_count < 1:
            new_count = 1
            
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
                self._stopping_workers.remove(current_task)
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
        
        # Re-queue pending jobs
        pending = job_service.get_pending_jobs()
        for job in pending:
            await self.enqueue(job.id, job.provider_id)
            recovered_count += 1
        
        # Handle stuck running jobs
        running = job_service.get_running_jobs()
        for job in running:
            if job.started_at:
                elapsed = (datetime.utcnow() - job.started_at).total_seconds()
                if elapsed > timeout_seconds:
                    # Job was running when server died - mark failed
                    try:
                        await job_service.update_job(
                            job.id, 
                            status=JobStatus.FAILED, 
                            error="Server restart during processing - job timed out"
                        )
                        failed_count += 1
                        logger.warning("job_recovery_timeout", job_id=job.id, elapsed=f"{elapsed:.0f}s")
                    except Exception as e:
                        logger.error("job_recovery_failed", job_id=job.id, error=str(e))
                else:
                    # Job might still be valid, re-queue
                    await self.enqueue(job.id, job.provider_id)
                    recovered_count += 1
            else:
                # No started_at timestamp, re-queue
                await self.enqueue(job.id, job.provider_id)
                recovered_count += 1
        
        if recovered_count > 0 or failed_count > 0:
            logger.info("job_recovery_complete", recovered=recovered_count, failed=failed_count)
        else:
            logger.info("job_recovery_none")
        
        return recovered_count, failed_count


# Global singleton
job_queue = JobQueue()
