"""
Beam Provider Worker - HTTP Wrapper with Full Reconciliation
Routes requests to appropriate Beam endpoint (GPU for inference, CPU for storage).

Refactored to use shared provider_core package for common functionality.
Now includes concurrent downloads (5 parallel) and job cancellation support.
"""
import asyncio
import json
import os
import base64
from typing import Dict, List, Optional, Any
from datetime import datetime

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse, Response
import httpx
import websockets

# Import shared modules from provider_core
import sys
sys.path.insert(0, "/app")

from provider_core import (
    # Models
    InferenceRequest,
    DownloadRequest,
    ListModelsRequest,
    DeleteModelRequest,
    UploadFileRequest,
    ValidateModelsRequest,
    CancelJobRequest,
    build_error_response,
    # State
    get_reconciliation_state,
    # Reconciliation
    report_file_status_v2,
    batch_update_file_status_v2,
    push_reconciliation_event,
    get_pending_downloads,
    get_all_expected_paths,
    determine_download_token,
    calculate_safe_deletion_limit,
    run_reconciliation_v2,
    # Background
    reconciliation_loop,
    log_startup_info,
    get_job_tracker,
    build_deploy_compatibility_response,
)
from provider_core.models import MODEL_DIRECTORIES
from provider_core.sync_progress import init_sync_reporter

app = FastAPI(title="Beam Provider Worker")

# Configuration from environment
BEAM_API_KEY = os.getenv("BEAM_API_KEY", "")
BEAM_WORKSPACE_ID = os.getenv("BEAM_WORKSPACE_ID", "")
PROVIDER_ID = os.getenv("PROVIDER_ID", "beam-worker")
BEAM_GPU_TYPE = os.getenv("BEAM_GPU_TYPE", "RTX4090")
BEAM_GPU_URL = os.getenv("BEAM_GPU_URL", "")
BEAM_STORAGE_URL = os.getenv("BEAM_STORAGE_URL", "")
BEAM_DOWNLOAD_URL = os.getenv("BEAM_DOWNLOAD_URL", "")  # Separate download endpoint
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
HF_TOKEN = os.getenv("HF_TOKEN", "")
CIVITAI_TOKEN = os.getenv("CIVITAI_TOKEN", "")

# Worker settings (hot-reloadable via restart or /config endpoint)
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "5"))
VALIDATION_TIMEOUT_SECONDS = float(os.getenv("VALIDATION_TIMEOUT_SECONDS", "300"))
DOWNLOAD_TIMEOUT_SECONDS = float(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", "1800"))
WS_MAX_SIZE_MB = int(os.getenv("WS_MAX_SIZE_MB", "20"))
WS_OPEN_TIMEOUT = int(os.getenv("WS_OPEN_TIMEOUT", "120"))
INFERENCE_TIMEOUT_SECONDS = float(os.getenv("INFERENCE_TIMEOUT_SECONDS", "3600"))

# Runtime config (can be updated via /config endpoint without restart)
runtime_config = {
    "max_concurrent_downloads": MAX_CONCURRENT_DOWNLOADS,
    "validation_timeout_seconds": VALIDATION_TIMEOUT_SECONDS,
    "download_timeout_seconds": DOWNLOAD_TIMEOUT_SECONDS,
    "ws_max_size_mb": WS_MAX_SIZE_MB,
    "ws_open_timeout": WS_OPEN_TIMEOUT,
    "inference_timeout_seconds": INFERENCE_TIMEOUT_SECONDS,
}

# Initialize state and job tracker
reconciliation_state = get_reconciliation_state(PROVIDER_ID)
job_tracker = get_job_tracker()


def get_beam_headers() -> Dict[str, str]:
    """Get headers for Beam API requests."""
    headers = {"Authorization": f"Bearer {BEAM_API_KEY}", "Content-Type": "application/json"}
    if BEAM_WORKSPACE_ID:
        headers["X-Beam-Workspace-Id"] = BEAM_WORKSPACE_ID
    return headers


# ============================================
# Health & Info Endpoints
# ============================================

@app.get("/health")
async def health_check():
    """Container health check endpoint."""
    missing = []
    if not BEAM_API_KEY:
        missing.append("BEAM_API_KEY")
    if not BEAM_GPU_URL:
        missing.append("BEAM_GPU_URL")
    if not BEAM_STORAGE_URL:
        missing.append("BEAM_STORAGE_URL")

    if missing:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "provider_id": PROVIDER_ID,
                "ready": False,
                "missing": missing,
            },
        )

    return {
        "status": "healthy",
        "provider_id": PROVIDER_ID,
        "gpu_endpoint": BEAM_GPU_URL or "not configured",
        "storage_endpoint": BEAM_STORAGE_URL or "not configured",
        "has_api_key": bool(BEAM_API_KEY),
        "ready": True,
    }


