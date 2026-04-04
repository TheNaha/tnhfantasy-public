import modal
import subprocess
import time
import logging

import os
import json
from typing import Dict, Any
from pathlib import Path

# IMPORTANT: provider_core is a sibling package. Modal cloud functions can fail
# to import this module unless provider_core is explicitly packaged into the
# image (see image_base.add_local_dir below).
from provider_core.utils import get_safe_path
from provider_core.downloads import download_model_to_path
from provider_core.validation import (
    MIN_MODEL_SIZE,
    VALID_FILE_HEADERS,
)
from provider_core.workflow_executor import (
    IMAGE_FETCH_FILESYSTEM,
    execute_comfy_workflow,
)

# Configure logging for Modal functions
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s %(name)s: %(message)s'
)
logger = logging.getLogger("modal_app")


def _resolve_provider_core_local_path() -> Path:
    """Resolve provider_core source path for Modal image packaging."""
    candidates = [
        Path(__file__).parent / "provider_core",
        Path(__file__).parent.parent / "provider_core",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise RuntimeError("provider_core source directory not found for modal image build")


PROVIDER_CORE_LOCAL_PATH = _resolve_provider_core_local_path()

# =============================================================================
# Per-Function Configuration from Environment (set during modal deploy)
# =============================================================================

# ComfyUI GPU function settings
COMFYUI_GPU_TYPE = os.getenv("MODAL_GPU_TYPE", "L4")
COMFYUI_CPU = int(os.getenv("MODAL_GPU_CPU", "2"))
COMFYUI_TIMEOUT = int(os.getenv("MODAL_GPU_TIMEOUT", "600"))
COMFYUI_MAX_CONTAINERS = int(os.getenv("MODAL_GPU_MAX_CONTAINERS", "1"))
COMFYUI_SCALEDOWN = int(os.getenv("MODAL_GPU_SCALEDOWN", "40"))
COMFYUI_SCALEDOWN_SNAPSHOT = int(os.getenv("MODAL_GPU_SCALEDOWN_SNAPSHOT", "40"))

# Download function settings
DOWNLOAD_TIMEOUT = int(os.getenv("MODAL_DOWNLOAD_TIMEOUT", "1800"))
DOWNLOAD_MAX_CONTAINERS = int(os.getenv("MODAL_DOWNLOAD_MAX_CONTAINERS", "5"))

# Storage function settings
STORAGE_TIMEOUT = int(os.getenv("MODAL_STORAGE_TIMEOUT", "300"))
STORAGE_MAX_CONTAINERS = int(os.getenv("MODAL_STORAGE_MAX_CONTAINERS", "1"))
STORAGE_SCALEDOWN = int(os.getenv("MODAL_STORAGE_SCALEDOWN", "5"))

# Validate function settings
VALIDATE_TIMEOUT = int(os.getenv("MODAL_VALIDATE_TIMEOUT", "600"))
VALIDATE_MAX_CONTAINERS = int(os.getenv("MODAL_VALIDATE_MAX_CONTAINERS", "1"))

# Volume name (allows different volumes per provider)
VOLUME_NAME = os.getenv("MODAL_VOLUME_NAME", "comfy-storage")

# Define the Modal Stub
app = modal.App("comfy-modal-stack")

# Define the Volume for persistent storage
vol = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

# =============================================================================
# Base Image (shared between stable and snapshot modes)
# Uses comfy-cli for ALL operations: installation, custom nodes, launching
# =============================================================================
image_base = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "libgl1-mesa-glx", "libglib2.0-0")
    .uv_pip_install( "comfy-cli", "fastapi", "websockets", "uvicorn", "requests", "safetensors",)
    # Ensure shared provider_core utilities are present in cloud runtime.
    .add_local_dir(
        local_path=PROVIDER_CORE_LOCAL_PATH,
        remote_path="/root/provider_core",
        copy=True,
    )
    # Install ComfyUI using comfy-cli
    .run_commands("comfy --skip-prompt install --fast-deps --nvidia")
    # Install Custom Nodes via comfy-cli registry
    # See: https://registry.comfy.org/
    .run_commands(
        "comfy node install --fast-deps comfyui-manager",
        "comfy node install --fast-deps comfyui-impact-pack",
        "comfy node install --fast-deps comfyui_controlnet_aux",
        "comfy node install --fast-deps comfyui-animatediff-evolved",
        "comfy --help"
    )
    # Create symlinks to volume for models, output, and input
    .run_commands(
        "rm -rf /root/comfy/ComfyUI/models /root/comfy/ComfyUI/output /root/comfy/ComfyUI/input",
        "ln -s /mnt/data/models /root/comfy/ComfyUI/models",
        "ln -s /mnt/data/output /root/comfy/ComfyUI/output",
        "ln -s /mnt/data/input /root/comfy/ComfyUI/input"
    )
)

