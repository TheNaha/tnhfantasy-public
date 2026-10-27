"""Shared validation helpers for provider workers."""

from __future__ import annotations

import os
import struct
import json
from typing import Any, Dict, Optional
from .logging import get_logger
from .utils import NON_MODEL_SUFFIXES

logger = get_logger("provider_core.validation")

# Minimum model size in bytes (10KB).
MIN_MODEL_SIZE = 10 * 1024

# File signatures that we consider recognized for download validation.
VALID_FILE_HEADERS = {
    b"{": "json",
    b"PK": "zip/ckpt",
    b"\x80\x04": "pickle",
    b"\x80\x05": "pickle5",
    b"GGUF": "gguf",
    b"\x89PNG": "png",
}

# Derived from the shared tuple rather than re-listed, because the two answers
# must not be able to disagree: this list decides whether the header check is
# skipped, `is_model_candidate` decides whether the file is validated (and hence
# deleted) at all. A suffix added to one and not the other is exactly the drift
# that removed four files from a wildcards directory.
_SKIP_HEADER_EXTENSIONS = tuple(
    suffix for suffix in NON_MODEL_SUFFIXES if suffix in (
        ".png", ".jpg", ".jpeg", ".json", ".txt", ".yaml", ".yml",
    )
)


def validate_downloaded_file(
    path: str,
    total_size: int = 0,
    *,
    unknown_header_log_prefix: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate a downloaded file and return a normalized validation payload.

    Three outcomes, not two:

    * `valid: True` — read it, it is fine.
    * `valid: False, indeterminate: False` — read it, it is genuinely bad.
    * `valid: False, indeterminate: True` — **could not** read it (EIO, ENOMEM,
      EMFILE, a JSON parse error, a gcsfuse stall).

    That third case is the reason this function has a flag rather than a boolean.
    A `read()` raising `OSError` and a header that genuinely is not a model both
    used to append to the same `validation_errors` list, so both produced
    `valid: False`. Reconciliation calls all three validators with
    `delete_invalid=True` (`image_worker/engines/modal/client.py`,
    `llm_worker/engines/modal/client.py`, `image_worker/engines/beam/client.py`),
    which then `os.remove`d the model *and* its `.json` and `.preview.png`
    sidecars. So one transient read error on a healthy 7 GB checkpoint destroyed
    it, unattended, every 2 hours. These are network (gcsfuse) mounts where EIO
    and stalls are far more likely than on a local disk, and it is exactly the
    failure direction that costs money.

    A caller that can act destructively on `invalid` MUST check `indeterminate`
    first. Deleting on an indeterminate result is never correct: the file may be
    fine, and there is no way to recover a multi-GB download that was deleted on
    a guess.
    """
    validation_errors = []
    # Set when a failure is "we could not find out" rather than "it is bad".
    # Tracked separately so the destructive callers can refuse to act on it.
    indeterminate = False

    if not os.path.isfile(path):
        return {
            "valid": False,
            "indeterminate": True,
            "error": "File not found or is a directory",
        }

    try:
        actual_size = os.path.getsize(path)
    except OSError as exc:
        # EACCES, EIO, ENOENT racing a download. Not a verdict on the file.
        logger.warning(f"validation_stat_failed: path={path} error={exc}")
        return {
            "valid": False,
            "indeterminate": True,
            "error": f"Could not stat file: {exc}",
        }

    min_size = 512 if "embedding" in path.lower() else MIN_MODEL_SIZE
    if total_size > 0 and actual_size != total_size:
        validation_errors.append(f"Size mismatch: expected {total_size}, got {actual_size}")

    if actual_size < min_size:
        validation_errors.append(
            f"File too small: {actual_size} bytes (min: {min_size})"
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

            # Safetensors files begin with an 8-byte unsigned little-endian integer (header length N),
            # followed by a JSON object string starting with '{'.
            if not header_valid and len(header) >= 9:
                try:
                    s_len = struct.unpack("<Q", header[:8])[0]
                    if 2 <= s_len <= min(100 * 1024 * 1024, max(0, actual_size - 8)) and header[8:9] in (b"{", b" ", b"\t", b"\n", b"\r"):
                        header_valid = True
                        detected_format = "safetensors"
                except Exception:
                    pass

            if not header_valid and (".safetensors" in os.path.basename(path).lower()) and len(header) >= 8:
                try:
                    s_len = struct.unpack("<Q", header[:8])[0]
                    if 2 <= s_len <= min(100 * 1024 * 1024, max(0, actual_size - 8)):
                        header_valid = True
                        detected_format = "safetensors"
                except Exception:
                    pass

            if header_valid and detected_format == "json":
                # A JSON body is either a MODEL (some formats ship JSON) or a
                # PROXY ERROR ENVELOPE served with a 200. The header cannot
                # tell them apart — both start with `{` — so the content
                # has to.
                #
                # The `b"{"` magic is in `VALID_FILE_HEADERS`, so an error
                # envelope from a gateway (a rate limit, an auth failure, a
                # Cloudflare interstitial) passed validation and was published
                # as a model. The failure then surfaced as "llama-server
                # exited 1" with nothing pointing at the download.
                try:
                    # A proxy error envelope is SMALL; a JSON model is not.
                    # So only a file small enough to be an envelope is worth
                    # parsing — and it is parsed WHOLE, because a truncated
                    # prefix of a JSON document does not parse and would
                    # silently pass.
                    if actual_size <= 1024 * 1024:
                        with open(path, "rb") as file_handle:
                            probe = file_handle.read()
                        text = probe.decode("utf-8", errors="replace").lstrip()
                        if text.startswith("{") or text.startswith("["):
                            try:
                                parsed = json.loads(text)
                            except ValueError:
                                parsed = None
                            if isinstance(parsed, dict):
                                errorish = [
                                    k
                                    for k in ("error", "errors", "detail", "exception", "traceback")
                                    if k in parsed
                                ]
                                if errorish:
                                    validation_errors.append(
                                        "Downloaded a JSON error envelope instead of a model "
                                        f"(keys: {', '.join(errorish)})"
                                    )
                                    header_valid = False
                                    detected_format = "unknown"
                except OSError:
                    pass

            if not header_valid:
                lowered = header.lower()
                if b"<html" in lowered or b"<!doctype" in lowered:
                    validation_errors.append(
                        "Downloaded HTML instead of model (possible auth error)"
                    )
                elif b"{" in header[:1] or b"[" in header[:1]:
                    # A JSON body with a 200 status: a proxy error envelope,
                    # a rate-limit body, an auth error. Not a model.
                    validation_errors.append(
                        "Downloaded JSON instead of model (proxy or auth error)"
                    )
                elif unknown_header_log_prefix:
                    logger.warning(
                        f"[{unknown_header_log_prefix}] Unknown format: "
                        f"header={header[:8].hex()}"
                    )
                else:
                    # An UNRECOGNISED header is not a verdict of "valid".
                    #
                    # It used to be: the branch above only appended an error
                    # for HTML, and everything else fell through to
                    # `header_valid = False` with NO error appended — and the
                    # caller treats "no errors" as valid. So a CDN that
                    # answered 200 with a truncated or proxy-generated body was
                    # published as a model.
                    #
                    # It is now an error. A file whose format we do not
                    # recognise is not something we can load, and pretending
                    # otherwise moves the failure from "the download is
                    # broken" to "llama-server exited 1 with no clue why".
                    validation_errors.append(
                        f"Unrecognised file header: {header[:8].hex()}"
                    )
        except OSError as exc:
            # A read that fails is an I/O fault, not a corrupt file. These
            # providers store models on gcsfuse volumes where EIO and EMFILE are
            # routine, and this branch used to feed `delete_invalid`.
            logger.warning(f"validation_header_read_failed: path={path} error={exc}")
            validation_errors.append(f"Error reading header: {exc}")
            indeterminate = True
        except Exception as exc:  # pragma: no cover - defensive
            validation_errors.append(f"Error reading header: {exc}")
            indeterminate = True

    if detected_format == "safetensors" or ".safetensors" in os.path.basename(path).lower():
        if actual_size >= min_size and not validation_errors:
            try:
                with open(path, 'rb') as f:
                    header_size_bytes = f.read(8)
                    if len(header_size_bytes) < 8:
                        raise ValueError("File too small for safetensors header")
                    header_size = struct.unpack('<Q', header_size_bytes)[0]
                    if header_size > actual_size - 8:
                        raise ValueError(f"Invalid header size: {header_size} > {actual_size - 8}")
                    if header_size > 100 * 1024 * 1024:  # 100MB cap
                        raise ValueError(f"Header size too large (exceeds 100MB limit): {header_size}")
                    header_bytes = f.read(header_size)
                    header = json.loads(header_bytes)
                    if not isinstance(header, dict):
                        raise ValueError("Header is not a dict")
                    detected_format = "safetensors"
            except (ValueError, struct.error) as exc:
                # The bytes were read and do not parse as a safetensors header.
                # That IS a verdict.
                validation_errors.append(f"Safetensors corrupted: {exc}")
            except OSError as exc:
                logger.warning(f"validation_safetensors_read_failed: path={path} error={exc}")
                validation_errors.append(f"Error reading safetensors header: {exc}")
                indeterminate = True
            except Exception as exc:  # pragma: no cover - defensive
                validation_errors.append(f"Safetensors corrupted: {exc}")
                indeterminate = True

    if validation_errors:
        return {
            "valid": False,
            # Absent from the healthy result too, so a caller can use
            # `result.get("indeterminate")` without a KeyError.
            "indeterminate": indeterminate,
            "error": "; ".join(validation_errors),
            "errors": validation_errors,
            "format": detected_format,
        }

    return {
        "valid": True,
        "indeterminate": False,
        "format": detected_format,
        "size": actual_size,
    }
