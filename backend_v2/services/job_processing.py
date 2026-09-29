import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import Any

from infrastructure.deps import get_session_context
from config import settings
from core.entities import JobStatus
from core.exceptions import NotFoundError
from infrastructure.background_tasks import start_background_task
from infrastructure.logging import get_logger
from services.chat_utils import extract_first_text
from services.image_processing import build_job_outputs, normalize_persisted_output
from services.job_service import FAILURE_FINALIZATION
from services.orchestrator_service import MAX_AGENTIC_DEPTH, get_max_agentic_depth

logger = get_logger("job_processing")


def get_default_checkpoint() -> str:
    """The configured default checkpoint, or the well-known base name.

    Delegates to `config.resolve_default_checkpoint`, which is the single
    reader of that key. This copy returned `None` when the key was present but
    empty, so a config with `default_checkpoint: ""` produced a job whose
    checkpoint was `None` and the failure surfaced much later as a
    missing-model error naming `None`.
    """
    from config import resolve_default_checkpoint

    return resolve_default_checkpoint()


_finalizing_jobs: set[str] = set()
_finalizing_jobs_lock = None


def _get_finalization_lock():
    """Lazy initialization of asyncio.Lock to avoid event loop issues at import time."""
    global _finalizing_jobs_lock
    if _finalizing_jobs_lock is None:
        _finalizing_jobs_lock = asyncio.Lock()
    return _finalizing_jobs_lock


async def _reserve_finalization(job_id: str) -> bool:
    async with _get_finalization_lock():
        if job_id in _finalizing_jobs:
            return False
        _finalizing_jobs.add(job_id)
        return True


async def _release_finalization(job_id: str) -> None:
    async with _get_finalization_lock():
        _finalizing_jobs.discard(job_id)


