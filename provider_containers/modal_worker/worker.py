"""
Modal Provider Worker - HTTP Wrapper
This service receives HTTP requests and calls Modal functions using containerized credentials.

Refactored to use shared provider_core package for common functionality.
"""
import asyncio
import json
import os
import base64
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, Response
import modal

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
    build_status_response,
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

app = FastAPI(title="Modal Provider Worker")

# Configuration from environment
MODAL_APP_NAME = os.getenv("MODAL_APP_NAME", "comfy-modal-stack")
MODAL_USERNAME = os.getenv("MODAL_USERNAME", "")
PROVIDER_ID = os.getenv("PROVIDER_ID", "modal-worker")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
HF_TOKEN = os.getenv("HF_TOKEN", "")
CIVITAI_TOKEN = os.getenv("CIVITAI_TOKEN", "")

# Worker settings (hot-reloadable via restart or /config endpoint)
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "5"))
VALIDATION_TIMEOUT_SECONDS = float(os.getenv("VALIDATION_TIMEOUT_SECONDS", "300"))
RECONCILIATION_LIST_TIMEOUT_SECONDS = float(os.getenv("RECONCILIATION_LIST_TIMEOUT_SECONDS", "45"))
RECONCILIATION_INTERVAL_SECONDS = int(os.getenv("RECONCILIATION_INTERVAL_SECONDS", "7200"))
RECONCILIATION_STARTUP_DELAY_SECONDS = int(os.getenv("RECONCILIATION_STARTUP_DELAY_SECONDS", "130"))
INFERENCE_TIMEOUT_SECONDS = float(os.getenv("INFERENCE_TIMEOUT_SECONDS", "3600"))

# Runtime config (can be updated via /config endpoint without restart)
runtime_config = {
    "max_concurrent_downloads": MAX_CONCURRENT_DOWNLOADS,
    "validation_timeout_seconds": VALIDATION_TIMEOUT_SECONDS,
    "reconciliation_list_timeout_seconds": RECONCILIATION_LIST_TIMEOUT_SECONDS,
    "reconciliation_interval_seconds": RECONCILIATION_INTERVAL_SECONDS,
    "reconciliation_startup_delay_seconds": RECONCILIATION_STARTUP_DELAY_SECONDS,
    "inference_timeout_seconds": INFERENCE_TIMEOUT_SECONDS,
}

# Function cache for Modal functions
_function_cache = {}

_background_tasks: list[asyncio.Task] = []

# Initialize state and job tracker
reconciliation_state = get_reconciliation_state(PROVIDER_ID)
job_tracker = get_job_tracker()


def get_modal_function(func_name: str):
    """Get Modal function with caching."""
    key = f"{MODAL_APP_NAME}.{func_name}"
    if key not in _function_cache:
        print(f"[{PROVIDER_ID}] Caching Modal function: {key}")
        _function_cache[key] = modal.Function.from_name(MODAL_APP_NAME, func_name)
    return _function_cache[key]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup and shutdown hooks for the worker."""
    log_startup_info(
        provider_id=PROVIDER_ID,
        provider_type="modal",
        backend_url=BACKEND_URL,
        extra_vars={"MODAL_USERNAME": MODAL_USERNAME, "MODAL_APP_NAME": MODAL_APP_NAME},
    )

    _background_tasks.append(
        asyncio.create_task(
            reconciliation_loop(
                PROVIDER_ID,
                BACKEND_URL,
                interval_seconds=int(runtime_config.get("reconciliation_interval_seconds") or RECONCILIATION_INTERVAL_SECONDS),
                startup_delay_seconds=int(runtime_config.get("reconciliation_startup_delay_seconds") or RECONCILIATION_STARTUP_DELAY_SECONDS),
            )
        )
    )

    try:
        yield
    finally:
        for task in _background_tasks:
            task.cancel()
        if _background_tasks:
            await asyncio.gather(*_background_tasks, return_exceptions=True)
        _background_tasks.clear()


app.router.lifespan_context = lifespan


# ============================================
# Health & Info Endpoints
# ============================================

@app.get("/health")
async def health_check():
    """Container health check endpoint."""
    missing = []
    if not MODAL_APP_NAME:
        missing.append("MODAL_APP_NAME")

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
        "modal_username": MODAL_USERNAME,
        "modal_app": MODAL_APP_NAME,
        "ready": True,
    }


@app.get("/info")
async def get_info():
    """Get provider information."""
    return {
        "provider_id": PROVIDER_ID,
        "type": "modal",
        "username": MODAL_USERNAME,
        "app_name": MODAL_APP_NAME,
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
            "RECONCILIATION_LIST_TIMEOUT_SECONDS": RECONCILIATION_LIST_TIMEOUT_SECONDS,
            "RECONCILIATION_INTERVAL_SECONDS": RECONCILIATION_INTERVAL_SECONDS,
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
    - reconciliation_list_timeout_seconds: float
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
# Job Cancellation
# ============================================

@app.post("/cancel-job")
async def cancel_job_endpoint(request: CancelJobRequest):
    """
    Cancel a running job.
    Marks the job as cancelled so streaming stops.
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
# Inference Endpoint
# ============================================

