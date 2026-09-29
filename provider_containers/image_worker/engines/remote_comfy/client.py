import asyncio
import os
import json
import time
import urllib.parse
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
import httpx

from provider_core import (
    InferenceRequest, DownloadRequest, ListModelsRequest, DeleteModelRequest,
    UploadFileRequest, ValidateModelsRequest,
    get_logger, get_http_client
)
from provider_core.background import MAX_BACKGROUND_TASKS, BackgroundTaskLimitExceeded, spawn_background_task
from provider_core.base_client import BaseProviderClient
from provider_core.responses import failed, files_from, from_upstream, ok
from provider_core.utils import translate_task_events, TaskEvent
from provider_core.reconciliation import determine_download_token

# Forward the body in chunks so peak memory is one chunk rather than one file.
_STREAM_CHUNK_BYTES = 1024 * 1024
# Long enough for a multi-GB checkpoint to arrive, short enough that a
# dead agent does not hold the worker.
_GET_FILE_TIMEOUT_SECONDS = 600.0

# Ceiling on EACH of the two /health upstream probes, which run concurrently.
# It has to fit inside the *dispatcher's* budget rather than the healthcheck's:
# the compose and Dockerfile healthchecks no longer probe the upstream at all
# (they call /live), but backend_v2/services/load_balancer.py:345 and
# api/routes/providers/crud.py:167 probe /health with
# `_HTTP_HEALTH_PROBE_TIMEOUT_SECONDS = 2.0` and require HTTP 200, so anything
# slower reads as "no answer" and the provider is excluded from dispatch.
# Kept in step with direct_url's COMFYUI_HEALTH_PROBE_TIMEOUT for the same reason.
HEALTH_PROBE_TIMEOUT = float(os.getenv("REMOTE_HEALTH_PROBE_TIMEOUT", "1.5"))

# Ceiling on the cached /object_info document, in seconds. Same reasoning as
# direct_url's COMFYUI_OBJECT_INFO_CACHE_TTL: `get_storage_stats` calls
# `list_models` once per MODEL_DIRECTORIES entry (16), and ComfyUI's /object_info
# is multi-megabyte on a production install.
OBJECT_INFO_CACHE_TTL = float(os.getenv("COMFYUI_OBJECT_INFO_CACHE_TTL", "30.0"))

from provider_core.models import MODEL_DIRECTORIES

logger = get_logger("image_worker.remote_comfy.client")

PROVIDER_ID = os.getenv("PROVIDER_ID", "remote-comfy-worker")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8002")
HF_TOKEN = os.getenv("HF_TOKEN", "")
CIVITAI_TOKEN = os.getenv("CIVITAI_TOKEN", "")
REMOTE_AGENT_URL = os.getenv("REMOTE_AGENT_URL", "http://localhost:8001")


