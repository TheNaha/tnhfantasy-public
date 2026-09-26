import asyncio
import os
import json
import time
from typing import Any, AsyncIterator, Dict, Optional

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from provider_core import (
    InferenceRequest, DownloadRequest, ListModelsRequest, DeleteModelRequest,
    UploadFileRequest, ValidateModelsRequest
)
from provider_core.background import BackgroundTaskLimitExceeded, spawn_background_task
from provider_core.base_client import BaseProviderClient

# Forward the body in chunks so peak memory is one chunk rather than one file.
_STREAM_CHUNK_BYTES = 1024 * 1024
from provider_core.responses import failed, ok, outcome
from provider_core.utils import translate_task_events, TaskEvent

PROVIDER_ID = os.getenv("PROVIDER_ID", "direct-url-worker")

# Ceiling on the /health upstream probe.
#
# This has to fit inside the *dispatcher's* budget, not the healthcheck's: the
# compose and Dockerfile healthchecks no longer probe the upstream at all (they
# call /live), but backend_v2/services/load_balancer.py:345 and
# api/routes/providers/crud.py:167 both probe /health with
# `_HTTP_HEALTH_PROBE_TIMEOUT_SECONDS = 2.0` and require HTTP 200. A probe that
# takes longer than that reads as "no answer", so a slow-but-healthy ComfyUI is
# indistinguishable from an unreachable one and the provider is excluded from
# dispatch. 1.5s leaves room for the handler, so the provider returns a definite
# 503 with a real diagnosis instead of leaving the caller to time out.
#
# GET /system_stats is a few hundred bytes and answers in single-digit
# milliseconds on a warm ComfyUI; 1.5s is a long time for it. A cold ComfyUI
# still loading a checkpoint can exceed it, and that is a real condition — it
# genuinely cannot take a job quickly — but raise it if your ComfyUI is on a
# slow link and you would rather see a timeout than an unhealthy.
HEALTH_PROBE_TIMEOUT = float(os.getenv("COMFYUI_HEALTH_PROBE_TIMEOUT", "1.5"))

# Ceiling on the cached /object_info document, in seconds.
#
# `get_storage_stats` (provider_core/base_client.py) calls `list_models` once per
# MODEL_DIRECTORIES entry — 16 — and ComfyUI's /object_info is multi-megabyte on a
# production install, so one /provider-stats click used to be 16 full downloads
# and 16 full JSON parses. OBJECT_INFO_TTL bounds how stale a listing may be.
OBJECT_INFO_CACHE_TTL = float(os.getenv("COMFYUI_OBJECT_INFO_CACHE_TTL", "30.0"))

NODE_TO_DIRECTORY = {
    "CheckpointLoaderSimple": "checkpoints",
    "CheckpointLoader": "checkpoints",
    "UNETLoader": "unet",
    "LoraLoader": "loras",
    "LoraLoaderModelOnly": "loras",
    "VAELoader": "vae",
    "ControlNetLoader": "controlnet",
    "UpscaleModelLoader": "upscale_models",
    "CLIPLoader": "clip",
    "CLIPVisionLoader": "clip_vision",
    "HypernetworkLoader": "hypernetworks",
    "DiffusersLoader": "diffusers",
    "unCLIPCheckpointLoader": "checkpoints",
}

MODEL_INPUT_NAMES = {
    "ckpt_name", "model_name", "lora_name", "vae_name", "control_net_name",
    "model_name1", "clip_name", "upscaler_name", "hypernetwork_name",
}


def _normalize_directory(directory: str | None) -> str:
    value = (directory or "").strip().strip("/")
    if value == "models":
        return ""
    if value.startswith("models/"):
        value = value[len("models/"):]
    return value


