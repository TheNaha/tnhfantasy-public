"""Beam.cloud Application for ComfyUI - GPU, Storage, and Download Split

Four deployments:
  - comfy_gpu: Realtime WebSocket for inference (RTX4090, checkpoint restore)
  - comfy_storage: ASGI for file operations (CPU only, cheap)
  - comfy_download: ASGI for model downloads (separate scaling)
  - comfy_extractor: REST for /object_info, the ComfyUI node catalogue

Deploy from the REPOSITORY ROOT, so the synced working directory carries the
packages this file imports (see below):
    beam deploy deployables/beam/beam_app.py:comfy_gpu
    beam deploy deployables/beam/beam_app.py:comfy_storage
    beam deploy deployables/beam/beam_app.py:comfy_download
    beam deploy deployables/beam/beam_app.py:comfy_extractor

    beta9 deploy deployables/beam/beam_app.py:comfy_gpu
    ...

The deploy context matters more here than on Modal. Unlike Modal, this file's
images add no source of their own (`gpu_image`/`cpu_image` below are built from
commands and pip packages only), and every one of the four decorators used here
syncs the local working directory to the container (`.beamignore` in this
directory controls what goes). So every module imported here — this file's two
siblings plus both provider packages — has to be inside the directory you deploy
from. The 2026-08 procedure was `cd provider_containers/image_worker/engines/beam`
and deploy from there, which no longer works: `provider_core` is not a sibling of
this file any more. Deploying from the repo root restores it, at the cost of
syncing the whole checkout (add to `.beamignore` if that matters). See the
`sys.path` bootstrap below for how the imports resolve either way.
"""
# beam is the CLI alias for the beta9 Python package
from beta9 import asgi, realtime, Image, Volume, QueueDepthAutoscaler, rest_api
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
import os
import json
import subprocess
import sys
import time
import asyncio
from pathlib import Path
from typing import Dict, Any
import base64

# IMPORTANT: every package below must be present in the deploy source context.
# `provider_core` used to be a sibling package — `provider_containers/` held
# this app in `image_worker/engines/beam/`, `workflow_executor.py` and
# `models_utils.py` in `image_worker/comfy/`, and the library in
# `provider_core/` — so `import provider_core` worked wherever the file happened
# to sit inside that tree and nothing here said so. The container layout is gone
# (see deployables/README.md), `provider_core` now lives under `remote_agent/`,
# and that positional assumption is what made the source un-deployable: it could
# not move without breaking these imports, and the imports could not be
# satisfied without the source. Resolve the repo root explicitly instead of
# counting parents, and fall through to the directory this file was uploaded
# from when the marker is missing — which is the only thing that can work inside
# the container, where there is no repo.
_HERE = Path(__file__).resolve().parent
# This file is 2 levels below the repo root: beam -> deployables -> repo root.
_REPO_ROOT = next(
    (p for p in _HERE.parents if (p / "remote_agent" / "provider_core").is_dir()),
    None,
)
# `remote_agent/` makes the shared provider_core importable; `deployables/`
# makes provider_worker_core (the modules the 2026-10-08 slimming deleted,
# which this app still imports) importable; `_HERE` is `workflow_executor` and
# `models_utils`, which are siblings of this file by design and are what the
# deploy context has to carry.
for _sys_path_entry in (
    _HERE,
    *((_REPO_ROOT / "deployables", _REPO_ROOT / "remote_agent") if _REPO_ROOT else ()),
):
    if _sys_path_entry.is_dir() and str(_sys_path_entry) not in sys.path:
        sys.path.insert(0, str(_sys_path_entry))

from provider_core.auth import bearer_from_header, token_matches
from provider_core.downloads import pending_download_paths, pipeline_artifacts
from provider_core.http_client import get_file_size_cap, get_upload_size_cap
from provider_core.utils import get_safe_path, is_model_candidate, is_transient_artifact
from provider_core.logging import get_logger
from provider_worker_core.responses import failed, ok, outcome

