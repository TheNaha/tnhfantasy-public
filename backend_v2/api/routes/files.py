# File routes - Gallery file listing, viewing, upload and deletion
#
# Serves files from two directories:
#   OUTPUT_DIR – generated images (PNG, organized by date)
#   INPUT_DIR  – user-uploaded source images for Img2Img/Inpainting
#
# KEY ENDPOINTS:
#   GET  /api/v2/assets                    – Keyset-paginated asset listing
#   GET  /api/v2/assets/dates              – Per-day counts for the timeline scrubber
#   GET  /api/v2/assets/{id}/file          – Serve one asset's original bytes
#   GET  /api/files/{filename}             – Serve a raw file (full resolution)
#   GET  /api/thumbnail/{size}/{filename}  – Serve a pre-generated WebP thumbnail
#   POST /api/files/upload                 – Upload a file to OUTPUT_DIR
#   POST /api/upload/input                 – Upload a source image (Img2Img)
#   POST /api/upload/mask                  – Upload an inpainting mask (base64→PNG)
#   DELETE /api/files/{filename}           – Delete a file and its thumbnail
#
# UPLOAD/EXPORT HARDENING:
#   All upload endpoints bound their body (see core/upload_validation.py), read
#   it in chunks so an oversized request dies early, verify that image bytes are
#   actually a readable image within the dimension budget, and sanitize the
#   client filename before it reaches the filesystem. Rejections raise
#   UploadValidationError -> HTTP 400 with a machine-readable `code`.
import asyncio
import random

from services.asset_reconciler import upsert_asset
import base64
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlmodel import Session, select
from starlette.background import BackgroundTask