class DirectUrlProviderClient(BaseProviderClient):
    def __init__(self, runtime_config: Dict[str, Any]):
        super().__init__(PROVIDER_ID, runtime_config)
        self.comfy_url = os.getenv("COMFYUI_URL", "http://localhost:8188")
        self._http_headers = {}
        api_key = os.getenv("COMFYUI_API_KEY")
        if api_key:
            self._http_headers["Authorization"] = f"Bearer {api_key}"
        self._http = httpx.AsyncClient(
            base_url=self.comfy_url,
            timeout=30.0,
            headers=self._http_headers,
        )
        self._object_info_cache: tuple[float, Dict[str, Any]] | None = None
        # Single-flight. A plain dict cache is not enough: 16 concurrent
        # `get_storage_stats` callers all miss a cold cache at the same instant and
        # all fetch, which is the thing the cache was supposed to prevent. The lock
        # is re-checked inside, so the winner populates the cache and the other 15
        # get the same document without waiting on a second request.
        self._object_info_lock = asyncio.Lock()

    async def close(self):
        await self._http.aclose()

    async def _fetch_object_info(self) -> Dict[str, Any]:
        """The cached /object_info document.

        A failure is NOT cached: a ComfyUI that is restarting should be retried on
        the next call rather than pinned as an error for the whole TTL. The caller
        (`get_object_info`, which is a verbatim pass-through) still answers a
        `failed()` envelope, so the 502 is visible to the caller that asked.
        """
        now = time.monotonic()
        cached = self._object_info_cache
        if cached is not None and now - cached[0] < OBJECT_INFO_CACHE_TTL:
            return cached[1]

        async with self._object_info_lock:
            # Re-check: another caller may have fetched while we waited.
            cached = self._object_info_cache
            now = time.monotonic()
            if cached is not None and now - cached[0] < OBJECT_INFO_CACHE_TTL:
                return cached[1]
            response = await self._http.get("/object_info")
            response.raise_for_status()
            document = response.json()
            self._object_info_cache = (time.monotonic(), document)
            return document

    async def _object_info_or_error(self) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Fetch the cached /object_info, as `(document, error_message)`.

        One of the two is always None. The callers each build their own envelope
        from the message, because `get_object_info` is a verbatim pass-through of
        ComfyUI's own document (api/routes/nodes.py returns it to the UI) and must
        not be wrapped, while `list_models` / `validate_models` answer in the
        dialect.
        """
        try:
            return await self._fetch_object_info(), None
        except Exception as e:
            self.logger.warning(f"Failed to fetch /object_info: {e}")
            return None, str(e)

    def _iter_object_info_model_paths(self, object_info: Dict[str, Any], directory: str = "") -> list[str]:
        """Walk /object_info and yield model file paths for the given directory.

        Shared by list_models and validate_models so the NODE_TO_DIRECTORY /
        MODEL_INPUT_NAMES parsing logic lives in exactly one place.
        """
        paths: list[str] = []
        directory = _normalize_directory(directory)
        for node_type, node_info in object_info.items():
            target_dir = NODE_TO_DIRECTORY.get(node_type)
            if not target_dir:
                continue
            if directory and target_dir != directory:
                continue
            node_input = node_info.get("input", {}) or {}
            inputs = []
            if isinstance(node_input.get("required"), dict):
                inputs.extend(node_input["required"].items())
            elif isinstance(node_input.get("required"), (list, tuple)):
                inputs.extend(node_input["required"])
                
            if isinstance(node_input.get("optional"), dict):
                inputs.extend(node_input["optional"].items())
            elif isinstance(node_input.get("optional"), (list, tuple)):
                inputs.extend(node_input["optional"])
            
            for input_def in inputs:
                if not isinstance(input_def, (list, tuple)) or len(input_def) < 2:
                    continue
                input_name = input_def[0]
                if input_name not in MODEL_INPUT_NAMES:
                    continue
                model_list = input_def[1]
                if isinstance(model_list, list) and model_list:
                    choices = model_list[0] if isinstance(model_list[0], list) else model_list
                    for model_name in choices:
                        if isinstance(model_name, str) and model_name:
                            paths.append(f"{target_dir}/{model_name}")
        return sorted(set(paths))

    async def get_health(self) -> Dict[str, Any]:
        """Actually probe the configured ComfyUI server.

        This used to return `{"status": "healthy", "ready": True}` without
        touching the network, so both the Dockerfile HEALTHCHECK and the compose
        healthcheck passed and `docker compose ps` reported a provider healthy
        while its ComfyUI server was unreachable — and the backend's
        `/health` probe (services/load_balancer.py, api/routes/providers/crud.py)
        counted it as a usable target and dispatched paid jobs at it.

        Unlike the Modal/Beam engines, which deliberately never probe their
        serverless deployment because a probe costs money (VISION #4), this
        engine points at a ComfyUI server the user runs themselves: a GET of
        /system_stats is free, is always present, and returns a few hundred
        bytes.

        A dead upstream is 503 *without* a `retryable` marker, so the router
        still classifies it as transient — unlike a configuration fault, this
        one really can come back.
        """
        try:
            response = await self._http.get("/system_stats", timeout=HEALTH_PROBE_TIMEOUT)
            response.raise_for_status()
        except Exception as e:
            self.logger.warning(f"[{PROVIDER_ID}] ComfyUI health probe failed: {e}")
            raise HTTPException(
                status_code=503,
                detail={
                    "message": f"ComfyUI server is unreachable: {type(e).__name__}: {e}",
                    "status": "unhealthy",
                    "provider_id": PROVIDER_ID,
                    "ready": False,
                    "engine": "direct_url",
                },
            )
        return {
            "status": "healthy",
            "provider_id": PROVIDER_ID,
            "ready": True,
            "engine": "direct_url",
            "comfy_reachable": True,
        }

    async def get_info(self) -> Dict[str, Any]:
        # `comfy_url` is a LAN IP on most deployments. This route is
        # authenticated (see provider_core/router.py), so the address is only
        # visible to the backend.
        return {"provider_id": PROVIDER_ID, "type": "direct_url", "containerized": True, "comfy_url": self.comfy_url}

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
                    event="failed",
                    job_id=job_id,
                    message=f"Inference timed out after {int(inference_timeout)}s",
                    retryable=True,
                ).to_ndjson()
            except Exception as e:
                self.logger.exception("Inference failed")
                yield TaskEvent(event="failed", job_id=job_id, message=str(e), retryable=True).to_ndjson()
            finally:
                if job_id:
                    await self.job_tracker.end_job(job_id)

        return StreamingResponse(translate_task_events(stream(), job_id=job_id), media_type="application/x-ndjson")

    async def setup_models(self) -> Dict[str, Any]:
        return ok("Setup not needed for direct_url provider", provider=PROVIDER_ID)

    async def download_model(self, request: DownloadRequest) -> Dict[str, Any]:
        return failed(
            "Model download is not supported for direct_url providers. "
            "Please install models directly on the ComfyUI server.",
            code=501,
            provider=PROVIDER_ID,
        )

    async def list_models(self, request: Optional[ListModelsRequest] = None) -> Dict[str, Any]:
        directory = request.directory if request else ""
        object_info, error = await self._object_info_or_error()
        if error is not None:
            return failed(f"Failed to query ComfyUI: {error}", code=502, retryable=True, provider=PROVIDER_ID)

        files = [
            {"name": path.split("/", 1)[-1], "path": path, "type": "file", "size": 0}
            for path in self._iter_object_info_model_paths(object_info, directory)
        ]
        return ok(f"Listed {len(files)} models", provider=PROVIDER_ID, files=files)

    async def delete_model(self, request: DeleteModelRequest) -> Dict[str, Any]:
        return outcome(
            False,
            "Model deletion is not supported for direct_url providers.",
            provider=PROVIDER_ID,
            code=405,
        )

    async def get_file(self, path: str) -> StreamingResponse:
        """Stream the file straight through from ComfyUI.

        This was `Response(content=resp.content)`, which holds the entire file in
        the worker's memory and then in the response — two copies. A 7 GB SDXL
        checkpoint cannot survive that, and this engine fronts a ComfyUI server the
        user runs on their own hardware, which is exactly where they have a 7 GB
        checkpoint.

        `client.stream` leaves the body on the wire: ComfyUI reads from disk in
        chunks and we forward them, so peak memory is one chunk. The response is
        opened inside the generator's own context so the status is checked before
        the first byte of body is sent — after the 200 has gone out we can no
        longer turn the request into a 4xx.
        """

        async def _stream() -> AsyncIterator[bytes]:
            async with self._http.stream("GET", "/view", params={"filename": path}) as resp:
                if resp.status_code == 404:
                    raise HTTPException(status_code=404, detail=f"File not found: {path}")
                if resp.status_code >= 400:
                    raise HTTPException(
                        status_code=resp.status_code,
                        detail=f"ComfyUI returned {resp.status_code} for {path}",
                    )
                async for chunk in resp.aiter_bytes(_STREAM_CHUNK_BYTES):
                    yield chunk

        return StreamingResponse(_stream(), media_type="application/octet-stream")

    async def delete_file(self, path: str) -> Dict[str, Any]:
        return outcome(
            False,
            "File deletion is not supported for direct_url providers.",
            code=405,
        )

    async def upload_file(self, request: UploadFileRequest) -> Dict[str, Any]:
        # The backend detects this failure by `body["status"] == "error"`
        # (api/routes/files.py), which the dialect preserves.
        return failed("File upload is not supported for direct_url providers.", code=405)

    async def deploy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return ok("No deployment needed for direct_url", provider=PROVIDER_ID)

    async def validate_models(self, request: ValidateModelsRequest) -> Dict[str, Any]:
        object_info, error = await self._object_info_or_error()
        if error is not None:
            return failed(f"Failed to query ComfyUI: {error}", code=502, retryable=True, provider=PROVIDER_ID)

        target_dir = request.directory if isinstance(request.directory, str) else ""
        available = self._iter_object_info_model_paths(object_info, target_dir)

        # `available` used to be passed to build_status_response, which dropped
        # it: StatusResponse declares status/message/provider/result/files and
        # sets no model_config, so Pydantic v2's default extra='ignore'
        # discarded the entire result of the method and `validate_all_models`
        # (which delegates here) reported nothing at all. `result` is the
        # declared slot, `available` is the name the caller looks for.
        return ok(
            f"Found {len(available)} models available on ComfyUI server",
            provider=PROVIDER_ID,
            result=available,
            available=available,
        )

    async def validate_all_models(self) -> Dict[str, Any]:
        return await self.validate_models(ValidateModelsRequest(directory=""))

    async def get_object_info(self) -> Dict[str, Any]:
        # Success is a raw pass-through of ComfyUI's own document:
        # api/routes/nodes.py returns it verbatim to the UI.
        object_info, error = await self._object_info_or_error()
        if error is not None:
            return failed(f"Failed to query ComfyUI: {error}", code=502, retryable=True, provider=PROVIDER_ID)
        return object_info

    async def run_reconciliation(self, quick_sync: bool = False) -> Dict[str, Any]:
        backend_url = os.getenv("BACKEND_URL", "http://localhost:8002")
        
        async def perform_reconciliation():
            object_info, error = await self._object_info_or_error()
            if error is not None:
                self.logger.error(f"Failed to query ComfyUI: {error}")
                from provider_core.http_client import get_http_client
                from provider_core.reconciliation import push_reconciliation_event
                client = get_http_client()
                await push_reconciliation_event(
                    backend_url=backend_url,
                    provider_id=PROVIDER_ID,
                    status="failed",
                    phase="failed",
                    message=f"Failed to query ComfyUI: {error}",
                    http_client=client,
                )
                return

            paths = self._iter_object_info_model_paths(object_info, "")
            
            files = [
                {"path": path, "size_bytes": 0}
                for path in paths
            ]
            
            from provider_core.http_client import get_http_client
            client = get_http_client()
            url = f"{backend_url}/api/v2/models/register-discovered"
            payload = {
                "provider_id": PROVIDER_ID,
                "files": files,
            }
            
            try:
                response = await client.post(url, json=payload, timeout=60.0)
                if response.status_code == 200:
                    result = response.json()
                    
                    # Push a completion event so the UI updates
                    from provider_core.reconciliation import push_reconciliation_event
                    await push_reconciliation_event(
                        backend_url=backend_url,
                        provider_id=PROVIDER_ID,
                        status="completed",
                        phase="completed",
                        message=f"Discovered and registered {len(paths)} models from ComfyUI",
                        stats={"files_discovered": len(paths), "storage_bytes": 0},
                        http_client=client
                    )
                else:
                    self.logger.error(f"Failed to register models: {response.status_code}")
            except Exception as e:
                self.logger.error(f"Error communicating with backend: {e}")

        # Retained: a bare create_task is GC-eligible while the reconciliation
        # (which can run for hours, holding a download semaphore) is in flight.
        try:
            spawn_background_task(
                perform_reconciliation(),
                tasks=self._background_tasks,
                name=f"direct-url-reconcile:{PROVIDER_ID}",
            )
        except BackgroundTaskLimitExceeded:
            return failed(
                f"Reconciliation not started: {len(self._background_tasks)} background "
                f"tasks already in flight for {PROVIDER_ID}",
                code=429,
                retryable=True,
                provider=PROVIDER_ID,
            )

        return ok(
            "Reconciliation started (background task)",
            provider=PROVIDER_ID,
            status="queued",
        )
