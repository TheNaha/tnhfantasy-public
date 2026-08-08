# File routes - Gallery file listing, viewing, upload and deletion
#
# Serves files from two directories:
#   OUTPUT_DIR – generated images (PNG, organized by date)
#   INPUT_DIR  – user-uploaded source images for Img2Img/Inpainting
#
# KEY ENDPOINTS:
#   GET  /api/files                        – Paginated file listing (uses GalleryIndexer)
#   GET  /api/files/{filename}             – Serve a raw file (full resolution)
#   GET  /api/thumbnail/{size}/{filename}  – Serve a pre-generated WebP thumbnail
#   POST /api/files/upload                 – Upload a file to OUTPUT_DIR
#   POST /api/upload/input                 – Upload a source image (Img2Img)
#   POST /api/upload/mask                  – Upload an inpainting mask (base64→PNG)
#   DELETE /api/files/{filename}           – Delete a file and its thumbnail
import asyncio
import base64
import json
import os
import tempfile

from fastapi import APIRouter, Depends, File, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session
from starlette.background import BackgroundTask

from api.deps import (
    get_logger,
    get_model_service_v2,
    get_provider_service,
    get_session,
)
from config import settings
from core.exceptions import ComfyError, NotFoundError, ValidationError
from services.provider_service import ProviderService

logger = get_logger("files_route")

router = APIRouter(tags=["files"])

# Output directory - defaults to backend output folder
OUTPUT_DIR = settings.output_dir
INPUT_DIR = settings.input_dir
CACHE_DIR = os.environ.get("CACHE_DIR", os.path.join(os.path.dirname(__file__), "../../cache"))

MAX_INPUT_SIZE_MB = 50


def _delete_thumbnails(local_path: str) -> None:
    """Remove all thumbnail variants for an output image.

    Thumbnails live in OUTPUT_DIR/thumb mirrored by date hierarchy
    (output/thumb/YYYY/MM/DD/name.webp) plus legacy flat files
    (output/thumb/name.medium.png / name.full.png).
    """
    import glob

    name_only = os.path.splitext(os.path.basename(local_path))[0]
    rel_dir = os.path.relpath(os.path.dirname(local_path), OUTPUT_DIR)

    candidates = [
        os.path.join(OUTPUT_DIR, "thumb", rel_dir, f"{name_only}.webp"),
        os.path.join(OUTPUT_DIR, "thumb", f"{name_only}.medium.png"),
        os.path.join(OUTPUT_DIR, "thumb", f"{name_only}.full.png"),
    ]
    for candidate in candidates:
        try:
            if os.path.exists(candidate):
                os.remove(candidate)
        except OSError:
            pass

    # Catch any stragglers elsewhere in the thumb tree (same basename).
    thumb_root = os.path.join(OUTPUT_DIR, "thumb")
    for pattern in (f"**/{name_only}.webp", f"**/{name_only}.png"):
        for match in glob.glob(os.path.join(thumb_root, pattern), recursive=True):
            try:
                os.remove(match)
            except OSError:
                pass



async def _sync_file_to_providers(session: Session, filename: str, content: bytes, directory: str = "input") -> dict:
    """
    Sync an uploaded file to all active providers.
    Returns {"sync_status": str, "synced_count": int, "failed_count": int}.
    """
    from services.provider_runtime import resolve_provider_runtime

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

            provider_entity = service.get_provider(p_id)
            if not provider_entity:
                continue
            
            runtime = resolve_provider_runtime(provider_entity)
            if not runtime.worker_url:
                continue
                
            active_providers.append({"id": p_id, "worker_url": runtime.worker_url})

        if active_providers:
            from api.deps import get_http_client
            http = get_http_client()
            payload = {
                "filename": filename,
                "content_base64": base64.b64encode(content).decode(),
                "directory": directory,
            }

            for provider in active_providers:
                worker_url = provider["worker_url"]
                provider_id = provider["id"]

                try:
                    response = await http.post(
                        f"{worker_url}/upload-file",
                        json=payload,
                        timeout=30.0,
                    )
                    if response.status_code == 200:
                        synced_count += 1
                    else:
                        failed_count += 1
                        logger.warning("sync_provider_failed", provider_id=provider_id, status=response.status_code)
                except Exception as e:
                    failed_count += 1
                    logger.warning("sync_provider_error", provider_id=provider_id, error=str(e))

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


