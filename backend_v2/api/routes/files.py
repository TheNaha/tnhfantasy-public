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
import os
import json
from typing import Optional
from fastapi import APIRouter, HTTPException, Response, Depends, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask
from sqlmodel import Session
from pydantic import BaseModel
from typing import List
import tempfile
import asyncio

from api.deps import get_session, get_provider_service

router = APIRouter(tags=["files"])

# Output directory - defaults to backend output folder
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", os.path.join(os.path.dirname(__file__), "../../output"))
INPUT_DIR = os.environ.get("INPUT_DIR", os.path.join(os.path.dirname(__file__), "../../input"))
CACHE_DIR = os.environ.get("CACHE_DIR", os.path.join(os.path.dirname(__file__), "../../cache"))


class BatchDeleteRequest(BaseModel):
    directory: str
    files: List[str]


def get_safe_path(base_dir: str, requested_path: str) -> str:
    """
    Resolve and validate a path to prevent directory traversal.

    Args:
        base_dir: The trusted base directory.
        requested_path: The user-provided path component.

    Returns:
        The absolute resolved path if valid.

    Raises:
        HTTPException(403) if path traversal is detected.
    """
    # Remove leading slashes to prevent absolute path interpretation
    clean_path = requested_path.lstrip("/\\")

    if not clean_path:
        raise HTTPException(status_code=400, detail="Invalid path: path cannot be empty")

    # Resolve full path
    full_path = os.path.abspath(os.path.join(base_dir, clean_path))
    base_path = os.path.abspath(base_dir)

    # Use commonpath so mixed separators and platform differences are handled correctly.
    try:
        common = os.path.commonpath([full_path, base_path])
    except ValueError:
        # Happens when drives differ on Windows (e.g. C:\ vs D:\)
        raise HTTPException(status_code=403, detail="Access denied: Path outside allowed directory")

    if common != base_path:
        raise HTTPException(status_code=403, detail="Access denied: Path outside allowed directory")

    return full_path


def encode_filename_for_header(filename: str) -> str:
    """Encode filename for Content-Disposition header using RFC 2231."""
    from urllib.parse import quote
    encoded = quote(filename)
    return f"filename*=UTF-8''{encoded}"


def matches_search(item, query):
    """Check if item matches search query."""
    if not query:
        return True
    query_lower = query.lower()
    
    if isinstance(item, dict):
        name = item.get("name", "").lower()
        metadata = item.get("metadata", {})
        
        if query_lower in name:
            return True
        
        if isinstance(metadata, dict):
            for key, value in metadata.items():
                if isinstance(value, str) and query_lower in value.lower():
                    return True
                elif isinstance(value, list):
                    for v in value:
                        if isinstance(v, str) and query_lower in v.lower():
                            return True
        return False
    
    elif isinstance(item, str):
        return query_lower in item.lower()
    
    return False


def _scan_local_model_directory(model_type, search, sort, limit, offset):
    """
    Sync helper to scan model directory.
    Run in thread pool to avoid blocking event loop.
    """
    try:
        base_model_dir = os.path.join(CACHE_DIR, "models")
        try:
            model_cache_dir = get_safe_path(base_model_dir, model_type)
        except HTTPException:
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
                    except:
                        pass

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
        print(f"Model cache read failed: {e}")
        return {"files": [], "total": 0}


