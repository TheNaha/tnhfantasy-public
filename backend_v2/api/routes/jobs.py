# Job routes - CRUD + validation endpoints for the job lifecycle
#
# KEY ENDPOINTS:
#   POST   /api/jobs            – Create and enqueue a new job
#   GET    /api/jobs            – List jobs with pagination
#   GET    /api/jobs/{id}       – Get a single job by ID
#   GET    /api/jobs/{id}/diagnostics – Failure diagnostics for a single job
#   DELETE /api/jobs/{id}       – Delete a job record
#   DELETE /api/jobs            – Clear all job records
#   POST   /api/jobs/{id}/retry – Re-submit a failed job with the same workflow
#   POST   /api/jobs/{id}/cancel– Cancel a queued or in-flight job
#   GET    /api/jobs/failed     – Failed jobs with diagnostics + summary
#   POST   /api/jobs/recover    – Fail wedged jobs, optionally re-queue active ones
#   POST   /api/jobs/reconcile-chat-replies – Re-drive paid chat replies lost by a queue drop
#   POST   /api/jobs/validate   – Pre-flight model-availability check
#
# Optional idempotency:
#   - POST /api/jobs accepts `Idempotency-Key` for short-window response reuse
#     to prevent duplicate submissions from client retries.
#
# Every serialized job carries a `diagnostics` block (provider, model, attempt
# history, duration, failure kind, retryability) built in JobService.
#
# Real-time updates are delivered via WebSocket (routes/websocket.py).
# The job queue itself lives in services/job_queue.py.

from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, field_validator

from api.deps import (
    get_job_service,
    get_job_submission_service,
)
from core.entities import JobStatus, VALID_TASK_TYPES
from core.exceptions import ValidationError
from infrastructure.logging import api_logger
from infrastructure.request_dedup import deduplicated, make_key
from services.job_service import JobService
from services.job_submission_service import JobSubmissionService

logger = api_logger()

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

# Upper bound on GET /api/jobs page size. list payloads omit the bulky parts of
# job.metadata (see JobService._job_to_dict), so a large page is cheap, but an
# unbounded one still forces a full-table scan.
MAX_JOBS_PAGE_SIZE = 200

# How many PENDING jobs the active-jobs view returns.
#
# The queue can hold thousands - only `max_concurrent` are claimed at a time
# - and the view used to materialise every one of them, with the full
# `workflow` and `metadata_` jsonb of each, on every poll. This is far
# above what any UI renders; `pending_total` still reports the true size.
MAX_ACTIVE_JOBS_RETURNED = 200
# Ceiling on the job search term, in characters.
MAX_SEARCH_LENGTH = 200

MAX_FAILED_PAGE_SIZE = 100

# A job takes minutes, not seconds, and the caller picks this value. The old
# floor was 30s, which meant `?timeout_seconds=30` failed essentially every live
# image job: the request was a one-liner that looked harmless and silently
# marked paying work FAILED.
#
# The floor is now the SHORTEST window any task type allows, because startup
# recovery uses each job's own task-type timeout (`get_job_timeout`) and a
# manual recover must never be more aggressive than an automatic one. The
# image timeout is 3600s and the LLM timeout is 180s, so the floor is the
# LLM's - a hardcoded 300 was more permissive than the automatic recovery of
# an LLM job.
MIN_RECOVER_TIMEOUT_SECONDS = 180
MAX_RECOVER_TIMEOUT_SECONDS = 3600


def _min_recover_timeout_seconds() -> int:
    """The shortest window any task type allows, computed from the config.

    The constant above is the fallback for a config that cannot be read at
    import time. This is the live value, and the test asserts the two agree
    with what the config actually says.
    """
    from config import get_job_timeout
    from core.entities import VALID_TASK_TYPES

    return min(get_job_timeout(task_type) for task_type in VALID_TASK_TYPES)