@app.post("/inference")
async def run_inference(request: InferenceRequest):
    """
    Execute ComfyUI workflow via Modal.
    Streams progress updates as newline-delimited JSON.
    """
    use_snapshot = request.use_snapshot
    job_id = request.job_id
    inference_timeout = max(
        1.0,
        float(
            request.timeout_seconds
            or runtime_config.get("inference_timeout_seconds")
            or INFERENCE_TIMEOUT_SECONDS
        ),
    )
    mode_name = "SNAPSHOT (experimental)" if use_snapshot else "STABLE"
    class_name = "ComfyUISnapshot" if use_snapshot else "ComfyUIStable"
    
    print(f"[{PROVIDER_ID}] Starting inference in {mode_name} mode... (job_id={job_id})")
    print(f"[{PROVIDER_ID}] Calling Modal class: {class_name}")
    
    # Track active job
    if job_id:
        await job_tracker.start_job(job_id)
    
    try:
        ComfyUIClass = modal.Cls.from_name(MODAL_APP_NAME, class_name)
        comfy_instance = ComfyUIClass()
        
        async def generate():
            try:
                async with asyncio.timeout(inference_timeout):
                    async for update in comfy_instance.run.remote_gen.aio(request.workflow):
                        # Check if job was cancelled
                        if job_id and await job_tracker.is_cancelled(job_id):
                            print(f"[{PROVIDER_ID}] Job {job_id} cancelled, aborting stream")
                            yield json.dumps({"status": "cancelled", "message": "Job cancelled by user"}) + "\n"
                            return

                        # Debug logging for success updates
                        if update.get("status") == "success":
                            print(f"[{PROVIDER_ID}] Modal returned SUCCESS")
                            if "images" in update:
                                print(f"[{PROVIDER_ID}] Images count from Modal: {len(update['images'])}")
                            else:
                                print(f"[{PROVIDER_ID}] WARNING: Modal returned success but NO images key!")

                        # Normalize image payloads for backend-side persistence.
                        if update.get("status") == "success" and "images" in update:
                            saved_images = []
                            for i, img in enumerate(update["images"]):
                                if "data" in img and isinstance(img["data"], bytes):
                                    # Encode as base64
                                    img_b64 = base64.b64encode(img["data"]).decode('utf-8')
                                    saved_images.append({
                                        "filename": img.get("filename", f"image_{i}.png"),
                                        "data": img_b64,
                                        "_base64_encoded": True
                                    })

                            # Replace images with saved versions
                            update["images"] = saved_images

                        yield json.dumps(update) + "\n"

            except TimeoutError:
                error_msg = f"Inference timed out after {int(inference_timeout)}s"
                print(f"[{PROVIDER_ID}] {error_msg}")
                yield json.dumps(build_error_response(error_msg, retryable=True, code=408)) + "\n"
            
            except modal.exception.ConnectionError as ce:
                # Modal connection timeout - likely happened after job executed but before results streamed
                error_msg = f"Modal connection timeout: {ce}"
                print(f"[{PROVIDER_ID}] {error_msg}")
                yield json.dumps(build_error_response(error_msg, retryable=True)) + "\n"
            
            except Exception as e:
                # Other errors during streaming
                error_msg = f"Stream error: {e}"
                print(f"[{PROVIDER_ID}] {error_msg}")
                yield json.dumps(build_error_response(error_msg, retryable=False)) + "\n"
            
            finally:
                if job_id:
                    await job_tracker.end_job(job_id)
        
        return StreamingResponse(generate(), media_type="application/x-ndjson")
    
    except Exception as e:
        if job_id:
            await job_tracker.end_job(job_id)
        print(f"[{PROVIDER_ID}] Inference error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Model Management Endpoints
# ============================================

@app.post("/setup")
async def setup_models_endpoint():
    """Queue setup_models to initialize Modal directories and default assets."""
    print(f"[{PROVIDER_ID}] Running setup_models...")
    try:
        setup_func = get_modal_function("setup_models")
        # Setup may include long-running downloads; queue work and return quickly.
        await setup_func.spawn.aio()
        return build_status_response("queued", "Setup queued", provider=PROVIDER_ID)
    except Exception as e:
        print(f"[{PROVIDER_ID}] Setup error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/download-model")
async def download_model(request: DownloadRequest):
    """Queue model download via Modal."""
    print(f"[{PROVIDER_ID}] Queueing download: {request.path}")
    try:
        download_func = get_modal_function("download_model")
        await download_func.spawn.aio(
            request.url,
            request.path,
            request.token,
            request.preview_url,
            request.metadata,
        )
        return build_status_response("queued", f"Download queued for {request.path}", provider=PROVIDER_ID)
    except Exception as e:
        print(f"[{PROVIDER_ID}] Download error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/list-models")
async def list_models(request: ListModelsRequest):
    """List models in directory via Modal."""
    print(f"[{PROVIDER_ID}] Listing models in {request.directory}")
    try:
        list_func = get_modal_function("list_models_with_metadata")
        files = await list_func.remote.aio(request.directory)
        return build_status_response("success", f"Listed models in {request.directory}", provider=PROVIDER_ID, files=files)
    except Exception as e:
        print(f"[{PROVIDER_ID}] List models error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/modal-stats")
async def get_modal_stats():
    """Get model counts per directory from Modal storage."""
    directories = MODEL_DIRECTORIES
    
    stats = {}
    total = 0
    
    try:
        list_func = get_modal_function("list_models_with_metadata")
        async def _count_directory(directory: str):
            short_name = directory.replace("models/", "")
            try:
                files = await asyncio.wait_for(list_func.remote.aio(directory), timeout=45.0)
                return short_name, len(files) if files else 0
            except Exception as e:
                print(f"[{PROVIDER_ID}] Error listing {directory}: {type(e).__name__}: {e}")
                return short_name, 0

        counts = await asyncio.gather(*(_count_directory(directory) for directory in directories))
        for short_name, count in counts:
            stats[short_name] = count
            total += count
        
        return {"provider_id": PROVIDER_ID, "total": total, "by_directory": stats}
    except Exception as e:
        print(f"[{PROVIDER_ID}] Modal stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/delete-model")
async def delete_model(request: DeleteModelRequest):
    """Delete model from Modal storage."""
    print(f"[{PROVIDER_ID}] Deleting model: {request.path}")
    try:
        FileStorage = modal.Cls.from_name(MODAL_APP_NAME, "FileStorage")
        storage = FileStorage()
        success = await storage.delete_file.remote.aio(request.path)
        return {
            "success": success,
            "message": f"Deleted {request.path}" if success else f"Failed to delete {request.path}",
            "provider": PROVIDER_ID,
        }
    except Exception as e:
        print(f"[{PROVIDER_ID}] Delete error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# File Storage Endpoints
# ============================================

@app.get("/get-file/{path:path}")
async def get_file(path: str):
    """Get file from Modal volume via FileStorage."""
    print(f"[{PROVIDER_ID}] Getting file: {path}")
    try:
        FileStorage = modal.Cls.from_name(MODAL_APP_NAME, "FileStorage")
        storage = FileStorage()
        file_contents = await storage.get_file.remote.aio(path)
        return Response(content=file_contents, media_type="application/octet-stream")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    except Exception as e:
        print(f"[{PROVIDER_ID}] Get file error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/delete-file/{path:path}")
async def delete_file_endpoint(path: str):
    """Delete file from Modal volume via FileStorage."""
    print(f"[{PROVIDER_ID}] Deleting file: {path}")
    try:
        FileStorage = modal.Cls.from_name(MODAL_APP_NAME, "FileStorage")
        storage = FileStorage()
        success = await storage.delete_file.remote.aio(path)
        return {"success": success, "message": f"Deleted {path}" if success else f"File not found: {path}"}
    except Exception as e:
        print(f"[{PROVIDER_ID}] Delete file error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/upload-file")
async def upload_file_to_modal(request: UploadFileRequest):
    """Upload a file to Modal volume."""
    print(f"[{PROVIDER_ID}] Uploading file: {request.directory}/{request.filename}")
    try:
        content = base64.b64decode(request.content_base64)
        FileStorage = modal.Cls.from_name(MODAL_APP_NAME, "FileStorage")
        storage = FileStorage()
        path = f"{request.directory}/{request.filename}"
        await storage.put_file.remote.aio(path=path, content=content)
        print(f"[{PROVIDER_ID}] ✓ Uploaded {len(content)} bytes to {path}")
        return {"status": "success", "path": path, "size": len(content)}
    except Exception as e:
        print(f"[{PROVIDER_ID}] Upload file error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Deploy Endpoint (Modal-specific)
# ============================================

@app.post("/deploy")
async def deploy_modal_app():
    """Compatibility endpoint; backend orchestrator is the source of truth for deploys."""
    return build_deploy_compatibility_response(
        backend_url=BACKEND_URL,
        provider_id=PROVIDER_ID,
        provider_type="modal",
    )


# ============================================
# Model Validation
# ============================================

@app.post("/validate-models")
async def validate_models_endpoint(request: ValidateModelsRequest):
    """Validate all models in a directory."""
    print(f"[{PROVIDER_ID}] Validating models in {request.directory}...")
    try:
        validate_fn = get_modal_function("validate_models")
        result = await validate_fn.remote.aio(request.directory, request.delete_invalid)
        
        valid_count = result.get("valid_count", 0)
        invalid_count = result.get("invalid_count", 0)
        partial_count = result.get("partial_count", 0)
        
        print(f"[{PROVIDER_ID}] ✓ Validation: {valid_count} valid, {invalid_count} invalid, {partial_count} partial")
        return result
    except Exception as e:
        print(f"[{PROVIDER_ID}] Validate error: {e}")
        return {"error": str(e), "valid": [], "invalid": [], "partial": []}


@app.post("/validate-all-models")
async def validate_all_models_endpoint(delete_invalid: bool = False):
    """Validate all model directories."""
    print(f"[{PROVIDER_ID}] Validating ALL model directories...")
    
    results = {"total_valid": 0, "total_invalid": 0, "total_partial": 0, "by_directory": {}}
    
    try:
        validate_fn = get_modal_function("validate_models")
        batch_result = await asyncio.wait_for(
            validate_fn.remote.aio(MODEL_DIRECTORIES, delete_invalid),
            timeout=runtime_config["validation_timeout_seconds"],
        )
        if batch_result:
            results = batch_result
    except asyncio.TimeoutError:
        print(f"[{PROVIDER_ID}] Timeout waiting for batch validation")
    except Exception as e:
        print(f"[{PROVIDER_ID}] Error in batch validation: {e}")
    
    print(f"[{PROVIDER_ID}] Validation: {results.get('total_valid', 0)} valid, {results.get('total_invalid', 0)} invalid")
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
        validate_fn = get_modal_function("validate_models")
        timeout_seconds = max(
            1.0,
            float(runtime_config.get("validation_timeout_seconds") or VALIDATION_TIMEOUT_SECONDS),
        )
        try:
            return await asyncio.wait_for(
                validate_fn.remote.aio(MODEL_DIRECTORIES, delete_invalid),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise RuntimeError(f"validate_models timed out after {int(timeout_seconds)}s") from exc
        except Exception as exc:
            message = str(exc).strip() or repr(exc)
            raise RuntimeError(f"validate_models failed: {type(exc).__name__}: {message}") from exc

    async def list_existing_files():
        paths = set()
        list_models_func = get_modal_function("list_models_with_metadata")
        list_timeout_seconds = max(
            1.0,
            float(runtime_config.get("reconciliation_list_timeout_seconds") or RECONCILIATION_LIST_TIMEOUT_SECONDS),
        )
        for directory in MODEL_DIRECTORIES:
            try:
                files = await asyncio.wait_for(
                    list_models_func.remote.aio(directory),
                    timeout=list_timeout_seconds,
                )
                for file_info in files:
                    paths.add(f"{directory}/{file_info['name']}")
            except asyncio.TimeoutError:
                print(
                    f"[V2 Reconciliation] Warning: Timeout listing {directory} "
                    f"after {int(list_timeout_seconds)}s"
                )
            except Exception as exc:
                message = str(exc).strip() or repr(exc)
                print(
                    f"[V2 Reconciliation] Warning: Error listing {directory}: "
                    f"{type(exc).__name__}: {message}"
                )
        return paths

    async def download_file(download_url: str, storage_path: str, token: str = None):
        download_model_func = get_modal_function("download_model")
        await download_model_func.remote.aio(url=download_url, path=storage_path, token=token)

    async def delete_file(storage_path: str):
        delete_file_func = get_modal_function("storage_delete_file")
        await delete_file_func.remote.aio(storage_path)
        return True

    await run_reconciliation_v2(
        provider_id=PROVIDER_ID,
        backend_url=BACKEND_URL,
        reconciliation_state=reconciliation_state,
        max_concurrent_downloads=runtime_config["max_concurrent_downloads"],
        hf_token=HF_TOKEN,
        civitai_token=CIVITAI_TOKEN,
        storage_label="Modal",
        validate_existing=validate_existing,
        list_existing_files=list_existing_files,
        download_file=download_file,
        delete_file=delete_file,
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