logger = get_logger("deployables.beam.beam_app")
from provider_core.downloads import download_model_to_path
from workflow_executor import (
    IMAGE_FETCH_VIEW_API,
    execute_comfy_workflow,
)


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
# Socket timeout for the download transfer, distinct from the function timeout
# above. `requests.get` with no timeout blocks forever on a peer that accepts the
# connection and then stops sending; on the storage/download deployments that
# wedges a container that also serves /list-models. Same value as the function
# timeout by default, kept separate because the two answer different questions.
DOWNLOAD_HTTP_TIMEOUT = float(os.getenv("BEAM_DOWNLOAD_HTTP_TIMEOUT", str(DOWNLOAD_TIMEOUT)))
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
    fast_save_node = "/root/comfy/ComfyUI/custom_nodes/tnh_fast_save.py"
    try:
        os.makedirs(os.path.dirname(fast_save_node), exist_ok=True)
        with open(fast_save_node, "w", encoding="utf-8") as f:
            f.write(
                "import logging\n"
                "logger = logging.getLogger('tnh_fast_save')\n"
                "try:\n"
                "    import nodes\n"
                "    if hasattr(nodes, 'SaveImage'):\n"
                "        _orig_init = nodes.SaveImage.__init__\n"
                "        def _fast_init(self, *args, **kwargs):\n"
                "            _orig_init(self, *args, **kwargs)\n"
                "            self.compress_level = 1\n"
                "        nodes.SaveImage.__init__ = _fast_init\n"
                "        logger.info('Patched SaveImage.compress_level = 1 for fast lossless encoding')\n"
                "except Exception as e:\n"
                "    logger.warning(f'Could not patch SaveImage: {e}')\n"
                "NODE_CLASS_MAPPINGS = {}\n"
            )
    except Exception:
        pass

    logger.info("[ComfyUI] Starting server via comfy-cli...")
    cmd = ["comfy", "launch", "--background", "--", "--listen", "0.0.0.0", "--port", str(_comfy_port), "--highvram"]
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
        status = update.get("status") or update.get("event", "unknown")
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


async def verify_beam_token(request: Request):
    """Token gate for the storage and download apps.

    Fail CLOSED, and compare with `hmac.compare_digest` rather than `!=`: a plain
    string compare short-circuits on the first differing byte, which leaks the
    length of the shared prefix of a guessed token.

    This is the same rule `provider_core/router.py:_require_worker_token` applies
    to the worker, mirrored for the two serverless apps. `BEAM_API_KEY` is
    already in the environment of the worker that calls these routes and is the
    only shared secret between the two, so it is the one to gate on. An unset key
    refuses every call rather than opening the deployment: a storage app that
    answers /download-model, /upload-file and /delete-file to anyone who can reach
    the URL can write arbitrary bytes into a volume that holds multi-GB
    checkpoints, and this app was reachable with no gate at all.
    """
    expected = os.environ.get("BEAM_API_KEY", "").strip()
    if not expected:
        logger.error(
            "beam_token_not_configured: BEAM_API_KEY is not set in this "
            "deployment's environment; refusing to serve an unauthenticated "
            "storage API. Set it on both `beam deploy` invocations and on the worker."
        )
        raise HTTPException(
            status_code=503,
            detail={
                "message": "BEAM_API_KEY is not configured on this storage deployment",
                "retryable": False,
            },
        )

    # `provider_core/auth.py` — see there for why the comparison is done on
    # bytes: a non-ASCII header raised TypeError inside compare_digest, was
    # reported as a 500 with `retryable: true`, and the dispatcher turned a
    # malformed token into a paid retry on every other provider.
    if not token_matches(bearer_from_header(request.headers.get("Authorization")), expected):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