from api.deps import (
    get_model_service_v2,
    get_provider_service,
    get_session,
    get_session_sync,
)
from infrastructure.logging import get_logger
from config import settings
from core.entities import Asset
from core.exceptions import (
    ComfyError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from core.sql_search import LIKE_ESCAPE_CHAR, like_contains
from core.upload_validation import (
    ALLOWED_UPLOAD_EXTENSIONS,
    IMAGE_EXTENSIONS,
    MAX_BATCH_ITEMS,
    MAX_EXPORT_FILES,
    MAX_EXPORT_FILE_MB,
    MAX_EXPORT_TOTAL_MB,
    MAX_INPUT_SIZE_MB,
    MAX_UPLOAD_SIZE_MB,
    UploadValidationError,
    decode_base64_bounded,
    human_size,
    inspect_image,
    read_upload_bounded,
    require_batch_size,
    require_declared_size,
    require_extension,
    sanitize_filename,
)
from services.statistics_service import (
    ASSET_GALLERY_TIMESTAMP,
    get_asset_date_histogram,
)


def _sync_session():
    """Open a synchronous DB session for non-request code paths in this module."""
    return get_session_sync()

logger = get_logger("files_route")

router = APIRouter(tags=["files"])

# Output directory - defaults to backend output folder
OUTPUT_DIR = settings.output_dir
INPUT_DIR = settings.input_dir
CACHE_DIR = os.environ.get("CACHE_DIR", os.path.join(os.path.dirname(__file__), "../../cache"))

# Byte budgets (overridable via COMFY_MAX_* env vars, see core/upload_validation)
MAX_INPUT_BYTES = MAX_INPUT_SIZE_MB * 1024 * 1024
MAX_UPLOAD_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
MAX_EXPORT_FILE_BYTES = MAX_EXPORT_FILE_MB * 1024 * 1024
MAX_EXPORT_TOTAL_BYTES = MAX_EXPORT_TOTAL_MB * 1024 * 1024
MAX_PATH_LENGTH = 1024
# Ceiling on any `search`/`q`/`tag` query parameter, in characters.
#
# Unbounded on purpose by omission: the value flows straight into
# `like_contains`, which is an ILIKE against `metadata_` — a jsonb blob averaging
# ~4 KB and holding the whole ComfyUI workflow. A 1 MB term is millions of
# comparisons per row against ~16k rows, and it is unauthenticated, so one
# request can pin the event loop for minutes.
#
# 200 characters is a generous search box. It is NOT arbitrary: the longest
# practical prompt-word query is a handful of tokens, and a legitimate search
# that needs more is a filter, which this app has (`base_model`, `model_type`,
# `tags`, `directory`).
MAX_SEARCH_LENGTH = 200
# Every item in an asset page carries its `metadata_` jsonb blob, so a page
# size is a payload budget and not just a row count. The other list routes in
# this app cap at 100-200; the asset page is the widest row in the schema, so it
# takes the smallest cap of the four.
MAX_ASSETS_PAGE_SIZE = 200

# Streaming chunk for asset copies. Whole-file reads on the copy path used to
# buffer an entire generated image into a `bytes` object in the event-loop process.
_COPY_CHUNK_BYTES = 1024 * 1024


def _bounded_search(
    description: str = "Search term (ILIKE substring match)",
    default: str | None = None,
):
    """A `search`/`q` parameter that is clamped at the declaration.

    Preferable to a check inside the handler: an HTTPException raised there needs
    a preceding `await` and a mutable `request`, where this one answers 422
    during validation before the handler runs at all.

    Deliberately no return annotation. `-> Query | None` reads fine on Python
    3.14, where PEP 649 defers annotation evaluation, and is a hard TypeError at
    import on 3.13 — which is what the deployed backend container runs — because
    `fastapi.Query` is a function, not a type, and `function | None` cannot be
    evaluated. The local venv is 3.14, so this failed only in the container.
    """
    if default is None:
        return Query(None, max_length=MAX_SEARCH_LENGTH, description=description)
    return Query(default, max_length=MAX_SEARCH_LENGTH, description=description)


def _cancel_checker(request: Request):
    """Build a should_cancel() hook that trips when the client disconnects.

    Polling the request on every chunk is cheap (the body is already spooled to
    a temp file) but not free, so it is sampled every few chunks.
    """
    state = {"ticks": 0}

    async def _should_cancel() -> bool:
        state["ticks"] += 1
        if state["ticks"] % 4:
            return False
        try:
            return await request.is_disconnected()
        except Exception:  # pragma: no cover - defensive, never block the upload
            return False

    return _should_cancel


def _indexed_thumbnail_path(relative_path: str, session: Session | None) -> str | None:
    """The exact thumbnail location for an asset, if the index knows it.

    One indexed lookup replaces a walk of the whole thumbnail tree. Returns
    `None` when the asset is not indexed, which is the only case where a search
    is justified.
    """
    rel = relative_path
    if not rel:
        return None

    def _lookup(sess):
        asset = sess.exec(
            select(Asset).where(Asset.relative_path == rel)
        ).first()
        if not asset and "/" not in rel:
            asset = sess.exec(select(Asset).where(Asset.filename == rel)).first()
        return asset.thumbnail_relative_path if asset else None

    try:
        # Reuses the caller's session when there is one. It used to open its own
        # via `_sync_session()` and ignore the parameter entirely, so the
        # batch-delete path paid a second pooled connection per thumbnail —
        # and read as though the session were being reused, which is the exact
        # confusion `_soft_delete_assets`' docstring exists to prevent.
        if session is not None:
            thumb_rel = _lookup(session)
        else:
            with _sync_session() as own:
                thumb_rel = _lookup(own)
    except Exception as exc:
        logger.debug("thumbnail_index_lookup_failed", path=rel, error=str(exc))
        return None
    if not thumb_rel:
        return None
    try:
        return get_safe_path(OUTPUT_DIR, thumb_rel)
    except ValidationError:
        return None


def _delete_thumbnails(local_path: str, session: Session | None = None) -> None:
    """Remove all thumbnail variants for an output image.

    Thumbnails live in OUTPUT_DIR/thumb mirrored by date hierarchy
    (output/thumb/YYYY/MM/DD/name.webp) plus legacy flat files
    (output/thumb/name.medium.png / name.full.png).

    The catch-all glob at the end is a full recursive walk of the thumbnail
    tree — twice, since it runs a `**/*.webp` and a `**/*.png` pattern. At
    `MAX_BATCH_ITEMS` (1000) that was 2000 full tree walks inside one request,
    which on a 13k-image library is minutes of syscalls. It now runs only when
    the index cannot name the thumbnail, which is the rare case; the indexed
    path is O(1).
    """
    import glob

    name_only = os.path.splitext(os.path.basename(local_path))[0]
    rel_dir = os.path.relpath(os.path.dirname(local_path), OUTPUT_DIR)

    candidates = [
        os.path.join(OUTPUT_DIR, "thumb", rel_dir, f"{name_only}.webp"),
        os.path.join(OUTPUT_DIR, "thumb", f"{name_only}.medium.png"),
        os.path.join(OUTPUT_DIR, "thumb", f"{name_only}.full.png"),
    ]
    # The partitioned layout the reconciler actually writes to, from the index.
    indexed = _indexed_thumbnail_path(
        os.path.relpath(local_path, OUTPUT_DIR).replace("\\", "/"), session
    )
    if indexed:
        candidates.append(indexed)

    for candidate in candidates:
        try:
            if os.path.exists(candidate):
                os.remove(candidate)
        except OSError as exc:
            logger.debug("thumbnail_remove_failed", path=candidate, error=str(exc))

    if indexed:
        # Every location the reconciler can name has been covered.
        return

    # Unindexed: catch any stragglers elsewhere in the thumb tree (same basename).
    thumb_root = os.path.join(OUTPUT_DIR, "thumb")
    for pattern in (f"**/{name_only}.webp", f"**/{name_only}.png"):
        for match in glob.glob(os.path.join(thumb_root, pattern), recursive=True):
            try:
                os.remove(match)
            except OSError as exc:
                logger.debug("thumbnail_remove_failed", path=match, error=str(exc))



async def _sync_file_to_providers(session: Session, filename: str, content: bytes, directory: str = "input") -> dict:
    """
    Sync an uploaded file to all active providers.
    Returns {"sync_status": str, "synced_count": int, "failed_count": int}.
    """
    from services.provider_runtime import resolve_provider_runtime_async

    sync_status = "local_only"
    synced_count = 0
    failed_count = 0

    try:
        service = get_provider_service(session)
        providers = await service.list_providers()

        active_providers = []
        for p in providers:
            p_id = p.get("id") if isinstance(p, dict) else getattr(p, "id", None)
            enabled = p.get("enabled") if isinstance(p, dict) else getattr(p, "enabled", False)

            if not enabled or not p_id:
                continue

            provider_entity = await service.get_provider(p_id)
            if not provider_entity:
                continue
            
            runtime = await resolve_provider_runtime_async(provider_entity)
            if getattr(runtime, "mode", "") == "in_process":
                active_providers.append({"id": p_id, "engine": True})
                continue
            # No other runtime carries a writable model tree.

        if active_providers:
            from services.engines.base import get_upload_max_bytes_encoded, get_upload_size_cap

            # Raw cap for the fail-fast (avoids base64-encoding a 7 GB body
            # just to discover it is over), encoded cap for the wire verdict
            # (base64 text carries ~33% overhead). Either over answers
            # sync_failed like the 413 path.
            upload_cap = get_upload_size_cap()
            encoded_cap = get_upload_max_bytes_encoded()
            encoded_len = ((len(content) + 2) // 3) * 4
            if (upload_cap and len(content) > upload_cap) or (
                encoded_cap and encoded_len > encoded_cap
            ):
                # Engines answer 413 past PROVIDER_UPLOAD_MAX_BYTES. Fail fast
                # here instead of pushing the bytes at every provider first.
                logger.warning(
                    "sync_provider_over_cap",
                    size=len(content),
                    cap=upload_cap,
                    providers=len(active_providers),
                )
                return {
                    "sync_status": "sync_failed",
                    "synced_count": 0,
                    "failed_count": len(active_providers),
                }
            for provider in active_providers:
                provider_id = provider["id"]

                # In-process engine upload. Engines without a model tree
                # (LLM, TTS, plain Direct) have no storage to sync to — skip
                # them like maintenance.py does instead of counting their
                # upload_file()->False as a failed provider.
                try:
                    from services.engines.engine_factory import get_engine

                    engine = get_engine(provider_id)
                    if engine is not None and not getattr(
                        engine, "manages_model_files", False
                    ):
                        continue
                    uploaded = (
                        await engine.upload_file(
                            filename=filename,
                            content_base64=base64.b64encode(content).decode(),
                            directory=directory,
                        )
                        if engine is not None
                        else False
                    )
                except NotImplementedError:
                    uploaded = False
                except Exception as e:
                    failed_count += 1
                    logger.warning("sync_provider_error", provider_id=provider_id, error=str(e))
                    continue
                if uploaded:
                    synced_count += 1
                else:
                    failed_count += 1
                    logger.warning("sync_provider_failed", provider_id=provider_id, reason="engine upload unsupported or failed")

            if synced_count > 0:
                sync_status = "synced"
            elif failed_count > 0:
                sync_status = "sync_failed"

    except Exception as e:
        logger.warning("sync_to_providers_failed", error=str(e), exc_info=True)
        sync_status = "sync_failed"

    return {"sync_status": sync_status, "synced_count": synced_count, "failed_count": failed_count}


class BatchDeleteRequest(BaseModel):
    directory: str
    files: list[str]


class BatchDownloadRequest(BaseModel):
    files: list[str]


def _unique_arcname(arcname: str, taken: set[str]) -> str:
    """Keep two same-named files from clobbering each other inside the ZIP."""
    if arcname not in taken:
        taken.add(arcname)
        return arcname
    stem, ext = os.path.splitext(arcname)
    for index in range(2, 1000):
        candidate = f"{stem} ({index}){ext}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
    candidate = f"{stem}-{os.urandom(4).hex()}{ext}"
    taken.add(candidate)
    return candidate


@router.post("/api/files/batch-download")
async def batch_download(req: BatchDownloadRequest):
    """Create a ZIP file of multiple images for batch download.

    Bounded by design: the request is capped at MAX_EXPORT_FILES entries, every
    file at MAX_EXPORT_FILE_MB and the archive at MAX_EXPORT_TOTAL_MB. The byte
    budget is checked *before* zipping so an over-budget request fails fast with
    a clear message instead of filling the temp volume. Files that no longer
    resolve are reported through `X-Missing-Count` / `X-Missing-Files`; if none
    of them resolve the request fails outright rather than returning a broken
    empty archive.

    The whole build runs on a worker thread. It used to run inline on the event
    loop, and between them the per-file `_resolve_asset_path` (up to 500 files,
    each opening its own synchronous session) and the DEFLATE pass over up to
    1 GiB stalled every other request, WebSocket frame and job dispatch for the
    duration of the compression.
    """
    if not req.files:
        raise UploadValidationError(
            "No files requested for download",
            code="EXPORT_NO_MATCHING_FILES",
            field="files",
        )

    if len(req.files) > MAX_EXPORT_FILES:
        raise UploadValidationError(
            f"Too many files requested: {len(req.files)} (limit {MAX_EXPORT_FILES}). "
            "Narrow the selection and try again.",
            code="EXPORT_TOO_MANY_FILES",
            field="files",
            details={"received": len(req.files), "max_files": MAX_EXPORT_FILES},
        )

    temp_path, headers = await asyncio.to_thread(_build_export_zip_sync, req.files)

    return FileResponse(
        temp_path,
        media_type="application/zip",
        headers=headers,
        background=BackgroundTask(os.remove, temp_path)
    )


def _build_export_zip_sync(filenames: list[str]) -> tuple[str, dict[str, str]]:
    """Resolve, measure and compress an export ZIP on a worker thread.

    Returns `(temp_path, headers)`. The archive is streamed into a temp file
    rather than a `BytesIO` + `getvalue()`, so a full second copy of a 1 GiB
    archive never exists in memory; `FileResponse` streams the file and
    `BackgroundTask` unlinks it afterwards.

    Raises `UploadValidationError` / `ComfyError` on failure, having removed the
    temp file in that case.
    """
    import zipfile

    # Resolve + measure first: cheaper than writing a ZIP we would discard.
    resolved: list[tuple[str, str]] = []  # (source_path, arcname)
    missing: list[str] = []
    total_bytes = 0
    taken: set[str] = set()

    # One session for the whole export: at MAX_EXPORT_FILES that is one pooled
    # connection instead of 500, each previously held across two SELECTs.
    with _sync_session() as session:
        for filename in filenames:
            source_path = _resolve_asset_path(filename, session)
            if not source_path:
                try:
                    candidate = get_safe_path(OUTPUT_DIR, filename)
                    if os.path.exists(candidate):
                        source_path = candidate
                except ValidationError:
                    source_path = None

            if not source_path or not os.path.isfile(source_path):
                missing.append(filename)
                continue

            try:
                size = os.path.getsize(source_path)
            except OSError as exc:
                logger.warning("batch_download_stat_failed", filename=filename, error=str(exc))
                missing.append(filename)
                continue

            if size > MAX_EXPORT_FILE_BYTES:
                raise UploadValidationError(
                    f"'{os.path.basename(filename)}' is {human_size(size)}, above the "
                    f"{human_size(MAX_EXPORT_FILE_BYTES)} per-file export limit",
                    code="EXPORT_TOO_LARGE",
                    field="files",
                    max_bytes=MAX_EXPORT_FILE_BYTES,
                    received_bytes=size,
                    details={"filename": os.path.basename(filename)},
                )

            total_bytes += size
            if total_bytes > MAX_EXPORT_TOTAL_BYTES:
                raise UploadValidationError(
                    f"Export would total more than the {human_size(MAX_EXPORT_TOTAL_BYTES)} "
                    "limit. Download fewer files at a time.",
                    code="EXPORT_TOO_LARGE",
                    field="files",
                    max_bytes=MAX_EXPORT_TOTAL_BYTES,
                    received_bytes=total_bytes,
                )

            resolved.append((source_path, _unique_arcname(os.path.basename(filename), taken)))

    if not resolved:
        preview = ", ".join(os.path.basename(name) or name for name in missing[:5])
        raise UploadValidationError(
            f"None of the {len(missing)} requested files exist ({preview}"
            f"{', ...' if len(missing) > 5 else ''})",
            code="EXPORT_NO_MATCHING_FILES",
            field="files",
            details={"missing": [os.path.basename(n) for n in missing[:20]]},
        )

    if missing:
        logger.warning("batch_download_missing_files", missing=len(missing), requested=len(filenames))

    fd, temp_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)

    try:
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for source_path, arcname in resolved:
                zipf.write(source_path, arcname=arcname)
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        if isinstance(e, (UploadValidationError, ComfyError)):
            raise
        raise ComfyError(f"Failed to create batch download: {e!s}")

    headers = {"Content-Disposition": "attachment; filename=batch_download.zip"}
    if missing:
        headers["X-Missing-Count"] = str(len(missing))
        headers["X-Missing-Files"] = ",".join(
            os.path.basename(name) for name in missing[:20]
        )[:1000]

    return temp_path, headers


def get_safe_path(base_dir: str, requested_path: str) -> str:
    """
    Resolve and validate a path to prevent directory traversal.

    Normalizes both separator styles (a Windows client may send `..\\..\\x`),
    rejects NUL bytes and absurdly long paths, and confirms the fully resolved
    path (symlinks included) is still inside the base directory.

    Args:
        base_dir: The trusted base directory.
        requested_path: The user-provided path component.

    Returns:
        The absolute resolved path if valid.

    Raises:
        ValidationError (400) if the path is empty, malformed, or escapes the
        base directory.
    """
    # Remove leading slashes to prevent absolute path interpretation and fold
    # backslashes so Windows-style traversal cannot slip past the checks below.
    clean_path = requested_path.lstrip("/\\").replace("\\", "/")

    if not clean_path or clean_path.strip("/") == "":
        raise ValidationError("Invalid path: path cannot be empty")

    if "\0" in requested_path:
        raise ValidationError("Invalid path: null bytes are not allowed")

    if len(clean_path) > MAX_PATH_LENGTH:
        raise ValidationError(f"Invalid path: exceeds {MAX_PATH_LENGTH} characters")

    base_path = os.path.realpath(os.path.abspath(base_dir))
    full_path = os.path.realpath(os.path.join(base_path, clean_path))

    # Use commonpath so mixed separators and platform differences are handled correctly.
    try:
        common = os.path.commonpath([full_path, base_path])
    except ValueError:
        # Happens when drives differ on Windows (e.g. C:\ vs D:\)
        raise ValidationError("Access denied: Path outside allowed directory")

    if common != base_path:
        raise ValidationError("Access denied: Path outside allowed directory")

    return full_path


def encode_filename_for_header(filename: str) -> str:
    """Encode filename for Content-Disposition header using RFC 2231."""
    from urllib.parse import quote
    encoded = quote(filename)
    return f"filename*=UTF-8''{encoded}"


def _scan_local_model_directory(model_type, search, sort, limit, offset):
    """
    Sync helper to scan model directory.
    Run in thread pool to avoid blocking event loop.
    """
    try:
        base_model_dir = os.path.join(CACHE_DIR, "models")
        try:
            model_cache_dir = get_safe_path(base_model_dir, model_type)
        except ValidationError:
            return {"files": [], "total": 0}

        if not os.path.exists(model_cache_dir):
            return {"files": [], "total": 0}

        entries = os.listdir(model_cache_dir)
        valid_files = []

        for name in entries:
            if name.endswith(('.safetensors', '.ckpt', '.pt', '.pth', '.bin')):
                if search and search.lower() not in name.lower():
                    continue

                full_path = os.path.join(model_cache_dir, name)
                stat = os.stat(full_path)

                # Load metadata if exists
                metadata = {}
                meta_path = full_path.replace(os.path.splitext(name)[1], '.json')
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, 'r') as f:
                            metadata = json.load(f)
                    except Exception as e:
                        logger.warning("model_metadata_read_error", path=meta_path, error=str(e))

                valid_files.append({
                    "name": name,
                    "size": stat.st_size,
                    "modified_time": stat.st_mtime,
                    "metadata": metadata,
                    "preview": metadata.get("preview_url", "")
                })

        # Sort
        if sort == "date_desc":
            valid_files.sort(key=lambda x: x.get("modified_time", 0), reverse=True)
        elif sort == "name_asc":
            valid_files.sort(key=lambda x: x.get("name", ""))
        elif sort == "size_desc":
            valid_files.sort(key=lambda x: x.get("size", 0), reverse=True)
        elif sort == "rating_desc":
            valid_files.sort(key=lambda x: x.get("metadata", {}).get("stats", {}).get("thumbsUpCount", 0) or 0, reverse=True)
        elif sort.startswith("random"):
            import random
            seed = "stable_random_seed"
            if sort.startswith("random:"):
                seed = sort.split(":", 1)[1]
            random.Random(search or seed).shuffle(valid_files)

        total = len(valid_files)
        paginated = valid_files[offset:offset + limit]

        return {"files": paginated, "total": total}

    except Exception as e:
        # Re-raised, not softened. This used to return `{"files": [], "total": 0}`
        # at HTTP 200, which is indistinguishable from "you have no models" to
        # the caller: a driver failure, a corrupt index or a bug all rendered as
        # an empty gallery with no error anywhere. `total: 0` was also a lie —
        # the real count is unknown, not zero.
        logger.error("model_cache_read_failed", error=str(e), exc_info=True)
        raise ServiceUnavailableError(
            "Model cache is unavailable", service="model_cache"
        ) from e


