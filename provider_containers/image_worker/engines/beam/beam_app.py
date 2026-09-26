"""Beam.cloud Application for ComfyUI - GPU, Storage, and Download Split

Three deployments:
  - comfy_gpu: Realtime WebSocket for inference (RTX4090, checkpoint restore)
  - comfy_storage: ASGI for file operations (CPU only, cheap)
  - comfy_download: ASGI for model downloads (separate scaling)

Deploy:
    beam deploy beam_app.py:comfy_gpu
    beam deploy beam_app.py:comfy_storage
    beam deploy beam_app.py:comfy_download

    beta9 deploy beam_app.py:comfy_gpu
    beta9 deploy beam_app.py:comfy_storage
    beta9 deploy beam_app.py:comfy_download
"""
# beam is the CLI alias for the beta9 Python package
from beta9 import asgi, realtime, Image, Volume, QueueDepthAutoscaler, rest_api
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, Response
import os
import json
import logging
import subprocess
import time
# IMPORTANT: provider_core is a sibling package and must be present in the deploy
# source context. Deploying beam_app.py from only image_worker/engines/beam/ (without the
# provider_containers root) can fail with ModuleNotFoundError: provider_core.
from provider_core.downloads import pending_download_paths
from provider_core.utils import get_safe_path, is_model_file, is_transient_artifact
from provider_core.logging import get_logger

