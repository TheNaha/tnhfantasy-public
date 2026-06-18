"""Shared validation helpers for provider workers."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

# Minimum model size in bytes (10KB).
MIN_MODEL_SIZE = 10 * 1024

# File signatures that we consider recognized for download validation.
VALID_FILE_HEADERS = {
    b'{"__metadata__': "safetensors",
    b"{": "safetensors/json",
    b"PK": "zip/ckpt",
    b"\x80\x04": "pickle",
    b"\x80\x05": "pickle5",
    b"GGUF": "gguf",
    b"\x89PNG": "png",
}

_SKIP_HEADER_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".json",
    ".txt",
    ".yaml",
    ".yml",
)


def validate_downloaded_file(
    path: str,
    total_size: int = 0,
    *,
    unknown_header_log_prefix: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate a downloaded file and return a normalized validation payload."""
    validation_errors = []

    if not os.path.exists(path):
        return {"valid": False, "error": "File not found"}

    actual_size = os.path.getsize(path)
    if total_size > 0 and actual_size != total_size:
        validation_errors.append(f"Size mismatch: expected {total_size}, got {actual_size}")

    if actual_size < MIN_MODEL_SIZE:
        validation_errors.append(
            f"File too small: {actual_size} bytes (min: {MIN_MODEL_SIZE})"
        )

    detected_format = "unknown"
    header_valid = False
    skip_header_check = path.endswith(_SKIP_HEADER_EXTENSIONS)

    if not skip_header_check and actual_size >= 16:
        try:
            with open(path, "rb") as file_handle:
                header = file_handle.read(16)

            for magic, fmt in VALID_FILE_HEADERS.items():
                if header.startswith(magic):
                    header_valid = True
                    detected_format = fmt
                    break

            if not header_valid and header[0:1] == b"{":
                header_valid = True
                detected_format = "safetensors/json"

            if not header_valid:
                lowered = header.lower()
                if b"<html" in lowered or b"<!doctype" in lowered:
                    validation_errors.append(
                        "Downloaded HTML instead of model (possible auth error)"
                    )
                elif unknown_header_log_prefix:
                    print(
                        f"[{unknown_header_log_prefix}] Unknown format: "
                        f"header={header[:8].hex()}"
                    )
        except Exception as exc:
            validation_errors.append(f"Error reading header: {exc}")

    if "safetensors" in detected_format or path.endswith(".safetensors"):
        if actual_size >= MIN_MODEL_SIZE and not validation_errors:
            try:
                import struct
                import json
                with open(path, 'rb') as f:
                    header_size_bytes = f.read(8)
                    if len(header_size_bytes) < 8:
                        raise ValueError("File too small for safetensors header")
                    header_size = struct.unpack('<Q', header_size_bytes)[0]
                    if header_size > actual_size - 8:
                        raise ValueError(f"Invalid header size: {header_size} > {actual_size - 8}")
                    header_bytes = f.read(header_size)
                    header = json.loads(header_bytes)
                    if not isinstance(header, dict):
                        raise ValueError("Header is not a dict")
            except Exception as exc:
                validation_errors.append(f"Safetensors corrupted: {exc}")

    if validation_errors:
        return {
            "valid": False,
            "error": "; ".join(validation_errors),
            "errors": validation_errors,
            "format": detected_format,
        }

    return {
        "valid": True,
        "format": detected_format,
        "size": actual_size,
    }