def _resolve_asset_path(rel_or_filename: str, session: Session | None = None) -> str | None:
    """Resolve an image request (relative_path or filename) to an on-disk path.

    Uses the DB-backed assets index first, falling back to a direct join under
    OUTPUT_DIR so requests still work during/after the partition migration.

    Pass `session` to reuse a caller's open session — same contract as
    `_soft_delete_assets`. Without it, a batch that resolves N names checks out
    N pooled connections in sequence, each held for two SELECTs.
    """
    rel = rel_or_filename.lstrip("/\\")
    try:
        direct = get_safe_path(OUTPUT_DIR, rel)
    except ValidationError:
        return None
    if os.path.exists(direct):
        return direct
    asset = None
    from contextlib import ExitStack

    with ExitStack() as stack:
        owned = session is None
        if owned:
            session = stack.enter_context(_sync_session())
        try:
            asset = session.exec(
                select(Asset).where(Asset.relative_path == rel).where(Asset.deleted_at.is_(None))
            ).first()
            if not asset and "/" not in rel:
                asset = session.exec(
                    select(Asset).where(Asset.filename == rel).where(Asset.deleted_at.is_(None))
                ).first()
        except Exception as exc:
            # Not the same as "no such asset": a driver failure, a missing column
            # or a closed session was being reported as an empty index, and the
            # caller then fell through to the basename guess below — which
            # happens to work often enough that the real error was never seen.
            # Same reason `_query_gallery_files` logs before it raises.
            logger.warning("asset_index_lookup_failed", relative_path=rel, error=str(exc))
            asset = None
    if asset:
            cand = get_safe_path(OUTPUT_DIR, asset.relative_path)
            if os.path.exists(cand):
                return cand
            leg = get_safe_path(OUTPUT_DIR, asset.filename)
            if os.path.exists(leg):
                return leg
    leg = get_safe_path(OUTPUT_DIR, os.path.basename(rel))
    return leg if os.path.exists(leg) else None


def _query_gallery_files(
    limit: int = 20,
    offset: int = 0,
    sort: str = "date_desc",
    search: str | None = _bounded_search(),
    workspace: str | None = None,
    character_id: str | None = None,
    story_id: str | None = None,
) -> dict:
    """DB-backed gallery listing (replaces the in-memory GalleryIndexer).

    Synchronous helper — callers MUST wrap in asyncio.to_thread. Ordering uses
    `generated_at` (true image time) falling back to `created_at`. Sort options:
    date_desc (default), date_asc, name_asc, name_desc.
    """
    from sqlalchemy import String, func
    from sqlalchemy import func as sqlfunc

    from services.asset_reconciler import _asset_as_file_data

    order_col = func.coalesce(Asset.generated_at, Asset.created_at)
    with _sync_session() as session:
        q = select(Asset).where(Asset.deleted_at.is_(None))
        if workspace:
            q = q.where(Asset.workspace == workspace)
        if character_id:
            q = q.where(Asset.character_id == character_id)
        if story_id:
            q = q.where(Asset.story_id == story_id)
        if search:
            like = like_contains(search)
            # `String`, NOT the builtin `str`: `Column.cast()` takes a TypeEngine
            # and the builtin made it raise `TypeError: Object '' associated with
            # '.type' attribute is not a TypeEngine class or object` — which the
            # caller's `except` turned into a 503 "File listing is unavailable".
            # So every gallery search, for every term, was a hard failure on the
            # live site; the sibling call sites below already used `String`.
            q = q.where(
                (Asset.filename.ilike(like, escape=LIKE_ESCAPE_CHAR))
                | (Asset.metadata_.cast(String).ilike(like, escape=LIKE_ESCAPE_CHAR))
            )

        if sort in ("name_asc", "name_desc"):
            # Ordered and paged in SQL. This used to be
            # `exec(q.order_by(...)).all()` then `sorted(...)` in Python then a
            # slice, so the *whole* `assets` table — 16,907 rows including the
            # ~70 MB `metadata_` jsonb column — was materialised to answer a
            # request whose response is 27 kB. Measured on the live stack:
            # 5.5–9.8 s wall, and the backend container's RSS going 150 MiB →
            # 555 MiB per request. Two concurrent requests would exhaust a 2 GiB
            # container.
            #
            # `filename` alone is not a stable sort (a directory of renamed
            # files can contain duplicates), so `id` breaks the tie exactly as
            # the date branch does.
            name_order = Asset.filename.asc() if sort == "name_asc" else Asset.filename.desc()
            total = session.exec(select(sqlfunc.count()).select_from(q.subquery())).one()
            page = session.exec(
                q.order_by(name_order, Asset.id.asc() if sort == "name_asc" else Asset.id.desc())
                .offset(offset)
                .limit(limit)
            ).all()
            return {"files": [_asset_as_file_data(a, OUTPUT_DIR) for a in page], "total": total}

        order = order_col.asc() if sort == "date_asc" else order_col.desc()
        id_order = Asset.id.asc() if sort == "date_asc" else Asset.id.desc()
        # Get total count efficiently without loading all rows
        total = session.exec(select(sqlfunc.count()).select_from(q.subquery())).one()
        page = session.exec(q.order_by(order, id_order).offset(offset).limit(limit)).all()
        return {"files": [_asset_as_file_data(a, OUTPUT_DIR) for a in page], "total": total}


def _soft_delete_assets(relative_or_filename: str, session: Session | None = None) -> int:
    """Mark matching asset rows deleted after their file is removed from disk.

    Pass `session` to reuse a caller's open session. Opening a second one instead
    means committing while the first is still uncommitted, which is how
    `move_asset` ended up with two sessions for one request.
    """
    from contextlib import ExitStack

    from datetime import datetime, timezone

    rel = relative_or_filename.lstrip("/\\")
    now = datetime.now(timezone.utc)
    with ExitStack() as stack:
        if session is None:
            session = stack.enter_context(_sync_session())
        q = select(Asset).where(Asset.deleted_at.is_(None)).where(
            (Asset.relative_path == rel) | (Asset.relative_path == "/" + rel)
        )
        rows = session.exec(q).all()
        if not rows and "/" not in rel:
            # Fallback for basenames sent by the UI.
            #
            # Both arms anchor on a path boundary. A third arm,
            # `relative_path.endswith(rel)`, also existed and matched every row
            # whose path merely *ended with* the same characters, so a request
            # for `abc.png` soft-deleted `notabc.png` and `xabc.png` as well.
            # It is unreachable as a rescue for the exact-path form, because
            # `relative_path` is always date-partitioned, so every basename
            # keyed call took this branch and therefore the over-broad match.
            #
            # Reachable without any mistake from the user: the thumbnail route's
            # "self-heal a missing index row" fall-through calls this with a bare
            # filename, and the gallery's batch delete does too.
            rows = session.exec(
                select(Asset).where(Asset.deleted_at.is_(None)).where(
                    (Asset.filename == rel) | (Asset.relative_path.endswith("/" + rel))
                )
            ).all()
        for a in rows:
            a.deleted_at = now
            session.add(a)
        session.commit()
        return len(rows)


# ── asset keyset cursor and date seek ───────────────────────────────────────
#
# The listing sorts on `(ASSET_GALLERY_TIMESTAMP, id)`. A cursor therefore has
# to name a *row*, not an instant: `WHERE ts < cursor_ts` is not a total order
# over `(ts, id)`, so every asset that shares its timestamp with the last row of
# the previous page falls through the boundary and is silently dropped from the
# result set. Ties are the normal case, not an edge case — one multi-image job
# writes several assets with the identical `generated_at`, and the scrubber
# stresses this hardest because jumping far back in time is exactly the
# navigation that walks the most pages.
#
# Cursor format is `<iso>|<id>`, one `|`, the timestamp always first.
_ASSET_CURSOR_SEP = "|"


def _encode_asset_cursor(moment: datetime, asset_id: str) -> str:
    return f"{moment.isoformat()}{_ASSET_CURSOR_SEP}{asset_id}"