@app.get("/info")
async def get_info():
    """Get provider information."""
    return {
        "provider_id": PROVIDER_ID,
        "type": "beam",
        "gpu_url": BEAM_GPU_URL,
        "storage_url": BEAM_STORAGE_URL,
        "download_url": BEAM_DOWNLOAD_URL,
        "gpu_type": BEAM_GPU_TYPE,
        "containerized": True,
    }


# ============================================
# Runtime Configuration (Hot-Reload)
# ============================================

@app.get("/config")
async def get_config():
    """Get current runtime configuration."""
    return {
        "config": runtime_config,
        "env": {
            "MAX_CONCURRENT_DOWNLOADS": MAX_CONCURRENT_DOWNLOADS,
            "VALIDATION_TIMEOUT_SECONDS": VALIDATION_TIMEOUT_SECONDS,
            "DOWNLOAD_TIMEOUT_SECONDS": DOWNLOAD_TIMEOUT_SECONDS,
            "WS_MAX_SIZE_MB": WS_MAX_SIZE_MB,
            "WS_OPEN_TIMEOUT": WS_OPEN_TIMEOUT,
            "INFERENCE_TIMEOUT_SECONDS": INFERENCE_TIMEOUT_SECONDS,
        }
    }


@app.post("/config")
async def update_config(updates: Dict[str, Any]):
    """
    Hot-reload runtime configuration without container restart.
    
    Supported keys:
    - max_concurrent_downloads: int
    - validation_timeout_seconds: float
    - download_timeout_seconds: float
    - ws_max_size_mb: int
    - ws_open_timeout: int
    - inference_timeout_seconds: float
    """
    updated = []
    for key, value in updates.items():
        if key in runtime_config:
            runtime_config[key] = value
            updated.append(key)
            print(f"[{PROVIDER_ID}] Config updated: {key} = {value}")
    
    return {
        "status": "updated",
        "updated_keys": updated,
        "config": runtime_config
    }


# ============================================
# Job Cancellation (NEW - parity with Modal)
# ============================================

@app.post("/cancel-job")
async def cancel_job_endpoint(request: CancelJobRequest):
    """
    Cancel a running job.
    For Beam, this closes the WebSocket connection.
    """
    job_id = request.job_id
    print(f"[{PROVIDER_ID}] Cancel requested for job: {job_id}")
    
    cancelled = await job_tracker.cancel_job(job_id)
    if cancelled:
        return {
            "status": "cancelled",
            "job_id": job_id,
            "message": "Job marked for cancellation, streaming will stop",
        }
    else:
        return {
            "status": "not_found",
            "job_id": job_id,
            "message": "Job not currently active on this worker",
        }


# ============================================
# Inference Endpoint (WebSocket to Beam GPU)
# ============================================