class CreateJobRequest(BaseModel):
    workflow: dict
    metadata: dict = {}
    task_type: str = "image"

    @field_validator("task_type")
    @classmethod
    def _check_task_type(cls, value: str) -> str:
        # Constrained here rather than left a bare `str` because SQLModel does
        # not run `field_validator`s for table models, so
        # `Job._validate_task_type` never fires. A typo then routed the job to
        # whichever queue "isn't llm" and left it PENDING forever with
        # `enqueued_at` set and no error written — the claim query's predicate
        # could never match it. Resolved from `VALID_TASK_TYPES` so this and the
        # entity's own check cannot drift apart.
        if value not in VALID_TASK_TYPES:
            raise ValueError(
                f"task_type must be one of {sorted(VALID_TASK_TYPES)}, got {value!r}"
            )
        return value


class RetryJobRequest(BaseModel):
    keep_provider: bool = False


class CancelJobRequest(BaseModel):
    reason: str | None = None


class ValidateWorkflowRequest(BaseModel):
    """Request to validate workflow model availability."""
    workflow: dict | None = None
    options: dict | None = None
    preferred_provider_id: str | None = None


class ValidateWorkflowResponse(BaseModel):
    """Response with model availability information."""
    valid: bool
    eligible_providers: list[str]
    missing_models: dict[str, dict[str, list[str]]]  # {provider: {dir: [files]}}
    global_missing: dict[str, list[str]]  # Models missing on ALL providers
    can_trigger_download: bool
    required_models: dict[str, list[str]]  # What models were found in workflow


# Plain `def` on purpose, not `async def`: nothing in this handler awaits,
# so as `async def` it ran on the event loop and its DB/disk work blocked
# every other request for the duration. FastAPI runs a plain `def` handler in
# a worker thread, which is what the work actually needs.
@router.post("/validate", response_model=ValidateWorkflowResponse)
def validate_workflow(
    request: ValidateWorkflowRequest,
    submission_service: JobSubmissionService = Depends(get_job_submission_service)
):
    """
    Pre-flight validation to check if required models are available.
    
    Use this before job creation to:
    - Check if any provider has all required models
    - Get list of missing models per provider
    - Identify globally missing models (not on any provider)
    - Determine if downloads can be triggered
    
    Returns detailed breakdown to allow UI to show missing models
    and offer download triggers.
    """
    from core.workflow_builder import WorkflowBuilder
    workflow = request.workflow
    if not workflow and request.options:
        builder = WorkflowBuilder()
        workflow = builder.build(request.options)

    if not workflow:
        from core.exceptions import ValidationError
        raise ValidationError("workflow or options is required", field="workflow")

    response = submission_service.build_validation_response(
        workflow,
        preferred_provider_id=request.preferred_provider_id,
    )
    logger.debug("workflow_validation_start", model_count=len(response["required_models"]))
    return response


@router.post("")
async def create_job(
    request: CreateJobRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        description="Optional request key. Re-using the same key reuses the same response for a short deduplication window.",
    ),
    submission_service: JobSubmissionService = Depends(get_job_submission_service)
):
    """
    Create a new job.
    
    Validates that at least one provider has all required models.
    Returns 400 with detailed missing model info if validation fails.

    Idempotency:
    - If `Idempotency-Key` is provided, duplicate submissions with the same key
      return the same response during a short deduplication window.
    - If omitted, each request creates a new job.
    """

    async def _create_and_enqueue():
        job = await submission_service.create_and_enqueue_job(
            request.workflow,
            request.metadata,
            task_type=request.task_type,
        )
        logger.info("job_enqueued", job_id=job.id)
        return submission_service.job_service._job_to_dict(job)

    # Opt-in idempotency for clients that can safely provide a request key.
    # Default behavior remains unchanged for repeated submissions without the header.
    if idempotency_key:
        dedup_key = make_key("create_job", idempotency_key.strip())
        return await deduplicated(dedup_key, _create_and_enqueue)

    return await _create_and_enqueue()