logger = get_logger("image_worker.beam.beam_app")
from provider_core.downloads import download_model_to_path
from provider_core.validation import (
    MIN_MODEL_SIZE,
    VALID_FILE_HEADERS,
)
from image_worker.comfy.workflow_executor import (
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
        "httpx",
        "aiofiles",
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
        "httpx",
        "aiofiles",
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
            logger.info("[ComfyUI] Server already running")
            return True
    except Exception:
        pass
    
    logger.info("[ComfyUI] Starting server via comfy-cli...")
    cmd = ["comfy", "launch", "--background", "--", "--listen", "0.0.0.0", "--port", str(_comfy_port)]
    _comfy_process = subprocess.Popen(cmd)
    
    logger.info("[ComfyUI] Waiting for server to be ready...")
    for i in range(120):
        try:
            response = requests.get(f"http://127.0.0.1:{_comfy_port}", timeout=2)
            if response.status_code == 200:
                logger.info("[ComfyUI] Server is ready!")
                return True
        except Exception:
            pass
        time.sleep(1)
    
    logger.warning("[ComfyUI] Warning - Server did not respond within 120 seconds")
    return False


def init_comfyui():
    """
    Pre-start ComfyUI when container boots.
    
    This runs during on_start and is captured by checkpoint_enabled,
    so cold starts will resume from this point with ComfyUI already running.
    """
    logger.info("[on_start] Pre-starting ComfyUI server...")
    
    # Ensure volume directories exist (symlinks point here)
    volume_dirs = ["/mnt/data/models", "/mnt/data/output", "/mnt/data/input"]
    for dir_path in volume_dirs:
        os.makedirs(dir_path, exist_ok=True)
        logger.info(f"[on_start] Ensured directory exists: {dir_path}")
    
    _ensure_comfyui_running()
    logger.info("[on_start] ComfyUI ready for inference")


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
        
        # Log what we're yielding
        status = update.get("status", "unknown")
        logger.info(f"[_run_inference_realtime] Yielding: status={status}")
        
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
    from provider_core.models import MODEL_DIRECTORIES
    dirs = ["/mnt/data/output", "/mnt/data/input", "/mnt/data/downloads"] + [f"/mnt/data/{d}" for d in MODEL_DIRECTORIES]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    return {"status": "success", "directories": dirs}


async def shared_download_model(data: dict):
    url = data.get("url")
    path = data.get("path")
    token = data.get("token")
    preview_url = data.get("preview_url")
    metadata = data.get("metadata")

    base_path = "/mnt/data"
    try:
        full_path = get_safe_path(base_path, path)
    except Exception as e:
        logger.error(f"[Download] Path traversal blocked: {e}")
        return {"status": "error", "message": "Invalid path"}

    import asyncio
    
    progress_dir = "/mnt/data/downloads"
    os.makedirs(progress_dir, exist_ok=True)
    safe_name = os.path.basename(path)
    progress_file = os.path.join(progress_dir, f"{safe_name}.json")
    
    last_progress_update = [0.0]
    
    def progress_callback(payload: Dict[str, Any]):
        status = payload.get("status")
        now = time.time()
        
        if status == "starting":
            percent, speed_str, eta_str, downloaded_str, total_str, msg = 0, "", "", "", "", ""
        elif status == "downloading":
            if now - last_progress_update[0] < 0.5:
                return
            last_progress_update[0] = now
            total_bytes = payload.get("total_bytes", 0) or 0
            downloaded_bytes = payload.get("downloaded_bytes", 0) or 0
            speed_mbps = payload.get("speed_mbps", 0.0) or 0.0
            eta_seconds = int(payload.get("eta_seconds", 0) or 0)
            percent = int(payload.get("percent", 0) or 0)
            
            downloaded_str = f"{downloaded_bytes / (1024 ** 2):.2f} MB"
            total_str = f"{total_bytes / (1024 ** 2):.2f} MB" if total_bytes > 0 else "Unknown"
            speed_str = f"{speed_mbps:.2f} MB/s"
            eta_str = f"{eta_seconds}s"
            msg = ""
        elif status == "success":
            percent, speed_str, eta_str, downloaded_str, total_str, msg = 100, "", "", "", "", "Download complete"
        elif status == "message":
            status = "error"
            percent, speed_str, eta_str, downloaded_str, total_str, msg = 0, "", "", "", "", payload.get("message", "Download failed")
        else:
            return
            
        try:
            with open(progress_file, "w") as f:
                json.dump({
                    "filename": safe_name,
                    "status": status,
                    "percent": percent,
                    "speed": speed_str,
                    "eta": eta_str,
                    "downloaded": downloaded_str,
                    "total": total_str,
                    "message": msg,
                    "updated_at": now
                }, f)
        except Exception:
            pass

    try:
        res = await asyncio.to_thread(
            download_model_to_path,
            url=url,
            full_path=full_path,
            path=path,
            token=token,
            hf_token=os.environ.get("HF_TOKEN"),
            civitai_token=os.environ.get("CIVITAI_TOKEN"),
            preview_url=preview_url,
            metadata=metadata,
            log=print,
            log_prefix="Download",
            progress_callback=progress_callback,
            validation_unknown_header_log_prefix="Validate",
        )
        
        if res.get("status") == "success":
            await asyncio.sleep(5)
            
        return res
    finally:
        if os.path.exists(progress_file):
            try:
                os.remove(progress_file)
            except Exception:
                pass

@storage_app.post("/download-model")
async def download_model(request: Request):
    """Download a model to the volume with shared validation pipeline."""
    return await shared_download_model(await request.json())


@storage_app.post("/list-models")
async def list_models(request: Request):
    """List models in a directory."""
    data = await request.json()
    directory = data.get("directory")
    if not directory:
        raise HTTPException(status_code=400, detail="directory is required")
    
    from image_worker.comfy.models_utils import list_models_with_metadata_internal
    files = await list_models_with_metadata_internal("/mnt/data", directory, compute_hashes=False)
    
    return {"files": files}


@storage_app.post("/delete-model")
async def delete_model(request: Request):
    import asyncio
    import shutil
    data = await request.json()
    path = data.get("path")
    full_path = get_safe_path("/mnt/data", path)

    def _do_delete():
        if not os.path.exists(full_path) and not list(pending_download_paths(full_path)):
            return False, f"Not found: {path}"
        try:
            if os.path.exists(full_path):
                if os.path.isdir(full_path):
                    shutil.rmtree(full_path)
                else:
                    os.remove(full_path)
            for stale in pending_download_paths(full_path):
                os.remove(stale)
            if not path.endswith((".json", ".preview.png", ".sha256")):
                base_path, _ = os.path.splitext(full_path)
                for side_file in [base_path + ".json", base_path + ".preview.png", full_path + ".sha256"]:
                    if os.path.exists(side_file):
                        os.remove(side_file)
            return True, f"Deleted {path}"
        except Exception as e:
            return False, str(e)

    success, message = await asyncio.to_thread(_do_delete)
    return {"success": success, "message": message}


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
    import asyncio
    import shutil
    data = await request.json()
    path = data.get("path")
    full_path = get_safe_path("/mnt/data", path)

    def _do_delete():
        if not os.path.exists(full_path):
            return False, f"Not found: {path}"
        if os.path.isdir(full_path):
            shutil.rmtree(full_path)
        else:
            os.remove(full_path)
        return True, f"Deleted {path}"
        
    success, message = await asyncio.to_thread(_do_delete)
    return {"success": success, "message": message}


@storage_app.post("/upload-file")
async def upload_file(request: Request):
    """Upload file."""
    data = await request.json()
    filename = data.get("filename")
    content_base64 = data.get("content_base64")
    directory = data.get("directory")
    if not directory:
        raise HTTPException(status_code=400, detail="directory is required")
    
    content = base64.b64decode(content_base64)
    full_path = get_safe_path("/mnt/data", f"{directory}/{filename}")
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    
    with open(full_path, "wb") as f:
        f.write(content)
    
    return {"success": True, "path": f"{directory}/{filename}", "size": len(content)}


@storage_app.post("/validate-models")
async def validate_models(request: Request):
    from provider_core.utils import get_safe_path
    from provider_core.validation import validate_downloaded_file
    import asyncio
    
    data = await request.json()
    directory = data.get("directory")
    if not directory:
        raise HTTPException(status_code=400, detail="directory is required")
    delete_invalid = data.get("delete_invalid", False)
    
    try:
        target_dir = get_safe_path("/mnt/data", directory)
    except Exception as e:
        return {"valid": [], "invalid": [], "partial": [], "total": 0, "message": f"Invalid directory: {e}"}

    if not os.path.exists(target_dir):
        return {"valid": [], "invalid": [], "partial": [], "total": 0}
    
    def _validate_dir():
        valid_models = []
        invalid_models = []
        partial_downloads = []
        with os.scandir(target_dir) as entries:
            for entry in entries:
                name = entry.name
                if not is_model_file(name):
                    continue
                if not entry.is_file():
                    continue
                full_path = entry.path
                if is_transient_artifact(name):
                    # A lock or an in-flight download is not a broken model.
                    # Deleting it here also deleted the model's .json and
                    # .preview.png sidecars (splitext("x.safetensors.lock") is
                    # "x.safetensors") and unlinked a held flock.
                    continue
                file_size = entry.stat().st_size
                validation = validate_downloaded_file(full_path)
                model_info = {
                    "name": name,
                    "size": file_size,
                    "size_mb": round(file_size / (1024 * 1024), 1),
                    "format": validation.get("format", "unknown")
                }
                if not validation["valid"]:
                    model_info["issues"] = [validation["error"]]
                    invalid_models.append(model_info)
                    if delete_invalid:
                        os.remove(full_path)
                        for ext in [".json", ".preview.png", ".sha256"]:
                            side_file = os.path.splitext(full_path)[0] + ext
                            if os.path.exists(side_file):
                                os.remove(side_file)
                else:
                    valid_models.append(model_info)
        return valid_models, invalid_models, partial_downloads

    valid_models, invalid_models, partial_downloads = await asyncio.to_thread(_validate_dir)
            
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

@storage_app.post("/validate-all-models")
async def validate_all_models(request: Request):
    """Validate all model directories in one batch call to avoid O(N) HTTP requests."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    delete_invalid = data.get("delete_invalid", False)
    
    # We create a dummy request for the child function
    class DummyRequest:
        def __init__(self, data):
            self._data = data
        async def json(self):
            return self._data

    from provider_core.models import MODEL_DIRECTORIES
    results = {"total_valid": 0, "total_invalid": 0, "total_partial": 0, "by_directory": {}}
    
    for directory in MODEL_DIRECTORIES:
        req = DummyRequest({"directory": directory, "delete_invalid": delete_invalid})
        res = await validate_models(req)
        
        dir_key = directory.replace("models/", "")
        results["by_directory"][dir_key] = {
            "valid": res.get("valid_count", 0),
            "invalid": res.get("invalid_count", 0),
            "partial": res.get("partial_count", 0),
        }
        results["total_valid"] += res.get("valid_count", 0)
        results["total_invalid"] += res.get("invalid_count", 0)
        results["total_partial"] += res.get("partial_count", 0)
        
    return results


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
            yield json.dumps({"status": "error", "message": f"Invalid JSON: {event[:100]}"})
            return
    
    workflow = event.get("workflow", {})
    
    if not workflow:
        yield json.dumps({"status": "error", "message": "No workflow provided"})
        return  # Exit generator early
    
    logger.info(f"[comfy_gpu] Received workflow with {len(workflow)} nodes")
    
    # Stream progress updates through WebSocket
    # Note: _run_inference_realtime yields JSON strings
    async for update_json in _run_inference_realtime(workflow):
        logger.info(f"[comfy_gpu] Sending update through WebSocket")
        yield update_json
    
    logger.info("[comfy_gpu] Inference complete")


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
    data = await request.json()
    res = await shared_download_model(data)
    if res.get("status") == "success":
        return {"status": "success", "path": data.get("path"), "size": res.get("size", 0)}
    return {"status": "error", "message": res.get("message", "Download failed")}


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
    autoscaler=QueueDepthAutoscaler(max_containers=DOWNLOAD_MAX_CONTAINERS, tasks_per_container=1)
)
def comfy_download():
    """Dedicated download endpoint for model downloads (separate scaling from storage)."""
    return download_app


# =============================================================================
# Extractor Deployment (CPU-only node mapping)
# =============================================================================

extractor_app = FastAPI(title="ComfyUI Extractor Server")

@extractor_app.get("/object_info")
async def get_object_info():
    import requests
    import subprocess
    import time
    
    port = 8189
    logger.info("[ComfyUINodeExtractor] Starting CPU-only server...")
    cmd = ["comfy", "launch", "--", "--listen", "0.0.0.0", "--port", str(port), "--cpu"]
    server_process = subprocess.Popen(cmd)
    
    # Wait for ready
    deadline = time.time() + 60
    ready = False
    while time.time() < deadline:
        try:
            response = requests.get(f"http://127.0.0.1:{port}", timeout=2)
            if response.status_code == 200:
                ready = True
                break
        except Exception:
            pass
        time.sleep(1)
        
    if not ready:
        server_process.kill()
        return {"error": "ComfyUI failed to start in CPU mode for extraction"}
        
    try:
        response = requests.get(f"http://127.0.0.1:{port}/object_info", timeout=60)
        response.raise_for_status()
        data = response.json()
        logger.info(f"[Extractor] Successfully extracted object_info ({len(data)} nodes).")
    finally:
        # Kill the server gracefully
        logger.info("[ComfyUINodeExtractor] Shutting down CPU server...")
        server_process.terminate()
        try:
            server_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server_process.kill()
        
    return data

@rest_api(
    name="comfyui-extractor",
    cpu=1,
    memory="4Gi",
    image=gpu_image,
    volumes=[Volume(VOL_NAME, mount_path="/mnt/data")],
    timeout=300,
    keep_warm_seconds=0,
)
def comfy_extractor():
    """CPU endpoint for extracting ComfyUI node definitions."""
    return extractor_app
