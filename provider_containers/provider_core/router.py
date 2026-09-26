import hmac
import os
from typing import Protocol, Any, Dict, Optional
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging import get_logger
from .models import (
    InferenceRequest, DownloadRequest, ListModelsRequest, DeleteModelRequest,
    UploadFileRequest, ValidateModelsRequest, CancelJobRequest, DeleteFileRequest,
    ReconcileRequest, build_error_response
)
from .responses import config_fault_detail, retryable_for_status

logger = get_logger("provider_core.router")

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
    async def get_deploy_status(self) -> Dict[str, Any]: ...
    async def validate_models(self, request: ValidateModelsRequest) -> Dict[str, Any]: ...
    async def validate_all_models(self) -> Dict[str, Any]: ...
    async def run_reconciliation(self, quick_sync: bool = False) -> Dict[str, Any]: ...
    async def get_storage_stats(self) -> Dict[str, Any]: ...
    def get_reconciliation_status(self) -> Dict[str, Any]: ...
    def get_config(self) -> Dict[str, Any]: ...
    def update_config(self, new_config: Dict[str, Any]) -> Dict[str, Any]: ...
    async def get_object_info(self) -> Dict[str, Any]: ...

async def _require_worker_token(request: Request) -> None:
    """Auth gate for every state-touching provider endpoint.

    Fails CLOSED. The previous form was `if expected and header != expected`,
    which meant an unset PROVIDER_WORKER_TOKEN disabled authentication
    entirely — and empty is what .env.example ships, so /inference,
    /download-model, /delete-model, /delete-file, /get-file, /upload-file,
    /config and (worst of all) /deploy were all open by default. /deploy shells
    out to `modal deploy` / `beam deploy`.
    """
    expected = os.getenv("PROVIDER_WORKER_TOKEN", "").strip()
    if not expected:
        logger.error(
            "provider_token_not_configured: set PROVIDER_WORKER_TOKEN in .env; "
            "refusing to serve an unauthenticated management API"
        )
        raise HTTPException(
            status_code=503,
            # retryable=False, explicitly: this container will answer 503 until
            # someone edits its environment. Advertising it as retryable made
            # the dispatcher fail the job over to a second provider and spend
            # real GPU money on a request that cannot succeed.
            detail=config_fault_detail(
                "PROVIDER_WORKER_TOKEN is not configured on this provider container"
            ),
        )
    provided = request.headers.get("X-Provider-Token", "")
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid provider worker token")