@router.get("")
async def list_jobs(
    limit: int = 20,
    offset: int = 0,
    cursor: str | None = None,
    service: JobService = Depends(get_job_service)
):
    if limit < 1:
        raise ValidationError("limit must be at least 1")
    # Cap the page size. This endpoint had no ceiling, so `?limit=1000000`
    # forced a full-table load. Sibling endpoints already cap (search_jobs at
    # 100, chats at 1000); list_jobs is the one users hit most.
    if limit > MAX_JOBS_PAGE_SIZE:
        limit = MAX_JOBS_PAGE_SIZE
    """List jobs with pagination. Uses deduplication to prevent duplicate work."""
    
    # Keyset pagination: cursor is "ISO8601_created_at|job_id" of the last row
    # of the previous page. When provided it replaces OFFSET (O(log n) fetches
    # on PostgreSQL instead of O(n) row skipping).
    parsed_cursor = None
    if cursor:
        try:
            created_part, _, job_id = cursor.partition("|")
            parsed_cursor = (datetime.fromisoformat(created_part), job_id)
        except (ValueError, TypeError):
            raise ValidationError("Invalid cursor format; expected 'created_at|job_id'")
    
    # Deduplicate concurrent identical requests
    async def _list():
        result = await service.list_jobs(limit=limit, offset=offset, cursor=parsed_cursor)
        if result["jobs"]:
            last = result["jobs"][-1]
            result["next_cursor"] = f"{last['created_at']}|{last['id']}"
        return result

    return await deduplicated(
        make_key("list_jobs", limit, offset, cursor),
        _list,
    )


@router.get("/search")
async def search_jobs(
    q: str = Query(..., max_length=MAX_SEARCH_LENGTH),
    limit: int = 25,
    service: JobService = Depends(get_job_service)
):
    """Full-text search over job prompts (tsvector on Postgres, LIKE on SQLite)."""
    if not q.strip():
        return {"jobs": []}
    # Negative reaches the repo as-is: Postgres rejects `LIMIT -1` with a
    # 500 and SQLite reads it as "no limit", an unauthenticated whole-table
    # dump. Clamp at both ends like `list_failed_jobs` does.
    limit = max(1, min(limit, 100))
    results = await deduplicated(
        make_key("search_jobs", q, limit),
        lambda: service.search_jobs(q.strip(), limit=limit),
    )
    return {"jobs": results}



@router.get("/active")
def get_active_jobs(service: JobService = Depends(get_job_service)):
    """Get all active (pending/running) jobs to rehydrate frontend state.

    Serialized with `include_full_metadata=False`, the contract the sibling
    `list_jobs` already documents and passes. It was omitted here, so every
    poll returned each job's entire `metadata_` — including
    `original_messages`, the whole agentic conversation — for every PENDING row
    in the table. PENDING has no limit: only `max_concurrent` are claimed at a
    time, so the queue can hold thousands, and `useActiveJobs` polls this every
    5 seconds from `Dashboard.jsx`. `LIST_METADATA_OMIT` exists for exactly
    this and was not applied.

    The job still carries `workflow`, so the frontend can key a rehydrated job
    to its graph; that is what the active-jobs view is for, and it is a single
    graph rather than a transcript.

    The PENDING list is BOUNDED. Only `max_concurrent` jobs are claimed at a
    time, so the queue can hold thousands, and this route used to
    materialise every one of them - with the full `workflow` and
    `metadata_` jsonb of each - on every poll. Measured on 5 000 pending
    jobs with a 40-node workflow each: 802 ms and 5 000 full rows, for a
    view that shows a handful. The bound is far above what the UI renders,
    and `pending_total` still reports the true size of the queue.
    """
    pending = service.get_pending_jobs(limit=MAX_ACTIVE_JOBS_RETURNED)
    running = service.get_running_jobs()
    pending_total = service.count_pending_jobs()

    jobs_data = []
    per_type_position = {}

    for job in running:
        jobs_data.append(service._job_to_dict(job, include_full_metadata=False))

    for job in pending:
        job_dict = service._job_to_dict(job, include_full_metadata=False)
        per_type_position[job.task_type] = per_type_position.get(job.task_type, 0) + 1
        job_dict["queue_position"] = per_type_position[job.task_type]
        jobs_data.append(job_dict)

    return {"jobs": jobs_data, "pending_total": pending_total}