def _decode_asset_cursor(raw: str | None) -> tuple[datetime | None, str | None]:
    """A cursor as `(timestamp, id)`; `(None, None)` if unusable.

    A bare ISO timestamp — every cursor this endpoint issued before the
    composite — decodes with `id=None`, which the caller turns into the
    inclusive-bound fallback documented at its predicate.
    """
    text = (raw or "").strip()
    if not text:
        return None, None
    stamp, sep, asset_id = text.rpartition(_ASSET_CURSOR_SEP)
    if not sep:
        stamp, asset_id = text, ""
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")), asset_id or None
    except ValueError:
        logger.debug("invalid_cursor", cursor=text[:64])
        return None, None


def _parse_seek_bound(value: str | None, *, end_of_day: bool) -> datetime | None:
    """A `?on_or_before=` / `?since=` value as an aware instant, or None.

    A bare `YYYY-MM-DD` is a whole UTC day, not its midnight. That is the unit
    the scrubber navigates by and the only date form a human types, so
    `on_or_before=2026-03-02` has to mean "the last instant of 2026-03-02";
    anchoring it to midnight would return a page holding 2026-03-01's tail,
    which is the opposite of the request.
    """
    text = (value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            midnight = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        if end_of_day:
            return midnight + timedelta(days=1) - timedelta(microseconds=1)
        return midnight
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _validate_seek(sort: str, on_or_before: str | None, since: str | None) -> None:
    """Refuse a seek that cannot work, rather than silently ignoring it.

    Both bounds are just predicates, so a mismatched pair is not an error at the
    SQL level — it is a call that returns the newest (or oldest) page of the
    library and looks like it worked. A jump that lands on the wrong end of a
    16k gallery is worse than a 400, and both parameters are new, so no existing
    caller can be relying on the loose behaviour.
    """
    if not (on_or_before or since):
        return
    if sort.startswith("random"):
        raise ValidationError(
            "Date seeking is not available with a random sort; the order carries no timeline."
        )
    if on_or_before and since:
        return
    if on_or_before and sort == "date_asc":
        raise ValidationError(
            "`on_or_before` seeks backwards and needs a descending sort. "
            "With `sort=date_asc` use `since`."
        )
    if since and sort != "date_asc":
        raise ValidationError(
            "`since` seeks forwards and needs `sort=date_asc`. "
            "With a descending sort use `on_or_before`."
        )


def _list_assets_sync(
    limit: int = 24,
    cursor: str | None = None,
    workspace: str | None = None,
    character_id: str | None = None,
    story_id: str | None = None,
    search: str | None = _bounded_search(),
    sort: str = "date_desc",
    on_or_before: str | None = None,
    since: str | None = None,
):
    """Keyset-paginated asset listing backed by the DB (replaces in-memory scan).

    Ordering uses `ASSET_GALLERY_TIMESTAMP` — `generated_at` (true image creation
    time) falling back to `created_at`, so migrated legacy rows keep their
    timeline position — with `id` as the tiebreak, and the cursor encodes both
    halves. The same expression drives `GET /api/v2/assets/dates`, so a day's
    tick and the day's contents cannot disagree.

    `on_or_before` / `since` seek: they bound the start of the first page
    directly, so a date deep in a 16k library is one request rather than one
    request per intervening page. Items carry both the legacy gallery shape
    (`name`/`preview`/`thumbnail`/metadata) and the new id-based fields.

    The cap is re-applied here as well as at the route. The route's
    `Query(le=...)` guards the wire; this guards the internal callers, and it
    clamps rather than rejects so an internal caller asking for more than a page
    gets a page instead of a traceback.
    """
    from sqlalchemy import String, and_, func, or_

    from services.asset_reconciler import _asset_as_file_data

    limit = max(1, min(limit, MAX_ASSETS_PAGE_SIZE))
    order_col = ASSET_GALLERY_TIMESTAMP
    seek_to = _parse_seek_bound(on_or_before, end_of_day=True)
    seek_from = _parse_seek_bound(since, end_of_day=False)
    with _sync_session() as session:
        q = select(Asset).where(Asset.deleted_at.is_(None))
        if workspace:
            q = q.where(Asset.workspace == workspace)
        if character_id:
            q = q.where(Asset.character_id == character_id)
        if story_id:
            q = q.where(Asset.story_id == story_id)
        if search:
            like = like_contains(search)
            q = q.where(
                (Asset.filename.ilike(like, escape=LIKE_ESCAPE_CHAR))
                | (Asset.metadata_.cast(String).ilike(like, escape=LIKE_ESCAPE_CHAR))
            )
        if sort.startswith("random"):
            from sqlalchemy import cast
            seed = "stable_random_seed"
            if sort.startswith("random:"):
                seed = sort.split(":", 1)[1]
            hash_col = func.md5(func.concat(cast(Asset.id, String), seed))
            if cursor:
                q = q.where(hash_col > cursor)
            q = q.order_by(hash_col.asc()).limit(limit + 1)
        else:
            # A date seek positions the *first* page. It composes with a cursor:
            # the bound still applies, the cursor still resumes within it.
            ascending = sort == "date_asc"
            if cursor:
                cur_dt, cur_id = _decode_asset_cursor(cursor)
                if cur_dt is not None:
                    if cur_id is None:
                        # Legacy bare-timestamp cursor. The old predicate was a
                        # strict `ts < cur_ts`, which dropped every row sharing
                        # `cur_ts`; the inclusive form re-serves them instead,
                        # so an in-flight infinite scroll sees a one-page
                        # duplicate rather than silently losing images. It heals
                        # itself: the cursor this response returns is composite,
                        # so page N+1 onwards is exact again.
                        q = q.where(order_col > cur_dt if ascending else order_col <= cur_dt)
                    else:
                        # The total-order predicate over `(ts, id)`.
                        q = q.where(
                            or_(
                                order_col > cur_dt,
                                and_(order_col == cur_dt, Asset.id > cur_id),
                            )
                            if ascending
                            else or_(
                                order_col < cur_dt,
                                and_(order_col == cur_dt, Asset.id < cur_id),
                            )
                        )
            if seek_to is not None:
                q = q.where(order_col <= seek_to)
            if seek_from is not None:
                q = q.where(order_col >= seek_from)
            q = q.order_by(
                order_col.asc() if ascending else order_col.desc(),
                Asset.id.asc() if ascending else Asset.id.desc(),
            ).limit(limit + 1)
        rows = session.exec(q).all()
        has_more = len(rows) > limit
        page = rows[:limit]
        items = []
        for a in page:
            item = _asset_as_file_data(a, OUTPUT_DIR)
            item.update({
                "id": a.id,
                "filename": a.filename,
                "relative_path": a.relative_path,
                "thumbnail": f"/api/thumbnail/medium/{a.relative_path}",
                "file_url": f"/api/v2/assets/{a.id}/file",
                "thumb_url": f"/api/v2/assets/{a.id}/thumb" if a.thumbnail_relative_path else f"/api/v2/assets/{a.id}/file",
                "workspace": a.workspace,
                "character_id": a.character_id,
                "story_id": a.story_id,
                "width": a.width,
                "height": a.height,
                "blurhash": a.blurhash,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "metadata": a.metadata_ or {},
            })
            items.append(item)
        if sort.startswith("random"):
            import hashlib
            if page:
                seed = "stable_random_seed"
                if sort.startswith("random:"):
                    seed = sort.split(":", 1)[1]
                last_id_seed = (str(page[-1].id) + seed).encode('utf-8')
                next_cursor = hashlib.md5(last_id_seed).hexdigest() if has_more else None
            else:
                next_cursor = None
        else:
            order_ts = (page[-1].generated_at or page[-1].created_at) if page else None
            next_cursor = (
                _encode_asset_cursor(order_ts, page[-1].id)
                if (has_more and order_ts)
                else None
            )
        return {"items": items, "has_more": has_more, "next_cursor": next_cursor}


@router.get("/api/v2/assets")
async def list_assets(
    limit: int = Query(24, ge=1, le=MAX_ASSETS_PAGE_SIZE),
    cursor: str | None = None,
    workspace: str | None = None,
    character_id: str | None = None,
    story_id: str | None = None,
    search: str | None = _bounded_search(),
    sort: str = "date_desc",
    on_or_before: str | None = None,
    since: str | None = None,
):
    """Keyset-paginated asset listing backed by the DB.

    The query runs on a worker thread: it opens a synchronous Session and
    issues a full keyset page, and doing that inline on the event loop blocked
    every other request for the duration.

    `limit` is capped. It was a bare `int = 24`, so `?limit=1000000` scanned the
    whole asset table and serialised every row's `metadata_` jsonb blob in one
    response — the sibling list routes in this app (`jobs.py` 200,
    `sessions.py` 100, `tags.py` 200) all cap, and this one silently did not.

    `on_or_before` (descending) and `since` (`sort=date_asc`) seek the first page
    to an instant instead of the newest row, so the response already contains
    the day that was asked for. They accept a full ISO-8601 instant or a bare
    `YYYY-MM-DD`, which means the whole UTC day. Each is rejected with a 400
    when it cannot work with the requested sort — see `_validate_seek`.
    """
    _validate_seek(sort, on_or_before, since)
    return await asyncio.to_thread(
        _list_assets_sync,
        limit=limit,
        cursor=cursor,
        workspace=workspace,
        character_id=character_id,
        story_id=story_id,
        search=search,
        sort=sort,
        on_or_before=on_or_before,
        since=since,
    )


@router.get("/api/v2/assets/dates")
async def asset_date_histogram(
    workspace: str | None = None,
    character_id: str | None = None,
    story_id: str | None = None,
    search: str | None = _bounded_search(),
):
    """Per-day image counts for the gallery timeline scrubber.

    Declared here rather than under `/api/statistics` because that endpoint's
    `images_by_date` buckets on `metadata.job.completed_at` and applies no
    scope at all: neither agrees with the gallery's own
    `coalesce(generated_at, created_at)` timeline, and neither describes a
    filtered gallery. The filters accepted here are exactly the ones
    `GET /api/v2/assets` accepts, so the rail always matches the list.
    """
    return await asyncio.to_thread(
        get_asset_date_histogram,
        workspace=workspace,
        character_id=character_id,
        story_id=story_id,
        search=search,
    )


def _serve_asset_file_sync(asset_id: str):
    with _sync_session() as session:
        asset = session.get(Asset, asset_id)
        if not asset or asset.deleted_at is not None:
            raise NotFoundError("Asset", asset_id)
        path = get_safe_path(OUTPUT_DIR, asset.relative_path)
        if not os.path.exists(path):
            path = get_safe_path(OUTPUT_DIR, asset.filename)
        if not os.path.exists(path):
            _soft_delete_assets(asset.relative_path)
            raise NotFoundError("Asset file", asset.relative_path)
        return FileResponse(path)


@router.get("/api/v2/assets/{asset_id}/file")
async def serve_asset_file(asset_id: str):
    # Off the event loop: the body opens a synchronous Session and stats the
    # filesystem. See _list_assets_sync for the same reasoning.
    return await asyncio.to_thread(_serve_asset_file_sync, asset_id)


def _serve_asset_thumb_sync(asset_id: str):
    with _sync_session() as session:
        asset = session.get(Asset, asset_id)
        if not asset or asset.deleted_at is not None or not asset.thumbnail_relative_path:
            raise NotFoundError("Thumbnail", asset_id)
        path = get_safe_path(OUTPUT_DIR, asset.thumbnail_relative_path)
        if not os.path.exists(path):
            orig_path = get_safe_path(OUTPUT_DIR, asset.relative_path)
            if not os.path.exists(orig_path):
                _soft_delete_assets(asset.relative_path)
            raise NotFoundError("Thumbnail file", asset.thumbnail_relative_path)
        return FileResponse(path)


@router.get("/api/v2/assets/{asset_id}/thumb")
async def serve_asset_thumb(asset_id: str):
    return await asyncio.to_thread(_serve_asset_thumb_sync, asset_id)


class MoveAssetRequest(BaseModel):
    workspace: str | None = None
    character_id: str | None = None
    story_id: str | None = None
    copy_file: bool = Field(
        default=False,
        validation_alias=AliasChoices("copy_file", "copy"),
    )

    # `copy` was what the dashboard's Copy Asset button sent, and pydantic
    # dropped it silently, so `copy_file` fell back to False and the request
    # took the `os.rename` branch: the "copy" moved the original and the UI
    # toasted "Asset copied". The frontend is fixed, but a stale cached bundle
    # would still send `copy`, and the failure is asymmetric — asking for a copy
    # and losing the original. Accepting the old spelling costs one line and
    # makes that impossible.
    model_config = ConfigDict(populate_by_name=True)


def _move_asset_sync(asset_id: str, body: MoveAssetRequest) -> dict:
    """Reorganise an asset on disk and in the index.

    Runs in a worker thread, behind a thin async route. It was previously an
    `async def` with its whole body inline, so `session.get`, `os.makedirs`,
    `open` and `session.commit` all ran on the event loop — and the copy branch
    did `dst.write(src.read())`, buffering an entire asset into a `bytes` object
    in the event-loop process. It also opened a *second* session through
    `_soft_delete_assets` while the request's own session was still open and
    uncommitted.
    """
    with _sync_session() as session:
        asset = session.get(Asset, asset_id)
        if not asset or asset.deleted_at is not None:
            raise NotFoundError("Asset", asset_id)

        if not any([body.workspace, body.character_id, body.story_id]):
            raise ValidationError("Provide at least one of workspace, character_id, or story_id")

        source_path = get_safe_path(OUTPUT_DIR, asset.relative_path)
        if not os.path.exists(source_path):
            # Same session, so the row is marked deleted atomically with the 404
            # rather than through a second uncommitted session.
            _soft_delete_assets(asset.relative_path, session)
            raise NotFoundError("Asset file", asset.relative_path)

        target_workspace = body.workspace or asset.workspace
        target_character_id = body.character_id if body.character_id is not None else asset.character_id
        target_story_id = body.story_id if body.story_id is not None else asset.story_id

        target_rel = os.path.join(
            target_workspace,
            *([target_character_id] if target_character_id else []),
            *([target_story_id] if target_story_id else []),
            asset.filename,
        )
        target_path = get_safe_path(OUTPUT_DIR, target_rel)

        if body.copy_file:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            # Streamed in chunks. `src.read()` with no argument materialises the
            # whole asset — a generated image can be tens of megabytes.
            with open(source_path, "rb") as src, open(target_path, "wb") as dst:
                while chunk := src.read(_COPY_CHUNK_BYTES):
                    dst.write(chunk)
            # Routed through `upsert_asset` so the copied row gets the same
            # statistics rollup columns as any other write. Constructing `Asset`
            # directly here used to silently drop them.
            upsert_asset(
                session,
                relative_path=target_rel,
                filename=asset.filename,
                user_id=asset.user_id,
                workspace=target_workspace,
                character_id=target_character_id,
                story_id=target_story_id,
                job_id=asset.job_id,
                width=asset.width,
                height=asset.height,
                blurhash=asset.blurhash,
                thumbnail_relative_path=asset.thumbnail_relative_path,
                generated_at=asset.generated_at,
                metadata=asset.metadata_,
            )
            copied = session.exec(
                select(Asset).where(Asset.relative_path == target_rel)
            ).one()
            return {"id": copied.id, "relative_path": copied.relative_path}

        if target_path != source_path:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            os.rename(source_path, target_path)
            asset.relative_path = target_rel
            asset.workspace = target_workspace
            asset.character_id = target_character_id
            asset.story_id = target_story_id
            session.add(asset)
            session.commit()
            session.refresh(asset)

        return {"id": asset.id, "relative_path": asset.relative_path}


@router.post("/api/v2/assets/{asset_id}/move")
async def move_asset(asset_id: str, body: MoveAssetRequest):
    return await asyncio.to_thread(_move_asset_sync, asset_id, body)


@router.get("/api/v2/gallery")
async def get_v2_gallery(
    # These need their own bounds, not `list_files_endpoint`'s. Calling a route
    # function as a plain Python call means FastAPI never resolves the callee's
    # `Query(..., ge=1, le=MAX_BATCH_ITEMS)` default, so `?limit=100000000`
    # reached `_query_gallery_files` and materialised the whole assets table —
    # including the ~70 MB `metadata_` jsonb — in a single response, and a
    # negative offset made Postgres raise, reported as a 503.
    limit: int = Query(20, ge=1, le=MAX_BATCH_ITEMS),
    offset: int = Query(0, ge=0),
    sort: str = "date_desc", 
    search: str | None = _bounded_search(),
    workspace: str | None = None,
    character_id: str | None = None,
    story_id: str | None = None,
    model_service = Depends(get_model_service_v2)
):
    return await list_files_endpoint(
        directory="output",
        limit=limit,
        offset=offset,
        sort=sort,
        search=search,
        workspace=workspace,
        character_id=character_id,
        story_id=story_id,
        model_service=model_service
    )

@router.get("/api/files")
async def list_files_endpoint(
    directory: str = "output",
    limit: int = Query(20, ge=1, le=MAX_BATCH_ITEMS),
    offset: int = Query(0, ge=0),
    sort: str = "date_desc", 
    search: str | None = _bounded_search(),
    base_model: str | None = None,
    model_type: str | None = None,
    show_nsfw: bool = True,
    # A comma-separated list of tags, each an ILIKE term against the same jsonb
    # column as `search`. Unbounded both per item and overall, so a long list of
    # long tags multiplies the cost of the search term without a length cap
    # anywhere. Bounded with `max_length` on the whole parameter, which is the
    # conservative bound: it admits up to 200 chars of tag list.
    tags: str | None = _bounded_search("Comma-separated tag filters"),
    workspace: str | None = None,
    character_id: str | None = None,
    story_id: str | None = None,
    model_service = Depends(get_model_service_v2)
):
    """List files in a directory with pagination and search."""
    
    # Handle Local Output Files
    if directory == "output" or directory.startswith("output/"):
        try:
            return await asyncio.to_thread(
                _query_gallery_files,
                limit=limit,
                offset=offset,
                sort=sort,
                search=search,
                workspace=workspace,
                character_id=character_id,
                story_id=story_id,
            )
        except Exception as e:
            # Same reasoning as `model_cache_read_failed` above: a 200 with an
            # empty list is the one response shape that cannot be told apart
            # from "there is nothing here", which is exactly when the user most
            # needs to know the query itself failed.
            logger.error("local_file_list_failed", error=str(e), exc_info=True)
            raise ServiceUnavailableError(
                "File listing is unavailable", service="file_listing"
            ) from e

    # Handle Models directories - query from SQLite model service
    if directory.startswith("models/"):
        model_dir_type = directory.replace("models/", "")

        # The database does the filtering, the sorting and the paging.
        #
        # All three used to happen here, in Python, *after* the whole directory
        # had been hydrated: this branch built a full `file_data` row —
        # description, trained words, every version, every image — for all 484
        # LoRAs and then discarded all but `limit` of them. The query could not
        # see the page size at all. Measured per request: `limit=2` 543 ms,
        # `limit=20` 537 ms, `limit=500` 1,198 ms for 3.4 MB, and a search for a
        # string that does not exist 867 ms to return `{"files": []}`.
        #
        # So they are pushed into `ModelServiceV2.list_models_page`, and this
        # function only projects the rows it is handed. The call is hoisted into
        # `asyncio.to_thread` for the other half of the same defect: it is a
        # synchronous query chain inside an `async def` route, so inline it runs
        # on the event loop and the whole container waits for it.
        want_tags = [t.strip() for t in tags.split(",")] if tags else None
        want_base_model = None if base_model in (None, "", "all") else base_model
        want_model_type = None if model_type in (None, "", "all") else model_type

        # `random[:seed]` shuffles the whole directory before it can take a page,
        # so it is not a SQL `ORDER BY`. It gets the matching ids — cheap, no
        # hydration — shuffled by the same algorithm and the same seed over the
        # same id-ordered input the old code shuffled, and only the resulting page
        # is hydrated.
        random_seed = None
        if sort and sort.startswith("random"):
            random_seed = sort.split(":", 1)[1] if ":" in sort else (search or "stable_random_seed")

        def _load_models_page() -> tuple[list[dict], int]:
            page_ids = None
            if sort and sort.startswith("random"):
                matching = model_service.repo.get_model_ids_by_directory(
                    model_dir_type,
                    search=search,
                    tags=want_tags,
                    model_type=want_model_type,
                    base_model=want_base_model,
                    show_nsfw=show_nsfw,
                )
                random.Random(random_seed).shuffle(matching)
                page_ids = matching[offset : offset + limit]
            return model_service.list_models_page(
                model_dir_type,
                search=search,
                tags=want_tags,
                model_type=want_model_type,
                base_model=want_base_model,
                show_nsfw=show_nsfw,
                sort=None if sort in (None, "random", random_seed) else sort,
                limit=limit,
                offset=offset,
                ids=page_ids,
            )

        try:
            models, total = await asyncio.to_thread(_load_models_page)

            # Format V2 data for frontend compatibility
            valid_files = []
            for model in models:
                if not isinstance(model, dict):
                    continue

                # Get versions and find default
                versions = model.get("versions", [])
                default_version = next(
                    (v for v in versions if v.get("is_default")),
                    versions[0] if versions else None
                )

                # Extract file info from default version
                file_info = (default_version.get("file") or {}) if default_version else {}
                filename = file_info.get("filename", model.get("name", "unknown"))
                size_kb = file_info.get("size_kb", 0)

                # Skip partial/incomplete download artifacts — they must never be
                # offered as selectable models (preflight would always fail).
                if any(
                    filename.lower().endswith(suffix)
                    for suffix in (".downloading", ".part", ".crdownload", ".tmp", ".temp")
                ):
                    continue

                # Get preview image URL
                preview_image = model.get("preview_image") or {}
                civitai_id = model.get("civitai_model_id")
                preview_url = (
                    preview_image.get("url") if preview_image else None
                ) or (
                    f"/api/v2/models/preview/{civitai_id}" if civitai_id else ""
                )

                # Provider statuses
                provider_statuses = model.get("provider_statuses") or {}

                # `trained_words`, `version_description` and `images` are NOT
                # repeated here. They were copies of the default version's own
                # fields, which are still in the payload under `versions`, and
                # every reader of the top-level copy read it as a fallback that
                # cannot fire: `ModelDetailsModal.jsx:252-254` uses
                # `selectedVersion?.x || <the copy>`, and `selectedVersion` is
                # that same version whenever it exists — and when `versions` is
                # empty there is no image, trained word or version description to
                # fall back to. `ModelSelector.jsx` reads `version.trained_words`
                # off the version object, not off this row.
                #
                # Model-level `description` stays: it is a different field from
                # the version's, and `ModelDetailsModal.jsx:239` renders it.
                file_data = {
                    # Actual filename for generator
                    "name": filename,
                    # Display name for UI
                    "display_name": model.get("name", filename),
                    # Size in bytes and KB
                    "size": size_kb * 1024 if size_kb else 0,
                    "size_kb": size_kb,
                    # Timestamps
                    "modified_time": model.get("updated_at", 0),
                    # IDs
                    "model_id": model.get("id"),
                    "civitai_id": civitai_id,
                    # Version info
                    "base_model": default_version.get("base_model", "") if default_version else "",
                    "version_count": len(versions),
                    "default_version": default_version.get("name", "") if default_version else "",
                    # Full versions list for version selector
                    "versions": versions,
                    # Model type
                    "type": model.get("type", ""),
                    "nsfw": model.get("nsfw", False),
                    # Preview image
                    "preview": preview_url,
                    # Provider sync status
                    "provider_statuses": provider_statuses,
                    # Stats
                    "stats": model.get("stats", {}),
                    # Tags
                    "tags": model.get("tags", []),
                    # Model description
                    "description": model.get("description", ""),
                    # Creator
                    "creator": model.get("creator", {}),
                }

                valid_files.append(file_data)

            return {"files": valid_files, "total": total}

            
        except Exception as e:
            # A DB failure here used to fall through to a filesystem scan and
            # answer 200 with a *different, smaller* result set — the model list
            # silently changed shape depending on whether Postgres was reachable.
            # The `output` branch above this one already rejected exactly this
            # ("a 200 with an empty list is the one response shape that cannot be
            # told apart from 'there is nothing here'"); the models branch kept
            # the lying fallback. A local scan is still attempted, but only as a
            # *declared* degradation: the response says it came from the
            # filesystem, so the UI can say so too.
            logger.warning("model_service_query_failed", error=str(e), exc_info=True)
            try:
                scanned = await asyncio.to_thread(
                    _scan_local_model_directory,
                    model_dir_type,
                    search,
                    sort,
                    limit,
                    offset,
                )
            except Exception as scan_error:
                logger.error("model_directory_scan_failed", error=str(scan_error), exc_info=True)
                raise ServiceUnavailableError(
                    "Model listing is unavailable", service="model_listing"
                ) from scan_error
            scanned["source"] = "filesystem_fallback"
            scanned["degraded"] = True
            return scanned
    
    return {"files": [], "total": 0}


@router.get("/api/view/{path:path}")
async def view_file_endpoint(path: str):
    """Serve files from local output or cached previews."""
    # Everything below stats the filesystem, globs the output tree and — via
    # `_resolve_asset_path` — opens a synchronous DB session. Run off the loop.
    return await asyncio.to_thread(_view_file_sync, path)


def _view_file_sync(path: str) -> FileResponse:
    """Worker-thread body for `view_file_endpoint`."""
    import glob

    # Try local output first (supports both legacy flat and new partitioned paths)
    if path.startswith("output/"):
        filename = path.replace("output/", "").lstrip("/\\")

        # Security check: ensure path is within OUTPUT_DIR
        local_path = get_safe_path(OUTPUT_DIR, filename)
        if os.path.exists(local_path) and os.path.isfile(local_path):
            return FileResponse(
                local_path,
                headers={
                    "Content-Disposition": f"attachment; {encode_filename_for_header(os.path.basename(local_path))}"
                }
            )

        # Resolve via the DB-backed asset index (partitioned layout aware)
        indexed_path = _resolve_asset_path(filename)
        if indexed_path and os.path.exists(indexed_path):
            return FileResponse(
                indexed_path,
                headers={
                    "Content-Disposition": f"attachment; {encode_filename_for_header(os.path.basename(indexed_path))}"
                }
            )
        
        # Search in date-based subdirectories only for explicit relative paths.
        if "/" in filename:
            pattern = os.path.join(OUTPUT_DIR, "**", filename)
            matches = glob.glob(pattern, recursive=True)
            matches = [m for m in matches if "/thumb/" not in m]

            if matches:
                return FileResponse(
                    matches[0],
                    headers={
                        "Content-Disposition": f"attachment; {encode_filename_for_header(os.path.basename(matches[0]))}"
                    }
                )
    
    # Try preview cache
    try:
        preview_path = get_safe_path(os.path.join(CACHE_DIR, "previews"), path)
        if os.path.exists(preview_path) and os.path.isfile(preview_path):
            filename = os.path.basename(preview_path)
            return FileResponse(
                preview_path,
                headers={
                    "Content-Disposition": f"attachment; {encode_filename_for_header(filename)}"
                }
            )
    except ValidationError as e:
        logger.warning("invalid_filename_path", error=str(e))
    
    # Try input directory for Img2Img/Inpaint source images
    if path.startswith("input/"):
        filename = path.replace("input/", "").lstrip("/\\")

        # Security check: ensure path is within INPUT_DIR
        local_path = get_safe_path(INPUT_DIR, filename)
        
        if os.path.exists(local_path) and os.path.isfile(local_path):
            return FileResponse(
                local_path,
                headers={
                    "Content-Disposition": f"inline; {encode_filename_for_header(os.path.basename(local_path))}"
                }
            )
    
    raise NotFoundError("Resource", "File not found")


@router.get("/api/thumbnail/{size}/{filename:path}")
async def serve_thumbnail(size: str, filename: str):
    """
    Serve pre-generated thumbnails for faster gallery loading.

    Runs entirely on a worker thread: the whole body opens a synchronous
    Session, issues SELECTs, and does recursive `glob` walks of the thumbnail
    tree. This is the URL the entire UI uses for images
    (`frontend_v2/src/utils/assetUrl.js` -> `/api/thumbnail/medium/{path}`), so a
    dashboard with 50 visible thumbnails is 50 concurrent pool checkouts; done
    inline on the event loop each one blocked every other request, WebSocket
    frame and job dispatch. Same pattern as `_list_assets_sync` /
    `_serve_asset_thumb_sync`.

    Args:
        size: Thumbnail size - 'medium' (512px)
        filename: Original image filename

    Returns:
        Thumbnail image if exists, otherwise falls back to full image
    """
    return await asyncio.to_thread(_serve_thumbnail_sync, size, filename)


def _serve_thumbnail_sync(size: str, filename: str):
    """Worker-thread body for `serve_thumbnail`.

    Opens its own synchronous Session (see `_sync_session`) for the asset-index
    lookups and `_soft_delete_assets`, so the pool connection is held only for
    the duration of this one thumbnail request rather than for the whole
    gallery fan-out.
    """
    import glob
    import hashlib

    if size not in ("medium",):
        raise ValidationError("Size must be 'medium'")

    # Strip leading slashes to prevent absolute path injection via os.path.join
    filename = filename.lstrip("/\\")

    # Security check: ensure filename path is safe
    get_safe_path(OUTPUT_DIR, filename)
    
    # Extract just the filename for searching, ignoring path components
    # This ensures we find the file regardless of deep directory structure inputs
    base_name = os.path.basename(filename)
    name_only, ext = os.path.splitext(base_name)
    
    # Thumbnail directory (output/thumb)
    thumb_dir = os.path.join(OUTPUT_DIR, "thumb")

    # Fast path: the DB assets index knows the exact thumbnail location
    # (partitioned layout: {uid}/{ws}/thumb/YYYY/MM/DD/name.webp).
    with _sync_session() as session:
        rel = filename
        asset = session.exec(
            select(Asset).where(Asset.relative_path == rel).where(Asset.deleted_at.is_(None))
        ).first()
        if not asset and "/" not in rel:
            asset = session.exec(
                select(Asset).where(Asset.filename == rel).where(Asset.deleted_at.is_(None))
            ).first()
        if asset and asset.thumbnail_relative_path:
            indexed_thumb = get_safe_path(OUTPUT_DIR, asset.thumbnail_relative_path)
            if os.path.exists(indexed_thumb):
                stat = os.stat(indexed_thumb)
                etag = hashlib.md5(f"{indexed_thumb}:{stat.st_mtime}".encode()).hexdigest()[:16]
                return FileResponse(
                    indexed_thumb,
                    media_type="image/webp",
                    headers={
                        "Cache-Control": "public, max-age=31536000, immutable",
                        "ETag": f'"{etag}"',
                        "Content-Disposition": f"inline; {encode_filename_for_header(os.path.basename(indexed_thumb))}"
                    }
                )

    # Optimization: resolve original image via assets index, then infer the
    # thumbnail path from the mirrored structure (legacy flat thumb layout).
    original_path = _resolve_asset_path(filename)
    if not original_path:
        original_path = _resolve_asset_path(base_name)

    if original_path:
        # Check if we have a thumbnail in the mirrored structure
        # original: output/2025/12/07/image.png
        # thumb:    output/thumb/2025/12/07/image.webp

        try:
            rel_path = os.path.relpath(os.path.dirname(original_path), OUTPUT_DIR)
            # Prevent path traversal in relative path
            if ".." in rel_path:
                rel_path = ""

            inferred_thumb_path = os.path.join(thumb_dir, rel_path, f"{name_only}.webp")

            if os.path.exists(inferred_thumb_path):
                stat = os.stat(inferred_thumb_path)
                etag_source = f"{inferred_thumb_path}:{stat.st_mtime}"
                etag = hashlib.md5(etag_source.encode()).hexdigest()[:16]

                return FileResponse(
                    inferred_thumb_path,
                    media_type="image/webp",
                    headers={
                        "Cache-Control": "public, max-age=31536000, immutable",
                        "ETag": f'"{etag}"',
                        "Content-Disposition": f"inline; {encode_filename_for_header(os.path.basename(inferred_thumb_path))}"
                    }
                )
        except Exception as e:
            # Fallback to standard search if path manipulation fails
            logger.warning("thumbnail_path_inference_failed", error=str(e))

    # Search priority:
    # 1. New WebP in thumb directory with date hierarchy (output/thumb/YYYY/MM/DD/name.webp)
    # 2. Legacy PNG in flat thumb directory (output/thumb/name.medium.png)
    # 3. Legacy thumbnail alongside original (output/name.medium.png)
    # 4. Fall back to full image
    
    # Try new WebP format in date-based hierarchy
    # Search recursively for the filename in the thumb directory
    # Note: If optimization above worked, we wouldn't be here.
    if "/" in filename:
        webp_pattern = os.path.join(thumb_dir, "**", f"{name_only}.webp")
        webp_matches = glob.glob(webp_pattern, recursive=True)
        
        if webp_matches:
            thumbnail_path = webp_matches[0]
            stat = os.stat(thumbnail_path)
            etag_source = f"{thumbnail_path}:{stat.st_mtime}"
            etag = hashlib.md5(etag_source.encode()).hexdigest()[:16]
            
            return FileResponse(
                thumbnail_path,
                media_type="image/webp",
                headers={
                    "Cache-Control": "public, max-age=31536000, immutable",
                    "ETag": f'"{etag}"',
                    "Content-Disposition": f"inline; {encode_filename_for_header(os.path.basename(thumbnail_path))}"
                }
            )
    
    # Try legacy .medium.png in flat thumb directory
    legacy_thumb_flat = os.path.join(thumb_dir, f"{name_only}.{size}.png")
    if os.path.exists(legacy_thumb_flat):
        stat = os.stat(legacy_thumb_flat)
        etag = hashlib.md5(f"{legacy_thumb_flat}:{stat.st_mtime}".encode()).hexdigest()[:16]
        return FileResponse(
            legacy_thumb_flat,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "ETag": f'"{etag}"',
            }
        )
    
    # Try legacy thumbnail alongside original image (output/name.medium.png)
    # Note: This fallback might be tricky with relative paths, but we try standard locations
    legacy_alongside = os.path.join(OUTPUT_DIR, f"{name_only}.{size}{ext}")
    if os.path.exists(legacy_alongside):
        stat = os.stat(legacy_alongside)
        etag = hashlib.md5(f"{legacy_alongside}:{stat.st_mtime}".encode()).hexdigest()[:16]
        return FileResponse(
            legacy_alongside,
            media_type="image/png" if ext.lower() == ".png" else "image/jpeg",
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "ETag": f'"{etag}"',
            }
        )
    
    # Search in date-based hierarchy for original image
    # Optimization: Use index if available
    if original_path and os.path.exists(original_path):
        return FileResponse(
            original_path,
            headers={
                "Cache-Control": "public, max-age=3600",
                "Content-Disposition": f"inline; {encode_filename_for_header(base_name)}"
            }
        )

    if "/" in filename:
        original_pattern = os.path.join(OUTPUT_DIR, "**", filename)
        original_matches = glob.glob(original_pattern, recursive=True)
        original_matches = [m for m in original_matches if "/thumb/" not in m]
        
        if original_matches:
            full_path = original_matches[0]
            return FileResponse(
                full_path,
                headers={
                    "Cache-Control": "public, max-age=3600",
                    "Content-Disposition": f"inline; {encode_filename_for_header(filename)}"
                }
            )
    
    # Final fallback: check flat output directory
    full_path = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(full_path) and os.path.isfile(full_path):
        return FileResponse(
            full_path,
            headers={
                "Cache-Control": "public, max-age=3600",
                "Content-Disposition": f"inline; {encode_filename_for_header(filename)}"
            }
        )
    
    # If we reached here, the file does not exist on disk in any format or location.
    # Self-heal the database index by soft-deleting this missing file so it doesn't show up again.
    _soft_delete_assets(filename)
    
    raise NotFoundError("Resource", "File not found")


