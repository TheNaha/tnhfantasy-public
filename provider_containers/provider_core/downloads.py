"""Shared download pipeline helpers for provider workers."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

from .validation import validate_downloaded_file

ProgressCallback = Callable[[Dict[str, Any]], None]
LogCallback = Callable[[str], None]


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

    resolved_hf_token = token if token and token.startswith("hf_") else hf_token
    resolved_civitai_token = token if token and not token.startswith("hf_") else civitai_token

    used_hf_token = False
    used_civitai_token = False

    if "huggingface.co" in url and resolved_hf_token:
        headers["Authorization"] = f"Bearer {resolved_hf_token}"
        used_hf_token = True
    elif "civitai.com" in url and resolved_civitai_token:
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
    print(message)


def download_model_to_path(
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
    chunk_size: int = 1024 * 1024,
    preview_timeout_seconds: float = 30.0,
    request_timeout_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    """Download a model file to disk with strict validation and atomic rename."""
    logger = log or _default_log
    label = path or os.path.basename(full_path)
    temp_path = full_path + ".downloading"

    resolved_url, headers, auth_info = build_authenticated_download_request(
        url,
        token,
        hf_token=hf_token,
        civitai_token=civitai_token,
    )

    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    logger(f"[{log_prefix}] Starting: {label}")
    logger(f"[{log_prefix}] URL: {resolved_url[:80]}...")
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
        return {"status": "error", "message": error_message, "error": error_message}