# Image for stable mode (no snapshot helper needed)
image = image_base

# Image for snapshot mode (includes memory_snapshot_helper custom node)
image_snapshot = image_base.add_local_dir(
    local_path=Path(__file__).parent / "memory_snapshot_helper",
    remote_path="/root/comfy/ComfyUI/custom_nodes/memory_snapshot_helper",
    copy=True,
)


# =============================================================================
# Shared workflow execution logic
# =============================================================================
async def _execute_workflow(workflow_json: Dict[str, Any], port: int = 8188):
    """
    Execute a ComfyUI workflow and stream progress updates.
    Shared between stable and snapshot modes.
    """
    async for update in execute_comfy_workflow(
        workflow_json,
        port,
        image_fetch_mode=IMAGE_FETCH_FILESYSTEM,
        output_dir="/root/comfy/ComfyUI/output",
        temp_dir="/root/comfy/ComfyUI/temp",
        logger=logger,
    ):
        yield update



# =============================================================================
# STABLE MODE: No memory snapshot, guaranteed reliability
# =============================================================================
@app.cls(
    image=image,
    cpu=COMFYUI_CPU,
    gpu=COMFYUI_GPU_TYPE,
    volumes={"/mnt/data": vol},
    timeout=COMFYUI_TIMEOUT,
    max_containers=COMFYUI_MAX_CONTAINERS,
    scaledown_window=COMFYUI_SCALEDOWN,  # Keep warm longer since no snapshot
)
class ComfyUIStable:
    """
    Stable ComfyUI class without memory snapshot.
    Slower cold starts but 100% reliable GPU access.
    """
    port: int = 8188
    
    @modal.enter()
    def launch_server(self):
        import requests
        
        logger.info("[ComfyUIStable] Starting ComfyUI server via comfy-cli...")
        
        # Start ComfyUI in background using comfy launch with Popen
        cmd = ["comfy", "launch", "--background", "--", "--listen", "0.0.0.0", "--port", str(self.port)]
        subprocess.Popen(cmd)
        
        # Wait for server to be ready
        logger.info("[ComfyUIStable] Waiting for ComfyUI to be ready...")
        for i in range(120):  # 2 minute timeout for cold start
            try:
                response = requests.get(f"http://127.0.0.1:{self.port}", timeout=2)
                if response.status_code == 200:
                    logger.info("[ComfyUIStable] ComfyUI is ready!")
                    return
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)
        
        logger.info("[ComfyUIStable] Warning - ComfyUI did not respond within 120 seconds.")
    
    @modal.method()
    async def run(self, workflow_json: Dict[str, Any]):
        async for update in _execute_workflow(workflow_json, self.port):
            yield update