@router.post("/api/upload")
async def upload_file_endpoint(
    file: UploadFile = File(...),
    path: str = "input",
    request: Request = None,
):
    """Upload a file to storage.

    Bounded by MAX_UPLOAD_BYTES, restricted to ALLOWED_UPLOAD_EXTENSIONS, and
    written under a sanitized filename inside a path-checked directory. Image
    extensions are additionally verified to be readable images within the
    dimension budget, so a `.png` that is really something else never lands on
    disk.
    """
    if not file.filename:
        raise UploadValidationError(
            "Filename is required", code="UPLOAD_INVALID", field="file"
        )

    # Resolve the target directory before reading the body so a bad `path` is
    # refused without spending bandwidth.
    upload_dir = get_safe_path(OUTPUT_DIR, path)
    filename = sanitize_filename(file.filename, default="upload")

    require_extension(filename, ALLOWED_UPLOAD_EXTENSIONS, field="file")
    require_declared_size(file, MAX_UPLOAD_BYTES)

    content = await read_upload_bounded(
        file,
        MAX_UPLOAD_BYTES,
        field="file",
        should_cancel=_cancel_checker(request) if request is not None else None,
    )

    if not content:
        raise UploadValidationError(
            "Uploaded file is empty", code="UPLOAD_INVALID", field="file"
        )

    ext = os.path.splitext(filename)[1].lower()
    if ext in IMAGE_EXTENSIONS:
        inspect_image(content, field="file", label="Uploaded file")

    file_path = get_safe_path(upload_dir, filename)

    def _write_file():
        os.makedirs(upload_dir, exist_ok=True)
        with open(file_path, 'wb') as f:
            f.write(content)

    await asyncio.to_thread(_write_file)

    return {"status": "success", "filename": filename}