@router.get("/queue")
def get_queue_status(service: JobService = Depends(get_job_service)):
    """
    Get queue status with ETA estimates.
    Returns pending and running jobs with estimated completion times.
    ETAs are computed per task_type so LLM jobs (seconds) don't pollute
    image job (minutes) estimates.
    """

    pending = service.get_pending_queue_items()
    running = service.get_running_queue_items()
    running_by_type = {}
    pending_by_type = {}
    for job in running:
        running_by_type.setdefault(job.task_type, []).append(job)
    for job in pending:
        pending_by_type.setdefault(job.task_type, []).append(job)

    avg_durations = {
        task_type: service.get_average_duration(task_type=task_type)
        for task_type in set(list(running_by_type.keys()) + list(pending_by_type.keys()))
    }

    # Build queue items with ETA (per task_type)
    queue = []
    cumulative_by_type = {}
    pending_position = {}

    for job in running:
        avg_duration = avg_durations.get(job.task_type, 30.0)
        remaining = avg_duration * (1 - (job.overall_progress / 100)) if job.overall_progress else avg_duration
        queue.append({
            "id": job.id,
            "task_type": job.task_type,
            "status": "generating",
            "position": 0,
            "progress": job.overall_progress,
            "eta_seconds": remaining,
            "prompt": job.metadata_.get("prompt", "")[:50] if job.metadata_ else "",
        })
        cumulative_by_type[job.task_type] = remaining

    # Add pending jobs with cumulative ETA (per task_type)
    for job in pending:
        avg_duration = avg_durations.get(job.task_type, 30.0)
        cumulative = cumulative_by_type.get(job.task_type, 0)
        eta = cumulative + avg_duration
        pending_position[job.task_type] = pending_position.get(job.task_type, 0) + 1
        queue.append({
            "id": job.id,
            "task_type": job.task_type,
            "status": "pending",
            "position": pending_position[job.task_type],
            "progress": 0,
            "eta_seconds": eta,
            "prompt": job.metadata_.get("prompt", "")[:50] if job.metadata_ else "",
        })
        cumulative_by_type[job.task_type] = eta

    return {
        "queue": queue,
        "avg_duration_seconds": avg_durations,
        "has_history": any(v != 30.0 for v in avg_durations.values()),
        "total_pending": len(pending),
        "total_running": len(running),
    }


@router.get("/stats/summary")
def get_job_stats(service: JobService = Depends(get_job_service)):
    """Get job statistics."""
    return service.get_job_stats()


@router.get("/failed")
async def list_failed_jobs(
    limit: int = 25,
    offset: int = 0,
    task_type: str | None = None,
    include_acknowledged: bool = False,
    service: JobService = Depends(get_job_service),
):
    """
    List failed jobs (newest first) with diagnostics for the failure view.

    Each job includes the `diagnostics` block (provider, model, attempt history,
    duration, failure kind, whether it is retryable). The `summary` counters
    describe the returned page; `total` is the full failure count for the filter.

    Jobs the user has acknowledged are excluded unless `include_acknowledged` is
    set, and `acknowledged_count` reports how many were hidden so the UI can
    offer to show them again.
    """
    limit = max(1, min(limit, MAX_FAILED_PAGE_SIZE))
    offset = max(0, offset)

    jobs, total = await service.get_failed_jobs(
        limit=limit,
        offset=offset,
        task_type=task_type,
        include_acknowledged=include_acknowledged,
    )
    return {
        "jobs": jobs,
        "total": total,
        "limit": limit,
        "offset": offset,
        "summary": service.summarize_failed_jobs(jobs),
        "acknowledged_count": 0
        if include_acknowledged
        else await service.count_acknowledged_failed(task_type=task_type),
    }


