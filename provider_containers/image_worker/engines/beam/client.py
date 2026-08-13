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
    UploadFileRequest, ValidateModelsRequest,
    build_error_response, build_status_response,
    get_logger, get_http_client
)
from provider_core.base_client import BaseProviderClient
from provider_core.utils import translate_task_events, TaskEvent
from provider_core.reconciliation import determine_download_token

class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):
            try:
                return obj.decode('utf-8')
            except UnicodeDecodeError:
                return base64.b64encode(obj).decode('utf-8')
        return super().default(obj)

logger = get_logger("image_worker.beam.client")
from provider_core.models import MODEL_DIRECTORIES

BEAM_API_KEY = os.getenv("BEAM_API_KEY", "")
BEAM_WORKSPACE_ID = os.getenv("BEAM_WORKSPACE_ID", "")
PROVIDER_ID = os.getenv("PROVIDER_ID", "beam-worker")
BEAM_GPU_TYPE = os.getenv("BEAM_GPU_TYPE", "RTX4090")
BEAM_GPU_URL = os.getenv("BEAM_GPU_URL", "")
BEAM_STORAGE_URL = os.getenv("BEAM_STORAGE_URL", "")
BEAM_DOWNLOAD_URL = os.getenv("BEAM_DOWNLOAD_URL", "")
BEAM_EXTRACTOR_URL = os.getenv("BEAM_EXTRACTOR_URL", "")
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
        self._deploy_task: Optional[asyncio.Task] = None
        self._download_tasks: set = set()

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

        # Local-only health check per VISION #4: never ping the remote
        # serverless deployment from health checks (serverless billing risk).
        return {"status": "healthy", "provider_id": PROVIDER_ID, "ready": True}

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
        use_snapshot = bool(getattr(request, "use_snapshot", False))

        if job_id:
            await self.job_tracker.start_job(job_id)

        async def generate():
            try:
                task = None
                async with asyncio.timeout(inference_timeout):
                    q = asyncio.Queue()

                    async def fetcher():
                        try:
                            headers = {"Authorization": f"Bearer {BEAM_API_KEY}"}
                            async with websockets.connect(
                                BEAM_GPU_URL,
                                max_size=WS_MAX_SIZE_MB * 1024 * 1024,
                                additional_headers=headers,
                                open_timeout=WS_OPEN_TIMEOUT,
                            ) as ws:
                                payload = {"workflow": request.workflow}
                                if use_snapshot:
                                    payload["use_snapshot"] = True
                                await ws.send(json.dumps(payload))
                                async for message in ws:
                                    if job_id and await self.job_tracker.is_cancelled(job_id):
                                        return
                                    await q.put(message)
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
                                yield TaskEvent(event="cancelled", job_id=job_id, message="Job cancelled").to_ndjson()
                                return
                            continue

                        if item is None:
                            break

                        if isinstance(item, Exception):
                            raise item

                        message = item
                        if isinstance(message, bytes):
                            message = message.decode("utf-8")

                        if job_id and await self.job_tracker.is_cancelled(job_id):
                            task.cancel()
                            yield TaskEvent(event="cancelled", job_id=job_id, message="Job cancelled").to_ndjson()
                            return

                        yield message + "\n"

                if task is not None:
                    task.cancel()
            except asyncio.TimeoutError:
                yield TaskEvent(event="failed", job_id=job_id, message=str(f"Inference timed out after {int(inference_timeout)}s"), retryable=True).to_ndjson()
            except websockets.exceptions.ConnectionClosedError as e:
                yield TaskEvent(event="failed", job_id=job_id, message=str(f"Websocket connection closed with error: {str(e)}"), retryable=True).to_ndjson()
            except websockets.exceptions.ConnectionClosed:
                yield TaskEvent(event="failed", job_id=job_id, message="Websocket connection closed unexpectedly", retryable=True).to_ndjson()
            except Exception as e:
                yield TaskEvent(event="failed", job_id=job_id, message=str(f"Stream error: {e}"), retryable=True).to_ndjson()
            finally:
                if task is not None:
                    task.cancel()
                if job_id:
                    await self.job_tracker.end_job(job_id)

        return StreamingResponse(translate_task_events(generate(), job_id=job_id), media_type="application/x-ndjson")

    async def setup_models(self) -> Dict[str, Any]:
        client = get_http_client()
        response = await client.post(f"{BEAM_STORAGE_URL}/setup", headers=get_beam_headers(), timeout=300.0)
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)

    async def download_model(self, request: DownloadRequest) -> Dict[str, Any]:
        client = get_http_client()
        download_url = BEAM_DOWNLOAD_URL or BEAM_STORAGE_URL
        
        async def _do_download():
            try:
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
                if response.status_code != 200:
                    logger.error(f"Beam download failed with status {response.status_code}: {response.text}")
            except Exception as e:
                logger.error(f"Beam download exception: {e}")

        task = asyncio.create_task(_do_download())
        self._download_tasks.add(task)
        task.add_done_callback(self._download_tasks.discard)
        return build_status_response("queued", f"Download queued for {request.path}", provider=PROVIDER_ID)

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
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="File not found")
        if response.status_code >= 500:
            raise HTTPException(status_code=502, detail=f"Upstream storage error ({response.status_code})")
        raise HTTPException(status_code=response.status_code, detail=response.text)

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
        from provider_core.deploy import start_deploy_task
        from provider_core.base_client import _DEPLOY_STATE
        
        commands = [
            ["beam", "deploy", "/app/image_worker/engines/beam/beam_app.py:comfy_gpu"],
            ["beam", "deploy", "/app/image_worker/engines/beam/beam_app.py:comfy_storage"]
        ]
        self._deploy_task = start_deploy_task("Beam", commands)
        return _DEPLOY_STATE

    async def validate_models(self, request: ValidateModelsRequest) -> Dict[str, Any]:
        client = get_http_client()
        results = {"by_directory": {}, "valid": [], "invalid": [], "partial": []}
        for directory in request.directories:
            response = await client.post(
                f"{BEAM_STORAGE_URL}/validate-models",
                json={"directory": directory, "delete_invalid": request.delete_invalid},
                headers=get_beam_headers(),
                timeout=120.0
            )
            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}", "valid": [], "invalid": [], "partial": []}
            payload = response.json()
            results["by_directory"][directory] = payload
            results["valid"].extend(payload.get("valid", []))
            results["invalid"].extend(payload.get("invalid", []))
            results["partial"].extend(payload.get("partial", []))
        return results

    async def validate_all_models(self) -> Dict[str, Any]:
        client = get_http_client()
        response = await client.post(
            f"{BEAM_STORAGE_URL}/validate-all-models",
            headers=get_beam_headers(),
            timeout=300.0,
        )
        response.raise_for_status()
        return response.json()

    async def get_object_info(self) -> Dict[str, Any]:
        client = get_http_client()
        extractor_url = BEAM_EXTRACTOR_URL or BEAM_STORAGE_URL
        response = await client.get(
            f"{extractor_url}/object_info",
            headers=get_beam_headers(),
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()

    async def run_reconciliation(self, quick_sync: bool = False) -> Dict[str, Any]:
        async def validate_existing(delete_invalid: bool):
            client = get_http_client()
            response = await client.post(f"{BEAM_STORAGE_URL}/validate-all-models", json={"delete_invalid": delete_invalid}, headers=get_beam_headers(), timeout=120.0)
            return response.json() if response.status_code == 200 else {}

        async def list_existing_files():
            paths = {}
            client = get_http_client()
            
            async def _fetch_dir(directory: str):
                response = await client.post(f"{BEAM_STORAGE_URL}/list-models", json={"directory": directory}, headers=get_beam_headers(), timeout=3600.0)
                response.raise_for_status()
                return directory, response.json().get("files", [])
                
            results = await asyncio.gather(*[_fetch_dir(d) for d in MODEL_DIRECTORIES])
            for directory, files in results:
                for f in files:
                    paths[f"{directory}/{f['name']}"] = f
                    
            return paths

        async def download_file(download_url: str, storage_path: str, token: str = None):
            client = get_http_client()
            download_endpoint = BEAM_DOWNLOAD_URL or BEAM_STORAGE_URL
            response = await client.post(
                f"{download_endpoint}/download-model",
                json={
                    "url": download_url, "path": storage_path,
                    "token": token or determine_download_token(download_url, HF_TOKEN, CIVITAI_TOKEN),
                },
                headers=get_beam_headers(),
                timeout=1800.0
            )
            response.raise_for_status()
            result = response.json()
            if isinstance(result, dict) and result.get("status") == "error":
                raise RuntimeError(result.get("message", "Download failed"))
            
        async def delete_file(storage_path: str):
            client = get_http_client()
            response = await client.post(f"{BEAM_STORAGE_URL}/delete-model", json={"path": storage_path}, headers=get_beam_headers(), timeout=60.0)
            response.raise_for_status()
            return True

        return await self._start_reconciliation_task(
            backend_url=BACKEND_URL,
            hf_token=HF_TOKEN,
            civitai_token=CIVITAI_TOKEN,
            storage_label="Beam",
            validate_existing_fn=validate_existing,
            list_existing_files_fn=list_existing_files,
            download_file_fn=download_file,
            delete_file_fn=delete_file,
            quick_sync=quick_sync,
        )