@router.post("/api/upload/input")
async def upload_input_image(
    file: UploadFile = File(...),
    provider_id: str | None = None,
    session: Session = Depends(get_session),
    request: Request = None,
):
    """
    Upload an image for Img2Img or Inpainting.
    Saves locally and syncs to ALL active providers to ensure availability.

    The payload is verified as a real image (not just an image extension) and
    capped at MAX_INPUT_BYTES plus the shared dimension budget. The stored
    extension comes from the format Pillow detected, so a mislabelled file is
    saved truthfully.

    Args:
        file: Image file to upload
        provider_id: Deprecated - now syncs to all active providers
    """
    import uuid

    require_declared_size(file, MAX_INPUT_BYTES)

    content = await read_upload_bounded(
        file,
        MAX_INPUT_BYTES,
        field="file",
        should_cancel=_cancel_checker(request) if request is not None else None,
    )

    # Content-based validation: rejects non-images regardless of extension and
    # caps resolution so a decompression bomb cannot reach a worker.
    width, height, ext = inspect_image(content, field="file", label="Uploaded image")

    # Unique filename to avoid collisions
    unique_name = f"{uuid.uuid4().hex}{ext}"

    # Save locally first (for preview/fallback) - use dedicated input folder
    local_path = os.path.join(INPUT_DIR, unique_name)

    def _save():
        os.makedirs(INPUT_DIR, exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(content)

    await asyncio.to_thread(_save)

    # Sync to ALL active providers (so job can go to any of them)
    sync_result = await _sync_file_to_providers(session, unique_name, content, "input")
    synced_count = sync_result["synced_count"]
    failed_count = sync_result["failed_count"]

    logger.info("upload_complete", filename=unique_name, synced=synced_count, failed=failed_count)

    return {
        "status": "success",
        "filename": unique_name,
        "path": f"input/{unique_name}",
        "local_preview": f"/api/view/input/{unique_name}",
        "width": width,
        "height": height,
        "sync_status": sync_result["sync_status"],
        "synced_providers": synced_count
    }


@router.post("/api/upload/mask")
async def upload_mask_image(
    request: dict,
    provider_id: str | None = None,
    session: Session = Depends(get_session)
):
    """
    Upload a mask image for inpainting.
    Accepts base64 data URL from canvas export.
    Syncs to ALL active providers.

    The decoded payload is bounded *before* decoding and must be a real image
    within the shared dimension budget - the endpoint always stores PNG, so a
    non-image would previously have been written with an image extension.
    """
    import uuid

    if not isinstance(request, dict):
        raise UploadValidationError(
            "Request body must be a JSON object", code="UPLOAD_INVALID", field="body"
        )

    mask_data = request.get("mask_data")
    source_filename = sanitize_filename(request.get("source_filename") or "", default="")

    if not mask_data:
        raise ValidationError("mask_data is required")

    content = decode_base64_bounded(
        mask_data, MAX_INPUT_BYTES, field="mask_data", label="Mask data"
    )

    inspect_image(content, field="mask_data", label="Mask")

    # Generate filename linked to source
    source_base = os.path.splitext(source_filename)[0] if source_filename else "mask"
    mask_filename = f"{source_base}_mask_{uuid.uuid4().hex[:8]}.png"

    # Save locally to dedicated input folder
    local_path = get_safe_path(INPUT_DIR, mask_filename)

    def _save_mask():
        os.makedirs(INPUT_DIR, exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(content)

    await asyncio.to_thread(_save_mask)

    # Sync to ALL active providers
    sync_result = await _sync_file_to_providers(session, mask_filename, content, "input")

    return {
        "status": "success",
        "filename": mask_filename,
        "path": f"input/{mask_filename}",
        "sync_status": sync_result["sync_status"],
        "synced_providers": sync_result["synced_count"]
    }


@router.delete("/api/files/{filename}")
async def delete_single_file(filename: str):
    """Delete a single file (cleanup after failed gallery refresh)."""
    import glob

    def _delete():
        safe_filename = filename.lstrip("/\\")
        local_path = None

        try:
            local_path = get_safe_path(OUTPUT_DIR, safe_filename)
        except ValidationError as e:
            logger.warning("delete_file_path_invalid", error=str(e))

        if local_path and os.path.exists(local_path):
            if os.path.isdir(local_path):
                _soft_delete_assets(safe_filename)
                return {"status": "success", "deleted": True}
            os.remove(local_path)
            meta_path = f"{local_path}.json"
            if os.path.exists(meta_path):
                os.remove(meta_path)
            _delete_thumbnails(local_path)
            _soft_delete_assets(safe_filename)
            logger.info("delete_file_removed", path=local_path)
            return {"status": "success", "deleted": True}

        indexed_path = _resolve_asset_path(safe_filename)
        if indexed_path and os.path.exists(indexed_path):
            os.remove(indexed_path)
            meta_path = f"{indexed_path}.json"
            if os.path.exists(meta_path):
                os.remove(meta_path)
            _delete_thumbnails(indexed_path)
            _soft_delete_assets(safe_filename)
            logger.info("delete_file_removed", path=indexed_path)
            return {"status": "success", "deleted": True}

        pattern = os.path.join(OUTPUT_DIR, "**", safe_filename)
        matches = glob.glob(pattern, recursive=True)
        matches = [m for m in matches if "/thumb/" not in m]
        if matches:
            os.remove(matches[0])
            _delete_thumbnails(matches[0])
            _soft_delete_assets(safe_filename)
            logger.info("delete_file_removed", path=matches[0])
            return {"status": "success", "deleted": True}

        _soft_delete_assets(safe_filename)
        raise NotFoundError("Resource", f"File '{filename}' not found")

    try:
        return await asyncio.to_thread(_delete)
    except ValidationError:
        raise ValidationError("Invalid filename")
    except NotFoundError:
        raise
    except Exception as e:
        raise ComfyError(str(e))


@router.post("/api/batch/delete")
async def batch_delete_endpoint(req: BatchDeleteRequest):
    """Batch delete files."""
    # Validate directory
    allowed_dirs = [
        "output",
        "models/checkpoints",
        "models/loras",
        "models/vae",
        "models/controlnet",
        "models/unet",
        "models/clip",
        "models/embeddings",
        "models/upscale_models",
        "models/hypernetworks",
        "models/aesthetics",
        "models/poses",
        "models/wildcards",
        "models/ultralytics/bbox",
        "models/motion_modules",
    ]
    if req.directory not in allowed_dirs:
        raise ValidationError("Invalid directory")

    # Bound the batch before touching the filesystem: a 100k-entry delete
    # list would otherwise fan out into 100k stat/glob/unlink calls.
    require_batch_size(req.files, MAX_BATCH_ITEMS, field="files")

    try:
        return await asyncio.to_thread(_batch_delete_sync, req.directory, req.files)
    except ComfyError:
        # Validation/upload errors keep their own status and code (400) instead
        # of being flattened into a generic 500.
        raise
    except Exception as e:
        raise ComfyError(str(e))


def _batch_delete_sync(directory: str, filenames: list[str]) -> dict:
    """Worker-thread body for `POST /api/batch/delete`.

    The per-item loop used to be inline in the `async def` route, so at
    MAX_BATCH_ITEMS it ran ~2000 recursive globs of the whole `output/thumb`
    tree plus one synchronous session (and commit) per item on the event loop.
    The delete-by-asset-id route already wrapped the same glob in
    `to_thread`; this variant was missed.

    One session is opened for the whole batch and threaded through
    `_soft_delete_assets`, so a 1000-item delete checks out one pooled
    connection for the duration instead of 1000.
    """
    import glob

    success_count = 0
    with _sync_session() as session:
        for filename in filenames:
            filename = filename.lstrip("/\\")

            # Handle output directory (supports hierarchical date-based folders)
            if directory == "output":
                # First try direct path
                try:
                    local_path = get_safe_path(OUTPUT_DIR, filename)
                except ValidationError:
                    logger.warning("delete_path_traversal_blocked", filename=filename, directory="output")
                    continue

                if not os.path.exists(local_path):
                    indexed_path = _resolve_asset_path(filename, session)
                    if indexed_path and os.path.exists(indexed_path):
                        local_path = indexed_path
                    elif "/" in filename:
                        pattern = os.path.join(OUTPUT_DIR, "**", filename)
                        matches = glob.glob(pattern, recursive=True)
                        matches = [m for m in matches if "/thumb/" not in m]
                        if matches:
                            local_path = matches[0]
                        else:
                            logger.info("delete_file_not_found", filename=filename)
                            _soft_delete_assets(filename, session)
                            success_count += 1
                            continue
                    else:
                        logger.info("delete_file_not_found", filename=filename)
                        _soft_delete_assets(filename, session)
                        success_count += 1
                        continue

                if os.path.exists(local_path):
                    if os.path.isdir(local_path):
                        logger.warning("delete_is_directory", filename=filename, path=local_path)
                        _soft_delete_assets(filename, session)
                        success_count += 1
                        continue
                    try:
                        os.remove(local_path)
                        logger.info("delete_file_removed", path=local_path)

                        # Also remove metadata sidecar if exists
                        meta_path = f"{local_path}.json"
                        if os.path.exists(meta_path):
                            os.remove(meta_path)

                        _delete_thumbnails(local_path, session)
                        _soft_delete_assets(filename, session)

                        success_count += 1
                    except Exception as e:
                        logger.warning("delete_file_failed", filename=filename, error=str(e))
            else:
                # Handle model files
                try:
                    target_dir = os.path.join(CACHE_DIR, directory)
                    model_path = get_safe_path(target_dir, filename)
                except ValidationError:
                    logger.warning("delete_path_traversal_blocked", filename=filename, directory="models")
                    continue

                if os.path.exists(model_path):
                    try:
                        os.remove(model_path)
                        success_count += 1
                    except Exception as e:
                        logger.warning("delete_file_failed", filename=filename, error=str(e))

    return {"status": "success", "deleted": success_count, "total": len(filenames)}


class BatchMetadataRequest(BaseModel):
    """Request model for batch metadata fetching."""
    paths: list[str]


@router.post("/api/files/metadata/batch")
async def batch_get_metadata(request: BatchMetadataRequest):
    """
    Get metadata for multiple images in a single request.
    
    This is more efficient than making individual metadata requests for gallery loading.
    
    Args:
        request: BatchMetadataRequest with list of image paths
        
    Returns:
        Dict mapping paths to their metadata
    """
    from infrastructure.image_processor import read_image_metadata

    require_batch_size(request.paths, MAX_BATCH_ITEMS, field="paths")

    def _process(paths: list[str]) -> dict:
        results = {}
        missing_files_map = {}  # path -> filename

        # One session for the whole batch, opened lazily on the first name that
        # needs the index. `_resolve_asset_path` takes one precisely so this is
        # possible (`_build_export_zip_sync` does the same at MAX_EXPORT_FILES),
        # and both call sites here were passing none — so each unresolved name
        # checked out its own pooled connection and held it across two SELECTs.
        # At MAX_BATCH_ITEMS (1000) that is 1000 checkouts for one request.
        # Lazy, not eager: a batch where every path resolves directly never
        # needs a connection at all.
        from contextlib import ExitStack

        with ExitStack() as session_stack:
            session_holder: list[Session] = []

            def _resolve(name: str):
                if not session_holder:
                    session_holder.append(session_stack.enter_context(_sync_session()))
                return _resolve_asset_path(name, session_holder[0])

            def _get_metadata_result(full_path):
                """Helper to extract metadata from a file."""
                try:
                    metadata = read_image_metadata(full_path)
                    return {
                        "success": True,
                        "metadata": metadata,
                        "blurhash": metadata.get("blurhash")
                    }
                except Exception:
                    # Fallback to sidecar JSON
                    meta_path = f"{full_path}.json"
                    if os.path.exists(meta_path):
                        try:
                            with open(meta_path, 'r') as f:
                                metadata = json.load(f)
                            return {
                                "success": True,
                                "metadata": metadata,
                                "blurhash": metadata.get("blurhash")
                            }
                        except Exception:
                            return {"error": "metadata_read_failed"}
                    else:
                        return {"error": "metadata_not_found"}

            # Phase 1: Check direct paths and collect missing files
            for path in paths:
                try:
                    # Normalize path
                    if path.startswith("output/"):
                        filename = path.replace("output/", "").lstrip("/\\")
                    else:
                        filename = path.lstrip("/\\")

                    # Try direct path first
                    try:
                        full_path = get_safe_path(OUTPUT_DIR, filename)
                    except ValidationError:
                        results[path] = {"error": "invalid_path"}
                        continue

                    if os.path.exists(full_path):
                        results[path] = _get_metadata_result(full_path)
                    else:
                        indexed_path = _resolve(filename)
                        if indexed_path and os.path.exists(indexed_path):
                            results[path] = _get_metadata_result(indexed_path)
                        else:
                            # Keep a basename fallback for legacy callers that only store filenames
                            missing_files_map[path] = filename

                except Exception as e:
                    results[path] = {"error": str(e)}

            # Phase 2: Single pass scan for missing files
            if missing_files_map:
                unresolved = {}
                for path, filename in missing_files_map.items():
                    full_path = _resolve(os.path.basename(filename))
                    if full_path and os.path.exists(full_path):
                        results[path] = _get_metadata_result(full_path)
                    else:
                        unresolved[path] = os.path.basename(filename)

                if unresolved:
                    target_filenames = set(unresolved.values())

                    def _scan_metadata():
                        found = {}
                        for root, dirs, files in os.walk(OUTPUT_DIR):
                            if "thumb" in dirs:
                                dirs.remove("thumb")
                            for f in files:
                                if f not in target_filenames:
                                    continue
                                found.setdefault(f, []).append(os.path.join(root, f))
                        return found

                    found_files = _scan_metadata()

                    for path, filename in unresolved.items():
                        matches = found_files.get(filename, [])
                        if len(matches) == 1:
                            results[path] = _get_metadata_result(matches[0])
                        else:
                            results[path] = {"error": "not_found"}

            return results

    results = await asyncio.to_thread(_process, request.paths)

    return {
        "results": results,
        "total": len(request.paths),
        "found": sum(1 for r in results.values() if r.get("success"))
    }