class RemoteComfyProviderClient(BaseProviderClient):
    def __init__(self, runtime_config: Dict[str, Any]):
        super().__init__(PROVIDER_ID, runtime_config)
        self.comfy_url = os.getenv("COMFYUI_URL", "http://localhost:8188")
        self._download_tasks: set = set()
        headers = {}
        api_key = os.getenv("COMFYUI_API_KEY", "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._http = httpx.AsyncClient(base_url=self.comfy_url, timeout=30.0, headers=headers)
        self._object_info_cache: tuple[float, Dict[str, Any]] | None = None
        # Single-flight: 16 concurrent get_storage_stats callers must cause ONE
        # fetch, not 16. Re-checked inside the lock, so the winner populates the
        # cache and the rest get the same document without a second request.
        self._object_info_lock = asyncio.Lock()

    async def close(self):
        await self._http.aclose()

    async def _fetch_object_info(self) -> Dict[str, Any]:
        """The cached /object_info document. A failure is not cached."""
        now = time.monotonic()
        cached = self._object_info_cache
        if cached is not None and now - cached[0] < OBJECT_INFO_CACHE_TTL:
            return cached[1]

        async with self._object_info_lock:
            cached = self._object_info_cache
            now = time.monotonic()
            if cached is not None and now - cached[0] < OBJECT_INFO_CACHE_TTL:
                return cached[1]
            resp = await self._http.get("/object_info")
            resp.raise_for_status()
            document = resp.json()
            self._object_info_cache = (time.monotonic(), document)
            return document

    def get_agent_headers(self) -> Dict[str, str]:
        agent_token = os.getenv("REMOTE_AGENT_TOKEN", "")
        headers = {"Content-Type": "application/json"}
        if agent_token:
            headers["Authorization"] = f"Bearer {agent_token}"
        return headers

    async def get_health(self) -> Dict[str, Any]:
        """Probe the remote ComfyUI and the remote agent.

        This returned a hardcoded `{"status": "healthy", "ready": True}` without
        touching the network. The backend's `_check_provider_health`
        (services/load_balancer.py) requires HTTP 200, so it counted this
        provider as a usable target and dispatched paid jobs at it; the first job
        then failed at `/prompt`, and because every httpx error in this file is
        marked `retryable=True` (provider_core/responses.py) the balancer retried
        across every other provider — spending money on requests that cannot
        succeed.

        `direct_url` is the same shape of bug and was already fixed
        (direct_url/client.py), by doing a real `GET /system_stats`; that is the
        fix, applied to the sibling that shares the code path. Unlike the
        Modal/Beam engines, which deliberately never probe their serverless
        deployment because a probe costs money (VISION #4), this engine fronts a
        ComfyUI the user runs themselves and an agent on the same rig, so a GET of
        /system_stats and a GET of the agent's /health are free.

        A dead upstream is 503 *without* a `retryable` marker, so the router keeps
        classifying it as transient — unlike a configuration fault, this one really
        can come back.
        """
        details: Dict[str, Any] = {}
        failures: List[str] = []

        async def _probe_comfy() -> Optional[str]:
            try:
                response = await self._http.get("/system_stats", timeout=HEALTH_PROBE_TIMEOUT)
                response.raise_for_status()
                return None
            except Exception as e:
                return f"ComfyUI server is unreachable: {type(e).__name__}: {e}"

        async def _probe_agent() -> Optional[str]:
            try:
                agent_response = await get_http_client().get(
                    f"{REMOTE_AGENT_URL}/health",
                    headers=self.get_agent_headers(),
                    timeout=HEALTH_PROBE_TIMEOUT,
                )
                agent_response.raise_for_status()
                return None
            except Exception as e:
                return f"Remote agent is unreachable: {type(e).__name__}: {e}"

        # Concurrently, because the dispatcher probes /health with
        # `_HTTP_HEALTH_PROBE_TIMEOUT_SECONDS = 2.0`
        # (backend_v2/services/load_balancer.py:345) and requires HTTP 200. Two
        # sequential 1.5s probes would take 3s on a fully dead rig and the
        # dispatcher would time out rather than read the 503.
        comfy_error, agent_error = await asyncio.gather(_probe_comfy(), _probe_agent())

        details["comfy_reachable"] = comfy_error is None
        details["agent_reachable"] = agent_error is None
        for error in (comfy_error, agent_error):
            if error:
                self.logger.warning(f"[{PROVIDER_ID}] health probe failed: {error}")
                failures.append(error)

        if failures:
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "; ".join(failures),
                    "status": "unhealthy",
                    "provider_id": PROVIDER_ID,
                    "ready": False,
                    "engine": "remote_comfy",
                    **details,
                },
            )

        return {
            "status": "healthy",
            "provider_id": PROVIDER_ID,
            "ready": True,
            "engine": "remote_comfy",
            **details,
        }

    async def get_info(self) -> Dict[str, Any]:
        return {
            "provider_id": PROVIDER_ID,
            "type": "remote_comfy",
            "comfy_url_configured": bool(self.comfy_url),
            "remote_agent_url_configured": bool(REMOTE_AGENT_URL),
        }

    async def inference(self, request: InferenceRequest) -> StreamingResponse:
        from image_worker.comfy.workflow_executor import execute_comfy_workflow, IMAGE_FETCH_VIEW_API

        job_id = request.job_id
        inference_timeout = max(1.0, float(request.timeout_seconds or self.runtime_config.get("inference_timeout_seconds", 3600.0)))

        if job_id:
            await self.job_tracker.start_job(job_id)

        async def stream():
            try:
                async with asyncio.timeout(inference_timeout):
                    async for payload in execute_comfy_workflow(
                        workflow_json=request.workflow,
                        comfy_api_url=self.comfy_url,
                        image_fetch_mode=IMAGE_FETCH_VIEW_API,
                        logger=self.logger,
                    ):
                        if job_id and await self.job_tracker.is_cancelled(job_id):
                            try:
                                await self._http.post("/interrupt", timeout=5.0)
                            except Exception as e:
                                self.logger.warning(f"Failed to interrupt ComfyUI after cancel: {e}")
                            yield TaskEvent(event="cancelled", job_id=job_id, message="Job cancelled").to_ndjson()
                            return
                        yield json.dumps(payload) + "\n"
            except TimeoutError:
                yield TaskEvent(
                    event="failed", job_id=job_id, message=f"Inference timed out after {int(inference_timeout)}s", retryable=True
                ).to_ndjson()
            except Exception as e:
                self.logger.exception("Inference failed")
                yield TaskEvent(event="failed", job_id=job_id, message=str(e), retryable=True).to_ndjson()
            finally:
                if job_id:
                    await self.job_tracker.end_job(job_id)

        return StreamingResponse(translate_task_events(stream(), job_id=job_id), media_type="application/x-ndjson")

    async def setup_models(self) -> Dict[str, Any]:
        client = get_http_client()
        response = await client.post(f"{REMOTE_AGENT_URL}/setup", headers=self.get_agent_headers(), timeout=60.0)
        if response.status_code == 200:
            return from_upstream(response.json(), provider=PROVIDER_ID, message="Setup complete")
        return failed(
            f"Setup failed with status {response.status_code}",
            code=response.status_code,
            retryable=response.status_code >= 500,
            provider=PROVIDER_ID,
        )

    async def download_model(self, request: DownloadRequest) -> Dict[str, Any]:
        client = get_http_client()
        async def _do_download():
            try:
                response = await client.post(
                    f"{REMOTE_AGENT_URL}/download-model",
                    json={
                        "url": request.url, "path": request.path,
                        "token": request.token or determine_download_token(request.url, HF_TOKEN, CIVITAI_TOKEN),
                    },
                    headers=self.get_agent_headers(),
                    timeout=1800.0
                )
                if response.status_code != 200:
                    logger.error(f"Remote Agent download failed: {response.text}")
            except Exception as e:
                logger.error(f"Remote Agent download exception: {e}", exc_info=True)

        # Retained: a bare create_task is GC-eligible while the multi-GB
        # download is still in flight.
        try:
            spawn_background_task(
                _do_download(),
                tasks=self._download_tasks,
                name=f"remote-comfy-download:{request.path}",
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
            f"{REMOTE_AGENT_URL}/list-models",
            json={"directory": directory},
            headers=self.get_agent_headers(),
            timeout=60.0
        )
        if response.status_code == 200:
            # `files_from`, not `.get("files", [])`: the agent's own dialect is a
            # dict today, but a proxy in front of it answering a bare JSON array
            # (or a 401 HTML page) turned this into an AttributeError and a 500
            # that discarded the real status — an odd upstream body read as a
            # worker bug rather than the empty listing it effectively is.
            return ok("Listed models", provider=PROVIDER_ID, files=files_from(response.json()))
        return failed(
            f"Listing models failed with status {response.status_code}",
            code=response.status_code,
            retryable=response.status_code >= 500,
            provider=PROVIDER_ID,
        )

    async def delete_model(self, request: DeleteModelRequest) -> Dict[str, Any]:
        client = get_http_client()
        response = await client.post(
            f"{REMOTE_AGENT_URL}/delete-model",
            json={"path": request.path},
            headers=self.get_agent_headers(),
            timeout=60.0
        )
        if response.status_code == 200:
            # Adopt, rather than assume: the agent answers HTTP 200 with
            # `{"success": false, "message": "File not found"}` (server.py:262-263),
            # and `outcome(True, ...)` turned that into a success here — so the
            # backend dropped the provider-file row while the bytes stayed on the
            # rig. Same reasoning as Beam's delete_model (beam/client.py).
            return from_upstream(response.json(), provider=PROVIDER_ID)
        return failed(
            f"Deletion failed with status {response.status_code}",
            code=response.status_code,
            retryable=response.status_code >= 500,
            provider=PROVIDER_ID,
        )

    async def get_file(self, path: str) -> StreamingResponse:
        """Stream the file straight through from the remote agent.

        The agent owns storage, so this reads from DATA_DIR via /get-file rather
        than ComfyUI's /view (which only serves output/ images and 404s for
        model-dir metadata/preview sidecars). This mirrors how the Modal/Beam
        engines back get_file with their own FileStorage.read_file.

        It was `Response(content=response.content)` — the agent's whole file, held
        once in the agent, then again in this worker, then again in the response.
        Three copies of a 7 GB checkpoint. `client.stream` keeps the body in flight
        instead, so peak memory here is one chunk on each side.
        """
        client = get_http_client()
        # `quote(..., safe="/")`, exactly as the backend quotes the same path in
        # `infrastructure/providers/provider_registry.py`. A model path is a path
        # segment, and `#`, `?` and `%` are all legal in one: unquoted, a
        # checkpoint called `flux#1.safetensors` requested everything up to the
        # `#` and the agent answered 404 for a file it is holding.
        url = f"{REMOTE_AGENT_URL}/get-file/{urllib.parse.quote(path, safe='/')}"

        async def _stream() -> AsyncIterator[bytes]:
            async with client.stream(
                "GET",
                url,
                headers=self.get_agent_headers(),
                timeout=_GET_FILE_TIMEOUT_SECONDS,
            ) as response:
                if response.status_code == 404:
                    raise HTTPException(status_code=404, detail=f"File not found: {path}")
                if response.status_code >= 400:
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Remote agent returned {response.status_code} for {path}",
                    )
                async for chunk in response.aiter_bytes(_STREAM_CHUNK_BYTES):
                    yield chunk

        return StreamingResponse(_stream(), media_type="application/octet-stream")

    async def delete_file(self, path: str) -> Dict[str, Any]:
        client = get_http_client()
        response = await client.post(f"{REMOTE_AGENT_URL}/delete-file", json={"path": path}, headers=self.get_agent_headers(), timeout=60.0)
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
            f"{REMOTE_AGENT_URL}/upload-file",
            json={"filename": request.filename, "content_base64": request.content_base64, "directory": request.directory},
            headers=self.get_agent_headers(),
            timeout=120.0
        )
        if response.status_code == 200:
            return from_upstream(response.json(), provider=PROVIDER_ID, message="File uploaded")
        return failed(
            f"File upload failed with status {response.status_code}",
            code=response.status_code,
            retryable=response.status_code >= 500,
            provider=PROVIDER_ID,
        )

    async def deploy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return ok("No deployment needed for remote_comfy", provider=PROVIDER_ID)

    async def validate_models(self, request: ValidateModelsRequest) -> Dict[str, Any]:
        client = get_http_client()
        results = {"by_directory": {}, "valid": [], "invalid": [], "partial": []}
        for directory in request.directories:
            response = await client.post(
                f"{REMOTE_AGENT_URL}/validate-models",
                json={"directory": directory, "delete_invalid": request.delete_invalid},
                headers=self.get_agent_headers(),
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
            f"{REMOTE_AGENT_URL}/validate-all-models",
            headers=self.get_agent_headers(),
            timeout=300.0,
        )
        # Adopt, not raise. `raise_for_status()` produced an
        # `httpx.HTTPStatusError` that provider_core/router.py's catch-all
        # flattened to "Internal server error" (code 500), discarding the agent's
        # status, message and body — a 401 from a misconfigured
        # REMOTE_AGENT_TOKEN became indistinguishable from a worker bug. The rest
        # of this file already answers 4xx/5xx with `failed(code=..., retryable=...)`.
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
        # Success is a raw pass-through of ComfyUI's own document:
        # api/routes/nodes.py returns it verbatim to the UI.
        try:
            return await self._fetch_object_info()
        except Exception as e:
            return failed(f"Failed to query ComfyUI: {e}", code=502, retryable=True, provider=PROVIDER_ID)

    async def run_reconciliation(self, quick_sync: bool = False) -> Dict[str, Any]:
        async def validate_existing(delete_invalid: bool):
            client = get_http_client()
            response = await client.post(f"{REMOTE_AGENT_URL}/validate-all-models", json={"delete_invalid": delete_invalid}, headers=self.get_agent_headers(), timeout=120.0)
            return response.json() if response.status_code == 200 else {}

        async def list_existing_files():
            paths = {}
            client = get_http_client()

            async def _fetch_dir(directory: str):
                response = await client.post(f"{REMOTE_AGENT_URL}/list-models", json={"directory": directory}, headers=self.get_agent_headers(), timeout=3600.0)
                # Not `raise_for_status()`: the router's catch-all turns that into
                # a 500 "Internal server error", so a 401 (agent token mismatch)
                # and a 404 (agent not deployed) both read as a worker bug. The
                # status and the agent's own message are the diagnosis.
                if response.status_code != 200:
                    raise RuntimeError(
                        f"Remote agent /list-models returned {response.status_code} "
                        f"for {directory}: {response.text}"
                    )
                return directory, files_from(response.json())

            results = await asyncio.gather(*[_fetch_dir(d) for d in MODEL_DIRECTORIES])
            for directory, files in results:
                for f in files:
                    paths[f"{directory}/{f['name']}"] = f
                    
            return paths

        async def download_file(download_url: str, storage_path: str, token: str = None):
            client = get_http_client()
            response = await client.post(
                f"{REMOTE_AGENT_URL}/download-model",
                json={
                    "url": download_url, "path": storage_path,
                    "token": token or determine_download_token(download_url, HF_TOKEN, CIVITAI_TOKEN),
                },
                headers=self.get_agent_headers(),
                timeout=1800.0
            )
            # Still a raise — the reconciliation download loop records a raise as a
            # failed download — but with the agent's own status and body in the
            # message, so the failure lands in `reconciliation_state.errors` with a
            # diagnosis instead of an httpx repr.
            if response.status_code != 200:
                raise RuntimeError(
                    f"Remote agent /download-model returned {response.status_code} for "
                    f"{storage_path}: {response.text}"
                )
            result = response.json()
            if isinstance(result, dict) and result.get("status") == "error":
                raise RuntimeError(result.get("message", "Download failed"))
            
        async def delete_file(storage_path: str):
            client = get_http_client()
            response = await client.post(f"{REMOTE_AGENT_URL}/delete-model", json={"path": storage_path}, headers=self.get_agent_headers(), timeout=60.0)
            # Adopt, rather than assume. The callback contract is True/False and
            # reconciliation increments `deletions_completed` on True, so an
            # unconditional True reported a clean sweep for orphans that were
            # still on the rig. The agent answers HTTP 200 with
            # `{"success": false, "message": "File not found"}`
            # (remote_agent/server.py:262-263), so the flag is in the body, not
            # the status.
            if response.status_code != 200:
                raise RuntimeError(
                    f"Remote agent /delete-model returned {response.status_code}: {response.text}"
                )
            payload = response.json()
            return bool(isinstance(payload, dict) and payload.get("success") is not False)

        return await self._start_reconciliation_task(
            backend_url=BACKEND_URL,
            hf_token=HF_TOKEN,
            civitai_token=CIVITAI_TOKEN,
            storage_label="RemoteComfy",
            validate_existing_fn=validate_existing,
            list_existing_files_fn=list_existing_files,
            download_file_fn=download_file,
            delete_file_fn=delete_file,
            quick_sync=quick_sync,
        )