@router.post("/recover")
async def recover_jobs(
    timeout_seconds: int | None = None,
    requeue_running: bool = False,
    force: bool = False,
    service: JobService = Depends(get_job_service),
):
    """
    Recover interrupted work: fail jobs wedged past the stale timeout, and
    optionally re-queue active ones.

    The same recovery the backend runs at startup, exposed so an operator can run
    it on a live instance when a worker died. It is destructive, so this
    endpoint guards what it can from here:

    * `timeout_seconds` is floored at MIN_RECOVER_TIMEOUT_SECONDS (300s) when
      the caller gives one. It used to floor at 30s, shorter than a normal
      image generation, so the caller's default wrote FAILED to every live
      job. Omitting it entirely means "use each job's own task-type timeout",
      which is what startup recovery does.

    * By default it performs only the safe half. `JobQueue.recover` fails stale
      jobs (safe: it only writes FAILED for jobs older than the timeout) and then
      `_reset_claims_and_requeue_sync` sets EVERY active job back to PENDING.
      `execute_job` requires PENDING, so that is not a re-mark — it re-dispatches.
      A running LLM job is then charged twice: the original worker finishes,
      downloads its image and creates its Asset, then calls update_job(COMPLETED)
      on a row that is no longer in an active state. Startup recovery can do
      this because it runs immediately after boot, when every claim in the DB is
      stale by definition. A live HTTP endpoint cannot make that assumption, so
      with active jobs present it fails the stale ones and requeues nothing.

    * `force=false` (the default) makes the stale half a REPORT when there are
      active jobs: it lists the jobs that recovery would fail and fails
      nothing. The dashboard's "Recover" button is a mutation the user can
      fire by accident, and it was failing live jobs - a 300-second window
      against a 3600-second image timeout, so every generation still running
      after five minutes was marked FAILED. `force=true` opts into failing
      them.

    * `requeue_running=true` opts into the old, fully destructive behaviour. It
      is off by default precisely because the guard against orphaning an in-flight
      attempt belongs in `JobQueue._reset_claims_and_requeue_sync`
      (services/job_queue.py:658) — a per-job, claim-checked reset — and that is
      outside this file.
    """
    from services.job_queue import queue_manager

    if timeout_seconds is not None:
        timeout_seconds = max(
            _min_recover_timeout_seconds(),
            min(timeout_seconds, MAX_RECOVER_TIMEOUT_SECONDS),
        )

    active_ids = _active_job_ids(service)

    if active_ids and not requeue_running:
        # Safe half only: report what is stale, requeue nothing, and fail
        # nothing unless the caller explicitly asked.
        candidates = await service.list_stale_running_jobs(timeout_seconds=timeout_seconds)
        stale_ids = {entry["job_id"] for entry in candidates}

        if not force:
            summary = {
                "mode": "report_only",
                "recovered": 0,
                "failed": 0,
                "failed_job_ids": [],
                "stale_candidates": candidates,
                "stale_candidate_ids": sorted(stale_ids),
                "pending": service.count_pending_jobs(),
                "running": len(active_ids),
                "requeued": False,
                "skipped_running": sorted(active_ids - stale_ids),
            }
            logger.info(
                "job_recovery_report_only",
                stale_candidates=len(candidates),
                active=len(active_ids),
                timeout_seconds=timeout_seconds,
            )
            return {"status": "success", **summary}

        stale = await service.fail_stale_running_jobs(timeout_seconds=timeout_seconds)
        stale_ids = {job.id for job in stale}
        summary = {
            "mode": "stale_only",
            "recovered": 0,
            "failed": len(stale),
            "failed_job_ids": sorted(stale_ids),
            "stale_candidate_ids": sorted(stale_ids),
            "pending": service.count_pending_jobs(),
            "running": len(active_ids),
            "requeued": False,
            "skipped_running": sorted(active_ids - stale_ids),
        }
        logger.info(
            "job_recovery_stale_only",
            failed=summary["failed"],
            active=len(active_ids),
            timeout_seconds=timeout_seconds,
        )
        return {"status": "success", **summary}

    if active_ids:
        logger.warning(
            "job_recovery_requeued_running_jobs",
            active=len(active_ids),
            sample=sorted(active_ids)[:5],
        )

    summary = await queue_manager.recover(service, timeout_seconds=timeout_seconds)
    logger.info(
        "job_recovery_requested",
        recovered=summary["recovered"],
        failed=summary["failed"],
        requeued_running=bool(active_ids and requeue_running),
        timeout_seconds=timeout_seconds,
    )
    return {"status": "success", **summary}