@router.post("/api/files/batch-download")
async def batch_download(request: BatchDownloadRequest):
    """Create a ZIP file of multiple images for batch download."""
    import zipfile

    from services.gallery_indexer import gallery_indexer
    
    fd, temp_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    
    try:
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for filename in request.files:
                indexed_path = gallery_indexer.get_path(filename)
                if not indexed_path:
                    indexed_path = gallery_indexer.get_path_by_filename(os.path.basename(filename))
                
                if indexed_path and os.path.exists(indexed_path):
                    zipf.write(indexed_path, arcname=os.path.basename(filename))
                else:
                    try:
                        safe_path = get_safe_path(OUTPUT_DIR, filename)
                        if os.path.exists(safe_path):
                            zipf.write(safe_path, arcname=os.path.basename(filename))
                    except Exception as e:
                        logger.warning("batch_download_file_error", filename=filename, error=str(e))
                        
        return FileResponse(
            temp_path,
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=batch_download.zip"},
            background=BackgroundTask(os.remove, temp_path)
        )
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        from core.exceptions import ComfyError
        raise ComfyError(f"Failed to create batch download: {e!s}")

def get_safe_path(base_dir: str, requested_path: str) -> str:
    """
    Resolve and validate a path to prevent directory traversal.

    Args:
        base_dir: The trusted base directory.
        requested_path: The user-provided path component.

    Returns:
        The absolute resolved path if valid.

    Raises:
       (403) if path traversal is detected.
    """
    # Remove leading slashes to prevent absolute path interpretation
    clean_path = requested_path.lstrip("/\\")

    if not clean_path:
        raise ValidationError("Invalid path: path cannot be empty")

    # Resolve full path
    full_path = os.path.abspath(os.path.join(base_dir, clean_path))
    base_path = os.path.abspath(base_dir)

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

        total = len(valid_files)
        paginated = valid_files[offset:offset + limit]

        return {"files": paginated, "total": total}

    except Exception as e:
        logger.warning("model_cache_read_failed", error=str(e))
        return {"files": [], "total": 0}