# =============================================================================
# SNAPSHOT MODE: Memory snapshot for faster cold starts (experimental)
# =============================================================================
@app.cls(
    image=image_snapshot,
    cpu=COMFYUI_CPU,
    gpu=COMFYUI_GPU_TYPE,
    volumes={"/mnt/data": vol},
    timeout=COMFYUI_TIMEOUT,
    max_containers=COMFYUI_MAX_CONTAINERS,
    scaledown_window=40,
    enable_memory_snapshot=True,  # CPU/memory snapshot only, NOT GPU
)
class ComfyUISnapshot:
    """
    ComfyUI class with memory snapshot enabled.
    Faster cold starts but may have GPU initialization issues.
    """
    port: int = 8188
    
    @modal.enter(snap=True)
    def launch_for_snapshot(self):
        import requests
        
        logger.info("[ComfyUISnapshot] Snapshotting: Starting ComfyUI via comfy-cli...")
        
        # Start ComfyUI in background using comfy launch with Popen
        cmd = ["comfy", "launch", "--background", "--", "--listen", "0.0.0.0", "--port", str(self.port)]
        subprocess.Popen(cmd)
        
        # Wait for server to be ready
        logger.info("[ComfyUISnapshot] Waiting for ComfyUI to be ready...")
        for i in range(60):
            try:
                response = requests.get(f"http://127.0.0.1:{self.port}", timeout=2)
                if response.status_code == 200:
                    logger.info("[ComfyUISnapshot] ComfyUI is ready for snapshot!")
                    return
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)
        
        logger.info("[ComfyUISnapshot] Warning - ComfyUI did not respond within 60 seconds.")
    
    @modal.enter(snap=False)
    def restore_from_snapshot(self):
        import requests
        
        logger.info("[ComfyUISnapshot] Restored from snapshot. Re-enabling CUDA...")
        
        # Re-enable CUDA device via our custom endpoint
        try:
            response = requests.post(f"http://127.0.0.1:{self.port}/cuda/set_device", timeout=5)
            if response.status_code == 200:
                logger.info("[ComfyUISnapshot] Successfully re-enabled CUDA device")
            else:
                logger.info(f"[ComfyUISnapshot] CUDA re-enable returned status {response.status_code}")
        except Exception as e:
            logger.info(f"[ComfyUISnapshot] Failed to re-enable CUDA: {e}")
            # Server might not be running, try to restart it via comfy-cli
            logger.info("[ComfyUISnapshot] Attempting to restart ComfyUI via comfy-cli...")
            cmd = ["comfy", "launch", "--background", "--", "--listen", "0.0.0.0", "--port", str(self.port)]
            subprocess.Popen(cmd)
            
            for i in range(60):
                try:
                    response = requests.get(f"http://127.0.0.1:{self.port}", timeout=2)
                    if response.status_code == 200:
                        logger.info("[ComfyUISnapshot] ComfyUI restarted successfully")
                        break
                except:
                    pass
                time.sleep(1)
        
        # Ensure output directory is linked to volume
        output_dir = "/root/comfy/ComfyUI/output"
        volume_output = "/mnt/data/output"
        
        if os.path.exists(volume_output):
            if os.path.islink(output_dir):
                logger.info("[ComfyUISnapshot] Output already linked.")
            elif os.path.isdir(output_dir):
                logger.info("[ComfyUISnapshot] Linking output directory to volume...")
                try:
                    import shutil
                    for f in os.listdir(output_dir):
                        src = os.path.join(output_dir, f)
                        dst = os.path.join(volume_output, f)
                        if not os.path.exists(dst):
                            shutil.move(src, dst)
                    shutil.rmtree(output_dir)
                    os.symlink(volume_output, output_dir)
                    logger.info("[ComfyUISnapshot] Output linked successfully.")
                except Exception as e:
                    logger.info(f"[ComfyUISnapshot] Failed to link output: {e}")
            else:
                os.symlink(volume_output, output_dir)
    
    @modal.method()
    async def run(self, workflow_json: Dict[str, Any]):
        async for update in _execute_workflow(workflow_json, self.port):
            yield update




# NOTE: Worker container now calls ComfyUIStable or ComfyUISnapshot directly
# based on ENABLE_MEMORY_SNAPSHOT env var. No router function needed.


