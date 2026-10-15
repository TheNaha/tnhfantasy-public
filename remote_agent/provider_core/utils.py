import os
from typing import Optional


LOCK_SUFFIX = ".lock"
DOWNLOADING_SUFFIX = ".downloading"
PUBLISHING_SUFFIX = ".publishing"

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
TRANSIENT_SUFFIXES = (LOCK_SUFFIX, DOWNLOADING_SUFFIX, PUBLISHING_SUFFIX)


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


# Suffixes that legitimately live *inside* a model directory and are not models.
#
# `models/embeddings` and `models/wildcards` hold `.txt` prompt files and
# `models/poses` holds `.yaml` pose configs. All three directories are in
# `MODEL_DIRECTORIES`, so the reconciliation validator walks them — and it runs
# with `delete_invalid=True` every couple of hours.
#
# `validate_downloaded_file` skips the header check for these extensions but
# still applies `MIN_MODEL_SIZE`, so an ordinary 200-byte wildcard list came back
# `valid: False, indeterminate: False` — a definite verdict, not a read failure —
# and was `os.remove`d. Measured on the remote agent: four `.txt`/`.yaml` files
# deleted from one `models/wildcards` directory in a single sweep, only the one
# over 10 KiB surviving. There is no undo and no notification; the operator finds
# out when a prompt stops applying.
NON_MODEL_SUFFIXES = (
    ".txt", ".yaml", ".yml", ".json", ".md", ".markdown", ".csv",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
)


def is_model_candidate(name: str) -> bool:
    """True when a directory entry should be *validated*, and so possibly deleted.

    Narrower than `is_model_file`, which only excludes pipeline-owned and sidecar
    names. This additionally excludes the non-model assets that are supposed to
    be in a model directory at all, because the validator's failure verdict
    removes the file.

    Anything this returns False for must not be passed to
    `validate_downloaded_file` on a `delete_invalid` path. That is the whole
    point of the predicate: it is a delete guard, not a listing filter.
    """
    return is_model_file(name) and not str(name).lower().endswith(NON_MODEL_SUFFIXES)


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
    # Remove leading slashes to prevent absolute path interpretation and fold
    # backslashes so Windows-style traversal cannot slip past the checks below.
    clean_path = requested_path.lstrip("/\\").replace("\\", "/")

    # Resolve full path
    if not clean_path.strip() or clean_path.strip("/") == "":
        raise ValueError("Invalid path: path cannot be empty")

    if "\0" in requested_path:
        raise ValueError("Invalid path: null bytes are not allowed")

    logical_base = os.path.abspath(base_dir)
    logical_path = os.path.abspath(os.path.join(logical_base, clean_path))

    # Check if the resolved path starts with the base path (prevent directory traversal)
    try:
        common = os.path.commonpath([logical_base, logical_path])
    except ValueError:
        raise ValueError("Access denied: Path outside allowed directory")

    if common != logical_base:
        raise ValueError("Access denied: Path outside allowed directory")

    return logical_path


def determine_download_token(
    url: str, hf_token: str, civitai_token: str
) -> Optional[str]:
    """Which of the two registry tokens authenticates this download URL.

    Lives here rather than in its own module because it is the only surviving
    part of `provider_core.reconciliation`, which was deleted on 2026-10-09
    together with the container workers it served: the backend replaced it with
    `services/in_process_reconciliation.py`, and this predicate is the one piece
    `remote_agent/server.py` still needs on its own download path.

    Returns None for a URL neither registry hosts, which is the correct answer
    for an unauthenticated mirror — not a signal to send a token anyway.
    """
    if not url:
        return None
    if "huggingface.co" in url:
        return hf_token
    if "civitai.com" in url or "civitai.red" in url:
        return civitai_token
    return None