@app.post("/inference")
async def run_inference(request: InferenceRequest):
    """
    Execute workflow via GPU endpoint using WebSocket.
    Now supports job cancellation.
    """
    if not BEAM_GPU_URL:
        raise HTTPException(status_code=500, detail="BEAM_GPU_URL not configured")
    
    job_id = request.job_id
    inference_timeout = max(
        1.0,
        float(
            request.timeout_seconds
            or runtime_config.get("inference_timeout_seconds")
            or INFERENCE_TIMEOUT_SECONDS
        ),
    )
    
    # Convert HTTP URL to WebSocket URL
    ws_url = BEAM_GPU_URL.replace("https://", "wss://").replace("http://", "ws://")
    
    print(f"[{PROVIDER_ID}] Starting inference via Beam GPU WebSocket... (job_id={job_id})")
    print(f"[{PROVIDER_ID}] WebSocket URL: {ws_url}")
    
    # Track active job
    if job_id:
        await job_tracker.start_job(job_id)
    
    async def generate():
        try:
            headers = {"Authorization": f"Bearer {BEAM_API_KEY}"}
            if BEAM_WORKSPACE_ID:
                headers["X-Beam-Workspace-Id"] = BEAM_WORKSPACE_ID

            async with asyncio.timeout(inference_timeout):
                async with websockets.connect(
                    ws_url,
                    extra_headers=headers,
                    open_timeout=runtime_config["ws_open_timeout"],
                    close_timeout=10,
                    ping_interval=30,
                    ping_timeout=60,
                    max_size=runtime_config["ws_max_size_mb"] * 1024 * 1024,
                ) as websocket:
                    print(f"[{PROVIDER_ID}] WebSocket connected, sending workflow...")
                    await websocket.send(json.dumps({"workflow": request.workflow}))

                    async for message in websocket:
                        # Check if job was cancelled
                        if job_id and await job_tracker.is_cancelled(job_id):
                            print(f"[{PROVIDER_ID}] Job {job_id} cancelled, closing WebSocket")
                            await websocket.close()
                            yield json.dumps({"status": "cancelled", "message": "Job cancelled by user"}) + "\n"
                            return

                        try:
                            update = json.loads(message)

                            if update.get("status") == "progress":
                                print(f"[{PROVIDER_ID}] Progress: {update.get('value')}/{update.get('max')}")
                            elif update.get("status") == "success":
                                print(f"[{PROVIDER_ID}] ✓ Inference complete")
                                if "images" in update:
                                    print(f"[{PROVIDER_ID}] Images count: {len(update['images'])}")
                            elif update.get("status") == "error":
                                error_message = update.get("message") or update.get("error") or "Unknown worker error"
                                update = build_error_response(
                                    error_message,
                                    retryable=bool(update.get("retryable", False)),
                                    code=update.get("code"),
                                    details=update.get("details") if isinstance(update.get("details"), dict) else None,
                                )
                                print(f"[{PROVIDER_ID}] ✗ Error: {error_message}")

                            yield json.dumps(update) + "\n"

                            if update.get("status") in ("success", "error"):
                                break
                        except json.JSONDecodeError:
                            print(f"[{PROVIDER_ID}] Non-JSON message: {message[:100]}")

        except TimeoutError:
            error_msg = f"Inference timed out after {int(inference_timeout)}s"
            print(f"[{PROVIDER_ID}] {error_msg}")
            yield json.dumps(build_error_response(error_msg, retryable=True, code=408)) + "\n"
        
        except websockets.exceptions.InvalidStatusCode as e:
            error_msg = f"WebSocket rejected with status {e.status_code}"
            print(f"[{PROVIDER_ID}] {error_msg}")
            yield json.dumps(build_error_response(error_msg, retryable=True, code=e.status_code)) + "\n"
        except websockets.exceptions.WebSocketException as e:
            error_msg = f"WebSocket error: {type(e).__name__}: {str(e)}"
            print(f"[{PROVIDER_ID}] {error_msg}")
            yield json.dumps(build_error_response(error_msg, retryable=True)) + "\n"
        except Exception as e:
            error_msg = f"Inference error: {type(e).__name__}: {str(e)}"
            print(f"[{PROVIDER_ID}] {error_msg}")
            yield json.dumps(build_error_response(error_msg)) + "\n"
        finally:
            if job_id:
                await job_tracker.end_job(job_id)
    
    return StreamingResponse(generate(), media_type="application/x-ndjson")


# ============================================
# Storage Operations (HTTP to Beam Storage)
# ============================================

@app.post("/setup")
async def setup():
    """Initialize Beam volume directories."""
    print(f"[{PROVIDER_ID}] Running setup on Beam storage...")
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(f"{BEAM_STORAGE_URL}/setup", json={}, headers=get_beam_headers())
            if response.status_code == 200:
                print(f"[{PROVIDER_ID}] ✓ Setup complete")
                return response.json()
            return build_error_response(response.text or "Beam storage setup failed", code=response.status_code)
    except Exception as e:
        print(f"[{PROVIDER_ID}] Setup error: {e}")
        return build_error_response(str(e))


