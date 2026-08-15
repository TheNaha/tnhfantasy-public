import asyncio
import base64
import io
import os
from collections.abc import Awaitable, Callable
from typing import Any

from api.deps import get_session_context
from config import settings
from core.entities import JobStatus
from core.exceptions import NotFoundError
from infrastructure.background_tasks import start_background_task
from infrastructure.logging import get_logger
from services.image_processing import build_job_outputs, normalize_persisted_output
from services.orchestrator_service import MAX_AGENTIC_DEPTH

logger = get_logger("job_processing")


def get_default_checkpoint() -> str:
    """Read the configured default checkpoint from settings, falling back to the
    well-known SDXL base name when no override is present."""
    from config import get_config
    return get_config().get("generator", {}).get("default_checkpoint", "sd_xl_base_1.0.safetensors")


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


def normalize_external_outputs(outputs) -> list[dict[str, Any]]:
    """Accept only persisted structured outputs from external workers."""
    if not isinstance(outputs, list):
        raise ValueError("Worker result outputs must be a list")

    normalized = []
    for output in outputs:
        if not isinstance(output, dict):
            raise ValueError("External worker outputs must be structured objects")
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
    """
    import os

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
        if all(os.path.exists(p) for p in output_paths):
            return
        await asyncio.sleep(delay_seconds)


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
                    job_service=job_service,
                    job_id=job_id,
                    outputs=outputs,
                    provider_id=provider_id,
                    load_balancer=load_balancer,
                    event_extra=event_extra,
                )
                logger.info("job_completed", job_id=job_id, outputs=len(outputs), provider_id=provider_id)
            except Exception as exc:
                logger.error("job_finalize_failed", job_id=job_id, provider_id=provider_id, error=str(exc), exc_info=True)
                await job_service.update_job(
                    job_id,
                    status=JobStatus.FAILED,
                    error=str(exc),
                    provider_id=provider_id,
                )
                if load_balancer and provider_id:
                    await load_balancer.release_job(provider_id)
            finally:
                await _release_finalization(job_id)

    start_background_task(
        complete_when_ready(),
        task_name=f"job_finalize:{job_id}",
    )


def _classify_llm_job_type(job, final_result: dict[str, Any]) -> str:
    """Classify an LLM job into a single semantic type.

    Returns one of: "chat_reply", "story_continue", "narrator",
    "story_illustrate_prompt", "impersonation", "suggest_reply".
    """
    workflow_type = (job.workflow or {}).get("type") if isinstance(job.workflow, dict) else None
    result_type = final_result.get("type")
    metadata_source = (job.metadata_ or {}).get("source") if isinstance(job.metadata_, dict) else None

    if metadata_source == "story_illustrate_prompt":
        return "story_illustrate_prompt"
    if (job.metadata_ or {}).get("is_impersonation") is True or metadata_source == "impersonation":
        return "impersonation"

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
        imp_text = ""
        if final_result.get("outputs") and isinstance(final_result["outputs"], list):
            imp_text = (final_result["outputs"][0] or {}).get("content", "")
        if not imp_text and final_result.get("text"):
            imp_text = final_result["text"]
        imp_text = imp_text.strip()

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
        generated_prompt = ""
        if final_result.get("outputs") and isinstance(final_result.get("outputs"), list):
            generated_prompt = (final_result.get("outputs")[0] or {}).get("content", "")
        if not generated_prompt and final_result.get("text"):
            generated_prompt = final_result.get("text")
        generated_prompt = generated_prompt.strip()

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
        narrator_content = ""
        if final_result.get("outputs") and isinstance(final_result.get("outputs"), list):
            narrator_content = (final_result.get("outputs")[0] or {}).get("content", "")
        if not narrator_content and final_result.get("text"):
            narrator_content = final_result.get("text")

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
        if job_type == "chat_reply" and assistant_output.get("tool_calls"):
            metadata = job.metadata_ or {}
            if metadata.get("agentic") and metadata.get("orchestrator_depth", 0) < MAX_AGENTIC_DEPTH:
                # Inherit the tool set the parent job exposed to the model
                # (already filtered by the chat's allow_image_generation /
                # allow_narration flags), falling back to safe basics if the
                # parent defined no tools.
                job_workflow = job.workflow if isinstance(job.workflow, dict) else {}
                allowed_tools = {
                    t.get("function", {}).get("name")
                    for t in (job_workflow.get("tools") or [])
                    if isinstance(t, dict) and t.get("function", {}).get("name")
                }
                if not allowed_tools:
                    allowed_tools = {"generate_image", "narrate_scene", "update_world_state"}
                from services.orchestrator_service import process_tool_calls_and_chain
                from services.job_queue import queue_manager

                chained = await process_tool_calls_and_chain(
                    job=job,
                    assistant_output=assistant_output,
                    final_result=final_result,
                    chat_id=entity_id,
                    character_id=metadata.get("character_id"),
                    job_service=job_service,
                    enqueue_fn=lambda jid: queue_manager.enqueue(jid, task_type="llm"),
                    allowed_tools=allowed_tools,
                )
                if chained:
                    if provider_id:
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
        is_audio = str(image_path).endswith(('.wav', '.mp3', '.ogg', '.flac'))
        if chat_id:
            event_extra = {
                "type": "chat_tts" if (metadata.get("type") == "chat_tts" or is_audio) else "chat_image",
                "chat_id": chat_id,
                "image_path": image_path,
                "metadata": metadata,
            }

        story_id = metadata.get("story_id")
        chapter_id = metadata.get("chapter_id")
        if story_id and chapter_id:
            event_extra = {
                **(event_extra or {}),
                "type": "story_image",
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