@storage_app.post("/setup", dependencies=[Depends(verify_beam_token)])
async def setup():
    """Initialize volume directories."""
    from provider_core.models import MODEL_DIRECTORIES
    dirs = ["/mnt/data/output", "/mnt/data/input", "/mnt/data/downloads"] + [f"/mnt/data/{d}" for d in MODEL_DIRECTORIES]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    return ok("Setup complete", directories=dirs)


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
        return failed("Invalid path", code=400)

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
            # Without this, `requests.get` blocks forever on a peer that accepts
            # the connection and then goes quiet. On the storage deployment that
            # is worse than a stuck download: the same container also serves
            # /list-models and /validate-all-models, so a wedged transfer takes
            # the whole provider's read API with it.
            request_timeout_seconds=DOWNLOAD_HTTP_TIMEOUT,
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

@storage_app.post("/download-model", dependencies=[Depends(verify_beam_token)])
async def download_model(request: Request):
    """Download a model to the volume with shared validation pipeline."""
    return await shared_download_model(await request.json())


@storage_app.post("/list-models", dependencies=[Depends(verify_beam_token)])
async def list_models(request: Request):
    """List models in a directory.

    An empty `directory` means "everything under /mnt/data", matching
    `deployables/modal/image/modal_app.py` (which maps "" to /mnt/data) and the
    deleted `direct_url` container client (which iterated all 16
    MODEL_DIRECTORIES for `directory in ("", None)`). This used to 400 on an
    empty directory, so a bare `GET /list-models` (no body ->
    ListModelsRequest(directory="")) answered 400 here, a full listing from
    direct_url, and a /mnt/data listing from Modal.
    """
    data = await request.json()
    directory = data.get("directory") or ""

    from models_utils import list_models_with_metadata_internal
    files = await list_models_with_metadata_internal("/mnt/data", directory, compute_hashes=False)

    # `files` is the key the worker's list_models reads, and the client re-wraps
    # it in the same dialect; both stay true.
    return ok(f"Listed {len(files)} models in {directory or '/'}", files=files)


@storage_app.post("/delete-model", dependencies=[Depends(verify_beam_token)])
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
            for stale in pipeline_artifacts(full_path):
                if os.path.exists(stale):
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
    return outcome(success, message)


@storage_app.post("/get-file", dependencies=[Depends(verify_beam_token)])
async def get_file(request: Request):
    """Stream a file off the volume.

    This used to do a blocking `open(full_path, "rb").read()` of the whole file
    inside an `async def`, which blocks the storage deployment's event loop for
    the length of the transfer and holds the entire file in RAM; the Beam client
    then buffered that body again and base64-decoded a third copy for the JSON
    variant. A `FileResponse` streams from disk off-thread, so nothing is
    buffered at all here.

    The size cap is a backstop against a wrong `path` turning into an
    out-of-memory kill of the storage container; override with
    `PROVIDER_GET_FILE_MAX_BYTES` if a deployment genuinely serves weights
    through this route.
    """
    data = await request.json()
    path = data.get("path")
    full_path = get_safe_path("/mnt/data", path)

    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail=f"Not found: {path}")

    max_bytes = get_file_size_cap()
    size = os.path.getsize(full_path)
    # `0` (or negative) is the documented *disable* value, not a zero-byte limit.
    # `>= 0` made an operator who set `PROVIDER_GET_FILE_MAX_BYTES=0` to disable
    # the cap get a 413 for every file — the storage app unreadable rather than
    # unlimited, from the setting that is supposed to open it up. The remote
    # agent's twin of this guard was fixed for exactly this reason and this copy
    # was not; `tests/test_provider_core_parity.py` now holds the two together.
    if max_bytes > 0 and size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"{path} is {size} bytes, over the {max_bytes} byte get-file limit",
        )

    return FileResponse(
        full_path,
        media_type="application/octet-stream",
        headers={"Content-Length": str(size)},
    )