@app.function(
    image=image,
    volumes={"/mnt/data": vol},
    timeout=DOWNLOAD_TIMEOUT,
    max_containers=DOWNLOAD_MAX_CONTAINERS
)
@modal.concurrent(max_inputs=1, target_inputs=1)
def download_model(url: str, path: str, token: str = None, preview_url: str = None, info: dict = None):
    """Download model with shared validation pipeline and progress tracking."""
    import time

    base_path = "/mnt/data"
    try:
        full_path = get_safe_path(base_path, path)
    except Exception as e:
        logger.error(f"[Download] Path traversal blocked: {e}")
        return {"status": "error", "error": "Invalid path"}

    # Progress tracking
    import json
    progress_dir = "/mnt/data/downloads"
    os.makedirs(progress_dir, exist_ok=True)
    safe_name = os.path.basename(path)
    progress_file = os.path.join(progress_dir, f"{safe_name}.json")
    
    def update_progress(status, percent=0, speed="", eta="", downloaded="", total="", message=""):
        try:
            with open(progress_file, "w") as f:
                json.dump({
                    "filename": safe_name,
                    "status": status,
                    "percent": percent,
                    "speed": speed,
                    "eta": eta,
                    "downloaded": downloaded,
                    "total": total,
                    "message": message,
                    "updated_at": time.time()
                }, f)
        except Exception as e:
            logger.info(f"[Download] Failed to write progress: {e}")

    last_progress_update = 0.0

    def progress_callback(payload: Dict[str, Any]):
        nonlocal last_progress_update
        status = payload.get("status")

        if status == "starting":
            update_progress("starting", 0)
            return

        if status == "downloading":
            now = time.time()
            if now - last_progress_update < 0.5:
                return

            total_bytes = payload.get("total_bytes", 0) or 0
            downloaded_bytes = payload.get("downloaded_bytes", 0) or 0
            speed_mbps = payload.get("speed_mbps", 0.0) or 0.0
            eta_seconds = int(payload.get("eta_seconds", 0) or 0)
            percent = int(payload.get("percent", 0) or 0)

            downloaded_str = f"{downloaded_bytes / (1024 ** 2):.2f} MB"
            total_str = f"{total_bytes / (1024 ** 2):.2f} MB" if total_bytes > 0 else "Unknown"
            speed_str = f"{speed_mbps:.2f} MB/s"

            update_progress(
                "downloading",
                percent,
                speed_str,
                f"{eta_seconds}s",
                downloaded_str,
                total_str,
            )
            last_progress_update = now
            return

        if status == "success":
            update_progress("success", 100, message="Download complete")
            return

        if status == "error":
            update_progress("error", message=payload.get("message", "Download failed"))

    result = download_model_to_path(
        url=url,
        full_path=full_path,
        path=path,
        token=token,
        hf_token=os.environ.get("HF_TOKEN"),
        civitai_token=os.environ.get("CIVITAI_TOKEN"),
        preview_url=preview_url,
        metadata=info,
        log=logger.info,
        log_prefix="Download",
        progress_callback=progress_callback,
    )

    if result.get("status") == "success":
        vol.commit()
        time.sleep(5)
        if os.path.exists(progress_file):
            os.remove(progress_file)

    return result

@app.function(
    image=image,
    volumes={"/mnt/data": vol}, 
    scaledown_window=STORAGE_SCALEDOWN,
    max_containers=STORAGE_MAX_CONTAINERS
)
@modal.concurrent(max_inputs=20, target_inputs=10)
def list_models_with_metadata(directory: str):
    import os
    import json
    
    base_path = "/mnt/data"

    try:
        target_dir = get_safe_path(base_path, directory)
    except Exception:
        logger.warning(f"[ListModels] Path traversal blocked: {directory}")
        return []
    
    if not os.path.exists(target_dir):
        return []
        
    entries = os.listdir(target_dir)
    files = []
    
    # Create a map for quick lookup
    entry_set = set(entries)
    
    for name in entries:
        # Skip metadata/preview files themselves
        if name.endswith('.json') or name.endswith('.preview.png'):
            continue
            
        full_path = os.path.join(target_dir, name)
        if not os.path.isfile(full_path):
            continue
            
        file_data = {
            "name": name,
            "type": "file",
            "size": os.path.getsize(full_path)
        }
        
        # Check for preview
        preview_name = f"{os.path.splitext(name)[0]}.preview.png"
        if preview_name in entry_set:
            file_data["preview"] = f"/api/view/{directory}/{preview_name}"
            
        # Check and READ metadata
        meta_name = f"{os.path.splitext(name)[0]}.json"
        if meta_name in entry_set:
            file_data["metadata_url"] = f"/api/view/{directory}/{meta_name}"
            try:
                with open(os.path.join(target_dir, meta_name), 'r') as f:
                    file_data["metadata"] = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read metadata for {name}: {e}")
                
        files.append(file_data)
        
    vol.commit()
    return files


# ============================================
# Model Validation (Standalone Function)
# ============================================