@router.get("/api/v2/gallery")
async def get_v2_gallery(
    limit: int = 20, 
    offset: int = 0, 
    sort: str = "date_desc", 
    search: str | None = None,
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
    limit: int = 20, 
    offset: int = 0, 
    sort: str = "date_desc", 
    search: str | None = None,
    base_model: str | None = None,
    model_type: str | None = None,
    show_nsfw: bool = True,
    tags: str | None = None,
    workspace: str | None = None,
    character_id: str | None = None,
    story_id: str | None = None,
    model_service = Depends(get_model_service_v2)
):
    """List files in a directory with pagination and search."""
    
    # Handle Local Output Files
    if directory == "output" or directory.startswith("output/"):
        try:
            from services.gallery_indexer import gallery_indexer
            return await asyncio.to_thread(
                gallery_indexer.get_files, limit=limit, offset=offset, sort=sort, search=search, workspace=workspace, character_id=character_id, story_id=story_id
            )
            
        except Exception as e:
            logger.warning("local_file_list_failed", error=str(e))
            return {"files": [], "total": 0}

    # Handle Models directories - query from SQLite model service
    if directory.startswith("models/"):
        model_dir_type = directory.replace("models/", "")
        
        try:
            # Get models for this directory from SQLite
            models = await model_service.list_models_by_directory(model_dir_type)
            
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
                
                # Get base model and trained words from default version
                version_base_model = default_version.get("base_model", "") if default_version else ""
                trained_words = default_version.get("trained_words", []) if default_version else []
                
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
                
                # Get images from default version
                version_images = default_version.get("images", []) if default_version else []
                
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
                    "base_model": version_base_model,
                    "trained_words": trained_words,
                    "version_count": len(versions),
                    "default_version": default_version.get("name", "") if default_version else "",
                    # Version description (separate from model description)
                    "version_description": default_version.get("description", "") if default_version else "",
                    # Full versions list for version selector
                    "versions": versions,
                    # Model type
                    "type": model.get("type", ""),
                    "nsfw": model.get("nsfw", False),
                    # Preview image
                    "preview": preview_url,
                    # All images from version for gallery
                    "images": version_images,
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
                
                
                # Apply search filter
                if search:
                    search_lower = search.lower()
                    # Include all version filenames in searchable string
                    version_filenames = " ".join([
                        (v.get("file") or {}).get("filename", "") for v in versions if v
                    ])
                    searchable = f"{file_data['name']} {file_data['display_name']} {version_filenames}".lower()
                    if search_lower not in searchable:
                        continue
                
                valid_files.append(file_data)
            
            # Apply filters
            if base_model and base_model != "all":
                valid_files = [f for f in valid_files if f.get("base_model") == base_model]
            if model_type and model_type != "all":
                valid_files = [f for f in valid_files if f.get("type") == model_type]
            if not show_nsfw:
                valid_files = [f for f in valid_files if not f.get("nsfw", False)]
            
            if tags:
                tag_list = [t.strip() for t in tags.split(",")]
                valid_files = [f for f in valid_files if all(tag in f.get("tags", []) for tag in tag_list)]
            
            # Sort
            if sort == "date_desc":
                valid_files.sort(key=lambda x: x.get("modified_time", 0), reverse=True)
            elif sort == "name_asc":
                valid_files.sort(key=lambda x: x.get("name", ""))
            elif sort == "name_desc":
                valid_files.sort(key=lambda x: x.get("name", ""), reverse=True)
                
            total = len(valid_files)
            paginated = valid_files[offset:offset + limit]
            
            return {"files": paginated, "total": total}
            
        except Exception as e:
            logger.warning("model_service_query_failed", error=str(e), exc_info=True)
        
        # Fallback: try to read from local cache directory
        # Run in thread pool to avoid blocking I/O
        return await asyncio.to_thread(
            _scan_local_model_directory,
            model_dir_type,
            search,
            sort,
            limit,
            offset
        )
    
    return {"files": [], "total": 0}