@storage_app.post("/delete-file", dependencies=[Depends(verify_beam_token)])
async def delete_file(request: Request):
    import asyncio
    import shutil
    data = await request.json()
    path = data.get("path")
    full_path = get_safe_path("/mnt/data", path)

    def _do_delete():
        # Same sweep as /delete-model, and for the same reason. This route removed
        # only the resolved path, while /delete-model called
        # `pending_download_paths(path)` — so the same app stranded a parked
        # partial (and the per-path `.lock`) on one route and not the other, and a
        # delete that succeeded could still leave a multi-GB `.downloading` behind
        # with no way to reclaim it. `pending_download_paths` is the single helper
        # that names both the per-attempt temp and the resume slot.
        if not os.path.exists(full_path) and not list(pending_download_paths(full_path)):
            return False, f"Not found: {path}"
        try:
            if os.path.exists(full_path):
                if os.path.isdir(full_path):
                    shutil.rmtree(full_path)
                else:
                    os.remove(full_path)
            for stale in pipeline_artifacts(full_path):
                if os.path.exists(stale):
                    os.remove(stale)
        except Exception as e:
            return False, str(e)
        return True, f"Deleted {path}"
        
    success, message = await asyncio.to_thread(_do_delete)
    return outcome(success, message)


@storage_app.post("/upload-file", dependencies=[Depends(verify_beam_token)])
async def upload_file(request: Request):
    """Upload file."""
    data = await request.json()
    filename = data.get("filename")
    content_base64 = data.get("content_base64")
    directory = data.get("directory")
    if not directory:
        raise HTTPException(status_code=400, detail="directory is required")
    
    content = base64.b64decode(content_base64)
    # The backend's own pre-check (api/routes/files.py) is route-local; this is
    # the container-side half of the PROVIDER_UPLOAD_MAX_BYTES contract that
    # services/engines/base.get_upload_size_cap documents. Cap 0 = disabled.
    cap = get_upload_size_cap()
    if cap and len(content) > cap:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds the {cap}-byte upload limit",
        )
    full_path = get_safe_path("/mnt/data", f"{directory}/{filename}")
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    
    with open(full_path, "wb") as f:
        f.write(content)
    
    return ok("File uploaded", path=f"{directory}/{filename}", size=len(content))


@storage_app.post("/validate-models", dependencies=[Depends(verify_beam_token)])
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
        return failed(f"Invalid directory: {e}", code=400)

    if not os.path.exists(target_dir):
        return ok(f"{directory} does not exist", valid=[], invalid=[], partial=[], total=0)
    
    def _validate_dir():
        valid_models = []
        invalid_models = []
        partial_downloads = []
        with os.scandir(target_dir) as entries:
            for entry in entries:
                name = entry.name
                full_path = entry.path
                if is_transient_artifact(name):
                    # Reported, never deleted. Unlinking an in-flight temp leaves
                    # its writer holding a live descriptor: it finishes the
                    # transfer and then fails at os.replace, which reconciliation
                    # reports as a failed download. Unlinking a `.lock` is
                    # worse — it removes the flock a concurrent downloader
                    # holds, so a second downloader takes a *different* lock and
                    # the interleaving corruption the lock exists to prevent
                    # happens. See `provider_core/utils.py`.
                    #
                    # ORDER MATTERS, and it was wrong here. This block sat AFTER
                    # `if not is_model_file(name): continue`, and `is_model_file`
                    # is false for every `.lock` and `.downloading` name — so the
                    # branch was unreachable, `partial_downloads` was permanently
                    # `[]`, and `total_partial` was permanently 0 on this engine.
                    # Reconciliation step 0 is the only step that reads it, so it
                    # ran blind here while the image Modal app and the LLM app
                    # both classified correctly. Same three-line order as
                    # `deployables/modal/image/modal_app.py` (list_models_with_metadata_internal).
                    if not entry.is_file():
                        continue
                    partial_downloads.append({
                        "name": name,
                        "size": entry.stat().st_size,
                        "format": "partial",
                        "issues": ["Incomplete download (temp file)"],
                    })
                    continue
                # `is_model_candidate`, not `is_model_file`: this sweep runs with
                # delete_invalid=True, so it must also skip the non-model assets
                # that legitimately live in a model directory — `.txt` wildcards
                # and embeddings, `.yaml` poses. `is_model_file` only excludes
                # pipeline-owned and sidecar names, so a 200-byte wildcard list
                # was validated, failed MIN_MODEL_SIZE, and was deleted. The
                # remote agent had the identical defect.
                if not is_model_candidate(name):
                    continue
                if not entry.is_file():
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
                    # `indeterminate` means the read FAILED (EIO, ENOMEM, a
                    # gcsfuse stall) — not that the file is bad. Reconciliation
                    # runs this every 2h with `delete_invalid=True` on a network
                    # volume, so deleting here destroyed healthy 7 GB checkpoints
                    # on a transient read error, together with their .json and
                    # .preview.png sidecars. There is no way to recover a
                    # multi-GB download that was removed on a guess, so an
                    # unreadable file is reported and left alone; the next tick
                    # reads it again.
                    if delete_invalid and not validation.get("indeterminate"):
                        os.remove(full_path)
                        for ext in [".json", ".preview.png", ".sha256"]:
                            side_file = os.path.splitext(full_path)[0] + ext
                            if os.path.exists(side_file):
                                os.remove(side_file)
                else:
                    valid_models.append(model_info)
        return valid_models, invalid_models, partial_downloads

    valid_models, invalid_models, partial_downloads = await asyncio.to_thread(_validate_dir)
            
    total = len(valid_models) + len(invalid_models) + len(partial_downloads)
    # The envelope, not a bare `{directory, total, valid, ...}`. The client adopts
    # this body verbatim through `from_upstream`, which is exactly the case that
    # needs `status`/`success` present rather than inferred.
    return ok(
        f"Validated {total} files in {directory}",
        directory=directory,
        total=total,
        valid=valid_models,
        valid_count=len(valid_models),
        invalid=invalid_models,
        invalid_count=len(invalid_models),
        partial=partial_downloads,
        partial_count=len(partial_downloads),
        deleted=delete_invalid,
    )

