import modal
import asyncio
import concurrent.futures
import subprocess
import time
import logging

import os
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, AsyncGenerator, List
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
# =============================================================================
# Inlined image_worker logic
# =============================================================================
IMAGE_FETCH_FILESYSTEM = "filesystem"
IMAGE_FETCH_VIEW_API = "view_api"

def _get_websockets_module():
    import websockets
    return websockets

def _log(logger_obj: logging.Logger | None, level: int, message: str) -> None:
    if logger_obj is not None:
        logger_obj.log(level, message)

async def _connect_with_retry(ws_url: str, *, max_retries: int, initial_retry_delay_seconds: float, logger_obj: logging.Logger | None):
    websockets = _get_websockets_module()
    retry_delay = initial_retry_delay_seconds
    for attempt in range(max_retries):
        try:
            return await websockets.connect(ws_url), websockets
        except Exception as error:
            if attempt >= max_retries - 1:
                raise
            _log(logger_obj, logging.WARNING, f"Workflow websocket connect failed: {error}")
            await asyncio.sleep(retry_delay)
            retry_delay *= 2
    raise RuntimeError("Workflow websocket connection retries exhausted")

async def _queue_prompt(server_address: str, workflow_json: Dict[str, Any], client_id: str) -> tuple[str | None, Dict[str, Any] | None]:
    if not server_address.startswith("http://") and not server_address.startswith("https://"):
        server_address = f"http://{server_address}"
    endpoint = f"{server_address}/prompt"
    payload = {"prompt": workflow_json, "client_id": client_id}
    from provider_core.http_client import get_http_client
    import httpx
    try:
        client = get_http_client()
        response = await client.post(endpoint, json=payload, timeout=10.0)
        response.raise_for_status()
        response_data = response.json()
    except httpx.HTTPStatusError as error:
        return None, {"status": "error", "message": f"ComfyUI rejected workflow: {error.response.text or str(error)}"}
    except Exception as error:
        return None, {"status": "error", "message": f"ComfyUI rejected workflow: {error}"}
    prompt_id = response_data.get("prompt_id")
    if not prompt_id: return None, {"status": "error", "message": "No prompt_id"}
    if "error" in response_data: return None, {"status": "error", "message": response_data["error"]}
    if response_data.get("node_errors"): return None, {"status": "error", "message": str(response_data.get("node_errors"))}
    return prompt_id, None

async def _get_history(server_address: str, prompt_id: str) -> tuple[Dict[str, Any] | None, str | None]:
    if not server_address.startswith("http://") and not server_address.startswith("https://"):
        server_address = f"http://{server_address}"
    endpoint = f"{server_address}/history/{prompt_id}"
    from provider_core.http_client import get_http_client
    try:
        client = get_http_client()
        response = await client.get(endpoint, timeout=10.0)
        response.raise_for_status()
        history = response.json()
    except Exception as error:
        return None, f"Failed to fetch history: {error}"
    if prompt_id not in history: return None, "Prompt not found in history"
    return history[prompt_id], None

def _collect_images_from_filesystem(history_data: Dict[str, Any], *, output_dir: str, temp_dir: str, logger_obj: logging.Logger | None) -> list[Dict[str, Any]]:
    import base64
    images_output = []
    for node_output in history_data.get("outputs", {}).values():
        for image in node_output.get("images", []):
            filename = image.get("filename")
            if not filename: continue
            subfolder = image.get("subfolder") or ""
            folder_type = image.get("type", "output")
            base_dir = output_dir if folder_type == "output" else temp_dir
            try:
                filepath = get_safe_path(base_dir, os.path.join(subfolder, filename) if subfolder else filename)
                with open(filepath, "rb") as file_obj:
                    images_output.append({"filename": filename, "data": base64.b64encode(file_obj.read()).decode('utf-8'), "_base64_encoded": True, "type": folder_type, "subfolder": subfolder})
            except Exception as error:
                _log(logger_obj, logging.ERROR, f"Failed to read image {filename}: {error}")
    return images_output

