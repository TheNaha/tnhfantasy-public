import os
import json
from typing import Any, AsyncIterator, Dict, Optional

from provider_core.models import TaskEvent

# Must stay in sync with the `event` Literal on TaskEvent in models.py.
# "cached_nodes" was missing here while being a valid TaskEvent.event value, so
# a canonical cached_nodes line from a ComfyUI worker was not recognised and was
# re-emitted as a contentless `progress` with value=None — reporting a progress
# step for an event that carries no progress.
_TASK_EVENT_KINDS = {
    "started", "progress", "delta", "node", "cached_nodes", "artifact", "completed",
    "failed", "cancelled",
}


LOCK_SUFFIX = ".lock"
DOWNLOADING_SUFFIX = ".downloading"

# Suffixes of files that live *beside* a model rather than being one.
SIDECAR_SUFFIXES = (".json", ".preview.png", ".sha256", ".txt", ".yaml", ".yml")

# Files the download pipeline itself owns. These are not models and must never be
# listed as one, registered in the model registry, or deleted by reconciliation.
#
# `exclusive_path_lock` creates `<model>.lock` and `download_model` creates
# `<model>.<pid>.<hex>.downloading`. Reconciliation runs with `delete_invalid`
# unconditionally true, and a 0-byte lock file fails the size check, so
# validation used to `os.remove` it — then, because `os.path.splitext(
# "x.safetensors.lock")[0]` is `"x.safetensors"`, delete `x.safetensors.json`
# and `x.safetensors.preview.png` alongside it. That silently destroyed the
# metadata and preview of every model ever downloaded. Deleting an in-flight
# `.downloading` was worse: the writer kept its file descriptor, transferred the
# whole file, and then failed at `os.replace`, which reconciliation reported as a
# failed download.
#
# Unlinking the lock also defeats the lock: a second downloader `O_CREAT`s a new
# inode, takes a *different* flock, and the interleaving corruption the lock
# exists to prevent happens again.
TRANSIENT_SUFFIXES = (LOCK_SUFFIX, DOWNLOADING_SUFFIX)


def is_transient_artifact(name: str) -> bool:
    """True for a file the download pipeline owns, never a model."""
    return str(name).endswith(TRANSIENT_SUFFIXES)


def is_sidecar_artifact(name: str) -> bool:
    """True for a metadata/preview file that accompanies a model."""
    return str(name).endswith(SIDECAR_SUFFIXES)


def is_model_file(name: str) -> bool:
    """True when a directory entry should be treated as a model file.

    The single predicate every listing and validation path should use, so a new
    pipeline-owned suffix is excluded everywhere at once instead of being added
    to a per-engine exclusion list that can drift.
    """
    return not (is_transient_artifact(name) or is_sidecar_artifact(name))


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
        deploy_endpoint = f"{base_url}/api/v2/providers/{provider_id}/deploy"
        status_endpoint = f"{base_url}/api/v2/providers/{provider_id}/deploy-status"
    else:
        deploy_endpoint = f"/api/v2/providers/{provider_id}/deploy"
        status_endpoint = f"/api/v2/providers/{provider_id}/deploy-status"

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
                artifact = {
                    "type": "image",
                    "data": img.get("data"),
                    "filename": img.get("filename"),
                    "subfolder": img.get("subfolder"),
                    "image_type": img.get("type"),
                }
                # Preserve the base64 marker so the backend knows it must decode
                # and persist this artifact instead of treating it as an
                # already-on-disk file (e.g. direct_url providers).
                if img.get("_base64_encoded") or img.get("data"):
                    artifact["_base64_encoded"] = True
                artifacts.append(artifact)
        return TaskEvent(event="completed", job_id=job_id, outputs=artifacts)

    if status == "error":
        return TaskEvent(
            event="failed",
            job_id=job_id,
            message=update.get("message") or "Image generation failed",
            retryable=update.get("retryable"),
        )

    if status == "cancelled":
        return TaskEvent(event="cancelled", job_id=job_id, message=update.get("message"))

    if status == "executing":
        return TaskEvent(event="node", job_id=job_id, node=update.get("node"))

    # progress event with a None value (which would stall the backend reducer).
    #
    # `queued` is in this list because workflow_executor.execute_comfy_workflow
    # yields `{"status": "queued", "prompt_id": ...}` unconditionally, so it is
    # the FIRST NDJSON line of every ComfyUI-backed job. It carries no `value`,
    # so it fell through every branch below and became
    # `TaskEvent(event="progress", value=None)` — a progress event with nothing
    # to progress. The HTTP-stream reducer coerces that to 0 and writes it to the
    # DB (backend_v2/services/provider_client.py:180-189), and the WS path
    # explicitly guards the same shape (infrastructure/worker_ws.py:158-160), so
    # both ends had a special case for a line the worker should never have sent.
    if status in ("execution_interrupted", "execution_start", "queued"):
        return None
    
    if status == "execution_cached":
        return TaskEvent(event="cached_nodes", job_id=job_id, nodes=update.get("nodes") or data.get("nodes") or [])

    value = update.get("value")
    max_v = update.get("max") or 0
    if value is not None and max_v:
        value = round(value / max_v * 100)
    elif value is None:
        progress = update.get("progress")
        if isinstance(progress, dict):
            p_max = progress.get("max") or 0
            p_cur = progress.get("value") or 0
            value = round(p_cur / p_max * 100) if p_max else None
    elif value is not None and value <= 1:
        # Defensive: legacy workers may emit a 0..1 fraction; canonical is percent 0..100.
        value = round(value * 100)

    return TaskEvent(event="progress", job_id=job_id, value=value)


async def translate_task_events(
    source: AsyncIterator[str],
    job_id: Optional[str] = None,
) -> AsyncIterator[str]:
    """Wrap a legacy ComfyUI NDJSON stream and re-emit it as TaskEvent NDJSON.

    Each item from ``source`` is either already a TaskEvent (instance or JSON
    string) or a legacy ``{"status": ...}`` dict (string or dict). Emits
    unified ``TaskEvent.to_ndjson()`` lines for every meaningful update.
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
        if isinstance(parsed, dict) and parsed.get("event") in _TASK_EVENT_KINDS:
            # Already a TaskEvent payload (e.g. beam's cancellation events);
            # pass through unchanged instead of misreading it as a legacy
            # {"status": ...} update.
            try:
                yield TaskEvent(**{k: v for k, v in parsed.items() if k in TaskEvent.model_fields}).to_ndjson()
            except Exception:
                continue
            continue
        te = comfy_status_to_task_event(parsed, job_id=job_id)
        if te is not None:
            yield te.to_ndjson()