@storage_app.post("/validate-all-models", dependencies=[Depends(verify_beam_token)])
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

    # Concurrent, not a serial loop. `validate_models` does its per-directory scan
    # in an `asyncio.to_thread` (see `_validate_dir`), so the work is designed to
    # be parallel and this function simply never awaited them together. Serially,
    # 16 directories had to fit in the caller's budget: reconciliation
    # (provider_core/reconciliation.py) caps the call at 120s and
    # `backend_v2/services/engines/beam_engine.py` (the in-process twin of the
    # deleted `beam/client.py`) at 300s. A volume with a few hundred files blew
    # that, and step 0 of reconciliation then proceeded with `total_invalid=0` —
    # orphan detection silently degraded to "nothing is invalid", which is the
    # worst possible failure direction for it.
    payloads = await asyncio.gather(*[
        validate_models(DummyRequest({"directory": directory, "delete_invalid": delete_invalid}))
        for directory in MODEL_DIRECTORIES
    ])

    for directory, res in zip(MODEL_DIRECTORIES, payloads):
        dir_key = directory.replace("models/", "")
        results["by_directory"][dir_key] = {
            "valid": res.get("valid_count", 0),
            "invalid": res.get("invalid_count", 0),
            "partial": res.get("partial_count", 0),
        }
        results["total_valid"] += res.get("valid_count", 0)
        results["total_invalid"] += res.get("invalid_count", 0)
        results["total_partial"] += res.get("partial_count", 0)

    return ok(
        f"Validated {results['total_valid']} models across {len(results['by_directory'])} directories",
        result=results,
        **results,
    )