@app.post("/download-model")
async def download_model(request: DownloadRequest):
    """Download model to Beam storage."""
    print(f"[{PROVIDER_ID}] Queueing download: {request.path}")
    try:
        async with httpx.AsyncClient(timeout=1800.0) as client:
            download_url = BEAM_DOWNLOAD_URL or BEAM_STORAGE_URL
            response = await client.post(
                f"{download_url}/download-model",
                json={
                    "url": request.url,
                    "path": request.path,
                    "token": request.token or HF_TOKEN or CIVITAI_TOKEN,
                    "preview_url": request.preview_url,
                    "metadata": request.metadata,
                },
                headers=get_beam_headers(),
            )
            if response.status_code == 200:
                print(f"[{PROVIDER_ID}] ✓ Download queued: {request.path}")
                return response.json()
            return build_error_response(response.text or f"Download queue failed for {request.path}", code=response.status_code)
    except Exception as e:
        print(f"[{PROVIDER_ID}] Download error: {e}")
        return build_error_response(str(e))


async def download_model_internal(url: str, path: str, token: str = None) -> Dict:
    """Internal helper for downloading models."""
    try:
        download_url = BEAM_DOWNLOAD_URL or BEAM_STORAGE_URL
        async with httpx.AsyncClient(timeout=1800.0) as client:
            response = await client.post(
                f"{download_url}/download-model",
                json={"url": url, "path": path, "token": token},
                headers=get_beam_headers(),
            )
            if response.status_code == 200:
                return response.json()
            raise Exception(f"HTTP {response.status_code}")
    except Exception as e:
        print(f"[{PROVIDER_ID}] Download error: {e}")
        raise


@app.post("/list-models")
@app.get("/list-models")
async def list_models(request: ListModelsRequest = None, directory: str = None):
    """List models in Beam storage directory."""
    dir_to_list = directory or (request.directory if request else "models/checkpoints")
    print(f"[{PROVIDER_ID}] Listing models in {dir_to_list}")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{BEAM_STORAGE_URL}/list-models",
                json={"directory": dir_to_list},
                headers=get_beam_headers(),
            )
            if response.status_code == 200:
                result = response.json()
                print(f"[{PROVIDER_ID}] Found {len(result.get('files', []))} models")
                return result
            return build_error_response(response.text or f"List models failed for {dir_to_list}", code=response.status_code)
    except Exception as e:
        print(f"[{PROVIDER_ID}] List models error: {e}")
        return build_error_response(str(e))


async def list_models_internal(directory: str) -> List[Dict]:
    """Internal helper for listing models."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{BEAM_STORAGE_URL}/list-models",
                json={"directory": directory},
                headers=get_beam_headers(),
            )
            if response.status_code == 200:
                return response.json().get("files", [])
    except Exception as e:
        print(f"[{PROVIDER_ID}] Error listing {directory}: {e}")
    return []


async def delete_model_internal(path: str) -> bool:
    """Internal helper for deleting models."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.request(
                "DELETE",
                f"{BEAM_STORAGE_URL}/delete-model",
                json={"path": path},
                headers=get_beam_headers(),
            )
            if response.status_code == 200:
                return True

            if response.status_code in {404, 405, 422}:
                response = await client.post(
                    f"{BEAM_STORAGE_URL}/delete-model",
                    json={"path": path},
                    headers=get_beam_headers(),
                )
                return response.status_code == 200

            return False
    except Exception:
        return False


@app.get("/beam-stats")
async def get_beam_stats():
    """Get model counts per directory from Beam storage."""
    stats = {}
    total = 0
    
    for d in MODEL_DIRECTORIES:
        try:
            files = await list_models_internal(d)
            count = len(files)
        except Exception:
            count = 0
        stats[d.replace("models/", "")] = count
        total += count
    
    return {"provider_id": PROVIDER_ID, "total": total, "by_directory": stats}


