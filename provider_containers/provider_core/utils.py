import os
import json
from typing import Any, AsyncIterator, Dict, Iterable, Optional

from provider_core.models import TaskEvent


def get_safe_path(base_dir: str, requested_path: str) -> str:
    """
    Resolve and validate a path to prevent directory traversal.

    Args:
        base_dir: The trusted base directory.
        requested_path: The user-provided path component.

    Returns:
        The absolute resolved path if valid.

    Raises:
        ValueError if path traversal is detected.
    """
    # Remove leading slashes to prevent absolute path interpretation
    clean_path = requested_path.lstrip("/\\")

    # Resolve full path
    if not clean_path.strip():
        raise ValueError("Invalid path: path cannot be empty")
        
    full_path = os.path.realpath(os.path.join(base_dir, clean_path))
        
    base_path = os.path.realpath(base_dir)

    # Check if the resolved path starts with the base path
    if os.path.commonpath([base_path, full_path]) != base_path:
         raise ValueError("Access denied: Path outside allowed directory")

    return full_path


def build_deploy_compatibility_response(
    *,
    backend_url: str,
    provider_id: str,
    provider_type: str,
) -> Dict[str, Any]:
    """Return a compatibility payload for deprecated worker-local deploy endpoints."""
    base_url = (backend_url or "").rstrip("/")
    if base_url:
        deploy_endpoint = f"{base_url}/api/providers/{provider_id}/deploy"
        status_endpoint = f"{base_url}/api/providers/{provider_id}/deploy-status"
    else:
        deploy_endpoint = f"/api/providers/{provider_id}/deploy"
        status_endpoint = f"/api/providers/{provider_id}/deploy-status"

    return {
        "status": "deprecated",
        "accepted": False,
        "compatibility_mode": True,
        "source_of_truth": "backend_orchestrator",
        "message": "Worker-local deploy endpoint is deprecated; use backend provider deploy endpoint.",
        "provider_id": provider_id,
        "provider_type": provider_type,
        "backend_deploy_endpoint": deploy_endpoint,
        "backend_deploy_status_endpoint": status_endpoint,
    }


def comfy_status_to_task_event(update: Dict[str, Any], job_id: Optional[str] = None) -> Optional[TaskEvent]:
    """Translate a legacy ComfyUI ``{"status": ...}`` progress dict into a unified TaskEvent.

    Used by image workers so the backend needs only one event schema.
    Returns ``None`` for updates that carry no meaningful progress (e.g. keep-alive).
    """
    if not isinstance(update, dict):
        return None
    status = (update.get("status") or "").lower()
    data = update.get("data") or {}

    if status == "success":
        # ComfyUI returns images as a list of {"data": base64, ...} or
        # {"filename": ..., "subfolder": ..., "type": ...}. Compose artifacts.
        raw_images = update.get("images") or data.get("images") or []
        artifacts = []
        for img in raw_images:
            if isinstance(img, dict):
                artifacts.append({
                    "type": "image",
                    "data": img.get("data"),
                    "filename": img.get("filename"),
                    "subfolder": img.get("subfolder"),
                    "image_type": img.get("type"),
                })
        return TaskEvent(event="completed", job_id=job_id, outputs=artifacts)

    if status == "error":
        return TaskEvent(event="failed", job_id=job_id, message=update.get("message") or "Image generation failed")

    if status == "cancelled":
        return TaskEvent(event="cancelled", job_id=job_id, message=update.get("message"))

    if status == "executing":
        return TaskEvent(event="node", job_id=job_id, node=update.get("node"))

    # queued / running / progress / starting / preparing -> progress fraction
    value = update.get("value")
    if value is None:
        progress = update.get("progress")
        if isinstance(progress, dict):
            max_v = progress.get("max") or 0
            cur = progress.get("value") or 0
            value = (cur / max_v) if max_v else None
    return TaskEvent(event="progress", job_id=job_id, value=value)


async def translate_task_events(
    source: AsyncIterator[str],
    job_id: Optional[str] = None,
) -> AsyncIterator[str]:
    """Wrap a legacy ComfyUI NDJSON stream and re-emit it as TaskEvent NDJSON.

    Each item from ``source`` is either already a TaskEvent JSON string or a
    legacy ``{"status": ...}`` dict (string or dict). Emits unified
    ``TaskEvent.to_ndjson()`` lines for every meaningful update.
    """
    async for item in source:
        if isinstance(item, TaskEvent):
            yield item.to_ndjson()
            continue
        if isinstance(item, str):
            try:
                parsed = json.loads(item)
            except (ValueError, TypeError):
                # Pass through lines we cannot parse (e.g. keep-alives are skipped upstream).
                continue
        else:
            parsed = item
        te = comfy_status_to_task_event(parsed, job_id=job_id)
        if te is not None:
            yield te.to_ndjson()
