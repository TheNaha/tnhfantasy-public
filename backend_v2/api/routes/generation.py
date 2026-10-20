# Generation routes
#
# These endpoints create ComfyUI generation jobs and enqueue them for
# processing.  The actual execution is handled asynchronously by the job
# queue workers in `services/job_queue.py`.
#
# FLOW:
#   POST /api/generate (or /api/generate/batch)
#     → create Job record in DB (status=PENDING)
#     → enqueue job ID into JobQueue (in-memory asyncio queue)
#     → return job dict immediately (caller tracks progress via WebSocket)
#
# For workflow validation (check model availability before submitting)
# use POST /api/jobs/validate (routes/jobs.py).
#
# Optional idempotency:
#   - POST /api/generate and POST /api/generate/batch accept `Idempotency-Key`
#     to deduplicate duplicate submissions within a short server-side window.
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlmodel import Session

from api.deps import get_job_submission_service
from core.exceptions import ValidationError
from core.upload_validation import require_batch_size
from infrastructure.logging import api_logger
from infrastructure.request_dedup import deduplicated, make_key
from services.job_submission_service import JobSubmissionService

logger = api_logger()

router = APIRouter(prefix="/api", tags=["generation"])

# Ceiling on `POST /generate/batch`. The frontend UI stops at 60, but the
# endpoint is directly reachable, and every entry below runs `validate_workflow`
# (two 4-table joins) plus a committed `create_job` inline in the request
# coroutine — so a 5000-entry body created 5000 paid GPU jobs and blocked the
# event loop for minutes. Sized well above the UI cap so scripted batch callers
# are unaffected.
MAX_GENERATE_BATCH = 60


class GenerateRequest(BaseModel):
    """Request body for single-image generation.

    `kind` says which of the two request shapes this is:

      * `guided` - the backend compiles `options` into a ComfyUI graph.
      * `graph` - the client compiled the graph and sends it as `workflow`.

    It is optional, and omitting it keeps the old behaviour (a request
    carrying `workflow` is a graph, one carrying `options` is guided), so
    existing clients keep working. It exists because the old rule was
    "whichever field is present", and a hand-written ComfyUI graph with a
    node keyed `prompt` or `mode` was routed to `options` and rejected by
    the option schema. The frontend sends it explicitly.
    """
    kind: Literal["guided", "graph"] | None = None
    workflow: dict[str, Any] | None = None  # Full ComfyUI workflow node graph
    options: dict[str, Any] | None = None  # Generator options
    metadata: dict[str, Any] = {}  # Optional: prompt, seed, model info for gallery display
    preferred_provider_id: str | None = None  # Pin the job to one provider


class GenerateBatchRequest(BaseModel):
    # Deliberately no `max_length` here. A model-level cap answers 422 during
    # validation; the 400 with `BATCH_TOO_LARGE` from `require_batch_size`
    # (below) is the contract callers branch on, and
    # `tests/test_event_loop_blocking.py::TestGenerateBatchCap` pins it.
    workflows: list[dict[str, Any]] | None = None
    options: dict[str, Any] | None = None
    metadata: dict[str, Any] = {}


async def _target_capabilities(
    provider_id: str | None, session: Session
) -> dict[str, Any] | None:
    """What a provider can do, or None when that could not be determined.

    The answer comes from the provider's own node graph, through the same
    cached `object_info` the node palette reads - so it costs nothing the
    palette has not already paid.

    None means "not known". A provider that is down, or a provider that
    has never been introspected, must not be read as a provider that
    cannot do FreeU - so the builder carries on as it always did.
    """
    if not provider_id:
        return None
    try:
        from api.routes.nodes import _fetch_provider_object_info
        from core.provider_capabilities import derive_capabilities

        digest, _graph = await _fetch_provider_object_info(provider_id, session)
        return derive_capabilities(digest, provider_id=provider_id)
    except Exception as exc:
        logger.warning(
            "capabilities_unavailable", provider_id=provider_id, error=str(exc)
        )
        return None