def attach_provider_routes(app: FastAPI, client: ProviderClient):
    protected = [Depends(_require_worker_token)]
    @app.exception_handler(StarletteHTTPException)
    async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            message = detail.get("message") or detail.get("detail") or str(detail)
        else:
            message = str(detail)
        # A raiser that knows the fault is permanent says so in the detail (see
        # responses.config_fault_detail); everything else 5xx is transient.
        retryable = retryable_for_status(exc.status_code, detail)

        import json
        if request.url.path.rstrip("/").endswith("/inference"):
            async def stream():
                yield json.dumps(build_error_response(message=message, retryable=retryable, code=exc.status_code)) + "\n"
            return StreamingResponse(stream(), status_code=exc.status_code, media_type="application/x-ndjson")

        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_response(
                message=message,
                retryable=retryable,
                code=exc.status_code,
            )
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        import json
        message = f"Validation error: {exc.errors()}"
        if request.url.path.rstrip("/").endswith("/inference"):
            async def stream():
                yield json.dumps(build_error_response(message=message, retryable=False, code=422)) + "\n"
            return StreamingResponse(stream(), status_code=422, media_type="application/x-ndjson")

        return JSONResponse(
            status_code=422,
            content=build_error_response(
                message=message,
                retryable=False,
                code=422,
            )
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        # exc_info=True: this is the only traceback a crash inside a handler
        # produces, and a `modal deploy` / `beam deploy` subprocess that dies
        # here left nothing at all in any log.
        logger.error(f"Unhandled exception: {type(exc).__name__}: {exc}", exc_info=True)
        
        import json
        if request.url.path.rstrip("/").endswith("/inference"):
            async def stream():
                yield json.dumps(build_error_response(message="Internal server error", retryable=True, code=500)) + "\n"
            return StreamingResponse(stream(), status_code=500, media_type="application/x-ndjson")

        return JSONResponse(
            status_code=500,
            content=build_error_response(
                message="Internal server error",
                retryable=True,
                code=500,
            )
        )

    @app.get("/health")
    async def health():
        # MUST stay unauthenticated: the compose and Dockerfile healthchecks call
        # it with no headers.
        return await client.get_health()

    @app.get("/info", dependencies=protected)
    async def info():
        # Now gated. It returns the upstream endpoint (direct_url's comfy_url is
        # a LAN IP, modal's is a *.modal.run URL) and the provider identity, and
        # nothing unauthenticated on the Docker bridge should read either.
        # NOTE: the only consumer is GET /api/v2/providers/{id}/live-metrics
        # (api/routes/providers/lifecycle.py), which the Diagnostics tab polls
        # every 5s. The backend attaches X-Provider-Token for tnhcomfy-*
        # container hosts and for COMFY_WORKER_HOSTS, so a provider reached by
        # any other hostname now answers 401 there.
        return await client.get_info()

    @app.get("/config", dependencies=protected)
    async def config_get():
        return client.get_config()

    @app.get("/provider-stats", dependencies=protected)
    async def provider_stats():
        # Now gated: nothing in backend_v2 or frontend_v2 calls it, and on a
        # remote_comfy provider this fans out to MODEL_DIRECTORIES x
        # list_models — 16 authenticated round trips to the remote agent —
        # triggered by an unauthenticated request.
        return await client.get_storage_stats()

    @app.post("/config", dependencies=protected)
    async def config_post(config: dict):
        return client.update_config(config)

    @app.post("/cancel-job", dependencies=protected)
    async def cancel_job(request: CancelJobRequest):
        return await client.cancel_job(request)

    @app.post("/inference", dependencies=protected)
    async def inference(request: InferenceRequest):
        return await client.inference(request)

    @app.post("/setup", dependencies=protected)
    async def setup():
        return await client.setup_models()

    @app.post("/download-model", dependencies=protected)
    async def download_model(request: DownloadRequest):
        return await client.download_model(request)

    @app.post("/list-models", dependencies=protected)
    @app.get("/list-models", dependencies=protected)
    async def list_models(request: Optional[ListModelsRequest] = None):
        if request is None:
            request = ListModelsRequest(directory="")
        return await client.list_models(request)

    @app.post("/delete-model", dependencies=protected)
    async def delete_model(request: DeleteModelRequest):
        return await client.delete_model(request)

    @app.delete("/delete-model", dependencies=protected)
    async def delete_model_query(path: str):
        return await client.delete_model(DeleteModelRequest(path=path))

    @app.get("/get-file/{path:path}", dependencies=protected)
    async def get_file(path: str):
        return await client.get_file(path)

    @app.post("/delete-file", dependencies=protected)
    async def delete_file(request: DeleteFileRequest):
        return await client.delete_file(request.path)

    @app.delete("/delete-file", dependencies=protected)
    async def delete_file_query(request: DeleteFileRequest | None = None, path: str | None = None):
        # Accept the path in either the body or the query string. A DELETE with a
        # JSON body is what the backend actually sends, and a handler that only
        # declared `path: str` read the *query* parameter, so that request 422'd
        # and the caller reported "not found" for a file it had just written.
        target = (request.path if request is not None else None) or path
        if not target:
            raise HTTPException(status_code=400, detail="path is required")
        return await client.delete_file(target)

    @app.post("/upload-file", dependencies=protected)
    async def upload_file(request: UploadFileRequest):
        return await client.upload_file(request)

    @app.post("/deploy", dependencies=protected)
    async def deploy(payload: dict):
        return await client.deploy(payload)

    @app.get("/deploy-status", dependencies=protected)
    async def deploy_status():
        return await client.get_deploy_status()

    @app.post("/validate-models", dependencies=protected)
    async def validate_models(request: ValidateModelsRequest):
        return await client.validate_models(request)

    @app.post("/validate-all-models", dependencies=protected)
    async def validate_all_models():
        return await client.validate_all_models()

    @app.post("/reconcile", dependencies=protected)
    async def reconcile(request: Optional[ReconcileRequest] = None):
        quick_sync = request.quick_sync if request else False
        return await client.run_reconciliation(quick_sync=quick_sync)

    @app.get("/reconciliation-status", dependencies=protected)
    async def reconciliation_status():
        return client.get_reconciliation_status()

    @app.get("/object-info", dependencies=protected)
    async def object_info():
        return await client.get_object_info()