async def execute_comfy_workflow(workflow_json: Dict[str, Any], port: int = 8188, *, image_fetch_mode: str = IMAGE_FETCH_FILESYSTEM, output_dir: str = "/root/comfy/ComfyUI/output", temp_dir: str = "/root/comfy/ComfyUI/temp", stall_timeout_seconds: float = 300.0, logger: logging.Logger | None = None) -> AsyncGenerator[Dict[str, Any], None]:
    import uuid
    client_id = str(uuid.uuid4())
    server_address = f"http://127.0.0.1:{port}"
    ws_url = f"ws://127.0.0.1:{port}/ws?clientId={client_id}"
    websocket, websockets_mod = await _connect_with_retry(ws_url, max_retries=5, initial_retry_delay_seconds=1.0, logger_obj=logger)
    
    prompt_id, queue_error = await _queue_prompt(server_address, workflow_json, client_id)
    if queue_error:
        yield queue_error; return
    
    yield {"status": "queued", "prompt_id": prompt_id}
    effective_stall_timeout = max(float(stall_timeout_seconds), 1.0)
    last_prompt_node = None
    
    try:
        while True:
            try: message = await asyncio.wait_for(websocket.recv(), timeout=effective_stall_timeout)
            except asyncio.TimeoutError:
                history_probe, _ = await _get_history(server_address, prompt_id)
                if history_probe is not None: break
                yield {"status": "error", "message": "Workflow stalled", "code": 408, "retryable": True, "details": {"reason": "workflow_stalled", "prompt_id": prompt_id, "last_node": last_prompt_node}}
                return
            except websockets_mod.exceptions.ConnectionClosed as error:
                from provider_core.http_client import get_http_client
                try: await get_http_client().post(f"{server_address}/interrupt", timeout=5.0)
                except: pass
                yield {"status": "error", "message": f"WebSocket closed: {error}", "code": 1006, "retryable": True, "details": {"reason": "websocket_closed", "prompt_id": prompt_id}}
                return
            except Exception as error:
                yield {"status": "error", "message": f"WebSocket error: {error}", "code": 500, "retryable": False, "details": {"reason": "websocket_error", "prompt_id": prompt_id}}
                return
                
            if not isinstance(message, str): continue
            try: payload = json.loads(message)
            except: continue
            
            msg_type = payload.get("type")
            msg_data = payload.get("data", {})
            msg_prompt_id = msg_data.get("prompt_id")
            
            if msg_type == "executing":
                node = msg_data.get("node")
                if node is None and msg_prompt_id == prompt_id: break
                if msg_prompt_id == prompt_id:
                    last_prompt_node = str(node) if node is not None else None
                    yield {"status": "executing", "node": node, "prompt_id": prompt_id}
            elif msg_type == "execution_cached" and msg_prompt_id == prompt_id:
                yield {"status": "execution_cached", "nodes": msg_data.get("nodes", []), "prompt_id": prompt_id}
            elif msg_type == "progress" and (msg_prompt_id is None or msg_prompt_id == prompt_id):
                yield {"status": "progress", "value": msg_data.get("value", 0), "max": msg_data.get("max", 0), "prompt_id": prompt_id}
            elif msg_type == "execution_error":
                yield {"status": "error", "message": str(msg_data)}; return
    except asyncio.CancelledError:
        from provider_core.http_client import get_http_client
        try: await get_http_client().post(f"{server_address}/interrupt", timeout=5.0)
        except: pass
        raise
    finally:
        await websocket.close()
        
    history_data, history_error = await _get_history(server_address, prompt_id)
    if history_error:
        yield {"status": "error", "message": history_error}; return
        
    yield {"status": "success", "images": _collect_images_from_filesystem(history_data, output_dir=output_dir, temp_dir=temp_dir, logger_obj=logger)}

def _start_comfy_server(port: int, extra_args: list[str] = None):
    cmd = ["comfy", "launch", "--background", "--", "--listen", "0.0.0.0", "--port", str(port)]
    if extra_args: cmd.extend(extra_args)
    subprocess.Popen(cmd)