@router.get("/api/files")
async def list_files_endpoint(
    directory: str = "output", 
    limit: int = 20, 
    offset: int = 0, 
    sort: str = "date_desc", 
    search: Optional[str] = None
):
    """List files in a directory with pagination and search."""
    
    # Handle Local Output Files
    if directory == "output" or directory.startswith("output/"):
        try:
            from services.gallery_indexer import gallery_indexer
            return gallery_indexer.get_files(limit=limit, offset=offset, sort=sort, search=search)
            
        except Exception as e:
            print(f"Local file list failed: {e}")
            return {"files": [], "total": 0}

    # Handle Models directories - query from SQLite model service
    if directory.startswith("models/"):
        model_type = directory.replace("models/", "")
        
        try:
            from api.deps import get_model_service_v2
            from infrastructure.database import get_session
            
            # Get database session and model service V2
            session_gen = get_session()
            db_session = next(session_gen)
            try:
                model_service = get_model_service_v2(db_session)
                
                # Get models for this directory from SQLite
                models = await model_service.list_models_by_directory(model_type)
            finally:
                if hasattr(session_gen, "close"):
                    session_gen.close()
                elif hasattr(db_session, "close"):
                    db_session.close()
            
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
                file_info = default_version.get("file", {}) if default_version else {}
                filename = file_info.get("filename", model.get("name", "unknown"))
                size_kb = file_info.get("size_kb", 0)
                
                # Get base model and trained words from default version
                base_model = default_version.get("base_model", "") if default_version else ""
                trained_words = default_version.get("trained_words", []) if default_version else []
                
                # Get preview image URL
                preview_image = model.get("preview_image", {})
                civitai_id = model.get("civitai_model_id")
                preview_url = (
                    preview_image.get("url") if preview_image else None
                ) or (
                    f"/api/models/preview-image?model_id={civitai_id}" if civitai_id else ""
                )
                
                # Provider statuses
                provider_statuses = model.get("provider_statuses", {})
                
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
                    "base_model": base_model,
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
                    searchable = f"{file_data['name']} {file_data['display_name']}".lower()
                    if search_lower not in searchable:
                        continue
                
                valid_files.append(file_data)
            
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
            print(f"Model service query failed: {e}")
            import traceback
            traceback.print_exc()
        
        # Fallback: try to read from local cache directory
        # Run in thread pool to avoid blocking I/O
        return await asyncio.to_thread(
            _scan_local_model_directory,
            model_type,
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

        # Optimization: Check index before globbing
        indexed_path = gallery_indexer.get_path_by_filename(filename)
        if indexed_path and os.path.exists(indexed_path):
            return FileResponse(
                indexed_path,
                headers={
                    "Content-Disposition": f"attachment; {encode_filename_for_header(os.path.basename(indexed_path))}"
                }
            )
        
        # Search in date-based subdirectories (fallback)
        pattern = os.path.join(OUTPUT_DIR, "**", filename)
        matches = glob.glob(pattern, recursive=True)
        # Filter out thumb directory
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
    except HTTPException:
        pass
    
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
    
    raise HTTPException(status_code=404, detail="File not found")


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
    import hashlib
    import glob
    from services.gallery_indexer import gallery_indexer
    
    if size not in ("medium",):
        raise HTTPException(status_code=400, detail="Size must be 'medium'")

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
            pass

    # Search priority:
    # 1. New WebP in thumb directory with date hierarchy (output/thumb/YYYY/MM/DD/name.webp)
    # 2. Legacy PNG in flat thumb directory (output/thumb/name.medium.png)
    # 3. Legacy thumbnail alongside original (output/name.medium.png)
    # 4. Fall back to full image
    
    # Try new WebP format in date-based hierarchy
    # Search recursively for the filename in the thumb directory
    # Note: If optimization above worked, we wouldn't be here.
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

    original_pattern = os.path.join(OUTPUT_DIR, "**", filename)
    original_matches = glob.glob(original_pattern, recursive=True)
    # Filter out thumb directory
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
    
    raise HTTPException(status_code=404, detail="File not found")


@router.post("/api/upload")
async def upload_file_endpoint(file: UploadFile = File(...), path: str = "input"):
    """Upload a file to storage."""
    try:
        content = await file.read()
        
        # Save locally
        # Security check: ensure upload path is within OUTPUT_DIR
        upload_dir = get_safe_path(OUTPUT_DIR, path)
        os.makedirs(upload_dir, exist_ok=True)
        
        # Sanitize filename to prevent path traversal
        filename = os.path.basename(file.filename)

        file_path = os.path.join(upload_dir, filename)
        with open(file_path, 'wb') as f:
            f.write(content)
        
        return {"status": "success", "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/upload/input")
async def upload_input_image(
    file: UploadFile = File(...),
    provider_id: Optional[str] = None,
    session: Session = Depends(get_session)
):
    """
    Upload an image for Img2Img or Inpainting.
    Saves locally and syncs to ALL active providers to ensure availability.
    
    Args:
        file: Image file to upload
        provider_id: Deprecated - now syncs to all active providers
    """
    import uuid
    import base64
    import aiohttp
    from PIL import Image
    import io
    
    # Generate unique filename to avoid collisions
    ext = os.path.splitext(file.filename)[1] or ".png"
    unique_name = f"{uuid.uuid4().hex}{ext}"
    
    content = await file.read()
    
    # Save locally first (for preview/fallback) - use dedicated input folder
    os.makedirs(INPUT_DIR, exist_ok=True)
    local_path = os.path.join(INPUT_DIR, unique_name)
    
    with open(local_path, "wb") as f:
        f.write(content)
    
    # Get image dimensions
    try:
        img = Image.open(io.BytesIO(content))
        width, height = img.size
    except Exception as e:
        print(f"[Upload] Could not get image dimensions: {e}")
        width, height = 0, 0
    
    # Sync to ALL active providers (so job can go to any of them)
    sync_status = "local_only"
    synced_count = 0
    failed_count = 0
    
    try:
        service = get_provider_service(session)
        providers = await service.list_providers()
        
        print(f"[Upload] DEBUG: Found {len(providers)} providers")
        
        # Filter enabled providers and construct worker URLs
        active_providers = []
        for p in providers:
            p_id = p.get("id") if isinstance(p, dict) else getattr(p, "id", None)
            enabled = p.get("enabled") if isinstance(p, dict) else getattr(p, "enabled", False)
            config = p.get("container_config") if isinstance(p, dict) else getattr(p, "container_config", {})
            
            if not enabled or not p_id:
                print(f"[Upload] DEBUG: Skipping {p_id}: enabled={enabled}")
                continue
            
            # Construct worker URL from provider ID
            # Container naming: comfy-provider-{id} running on internal port 8000
            worker_url = f"http://comfy-provider-{p_id}:8000"
            
            print(f"[Upload] DEBUG: Provider {p_id}: enabled={enabled}, worker_url={worker_url}")
            active_providers.append({"id": p_id, "worker_url": worker_url})
        
        if active_providers:
            async with aiohttp.ClientSession() as http:
                payload = {
                    "filename": unique_name,
                    "content_base64": base64.b64encode(content).decode(),
                    "directory": "input"
                }
                
                for provider in active_providers:
                    worker_url = provider["worker_url"]
                    provider_id = provider["id"]
                    
                    try:
                        async with http.post(
                            f"{worker_url}/upload-file",
                            json=payload,
                            timeout=aiohttp.ClientTimeout(total=30)
                        ) as response:
                            if response.status == 200:
                                synced_count += 1
                                print(f"[Upload] ✓ Synced {unique_name} to provider {provider_id}")
                            else:
                                failed_count += 1
                                body = await response.text()
                                print(f"[Upload] Sync to {provider_id} failed: {response.status} - {body[:100]}")
                    except Exception as e:
                        failed_count += 1
                        print(f"[Upload] Warning: Failed to sync to provider {provider_id}: {e}")
            
            if synced_count > 0:
                sync_status = "synced"
            elif failed_count > 0:
                sync_status = "sync_failed"
                
    except Exception as e:
        print(f"[Upload] Warning: Could not sync to providers: {e}")
        import traceback
        traceback.print_exc()
        sync_status = "sync_failed"
    
    print(f"[Upload] Image {unique_name}: synced to {synced_count} providers, {failed_count} failed")
    
    return {
        "status": "success",
        "filename": unique_name,
        "path": f"input/{unique_name}",
        "local_preview": f"/api/view/input/{unique_name}",
        "width": width,
        "height": height,
        "sync_status": sync_status,
        "synced_providers": synced_count
    }


@router.post("/api/upload/mask")
async def upload_mask_image(
    request: dict,
    provider_id: Optional[str] = None,
    session: Session = Depends(get_session)
):
    """
    Upload a mask image for inpainting.
    Accepts base64 data URL from canvas export.
    Syncs to ALL active providers.
    """
    import uuid
    import base64
    import aiohttp
    
    mask_data = request.get("mask_data")
    source_filename = request.get("source_filename", "")
    
    # Sanitize source filename
    if source_filename:
        source_filename = os.path.basename(source_filename)

    if not mask_data:
        raise HTTPException(status_code=400, detail="mask_data is required")
    
    # Parse data URL: data:image/png;base64,iVBORw0KGgoAAAA...
    if ',' in mask_data:
        header, b64_data = mask_data.split(',', 1)
    else:
        b64_data = mask_data
    
    try:
        content = base64.b64decode(b64_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 data: {e}")
    
    # Generate filename linked to source
    source_base = os.path.splitext(source_filename)[0] if source_filename else "mask"
    mask_filename = f"{source_base}_mask_{uuid.uuid4().hex[:8]}.png"
    
    # Save locally to dedicated input folder
    os.makedirs(INPUT_DIR, exist_ok=True)
    local_path = os.path.join(INPUT_DIR, mask_filename)
    
    with open(local_path, "wb") as f:
        f.write(content)
    
    # Sync to ALL active providers
    sync_status = "local_only"
    synced_count = 0
    
    try:
        service = get_provider_service(session)
        providers = await service.list_providers()
        
        # Filter enabled providers and construct worker URLs
        active_providers = []
        for p in providers:
            p_id = p.get("id") if isinstance(p, dict) else getattr(p, "id", None)
            enabled = p.get("enabled") if isinstance(p, dict) else getattr(p, "enabled", False)
            
            if not enabled or not p_id:
                continue
            
            # Construct worker URL: comfy-provider-{id}:8000
            worker_url = f"http://comfy-provider-{p_id}:8000"
            active_providers.append({"id": p_id, "worker_url": worker_url})
        
        if active_providers:
            async with aiohttp.ClientSession() as http:
                payload = {
                    "filename": mask_filename,
                    "content_base64": base64.b64encode(content).decode(),
                    "directory": "input"
                }
                
                for provider in active_providers:
                    worker_url = provider["worker_url"]
                    provider_id = provider["id"]
                    
                    try:
                        async with http.post(
                            f"{worker_url}/upload-file",
                            json=payload,
                            timeout=aiohttp.ClientTimeout(total=30)
                        ) as response:
                            if response.status == 200:
                                synced_count += 1
                                print(f"[Upload] ✓ Synced mask {mask_filename} to provider {provider_id}")
                    except Exception as e:
                        print(f"[Upload] Warning: Failed to sync mask to provider {provider_id}: {e}")
            
            if synced_count > 0:
                sync_status = "synced"
    except Exception as e:
        print(f"[Upload] Warning: Could not sync mask to providers: {e}")
    
    return {
        "status": "success",
        "filename": mask_filename,
        "path": f"input/{mask_filename}",
        "sync_status": sync_status,
        "synced_providers": synced_count
    }


@router.post("/api/batch/delete")
async def batch_delete_endpoint(req: BatchDeleteRequest):
    """Batch delete files."""
    import glob
    
    try:
        # Validate directory
        allowed_dirs = ["output", "models/checkpoints", "models/loras", "models/vae", "models/controlnet", "models/embeddings", "models/upscale_models", "models/hypernetworks", "models/aesthetics", "models/poses", "models/wildcards", "models/motion_modules"]
        if req.directory not in allowed_dirs:
            raise HTTPException(status_code=400, detail="Invalid directory")
        
        success_count = 0
        for filename in req.files:
            filename = filename.lstrip("/\\")

            # Handle output directory (supports hierarchical date-based folders)
            if req.directory == "output":
                # First try direct path
                try:
                    local_path = get_safe_path(OUTPUT_DIR, filename)
                except HTTPException:
                    print(f"[Delete] Security warning: Attempt to delete file outside output dir: {filename}")
                    continue
                
                if not os.path.exists(local_path):
                    # Search in date-based subdirectories (e.g., output/2025-12-07/filename.png)
                    pattern = os.path.join(OUTPUT_DIR, "**", filename)
                    matches = glob.glob(pattern, recursive=True)
                    # Filter out thumb directory
                    matches = [m for m in matches if "/thumb/" not in m]
                    if matches:
                        local_path = matches[0]
                    else:
                        print(f"[Delete] File not found: {filename}")
                        continue
                
                if os.path.exists(local_path):
                    try:
                        os.remove(local_path)
                        print(f"[Delete] Removed: {local_path}")
                        
                        # Also remove metadata sidecar if exists
                        meta_path = f"{local_path}.json"
                        if os.path.exists(meta_path):
                            os.remove(meta_path)
                        
                        # Remove thumbnail if exists
                        thumb_dir = os.path.join(os.path.dirname(local_path), "thumb")
                        thumb_path = os.path.join(thumb_dir, filename)
                        if os.path.exists(thumb_path):
                            os.remove(thumb_path)
                            
                        success_count += 1
                    except Exception as e:
                        print(f"[Delete] Failed to delete {filename}: {e}")
            else:
                # Handle model files
                try:
                    target_dir = os.path.join(CACHE_DIR, req.directory)
                    model_path = get_safe_path(target_dir, filename)
                except HTTPException:
                    print(f"[Delete] Security warning: Attempt to delete file outside model dir: {filename}")
                    continue

                if os.path.exists(model_path):
                    try:
                        os.remove(model_path)
                        success_count += 1
                    except Exception as e:
                        print(f"Failed to delete {filename}: {e}")
        
        return {"status": "success", "deleted": success_count, "total": len(req.files)}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Proxy endpoints for provider storage
@router.get("/api/files/proxy/{provider_id}/{path:path}")
async def proxy_file(
    provider_id: str,
    path: str,
    session: Session = Depends(get_session)
):
    """Proxy file from provider storage."""
    from infrastructure.providers import ModalProvider
    
    service = get_provider_service(session)
    provider_data = await service.get_provider(provider_id)
    
    provider = ModalProvider(provider_id, {
        "type": provider_data.type,
        "credentials": provider_data.credentials,
        "config": provider_data.config,
        "container_config": provider_data.container_config or {}
    })
    
    try:
        file_proxy = provider.get_file_proxy()
        content = await file_proxy.get_file(path)
        
        if path.endswith(('.png', '.jpg', '.jpeg', '.webp')):
            media_type = "image/png" if path.endswith('.png') else "image/jpeg"
        else:
            media_type = "application/octet-stream"
        
        return Response(content=content, media_type=media_type)
    
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


class BatchMetadataRequest(BaseModel):
    """Request model for batch metadata fetching."""
    paths: List[str]


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
                except:
                    return {"error": "metadata_read_failed"}
            else:
                return {"error": "metadata_not_found"}

    # Phase 1: Check direct paths and collect missing files
    for path in request.paths:
        try:
            # Normalize path
            if path.startswith("output/"):
                filename = path.replace("output/", "").lstrip("/\\")
            else:
                filename = path.lstrip("/\\")
            
            # Try direct path first
            try:
                full_path = get_safe_path(OUTPUT_DIR, filename)
            except HTTPException:
                results[path] = {"error": "invalid_path"}
                continue

            if os.path.exists(full_path):
                results[path] = _get_metadata_result(full_path)
            else:
                # Add to missing files list for batch search
                # Map original path -> basename (what we look for)
                missing_files_map[path] = os.path.basename(filename)
                    
        except Exception as e:
            results[path] = {"error": str(e)}
    
    # Phase 2: Single pass scan for missing files
    if missing_files_map:
        # Optimization: Scan OUTPUT_DIR once to find all missing files
        found_files = {}  # filename -> full_path
        target_filenames = set(missing_files_map.values())

        # Walk the directory
        for root, dirs, files in os.walk(OUTPUT_DIR):
            # Skip thumb directory for efficiency
            if "thumb" in dirs:
                dirs.remove("thumb")

            for f in files:
                if f in target_filenames:
                    found_files[f] = os.path.join(root, f)

            # Optimization: Stop if we found all files
            if len(found_files) == len(target_filenames):
                break

        # Fill results for missing files
        for path, filename in missing_files_map.items():
            if filename in found_files:
                full_path = found_files[filename]
                results[path] = _get_metadata_result(full_path)
            else:
                results[path] = {"error": "not_found"}

    return {
        "results": results,
        "total": len(request.paths),
        "found": sum(1 for r in results.values() if r.get("success"))
    }
