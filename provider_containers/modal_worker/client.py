import asyncio
import os
import base64
import json
from typing import Dict, Any, Optional

from fastapi import HTTPException
from fastapi.responses import StreamingResponse, Response
import modal

from provider_core import (
    InferenceRequest, DownloadRequest, ListModelsRequest, DeleteModelRequest,
    UploadFileRequest, ValidateModelsRequest, CancelJobRequest,
    build_error_response, build_status_response, build_deploy_compatibility_response,
    get_logger
)
from provider_core.base_client import BaseProviderClient

class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):
            try:
                return obj.decode('utf-8')
            except UnicodeDecodeError:
                return base64.b64encode(obj).decode('utf-8')
        return super().default(obj)

logger = get_logger("modal_worker.client")
from provider_core.models import MODEL_DIRECTORIES


def _log_deploy_done(task: asyncio.Task):
    if task.cancelled():
        logger.warning("Modal deploy task was cancelled")
    elif task.exception():
        logger.error(f"Modal deploy task failed with unhandled exception: {task.exception()}", exc_info=task.exception())

MODAL_APP_NAME = os.getenv("MODAL_APP_NAME", "comfy-modal-stack")
MODAL_USERNAME = os.getenv("MODAL_USERNAME", "")
PROVIDER_ID = os.getenv("PROVIDER_ID", "modal-worker")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
HF_TOKEN = os.getenv("HF_TOKEN", "")
CIVITAI_TOKEN = os.getenv("CIVITAI_TOKEN", "")

_function_cache = {}

def get_modal_function(func_name: str):
    key = f"{MODAL_APP_NAME}.{func_name}"
    if key not in _function_cache:
        logger.info(f"[{PROVIDER_ID}] Caching Modal function: {key}")
        _function_cache[key] = modal.Function.from_name(MODAL_APP_NAME, func_name)
    return _function_cache[key]

