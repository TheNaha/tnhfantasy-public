"""Beam.cloud Application for ComfyUI - GPU, Storage, and Download Split

Three deployments:
  - comfy_gpu: Realtime WebSocket for inference (RTX4090, checkpoint restore)
  - comfy_storage: ASGI for file operations (CPU only, cheap)
  - comfy_download: ASGI for model downloads (separate scaling)

Deploy:
  beam deploy beam_app.py:comfy_gpu
  beam deploy beam_app.py:comfy_storage
  beam deploy beam_app.py:comfy_download
"""
from beam import asgi, realtime, Image, Volume, QueueDepthAutoscaler
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, Response
import os
import json
import subprocess
import time
from provider_core.utils import get_safe_path
from provider_core.validation import (
    MIN_MODEL_SIZE,
    VALID_FILE_HEADERS,
    validate_downloaded_file,
)
from provider_core.workflow_executor import (
    IMAGE_FETCH_VIEW_API,
    execute_comfy_workflow,
)
from typing import Dict, Any
import base64


# =============================================================================
# Per-Deployment Configuration from Environment (set during beam deploy)
# =============================================================================

# Shared
VOL_NAME = os.getenv("BEAM_VOLUME_NAME", "comfy-storage")

# GPU deployment settings
GPU_TYPE = os.getenv("BEAM_GPU_TYPE", "RTX4090")
GPU_CPU = int(os.getenv("BEAM_GPU_CPU", "2"))
GPU_MEMORY = os.getenv("BEAM_GPU_MEMORY", "16Gi")
GPU_TIMEOUT = int(os.getenv("BEAM_GPU_TIMEOUT", "600"))
GPU_KEEP_WARM = int(os.getenv("BEAM_GPU_KEEP_WARM", "40"))
GPU_CONCURRENT = int(os.getenv("BEAM_GPU_CONCURRENT", "1"))

# Storage deployment settings
STORAGE_CPU = int(os.getenv("BEAM_STORAGE_CPU", "3"))
STORAGE_MEMORY = os.getenv("BEAM_STORAGE_MEMORY", "4Gi")
STORAGE_TIMEOUT = int(os.getenv("BEAM_STORAGE_TIMEOUT", "600"))
STORAGE_KEEP_WARM = int(os.getenv("BEAM_STORAGE_KEEP_WARM", "10"))
STORAGE_CONCURRENT = int(os.getenv("BEAM_STORAGE_CONCURRENT", "10"))
STORAGE_MAX_CONTAINERS = int(os.getenv("BEAM_STORAGE_MAX_CONTAINERS", "1"))

# Download deployment settings (separate from storage for independent scaling)
DOWNLOAD_CPU = int(os.getenv("BEAM_DOWNLOAD_CPU", "2"))
DOWNLOAD_MEMORY = os.getenv("BEAM_DOWNLOAD_MEMORY", "4Gi")
DOWNLOAD_TIMEOUT = int(os.getenv("BEAM_DOWNLOAD_TIMEOUT", "1800"))
DOWNLOAD_KEEP_WARM = int(os.getenv("BEAM_DOWNLOAD_KEEP_WARM", "5"))
DOWNLOAD_CONCURRENT = int(os.getenv("BEAM_DOWNLOAD_CONCURRENT", "5"))
DOWNLOAD_MAX_CONTAINERS = int(os.getenv("BEAM_DOWNLOAD_MAX_CONTAINERS", "3"))



# =============================================================================
# GPU Image (ComfyUI with full stack)
# =============================================================================
gpu_image = (
    Image(python_version="python3.12")
    .add_commands([
        "apt-get update && apt-get install -y git libgl1-mesa-glx libglib2.0-0"
    ])
    .add_python_packages([
        "comfy-cli",
        "fastapi", 
        "websockets", 
        "uvicorn", 
        "requests",
        "torch",
        "torchvision",
        "torchaudio",
    ])
    .add_commands([
        "comfy --skip-prompt install --fast-deps --nvidia",
        "comfy node install --fast-deps comfyui-manager",
        "comfy node install --fast-deps comfyui-impact-pack",
        "comfy node install --fast-deps comfyui_controlnet_aux",
        "comfy node install --fast-deps comfyui-animatediff-evolved",
        "rm -rf /root/comfy/ComfyUI/models /root/comfy/ComfyUI/output /root/comfy/ComfyUI/input || true",
        "ln -sf /mnt/data/models /root/comfy/ComfyUI/models",
        "ln -sf /mnt/data/output /root/comfy/ComfyUI/output",
        "ln -sf /mnt/data/input /root/comfy/ComfyUI/input",
    ])
    .build_with_gpu(gpu="RTX4090")
)


