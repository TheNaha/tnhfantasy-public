import asyncio
import base64
import io
import os
from collections.abc import Awaitable, Callable
from typing import Any

from api.deps import get_session_sync
from config import settings
from core.entities import JobStatus
from core.exceptions import NotFoundError
from infrastructure.background_tasks import start_background_task
from infrastructure.logging import get_logger
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


def _serialize_datetime(value: Any) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except Exception:
            pass
    return str(value)


async def _reserve_finalization(job_id: str) -> bool:
    async with _get_finalization_lock():
        if job_id in _finalizing_jobs:
            return False
        _finalizing_jobs.add(job_id)
        return True


async def _release_finalization(job_id: str) -> None:
    async with _get_finalization_lock():
        _finalizing_jobs.discard(job_id)


def normalize_persisted_output(output: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "type": output.get("type", "image"),
        "filename": output["filename"],
        "relative_path": output.get("relative_path"),
        "subfolder": output.get("subfolder", ""),
        "path": output.get("path"),
        "thumbnail": output.get("thumbnail"),
        "blurhash": output.get("blurhash"),
        "width": output.get("width"),
        "height": output.get("height"),
    }

    if not normalized["relative_path"] and normalized["path"]:
        base_output_dir = settings.output_dir
        try:
            normalized["relative_path"] = os.path.relpath(
                normalized["path"],
                base_output_dir,
            ).replace("\\", "/")
        except ValueError:
            normalized["relative_path"] = None

    if not normalized["subfolder"] and normalized["relative_path"]:
        subfolder = os.path.dirname(normalized["relative_path"]).replace("\\", "/")
        normalized["subfolder"] = "" if subfolder == "." else subfolder

    return normalized


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


def build_job_outputs(job, images: list[dict[str, Any]], provider_id: str, duration_seconds: float = None) -> list[dict[str, Any]]:
    """Persist worker images and return normalized job outputs."""
    from datetime import datetime, timezone

    from PIL import Image

    from infrastructure.image_processor import (
        get_output_path,
        save_image_with_metadata,
        write_metadata_sidecar,
    )

    outputs: list[dict[str, Any]] = []
    base_output_dir = settings.output_dir
    final_output_dir = get_output_path(base_output_dir)

    # Calculate duration if not provided and job has timing info
    if duration_seconds is None:
        job_started_at = getattr(job, "started_at", None)
        if job_started_at:
            now = datetime.now(timezone.utc)
            # Handle both naive and aware datetimes
            if job_started_at.tzinfo is None:
                job_started_at = job_started_at.replace(tzinfo=timezone.utc)
            duration_seconds = (now - job_started_at).total_seconds()

    for img in images:
        filename = img.get("filename", "output.png")
        subfolder = img.get("subfolder", "")

        if img.get("_base64_encoded") and img.get("data"):
            image_data = base64.b64decode(img["data"])

            if subfolder:
                target_dir = os.path.join(base_output_dir, subfolder)
                os.makedirs(target_dir, exist_ok=True)
            else:
                target_dir = final_output_dir

            output_path = os.path.join(target_dir, filename)
            job_created_at = _serialize_datetime(getattr(job, "created_at", None))
            full_metadata = {
                "job_id": job.id,
                "filename": filename,
                "provider": provider_id,
            }
            if job_created_at:
                # Persist a stable timeline anchor so replacement ordering survives reloads.
                full_metadata["job_created_at"] = job_created_at
                full_metadata["job_timeline_anchor"] = job_created_at
            # Add generation duration for statistics
            if duration_seconds is not None:
                full_metadata["job"] = {"duration_seconds": round(duration_seconds, 2)}
            if job.metadata_:
                for key in [
                    "prompt",
                    "negativePrompt",
                    "seed",
                    "steps",
                    "cfg",
                    "sampler",
                    "scheduler",
                    "width",
                    "height",
                    "checkpoint",
                    "loras",
                    "workflow",
                ]:
                    if key in job.metadata_:
                        full_metadata[key] = job.metadata_[key]

            try:
                img_obj = Image.open(io.BytesIO(image_data))
                save_image_with_metadata(img_obj, output_path, full_metadata)
                logger.debug("image_saved_with_metadata", path=output_path, bytes=len(image_data))
            except Exception as exc:
                logger.error(
                    "image_save_with_metadata_failed",
                    path=output_path,
                    error=str(exc),
                )
                with open(output_path, "wb") as file_handle:
                    file_handle.write(image_data)
                write_metadata_sidecar(output_path, full_metadata)

            rel_subfolder = os.path.relpath(target_dir, base_output_dir).replace("\\", "/")
            if rel_subfolder == ".":
                rel_subfolder = ""

            output = {
                "type": "image",
                "filename": filename,
                "subfolder": rel_subfolder,
                "relative_path": os.path.relpath(output_path, base_output_dir).replace("\\", "/"),
                "path": output_path,
            }
        else:
            output = normalize_persisted_output({
                "type": "image",
                "filename": filename,
                "subfolder": subfolder,
            })

        outputs.append(output)

    return outputs