@app.delete("/delete-model")
@app.post("/delete-model")
async def delete_model(
    request: Optional[DeleteModelRequest] = Body(default=None),
    path: Optional[str] = Query(default=None),
):
    """Delete model from Beam storage."""
    model_path = request.path if request and request.path else path
    if not model_path:
        raise HTTPException(status_code=422, detail="path is required")

    print(f"[{PROVIDER_ID}] Deleting model: {model_path}")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.request(
                "DELETE",
                f"{BEAM_STORAGE_URL}/delete-model",
                json={"path": model_path},
                headers=get_beam_headers(),
            )
            if response.status_code in {404, 405, 422}:
                response = await client.post(
                    f"{BEAM_STORAGE_URL}/delete-model",
                    json={"path": model_path},
                    headers=get_beam_headers(),
                )

            if response.status_code == 200:
                print(f"[{PROVIDER_ID}] ✓ Deleted: {model_path}")
                return response.json()
            return {"success": False, "code": response.status_code}
    except Exception as e:
        print(f"[{PROVIDER_ID}] Delete error: {e}")
        return {"success": False, "message": str(e)}


@app.get("/get-file/{path:path}")
async def get_file(path: str = None):
    """Get file from Beam storage."""
    print(f"[{PROVIDER_ID}] Getting file: {path}")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{BEAM_STORAGE_URL}/get-file",
                json={"path": path},
                headers=get_beam_headers(),
            )
            if response.status_code == 200:
                content_type = response.headers.get("content-type", "") or ""
                if not isinstance(content_type, str):
                    content_type = str(content_type)
                if "json" in content_type.lower() or response.content[:1] in (b"{", b"["):
                    try:
                        payload = response.json()
                    except Exception:
                        payload = None
                    if isinstance(payload, dict) and payload.get("content_base64"):
                        import base64

                        return Response(
                            content=base64.b64decode(payload["content_base64"]),
                            media_type=payload.get("media_type", "application/octet-stream"),
                        )

                return Response(
                    content=response.content,
                    media_type=content_type or "application/octet-stream",
                )
            raise HTTPException(status_code=404, detail=f"Not found: {path}")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[{PROVIDER_ID}] Get file error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/delete-file/{path:path}")
async def delete_file(path: str = None):
    """Delete file from Beam storage."""
    print(f"[{PROVIDER_ID}] Deleting file: {path}")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{BEAM_STORAGE_URL}/delete-file",
                json={"path": path},
                headers=get_beam_headers(),
            )
            if response.status_code == 200:
                return response.json()
            return {"success": False}
    except Exception as e:
        print(f"[{PROVIDER_ID}] Delete file error: {e}")
        return {"success": False, "message": str(e)}


@app.post("/upload-file")
async def upload_file(request: UploadFileRequest):
    """Upload file to Beam storage."""
    print(f"[{PROVIDER_ID}] Uploading file: {request.directory}/{request.filename}")
    try:
        content_size = len(base64.b64decode(request.content_base64))
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{BEAM_STORAGE_URL}/upload-file",
                json={
                    "filename": request.filename,
                    "content_base64": request.content_base64,
                    "directory": request.directory,
                },
                headers=get_beam_headers(),
            )
            if response.status_code == 200:
                print(f"[{PROVIDER_ID}] ✓ Uploaded {content_size} bytes")
                return response.json()
            return {"success": False, "code": response.status_code}
    except Exception as e:
        print(f"[{PROVIDER_ID}] Upload file error: {e}")
        return {"success": False, "message": str(e)}


# ============================================
# Deploy Info (Beam-specific)
# ============================================

@app.post("/deploy")
async def deploy_info():
    """Compatibility endpoint; backend orchestrator is the source of truth for deploys."""
    return build_deploy_compatibility_response(
        backend_url=BACKEND_URL,
        provider_id=PROVIDER_ID,
        provider_type="beam",
    )


# ============================================
# Model Validation
# ============================================

