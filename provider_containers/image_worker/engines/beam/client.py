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
    get_logger, get_http_client
)
from provider_core.background import MAX_BACKGROUND_TASKS, BackgroundTaskLimitExceeded, spawn_background_task
from provider_core.base_client import BaseProviderClient
from provider_core.http_client import get_file_size_cap, relay_bytes
from provider_core.responses import (
    config_fault_detail, failed, from_upstream, ok
)
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
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8002")
HF_TOKEN = os.getenv("HF_TOKEN", "")
CIVITAI_TOKEN = os.getenv("CIVITAI_TOKEN", "")

WS_MAX_SIZE_MB = int(os.getenv("WS_MAX_SIZE_MB", "20"))
WS_OPEN_TIMEOUT = int(os.getenv("WS_OPEN_TIMEOUT", "120"))

def get_beam_headers() -> Dict[str, str]:
    headers = {"Authorization": f"Bearer {BEAM_API_KEY}", "Content-Type": "application/json"}
    if BEAM_WORKSPACE_ID:
        headers["X-Beam-Workspace-Id"] = BEAM_WORKSPACE_ID
    return headers


def _declared_length(header_value: Optional[str]) -> Optional[int]:
    """Parse a Content-Length, or None if absent or unparseable.

    A malformed length cannot be trusted as "small", so it is treated as absent
    and the streaming ceiling in `relay_bytes` does the work instead.
    """
    if header_value is None:
        return None
    try:
        return int(header_value)
    except (TypeError, ValueError):
        return None