def _realtime_token_ok(provided: str | None) -> bool:
    """Constant-time token check for the `@realtime` GPU handler.

    Fails CLOSED when `BEAM_API_KEY` is unset. An unconfigured deployment
    refusing inference is recoverable; one serving free GPU time to anyone who
    finds the URL is not.

    The comparison itself lives in `provider_core/auth.py`, shared with the
    storage/download/extractor gate on this same deployment and with the
    `X-Provider-Token` gate in the router. It encodes to bytes first, because
    `hmac.compare_digest` raises `TypeError` on a `str` holding a byte >= 0x80 and
    a WebSocket payload is decoded as latin-1 — a non-ASCII token would otherwise
    raise inside the comparison instead of being rejected.
    """
    expected = os.environ.get("BEAM_API_KEY", "").strip()
    if not expected:
        logger.error(
            "beam_token_not_configured: BEAM_API_KEY is not set on the GPU "
            "deployment; refusing to serve an unauthenticated inference endpoint."
        )
        return False
    return token_matches(provided, expected)


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

    Event format: {"token": "...", "workflow": {...}}
    Yields: Progress updates through WebSocket
    Returns: Final {"status": "success", "images": [...]}

    AUTHENTICATION. This handler bills GPU time, executes an arbitrary ComfyUI
    graph, and reads and writes the shared `/mnt/data` volume that holds the
    multi-GB checkpoints — and it was the only route on this deployment with no
    gate at all. `verify_beam_token` protects `storage_app`, `download_app` and
    `extractor_app`, but not this one, so anyone who learned the deployment URL
    got free SDXL inference. The client was already sending
    `Authorization: Bearer $BEAM_API_KEY` on the socket; nothing read it.

    The token is read from the *payload* rather than a request context. A
    `@realtime` handler's signature is what the SDK's decorator inspects, and the
    beta9 context object is not available in every version this container has
    been deployed under — a handler that took a second positional parameter
    would fail to bind rather than fail safe. The payload channel works
    identically on every version, and both ends change together in the same
    commit. Comparison is constant-time.
    """
    # Parse event if it's a string (WebSocket sends raw JSON)
    if isinstance(event, str):
        try:
            event = json.loads(event)
        except json.JSONDecodeError:
            yield json.dumps({"status": "error", "message": f"Invalid JSON: {event[:100]}"})
            return
    if not isinstance(event, dict):
        yield json.dumps({"status": "error", "message": "Expected a JSON object"})
        return

    if not _realtime_token_ok(event.get("token")):
        logger.error("[comfy_gpu] Rejected an unauthenticated inference request")
        # Close rather than continue: a rejected call must not leave the
        # container warm and billable.
        yield json.dumps({
            "status": "error",
            "message": "Unauthorized",
            "retryable": False,
        })
        return

    workflow = event.get("workflow", {})

    if not workflow:
        yield json.dumps({"status": "error", "message": "No workflow provided"})
        return  # Exit generator early

    logger.info(f"[comfy_gpu] Received workflow with {len(workflow)} nodes")

    # Stream progress updates through WebSocket
    # Note: _run_inference_realtime yields JSON strings
    async for update_json in _run_inference_realtime(workflow):
        logger.info("[comfy_gpu] Sending update through WebSocket")
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


@download_app.post("/download-model", dependencies=[Depends(verify_beam_token)])
async def download_model_endpoint(request: Request):
    """Download a model - delegated from main storage app for separate scaling."""
    data = await request.json()
    res = await shared_download_model(data)
    if res.get("status") == "success":
        return ok("Download complete", path=data.get("path"), size=res.get("size", 0))
    return failed(res.get("message", "Download failed"), code=502, retryable=True)


@asgi(
    name="comfy-download",
    cpu=DOWNLOAD_CPU,
    memory=DOWNLOAD_MEMORY,
    image=cpu_image,
    volumes=[Volume(VOL_NAME, mount_path="/mnt/data")],
    timeout=DOWNLOAD_TIMEOUT,
    keep_warm_seconds=DOWNLOAD_KEEP_WARM,
    # DOWNLOAD_CONCURRENT, not a hardcoded 1. The knob was read and never used, so
    # the only way to run two downloads at once was to edit and redeploy — and
    # the autoscaler's tasks_per_container had to agree, or Beam schedules N tasks
    # onto a container that will only serve one and the rest queue behind it.
    concurrent_requests=DOWNLOAD_CONCURRENT,
    workers=DOWNLOAD_CONCURRENT,
    autoscaler=QueueDepthAutoscaler(max_containers=DOWNLOAD_MAX_CONTAINERS, tasks_per_container=DOWNLOAD_CONCURRENT)
)
def comfy_download():
    """Dedicated download endpoint for model downloads (separate scaling from storage)."""
    return download_app


# =============================================================================
# Extractor Deployment (CPU-only node mapping)
# =============================================================================

extractor_app = FastAPI(title="ComfyUI Extractor Server")

def _extract_object_info() -> dict:
    """Launch ComfyUI on the CPU, read its /object_info, shut it down.

    Entirely synchronous, and called through `asyncio.to_thread` below. It was
    previously inline in an `async def`, where a 60 s ready-poll (`time.sleep(1)`
    per attempt) plus a 60 s `requests.get` ran straight on the event loop: the
    whole Beam extractor deployment — which serves this one route — stopped
    answering for up to two minutes at a time.
    """
    import requests
    import subprocess
    import time

    port = 8189
    logger.info("[ComfyUINodeExtractor] Starting CPU-only server...")
    cmd = ["comfy", "launch", "--", "--listen", "0.0.0.0", "--port", str(port), "--cpu"]
    server_process = subprocess.Popen(cmd)

    try:
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
            # Was a bare `{"error": ...}` at HTTP 200: indistinguishable from a
            # successful extraction that happened to return no nodes, and it
            # carried no `retryable` for the worker to relay.
            raise ExtractionNotReady(
                "ComfyUI failed to start in CPU mode for extraction"
            )

        try:
            response = requests.get(f"http://127.0.0.1:{port}/object_info", timeout=60)
            response.raise_for_status()
            data = response.json()
            logger.info(f"[Extractor] Successfully extracted object_info ({len(data)} nodes).")
            return data
        except Exception as e:
            # A real 502, not an AttributeError: the client adopts the body through
            # `from_upstream`, which keys off `status == "error"`.
            raise ExtractionFailed(
                f"Extractor could not read /object_info: {e}"
            ) from e
    finally:
        # Kill the server gracefully
        logger.info("[ComfyUINodeExtractor] Shutting down CPU server...")
        server_process.terminate()
        try:
            server_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server_process.kill()


class ExtractionNotReady(RuntimeError):
    """ComfyUI never answered within the ready-poll deadline."""


class ExtractionFailed(RuntimeError):
    """ComfyUI answered, but /object_info could not be read."""


@extractor_app.get("/object_info", dependencies=[Depends(verify_beam_token)])
async def get_object_info():
    # `data` is bound before the call, and the launch/poll/read/shutdown sequence
    # lives in a worker thread. It used to be inline, which put a 60 s
    # `time.sleep` poll and a 60 s `requests.get` on the event loop.
    try:
        data: dict = await asyncio.to_thread(_extract_object_info)
    except ExtractionNotReady as e:
        raise HTTPException(status_code=503, detail={"message": str(e), "retryable": True})
    except ExtractionFailed as e:
        raise HTTPException(status_code=502, detail={"message": str(e), "retryable": True})

    # Success is a raw pass-through of ComfyUI's own /object_info document:
    # api/routes/nodes.py returns it verbatim to the UI.
    return data

@rest_api(
    name="comfyui-extractor",
    cpu=1,
    memory="4Gi",
    # cpu_image, not gpu_image. The endpoint launches ComfyUI with `--cpu` and
    # reads its /object_info; the two other deployments on this volume already use
    # cpu_image. Declaring the GPU image here billed a ~15 GB CUDA image and
    # pinned it to a GPU for a subprocess that is explicitly told not to use one.
    image=cpu_image,
    volumes=[Volume(VOL_NAME, mount_path="/mnt/data")],
    timeout=300,
    keep_warm_seconds=0,
)
def comfy_extractor():
    """CPU endpoint for extracting ComfyUI node definitions."""
    return extractor_app
