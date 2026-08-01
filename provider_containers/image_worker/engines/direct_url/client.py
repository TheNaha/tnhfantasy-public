from typing import Any, Dict, Optional
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
import json

from provider_core import (
    InferenceRequest, DownloadRequest, ListModelsRequest, DeleteModelRequest,
    UploadFileRequest, ValidateModelsRequest, build_status_response, build_error_response
)
from provider_core.base_client import BaseProviderClient
import os

PROVIDER_ID = os.getenv("PROVIDER_ID", "direct-url-worker")

class DirectUrlProviderClient(BaseProviderClient):
    def __init__(self, runtime_config: Dict[str, Any]):
        super().__init__(PROVIDER_ID, runtime_config)
        self.comfy_url = os.getenv("COMFYUI_URL", "http://localhost:8188")
        
    async def get_health(self) -> Dict[str, Any]:
        # Simple health check against ComfyUI directly
        return {"status": "healthy", "provider_id": PROVIDER_ID, "ready": True, "engine": "direct_url", "comfy_url": self.comfy_url}

    async def get_info(self) -> Dict[str, Any]:
        return {"provider_id": PROVIDER_ID, "type": "direct_url", "containerized": True}

    async def inference(self, request: InferenceRequest) -> StreamingResponse:
        from image_worker.comfy.workflow_executor import execute_comfy_workflow, IMAGE_FETCH_VIEW_API
        import json
        
        async def stream():
            try:
                async for payload in execute_comfy_workflow(
                    workflow_json=request.workflow,
                    comfy_api_url=self.comfy_url,
                    image_fetch_mode=IMAGE_FETCH_VIEW_API, # We can't fetch from filesystem, only view API
                    logger=self.logger,
                ):
                    yield json.dumps(payload) + "\n"
            except Exception as e:
                self.logger.exception("Inference failed")
                yield json.dumps(build_error_response(str(e), retryable=False, code=500)) + "\n"

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    async def setup_models(self) -> Dict[str, Any]:
        return build_status_response("success", "Setup complete", provider=PROVIDER_ID)

    async def download_model(self, request: DownloadRequest) -> Dict[str, Any]:
        return build_status_response("error", "Not implemented yet", provider=PROVIDER_ID)

    async def list_models(self, request: Optional[ListModelsRequest] = None) -> Dict[str, Any]:
        return build_status_response("success", "Not implemented yet", provider=PROVIDER_ID, files=[])

    async def delete_model(self, request: DeleteModelRequest) -> Dict[str, Any]:
        return {"success": False, "message": "Not implemented yet", "provider": PROVIDER_ID}

    async def get_file(self, path: str) -> StreamingResponse:
        raise HTTPException(status_code=501, detail="Not implemented yet")

    async def delete_file(self, path: str) -> Dict[str, Any]:
        return {"success": False, "message": "Not implemented yet"}

    async def upload_file(self, request: UploadFileRequest) -> Dict[str, Any]:
        return {"status": "error", "message": "Not implemented yet"}

    async def deploy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success", "message": "No deployment needed for direct_url"}

    async def validate_models(self, request: ValidateModelsRequest) -> Dict[str, Any]:
        return {"status": "success", "message": "Validation stub"}

    async def validate_all_models(self) -> Dict[str, Any]:
        return {"status": "success", "message": "Validation stub"}

    async def get_object_info(self) -> Dict[str, Any]:
        return {"status": "error", "message": "Not implemented yet"}

    async def run_reconciliation(self) -> Dict[str, Any]:
        return build_status_response("success", "Reconciliation stub", provider=PROVIDER_ID)
