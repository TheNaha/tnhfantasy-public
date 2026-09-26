"""Shared download pipeline helpers for provider workers."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import time
import uuid
from typing import Any, Callable, Dict, Iterator, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

from .utils import DOWNLOADING_SUFFIX
from .validation import validate_downloaded_file
from .logging import get_logger

logger = get_logger("provider_core.downloads")

ProgressCallback = Callable[[Dict[str, Any]], None]
LogCallback = Callable[[str], None]


@contextlib.contextmanager
def exclusive_path_lock(full_path: str) -> Iterator[None]:
    """Serialise downloads of the same destination across threads and processes.

    Without this, two concurrent downloads of one `full_path` shared the
    deterministic `<path>.downloading` temp file: the second `open(..., "wb")`
    truncated the first's partial data, both handles then wrote at their own
    offsets into the same inode, and both passed validation — the size is the
    full size either way, and whichever wrote offset 0 put a valid magic header
    there. The first to finish `os.replace`d a silently interleaved file into
    place. The second replaced it with its own interleaved version. A corrupted
    model published with no error anywhere.

    flock is used rather than an O_EXCL lock file because the kernel releases
    it if the process dies, so a crash mid-download cannot leave a lock that
    blocks every future attempt until someone deletes it by hand.
    """
    lock_path = f"{full_path}.lock"
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    handle = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        os.close(handle)


def _unique_temp_path(full_path: str) -> str:
    """Per-attempt temp path.

    Belt-and-braces with the lock: even if a lock is somehow bypassed, two
    attempts can no longer share a file, so interleaving is impossible. The
    previous deterministic `<path>.downloading` name was the root of the
    corruption described in exclusive_path_lock.
    """
    return f"{full_path}.{os.getpid()}.{uuid.uuid4().hex[:8]}.downloading"



def _append_query_param(url: str, key: str, value: str) -> str:
    """Append a query parameter only when the key does not already exist."""
    parsed = urlparse(url)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)

    if any(existing_key == key for existing_key, _ in query_items):
        return url

    query_items.append((key, value))
    return urlunparse(parsed._replace(query=urlencode(query_items)))


def build_authenticated_download_request(
    url: str,
    token: Optional[str] = None,
    *,
    hf_token: Optional[str] = None,
    civitai_token: Optional[str] = None,
) -> Tuple[str, Dict[str, str], Dict[str, bool]]:
    """Build a download URL and headers with provider token resolution rules."""
    headers: Dict[str, str] = {}
    resolved_url = url

    if not url:
        raise ValueError("download_url is empty or None — model may need to be re-added from CivitAI")

    resolved_hf_token = token if token and token.startswith("hf_") else hf_token
    resolved_civitai_token = token if token and not token.startswith("hf_") else civitai_token

    used_hf_token = False
    used_civitai_token = False

    hostname = (urlparse(url).hostname or "").lower()
    is_huggingface = hostname == "huggingface.co" or hostname.endswith(".huggingface.co")
    is_civitai = hostname in {"civitai.com", "civitai.red"} or hostname.endswith(".civitai.com")

    if is_huggingface and resolved_hf_token:
        headers["Authorization"] = f"Bearer {resolved_hf_token}"
        used_hf_token = True
    elif is_civitai and resolved_civitai_token:
        resolved_url = _append_query_param(url, "token", resolved_civitai_token)
        used_civitai_token = True

    auth_info = {
        "used_hf_token": used_hf_token,
        "used_civitai_token": used_civitai_token,
    }
    return resolved_url, headers, auth_info


def _safe_progress_emit(callback: Optional[ProgressCallback], payload: Dict[str, Any]) -> None:
    if not callback:
        return

    try:
        callback(payload)
    except Exception:
        # Progress updates must never break download flow.
        return


def _default_log(message: str) -> None:
    logger.info(message)


def download_model_to_path(**kwargs: Any) -> Dict[str, Any]:
    """Serialise downloads of the same destination, then perform the download.

    Keyword-only by design so this wrapper can forward everything without
    repeating the long parameter list. See exclusive_path_lock for why the
    serialisation is load-bearing rather than merely tidy.
    """
    full_path = kwargs.get("full_path")
    if not full_path:
        raise ValueError("full_path is required")
    with exclusive_path_lock(full_path):
        return _download_model_to_path_unlocked(**kwargs)


def _download_model_to_path_unlocked(
    *,
    url: str,
    full_path: str,
    path: Optional[str] = None,
    token: Optional[str] = None,
    hf_token: Optional[str] = None,
    civitai_token: Optional[str] = None,
    preview_url: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    log: Optional[LogCallback] = None,
    log_prefix: str = "Download",
    progress_callback: Optional[ProgressCallback] = None,
    validation_unknown_header_log_prefix: Optional[str] = None,
    chunk_size: int = 8 * 1024 * 1024,  # 8 MB — reduces Python iteration overhead for large files
    preview_timeout_seconds: float = 30.0,
    request_timeout_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    """Download a model file to disk with strict validation and atomic rename.

    Callers should use download_model_to_path, which holds the per-path lock.
    """
    logger = log or _default_log
    label = path or os.path.basename(full_path)
    temp_path = _unique_temp_path(full_path)

    if not url:
        raise ValueError("Cannot download model because download_url is missing or empty")

    resolved_url, headers, auth_info = build_authenticated_download_request(
        url,
        token,
        hf_token=hf_token,
        civitai_token=civitai_token,
    )

    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    logger(f"[{log_prefix}] Starting: {label}")
    logger(f"[{log_prefix}] Using temp file: {os.path.basename(temp_path)}")

    if auth_info["used_hf_token"]:
        logger(f"[{log_prefix}] Using HuggingFace token")
    if auth_info["used_civitai_token"]:
        logger(f"[{log_prefix}] Using CivitAI token")

    _safe_progress_emit(progress_callback, {"status": "starting", "percent": 0})

    try:
        request_kwargs: Dict[str, Any] = {"stream": True, "headers": headers}
        if request_timeout_seconds is not None:
            request_kwargs["timeout"] = request_timeout_seconds

        response = requests.get(resolved_url, **request_kwargs)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0) or 0)

        if total_size > 0:
            size_gb = total_size / (1024 ** 3)
            size_str = f"{size_gb:.2f} GB" if size_gb >= 1 else f"{total_size / (1024 ** 2):.1f} MB"
            logger(f"[{log_prefix}] Size: {size_str}")
        else:
            logger(f"[{log_prefix}] Size: Unknown")

        downloaded = 0
        last_log_percent = 0
        start_time = time.time()

        with open(temp_path, "wb") as file_handle:
            for chunk in response.iter_content(chunk_size):
                if not chunk:
                    continue

                file_handle.write(chunk)
                downloaded += len(chunk)

                elapsed = max(time.time() - start_time, 1e-6)
                speed_bytes_per_second = downloaded / elapsed
                percent = int((downloaded / total_size) * 100) if total_size > 0 else 0
                eta_seconds = (
                    (total_size - downloaded) / speed_bytes_per_second
                    if total_size > 0 and speed_bytes_per_second > 0
                    else 0
                )

                _safe_progress_emit(
                    progress_callback,
                    {
                        "status": "downloading",
                        "percent": percent,
                        "speed_mbps": speed_bytes_per_second / (1024 ** 2),
                        "downloaded_bytes": downloaded,
                        "total_bytes": total_size,
                        "eta_seconds": eta_seconds,
                    },
                )

                if total_size > 0 and percent >= last_log_percent + 10:
                    eta_str = f"{int(eta_seconds / 60)}m {int(eta_seconds % 60)}s" if eta_seconds > 60 else f"{int(eta_seconds)}s"
                    logger(
                        f"[{log_prefix}] {percent}% - "
                        f"{speed_bytes_per_second / (1024 ** 2):.1f} MB/s - ETA: {eta_str}"
                    )
                    last_log_percent = percent

        elapsed = max(time.time() - start_time, 1e-6)
        speed_mbps = (downloaded / (1024 ** 2)) / elapsed
        logger(f"[{log_prefix}] Download complete (temp file)")
        logger(
            f"[{log_prefix}] Size: {downloaded / (1024 ** 2):.1f} MB "
            f"in {elapsed:.1f}s ({speed_mbps:.1f} MB/s)"
        )

        validation = validate_downloaded_file(
            temp_path,
            total_size,
            unknown_header_log_prefix=validation_unknown_header_log_prefix,
        )

        if not validation.get("valid"):
            for err in validation.get("errors", [validation.get("error", "Validation failed")]):
                logger(f"[{log_prefix}] Validation error: {err}")
            raise ValueError(f"Validation failed: {validation.get('error', 'unknown validation error')}")

        detected_format = validation.get("format", "unknown")
        actual_size = int(validation.get("size", downloaded))
        logger(f"[{log_prefix}] Validation passed: {detected_format}")

        if os.path.exists(full_path):
            os.remove(full_path)
        os.replace(temp_path, full_path)
        logger(f"[{log_prefix}] Moved to final path: {label}")

        metadata_saved = False
        if metadata:
            metadata_path = os.path.splitext(full_path)[0] + ".json"
            with open(metadata_path, "w", encoding="utf-8") as metadata_handle:
                json.dump(metadata, metadata_handle)
            metadata_saved = True

        preview_saved = False
        if preview_url:
            try:
                preview_response = requests.get(preview_url, timeout=preview_timeout_seconds)
                if preview_response.status_code == 200:
                    preview_path = os.path.splitext(full_path)[0] + ".preview.png"
                    with open(preview_path, "wb") as preview_handle:
                        preview_handle.write(preview_response.content)
                    preview_saved = True
                    logger(f"[{log_prefix}] Preview saved")
            except Exception as preview_exc:
                logger(f"[{log_prefix}] Preview failed: {preview_exc}")

        success_payload = {
            "status": "success",
            "path": label,
            "size": actual_size,
            "speed_mbps": round(speed_mbps, 1),
            "format": detected_format,
            "validated": True,
            "downloaded_bytes": downloaded,
            "total_size_bytes": total_size,
            "metadata_saved": metadata_saved,
            "preview_saved": preview_saved,
        }

        _safe_progress_emit(
            progress_callback,
            {
                "status": "success",
                "percent": 100,
                "speed_mbps": round(speed_mbps, 1),
                "downloaded_bytes": downloaded,
                "total_bytes": total_size,
            },
        )

        return success_payload

    except Exception as exc:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

        error_message = str(exc)
        logger(f"[{log_prefix}] Error: {error_message}")
        _safe_progress_emit(
            progress_callback,
            {
                "status": "error",
                "percent": 0,
                "message": error_message,
            },
        )
        return {"status": "error", "message": error_message, }


def pending_download_paths(full_path: str) -> Iterator[str]:
    """Yield the temp files of every in-flight or abandoned attempt at `full_path`.

    `_unique_temp_path` names each attempt `<path>.<pid>.<hex>.downloading`, so a
    single fixed `.downloading` name no longer identifies "the" partial file.
    Deleting a model used to probe the old deterministic name and therefore
    never removed a partial download, leaving multi-GB files on the volume.
    """
    directory = os.path.dirname(full_path) or "."
    prefix = os.path.basename(full_path) + "."
    try:
        entries = os.listdir(directory)
    except OSError:
        return
    for entry in entries:
        if entry.startswith(prefix) and entry.endswith(DOWNLOADING_SUFFIX):
            yield os.path.join(directory, entry)
