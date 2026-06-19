import asyncio
import os
import base64
from typing import Dict, Any, Optional

from fastapi import HTTPException
from fastapi.responses import StreamingResponse, Response
import websockets
import json

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

logger = get_logger("beam_worker.client")
from provider_core.models import MODEL_DIRECTORIES

BEAM_API_KEY = os.getenv("BEAM_API_KEY", "")
BEAM_WORKSPACE_ID = os.getenv("BEAM_WORKSPACE_ID", "")
PROVIDER_ID = os.getenv("PROVIDER_ID", "beam-worker")
BEAM_GPU_TYPE = os.getenv("BEAM_GPU_TYPE", "RTX4090")
BEAM_GPU_URL = os.getenv("BEAM_GPU_URL", "")
BEAM_STORAGE_URL = os.getenv("BEAM_STORAGE_URL", "")
BEAM_DOWNLOAD_URL = os.getenv("BEAM_DOWNLOAD_URL", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
HF_TOKEN = os.getenv("HF_TOKEN", "")
CIVITAI_TOKEN = os.getenv("CIVITAI_TOKEN", "")

WS_MAX_SIZE_MB = int(os.getenv("WS_MAX_SIZE_MB", "20"))
WS_OPEN_TIMEOUT = int(os.getenv("WS_OPEN_TIMEOUT", "120"))

def get_beam_headers() -> Dict[str, str]:
    headers = {"Authorization": f"Bearer {BEAM_API_KEY}", "Content-Type": "application/json"}
    if BEAM_WORKSPACE_ID:
        headers["X-Beam-Workspace-Id"] = BEAM_WORKSPACE_ID
    return headers

class BeamProviderClient(BaseProviderClient):
    def __init__(self, runtime_config: Dict[str, Any]):
        super().__init__(PROVIDER_ID, runtime_config)

    async def get_health(self) -> Dict[str, Any]:
        missing = []
        if not BEAM_API_KEY: missing.append("BEAM_API_KEY")
        if not BEAM_GPU_URL: missing.append("BEAM_GPU_URL")
        if not BEAM_STORAGE_URL: missing.append("BEAM_STORAGE_URL")

        if missing:
            raise HTTPException(
                status_code=503,
                detail={"status": "unhealthy", "provider_id": PROVIDER_ID, "ready": False, "missing": missing},
            )

        return {"status": "healthy", "provider_id": PROVIDER_ID, "ready": True}

    async def get_info(self) -> Dict[str, Any]:
        return {
            "provider_id": PROVIDER_ID,
            "type": "beam",
            "gpu_type": BEAM_GPU_TYPE,
            "gpu_url_configured": bool(BEAM_GPU_URL),
            "storage_url_configured": bool(BEAM_STORAGE_URL),
        }

    async def get_info(self) -> Dict[str, Any]:
        return {
            "provider_id": PROVIDER_ID,
            "type": "beam",
            "gpu_type": BEAM_GPU_TYPE,
            "gpu_url_configured": bool(BEAM_GPU_URL),
            "storage_url_configured": bool(BEAM_STORAGE_URL),
        }

    async def inference(self, request: InferenceRequest) -> StreamingResponse:
        job_id = request.job_id
        inference_timeout = max(1.0, float(request.timeout_seconds or self.runtime_config.get("inference_timeout_seconds", 3600.0)))
        
        if job_id:
            await self.job_tracker.start_job(job_id)

        async def generate():
            try:
                headers = {"Authorization": f"Basic {BEAM_API_KEY}"}
                async with websockets.connect(BEAM_GPU_URL, max_size=WS_MAX_SIZE_MB * 1024 * 1024, additional_headers=headers, open_timeout=WS_OPEN_TIMEOUT) as ws:
                    await ws.send(json.dumps(request.workflow))
                    async with asyncio.timeout(inference_timeout):
                        async for message in ws:
                            if job_id and await self.job_tracker.is_cancelled(job_id):
                                yield json.dumps({"status": "cancelled", "message": "Job cancelled"}) + "\n"
                                return
                            try:
                                update = json.loads(message)
                                yield json.dumps(update, cls=CustomJSONEncoder) + "\n"
                            except json.JSONDecodeError:
                                pass
            except asyncio.TimeoutError:
                yield json.dumps(build_error_response(f"Inference timed out after {inference_timeout}s", retryable=True, code=408)) + "\n"
            except Exception as e:
                yield json.dumps(build_error_response(str(e), retryable=True)) + "\n"
            finally:
                if job_id:
                    await self.job_tracker.end_job(job_id)

        return StreamingResponse(generate(), media_type="application/x-ndjson")

    async def setup_models(self) -> Dict[str, Any]:
        client = get_http_client()
        response = await client.post(f"{BEAM_STORAGE_URL}/setup", headers=get_beam_headers(), timeout=300.0)
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)

    async def download_model(self, request: DownloadRequest) -> Dict[str, Any]:
        client = get_http_client()
        download_url = BEAM_DOWNLOAD_URL or BEAM_STORAGE_URL
        response = await client.post(
            f"{download_url}/download-model",
            json={
                "url": request.url, "path": request.path,
                "token": request.token or determine_download_token(request.url, HF_TOKEN, CIVITAI_TOKEN),
                "preview_url": request.preview_url, "metadata": request.metadata
            },
            headers=get_beam_headers(),
            timeout=1800.0
        )
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)

    async def list_models(self, request: Optional[ListModelsRequest] = None) -> Dict[str, Any]:
        client = get_http_client()
        directory = request.directory if request else ""
        response = await client.post(
            f"{BEAM_STORAGE_URL}/list-models",
            json={"directory": directory},
            headers=get_beam_headers(),
            timeout=60.0
        )
        if response.status_code == 200:
            return build_status_response("success", "Listed models", provider=PROVIDER_ID, files=response.json().get("files", []))
        raise HTTPException(status_code=response.status_code, detail=response.text)

    async def delete_model(self, request: DeleteModelRequest) -> Dict[str, Any]:
        client = get_http_client()
        response = await client.post(
            f"{BEAM_STORAGE_URL}/delete-model",
            json={"path": request.path},
            headers=get_beam_headers(),
            timeout=60.0
        )
        if response.status_code == 200:
            return {"success": True, "provider": PROVIDER_ID}
        raise HTTPException(status_code=response.status_code, detail=response.text)

    async def get_file(self, path: str) -> StreamingResponse:
        client = get_http_client()
        response = await client.post(f"{BEAM_STORAGE_URL}/get-file", json={"path": path}, headers=get_beam_headers(), timeout=120.0)
        if response.status_code == 200:
            content_type = str(response.headers.get("content-type", ""))
            if "json" in content_type.lower() or response.content[:1] in (b"{", b"["):
                try:
                    payload = response.json()
                    if isinstance(payload, dict) and payload.get("content_base64"):
                        return Response(content=base64.b64decode(payload["content_base64"]), media_type=payload.get("media_type", "application/octet-stream"))
                except Exception:
                    pass
            return Response(content=response.content, media_type=content_type or "application/octet-stream")
        raise HTTPException(status_code=404, detail="File not found")

    async def delete_file(self, path: str) -> Dict[str, Any]:
        client = get_http_client()
        response = await client.post(f"{BEAM_STORAGE_URL}/delete-file", json={"path": path}, headers=get_beam_headers(), timeout=60.0)
        return response.json() if response.status_code == 200 else {"success": False}

    async def upload_file(self, request: UploadFileRequest) -> Dict[str, Any]:
        client = get_http_client()
        response = await client.post(
            f"{BEAM_STORAGE_URL}/upload-file",
            json={"filename": request.filename, "content_base64": request.content_base64, "directory": request.directory},
            headers=get_beam_headers(),
            timeout=120.0
        )
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)

    async def deploy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return build_deploy_compatibility_response(backend_url=BACKEND_URL, provider_id=PROVIDER_ID, provider_type="beam")

    async def validate_models(self, request: ValidateModelsRequest) -> Dict[str, Any]:
        client = get_http_client()
        response = await client.post(
            f"{BEAM_STORAGE_URL}/validate-models",
            json={"directory": request.directory, "delete_invalid": request.delete_invalid},
            headers=get_beam_headers(),
            timeout=120.0
        )
        if response.status_code == 200:
            return response.json()
        return {"error": f"HTTP {response.status_code}", "valid": [], "invalid": [], "partial": []}

    async def validate_all_models(self) -> Dict[str, Any]:
        client = get_http_client()
        response = await client.post(f"{BEAM_STORAGE_URL}/validate-all-models", json={"delete_invalid": False}, headers=get_beam_headers(), timeout=120.0)
        if response.status_code == 200:
            return response.json()
        return {"error": f"HTTP {response.status_code}", "total_valid": 0, "total_invalid": 0, "total_partial": 0, "by_directory": {}}

    async def run_reconciliation(self) -> Dict[str, Any]:
        from provider_core.reconciliation import run_reconciliation_v2
        if self.reconciliation_state.status == "reconciling":
            return {"status": "already_running", "message": "Reconciliation already in progress"}
        
        async def validate_existing(delete_invalid: bool):
            client = get_http_client()
            response = await client.post(f"{BEAM_STORAGE_URL}/validate-all-models", json={"delete_invalid": delete_invalid}, headers=get_beam_headers(), timeout=120.0)
            return response.json() if response.status_code == 200 else {}

        async def list_existing_files():
            paths = set()
            client = get_http_client()
            for directory in MODEL_DIRECTORIES:
                response = await client.post(f"{BEAM_STORAGE_URL}/list-models", json={"directory": directory}, headers=get_beam_headers(), timeout=60.0)
                if response.status_code == 200:
                    for f in response.json().get("files", []):
                        paths.add(f"{directory}/{f['name']}")
            return paths

        async def download_file(download_url: str, storage_path: str, token: str = None):
            client = get_http_client()
            url = BEAM_DOWNLOAD_URL or BEAM_STORAGE_URL
            response = await client.post(f"{url}/download-model", json={"url": download_url, "path": storage_path, "token": token}, headers=get_beam_headers(), timeout=1800.0)
            if response.status_code != 200:
                raise Exception(response.text)

        async def delete_file(storage_path: str):
            client = get_http_client()
            response = await client.post(f"{BEAM_STORAGE_URL}/delete-model", json={"path": storage_path}, headers=get_beam_headers(), timeout=60.0)
            return response.status_code == 200

        async def perform_reconciliation():
            try:
                await run_reconciliation_v2(
                    provider_id=PROVIDER_ID, backend_url=BACKEND_URL, reconciliation_state=self.reconciliation_state,
                    max_concurrent_downloads=self.runtime_config["max_concurrent_downloads"],
                    hf_token=HF_TOKEN, civitai_token=CIVITAI_TOKEN, storage_label="Beam",
                    validate_existing=validate_existing, list_existing_files=list_existing_files,
                    download_file=download_file, delete_file=delete_file
                )
            except Exception as e:
                logger.exception(f"[{PROVIDER_ID}] Fatal error in reconciliation task: {e}")
                self.reconciliation_state.status = "error"

        asyncio.create_task(perform_reconciliation())
        return {"status": "started", "message": "Reconciliation started"}