@app.post("/validate-models")
async def validate_models(request: ValidateModelsRequest):
    """Validate models in a directory via Beam storage."""
    print(f"[{PROVIDER_ID}] Validating models in {request.directory}...")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{BEAM_STORAGE_URL}/validate-models",
                json={"directory": request.directory, "delete_invalid": request.delete_invalid},
                headers=get_beam_headers(),
            )
            if response.status_code == 200:
                result = response.json()
                print(f"[{PROVIDER_ID}] ✓ Validation: {result.get('valid_count', 0)} valid, {result.get('invalid_count', 0)} invalid")
                return result
            return {"error": f"HTTP {response.status_code}", "valid": [], "invalid": [], "partial": []}
    except Exception as e:
        print(f"[{PROVIDER_ID}] Validate error: {e}")
        return {"error": str(e), "valid": [], "invalid": [], "partial": []}


@app.post("/validate-all-models")
async def validate_all_models(delete_invalid: bool = False):
    """Validate all model directories."""
    print(f"[{PROVIDER_ID}] Validating ALL model directories...")
    
    results = {"total_valid": 0, "total_invalid": 0, "total_partial": 0, "by_directory": {}}
    
    for directory in MODEL_DIRECTORIES:
        try:
            result = await validate_models(ValidateModelsRequest(directory=directory, delete_invalid=delete_invalid))
            dir_key = directory.replace("models/", "")
            results["by_directory"][dir_key] = {
                "valid": result.get("valid_count", 0),
                "invalid": result.get("invalid_count", 0),
                "partial": result.get("partial_count", 0),
            }
            results["total_valid"] += result.get("valid_count", 0)
            results["total_invalid"] += result.get("invalid_count", 0)
            results["total_partial"] += result.get("partial_count", 0)
        except Exception as e:
            print(f"[{PROVIDER_ID}] Error validating {directory}: {e}")
    
    print(f"[{PROVIDER_ID}] Validation: {results['total_valid']} valid, {results['total_invalid']} invalid")
    return results


# ============================================
# Reconciliation Endpoints
# ============================================

@app.post("/reconcile")
async def trigger_reconciliation(use_v2: bool = True):
    """Trigger model reconciliation."""
    if reconciliation_state.status == "reconciling":
        return {"status": "already_running", "message": "Reconciliation already in progress"}
    
    asyncio.create_task(perform_reconciliation_v2())
    return {"status": "started", "message": f"Reconciliation started (V2={use_v2})"}


@app.get("/reconciliation-status")
async def get_reconciliation_status():
    """Get current reconciliation status."""
    return reconciliation_state.to_dict()


async def perform_reconciliation_v2():
    async def validate_existing(delete_invalid: bool):
        return await validate_all_models(delete_invalid=delete_invalid)

    async def list_existing_files():
        paths = set()
        for directory in MODEL_DIRECTORIES:
            files = await list_models_internal(directory)
            for file_info in files:
                paths.add(f"{directory}/{file_info['name']}")
        return paths

    async def download_file(download_url: str, storage_path: str, token: str = None):
        return await download_model_internal(url=download_url, path=storage_path, token=token)

    async def delete_file(storage_path: str):
        return await delete_model_internal(storage_path)

    await run_reconciliation_v2(
        provider_id=PROVIDER_ID,
        backend_url=BACKEND_URL,
        reconciliation_state=reconciliation_state,
        max_concurrent_downloads=runtime_config["max_concurrent_downloads"],
        hf_token=HF_TOKEN,
        civitai_token=CIVITAI_TOKEN,
        storage_label="Beam",
        validate_existing=validate_existing,
        list_existing_files=list_existing_files,
        download_file=download_file,
        delete_file=delete_file,
    )


# ============================================
# Startup & Background Tasks
# ============================================

@app.on_event("startup")
async def startup_event():
    """Start background tasks on worker startup."""
    log_startup_info(
        provider_id=PROVIDER_ID,
        provider_type="beam",
        backend_url=BACKEND_URL,
        extra_vars={
            "BEAM_GPU_URL": BEAM_GPU_URL,
            "BEAM_STORAGE_URL": BEAM_STORAGE_URL,
            "BEAM_GPU_TYPE": BEAM_GPU_TYPE,
        },
    )
    
    # Initialize sync progress reporter
    init_sync_reporter(PROVIDER_ID, BACKEND_URL)
    
    # Start reconciliation loop
    asyncio.create_task(reconciliation_loop(PROVIDER_ID, BACKEND_URL))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