def _wait_for_comfy_ready(port: int, timeout_seconds: float, label: str):
    import requests
    deadline = time.time() + max(timeout_seconds, 1.0)
    while time.time() < deadline:
        try:
            if requests.get(f"http://127.0.0.1:{port}", timeout=2).status_code == 200:
                logger.info(f"[{label}] ComfyUI is ready")
                return True
        except requests.exceptions.RequestException: pass
        time.sleep(1)
    return False

def _restart_comfy_server(port: int, label: str, timeout_seconds: float = 180.0):
    try:
        subprocess.run(["pkill", "-f", "ComfyUI/main.py"], check=False)
        subprocess.run(["pkill", "-f", "comfy launch"], check=False)
    except: pass
    time.sleep(1)
    _start_comfy_server(port)
    _wait_for_comfy_ready(port, timeout_seconds, label)

def capture_stall_diagnostics(port: int, label: str, details: Optional[Dict[str, Any]] = None, enabled: bool = True, diagnostics_timeout: float = 8.0, max_chars: int = 12000, volume_commit_fn = None) -> Optional[str]:
    if not enabled: return None
    diagnostics_path = Path("/mnt/data/diagnostics/comfyui_stalls") / f"{label.lower()}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(diagnostics_path, "w", encoding="utf-8") as f: json.dump({"label": label, "port": port, "stall_details": details or {}}, f)
        if volume_commit_fn: volume_commit_fn()
    except Exception as exc: logger.error(f"Failed diagnostics: {exc}")
    return str(diagnostics_path)

async def list_models_with_metadata_internal(base_path: str, directory: str, compute_hashes: bool = False) -> list[Dict[str, Any]]:
    import aiofiles
    try: target_dir = get_safe_path(base_path, directory)
    except: return []
    if not os.path.exists(target_dir): return []
    
    def _scan():
        entries, entry_set = [], set()
        try:
            for e in os.scandir(target_dir):
                if e.is_file():
                    entry_set.add(e.name)
                    if not e.name.endswith(('.json', '.preview.png', '.sha256')): entries.append((e.name, e.stat().st_size))
        except: pass
        return entries, entry_set
        
    entries, entry_set = await asyncio.to_thread(_scan)
    async def _proc(name: str, size: int):
        fpath = f"{directory}/{name}" if directory else name
        res = {"name": name, "path": fpath, "type": "file", "size": size, "sha256": None}
        if f"{os.path.splitext(name)[0]}.preview.png" in entry_set: res["preview"] = f"/api/view/{directory}/{os.path.splitext(name)[0]}.preview.png"
        meta_name = f"{os.path.splitext(name)[0]}.json"
        if meta_name in entry_set:
            res["metadata_url"] = f"/api/view/{directory}/{meta_name}"
            try:
                async with aiofiles.open(os.path.join(target_dir, meta_name), 'r') as f: res["metadata"] = json.loads(await f.read())
            except: pass
        return res
    return await asyncio.gather(*[_proc(n, s) for n, s in entries])


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
        Path(__file__).parent.parent.parent / "provider_core",
        Path(__file__).parent.parent.parent.parent / "provider_core",
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
COMFYUI_STALL_TIMEOUT_SECONDS = float(os.getenv("MODAL_COMFYUI_STALL_TIMEOUT_SECONDS", "300"))
COMFYUI_HEALTHCHECK_TIMEOUT_SECONDS = float(os.getenv("MODAL_COMFYUI_HEALTHCHECK_TIMEOUT_SECONDS", "180"))
COMFYUI_MAX_RUNS_BEFORE_RESTART = int(os.getenv("MODAL_COMFYUI_MAX_RUNS_BEFORE_RESTART", "30"))
COMFYUI_CAPTURE_STALL_DIAGNOSTICS = os.getenv("MODAL_COMFYUI_CAPTURE_STALL_DIAGNOSTICS", "true").strip().lower() in {
    "1", "true", "yes", "on"
}
COMFYUI_STALL_DIAGNOSTICS_TIMEOUT_SECONDS = float(
    os.getenv("MODAL_COMFYUI_STALL_DIAGNOSTICS_TIMEOUT_SECONDS", "8")
)
COMFYUI_STALL_DIAGNOSTICS_MAX_CHARS = int(os.getenv("MODAL_COMFYUI_STALL_DIAGNOSTICS_MAX_CHARS", "12000"))