@router.post("/generate")
async def generate(
    request: GenerateRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        description="Optional request key. Re-using the same key reuses the same response for a short deduplication window.",
    ),
    submission_service: JobSubmissionService = Depends(get_job_submission_service)
):
    """Create a new generation job.
    
    Accepts a ComfyUI workflow and optional metadata.
    Returns the created job with its ID for tracking.

        Idempotency:
        - If `Idempotency-Key` is provided, duplicate submissions with the same key
            return the same response during a short deduplication window.
        - If omitted, each request creates a new job.
    """
    try:
        from core.workflow_builder import WorkflowBuilder
        from core.workflow_metadata import derive_metadata_from_workflow, merge_metadata
        from core.workflow_postprocess import postprocess_graph

        if request.kind is not None:
            kind = request.kind
        elif request.workflow:
            kind = "graph"
        elif request.options:
            kind = "guided"
        else:
            raise ValidationError("workflow or options is required", field="workflow")

        workflow = request.workflow
        metadata = dict(request.metadata or {})

        if kind == "guided":
            if not request.options:
                raise ValidationError("options is required for a guided request", field="options")
            # What the TARGET provider can do.
            #
            # The builder used to hardcode the provider's node vocabulary in
            # Python and emit those nodes whatever the provider had
            # installed - so a FreeU toggle produced a graph with a
            # `FreeU_V2` node, and a provider without it failed at dispatch
            # with "node type not found", after the user had picked the
            # enhancement and waited for the job.
            #
            # With the capabilities in hand the builder skips what the
            # provider cannot do and says so, and the reason lands in the
            # job's metadata where the user can see it.
            #
            # "Not known" is not "no": a provider that is down is not a
            # provider that cannot do FreeU, so an unavailable answer leaves
            # the builder behaving as it always did.
            capabilities = await _target_capabilities(
                request.preferred_provider_id, submission_service.session
            )
            builder = WorkflowBuilder(capabilities=capabilities)
            workflow = builder.build(request.options)
            if builder.warnings:
                metadata["capability_warnings"] = list(builder.warnings)
        else:
            if not workflow:
                raise ValidationError("workflow is required for a graph request", field="workflow")
            # The graph path gets the same prompt treatment as the guided
            # one: the shortcuts expanded and the embedding references
            # checked. It used to get neither, because the client had
            # compiled the graph - so a graph with a missing embedding
            # reference reached the provider and failed there.
            postprocess_graph(workflow)
            # The graph path sent `metadata: {}`, so the gallery had no
            # prompt, no seed and no model name for it. Derive them from
            # the graph, and let the client's own metadata win where it
            # sent one.
            metadata = merge_metadata(derive_metadata_from_workflow(workflow), metadata)

        if not workflow:
            raise ValidationError("workflow or options is required", field="workflow")

        async def _create_generation_job():
            job = await submission_service.create_and_enqueue_job(
                workflow=workflow,
                metadata=metadata,
                preferred_provider_id=request.preferred_provider_id,
            )
            logger.info("generate_job_created", job_id=job.id, kind=kind)
            return submission_service.job_service._job_to_dict(job)

        if idempotency_key:
            dedup_key = make_key("generate", idempotency_key.strip())
            return await deduplicated(dedup_key, _create_generation_job)

        return await _create_generation_job()
    except Exception as e:
        logger.error("generate_failed", error=str(e))
        raise