def build_text_outputs(job, text_content: str, provider_id: str) -> list[dict[str, Any]]:
    """Persist text output and return normalized job outputs."""
    import os

    from infrastructure.image_processor import get_output_path
    
    base_output_dir = settings.output_dir
    final_output_dir = get_output_path(base_output_dir, subdir="text")
    os.makedirs(final_output_dir, exist_ok=True)
    
    filename = f"Generated_Text_{job.id[:8]}.txt"
    output_path = os.path.join(final_output_dir, filename)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text_content)
        
    rel_subfolder = os.path.relpath(final_output_dir, base_output_dir).replace("\\", "/")
    if rel_subfolder == ".":
        rel_subfolder = ""
        
    output = {
        "type": "text",
        "filename": filename,
        "subfolder": rel_subfolder,
        "relative_path": os.path.relpath(output_path, base_output_dir).replace("\\", "/"),
        "path": output_path,
    }
    
    return [output]


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
        from services.gallery_indexer import gallery_indexer

        try:
            for output in outputs:
                if output.get("type") == "text":
                    # Text outputs are routed in-memory to chat/story handlers and
                    # are never persisted to the image gallery; skip all disk/gallery
                    # work for them so LLM jobs don't stall on wait_for_gallery_outputs.
                    continue
                path = output.get("path") or output.get("relative_path")
                if path and not os.path.isabs(path) and not os.path.exists(path):
                    # Worker gave a relative path (e.g. YYYY/MM/DD/name.png); make it
                    # absolute under OUTPUT_DIR so reconcile can read dimensions/thumb.
                    candidate = os.path.join(settings.output_dir, path)
                    if os.path.exists(candidate):
                        path = candidate
                # Reconcile into the DB-backed assets index (replaces the
                # in-memory GalleryIndexer). Newly saved images already live in the
                # partitioned layout; this just writes/updates the asset row.
                if path and output.get("type") == "image":
                    try:
                        from services.asset_reconciler import reconcile_asset
                        await reconcile_asset(
                            get_session_sync(),
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
    is_chat_reply = job.task_type == 'llm' and (
        final_result.get('type') == 'chat_reply'
        or (isinstance(job.workflow, dict) and job.workflow.get("type") == "chat_reply")
    )
    is_story_continue = job.task_type == 'llm' and (
        final_result.get('type') == 'story_continue'
        or (isinstance(job.workflow, dict) and job.workflow.get("type") == "story_continue")
    )
    is_narrator = job.task_type == 'llm' and (
        final_result.get('type') == 'narrator'
        or (isinstance(job.workflow, dict) and job.workflow.get("type") == "narrator")
    )

    is_illustrate_prompt = (
        job.task_type == 'llm'
        and isinstance(job.metadata_, dict)
        and job.metadata_.get("source") == "story_illustrate_prompt"
    )

    is_impersonation = (
        job.task_type == 'llm'
        and isinstance(job.metadata_, dict)
        and job.metadata_.get("is_impersonation") is True
    )

    event_extra: dict[str, Any] | None = None

    if is_impersonation:
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

    if is_illustrate_prompt:
        generated_prompt = ""
        if final_result.get("outputs") and isinstance(final_result["outputs"], list):
            generated_prompt = (final_result["outputs"][0] or {}).get("content", "")
        if not generated_prompt and final_result.get("text"):
            generated_prompt = final_result["text"]
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

    if is_narrator:
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
    elif is_chat_reply or is_story_continue:
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

        entity_id = chat_id if is_chat_reply else story_id

        # --- Agentic tool-call handling ---
        if is_chat_reply and assistant_output.get("tool_calls"):
            metadata = job.metadata_ or {}
            if metadata.get("agentic") and metadata.get("orchestrator_depth", 0) < MAX_AGENTIC_DEPTH:
                # Decoupled DB checks; grant basic safe tool access by default.
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
                outputs=outputs,
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

        event_type_str = "chat_reply" if is_chat_reply else "story_continue"
        if is_chat_reply:
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
        if chat_id:
            event_extra = {
                "type": "chat_image",
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
        outputs = final_result["outputs"]
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
