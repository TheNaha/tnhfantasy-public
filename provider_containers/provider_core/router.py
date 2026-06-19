from typing import Protocol, Any, Dict, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from .models import (
    InferenceRequest, DownloadRequest, ListModelsRequest, DeleteModelRequest,
    UploadFileRequest, ValidateModelsRequest, CancelJobRequest,
    build_status_response
)

class ProviderClient(Protocol):
    async def get_health(self) -> Dict[str, Any]: ...
    async def get_info(self) -> Dict[str, Any]: ...
    async def cancel_job(self, request: CancelJobRequest) -> Dict[str, Any]: ...
    async def inference(self, request: InferenceRequest) -> StreamingResponse: ...
    async def setup_models(self) -> Dict[str, Any]: ...
    async def download_model(self, request: DownloadRequest) -> Dict[str, Any]: ...
    async def list_models(self, request: Optional[ListModelsRequest] = None) -> Dict[str, Any]: ...
    async def delete_model(self, request: DeleteModelRequest) -> Dict[str, Any]: ...
    async def get_file(self, path: str) -> StreamingResponse: ...
    async def delete_file(self, path: str) -> Dict[str, Any]: ...
    async def upload_file(self, request: UploadFileRequest) -> Dict[str, Any]: ...
    async def deploy(self, payload: Dict[str, Any]) -> Dict[str, Any]: ...
    async def validate_models(self, request: ValidateModelsRequest) -> Dict[str, Any]: ...
    async def validate_all_models(self) -> Dict[str, Any]: ...
    async def run_reconciliation(self) -> Dict[str, Any]: ...
    def get_reconciliation_status(self) -> Dict[str, Any]: ...
    def get_config(self) -> Dict[str, Any]: ...
    def update_config(self, new_config: Dict[str, Any]) -> Dict[str, Any]: ...

def attach_provider_routes(app: FastAPI, client: ProviderClient):
    @app.get("/health")
    async def health():
        return await client.get_health()

    @app.get("/info")
    async def info():
        return await client.get_info()

    @app.get("/config")
    async def config_get():
        return client.get_config()

    @app.post("/config")
    async def config_post(config: dict):
        return client.update_config(config)

    @app.post("/cancel-job")
    async def cancel_job(request: CancelJobRequest):
        return await client.cancel_job(request)

    @app.post("/inference")
    async def inference(request: InferenceRequest):
        return await client.inference(request)

    @app.post("/setup")
    async def setup():
        return await client.setup_models()

    @app.post("/download-model")
    async def download_model(request: DownloadRequest):
        return await client.download_model(request)

    @app.post("/list-models")
    @app.get("/list-models")
    async def list_models(request: Optional[ListModelsRequest] = None):
        if request is None:
            request = ListModelsRequest(directory="")
        return await client.list_models(request)

    @app.delete("/delete-model")
    @app.post("/delete-model")
    async def delete_model(request: DeleteModelRequest):
        return await client.delete_model(request)

    @app.get("/get-file/{path:path}")
    async def get_file(path: str):
        return await client.get_file(path)

    @app.delete("/delete-file/{path:path}")
    async def delete_file(path: str):
        return await client.delete_file(path)

    @app.post("/upload-file")
    async def upload_file(request: UploadFileRequest):
        return await client.upload_file(request)

    @app.post("/deploy")
    async def deploy(payload: dict):
        return await client.deploy(payload)

    @app.post("/validate-models")
    async def validate_models(request: ValidateModelsRequest):
        return await client.validate_models(request)

    @app.post("/validate-all-models")
    async def validate_all_models():
        return await client.validate_all_models()

    @app.post("/reconcile")
    async def reconcile():
        return await client.run_reconciliation()

    @app.get("/reconciliation-status")
    async def reconciliation_status():
        return client.get_reconciliation_status()
