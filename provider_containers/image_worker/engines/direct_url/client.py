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

    async def _close(self):
        await self._http.aclose()

    async def get_health(self) -> Dict[str, Any]:
        try:
            resp = await self._http.get("/system_stats")
            resp.raise_for_status()
            return {"status": "healthy", "provider_id": PROVIDER_ID, "ready": True, "engine": "direct_url", "comfy_url": self.comfy_url}
        except Exception:
            return {"status": "unhealthy", "provider_id": PROVIDER_ID, "ready": False, "engine": "direct_url", "comfy_url": self.comfy_url}

    async def get_info(self) -> Dict[str, Any]:
        return {"provider_id": PROVIDER_ID, "type": "direct_url", "containerized": True, "comfy_url": self.comfy_url}

    async def inference(self, request: InferenceRequest) -> StreamingResponse:
        from image_worker.comfy.workflow_executor import execute_comfy_workflow, IMAGE_FETCH_VIEW_API

        async def stream():
            try:
                async for payload in execute_comfy_workflow(
                    workflow_json=request.workflow,
                    comfy_api_url=self.comfy_url,
                    image_fetch_mode=IMAGE_FETCH_VIEW_API,
                    logger=self.logger,
                ):
                    yield json.dumps(payload) + "\n"
            except Exception as e:
                self.logger.exception("Inference failed")
                yield json.dumps(build_error_response(str(e), retryable=False, code=500)) + "\n"

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    async def setup_models(self) -> Dict[str, Any]:
        return build_status_response("success", "Setup not needed for direct_url provider", provider=PROVIDER_ID)

    async def download_model(self, request: DownloadRequest) -> Dict[str, Any]:
        return build_status_response(
            "error",
            "Model download is not supported for direct_url providers. "
            "Please install models directly on the ComfyUI server.",
            provider=PROVIDER_ID,
        )

    async def list_models(self, request: Optional[ListModelsRequest] = None) -> Dict[str, Any]:
        directory = request.directory if request else ""
        try:
            resp = await self._http.get("/object_info")
            resp.raise_for_status()
            object_info = resp.json()
        except Exception as e:
            self.logger.warning(f"Failed to fetch /object_info: {e}")
            return build_status_response("error", f"Failed to query ComfyUI: {e}", provider=PROVIDER_ID, files=[])

        files_by_name: Dict[str, Dict[str, Any]] = {}
        for node_type, node_info in object_info.items():
            target_dir = NODE_TO_DIRECTORY.get(node_type)
            if not target_dir:
                continue
            if directory and target_dir != directory:
                continue
            inputs = node_info.get("input", {}).get("required", []) + node_info.get("input", {}).get("optional", [])
            for input_def in inputs:
                if len(input_def) < 2:
                    continue
                input_name = input_def[0]
                if input_name not in MODEL_INPUT_NAMES:
                    continue
                model_list = input_def[1]
                if isinstance(model_list, list) and model_list:
                    choices = model_list[0] if isinstance(model_list[0], list) else model_list
                    for model_name in choices:
                        if not isinstance(model_name, str) or not model_name:
                            continue
                        file_path = f"{target_dir}/{model_name}"
                        if file_path not in files_by_name:
                            files_by_name[file_path] = {
                                "name": model_name,
                                "path": file_path,
                                "type": "file",
                                "size": 0,
                            }

        files = sorted(files_by_name.values(), key=lambda f: f["path"])
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
            return build_status_response("error", f"Failed to query ComfyUI: {e}", provider=PROVIDER_ID)

        target_dir = request.directory if isinstance(request.directory, str) else ""
        available = set()
        for node_type, node_info in object_info.items():
            expected_dir = NODE_TO_DIRECTORY.get(node_type)
            if not expected_dir:
                continue
            if target_dir and expected_dir != target_dir:
                continue
            inputs = node_info.get("input", {}).get("required", []) + node_info.get("input", {}).get("optional", [])
            for input_def in inputs:
                if len(input_def) < 2:
                    continue
                input_name = input_def[0]
                if input_name not in MODEL_INPUT_NAMES:
                    continue
                model_list = input_def[1]
                if isinstance(model_list, list) and model_list:
                    choices = model_list[0] if isinstance(model_list[0], list) else model_list
                    for model_name in choices:
                        if isinstance(model_name, str) and model_name:
                            available.add(f"{expected_dir}/{model_name}")

        return build_status_response(
            "success",
            f"Found {len(available)} models available on ComfyUI server",
            provider=PROVIDER_ID,
            available=list(available),
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

    async def run_reconciliation(self) -> Dict[str, Any]:
        return build_status_response(
            "success",
            "Reconciliation is not applicable for direct_url providers. "
            "Models are managed directly on the ComfyUI server.",
            provider=PROVIDER_ID,
        )
