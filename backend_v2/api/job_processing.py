import base64
import io
import os
from typing import Any, Callable, Dict, List

from core.entities import JobStatus
from infrastructure.background_tasks import start_background_task
from infrastructure.logging import get_logger

logger = get_logger("job_processing")


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
                "path": output_path,
            }
        else:
            output = {
                "type": "image",
                "filename": filename,
                "subfolder": subfolder,
            }

        outputs.append(output)

    return outputs


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

    await job_service.update_job(
        job_id,
        status=JobStatus.COMPLETED,
        outputs=outputs,
        progress=100,
        overall_progress=100,
    )

    load_balancer.report_success(provider_id)
    load_balancer.release_job(provider_id)
    logger.info("job_completed", job_id=job_id, outputs=len(outputs), provider_id=provider_id)

    for output in outputs:
        if output.get("path") and output.get("type") == "image":
            start_background_task(
                process_image_background_fn(output["path"], job_id),
                task_name=f"image_post_process:{job_id}:{output['path']}",
            )
