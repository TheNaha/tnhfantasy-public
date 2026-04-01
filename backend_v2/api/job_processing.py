import base64
import asyncio
import io
import os
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.entities import JobStatus
from core.events import EventType, emit_job_event
from infrastructure.background_tasks import start_background_task
from infrastructure.logging import get_logger

logger = get_logger("job_processing")


def normalize_persisted_output(output: Dict[str, Any]) -> Dict[str, Any]:
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
        base_output_dir = os.environ.get(
            "OUTPUT_DIR",
            os.path.join(os.path.dirname(__file__), "../output"),
        )
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


def normalize_external_outputs(outputs) -> List[Dict[str, Any]]:
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


def build_job_outputs(job, images: List[Dict[str, Any]], provider_id: str) -> List[Dict[str, Any]]:
    """Persist worker images and return normalized job outputs."""
    from PIL import Image

    from infrastructure.image_processor import (
        get_output_path,
        save_image_with_metadata,
        write_metadata_sidecar,
    )

    outputs: List[Dict[str, Any]] = []
    base_output_dir = os.environ.get(
        "OUTPUT_DIR",
        os.path.join(os.path.dirname(__file__), "../output"),
    )
    final_output_dir = get_output_path(base_output_dir)

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
            full_metadata = {
                "job_id": job.id,
                "filename": filename,
                "provider": provider_id,
            }
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


async def mark_job_post_processing(
    *,
    job_service,
    job_id: str,
    outputs: List[Dict[str, Any]],
    provider_id: Optional[str] = None,
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
    outputs: List[Dict[str, Any]],
    provider_id: Optional[str] = None,
    load_balancer=None,
) -> None:
    await job_service.update_job(
        job_id,
        status=JobStatus.COMPLETED,
        outputs=outputs,
        progress=100,
        overall_progress=100,
        provider_id=provider_id,
    )

    if load_balancer and provider_id:
        load_balancer.report_success(provider_id)
        load_balancer.release_job(provider_id)


async def wait_for_gallery_outputs(
    outputs: List[Dict[str, Any]],
    *,
    resolve_output_path,
    attempts: int = 20,
    delay_seconds: float = 0.5,
) -> None:
    output_refs = [
        output.get("relative_path") or output.get("filename")
        for output in outputs
        if isinstance(output, dict) and output.get("filename")
    ]
    if not output_refs:
        return

    for _ in range(attempts):
        if all(resolve_output_path(ref) for ref in output_refs):
            return
        await asyncio.sleep(delay_seconds)


async def finalize_persisted_job_outputs(
    *,
    job_service,
    job_id: str,
    outputs: List[Dict[str, Any]],
    provider_id: Optional[str] = None,
    load_balancer=None,
    process_image_background_fn: Optional[Callable[[str, str], Awaitable[Any]]] = None,
) -> None:
    await mark_job_post_processing(
        job_service=job_service,
        job_id=job_id,
        outputs=outputs,
        provider_id=provider_id,
    )
    await emit_job_event(
        EventType.JOB_POST_PROCESSING,
        {
            "id": job_id,
            "provider_id": provider_id,
            "status": JobStatus.POST_PROCESSING.value,
            "outputs": outputs,
        },
    )

    async def complete_when_ready():
        from services.gallery_indexer import gallery_indexer

        try:
            for output in outputs:
                path = output.get("path")
                if path:
                    try:
                        await asyncio.to_thread(gallery_indexer.add_file, path)
                    except Exception as exc:
                        logger.warning("gallery_index_update_failed", job_id=job_id, path=path, error=str(exc))

                if process_image_background_fn and path and output.get("type") == "image":
                    await process_image_background_fn(path, job_id)

            await wait_for_gallery_outputs(
                outputs,
                resolve_output_path=gallery_indexer.get_path,
            )
            await complete_job(
                job_service=job_service,
                job_id=job_id,
                outputs=outputs,
                provider_id=provider_id,
                load_balancer=load_balancer,
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
                load_balancer.release_job(provider_id)

    start_background_task(
        complete_when_ready(),
        task_name=f"job_finalize:{job_id}",
    )


async def finalize_successful_job(
    *,
    job,
    job_id: str,
    job_service,
    load_balancer,
    provider_id: str,
    final_result: Dict[str, Any],
    process_image_background_fn: Callable[[str, str], Any],
) -> None:
    """Finalize a successful provider result and schedule image post-processing."""
    images = final_result.get("images", [])
    outputs = build_job_outputs(job, images, provider_id)

    await finalize_persisted_job_outputs(
        job_service=job_service,
        job_id=job_id,
        outputs=outputs,
        provider_id=provider_id,
        load_balancer=load_balancer,
        process_image_background_fn=process_image_background_fn,
    )
