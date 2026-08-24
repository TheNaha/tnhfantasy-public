"""
Image-specific processing utilities.

This module owns the functions that persist raw provider image outputs into
the DB-backed ``assets`` indexer and normalize output shapes. These are image-
only concerns and do not belong in the generic ``job_processing`` module.
"""

from __future__ import annotations

import base64
import io
import os
from datetime import datetime, timezone
from typing import Any

from PIL import Image

from config import settings
from infrastructure.logging import get_logger

logger = get_logger("image_processing")


def normalize_persisted_output(output: dict[str, Any]) -> dict[str, Any]:
    """Normalize a single persisted output dict.

    Ensures ``relative_path`` is populated from ``path`` when missing and
    derives ``subfolder`` from the relative path.
    """
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


def build_job_outputs(
    job: Any,
    images: list[dict[str, Any]],
    provider_id: str,
    duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Persist worker images and return normalized job outputs.

    Saves base64 images to the output directory, writes metadata sidecars,
    and returns a list of normalized output dicts suitable for storing on
    the ``Job.outputs`` field.
    """
    from infrastructure.image_processor import (
        get_output_path,
        save_image_with_metadata,
        write_metadata_sidecar,
    )

    outputs: list[dict[str, Any]] = []
    base_output_dir = settings.output_dir
    workspace = (job.metadata_ or {}).get("workspace", "main")
    final_output_dir = get_output_path(base_output_dir, subdir="", workspace=workspace)

    if duration_seconds is None:
        job_started_at = getattr(job, "started_at", None)
        if job_started_at:
            now = datetime.now(timezone.utc)
            if job_started_at.tzinfo is None:
                job_started_at = job_started_at.replace(tzinfo=timezone.utc)
            duration_seconds = (now - job_started_at).total_seconds()

    for img in images:
        filename = img.get("filename", "output.png")
        subfolder = img.get("subfolder", "")

        if img.get("data"):
            image_data = base64.b64decode(img["data"])

            if subfolder:
                target_dir = get_output_path(base_output_dir, subdir=subfolder, workspace=workspace)
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
                full_metadata["job_created_at"] = job_created_at
                full_metadata["job_timeline_anchor"] = job_created_at
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


def _serialize_datetime(value: Any) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except Exception as exc:
            logger.debug("datetime_isoformat_failed", error=str(exc))
    return str(value)

