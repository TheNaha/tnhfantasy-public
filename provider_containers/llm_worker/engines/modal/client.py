import os
import json
import logging
import asyncio
from typing import Dict, Any, Optional

from fastapi.responses import StreamingResponse

from provider_core.base_client import BaseProviderClient
from provider_core.models import (
    InferenceRequest, DownloadRequest, ListModelsRequest, DeleteModelRequest,
    UploadFileRequest, ValidateModelsRequest,
    build_status_response, build_error_response
)


class VLLMModalProviderClient(BaseProviderClient):
    """
    Provider Client for LLM generation via vLLM deployed on Modal.
    This starts a Modal Web Endpoint containing a vLLM AsyncLLMEngine.
    """

    def __init__(self, provider_id: str, runtime_config: Dict[str, Any]):
        super().__init__(provider_id=provider_id, runtime_config=runtime_config)
        self.logger = logging.getLogger("provider_core.engines.vllm_modal")
        self.modal_app_name = os.environ.get("MODAL_APP_NAME", "vllm-modal-stack")
        self.modal_username = os.environ.get("MODAL_USERNAME", "")
        self._function_cache = {}

    def _get_modal_function(self, func_name: str):
        import modal
        key = f"{self.modal_app_name}.{func_name}"
        if key not in self._function_cache:
            self.logger.info(f"[{self.provider_id}] Caching Modal function: {key}")
            self._function_cache[key] = modal.Function.from_name(self.modal_app_name, func_name)
        return self._function_cache[key]

    async def get_health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "provider_id": self.provider_id,
            "engine": "vllm_modal",
            "modal_app": self.modal_app_name,
        }

    async def get_info(self) -> Dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "type": "vllm_modal",
            "app_name": self.modal_app_name,
            "containerized": True,
        }

    async def inference(self, request: InferenceRequest) -> StreamingResponse:
        async def stream():
            try:
                workflow = request.workflow
                model_id = workflow.get("model") or request.job_id or "default-model"
                messages = workflow.get("messages", [])

                # Map messages to string prompt for vLLM or pass as list if chat template is supported
                # For simplicity, we just pass the workflow to the remote function
                
                generate_fn = self._get_modal_function("generate")
                
                async for update in generate_fn.remote_gen.aio(model_id, messages):
                    if isinstance(update, str):
                        yield update + "\n"
                    elif isinstance(update, dict):
                        yield json.dumps(update) + "\n"

            except Exception as e:
                self.logger.error(f"Error during inference: {str(e)}")
                yield json.dumps(build_error_response(str(e), retryable=True, code=500)) + "\n"

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    async def setup_models(self) -> Dict[str, Any]:
        return build_status_response("success", "Setup complete", provider=self.provider_id)

    async def download_model(self, request: DownloadRequest) -> Dict[str, Any]:
        try:
            download_func = self._get_modal_function("download_model")
            await download_func.spawn.aio(request.url, request.path, request.token)
            return build_status_response("queued", f"Download queued for {request.path}", provider=self.provider_id)
        except Exception as e:
            return build_error_response(f"Failed to queue download: {e}")

    async def list_models(self, request: Optional[ListModelsRequest] = None) -> Dict[str, Any]:
        directory = request.directory if request else ""
        try:
            list_func = self._get_modal_function("list_models")
            files = await list_func.remote.aio(directory)
            return build_status_response("success", f"Listed models in {directory}", provider=self.provider_id, files=files)
        except Exception as e:
            return build_error_response(f"Failed to list models: {e}")

    async def delete_model(self, request: DeleteModelRequest) -> Dict[str, Any]:
        try:
            delete_func = self._get_modal_function("delete_file")
            success = await delete_func.remote.aio(request.path)
            return {"success": success, "message": f"Deleted {request.path}" if success else f"Failed to delete {request.path}", "provider": self.provider_id}
        except Exception as e:
            return build_error_response(f"Failed to delete model: {e}")

    async def get_file(self, path: str):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="File access not supported")

    async def delete_file(self, path: str) -> Dict[str, Any]:
        return await self.delete_model(DeleteModelRequest(path=path))

    async def upload_file(self, request: UploadFileRequest) -> Dict[str, Any]:
        return build_error_response("File upload not supported", retryable=False, code=404)

    async def deploy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from provider_core.deploy import start_deploy_task
        from provider_core.base_client import _DEPLOY_STATE

        commands = [["modal", "deploy", "/app/modal_app.py"]]
        start_deploy_task("Modal vLLM", commands)
        return _DEPLOY_STATE

    async def validate_models(self, request: ValidateModelsRequest) -> Dict[str, Any]:
        return build_status_response("success", "Not applicable", provider=self.provider_id)

    async def validate_all_models(self) -> Dict[str, Any]:
        return build_status_response("success", "Not applicable", provider=self.provider_id)

    async def get_object_info(self) -> Dict[str, Any]:
        return {"object_info": {}}

    async def run_reconciliation(self, quick_sync: bool = False) -> Dict[str, Any]:
        return build_status_response("success", "Not applicable", provider=self.provider_id)