@app.function(
    image=image,
    volumes={"/mnt/data": vol},
    timeout=VALIDATE_TIMEOUT,
    max_containers=VALIDATE_MAX_CONTAINERS
)
@modal.concurrent(max_inputs=10, target_inputs=5)
def validate_models(directories: list[str] = ["models/checkpoints"], delete_invalid: bool = False):
    """
    Validate all models in specified directories.
    Checks: minimum size, magic bytes, partial downloads.
    Returns: aggregated results for all directories.
    """
    import os
    import concurrent.futures
    import functools
    
    # ensure directories is a list
    if isinstance(directories, str):
        directories = [directories]
        
    validation_results = {
        "total_valid": 0,
        "total_invalid": 0,
        "total_partial": 0,
        "by_directory": {}
    }

    VALID_HEADERS = VALID_FILE_HEADERS
    MIN_SIZE = MIN_MODEL_SIZE
    
    def validate_single_file_in_dir(directory, name):
        """Helper to validate a single file, returns (directory, result)."""
        try:
            target_dir = get_safe_path("/mnt/data", directory)
        except Exception:
            return None

        if name.endswith(('.json', '.preview.png', '.txt', '.yaml', '.yml')):
            return None
            
        full_path = os.path.join(target_dir, name)
        if not os.path.isfile(full_path):
            return None
            
        # Check for partial downloads
        if name.endswith('.downloading'):
            if delete_invalid:
                os.remove(full_path)
                logger.info(f"[Validate] Deleted partial: {name}")
                
            return {
                "directory": directory,
                "type": "partial",
                "data": {
                    "name": name,
                    "size": os.path.getsize(full_path),
                    "issue": "Incomplete download (temp file)"
                }
            }
            
        try:
            file_size = os.path.getsize(full_path)
        except OSError:
            return None
            
        issues = []
        detected_format = "unknown"
        should_delete = False
        
        # Size check
        if file_size < MIN_SIZE:
            issues.append(f"Too small: {file_size} bytes")
            should_delete = True
            
        # Magic bytes check
        if file_size >= 16:
            try:
                with open(full_path, 'rb') as f:
                    header = f.read(16)
                
                header_valid = False
                for magic, fmt in VALID_HEADERS.items():
                    if header.startswith(magic):
                        header_valid = True
                        detected_format = fmt
                        break
                        
                if not header_valid:
                    if b'<html' in header.lower() or b'<!doctype' in header.lower():
                        issues.append("HTML content (auth error?)")
                        should_delete = True
                    else:
                        detected_format = f"unknown ({header[:4].hex()})"
            except Exception as e:
                issues.append(f"Read error: {e}")
                should_delete = False
        
        # Safetensors integrity check - validates the header structure
        # This catches corrupted files that pass magic byte checks but fail to load
        # NOTE: We parse the header manually for consistency (no framework dependency)
        if name.endswith('.safetensors') and file_size >= MIN_SIZE and not issues:
            try:
                import struct
                import json as json_module
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
                    header = json_module.loads(header_bytes)
                    
                    # Verify it has expected structure
                    if not isinstance(header, dict):
                        raise ValueError("Header is not a dict")
            except Exception as e:
                error_msg = str(e)
                # Truncate very long error messages
                if len(error_msg) > 100:
                    error_msg = error_msg[:100] + "..."
                issues.append(f"Safetensors corrupted: {error_msg}")
                should_delete = True
                logger.warning(f"[Validate] Corrupted safetensors: {name} - {error_msg}")
                
        model_info = {
            "name": name,
            "size": file_size,
            "size_mb": round(file_size / (1024**2), 1),
            "format": detected_format
        }
        
        if issues:
            model_info["issues"] = issues
            
            if delete_invalid and should_delete:
                os.remove(full_path)
                for ext in [".json", ".preview.png"]:
                    side_file = os.path.splitext(full_path)[0] + ext
                    if os.path.exists(side_file):
                        os.remove(side_file)
                logger.info(f"[Validate] Deleted invalid: {name}")
                
            return {"directory": directory, "type": "invalid", "data": model_info}
        
        return {"directory": directory, "type": "valid", "data": model_info}

    # Collect all file tasks
    all_file_tasks = []
    
    for directory in directories:
        try:
            target_dir = get_safe_path("/mnt/data", directory)
        except Exception:
            logger.error(f"[Validate] Path traversal attempt blocked for: {directory}")
            validation_results["by_directory"][directory] = {"valid": 0, "invalid": 0, "partial": 0}
            continue

        if not os.path.exists(target_dir):
            validation_results["by_directory"][directory] = {"valid": 0, "invalid": 0, "partial": 0}
            continue
            
        try:
            entries = os.listdir(target_dir)
            validation_results["by_directory"][directory] = {
                "valid": 0, "invalid": 0, "partial": 0, 
                "valid_files": [], "invalid_files": [], "partial_files": []
            }
            # Create a task for each file
            for name in entries:
                all_file_tasks.append((directory, name))
        except Exception as e:
            logger.error(f"Error listing {directory}: {e}")
            validation_results["by_directory"][directory] = {"error": str(e)}

    # Execute all file validations concurrently
    # Flattened list allows optimal thread pool usage across ALL directories
    if all_file_tasks:
        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
            # We need to pass both directory and name to the helper
            # Using list comprehension and lambda to bind arguments
            futures = [
                executor.submit(validate_single_file_in_dir, d, n) 
                for d, n in all_file_tasks
            ]
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    res = future.result()
                    if not res:
                        continue
                        
                    d = res["directory"]
                    t = res["type"]
                    data = res["data"]
                    
                    stats = validation_results["by_directory"][d]
                    
                    if t == "valid":
                        stats["valid"] += 1
                        # stats["valid_files"].append(data) # OMITTED to reduce payload size
                        validation_results["total_valid"] += 1
                    elif t == "invalid":
                        stats["invalid"] += 1
                        stats["invalid_files"].append(data)
                        validation_results["total_invalid"] += 1
                    elif t == "partial":
                        stats["partial"] += 1
                        stats["partial_files"].append(data)
                        validation_results["total_partial"] += 1
                        
                except Exception as e:
                    logger.error(f"File validation failed: {e}")
    
    if delete_invalid:
        vol.commit()
    
    summary = f"{validation_results['total_valid']} valid, {validation_results['total_invalid']} invalid"
    logger.info(f"[Validate] Batch complete: {summary}")
    
    return validation_results