@router.post("/generate/batch")
async def generate_batch(
    request: GenerateBatchRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        description="Optional request key. Re-using the same key reuses the same batch response for a short deduplication window.",
    ),
    submission_service: JobSubmissionService = Depends(get_job_submission_service)
):
    """Create multiple generation jobs at once.
    
    Accepts an array of workflows and creates one job per workflow.
    Each job gets a `batch_index` and `batch_total` added to its metadata
    so the UI can group the results.
    Returns an array of created job records.

    Idempotency:
    - If `Idempotency-Key` is provided, duplicate submissions with the same key
      return the same batch response during a short deduplication window.
    - If omitted, each request creates a new set of jobs.
    """
    try:
        from core.workflow_builder import WorkflowBuilder

        workflows = request.workflows

        def _normalize_item(item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
            """Return (workflow, metadata) for one batch entry.

            Accepts three shapes:
              - compiled workflow directly:             {nodes, edges, ...}
              - wrapped entry from the UI:              {workflow: {...}, options: {...}, metadata: {...}}
              - bare generator options (prompt only):   {prompt: ..., ...}
            """
            meta = item.get("metadata") or {}
            wf = item.get("workflow")
            if isinstance(wf, dict) and (wf.get("nodes") or wf.get("edges")):
                return wf, meta
            if isinstance(item.get("options"), dict):
                return WorkflowBuilder().build(item["options"]), meta
            if isinstance(item.get("nodes"), (list, dict)):
                return {k: v for k, v in item.items() if k != "metadata"}, meta
            if item.get("prompt"):
                return WorkflowBuilder().build(item), meta
            raise ValidationError("batch entry must provide workflow, options, or prompt", field="workflows")

        # If workflows are omitted but options are provided, treat it as a single-workflow batch
        if not workflows and request.options:
            builder = WorkflowBuilder()
            workflows = [{"workflow": builder.build(request.options), "metadata": {}}]

        if not workflows:
            raise ValidationError("workflows array is required", field="workflows")

        # Bound the batch before any job is created or enqueued. `require_batch_size`
        # gives the same 400-with-code error shape as the other batch endpoints
        # (files.py), with the cap passed explicitly so this endpoint's limit is
        # its own rather than the shared MAX_BATCH_ITEMS.
        require_batch_size(workflows, MAX_GENERATE_BATCH, field="workflows")

        async def _create_batch_jobs():
            created_jobs = []
            failures: list[dict[str, Any]] = []

            for i, entry in enumerate(workflows):
                try:
                    workflow, entry_metadata = _normalize_item(entry)
                except Exception as exc:
                    # A malformed entry is this entry's problem, not the
                    # batch's. The other entries are fine.
                    failures.append({"index": i, "error": str(exc)})
                    continue

                # Add batch index to metadata; per-workflow metadata (e.g. the
                # frontend's per-prompt entries) wins over the request-level one.
                job_metadata = {
                    **request.metadata,
                    **entry_metadata,
                    "batch_index": i,
                    "batch_total": len(workflows),
                }
                try:
                    job = await submission_service.create_and_enqueue_job(
                        workflow=workflow,
                        metadata=job_metadata,
                    )
                except Exception as exc:
                    # The jobs already created are REAL work - they are
                    # enqueued, they will run, and they will cost. The old
                    # code let the exception escape, so the client got a
                    # 5xx, `setJobIds` never ran, and the Batch Jobs panel
                    # stayed EMPTY while N-1 images were being produced
                    # somewhere.
                    #
                    # So the failure is reported WITH the jobs that were
                    # created, and the client shows both.
                    failures.append({"index": i, "error": str(exc)})
                    logger.warning(
                        "generate_batch_entry_failed",
                        index=i,
                        created_so_far=len(created_jobs),
                        error=str(exc),
                    )
                    continue

                created_jobs.append(submission_service.job_service._job_to_dict(job))

            logger.info(
                "generate_batch_created",
                count=len(created_jobs),
                failed=len(failures),
            )
            result = {"jobs": created_jobs, "count": len(created_jobs)}
            if failures:
                result["failures"] = failures
                result["failed_count"] = len(failures)
            return result

        if idempotency_key:
            dedup_key = make_key("generate_batch", idempotency_key.strip())
            return await deduplicated(dedup_key, _create_batch_jobs)

        return await _create_batch_jobs()
    except Exception as e:
        logger.error("generate_batch_failed", error=str(e))
        raise