# =============================================================================
# CPU Image (lightweight for storage ops)
# =============================================================================
cpu_image = (
    Image(python_version="python3.12")
    .add_python_packages([
        "fastapi", 
        "uvicorn", 
        "requests",
        "safetensors",
    ])
)


# =============================================================================
# GPU Server State & Helpers
# =============================================================================
_comfy_process = None
_comfy_port = 8188


def _ensure_comfyui_running():
    """Ensure ComfyUI server is running."""
    global _comfy_process
    import requests
    
    try:
        response = requests.get(f"http://127.0.0.1:{_comfy_port}", timeout=2)
        if response.status_code == 200:
            print("[ComfyUI] Server already running")
            return True
    except:
        pass
    
    print("[ComfyUI] Starting server via comfy-cli...")
    cmd = ["comfy", "launch", "--background", "--", "--listen", "0.0.0.0", "--port", str(_comfy_port)]
    _comfy_process = subprocess.Popen(cmd)
    
    print("[ComfyUI] Waiting for server to be ready...")
    for i in range(120):
        try:
            response = requests.get(f"http://127.0.0.1:{_comfy_port}", timeout=2)
            if response.status_code == 200:
                print("[ComfyUI] Server is ready!")
                return True
        except:
            pass
        time.sleep(1)
    
    print("[ComfyUI] Warning - Server did not respond within 120 seconds")
    return False


def _validate_download(path: str, total_size: int = 0) -> Dict[str, Any]:
    """
    Validate a downloaded file using strict checks.
    
    Args:
        path: Path to the file to validate
        total_size: Expected size from Content-Length (0 if unknown)
        
    Returns:
        Dict with validation result. If valid=False, contains error message.
    """
    return validate_downloaded_file(
        path,
        total_size,
        unknown_header_log_prefix="Validate",
    )


def init_comfyui():
    """
    Pre-start ComfyUI when container boots.
    
    This runs during on_start and is captured by checkpoint_enabled,
    so cold starts will resume from this point with ComfyUI already running.
    """
    print("[on_start] Pre-starting ComfyUI server...")
    
    # Ensure volume directories exist (symlinks point here)
    volume_dirs = ["/mnt/data/models", "/mnt/data/output", "/mnt/data/input"]
    for dir_path in volume_dirs:
        os.makedirs(dir_path, exist_ok=True)
        print(f"[on_start] Ensured directory exists: {dir_path}")
    
    _ensure_comfyui_running()
    print("[on_start] ComfyUI ready for inference")


async def _execute_workflow(workflow_json: Dict[str, Any], port: int = 8188):
    """Execute a ComfyUI workflow and stream progress updates."""
    async for update in execute_comfy_workflow(
        workflow_json,
        port,
        image_fetch_mode=IMAGE_FETCH_VIEW_API,
        history_delay_seconds=0.5,
    ):
        yield update


# =============================================================================
# GPU Realtime Handler (WebSocket for long-running inference)
# Note: The @realtime decorator is defined at the bottom of this file.
# This section contains the inference logic used by the realtime handler.
# =============================================================================

async def _run_inference_realtime(workflow: Dict[str, Any]):
    """
    Execute ComfyUI workflow and yield progress updates for WebSocket streaming.
    
    This is an async generator that yields JSON strings.
    The @realtime handler will send each yielded string through the WebSocket.
    """
    # Ensure ComfyUI is running (should already be from on_start/checkpoint)
    _ensure_comfyui_running()
    
    async for update in _execute_workflow(workflow, _comfy_port):
        if update.get("status") == "success" and "images" in update:
            # Base64 encode images for WebSocket transfer
            for img in update["images"]:
                if "data" in img and isinstance(img["data"], bytes):
                    img["data"] = base64.b64encode(img["data"]).decode('utf-8')
                    img["_base64_encoded"] = True
        
        # Log what we're yielding
        status = update.get("status", "unknown")
        print(f"[_run_inference_realtime] Yielding: status={status}")
        
        # Yield update as JSON string (Beam realtime expects strings)
        yield json.dumps(update)