@router.get("/api/view/{path:path}")
async def view_file_endpoint(path: str):
    """Serve files from local output or cached previews."""
    import glob

    from services.gallery_indexer import gallery_indexer
    
    # Try local output first
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

        # Optimization: Check the gallery index before any recursive scan
        indexed_path = gallery_indexer.get_path(filename)
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
            matches = await asyncio.to_thread(glob.glob, pattern, recursive=True)
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
    
    Args:
        size: Thumbnail size - 'medium' (512px)
        filename: Original image filename
        
    Returns:
        Thumbnail image if exists, otherwise falls back to full image
    """
    import glob
    import hashlib

    from services.gallery_indexer import gallery_indexer
    
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
    
    # Optimization: Use gallery index to find original image, then infer thumbnail path
    original_path = gallery_indexer.get_path(filename)
    if not original_path:
        original_path = gallery_indexer.get_path_by_filename(base_name)

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
        webp_matches = await asyncio.to_thread(glob.glob, webp_pattern, recursive=True)
        
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
        original_matches = await asyncio.to_thread(glob.glob, original_pattern, recursive=True)
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
    
    raise NotFoundError("Resource", "File not found")


MAX_UPLOAD_SIZE_MB = 500

ALLOWED_UPLOAD_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff',
    '.safetensors', '.ckpt', '.pt', '.pth', '.bin',
    '.json', '.yaml', '.yml', '.txt', '.csv',
    '.zip', '.tar', '.gz',
    '.onnx', '.gguf',
}


@router.post("/api/upload")
async def upload_file_endpoint(file: UploadFile = File(...), path: str = "input"):
    """Upload a file to storage."""
    from core.exceptions import ValidationError

    if not file.filename:
        raise ValidationError("Filename is required")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise ValidationError(
            f"File type '{ext}' is not allowed. "
            f"Allowed types: {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}"
        )

    if file.size is not None and file.size > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise ValidationError(
            f"File size exceeds the {MAX_UPLOAD_SIZE_MB} MB limit. "
            f"Received: {file.size / (1024 * 1024):.1f} MB"
        )

    content = await file.read()
    actual_size = len(content)
    if actual_size > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise ValidationError(
            f"File size exceeds the {MAX_UPLOAD_SIZE_MB} MB limit. "
            f"Received: {actual_size / (1024 * 1024):.1f} MB"
        )

    upload_dir = get_safe_path(OUTPUT_DIR, path)
    filename = os.path.basename(file.filename)
    file_path = os.path.join(upload_dir, filename)

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
    session: Session = Depends(get_session)
):
    """
    Upload an image for Img2Img or Inpainting.
    Saves locally and syncs to ALL active providers to ensure availability.
    
    Args:
        file: Image file to upload
        provider_id: Deprecated - now syncs to all active providers
    """
    import io
    import uuid

    from PIL import Image
    
    # Size guard: reject oversized uploads before reading into memory
    if file.size is not None and file.size > MAX_INPUT_SIZE_MB * 1024 * 1024:
        raise ValidationError(
            f"File size exceeds the {MAX_INPUT_SIZE_MB} MB limit. "
            f"Received: {file.size / (1024 * 1024):.1f} MB"
        )
    
    # Generate unique filename to avoid collisions
    ext = os.path.splitext(file.filename)[1] or ".png"
    unique_name = f"{uuid.uuid4().hex}{ext}"
    
    content = await file.read()
    
    if len(content) > MAX_INPUT_SIZE_MB * 1024 * 1024:
        raise ValidationError(
            f"File size exceeds the {MAX_INPUT_SIZE_MB} MB limit."
        )
    
    # Save locally first (for preview/fallback) - use dedicated input folder
    local_path = os.path.join(INPUT_DIR, unique_name)

    def _save_and_measure():
        os.makedirs(INPUT_DIR, exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(content)
        # Get image dimensions
        try:
            img = Image.open(io.BytesIO(content))
            return img.size
        except Exception as e:
            logger.warning("upload_image_dimensions_failed", error=str(e))
            return (0, 0)

    width, height = await asyncio.to_thread(_save_and_measure)
    
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
    """
    import base64
    import uuid
    
    mask_data = request.get("mask_data")
    source_filename = request.get("source_filename", "")
    
    # Sanitize source filename
    if source_filename:
        source_filename = os.path.basename(source_filename)

    if not mask_data:
        raise ValidationError("mask_data is required")
    
    # Parse data URL: data:image/png;base64,iVBORw0KGgoAAAA...
    if ',' in mask_data:
        header, b64_data = mask_data.split(',', 1)
    else:
        b64_data = mask_data
    
    try:
        content = base64.b64decode(b64_data)
    except Exception as e:
        raise ValidationError(f"Invalid base64 data: {e}")
    
    if len(content) > MAX_INPUT_SIZE_MB * 1024 * 1024:
        raise ValidationError(
            f"Decoded file size exceeds the {MAX_INPUT_SIZE_MB} MB limit."
        )
    
    # Generate filename linked to source
    source_base = os.path.splitext(source_filename)[0] if source_filename else "mask"
    mask_filename = f"{source_base}_mask_{uuid.uuid4().hex[:8]}.png"
    
    # Save locally to dedicated input folder
    local_path = os.path.join(INPUT_DIR, mask_filename)

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
            os.remove(local_path)
            meta_path = f"{local_path}.json"
            if os.path.exists(meta_path):
                os.remove(meta_path)
            _delete_thumbnails(local_path)
            logger.info("delete_file_removed", path=local_path)
            return {"status": "success", "deleted": True}

        from services.gallery_indexer import gallery_indexer
        indexed_path = gallery_indexer.get_path(safe_filename)
        if indexed_path and os.path.exists(indexed_path):
            os.remove(indexed_path)
            meta_path = f"{indexed_path}.json"
            if os.path.exists(meta_path):
                os.remove(meta_path)
            _delete_thumbnails(indexed_path)
            logger.info("delete_file_removed", path=indexed_path)
            return {"status": "success", "deleted": True}

        pattern = os.path.join(OUTPUT_DIR, "**", safe_filename)
        matches = glob.glob(pattern, recursive=True)
        matches = [m for m in matches if "/thumb/" not in m]
        if matches:
            os.remove(matches[0])
            _delete_thumbnails(matches[0])
            logger.info("delete_file_removed", path=matches[0])
            return {"status": "success", "deleted": True}

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
    import glob
    
    try:
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
        
        success_count = 0
        for filename in req.files:
            filename = filename.lstrip("/\\")

            # Handle output directory (supports hierarchical date-based folders)
            if req.directory == "output":
                # First try direct path
                try:
                    local_path = get_safe_path(OUTPUT_DIR, filename)
                except ValidationError:
                    logger.warning("delete_path_traversal_blocked", filename=filename, directory="output")
                    continue
                
                if not os.path.exists(local_path):
                    from services.gallery_indexer import gallery_indexer

                    indexed_path = gallery_indexer.get_path(filename)
                    if indexed_path and os.path.exists(indexed_path):
                        local_path = indexed_path
                    elif "/" in filename:
                        pattern = os.path.join(OUTPUT_DIR, "**", filename)
                        matches = await asyncio.to_thread(glob.glob, pattern, recursive=True)
                        matches = [m for m in matches if "/thumb/" not in m]
                        if matches:
                            local_path = matches[0]
                        else:
                            logger.info("delete_file_not_found", filename=filename)
                            continue
                    else:
                        logger.info("delete_file_not_found", filename=filename)
                        continue
                
                if os.path.exists(local_path):
                    try:
                        os.remove(local_path)
                        logger.info("delete_file_removed", path=local_path)
                        
                        # Also remove metadata sidecar if exists
                        meta_path = f"{local_path}.json"
                        if os.path.exists(meta_path):
                            os.remove(meta_path)
                        
                        _delete_thumbnails(local_path)
                        
                        success_count += 1
                    except Exception as e:
                        logger.warning("delete_file_failed", filename=filename, error=str(e))
            else:
                # Handle model files
                try:
                    target_dir = os.path.join(CACHE_DIR, req.directory)
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
        
        return {"status": "success", "deleted": success_count, "total": len(req.files)}
        
    except Exception as e:
        raise ComfyError(str(e))