# Download function settings
DOWNLOAD_TIMEOUT = int(os.getenv("MODAL_DOWNLOAD_TIMEOUT", "3600"))
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

# Define the Modal app (allow per-provider app names via deploy environment)
app = modal.App(os.getenv("MODAL_APP_NAME", "comfy-modal-stack"))

# Define the Volume for persistent storage
vol = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

# =============================================================================
# Base Image (shared between stable and snapshot modes)
# Uses comfy-cli for ALL operations: installation, custom nodes, launching
# =============================================================================
image_base = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("git", "libgl1-mesa-glx", "libglib2.0-0", gpu="L4")
    .uv_pip_install("comfy-cli", "fastapi", "websockets", "uvicorn", "requests", "safetensors", "py-spy", "httpx", "aiofiles", gpu="L4")
    # Install ComfyUI using comfy-cli
    .run_commands("comfy --skip-prompt install --fast-deps --nvidia --cuda-version 12.8",gpu="L4")
    # Ensure torch sees the complete CUDA user-space library set expected by modern nodes.
    .uv_pip_install(
        "nvidia-cuda-runtime-cu12",
        "nvidia-cuda-nvrtc-cu12",
        "nvidia-cuda-cupti-cu12",
        "nvidia-cublas-cu12",
        "nvidia-cudnn-cu12",
        "nvidia-cufft-cu12",
        "nvidia-curand-cu12",
        "nvidia-cusolver-cu12",
        "nvidia-cusparse-cu12",
        "nvidia-cusparselt-cu12",
        "nvidia-nccl-cu12",
        "nvidia-nvjitlink-cu12",
        "nvidia-nvtx-cu12",
        "nvidia-cufile-cu12",
        gpu="L4",
    )
    # Ensure torch sees CUDA runtime/nvrtc libs expected by its preload path.
    .run_commands(
        "python -c \"import torch; print('torch import OK before nodes:', torch.__version__)\"",
        gpu="L4",
    )
    # Install Custom Nodes via comfy-cli registry
    # See: https://registry.comfy.org/
    .run_commands(
        "comfy node install --fast-deps comfyui-manager",
        "comfy node install --fast-deps comfyui-impact-pack",
        "comfy node install --fast-deps comfyui_controlnet_aux",
        "comfy node install --fast-deps comfyui-animatediff-evolved",
        "comfy --help",
        gpu="L4",
    )
    # Create symlinks to volume for models, output, and input
    .run_commands(
        "rm -rf /root/comfy/ComfyUI/models /root/comfy/ComfyUI/output /root/comfy/ComfyUI/input",
        "ln -s /mnt/data/models /root/comfy/ComfyUI/models",
        "ln -s /mnt/data/output /root/comfy/ComfyUI/output",
        "ln -s /mnt/data/input /root/comfy/ComfyUI/input"
    )
    # Ensure shared provider_core utilities are present in cloud runtime.
    # Note: image_worker logic is now inlined into this file.
    .add_local_dir(
        local_path=PROVIDER_CORE_LOCAL_PATH,
        remote_path="/root/provider_core",
        copy=True,
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




def _capture_stall_diagnostics(port: int, label: str, details: Optional[Dict[str, Any]] = None) -> Optional[str]:
    return capture_stall_diagnostics(
        port, label, details,
        enabled=COMFYUI_CAPTURE_STALL_DIAGNOSTICS,
        diagnostics_timeout=COMFYUI_STALL_DIAGNOSTICS_TIMEOUT_SECONDS,
        max_chars=COMFYUI_STALL_DIAGNOSTICS_MAX_CHARS,
        volume_commit_fn=vol.commit
    )


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
        stall_timeout_seconds=COMFYUI_STALL_TIMEOUT_SECONDS,
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
        logger.info("[ComfyUIStable] Starting ComfyUI server via comfy-cli...")
        _start_comfy_server(self.port)
        _wait_for_comfy_ready(self.port, COMFYUI_HEALTHCHECK_TIMEOUT_SECONDS, "ComfyUIStable")
        self._completed_runs = 0
    
    @modal.method()
    async def run(self, workflow_json: Dict[str, Any]):
        if COMFYUI_MAX_RUNS_BEFORE_RESTART > 0 and getattr(self, "_completed_runs", 0) >= COMFYUI_MAX_RUNS_BEFORE_RESTART:
            await asyncio.to_thread(_restart_comfy_server, self.port, "ComfyUIStable")
            self._completed_runs = 0

        saw_stall = False
        stall_details = None
        async for update in _execute_workflow(workflow_json, self.port):
            details = update.get("details") if isinstance(update, dict) else None
            if update.get("status") == "error" and isinstance(details, dict) and details.get("reason") == "workflow_stalled":
                saw_stall = True
                stall_details = dict(details)
            yield update

        self._completed_runs = getattr(self, "_completed_runs", 0) + 1
        if saw_stall:
            diagnostics_path = await asyncio.to_thread(
                _capture_stall_diagnostics,
                self.port,
                "ComfyUIStable",
                stall_details,
            )
            if diagnostics_path:
                logger.warning(f"[ComfyUIStable] Stall diagnostics saved at: {diagnostics_path}")
            await asyncio.to_thread(_restart_comfy_server, self.port, "ComfyUIStable")
            self._completed_runs = 0



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
    scaledown_window=COMFYUI_SCALEDOWN_SNAPSHOT,
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
        # Snapshot capture can run without fully initialized CUDA runtime.
        # Defer ComfyUI launch to snap=False restore phase to avoid hard startup failure.
        logger.info("[ComfyUISnapshot] Snapshotting: deferring ComfyUI launch until restore phase")
        self._completed_runs = 0
    
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
            logger.info("[ComfyUISnapshot] Attempting to start ComfyUI via comfy-cli...")
            _start_comfy_server(self.port)
            _wait_for_comfy_ready(self.port, COMFYUI_HEALTHCHECK_TIMEOUT_SECONDS, "ComfyUISnapshot")
        
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
        if COMFYUI_MAX_RUNS_BEFORE_RESTART > 0 and getattr(self, "_completed_runs", 0) >= COMFYUI_MAX_RUNS_BEFORE_RESTART:
            await asyncio.to_thread(_restart_comfy_server, self.port, "ComfyUISnapshot")
            self._completed_runs = 0

        saw_stall = False
        stall_details = None
        async for update in _execute_workflow(workflow_json, self.port):
            details = update.get("details") if isinstance(update, dict) else None
            if update.get("status") == "error" and isinstance(details, dict) and details.get("reason") == "workflow_stalled":
                saw_stall = True
                stall_details = dict(details)
            yield update

        self._completed_runs = getattr(self, "_completed_runs", 0) + 1
        if saw_stall:
            diagnostics_path = await asyncio.to_thread(
                _capture_stall_diagnostics,
                self.port,
                "ComfyUISnapshot",
                stall_details,
            )
            if diagnostics_path:
                logger.warning(f"[ComfyUISnapshot] Stall diagnostics saved at: {diagnostics_path}")
            await asyncio.to_thread(_restart_comfy_server, self.port, "ComfyUISnapshot")
            self._completed_runs = 0


# =============================================================================
# EXTRACTOR MODE: CPU-only node extraction (for React Flow generator)
# =============================================================================
@app.cls(
    image=image,
    cpu=COMFYUI_CPU,
    gpu=None,  # CPU only
    volumes={"/mnt/data": vol},
    timeout=300,
    max_containers=1,
)
class ComfyUINodeExtractor:
    """
    CPU-only class to extract object_info from ComfyUI.
    This avoids booting expensive GPUs just to list custom nodes.
    """
    port: int = 8189
    
    @modal.method()
    def get_object_info(self) -> Dict[str, Any]:
        import requests
        import subprocess
        import time

        logger.info("[ComfyUINodeExtractor] Starting CPU-only server...")
        cmd = ["comfy", "launch", "--", "--listen", "0.0.0.0", "--port", str(self.port), "--cpu"]
        server_process = subprocess.Popen(cmd)
        
        # Wait for ready
        deadline = time.time() + 60
        ready = False
        while time.time() < deadline:
            try:
                response = requests.get(f"http://127.0.0.1:{self.port}", timeout=2)
                if response.status_code == 200:
                    ready = True
                    break
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)
            
        if not ready:
            raise RuntimeError("ComfyUI failed to start in CPU mode for extraction.")
            
        # Fetch object_info
        try:
            response = requests.get(f"http://127.0.0.1:{self.port}/object_info", timeout=60)
            response.raise_for_status()
            data = response.json()
            logger.info(f"[ComfyUINodeExtractor] Successfully extracted object_info ({len(data)} nodes).")
        finally:
            # Kill the server gracefully
            logger.info("[ComfyUINodeExtractor] Shutting down CPU server...")
            server_process.terminate()
            try:
                server_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server_process.kill()
            
        return data