# =============================================================================
# CPU FastAPI App (Storage Operations)
# =============================================================================
storage_app = FastAPI(title="ComfyUI Storage Server")


@storage_app.get("/health")
async def storage_health():
    return {"status": "healthy", "type": "storage"}


@storage_app.post("/setup")
async def setup():
    """Initialize volume directories."""
    dirs = [
        "/mnt/data/models/checkpoints", "/mnt/data/models/loras", "/mnt/data/models/vae",
        "/mnt/data/models/controlnet", "/mnt/data/models/unet", "/mnt/data/models/clip",
        "/mnt/data/models/embeddings", "/mnt/data/models/upscale_models",
        "/mnt/data/models/hypernetworks", "/mnt/data/models/motion_modules",
        "/mnt/data/output", "/mnt/data/input", "/mnt/data/downloads",
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    return {"status": "success", "directories": dirs}


@storage_app.post("/download-model")
async def download_model(request: Request):
    """Download a model to the volume with progress tracking and safe temp file pattern."""
    import requests
    import time
    
    data = await request.json()
    url = data.get("url")
    path = data.get("path")
    token = data.get("token")
    preview_url = data.get("preview_url")
    metadata = data.get("metadata")
    
    from provider_core.utils import get_safe_path

    base_path = "/mnt/data"
    try:
        full_path = get_safe_path(base_path, path)
    except Exception as e:
        logger.error(f"[Download] Path traversal blocked: {e}")
        return {"status": "error", "error": "Invalid path"}

    temp_path = full_path + ".downloading"  # Temp file suffix
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    
    headers = {}
    hf_token = token if token and token.startswith("hf_") else os.environ.get("HF_TOKEN")
    civitai_token = token if token and not token.startswith("hf_") else os.environ.get("CIVITAI_TOKEN")

    if "huggingface.co" in url and hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"
    elif "civitai.com" in url and civitai_token:
        url += f"&token={civitai_token}" if "?" in url else f"?token={civitai_token}"

    try:
        print(f"[Download] Starting: {path}")
        print(f"[Download] URL: {url[:80]}...")
        print(f"[Download] Using temp file: {os.path.basename(temp_path)}")
        
        response = requests.get(url, stream=True, headers=headers)
        response.raise_for_status()
        total_size = int(response.headers.get('content-length', 0))
        
        # Format size for display
        if total_size > 0:
            size_mb = total_size / (1024 * 1024)
            size_gb = total_size / (1024 * 1024 * 1024)
            size_str = f"{size_gb:.2f} GB" if size_gb >= 1 else f"{size_mb:.1f} MB"
            print(f"[Download] Size: {size_str}")
        else:
            print(f"[Download] Size: Unknown")
        
        # Download to TEMP FILE (not final path)
        downloaded = 0
        start_time = time.time()
        last_log_percent = 0
        chunk_size = 1024 * 1024  # 1 MB chunks
        
        with open(temp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size):
                f.write(chunk)
                downloaded += len(chunk)
                
                # Log progress every 10%
                if total_size > 0:
                    percent = int((downloaded / total_size) * 100)
                    if percent >= last_log_percent + 10:
                        elapsed = time.time() - start_time
                        speed_mbps = (downloaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                        remaining = total_size - downloaded
                        eta_seconds = remaining / (downloaded / elapsed) if elapsed > 0 and downloaded > 0 else 0
                        
                        # Format ETA
                        if eta_seconds > 60:
                            eta_str = f"{int(eta_seconds / 60)}m {int(eta_seconds % 60)}s"
                        else:
                            eta_str = f"{int(eta_seconds)}s"
                        
                        print(f"[Download] {percent}% - {speed_mbps:.1f} MB/s - ETA: {eta_str}")
                        last_log_percent = percent
        
        # Final stats
        elapsed = time.time() - start_time
        speed_mbps = (downloaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0
        print(f"[Download] ✓ Download complete (temp file)")
        print(f"[Download]   Size: {downloaded / (1024*1024):.1f} MB in {elapsed:.1f}s ({speed_mbps:.1f} MB/s)")
        
        # ========================================
        # VALIDATION: Check if download is valid
        # ========================================
        validation = _validate_download(temp_path, total_size)
        
        if not validation["valid"]:
            print(f"[Download] ✗ VALIDATION FAILED:")
            for err in validation.get("errors", [validation["error"]]):
                print(f"[Download]   - {err}")
            
            # Delete invalid temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)
                print(f"[Download] ✗ Deleted invalid temp file")
            
            return {"status": "error", "message": f"Validation failed: {validation['error']}"}
        
        detected_format = validation["format"]
        actual_size = validation["size"]
        print(f"[Download] ✓ Validation passed: {detected_format}")
        
        # ========================================
        # ATOMIC RENAME: Move temp to final path
        # ========================================
        # Remove old file if exists
        if os.path.exists(full_path):
            os.remove(full_path)
        
        # Atomic rename (instant operation)
        os.rename(temp_path, full_path)
        print(f"[Download] ✓ Moved to final path: {path}")
        # ========================================
        
        if metadata:
            with open(os.path.splitext(full_path)[0] + ".json", "w") as f:
                json.dump(metadata, f)
        
        if preview_url:
            try:
                print(f"[Download] Fetching preview image...")
                pr = requests.get(preview_url, timeout=30)
                if pr.status_code == 200:
                    with open(os.path.splitext(full_path)[0] + ".preview.png", "wb") as f:
                        f.write(pr.content)
                    print(f"[Download] ✓ Preview saved")
            except Exception as pe:
                print(f"[Download] ✗ Preview failed: {pe}")
        
        return {
            "status": "success", 
            "path": path, 
            "size": actual_size, 
            "speed_mbps": round(speed_mbps, 1), 
            "format": detected_format,
            "validated": True
        }
        
    except Exception as e:
        print(f"[Download] ✗ Error: {e}")
        # Clean up temp file on error
        if os.path.exists(temp_path):
            os.remove(temp_path)
            print(f"[Download] ✗ Cleaned up temp file")
        return {"status": "error", "message": str(e)}


@storage_app.post("/list-models")
async def list_models(request: Request):
    """List models in a directory."""
    data = await request.json()
    directory = data.get("directory", "models/checkpoints")
    
    from provider_core.utils import get_safe_path
    try:
        target_dir = get_safe_path("/mnt/data", directory)
    except Exception:
        print(f"[ListModels] Path traversal blocked: {directory}")
        return {"files": []}

    if not os.path.exists(target_dir):
        return {"files": []}
        
    entries = os.listdir(target_dir)
    files = []
    entry_set = set(entries)
    
    for name in entries:
        if name.endswith('.json') or name.endswith('.preview.png'):
            continue
        full_path = os.path.join(target_dir, name)
        if not os.path.isfile(full_path):
            continue
            
        file_data = {"name": name, "type": "file", "size": os.path.getsize(full_path)}
        
        preview_name = f"{os.path.splitext(name)[0]}.preview.png"
        if preview_name in entry_set:
            file_data["preview"] = f"/api/view/{directory}/{preview_name}"
            
        meta_name = f"{os.path.splitext(name)[0]}.json"
        if meta_name in entry_set:
            try:
                with open(os.path.join(target_dir, meta_name), 'r') as f:
                    file_data["metadata"] = json.load(f)
            except:
                pass
                
        files.append(file_data)
    
    return {"files": files}


@storage_app.post("/delete-model")
async def delete_model(request: Request):
    """Delete a model."""
    data = await request.json()
    path = data.get("path")
    full_path = get_safe_path("/mnt/data", path)
    
    if not os.path.exists(full_path):
        return {"success": False, "message": f"Not found: {path}"}
    
    try:
        os.remove(full_path)
        for ext in [".json", ".preview.png"]:
            side_file = os.path.splitext(full_path)[0] + ext
            if os.path.exists(side_file):
                os.remove(side_file)
        return {"success": True, "message": f"Deleted {path}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@storage_app.post("/get-file")
async def get_file(request: Request):
    """Get file contents."""
    data = await request.json()
    path = data.get("path")
    full_path = get_safe_path("/mnt/data", path)
    
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail=f"Not found: {path}")
    
    with open(full_path, "rb") as f:
        content = f.read()

    return Response(content=content, media_type="application/octet-stream")


@storage_app.post("/delete-file")
async def delete_file(request: Request):
    """Delete file."""
    data = await request.json()
    path = data.get("path")
    full_path = get_safe_path("/mnt/data", path)
    
    if not os.path.exists(full_path):
        return {"success": False, "message": f"Not found: {path}"}
    
    os.remove(full_path)
    return {"success": True, "message": f"Deleted {path}"}


@storage_app.post("/upload-file")
async def upload_file(request: Request):
    """Upload file."""
    data = await request.json()
    filename = data.get("filename")
    content_base64 = data.get("content_base64")
    directory = data.get("directory", "input")
    
    content = base64.b64decode(content_base64)
    dir_path = get_safe_path("/mnt/data", directory)
    os.makedirs(dir_path, exist_ok=True)
    
    with open(get_safe_path(dir_path, filename), "wb") as f:
        f.write(content)
    
    return {"success": True, "path": f"{directory}/{filename}", "size": len(content)}


@storage_app.post("/validate-models")
async def validate_models(request: Request):
    """
    Validate all models in a directory for reconciliation.
    Checks: minimum size, magic bytes, partial downloads.
    Returns: valid models, invalid models (to redownload), partial downloads (to clean up).
    """
    from provider_core.utils import get_safe_path

    data = await request.json()
    directory = data.get("directory", "models/checkpoints")
    delete_invalid = data.get("delete_invalid", False)  # If True, auto-delete invalid files
    
    try:
        target_dir = get_safe_path("/mnt/data", directory)
    except Exception as e:
        return {"valid": [], "invalid": [], "partial": [], "total": 0, "error": f"Invalid directory: {e}"}

    if not os.path.exists(target_dir):
        return {"valid": [], "invalid": [], "partial": [], "total": 0}
    
    # Magic bytes for validation
    VALID_HEADERS = VALID_FILE_HEADERS
    
    valid_models = []
    invalid_models = []
    partial_downloads = []
    
    entries = os.listdir(target_dir)
    
    for name in entries:
        # Skip metadata files
        if name.endswith(('.json', '.preview.png', '.txt', '.yaml', '.yml')):
            continue
        
        full_path = os.path.join(target_dir, name)
        
        if not os.path.isfile(full_path):
            continue
        
        # Check for partial downloads
        if name.endswith('.downloading'):
            partial_downloads.append({
                "name": name,
                "size": os.path.getsize(full_path),
                "issue": "Incomplete download (temp file)"
            })
            if delete_invalid:
                os.remove(full_path)
                print(f"[Validate] Deleted partial: {name}")
            continue
        
        file_size = os.path.getsize(full_path)
        issues = []
        detected_format = "unknown"
        should_delete = False  # Only delete files with CLEAR problems
        
        # Size check - too small files are definitely broken
        if file_size < MIN_MODEL_SIZE:
            issues.append(f"Too small: {file_size} bytes")
            should_delete = True  # Clear problem: file too small
        
        # Magic bytes check
        if file_size >= 16:
            with open(full_path, 'rb') as f:
                header = f.read(16)
            
            header_valid = False
            for magic, fmt in VALID_HEADERS.items():
                if header.startswith(magic):
                    header_valid = True
                    detected_format = fmt
                    break
            
            if not header_valid:
                # Check for HTML error pages
                if b'<html' in header.lower() or b'<!doctype' in header.lower():
                    issues.append("HTML content (auth error?)")
                    should_delete = True  # Clear problem: HTML instead of model
                else:
                    # Unknown format - log but DON'T delete (could be valid format we don't recognize)
                    detected_format = f"unknown ({header[:4].hex()})"
                    # NOT adding to issues - unknown format is not a problem
        
        # Safetensors integrity check - validates the header structure
        # This catches corrupted files that pass magic byte checks but fail to load
        # NOTE: We parse the header manually since safe_open(framework='pt') requires torch
        if name.endswith('.safetensors') and file_size >= MIN_MODEL_SIZE and not issues:
            try:
                import struct
                with open(full_path, 'rb') as f:
                    # Safetensors format: 8-byte header size (little-endian u64) + JSON header
                    header_size_bytes = f.read(8)
                    if len(header_size_bytes) < 8:
                        raise ValueError("File too small for safetensors header")
                    header_size = struct.unpack('<Q', header_size_bytes)[0]
                    
                    # Sanity check - header shouldn't be bigger than the file
                    if header_size > file_size - 8:
                        raise ValueError(f"Invalid header size: {header_size} > {file_size - 8}")
                    
                    # Read and parse the JSON header
                    header_bytes = f.read(header_size)
                    header = json.loads(header_bytes)
                    
                    # Verify it has expected structure (__metadata__ is optional, but should have tensor info)
                    if not isinstance(header, dict):
                        raise ValueError("Header is not a dict")
            except Exception as e:
                error_msg = str(e)
                # Truncate very long error messages
                if len(error_msg) > 100:
                    error_msg = error_msg[:100] + "..."
                issues.append(f"Safetensors corrupted: {error_msg}")
                should_delete = True
                print(f"[Validate] Corrupted safetensors: {name} - {error_msg}")
        
        model_info = {
            "name": name,
            "size": file_size,
            "size_mb": round(file_size / (1024 * 1024), 1),
            "format": detected_format
        }
        
        if issues:
            model_info["issues"] = issues
            invalid_models.append(model_info)
            
            # Only delete if we're sure it's broken (not just unknown format)
            if delete_invalid and should_delete:
                os.remove(full_path)
                # Also delete sidecar files
                for ext in [".json", ".preview.png"]:
                    side_file = os.path.splitext(full_path)[0] + ext
                    if os.path.exists(side_file):
                        os.remove(side_file)
                print(f"[Validate] Deleted invalid: {name} - {issues}")
        else:
            valid_models.append(model_info)
    
    print(f"[Validate] {directory}: {len(valid_models)} valid, {len(invalid_models)} invalid, {len(partial_downloads)} partial")
    
    return {
        "directory": directory,
        "total": len(valid_models) + len(invalid_models) + len(partial_downloads),
        "valid": valid_models,
        "valid_count": len(valid_models),
        "invalid": invalid_models,
        "invalid_count": len(invalid_models),
        "partial": partial_downloads,
        "partial_count": len(partial_downloads),
        "deleted": delete_invalid
    }


# =============================================================================
# Deployment Entry Points
# =============================================================================

@realtime(
    name="comfy-gpu",
    cpu=GPU_CPU,
    memory=GPU_MEMORY,
    gpu=GPU_TYPE,
    image=gpu_image,
    volumes=[Volume(VOL_NAME, mount_path="/mnt/data")],
    timeout=GPU_TIMEOUT,
    keep_warm_seconds=GPU_KEEP_WARM,
    concurrent_requests=GPU_CONCURRENT,
    on_start=init_comfyui,
    checkpoint_enabled=True,  # GPU memory snapshot for fast cold starts
)
async def comfy_gpu(event):
    """
    GPU endpoint for inference via WebSocket (realtime).
    
    Uses checkpoint restore for fast cold starts - ComfyUI is already
    loaded and ready when the container resumes from checkpoint.
    
    Event format: {"workflow": {...}}
    Yields: Progress updates through WebSocket
    Returns: Final {"status": "success", "images": [...]}
    """
    # Parse event if it's a string (WebSocket sends raw JSON)
    if isinstance(event, str):
        try:
            event = json.loads(event)
        except json.JSONDecodeError:
            yield {"status": "error", "message": f"Invalid JSON: {event[:100]}"}
            return
    
    workflow = event.get("workflow", {})
    
    if not workflow:
        yield {"status": "error", "message": "No workflow provided"}
        return  # Exit generator early
    
    print(f"[comfy_gpu] Received workflow with {len(workflow)} nodes")
    
    # Stream progress updates through WebSocket
    # Note: _run_inference_realtime yields JSON strings
    async for update_json in _run_inference_realtime(workflow):
        print(f"[comfy_gpu] Sending update through WebSocket")
        yield update_json
    
    print("[comfy_gpu] Inference complete")


@asgi(
    name="comfy-storage",
    cpu=STORAGE_CPU,
    memory=STORAGE_MEMORY,
    image=cpu_image,
    volumes=[Volume(VOL_NAME, mount_path="/mnt/data")],
    timeout=STORAGE_TIMEOUT,
    keep_warm_seconds=STORAGE_KEEP_WARM,
    concurrent_requests=STORAGE_CONCURRENT,
    workers=3,
    autoscaler=QueueDepthAutoscaler(max_containers=STORAGE_MAX_CONTAINERS, tasks_per_container=STORAGE_CONCURRENT)
)
def comfy_storage():
    """CPU endpoint for storage operations (list, delete, validate - cheap!)."""
    return storage_app


# =============================================================================
# Download Deployment (Separate from storage for independent scaling)
# =============================================================================

# Create download-specific FastAPI app
download_app = FastAPI(title="ComfyUI Download Server")


@download_app.get("/health")
async def download_health():
    return {"status": "healthy", "type": "download"}


@download_app.post("/download-model")
async def download_model_endpoint(request: Request):
    """Download a model - delegated from main storage app for separate scaling."""
    import requests
    
    data = await request.json()
    url = data.get("url")
    path = data.get("path")
    token = data.get("token")
    preview_url = data.get("preview_url")
    metadata = data.get("metadata")
    
    from provider_core.utils import get_safe_path

    base_path = "/mnt/data"
    try:
        full_path = get_safe_path(base_path, path)
    except Exception as e:
        logger.error(f"[Download] Path traversal blocked: {e}")
        return {"status": "error", "error": "Invalid path"}

    temp_path = full_path + ".downloading"
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    
    headers = {}
    hf_token = token if token and token.startswith("hf_") else os.environ.get("HF_TOKEN")
    civitai_token = token if token and not token.startswith("hf_") else os.environ.get("CIVITAI_TOKEN")

    if "huggingface.co" in url and hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"
    elif "civitai.com" in url and civitai_token:
        url += f"&token={civitai_token}" if "?" in url else f"?token={civitai_token}"

    try:
        print(f"[Download] Starting: {path}")
        print(f"[Download] URL: {url[:80]}...")
        
        response = requests.get(url, stream=True, headers=headers)
        response.raise_for_status()
        total_size = int(response.headers.get('content-length', 0))
        
        downloaded = 0
        start_time = time.time()
        chunk_size = 1024 * 1024  # 1 MB chunks
        
        with open(temp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size):
                f.write(chunk)
                downloaded += len(chunk)
        
        elapsed = time.time() - start_time
        speed_mbps = (downloaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0
        print(f"[Download] ✓ Complete: {downloaded / (1024*1024):.1f} MB in {elapsed:.1f}s ({speed_mbps:.1f} MB/s)")
        
        # ========================================
        # VALIDATION
        # ========================================
        validation = _validate_download(temp_path, total_size)
        
        if not validation["valid"]:
            print(f"[Download] ✗ VALIDATION FAILED: {validation['error']}")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return {"status": "error", "message": f"Validation failed: {validation['error']}"}
            
        print(f"[Download] ✓ Validation passed: {validation.get('format', 'unknown')}")
        
        # Atomic rename
        if os.path.exists(full_path):
            os.remove(full_path)
        os.rename(temp_path, full_path)
        
        # Save metadata if provided
        if metadata:
            with open(os.path.splitext(full_path)[0] + ".json", "w") as f:
                json.dump(metadata, f)
        
        # Fetch preview if provided
        if preview_url:
            try:
                pr = requests.get(preview_url, timeout=30)
                if pr.status_code == 200:
                    with open(os.path.splitext(full_path)[0] + ".preview.png", "wb") as f:
                        f.write(pr.content)
            except:
                pass
        
        return {"status": "success", "path": path, "size": downloaded}
        
    except Exception as e:
        print(f"[Download] ✗ Error: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return {"status": "error", "message": str(e)}


@asgi(
    name="comfy-download",
    cpu=DOWNLOAD_CPU,
    memory=DOWNLOAD_MEMORY,
    image=cpu_image,
    volumes=[Volume(VOL_NAME, mount_path="/mnt/data")],
    timeout=DOWNLOAD_TIMEOUT,
    keep_warm_seconds=DOWNLOAD_KEEP_WARM,
    concurrent_requests=1,
    workers=1,
    autoscaler=QueueDepthAutoscaler(max_containers=DOWNLOAD_CONCURRENT, tasks_per_container=1)
)
def comfy_download():
    """Dedicated download endpoint for model downloads (separate scaling from storage)."""
    return download_app