async def cancel_job(
    *,
    job_service,
    job_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Cancel a queued or in-flight job and report what happened.

    The provider signal is best-effort: the terminal CANCELLED state is always
    recorded, and the job runner stops on its next status check regardless of
    whether the worker acknowledged the request. Terminal jobs raise
    ValidationError because there is no provider work left to stop.
    """
    from services.job_runner import signal_provider_cancellation
    from services.provider_runtime import resolve_provider_runtime
    from services.provider_service import ProviderService

    job = await job_service.get_job(job_id)
    provider_id = job.provider_id
    provider_signalled = False

    if provider_id:
        try:
            provider = await ProviderService(job_service.session).get_provider(provider_id)
            runtime = resolve_provider_runtime(provider)
            provider_signalled = await signal_provider_cancellation(
                runtime=runtime,
                provider_id=provider_id,
                job_id=job_id,
            )
        except Exception as exc:
            # The provider record may be gone or unreachable — still cancel the
            # job locally so it stops occupying the queue.
            logger.warning("job_cancel_provider_signal_failed", job_id=job_id, error=str(exc))

    cancelled = await job_service.cancel_job(job_id, reason=reason)
    logger.info(
        "job_cancelled",
        job_id=job_id,
        provider_id=provider_id,
        provider_signalled=provider_signalled,
    )

    return {
        "job_id": cancelled.id,
        "job_status": cancelled.status.value,
        "provider_id": provider_id,
        "provider_signalled": provider_signalled,
    }


def normalize_external_outputs(outputs, *, allow_text: bool = False) -> list[dict[str, Any]]:
    """Accept structured persisted outputs and, for LLM jobs, text outputs."""
    if not isinstance(outputs, list):
        raise ValueError("Worker result outputs must be a list")

    normalized = []
    for output in outputs:
        if not isinstance(output, dict):
            raise ValueError("External worker outputs must be structured objects")
        if allow_text and (output.get("content") is not None or output.get("text") is not None):
            normalized.append({
                "type": "text",
                "content": output.get("content", output.get("text")),
                "role": output.get("role", "assistant"),
            })
            continue
        if not output.get("filename"):
            raise ValueError("External worker outputs must include filename")
        if not (output.get("relative_path") or output.get("path") or output.get("subfolder")):
            raise ValueError("External worker outputs must include a persisted path")
        normalized.append(normalize_persisted_output(output))

    return normalized


async def mark_job_post_processing(
    *,
    job_service,
    job_id: str,
    outputs: list[dict[str, Any]],
    provider_id: str | None = None,
) -> None:
    await job_service.update_job(
        job_id,
        status=JobStatus.POST_PROCESSING,
        outputs=outputs,
        progress=100,
        overall_progress=100,
        provider_id=provider_id,
    )


async def complete_job(
    *,
    job_service,
    job_id: str,
    outputs: list[dict[str, Any]],
    provider_id: str | None = None,
    load_balancer=None,
    event_extra: dict | None = None,
) -> None:
    # Note: duration_seconds is already saved to image metadata in build_job_outputs
    # via full_metadata["job"] = {"duration_seconds": ...}
    update_args: dict[str, Any] = {
        "status": JobStatus.COMPLETED,
        "outputs": outputs,
        "progress": 100,
        "overall_progress": 100,
        "provider_id": provider_id,
    }
    if event_extra is not None:
        update_args["event_extra"] = event_extra
    await job_service.update_job(job_id, **update_args)

    if load_balancer and provider_id:
        await load_balancer.report_success(provider_id)
        await load_balancer.release_job(provider_id)


async def wait_for_gallery_outputs(
    outputs: list[dict[str, Any]],
    *,
    resolve_output_path=None,
    attempts: int = 20,
    delay_seconds: float = 0.5,
) -> None:
    """Wait until every image output actually exists on disk.

    The DB-backed asset index replaces the old in-memory GalleryIndexer, so we
    verify files exist on the filesystem directly (the worker writes them before
    completion) rather than depending on an index that may not be populated yet.

    Raises `ProviderCallError` if the files never appear. Returning quietly used
    to let `complete_when_ready` mark the job COMPLETED with no image on disk:
    the user got a green tick and an empty gallery, and nothing anywhere
    recorded that the worker had reported a `completed` event for output it
    never wrote. Raising keeps the failure on the retry/failover path, which is
    the only place that can still recover it.
    """
    import os

    # Local import: `provider_client` imports from this module, so a top-level
    # import here is a cycle.
    from services.provider_client import ProviderCallError

    output_paths = [
        output.get("path") or output.get("relative_path")
        for output in outputs
        if isinstance(output, dict) and output.get("filename")
    ]
    output_paths = [p for p in output_paths if p]
    if not output_paths:
        return

    # Workers may return relative paths (e.g. YYYY/MM/DD/name.png); resolve them
    # against OUTPUT_DIR so the existence check actually matches on disk.
    def _absolutize(p: str) -> str:
        return p if os.path.isabs(p) else os.path.join(settings.output_dir, p)

    output_paths = [_absolutize(p) for p in output_paths]

    for _ in range(attempts):
        missing = [p for p in output_paths if not os.path.exists(p)]
        if not missing:
            return
        last_missing = missing
        await asyncio.sleep(delay_seconds)

    raise ProviderCallError(
        f"Worker reported {len(output_paths)} image output(s) but "
        f"{len(last_missing)} never appeared on disk after "
        f"{attempts * delay_seconds:.0f}s (first missing: {last_missing[0]})",
        is_retryable=True,
    )


async def finalize_persisted_job_outputs(
    *,
    job_service,
    job_id: str,
    outputs: list[dict[str, Any]],
    provider_id: str | None = None,
    load_balancer=None,
    process_image_background_fn: Callable[[str, str], Awaitable[Any]] | None = None,
    event_extra: dict | None = None,
) -> None:
    try:
        job = await job_service.get_job(job_id)
    except NotFoundError:
        logger.warning("job_finalize_not_found", job_id=job_id)
        return

    if job.status == JobStatus.COMPLETED:
        logger.debug("job_finalize_skipped_completed", job_id=job_id)
        return

    if job.status in {JobStatus.CANCELLED, JobStatus.FAILED}:
        logger.info(
            "job_finalize_skipped_terminal",
            job_id=job_id,
            status=job.status.value,
        )
        return

    if not await _reserve_finalization(job_id):
        logger.info("job_finalize_already_running", job_id=job_id)
        return

    try:
        if job.status != JobStatus.POST_PROCESSING:
            await mark_job_post_processing(
                job_service=job_service,
                job_id=job_id,
                outputs=outputs,
                provider_id=provider_id,
            )
    except Exception:
        await _release_finalization(job_id)
        raise

    async def complete_when_ready():
        async with get_session_context() as reconcile_session:
            from services.job_service import JobService
            reconcile_job_service = JobService(reconcile_session)
            active_job_service = reconcile_job_service
            try:
                await reconcile_job_service.get_job(job_id)
            except NotFoundError:
                active_job_service = job_service
            try:
                for output in outputs:
                    if output.get("type") == "text":
                        continue
                    path = output.get("path") or output.get("relative_path")
                    if path and not os.path.isabs(path) and not os.path.exists(path):
                        candidate = os.path.join(settings.output_dir, path)
                        if os.path.exists(candidate):
                            path = candidate
                    if path and output.get("type") == "image":
                        try:
                            from services.asset_reconciler import reconcile_asset

                            await asyncio.to_thread(
                                reconcile_asset,
                                reconcile_session,
                                path,
                                user_id="default_user",
                                workspace=(job.metadata_ or {}).get("workspace", "main"),
                                character_id=(job.metadata_ or {}).get("character_id"),
                                story_id=(job.metadata_ or {}).get("story_id"),
                                job_id=job_id,
                                job_metadata=job.metadata_,
                                output_dir=settings.output_dir,
                            )
                        except Exception as exc:
                            logger.warning("asset_reconcile_failed", job_id=job_id, path=path, error=str(exc))

                    if process_image_background_fn and path and output.get("type") == "image":
                        await process_image_background_fn(path, job_id)

                await wait_for_gallery_outputs(outputs)
                await complete_job(
                    job_service=active_job_service,
                    job_id=job_id,
                    outputs=outputs,
                    provider_id=provider_id,
                    load_balancer=load_balancer,
                    event_extra=event_extra,
                )
                logger.info("job_completed", job_id=job_id, outputs=len(outputs), provider_id=provider_id)
            except Exception as exc:
                logger.error("job_finalize_failed", job_id=job_id, provider_id=provider_id, error=str(exc), exc_info=True)
                await active_job_service.mark_failed(
                    job_id,
                    # `error` is user-visible: it comes back from
                    # `GET /api/jobs/{id}` and is embedded in the diagnostics
                    # block. `str(exc)` put a SQLAlchemy or httpx traceback —
                    # possibly a connection URL — in front of a browser, in the
                    # same way it did in `worker_ws`. `error_type` is the stable
                    # code the diagnostics view groups by, and it is already
                    # being set, so nothing is lost by keeping the prose generic
                    # here. The cause is in the log line above.
                    error=(
                        "The provider finished, but the result could not be saved. "
                        "The image may still be on disk; see the server log "
                        "(job_finalize_failed) for the cause."
                    ),
                    error_type=FAILURE_FINALIZATION,
                    provider_id=provider_id,
                )
                if load_balancer and provider_id:
                    await load_balancer.release_job(provider_id)
            finally:
                await _release_finalization(job_id)

    start_background_task(
        complete_when_ready(),
        task_name=f"job_finalize:{job_id}",
        timeout=None,  # finalization must never be wedged by the default 300s cap
    )


def _classify_llm_job_type(job, final_result: dict[str, Any]) -> str:
    """Classify an LLM job into a single semantic type.

    Returns one of: "chat_reply", "story_continue", "narrator",
    "story_illustrate_prompt", "impersonation", "suggest_reply",
    "memory_extraction".
    """
    workflow_type = (job.workflow or {}).get("type") if isinstance(job.workflow, dict) else None
    result_type = final_result.get("type")
    metadata_source = (job.metadata_ or {}).get("source") if isinstance(job.metadata_, dict) else None

    if metadata_source == "story_illustrate_prompt":
        return "story_illustrate_prompt"
    if (job.metadata_ or {}).get("is_impersonation") is True or metadata_source == "impersonation":
        return "impersonation"
    if metadata_source == "auto_memory" or workflow_type == "memory_extraction":
        return "memory_extraction"

    for candidate in (result_type, workflow_type):
        if candidate in {"chat_reply", "story_continue", "narrator", "suggest_reply", "story_parse"}:
            return candidate

    return "chat_reply"


async def _finalize_llm_job(
    *,
    job,
    job_id: str,
    job_service,
    load_balancer,
    provider_id: str,
    final_result: dict,
    outputs: list,
) -> None:
    job_type = _classify_llm_job_type(job, final_result)

    if job_type == "impersonation":
        imp_text = (extract_first_text(final_result) or "").strip()

        imp_chat_id = job.metadata_.get("chat_id")
        
        await finalize_persisted_job_outputs(
            job_service=job_service,
            job_id=job_id,
            outputs=[],
            provider_id=provider_id,
            load_balancer=load_balancer,
            process_image_background_fn=None,
            event_extra={
                "type": "impersonation",
                "metadata": {"chat_id": imp_chat_id, "type": "impersonation"},
                "chat_id": imp_chat_id,
                "content": imp_text,
            },
        )
        return

    if job_type == "story_illustrate_prompt":
        generated_prompt = (extract_first_text(final_result) or "").strip()

        story_id   = job.metadata_.get("story_id")
        chapter_id = job.metadata_.get("chapter_id")
        checkpoint = job.metadata_.get("scene_checkpoint") or get_default_checkpoint()

        await finalize_persisted_job_outputs(
            job_service=job_service,
            job_id=job_id,
            outputs=[],
            provider_id=provider_id,
            load_balancer=load_balancer,
            process_image_background_fn=None,
            event_extra={
                "type": "story_illustrate_prompt",
                "metadata": {
                    "story_id": story_id,
                    "chapter_id": chapter_id,
                    "type": "story_illustrate_prompt",
                    "source": "story_illustrate_prompt",
                },
                "story_id": story_id,
                "chapter_id": chapter_id,
                "prompt": generated_prompt,
                "checkpoint": checkpoint,
            }
        )
        return

    if job_type == "narrator":
        narrator_content = extract_first_text(final_result) or ""

        narrator_chat_id = job.metadata_.get("chat_id") if job.metadata_ else None
        if not narrator_chat_id:
            narrator_chat_id = final_result.get("chat_id")

        event_extra = {
            "type": "narrator",
            "metadata": {"chat_id": narrator_chat_id, "type": "narrator", "source": "narrator"},
            "chat_id": narrator_chat_id,
            "content": narrator_content,
        }
    elif job_type == "suggest_reply":
        # Suggestions are returned to the frontend only (via the JOB_COMPLETED
        # event that useLLMJobResult polls). They must NOT be persisted as a
        # Message in the chat — the world_integration_service dispatcher has no
        # handler for "suggest_reply", so emitting type="suggest_reply" is
        # a no-op there and the text reaches the caller via outputs/content.
        assistant_content = ""
        if final_result.get("outputs") and isinstance(final_result.get("outputs"), list):
            assistant_output: dict[str, Any] = final_result.get("outputs")[0] or {}
            assistant_content = assistant_output.get("content", "")
        else:
            assistant_output = {}
        if not assistant_content and final_result.get("text"):
            assistant_content = final_result.get("text")

        chat_id = job.metadata_.get("chat_id") if job.metadata_ else None
        if not chat_id:
            chat_id = final_result.get("chat_id")

        event_extra = {
            "type": "suggest_reply",
            "metadata": {"chat_id": chat_id, "type": "suggest_reply"},
            "chat_id": chat_id,
            "content": assistant_content,
        }
    elif job_type == "memory_extraction":
        from services.memory_extraction import parse_extraction_result, create_memories_from_extraction
        text = extract_first_text(final_result) or ""
        memories = parse_extraction_result(text)
        character_id = job.metadata_.get("character_id") if job.metadata_ else None
        if memories and character_id:
            # Off the loop: this runs a sentence-transformers forward pass per
            # memory. It is CPU-bound and takes seconds, and the caller is
            # `async def` on the event loop, so it was freezing every other
            # request in the process while the model loaded and inferred.
            await asyncio.to_thread(
                create_memories_from_extraction,
                job_service.session,
                character_id,
                memories,
            )
        await finalize_persisted_job_outputs(
            job_service=job_service,
            job_id=job_id,
            outputs=[],
            provider_id=provider_id,
            load_balancer=load_balancer,
            process_image_background_fn=None,
            event_extra={
                "type": "memory_extraction",
                "metadata": {"character_id": character_id, "type": "memory_extraction"},
                "character_id": character_id,
                "count": len(memories),
            },
        )
        return
    elif job_type == "story_parse":
        story_id = (job.metadata_.get("story_id") if job.metadata_ else None) or final_result.get("story_id")
        event_extra = {
            "type": "story_parse",
            "metadata": {"story_id": story_id, "type": "story_parse"},
            "story_id": story_id,
            "content": extract_first_text(final_result) or "",
        }
    elif job_type in ("chat_reply", "story_continue"):
        assistant_content = ""
        assistant_output: dict[str, Any] = {}
        if final_result.get("outputs") and isinstance(final_result.get("outputs"), list):
            assistant_output = final_result.get("outputs")[0]
            assistant_content = assistant_output.get("content", "")
        if not assistant_content and final_result.get("text"):
             assistant_content = final_result.get("text")
             
        chat_id = job.metadata_.get("chat_id") if job.metadata_ else None
        if not chat_id:
            chat_id = final_result.get("chat_id")

        story_id = job.metadata_.get("story_id") if job.metadata_ else None
        if not story_id:
            story_id = final_result.get("story_id")

        entity_id = chat_id if job_type == "chat_reply" else story_id

        # --- Agentic tool-call handling ---
        # Chats chain the full toolset; story continuations chain only
        # story-safe tools (image generation) via metadata.story_id routing.
        is_story_job = job_type == "story_continue" and bool(story_id)
        if (job_type == "chat_reply" or is_story_job) and assistant_output.get("tool_calls"):
            metadata = job.metadata_ or {}
            max_depth = (
                get_max_agentic_depth(metadata=metadata)
                if is_story_job
                else MAX_AGENTIC_DEPTH
            )
            if metadata.get("agentic") and metadata.get("orchestrator_depth", 0) < max_depth:
                allowed_tools = {
                    t.get("function", {}).get("name")
                    for t in ((job.workflow or {}).get("tools") or [])
                    if isinstance(t, dict) and t.get("function", {}).get("name")
                }
                if not allowed_tools:
                    allowed_tools = {"generate_image"} if is_story_job else {
                        "generate_image", "narrate_scene", "update_world_state"
                    }
                from services.orchestrator_service import process_tool_calls_and_chain
                from services.job_queue import queue_manager

                chained = await process_tool_calls_and_chain(
                    job=job,
                    assistant_output=assistant_output,
                    final_result=final_result,
                    chat_id=entity_id if not is_story_job else None,
                    character_id=metadata.get("character_id"),
                    job_service=job_service,
                    enqueue_fn=lambda jid: queue_manager.enqueue(jid, task_type="llm"),
                    allowed_tools=allowed_tools,
                    story_id=story_id if is_story_job else None,
                    chapter_id=(metadata.get("chapter_id") if metadata else None),
                )
                if chained:
                    # load_balancer is None for the external-worker path (the only
                    # production caller), where the job was dispatched without
                    # the in-process pool. An unguarded call here raised
                    # AttributeError, and the caller's except block then marked an
                    # already-paid-for, already-completed job FAILED.
                    if load_balancer and provider_id:
                        await load_balancer.report_success(provider_id)
                        await load_balancer.release_job(provider_id)
                    try:
                        from core.entities import JobStatus
                        await job_service.update_job(
                            job.id,
                            status=JobStatus.COMPLETED,
                            outputs=outputs or [],
                            progress=100,
                            overall_progress=100,
                            provider_id=provider_id,
                        )
                    except Exception as e:
                        logger.error("agentic_parent_finalize_failed", job_id=job.id, error=str(e))
                    return

        # Scene generation fallback: the LLM returned plain prompt text instead
        # of a tool call (model without tool-calling support). Chain the text
        # directly into an image job instead of persisting it as a chat reply.
        is_scene_prompt = (
            isinstance(job.metadata_, dict)
            and job.metadata_.get("source") == "scene_prompt"
        )
        if is_scene_prompt and not assistant_output.get("tool_calls"):
            scene_checkpoint = (
                job.metadata_.get("scene_checkpoint")
                or job.metadata_.get("generator_checkpoint")
                or get_default_checkpoint()
            )
            await finalize_persisted_job_outputs(
                job_service=job_service,
                job_id=job_id,
                outputs=[],
                provider_id=provider_id,
                load_balancer=load_balancer,
                process_image_background_fn=None,
                event_extra={
                    "type": "scene_prompt",
                    "chat_id": entity_id,
                    "character_id": job.metadata_.get("character_id"),
                    "prompt": assistant_content,
                    "checkpoint": scene_checkpoint,
                    "metadata": {
                        "chat_id": entity_id,
                        "character_id": job.metadata_.get("character_id"),
                        "type": "scene_prompt",
                        "source": "scene_prompt",
                    },
                },
            )
            return

        event_type_str = job_type
        if job_type == "chat_reply":
            event_extra = {
                "type": event_type_str,
                "metadata": {"chat_id": entity_id, "type": event_type_str, "regenerated": job.metadata_.get("regenerated") if job.metadata_ else False},
                "chat_id": entity_id,
                "content": assistant_content,
            }
        else:
            story_id = (job.metadata_.get("story_id") if job.metadata_ else None)
            chapter_id = (job.metadata_.get("chapter_id") if job.metadata_ else None) or final_result.get("chapter_id")
            event_extra = {
                "type": event_type_str,
                "metadata": {"story_id": story_id, "chapter_id": chapter_id, "type": event_type_str},
                "story_id": story_id,
                "chapter_id": chapter_id,
                "content": assistant_content,
            }

    await finalize_persisted_job_outputs(
        job_service=job_service,
        job_id=job_id,
        outputs=outputs,
        provider_id=provider_id,
        load_balancer=load_balancer,
        process_image_background_fn=None,
        event_extra=event_extra,
    )

    if job_type == "chat_reply":
        chat_id = job.metadata_.get("chat_id") if job.metadata_ else None
        character_id = job.metadata_.get("character_id") if job.metadata_ else None
        # A swipe or a regeneration re-runs a turn the user already has. The
        # extraction window is near-identical but not identical — a regeneration
        # deletes the messages it was built from — so deduplication downstream
        # cannot be relied on to catch every reworded duplicate. Set by
        # `generate_swipe` and `regenerate_reply`.
        if job.metadata_ and job.metadata_.get("suppress_memory_extraction"):
            logger.debug("memory_extraction_suppressed", job_id=job_id, chat_id=chat_id)
        elif chat_id and character_id:
            try:
                from services.memory_extraction import enqueue_memory_extraction
                await enqueue_memory_extraction(
                    session=job_service.session if hasattr(job_service, "session") else None,
                    chat_id=chat_id,
                    character_id=character_id,
                    job_service=job_service,
                )
            except Exception as exc:
                logger.debug("memory_extraction_hook_failed", job_id=job_id, error=str(exc))


_AUDIO_OUTPUT_SUFFIXES = (".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".opus")

# A narration is tens of seconds of audio, not a 7 GB checkpoint, but the cap
# still has to exist: the provider's `/get-file` returns the whole body and
# there is nothing on this side refusing an unbounded one.
_TTS_FETCH_MAX_BYTES = 128 * 1024 * 1024
_TTS_FETCH_TIMEOUT_SECONDS = 120.0


def _is_audio_path(value: str) -> bool:
    return str(value).lower().endswith(_AUDIO_OUTPUT_SUFFIXES)


def _resolve_tts_worker_base_sync(provider_id: str) -> str | None:
    """The base URL a TTS provider's own `/get-file` is served from.

    Resolved the way `resolve_provider_health_url` resolves the health URL: a
    serverless deployment has no Docker-DNS name, so the provider's configured
    `worker_url` wins and the container hostname is only the fallback. Runs
    synchronously and is called through `asyncio.to_thread` — it reads the
    database, and this is an `async def` caller on the event loop.
    """
    from infrastructure.providers.runtime import _publish_provider_host

    base = None
    try:
        from infrastructure.database import get_session_context
        from infrastructure.repositories.provider_repo import ProviderRepository
        from infrastructure.providers.runtime import get_provider_worker_base_url

        with get_session_context() as session:
            provider = ProviderRepository(session).get(provider_id)
            if provider is None:
                return None
            config = provider.config or {}
            container_config = provider.container_config or {}
            base = (
                config.get("worker_url")
                or config.get("discovery_url")
                or container_config.get("internal_url")
            )
            base = base or get_provider_worker_base_url(provider.id)
    except Exception as exc:  # pragma: no cover - resolution is best-effort
        logger.warning("tts_worker_base_unresolved", provider_id=provider_id, error=str(exc))
        return None

    base = base.rstrip("/")
    _publish_provider_host(base)
    return base


def _safe_output_subdir(subfolder: str) -> str:
    """A provider-supplied subfolder, confined to the output directory.

    The value comes from a remote worker, so it is untrusted input on a path we
    are about to write to. Anything that could climb out is dropped rather than
    sanitised into something surprising.
    """
    parts = [
        p
        for p in str(subfolder or "").replace("\\", "/").split("/")
        if p not in ("", ".", "..") and not p.startswith("~")
    ]
    return "/".join(parts)


async def _fetch_remote_tts_outputs(
    *,
    job,
    provider_id: str,
    final_result: dict[str, Any],
) -> list[dict[str, Any]]:
    """Pull a TTS provider's audio off its own volume and onto this filesystem.

    A serverless TTS worker writes to a Modal volume and reports
    ``{filename, subfolder, type}``. Nothing shared that path with this process,
    so without this the job finalised with zero outputs and the audio stayed
    where it was, with the job marked green.

    The bytes are pulled before the record is handed to the normal finalization
    path rather than lazily inside it, because every consumer downstream
    (`_handle_chat_tts`, `_handle_story_tts`, `_handle_voice_preview`) reads a
    path that must already exist on disk.

    The provider's own subfolder is preserved rather than replaced: ComfyUI's
    `SaveAudio` already namespaces by the `filename_prefix` the workflow asked
    for (`voice_preview/<id>`, `chat_tts/<chat>/<msg>`), and rewriting it here
    would lose the one piece of structure that makes the output findable.
    """
    from urllib.parse import quote

    from infrastructure.http_client import get as http_get

    artifacts = [
        a
        for a in ((final_result.get("outputs") or []) + (final_result.get("images") or []))
        if isinstance(a, dict)
    ]
    if not artifacts:
        return []

    # A worker that already returned inline bytes needs no transport at all.
    inline = [a for a in artifacts if a.get("data")]
    if inline:
        return await asyncio.to_thread(build_job_outputs, job, inline, provider_id)

    base = await asyncio.to_thread(_resolve_tts_worker_base_sync, provider_id)
    if not base:
        return []

    fetched: list[dict[str, Any]] = []
    for artifact in artifacts:
        filename = os.path.basename(str(artifact.get("filename") or "").replace("\\", "/"))
        if not filename or filename in {".", ".."}:
            continue
        subfolder = _safe_output_subdir(artifact.get("subfolder") or "")
        remote_path = f"{subfolder}/{filename}" if subfolder else filename

        target_dir = (
            os.path.join(settings.output_dir, *subfolder.split("/"))
            if subfolder
            else settings.output_dir
        )
        target_path = os.path.join(target_dir, filename)
        remote_url = f"{base}/get-file/{quote(remote_path, safe='/')}"

        try:
            response = await http_get(remote_url, timeout=_TTS_FETCH_TIMEOUT_SECONDS)
            response.raise_for_status()
            body = response.content
        except Exception as exc:
            # One unreadable artifact fails that artifact, not the job: the
            # provider has already been paid and its work is not reproducible.
            logger.warning(
                "tts_output_fetch_failed",
                provider_id=provider_id,
                path=remote_path,
                error=str(exc),
            )
            continue

        if not body:
            logger.warning("tts_output_empty", provider_id=provider_id, path=remote_path)
            continue
        if len(body) > _TTS_FETCH_MAX_BYTES:
            logger.warning(
                "tts_output_too_large",
                provider_id=provider_id,
                path=remote_path,
                bytes=len(body),
            )
            continue

        await asyncio.to_thread(_write_tts_output, target_path, body)
        fetched.append(
            {
                "filename": filename,
                "subfolder": subfolder,
                "relative_path": remote_path,
                "path": target_path,
                "type": artifact.get("type") or "output",
            }
        )

    return fetched


def _write_tts_output(path: str, data: bytes) -> None:
    """Write a fetched audio artifact, creating its directory first.

    Written to a temp name in the same directory and moved into place, so a
    reader that stats the path (reconciliation polls for it) never observes a
    half-written file. Mirrors what the download path already does for models.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.partial"
    try:
        with open(tmp_path, "wb") as handle:
            handle.write(data)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


async def _finalize_image_job(
    *,
    job,
    job_id: str,
    job_service,
    load_balancer,
    provider_id: str,
    outputs: list,
    process_image_background_fn,
) -> None:
    event_extra: dict[str, Any] | None = None
    metadata = job.metadata_ or {}
    image_path = None
    for output in outputs or []:
        if isinstance(output, dict):
            image_path = output.get("relative_path") or output.get("filename")
            if image_path:
                break

    if image_path:
        chat_id = metadata.get("chat_id")
        is_audio = _is_audio_path(image_path)
        if metadata.get("type") == "voice_preview" and metadata.get("voice_id"):
            event_extra = {
                "type": "voice_preview",
                "voice_id": metadata.get("voice_id"),
                "image_path": image_path,
            }
        elif chat_id:
            event_extra = {
                "type": "chat_tts" if (metadata.get("type") == "chat_tts" or is_audio) else "chat_image",
                "chat_id": chat_id,
                "image_path": image_path,
                "metadata": metadata,
            }

        story_id = metadata.get("story_id")
        chapter_id = metadata.get("chapter_id")
        if story_id and chapter_id:
            # A chapter narration is a TTS job, not an image job, and the two
            # dispatch to different handlers. This used to hardcode
            # "story_image", which overwrote the "chat_tts" decided just above
            # and sent every story narration to the image handler, so the audio
            # was never attached to the chapter's beat list.
            is_story_tts = metadata.get("source") == "story_tts" or is_audio
            event_extra = {
                **(event_extra or {}),
                "type": "story_tts" if is_story_tts else "story_image",
                "story_id": story_id,
                "chapter_id": chapter_id,
                "image_path": image_path,
            }

    await finalize_persisted_job_outputs(
        job_service=job_service,
        job_id=job_id,
        outputs=outputs,
        provider_id=provider_id,
        load_balancer=load_balancer,
        process_image_background_fn=process_image_background_fn,
        event_extra=event_extra,
    )


async def finalize_successful_job(
    *,
    job,
    job_id: str,
    job_service,
    load_balancer,
    provider_id: str,
    final_result: dict[str, Any],
    process_image_background_fn: Callable[[str, str], Any],
) -> None:
    """Finalize a successful provider result, dispatching on `job.task_type`.

    LLM and image results are normalized through *separate* code paths so that
    language-model jobs are never mistaken for image jobs (issue #4). LLM jobs
    take their outputs straight from the provider's native ``outputs`` list and
    skip all filesystem/gallery logic — the assistant text is routed in-memory to
    the chat/story handlers in ``_finalize_llm_job`` instead of being written to
    an orphan ``.txt`` file and gallery-indexed.

    TTS is a fourth case that did not exist here at all. A TTS provider writes
    its audio to *its own* filesystem — a Modal volume, not a directory shared
    with this process — and reports only ``{filename, subfolder, type}``. The
    "already-persisted" branch below resolves such a path against
    ``settings.output_dir``, which is correct for `direct_url` and wrong for
    every serverless provider: the file is not there, the job finalised with
    zero outputs, and the audio stayed on the volume with no user-visible signal
    that anything had been produced.
    """
    if job.task_type == "llm":
        # Language-model providers emit {"outputs": [{"role": "assistant", "content": "..."}]}].
        # We forward the native outputs directly; no disk write, no gallery entry.
        outputs = final_result.get("outputs", []) or []
        await _finalize_llm_job(
            job=job,
            job_id=job_id,
            job_service=job_service,
            load_balancer=load_balancer,
            provider_id=provider_id,
            final_result=final_result,
            outputs=outputs,
        )
        return

    if job.task_type == "tts":
        outputs = await _fetch_remote_tts_outputs(
            job=job,
            provider_id=provider_id,
            final_result=final_result,
        )
        await _finalize_image_job(
            job=job,
            job_id=job_id,
            job_service=job_service,
            load_balancer=load_balancer,
            provider_id=provider_id,
            outputs=outputs,
            process_image_background_fn=None,
        )
        return

    # --- image path: normalize provider images into persisted output records ---
    if "images" in final_result:
        images = final_result.get("images", [])
        outputs = await asyncio.to_thread(build_job_outputs, job, images, provider_id)
    elif "outputs" in final_result:
        # Already-persisted artifacts (e.g. direct_url providers on a shared
        # mount) carry only filename/subfolder; resolve real paths so
        # reconciliation and the disk-existence check work downstream.
        outputs = []
        for out in final_result.get("outputs", []) or []:
            if not isinstance(out, dict):
                continue
            if out.get("path") is None and out.get("filename"):
                sub = (out.get("subfolder") or "").strip("/")
                rel = os.path.join(sub, out["filename"]) if sub else out["filename"]
                rel = rel.replace("\\", "/")
                out = {**out, "relative_path": rel, "path": os.path.join(settings.output_dir, rel)}
            outputs.append(out)
    else:
        outputs = []

    await _finalize_image_job(
            job=job,
            job_id=job_id,
            job_service=job_service,
            load_balancer=load_balancer,
            provider_id=provider_id,
            outputs=outputs,
            process_image_background_fn=process_image_background_fn,
        )
