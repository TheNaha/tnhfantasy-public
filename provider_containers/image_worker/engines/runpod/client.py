from typing import Any, Dict, Optional
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
import json
import os
import asyncio

from provider_core import (
    InferenceRequest, DownloadRequest, ListModelsRequest, DeleteModelRequest,
    UploadFileRequest, ValidateModelsRequest, build_status_response, build_error_response,
    get_logger
)
from provider_core.base_client import BaseProviderClient

PROVIDER_ID = os.getenv("PROVIDER_ID", "runpod-worker")

logger = get_logger("image_worker.runpod.client")

class RunpodProviderClient(BaseProviderClient):
    def __init__(self, runtime_config: Dict[str, Any]):
        super().__init__(PROVIDER_ID, runtime_config)
        self.logger = logger
        self.endpoint_id = os.getenv("RUNPOD_ENDPOINT_ID", "")
        self.api_key = os.getenv("RUNPOD_API_KEY", "")
        self.base_url = f"https://api.runpod.ai/v2/{self.endpoint_id}"
        
    async def get_health(self) -> Dict[str, Any]:
        if not self.endpoint_id or not self.api_key:
            return {"status": "unhealthy", "provider_id": PROVIDER_ID, "ready": False,
                    "engine": "runpod", "reason": "RUNPOD_ENDPOINT_ID / RUNPOD_API_KEY not set"}
        return {"status": "healthy", "provider_id": PROVIDER_ID, "ready": True, "engine": "runpod"}

    async def get_info(self) -> Dict[str, Any]:
        return {"provider_id": PROVIDER_ID, "type": "runpod", "containerized": True}

    async def inference(self, request: InferenceRequest) -> StreamingResponse:
        async def stream():
            try:
                import httpx
                
                # RunPod expects {"input": {"workflow": ...}}
                payload = {
                    "input": {
                        "workflow": request.workflow
                    }
                }
                
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}"
                }
                
                inference_timeout = request.timeout_seconds or self.runtime_config.get("timeout_seconds", 300)
                
                async with httpx.AsyncClient() as client:
                    await self.job_tracker.start_job(request.job_id)
                    # Start the job
                    response = await client.post(
                        f"{self.base_url}/run",
                        headers=headers,
                        json=payload,
                        timeout=30.0
                    )
                    response.raise_for_status()
                    data = response.json()
                    job_id = data.get("id")
                    
                    if not job_id:
                        raise ValueError(f"Failed to get job ID from RunPod: {data}")
                    
                    # Poll for completion
                    completed = False
                    loop_started = asyncio.get_event_loop().time()
                    while not completed:
                        if await self.job_tracker.is_cancelled(request.job_id):
                            yield json.dumps({
                                "status": "cancelled",
                                "message": "Job cancelled",
                                "job_id": request.job_id,
                            }) + "\n"
                            return
                        if asyncio.get_event_loop().time() - loop_started > inference_timeout:
                            raise TimeoutError(f"RunPod job exceeded {inference_timeout}s")
                        await asyncio.sleep(2.0)
                        
                        status_res = await client.get(
                            f"{self.base_url}/status/{job_id}",
                            headers=headers,
                            timeout=30.0
                        )
                        status_res.raise_for_status()
                        status_data = status_res.json()
                        
                        status = status_data.get("status")
                        if status == "COMPLETED":
                            completed = True
                            # RunPod serverless typically returns the output in the "output" field
                            output = status_data.get("output", {})
                            
                            # Format for TNHComfy
                            # ComfyUI output generally returns images as {"status": "success", "images": [{"data": "base64..."}]}
                            # We yield that back
                            if isinstance(output, dict) and "message" in output and "status" in output:
                                # if output already matches comfyui format
                                yield json.dumps(output) + "\n"
                            else:
                                # otherwise wrap it
                                yield json.dumps({
                                    "status": "success",
                                    "images": output.get("images", []) if isinstance(output, dict) else [],
                                    "raw_output": output
                                }) + "\n"
                            
                        elif status in ["FAILED", "CANCELLED"]:
                            error_msg = status_data.get("error", "Unknown RunPod error")
                            raise ValueError(f"RunPod job failed: {error_msg}")
                        else:
                            # Still running or IN_PROGRESS
                            yield json.dumps({
                                "status": "running",
                                "message": f"RunPod Status: {status}"
                            }) + "\n"
                            
            except Exception as e:
                self.logger.exception("Inference failed")
                yield json.dumps(build_error_response(str(e), retryable=False, code=500)) + "\n"
            finally:
                await self.job_tracker.end_job(request.job_id)

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    async def setup_models(self) -> Dict[str, Any]:
        return build_status_response("success", "Setup complete", provider=PROVIDER_ID)

    async def download_model(self, request: DownloadRequest) -> Dict[str, Any]:
        return build_error_response("Not implemented for RunPod", retryable=False, code=501)

    async def list_models(self, request: Optional[ListModelsRequest] = None) -> Dict[str, Any]:
        return build_status_response("success", "Not implemented for RunPod", provider=PROVIDER_ID, files=[])

    async def delete_model(self, request: DeleteModelRequest) -> Dict[str, Any]:
        return {"success": False, "message": "Not implemented for RunPod", "provider": PROVIDER_ID}

    async def get_file(self, path: str) -> StreamingResponse:
        raise HTTPException(status_code=501, detail="Not implemented for RunPod")

    async def delete_file(self, path: str) -> Dict[str, Any]:
        return {"success": False, "message": "Not implemented for RunPod"}

    async def upload_file(self, request: UploadFileRequest) -> Dict[str, Any]:
        return {"status": "error", "message": "Not implemented for RunPod"}

    async def deploy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success", "message": "No deployment needed for RunPod API"}

    async def validate_models(self, request: ValidateModelsRequest) -> Dict[str, Any]:
        return {"status": "success", "message": "Validation stub"}

    async def validate_all_models(self) -> Dict[str, Any]:
        return {"status": "success", "message": "Validation stub"}

    async def get_object_info(self) -> Dict[str, Any]:
        return {"status": "error", "message": "Not implemented for RunPod"}

    async def run_reconciliation(self, quick_sync: bool = False) -> Dict[str, Any]:
        return build_status_response("success", "Reconciliation stub", provider=PROVIDER_ID)