def _active_job_ids(service: JobService) -> set[str]:
    """Ids of jobs sitting in an active state that has already started.

    PENDING-with-no-claim is excluded: those are already queued, and
    `JobQueue.recover` re-enqueues them without duplicating work. A job with no
    `started_at` is excluded too — it never left the queue, so there is no
    in-flight attempt to orphan.

    This is a "is anything in flight" test, not a liveness proof; there is no
    heartbeat to check. It exists so the destructive path costs an explicit
    `requeue_running=true` instead of happening on a one-line HTTP call.

    A failure here is RAISED, not reported as "nothing is running". The empty
    set is not a conservative answer: `recover_jobs` branches on
    `if active_ids and ...`, so "unknown" and "nothing" are the same branch —
    and the branch leads to `queue_manager.recover`, which per this module's own
    docstring sets every active job back to PENDING and re-dispatches it. A
    transient database error during recovery is exactly the moment jobs are
    most likely to be in flight. The previous `except Exception: return set()`
    with the comment "a DB failure must not block recovery" asserted the
    opposite of the safe default: it turned the one query that guards a
    destructive operation into the one query that could fail open.
    """
    return {job.id for job in service.get_running_jobs() if job.started_at}


@router.post("/reconcile-chat-replies")
async def reconcile_chat_replies(
    limit: int = 200,
    dry_run: bool = False,
    service: JobService = Depends(get_job_service),
):
    """Re-drive chat artefacts that were generated but never written to `messages`.

    The world-integration consumer is one writer of chat artefacts and it reads
    from a lossy queue. If a JOB_COMPLETED event is evicted under backpressure
    the output is gone: the job is COMPLETED, the user paid for it, and the
    conversation silently never shows it. This finds those jobs — COMPLETED
    chat_reply, narrator or chat_image jobs with no message stamped with their
    id — and replays each through the handler that would have written it.
    Idempotent: anything already persisted is never found, so repeat calls do
    nothing.

    The URL keeps its old name because an operator may have `_-replies` wired
    into a cron; what it repairs is the three artefact kinds, which is what
    `_PRECOMPLETION_PERSISTED_TYPES` in `job_processing` now writes before
    completion. `chat_tts` is excluded on purpose — it mutates an existing
    message rather than inserting one, so there is no row to find by absence.

    `dry_run=true` reports what would be re-driven without writing.
    """
    from services.world_integration_service import (
        find_unpersisted_chat_replies,
        reconcile_unpersisted_chat_replies,
    )

    limit = max(1, min(limit, 500))

    if dry_run:
        found = find_unpersisted_chat_replies(service.session, limit=limit)
        return {
            "found": len(found),
            "kinds": sorted({event_type for event_type, _ in found}),
            "job_ids": [job["id"] for _event_type, job in found],
            "chat_ids": sorted(
                {
                    (job["metadata"] or {}).get("chat_id")
                    or (job["workflow"] or {}).get("chat_id")
                    for _event_type, job in found
                }
                - {None}
            ),
            "repaired": [],
            "failed": [],
            "dry_run": True,
        }

    return {"dry_run": False, **await reconcile_unpersisted_chat_replies(limit=limit)}