# Proxy endpoints for provider storage
@router.get("/api/files/proxy/{provider_id}/{path:path}")
async def proxy_file(
    provider_id: str,
    path: str,
    service: ProviderService = Depends(get_provider_service)
):
    """Proxy file from provider storage."""
    from api.deps import create_provider_client
    
    provider_data = await service.get_provider(provider_id)
    
    provider = create_provider_client(provider_id, {
        "type": provider_data.type,
        "credentials": provider_data.credentials,
        "config": provider_data.config,
        "container_config": provider_data.container_config or {}
    })
    
    try:
        file_proxy = provider.get_file_proxy()
        content = await file_proxy.get_file(path)
        
        path_lower = path.lower()
        if path_lower.endswith(('.png', '.jpg', '.jpeg', '.webp')):
            if path_lower.endswith('.png'):
                media_type = "image/png"
            elif path_lower.endswith('.webp'):
                media_type = "image/webp"
            else:
                media_type = "image/jpeg"
        else:
            media_type = "application/octet-stream"
        
        return Response(content=content, media_type=media_type)
    
    except Exception as e:
        raise NotFoundError("Resource", str(e))


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
    from api.deps import read_image_metadata
    from services.gallery_indexer import gallery_indexer

    def _process(paths: list[str]) -> dict:
        results = {}
        missing_files_map = {}  # path -> filename

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
                    indexed_path = gallery_indexer.get_path(filename)
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
                full_path = gallery_indexer.get_path_by_filename(os.path.basename(filename))
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