def _files_from(response_json: Any) -> list:
    """Pull the file list out of a /list-models body.

    Was `response.json().get("files", [])`, which raises AttributeError -> 500 the
    moment the storage app answers with a bare JSON array. The storage app
    returns a dialect dict today, but a 401/404/error body from a proxy in front of
    it, or a future shape change, turns one odd response into a 500 instead of the
    empty listing it effectively is.
    """
    if isinstance(response_json, dict):
        files = response_json.get("files")
        return files if isinstance(files, list) else []
    if isinstance(response_json, list):
        return response_json
    return []


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
                # Not retryable: an unset BEAM_API_KEY / BEAM_*_URL will not fix
                # itself, and a 503 read as retryable fails the job over to
                # another provider.
                detail=config_fault_detail(
                    "provider is not configured",
                    status="unhealthy",
                    provider_id=PROVIDER_ID,
                    ready=False,
                    missing=missing,
                ),
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
            return from_upstream(
                response.json(),
                provider=PROVIDER_ID,
                message="Setup complete",
            )
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
                logger.error(f"Beam download exception: {e}", exc_info=True)

        try:
            spawn_background_task(
                _do_download(),
                tasks=self._download_tasks,
                name=f"beam-download:{request.path}",
            )
        except BackgroundTaskLimitExceeded:
            return failed(
                f"Too many downloads already in flight for {PROVIDER_ID}; "
                f"retry once one finishes (limit {MAX_BACKGROUND_TASKS})",
                code=429,
                retryable=True,
                provider=PROVIDER_ID,
            )
        return ok(f"Download queued for {request.path}", provider=PROVIDER_ID, status="queued")

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
            return ok("Listed models", provider=PROVIDER_ID, files=_files_from(response.json()))
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
            # Adopt, rather than assume: the storage app answers HTTP 200 with
            # `success: false` for a file it could not remove, and reporting
            # that as a success is how a "deleted" model stays on the volume.
            return from_upstream(response.json(), provider=PROVIDER_ID)
        raise HTTPException(status_code=response.status_code, detail=response.text)

    async def get_file(self, path: str) -> StreamingResponse:
        """Stream the file through instead of buffering it (three times over).

        The old form did `await client.post(...)` — the whole body in memory —
        then, for the JSON variant, base64-decoded it into a *second* copy and
        handed the `Response` a third. Files served here are model sidecars and
        output images, so a bounded streaming pass is both cheaper and the only
        way a 20 GB body cannot exhaust the container.
        """
        client = get_http_client()
        max_bytes = get_file_size_cap()
        http = await client.get_client()
        request = http.build_request(
            "POST", f"{BEAM_STORAGE_URL}/get-file", json={"path": path},
            headers=get_beam_headers(), timeout=120.0,
        )
        raw = await http.send(request, stream=True)
        try:
            if raw.status_code != 200:
                await raw.aread()
                if raw.status_code == 404:
                    raise HTTPException(status_code=404, detail="File not found")
                if raw.status_code >= 500:
                    raise HTTPException(status_code=502, detail=f"Upstream storage error ({raw.status_code})")
                raise HTTPException(status_code=raw.status_code, detail=raw.text)

            content_type = str(raw.headers.get("content-type", ""))
            declared = _declared_length(raw.headers.get("content-length"))
            if declared is not None and declared > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds the {max_bytes} byte get-file limit",
                )

            if "json" in content_type.lower():
                # The base64 variant cannot be relayed without decoding it, so
                # it is the one path that has to be buffered — under the cap.
                body = await raw.aread()
                if len(body) > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the {max_bytes} byte get-file limit",
                    )
                try:
                    payload = json.loads(body)
                except ValueError:
                    return Response(content=body, media_type=content_type or "application/octet-stream")
                if isinstance(payload, dict) and payload.get("content_base64"):
                    decoded = base64.b64decode(payload["content_base64"])
                    if len(decoded) > max_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=f"File exceeds the {max_bytes} byte get-file limit",
                        )
                    return Response(
                        content=decoded,
                        media_type=payload.get("media_type", "application/octet-stream"),
                    )
                return Response(content=body, media_type=content_type or "application/octet-stream")

            return StreamingResponse(
                relay_bytes(raw, max_bytes),
                status_code=200,
                media_type=content_type or "application/octet-stream",
            )
        except BaseException:
            await raw.aclose()
            raise

    async def delete_file(self, path: str) -> Dict[str, Any]:
        client = get_http_client()
        response = await client.post(f"{BEAM_STORAGE_URL}/delete-file", json={"path": path}, headers=get_beam_headers(), timeout=60.0)
        if response.status_code == 200:
            return from_upstream(response.json(), provider=PROVIDER_ID)
        return failed(
            f"File deletion failed with status {response.status_code}",
            code=response.status_code,
            retryable=response.status_code >= 500,
            provider=PROVIDER_ID,
        )

    async def upload_file(self, request: UploadFileRequest) -> Dict[str, Any]:
        client = get_http_client()
        response = await client.post(
            f"{BEAM_STORAGE_URL}/upload-file",
            json={"filename": request.filename, "content_base64": request.content_base64, "directory": request.directory},
            headers=get_beam_headers(),
            timeout=120.0
        )
        if response.status_code == 200:
            return from_upstream(response.json(), provider=PROVIDER_ID, message="File uploaded")
        raise HTTPException(status_code=response.status_code, detail=response.text)

    async def deploy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from provider_core.deploy import start_deploy_task, get_deploy_state

        commands = [
            ["beam", "deploy", "/app/image_worker/engines/beam/beam_app.py:comfy_gpu"],
            ["beam", "deploy", "/app/image_worker/engines/beam/beam_app.py:comfy_storage"]
        ]
        self._deploy_task = start_deploy_task("Beam", commands)
        return get_deploy_state()

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
                return failed(
                    f"Validation failed for {directory} with HTTP {response.status_code}",
                    code=response.status_code,
                    retryable=response.status_code >= 500,
                    provider=PROVIDER_ID,
                    valid=[], invalid=[], partial=[], by_directory={},
                )
            payload = response.json()
            results["by_directory"][directory] = payload
            results["valid"].extend(payload.get("valid", []))
            results["invalid"].extend(payload.get("invalid", []))
            results["partial"].extend(payload.get("partial", []))
        return ok(
            f"Validated {len(results['valid'])} models across {len(results['by_directory'])} directories",
            provider=PROVIDER_ID,
            result=results,
            **results,
        )

    async def validate_all_models(self) -> Dict[str, Any]:
        client = get_http_client()
        response = await client.post(
            f"{BEAM_STORAGE_URL}/validate-all-models",
            headers=get_beam_headers(),
            timeout=300.0,
        )
        # Adopt, not raise. `raise_for_status()` produced an
        # `httpx.HTTPStatusError` that provider_core/router.py's catch-all
        # flattened to "Internal server error" (code 500), discarding the storage
        # app's status and message. The storage app answers
        # `failed(..., code=404)` / `failed(..., code=500, retryable=True)`
        # precisely so the worker can relay them.
        if response.status_code != 200:
            return failed(
                f"Validation failed with status {response.status_code}",
                code=response.status_code,
                retryable=response.status_code >= 500,
                provider=PROVIDER_ID,
            )
        return from_upstream(
            response.json(),
            provider=PROVIDER_ID,
            message="Validated all models",
        )

    async def get_object_info(self) -> Dict[str, Any]:
        client = get_http_client()
        extractor_url = BEAM_EXTRACTOR_URL or BEAM_STORAGE_URL
        response = await client.get(
            f"{extractor_url}/object_info",
            headers=get_beam_headers(),
            timeout=120.0,
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Beam extractor returned {response.status_code}: {response.text}",
            )
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
                # Not `raise_for_status()`: the router's catch-all turns that into
                # a 500 "Internal server error", so a 401 (Beam API key rejected)
                # and a 404 (storage deployment missing) both read as a worker bug.
                if response.status_code != 200:
                    raise RuntimeError(
                        f"Beam storage /list-models returned {response.status_code} "
                        f"for {directory}: {response.text}"
                    )
                return directory, _files_from(response.json())
                
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
            # Still a raise — the reconciliation download loop records a raise as a
            # failed download — but with the upstream's own status and body in the
            # message, so the failure lands in `reconciliation_state.errors` with
            # a diagnosis instead of an httpx repr.
            if response.status_code != 200:
                raise RuntimeError(
                    f"Beam /download-model returned {response.status_code} for "
                    f"{storage_path}: {response.text}"
                )
            result = response.json()
            if isinstance(result, dict) and result.get("status") == "error":
                raise RuntimeError(result.get("message", "Download failed"))
            
        async def delete_file(storage_path: str):
            client = get_http_client()
            response = await client.post(f"{BEAM_STORAGE_URL}/delete-model", json={"path": storage_path}, headers=get_beam_headers(), timeout=60.0)
            # Adopt, rather than assume. The callback contract is True/False and
            # reconciliation increments `deletions_completed` on True, so an
            # unconditional True reported a clean sweep for orphans that were
            # still on the volume. The storage app answers HTTP 200 with
            # `success: false` (beam_app.py `outcome(False, ...)`) for a file it
            # could not remove, so the flag is in the body, not the status.
            if response.status_code != 200:
                raise RuntimeError(
                    f"Beam storage /delete-model returned {response.status_code}: {response.text}"
                )
            payload = response.json()
            return bool(isinstance(payload, dict) and payload.get("success") is not False)

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