@router.get("/breakdown")
async def get_jobs_breakdown(
    key: str = "model",
    limit: int = 25,
    service: JobService = Depends(get_job_service),
):
    """
    Aggregate jobs by a top-level metadata_ key using JSONB (PostgreSQL) /
    JSON1 (SQLite). E.g. GET /api/jobs/breakdown?key=model returns the most
    common checkpoint models across jobs.
    """
    import re

    if not re.fullmatch(r"[A-Za-z0-9_]+", key):
        raise ValidationError("key must be alphanumeric/underscore only", field="key")
    # Same both-ends clamp as `list_failed_jobs`: a negative limit reaches
    # SQL as `LIMIT -1`.
    limit = max(1, min(limit, 100))
    statuses = [JobStatus.COMPLETED, JobStatus.FAILED]
    items = await service.get_metadata_key_counts(key, statuses=statuses, limit=limit)
    return {"key": key, "breakdown": items}


# NOTE: Routes with path parameters MUST come AFTER static routes
# Otherwise '/queue' would match as job_id='queue'

@router.get("/{job_id}")
async def get_job(
    job_id: str,
    service: JobService = Depends(get_job_service)
):
    """Get a specific job."""
    job = await service.get_job(job_id)
    return service._job_to_dict(job)


@router.get("/{job_id}/diagnostics")
async def get_job_diagnostics(
    job_id: str,
    service: JobService = Depends(get_job_service),
):
    """
    Failure diagnostics for a single job.

    Returns the same `diagnostics` block embedded in job payloads, plus the
    attempt history in isolation so a UI can render a timeline without having to
    pick fields out of the full job record.
    """
    job = await service.get_job(job_id)
    diagnostics = service._job_to_dict(job)["diagnostics"]
    return {
        "id": job.id,
        "task_type": job.task_type,
        "status": job.status.value,
        "provider_id": job.provider_id,
        "error": job.error,
        "diagnostics": diagnostics,
        "attempts": diagnostics["attempts"],
    }


class AcknowledgeJobRequest(BaseModel):
    acknowledged: bool = True


class AcknowledgeAllRequest(BaseModel):
    acknowledged: bool = True
    task_type: str | None = None


@router.post("/acknowledge-all")
def acknowledge_all_failed_jobs(
    request: AcknowledgeAllRequest,
    service: JobService = Depends(get_job_service),
):
    """Acknowledge, or restore, every failed job matching the filter.

    The panel had only two actions — retry, or recover the queue — so a user who
    had read a failure and did not want it retried had no way to stop seeing it.
    Deleting the job was the only escape, and that discards the only record of
    what the provider did.

    Idempotent: the filter ignores the current acknowledged state, so calling it
    twice is a no-op the second time and `acknowledged: false` restores the full
    set rather than only the part still visible.
    """
    updated = service.acknowledge_all(
        acknowledged=request.acknowledged, task_type=request.task_type
    )
    return {
        "status": "success",
        "acknowledged": request.acknowledged,
        "updated": updated,
    }


@router.post("/{job_id}/acknowledge")
async def acknowledge_job(
    job_id: str,
    request: AcknowledgeJobRequest | None = None,
    service: JobService = Depends(get_job_service),
):
    """Acknowledge (or un-acknowledge) a single failed job.

    Reversible: `acknowledged: false` clears the timestamp and the failure comes
    back. Returns `updated: 0` for a job that was already in the requested state,
    so a client can report a no-op honestly instead of implying a change.
    """
    acknowledged = True if request is None else request.acknowledged
    # `get_job` raises NotFoundError for a missing id, which the app's handler
    # turns into a 404. Same shape as retry_job above.
    await service.get_job(job_id)

    updated = await service.acknowledge_jobs([job_id], acknowledged=acknowledged)
    return {
        "status": "success",
        "job_id": job_id,
        "acknowledged": acknowledged,
        "updated": updated,
    }