# NOTE: Worker container now calls ComfyUIStable or ComfyUISnapshot directly
# based on ENABLE_MEMORY_SNAPSHOT env var. No router function needed.


@app.function(
    image=image,
    volumes={"/mnt/data": vol},
    timeout=DOWNLOAD_TIMEOUT,
    max_containers=DOWNLOAD_MAX_CONTAINERS
)
@modal.concurrent(max_inputs=1, target_inputs=1)
def download_model(url: str, path: str, token: str = None, preview_url: str = None, metadata: dict = None):
    """Download model with shared validation pipeline and progress tracking."""
    vol.reload()
    base_path = "/mnt/data"
    try:
        full_path = get_safe_path(base_path, path)
    except Exception as e:
        logger.error(f"[Download] Path traversal blocked: {e}")
        return {"status": "error", "message": "Invalid path"}

    # Progress tracking
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
            vol.commit()
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

        if status == "message":
            update_progress("error", message=payload.get("message", "Download failed"))

    try:
        result = download_model_to_path(
            url=url,
            full_path=full_path,
            path=path,
            token=token,
            hf_token=os.environ.get("HF_TOKEN"),
            civitai_token=os.environ.get("CIVITAI_TOKEN"),
            preview_url=preview_url,
            metadata=metadata,
            log=logger.info,
            log_prefix="Download",
            progress_callback=progress_callback,
        )

        if result.get("status") == "success":
            vol.commit()
            time.sleep(5)
            
        return result
    finally:
        if os.path.exists(progress_file):
            try:
                os.remove(progress_file)
                vol.commit()
            except Exception:
                pass

