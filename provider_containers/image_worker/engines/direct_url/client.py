import asyncio
import os
import json
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse, Response

from provider_core import (
    InferenceRequest, DownloadRequest, ListModelsRequest, DeleteModelRequest,
    UploadFileRequest, ValidateModelsRequest, build_status_response, build_error_response
)
from provider_core.base_client import BaseProviderClient
from provider_core.utils import translate_task_events, TaskEvent

PROVIDER_ID = os.getenv("PROVIDER_ID", "direct-url-worker")

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


class DirectUrlProviderClient(BaseProviderClient):
    def __init__(self, runtime_config: Dict[str, Any]):
        super().__init__(PROVIDER_ID, runtime_config)
        self.comfy_url = os.getenv("COMFYUI_URL", "http://localhost:8188")
        self._http = httpx.AsyncClient(base_url=self.comfy_url, timeout=30.0)

    async def close(self):
        await self._http.aclose()

    def _iter_object_info_model_paths(self, object_info: Dict[str, Any], directory: str = "") -> list[str]:
        """Walk /object_info and yield model file paths for the given directory.

        Shared by list_models and validate_models so the NODE_TO_DIRECTORY /
        MODEL_INPUT_NAMES parsing logic lives in exactly one place.
        """
        paths: list[str] = []
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
        # Local-only health check per VISION #4: never probe the remote
        # engine on health checks. The worker assumes the remote URL is
        # alive until an actual job is dispatched.
        return {"status": "healthy", "provider_id": PROVIDER_ID, "ready": True, "engine": "direct_url", "comfy_url": self.comfy_url}

    async def get_info(self) -> Dict[str, Any]:
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
        return build_status_response("success", "Setup not needed for direct_url provider", provider=PROVIDER_ID)

    async def download_model(self, request: DownloadRequest) -> Dict[str, Any]:
        return build_error_response(
            "Model download is not supported for direct_url providers. "
            "Please install models directly on the ComfyUI server.",
            retryable=False,
            code=501,
        )

    async def list_models(self, request: Optional[ListModelsRequest] = None) -> Dict[str, Any]:
        directory = request.directory if request else ""
        try:
            resp = await self._http.get("/object_info")
            resp.raise_for_status()
            object_info = resp.json()
        except Exception as e:
            self.logger.warning(f"Failed to fetch /object_info: {e}")
            return build_error_response(f"Failed to query ComfyUI: {e}", retryable=True, code=502)

        files = [
            {"name": path.split("/", 1)[-1], "path": path, "type": "file", "size": 0}
            for path in self._iter_object_info_model_paths(object_info, directory)
        ]
        return build_status_response("success", f"Listed {len(files)} models", provider=PROVIDER_ID, files=files)

    async def delete_model(self, request: DeleteModelRequest) -> Dict[str, Any]:
        return {"success": False, "message": "Model deletion is not supported for direct_url providers.", "provider": PROVIDER_ID}

    async def get_file(self, path: str) -> StreamingResponse:
        try:
            resp = await self._http.get(f"/view", params={"filename": path})
            resp.raise_for_status()
            return Response(content=resp.content, media_type="application/octet-stream")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(status_code=404, detail=f"File not found: {path}")
            raise HTTPException(status_code=e.response.status_code, detail=str(e))

    async def delete_file(self, path: str) -> Dict[str, Any]:
        return {"success": False, "message": "File deletion is not supported for direct_url providers."}

    async def upload_file(self, request: UploadFileRequest) -> Dict[str, Any]:
        return {"status": "error", "message": "File upload is not supported for direct_url providers."}

    async def deploy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success", "message": "No deployment needed for direct_url"}

    async def validate_models(self, request: ValidateModelsRequest) -> Dict[str, Any]:
        try:
            resp = await self._http.get("/object_info")
            resp.raise_for_status()
            object_info = resp.json()
        except Exception as e:
            return build_error_response(f"Failed to query ComfyUI: {e}", retryable=True, code=502)

        target_dir = request.directory if isinstance(request.directory, str) else ""
        available = self._iter_object_info_model_paths(object_info, target_dir)

        return build_status_response(
            "success",
            f"Found {len(available)} models available on ComfyUI server",
            provider=PROVIDER_ID,
            available=available,
        )

    async def validate_all_models(self) -> Dict[str, Any]:
        return await self.validate_models(ValidateModelsRequest(directory=""))

    async def get_object_info(self) -> Dict[str, Any]:
        try:
            resp = await self._http.get("/object_info")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"status": "error", "message": f"Failed to query ComfyUI: {e}"}

    async def run_reconciliation(self, quick_sync: bool = False) -> Dict[str, Any]:
        backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")
        
        async def perform_reconciliation():
            try:
                resp = await self._http.get("/object_info")
                resp.raise_for_status()
                object_info = resp.json()
            except Exception as e:
                self.logger.error(f"Failed to query ComfyUI: {e}")
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
                        http_client=client
                    )
                else:
                    self.logger.error(f"Failed to register models: {response.status_code}")
            except Exception as e:
                self.logger.error(f"Error communicating with backend: {e}")

        import asyncio
        asyncio.create_task(perform_reconciliation())
        
        return build_status_response(
            "queued",
            "Reconciliation started (background task)",
            provider=PROVIDER_ID
        )