@router.post("/{job_id}/retry")
async def retry_job(
    job_id: str,
    request: RetryJobRequest | None = None,
    service: JobService = Depends(get_job_service),
    submission_service: JobSubmissionService = Depends(get_job_submission_service)
):
    """
    Retry a failed job by creating a new job with the same workflow.

    The new job is linked back to the original through `diagnostics.retry_of`.
    A stale `preferred_provider_id` is dropped by default so the retry can land
    on a healthy provider instead of failing on the same one again; pass
    `keep_provider: true` to pin it. Model availability is re-validated, so a
    retry of a job whose models went missing is rejected with 400.
    """
    original_job = await service.get_job(job_id)

    if original_job.status != JobStatus.FAILED:
        raise ValidationError("Only failed jobs can be retried", field="status")

    if not original_job.workflow:
        raise ValidationError("Job has no workflow to retry", field="workflow")

    keep_provider = bool(request.keep_provider) if request else False
    metadata = dict(original_job.metadata_ or {})
    if not keep_provider:
        metadata.pop("preferred_provider_id", None)

    job_service = submission_service.job_service
    from services.job_service import (
        JOB_DIAGNOSTICS_KEY,
        JOB_RETRY_ORIGIN_DIAGNOSTICS_KEY,
    )

    diagnostics = dict(metadata.get(JOB_DIAGNOSTICS_KEY) or {})
    # The retry's OWN history starts empty.
    #
    # This used to extend the original job's diagnostics block, so a retry
    # that had not run yet reported the ORIGINAL's failure kind, the
    # original's attempt count, and the original's attempt history - and
    # `record_attempt` then appended the retry's own attempt to that
    # inherited list, so the timeline belonged to two different job ids.
    # The lineage is kept; the failure history is not inherited.
    retry_count = int(diagnostics.get("retry_count") or 0) + 1
    if diagnostics:
        # Keep the original's block, but under its own name, so the retry
        # can still be traced back to what the first attempt said.
        metadata[JOB_RETRY_ORIGIN_DIAGNOSTICS_KEY] = diagnostics
    metadata[JOB_DIAGNOSTICS_KEY] = {
        "retry_of": job_id,
        "retry_count": retry_count,
    }

    new_job = await submission_service.create_and_enqueue_job(
        original_job.workflow,
        metadata,
        task_type=original_job.task_type,
    )

    logger.info(
        "job_retried",
        original_job_id=job_id,
        new_job_id=new_job.id,
        keep_provider=keep_provider,
    )

    return {
        "status": "success",
        "new_job_id": new_job.id,
        "original_job_id": job_id,
        "new_job": job_service._job_to_dict(new_job),
    }


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    request: CancelJobRequest | None = None,
    service: JobService = Depends(get_job_service),
):
    """
    Cancel a queued or in-flight job.

    Signals the provider worker (best effort) and records the terminal
    CANCELLED state so the job stops occupying the queue. Terminal jobs are
    rejected with 400 — there is no provider work left to stop.
    """
    from services.job_processing import cancel_job as cancel_job_processing

    result = await cancel_job_processing(
        job_service=service,
        job_id=job_id,
        reason=request.reason if request else None,
    )
    return {"status": "success", **result}


@router.delete("/{job_id}")
async def delete_job(
    job_id: str,
    service: JobService = Depends(get_job_service)
):
    """Delete a job."""
    await service.delete_job(job_id)
    return {"status": "success"}


@router.delete("")
def delete_all_jobs(service: JobService = Depends(get_job_service)):
    """Delete all jobs."""
    count = service.clear_all_jobs()
    return {"status": "success", "deleted": count}