class ModalProviderClient(BaseProviderClient):
    def __init__(self, runtime_config: Dict[str, Any]):
        super().__init__(PROVIDER_ID, runtime_config)
        self._deploy_task: Optional[asyncio.Task] = None

    async def get_health(self) -> Dict[str, Any]:
        missing = []
        if not MODAL_APP_NAME:
            missing.append("MODAL_APP_NAME")

        if missing:
            raise HTTPException(
                status_code=503,
                detail={"status": "unhealthy", "provider_id": PROVIDER_ID, "ready": False, "missing": missing},
            )
        return {"status": "healthy", "provider_id": PROVIDER_ID, "modal_username": MODAL_USERNAME, "modal_app": MODAL_APP_NAME, "ready": True}

    async def get_info(self) -> Dict[str, Any]:
        return {"provider_id": PROVIDER_ID, "type": "modal", "username": MODAL_USERNAME, "app_name": MODAL_APP_NAME, "containerized": True}

    async def inference(self, request: InferenceRequest) -> StreamingResponse:
        use_snapshot = request.use_snapshot
        job_id = request.job_id
        inference_timeout = max(1.0, float(request.timeout_seconds or self.runtime_config.get("inference_timeout_seconds", 3600.0)))
        class_name = "ComfyUISnapshot" # Always use snapshot per user request
        
        if job_id:
            await self.job_tracker.start_job(job_id)
        
        try:
            ComfyUIClass = modal.Cls.from_name(MODAL_APP_NAME, class_name)
            comfy_instance = ComfyUIClass()
            
            async def generate():
                try:
                    async with asyncio.timeout(inference_timeout):
                        q = asyncio.Queue()
                        
                        async def fetcher():
                            try:
                                async for update in comfy_instance.run.remote_gen.aio(request.workflow):
                                    await q.put(update)
                                await q.put(None)
                            except Exception as e:
                                await q.put(e)
                                
                        task = asyncio.create_task(fetcher())
                        
                        while True:
                            try:
                                item = await asyncio.wait_for(q.get(), timeout=2.0)
                            except asyncio.TimeoutError:
                                if job_id and await self.job_tracker.is_cancelled(job_id):
                                    task.cancel()
                                    yield json.dumps(build_error_response("Job cancelled", retryable=False)) + "\n"
                                    return
                                continue
                            
                            if item is None:
                                break
                                
                            if isinstance(item, Exception):
                                raise item
                                
                            update = item

                            if job_id and await self.job_tracker.is_cancelled(job_id):
                                task.cancel()
                                yield json.dumps(build_error_response("Job cancelled", retryable=False)) + "\n"
                                return

                            # Backwards compatibility for old Modal deployments
                            if update.get("status") == "success" and "images" in update:
                                for img in update["images"]:
                                    if isinstance(img.get("data"), bytes):
                                        img["data"] = base64.b64encode(img["data"]).decode("utf-8")
                                        img["_base64_encoded"] = True
                                    if "subfolder" not in img:
                                        img["subfolder"] = ""

                            yield json.dumps(update, cls=CustomJSONEncoder) + "\n"

                except TimeoutError:
                    yield json.dumps(build_error_response(f"Inference timed out after {int(inference_timeout)}s", retryable=True, code=408)) + "\n"
                except modal.exception.ConnectionError as ce:
                    yield json.dumps(build_error_response(f"Modal connection timeout: {ce}", retryable=True)) + "\n"
                except Exception as e:
                    yield json.dumps(build_error_response(f"Stream error: {e}", retryable=False)) + "\n"
                finally:
                    if job_id:
                        await self.job_tracker.end_job(job_id)
            
            return StreamingResponse(generate(), media_type="application/x-ndjson")
        except Exception as e:
            if job_id:
                await self.job_tracker.end_job(job_id)
            async def stream_err():
                yield json.dumps(build_error_response(f"Internal error: {e}", retryable=False, code=500)) + "\n"
            return StreamingResponse(stream_err(), status_code=500, media_type="application/x-ndjson")

    async def setup_models(self) -> Dict[str, Any]:
        setup_func = get_modal_function("setup_models")
        await setup_func.spawn.aio()
        return build_status_response("queued", "Setup queued", provider=PROVIDER_ID)

    async def download_model(self, request: DownloadRequest) -> Dict[str, Any]:
        download_func = get_modal_function("download_model")
        await download_func.spawn.aio(request.url, request.path, request.token, request.preview_url, request.metadata)
        return build_status_response("queued", f"Download queued for {request.path}", provider=PROVIDER_ID)

    async def list_models(self, request: Optional[ListModelsRequest] = None) -> Dict[str, Any]:
        directory = request.directory if request else ""
        list_func = get_modal_function("list_models_with_metadata")
        files = await list_func.remote.aio(directory)
        return build_status_response("success", f"Listed models in {directory}", provider=PROVIDER_ID, files=files)

    async def delete_model(self, request: DeleteModelRequest) -> Dict[str, Any]:
        FileStorage = modal.Cls.from_name(MODAL_APP_NAME, "FileStorage")
        storage = FileStorage()
        success = await storage.delete_file.remote.aio(request.path)
        return {"success": success, "message": f"Deleted {request.path}" if success else f"Failed to delete {request.path}", "provider": PROVIDER_ID}

    async def get_file(self, path: str) -> StreamingResponse:
        try:
            FileStorage = modal.Cls.from_name(MODAL_APP_NAME, "FileStorage")
            storage = FileStorage()
            file_contents = await storage.read_file.remote.aio(path)
            return Response(content=file_contents, media_type="application/octet-stream")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

    async def delete_file(self, path: str) -> Dict[str, Any]:
        FileStorage = modal.Cls.from_name(MODAL_APP_NAME, "FileStorage")
        storage = FileStorage()
        success = await storage.delete_file.remote.aio(path)
        return {"success": success, "message": f"Deleted {path}" if success else f"File not found: {path}"}

    async def upload_file(self, request: UploadFileRequest) -> Dict[str, Any]:
        content = base64.b64decode(request.content_base64)
        FileStorage = modal.Cls.from_name(MODAL_APP_NAME, "FileStorage")
        storage = FileStorage()
        path = f"{request.directory}/{request.filename}"
        await storage.put_file.remote.aio(path=path, content=content)
        return {"status": "success", "path": path, "size": len(content)}

    async def deploy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from provider_core.deploy import start_deploy_task
        from provider_core.base_client import _DEPLOY_STATE

        commands = [["modal", "deploy", "/app/modal_app.py"]]
        self._deploy_task = start_deploy_task("Modal", commands)
        return _DEPLOY_STATE

    async def validate_models(self, request: ValidateModelsRequest) -> Dict[str, Any]:
        validate_fn = get_modal_function("validate_models")
        return await validate_fn.remote.aio(request.directory, request.delete_invalid)

    async def validate_all_models(self) -> Dict[str, Any]:
        validate_fn = get_modal_function("validate_models")
        return await validate_fn.remote.aio(MODEL_DIRECTORIES, False)

    async def get_object_info(self) -> Dict[str, Any]:
        ComfyUINodeExtractor = modal.Cls.from_name(MODAL_APP_NAME, "ComfyUINodeExtractor")
        extractor = ComfyUINodeExtractor()
        return await extractor.get_object_info.remote.aio()

    async def run_reconciliation(self) -> Dict[str, Any]:
        async def validate_existing(delete_invalid: bool):
            validate_fn = get_modal_function("validate_models")
            timeout_seconds = max(1.0, float(self.runtime_config.get("validation_timeout_seconds", 300.0)))
            return await asyncio.wait_for(validate_fn.remote.aio(MODEL_DIRECTORIES, delete_invalid), timeout=timeout_seconds)

        async def list_existing_files():
            paths = {}
            list_models_func = get_modal_function("list_models_with_metadata")
            list_timeout_seconds = max(1.0, float(self.runtime_config.get("reconciliation_list_timeout_seconds", 3600.0)))
            for directory in MODEL_DIRECTORIES:
                try:
                    files = await asyncio.wait_for(list_models_func.remote.aio(directory), timeout=list_timeout_seconds)
                    for file_info in files: paths[f"{directory}/{file_info['name']}"] = file_info
                except asyncio.TimeoutError:
                    raise RuntimeError(f"Timeout listing {directory} on Modal after {list_timeout_seconds}s")
                except Exception as e:
                    raise RuntimeError(f"Failed to list {directory} on Modal: {e}")
            return paths

        async def download_file(download_url: str, storage_path: str, token: str = None):
            download_model_func = get_modal_function("download_model")
            result = await download_model_func.remote.aio(url=download_url, path=storage_path, token=token)
            if isinstance(result, dict) and result.get("status") == "error":
                raise RuntimeError(result.get("message", "Download failed"))

        async def delete_file(storage_path: str):
            FileStorage = modal.Cls.from_name(MODAL_APP_NAME, "FileStorage")
            storage = FileStorage()
            await storage.delete_file.remote.aio(storage_path)
            return True

        return await self._start_reconciliation_task(
            backend_url=BACKEND_URL,
            hf_token=HF_TOKEN,
            civitai_token=CIVITAI_TOKEN,
            storage_label="Modal",
            validate_existing_fn=validate_existing,
            list_existing_files_fn=list_existing_files,
            download_file_fn=download_file,
            delete_file_fn=delete_file
        )