# ============================================
# File Storage Operations (Serverless Functions)
# Each account has its own volume, accessed via Modal functions
# ============================================

@app.cls(
    image=image,
    volumes={"/mnt/data": vol},
    timeout=300,
    max_containers=1,
    scaledown_window=5
)
class FileStorage:
    """
    File storage operations for Modal volume.
    Each provider instance accesses its own volume via these serverless functions.
    """
    
    @modal.method()
    def get_file(self, path: str) -> bytes:
        """
        Get file contents from volume.
        
        Args:
            path: File path relative to /mnt/data (e.g., "models/checkpoints/model.safetensors")
            
        Returns:
            File contents as bytes
        """
        import os
        
        full_path = get_safe_path("/mnt/data", path)
        logger.info(f"[FileStorage] Reading file: {full_path}")
        
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {path}")
        
        with open(full_path, "rb") as f:
            return f.read()
    
    @modal.method()
    def delete_file(self, path: str) -> bool:
        """
        Delete file from volume.
        
        Args:
            path: File path relative to /mnt/data
            
        Returns:
            True if successful
        """
        import os
        
        full_path = get_safe_path("/mnt/data", path)
        logger.info(f"[FileStorage] Deleting file: {full_path}")
        
        if not os.path.exists(full_path):
            return False
        
        try:
            os.remove(full_path)
            vol.commit()  # Persist changes
            return True
        except Exception as e:
            logger.info(f"[FileStorage] Error deleting file: {e}")
            return False
    
    @modal.method()
    def list_files(self, directory: str = "models") -> list:
        """
        List files in directory.
        
        Args:
            directory: Directory path relative to /mnt/data
            
        Returns:
            List of file paths
        """
        import os
        
        full_path = get_safe_path("/mnt/data", directory)
        logger.info(f"[FileStorage] Listing directory: {full_path}")
        
        if not os.path.exists(full_path):
            return []
        
        files = []
        for root, dirs, filenames in os.walk(full_path):
            for filename in filenames:
                filepath = os.path.join(root, filename)
                # Make path relative to /mnt/data
                rel_path = os.path.relpath(filepath, "/mnt/data")
                files.append(rel_path)
        
        return files
    
    @modal.method()
    def file_exists(self, path: str) -> bool:
        """Check if file exists in volume."""
        import os
        full_path = get_safe_path("/mnt/data", path)
        return os.path.exists(full_path)
    
    @modal.method()
    def get_file_size(self, path: str) -> int:
        """Get file size in bytes."""
        import os
        full_path = get_safe_path("/mnt/data", path)
        if os.path.exists(full_path):
            return os.path.getsize(full_path)
        return 0
    
    @modal.method()
    def put_file(self, path: str, content: bytes) -> bool:
        """
        Write file contents to volume.
        Used for Img2Img and Inpainting source images/masks.
        
        Args:
            path: File path relative to /mnt/data (e.g., "input/image.png")
            content: File contents as bytes
            
        Returns:
            True if successful
        """
        from pathlib import Path
        
        full_path = Path(get_safe_path("/mnt/data", path))
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(full_path, "wb") as f:
            f.write(content)
        
        vol.commit()  # Persist to volume
        logger.info(f"[FileStorage] Saved {len(content)} bytes to {full_path}")
        return True


