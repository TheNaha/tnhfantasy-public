import os
from typing import Protocol, Any, Dict, Optional
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .auth import token_matches
from .logging import get_logger
from .models import (
    InferenceRequest, DownloadRequest, ListModelsRequest, DeleteModelRequest,
    UploadFileRequest, ValidateModelsRequest, CancelJobRequest, DeleteFileRequest,
    ReconcileRequest, TaskEvent, build_error_response
)
from .responses import config_fault_detail, retryable_for_status

logger = get_logger("provider_core.router")


def _with_started_event(response: StreamingResponse, job_id: Optional[str]) -> StreamingResponse:
    """Prepend a `started` TaskEvent to an inference stream.

    `TaskEvent.event` has carried `"started"` — documented as "job accepted, work
    beginning" — since the event schema was written, and the backend acts on it:
    it is the sole writer of `JobStatus.PRE_GENERATION`
    (`backend_v2/services/provider_client.py`), which is what `JobCard`'s
    "Preparing" state renders from. No worker ever emitted it, so that status and
    that UI state were unreachable: a job went straight from queued to
    generating.

    Emitting it here rather than in an engine is deliberate. `router.py` is the
    one request path every image worker's `/inference` goes through, so this is
    the only place that can guarantee the event regardless of engine. Deriving it
    from ComfyUI's own `execution_start` message does not: a job whose graph is
    entirely cached emits `execution_cached` and never starts executing, and the
    websocket reader in `workflow_executor.py` does not handle `execution_start`
    at all.

    It is prepended to a stream that already began, so an engine that emits its
    own `started` first would simply produce two; nothing downstream treats a
    repeat as terminal.
    """
    if not job_id or not hasattr(response, "body_iterator"):
        return response

    inner = response.body_iterator

    async def with_started():
        yield TaskEvent(event="started", job_id=job_id).to_ndjson()
        async for chunk in inner:
            yield chunk

    return StreamingResponse(
        with_started(),
        status_code=response.status_code,
        media_type=response.media_type,
        headers=dict(response.headers or {}),
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
    which meant an unset COMFY_PROVIDER_TOKEN disabled authentication
    entirely — and empty is what .env.example ships, so /inference,
    /download-model, /delete-model, /delete-file, /get-file, /upload-file,
    /config and (worst of all) /deploy were all open by default. /deploy shells
    out to `modal deploy` / `beam deploy`.
    """
    expected = os.getenv("COMFY_PROVIDER_TOKEN", "").strip()
    if not expected:
        logger.error(
            "provider_token_not_configured: set COMFY_PROVIDER_TOKEN in .env; "
            "refusing to serve an unauthenticated management API"
        )
        raise HTTPException(
            status_code=503,
            # retryable=False, explicitly: this container will answer 503 until
            # someone edits its environment. Advertising it as retryable made
            # the dispatcher fail the job over to a second provider and spend
            # real GPU money on a request that cannot succeed.
            detail=config_fault_detail(
                "COMFY_PROVIDER_TOKEN is not configured on this provider container"
            ),
        )
    # `provider_core/auth.py` owns the comparison. It encodes to bytes first
    # because `hmac.compare_digest` raises TypeError on a `str` holding a byte
    # >= 0x80, and Starlette decodes header bytes as latin-1: a single non-ASCII
    # character in X-Provider-Token raised *inside* this check, and the catch-all
    # above turned that into a 500 with `retryable: true`, which the backend
    # reads as "this provider is unhealthy, try the request elsewhere" — so one
    # malformed auth header became a paid retry across the whole pool.
    if not token_matches(request.headers.get("X-Provider-Token"), expected):
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

    @app.get("/live")
    async def live():
        """Process liveness. The container healthcheck's endpoint.

        Separate from `/health` on purpose. `/health` is the *operator and
        dispatcher* signal and is allowed to depend on an upstream: `direct_url`
        and `remote_comfy` probe their ComfyUI, because the backend decides
        whether to spend a paid job on the answer and needs the upstream's state.

        A container healthcheck needs neither. It answers "is this process
        serving HTTP", and nothing else. Pointing it at `/health` made a
        provider's container UNHEALTHY whenever a third-party ComfyUI the
        compose file neither manages nor gates was slow or down — five
        consecutive failures, a red `docker compose ps`, and a cascade out of
        anything that depends_on the provider, for a worker that was serving
        perfectly well. The upstream signal stays on `/health`, where the
        dispatcher reads it.

        MUST stay unauthenticated, same as `/health`: the healthcheck sends no
        headers.
        """
        return {"status": "alive", "provider_id": getattr(client, "provider_id", None)}

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
        response = await client.inference(request)
        return _with_started_event(response, request.job_id)

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