LIGHTWEIGHT_SCALEDOWN = 15

_reload_lock = asyncio.Lock()

@app.function(
    image=image,
    volumes={"/mnt/data": vol}, 
    scaledown_window=LIGHTWEIGHT_SCALEDOWN,
    max_containers=STORAGE_MAX_CONTAINERS,
    timeout=3600
)
@modal.concurrent(max_inputs=20, target_inputs=10)
async def list_models_with_metadata(directory: str):
    async with _reload_lock:
        await vol.reload.aio()
        return await list_models_with_metadata_internal("/mnt/data", directory, compute_hashes=False)


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
async def validate_models(directories: list[str], delete_invalid: bool = False):
    await vol.reload.aio()
    """
    Validate all models in specified directories.
    Checks: minimum size, magic bytes, partial downloads.
    Returns: aggregated results for all directories.
    """
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
            file_size = 0
            if os.path.exists(full_path):
                file_size = os.path.getsize(full_path)
            
            if delete_invalid:
                try:
                    os.remove(full_path)
                    logger.info(f"[Validate] Deleted partial: {name}")
                except Exception as e:
                    logger.warning(f"[Validate] Failed to delete partial {name}: {e}")
                
            return {
                "directory": directory,
                "type": "partial",
                "data": {
                    "name": name,
                    "size": file_size,
                    "issue": "Incomplete download (temp file)"
                }
            }
            
        file_size = os.path.getsize(full_path)
        from provider_core.validation import validate_downloaded_file
        validation = validate_downloaded_file(full_path)
        issues = [] if validation["valid"] else [validation["error"]]
        should_delete = not validation["valid"]
        detected_format = validation.get("format", "unknown")
                
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
                side_files = [
                    os.path.splitext(full_path)[0] + ".json",
                    os.path.splitext(full_path)[0] + ".preview.png",
                    full_path + ".sha256"
                ]
                for side_file in side_files:
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
            validation_results["by_directory"][directory] = {"message": str(e)}

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
        await vol.commit.aio()
    
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
    def read_file(self, path: str) -> bytes:
        """
        Read file contents from the volume.
        """
        import os
        
        vol.reload()
        full_path = get_safe_path("/mnt/data", path)
        logger.info(f"[FileStorage] Reading file: {full_path}")
        
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {path}")
        
        with open(full_path, "rb") as f:
            return f.read()
    
    @modal.method()
    async def delete_file(self, path: str) -> bool:
        """
        Delete a file from the volume.
        """
        import os
        import asyncio
        
        vol.reload()
        full_path = get_safe_path("/mnt/data", path)
        logger.info(f"[FileStorage] Deleting file: {full_path}")
        
        if not os.path.exists(full_path) and not os.path.exists(full_path + ".downloading"):
            return False
        
        try:
            if os.path.exists(full_path):
                if os.path.isdir(full_path):
                    import shutil
                    await asyncio.to_thread(shutil.rmtree, full_path)
                else:
                    await asyncio.to_thread(os.remove, full_path)
                
            if os.path.exists(full_path + ".downloading"):
                await asyncio.to_thread(os.remove, full_path + ".downloading")
                
            if not path.endswith((".json", ".preview.png", ".sha256")):
                base_path, _ = os.path.splitext(full_path)
                side_files = [
                    base_path + ".json",
                    base_path + ".preview.png",
                    full_path + ".sha256"
                ]
                for side_file in side_files:
                    if os.path.exists(side_file):
                        await asyncio.to_thread(os.remove, side_file)
            
            await asyncio.to_thread(vol.commit)  # Persist changes
            return True
        except Exception as e:
            logger.info(f"[FileStorage] Error deleting file: {e}")
            return False
    
    @modal.method()
    def list_directory(self, directory: str) -> list[dict]:
        """
        List all files in a directory.
        """
        import os
        
        vol.reload()
        full_path = get_safe_path("/mnt/data", directory)
        logger.info(f"[FileStorage] Listing directory: {full_path}")
        
        if not os.path.exists(full_path):
            return []
        
        files = []
        for root, dirs, filenames in os.walk(full_path):
            for filename in filenames:
                if filename.endswith(".sha256") or filename.endswith(".json") or filename.endswith(".preview.png"):
                    continue
                filepath = os.path.join(root, filename)
                # Make path relative to /mnt/data
                rel_path = os.path.relpath(filepath, "/mnt/data")
                files.append(rel_path)
        
        return files
    
    @modal.method()
    def file_exists(self, path: str) -> bool:
        """Check if file exists in volume."""
        import os
        vol.reload()
        full_path = get_safe_path("/mnt/data", path)
        return os.path.exists(full_path)
    
    @modal.method()
    def get_file_size(self, path: str) -> int:
        """Get file size in bytes."""
        import os
        vol.reload()
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


@app.function(
    image=image,
    volumes={"/mnt/data": vol},
    timeout=600,
    scaledown_window=5,
    max_containers=1
)
@modal.concurrent(max_inputs=10, target_inputs=5)
def setup_models():
    vol.reload()
    import os
    import requests
    import time
    from provider_core.models import MODEL_DIRECTORIES
    dirs = ["/mnt/data/output", "/mnt/data/downloads"] + [f"/mnt/data/{d}" for d in MODEL_DIRECTORIES]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        logger.debug(f"Ensured directory: {d}")
        
    logger.info("Setup complete. Volume ready.")

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