# Entry point wrappers for FileStorage
@app.function(
    image=image,
    volumes={"/mnt/data": vol},
    timeout=300
)
def storage_get_file(path: str) -> bytes:
    """Get file from volume (serverless function)."""
    return FileStorage().get_file.remote(path)


@app.function(
    image=image,
    volumes={"/mnt/data": vol},
    timeout=300
)
def storage_delete_file(path: str) -> bool:
    """Delete file from volume (serverless function)."""
    return FileStorage().delete_file.remote(path)


@app.function(
    image=image,
    volumes={"/mnt/data": vol},
    timeout=300
)
def storage_list_files(directory: str = "models") -> list:
    """List files in directory (serverless function)."""
    return FileStorage().list_files.remote(directory)


@app.function(
    image=image,
    volumes={"/mnt/data": vol},
    timeout=300
)
def storage_file_exists(path: str) -> bool:
    """Check if file exists (serverless function)."""
    return FileStorage().file_exists.remote(path)

@app.function(
    image=image,
    volumes={"/mnt/data": vol},
    timeout=600,
    scaledown_window=5,
    max_containers=1
)
@modal.concurrent(max_inputs=10, target_inputs=5)
def setup_models():
    import os
    # Ensure directories exist
    dirs = [
        "/mnt/data/output",
        "/mnt/data/downloads",
        "/mnt/data/models/checkpoints",
        "/mnt/data/models/loras",
        "/mnt/data/models/vae",
        "/mnt/data/models/controlnet",
        "/mnt/data/models/embeddings",
        "/mnt/data/models/upscale_models"
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        logger.debug(f"Ensured directory: {d}")
        
    # Check if we have models
    if not os.path.exists("/mnt/data/models/checkpoints"):
        logger.warning("No checkpoints directory found!")
        return
        
    logger.info("Setup complete. Volume ready.")
    """
    Downloads standard models (Upscalers, ADetailer) to the volume.
    Run this once: modal run backend/modal_app.py::setup_models
    """
    import os
    import requests
    import time

    models = [
        # Upscalers
        {
            "url": "https://huggingface.co/lokCX/4x-Ultrasharp/resolve/main/4x-Ultrasharp.pth",
            "path": "models/upscale_models/4x-Ultrasharp.pth"
        },
        {
            "url": "https://huggingface.co/Facehugger/4x-foolhardy-Remacri/resolve/main/4x_foolhardy_Remacri.pth",
            "path": "models/upscale_models/4x_foolhardy_Remacri.pth"
        },
        {
            "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
            "path": "models/upscale_models/RealESRGAN_x4plus.pth"
        },
        {
            "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
            "path": "models/upscale_models/RealESRGAN_x4plus_anime_6B.pth"
        },
        # ADetailer Models (Bbox)
        {
            "url": "https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov8n.pt",
            "path": "models/ultralytics/bbox/face_yolov8n.pt"
        },
        {
            "url": "https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov8s.pt",
            "path": "models/ultralytics/bbox/face_yolov8s.pt"
        },
        {
            "url": "https://huggingface.co/Bingsu/adetailer/resolve/main/hand_yolov8n.pt",
            "path": "models/ultralytics/bbox/hand_yolov8n.pt"
        },
        # ADetailer Models (Seg)
        {
            "url": "https://huggingface.co/Bingsu/adetailer/resolve/main/person_yolov8n-seg.pt",
            "path": "models/ultralytics/seg/person_yolov8n-seg.pt"
        }
    ]

    logger.info("Starting model setup...")
    base_path = "/mnt/data"
    
    for model in models:
        full_path = os.path.join(base_path, model['path'])
        if os.path.exists(full_path):
            logger.info(f"Skipping {model['path']} (already exists)")
            continue
            
        logger.info(f"Downloading {model['path']}...")
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        try:
            response = requests.get(model['url'], stream=True)
            response.raise_for_status()
            with open(full_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"Downloaded {model['path']}")
        except Exception as e:
            logger.error(f"Failed to download {model['path']}: {e}")

    logger.info("Model setup complete!")
    return {"status": "success"}