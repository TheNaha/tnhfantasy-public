from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.exceptions import (
    ComfyError,
    ConfigurationError,
    ContainerError,
    DownloadError,
    JobError,
    MissingModelsError,
    NotFoundError,
    ProviderError,
    ServiceUnavailableError,
    UploadValidationError,
    ValidationError,
)
from infrastructure.logging import get_logger

logger = get_logger("error_handlers")


def register_exception_handlers(app: FastAPI) -> None:
    """Register application-wide exception handlers."""

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError):
        logger.warning("not_found_error", path=request.url.path, error=exc.message, code=exc.code)
        return JSONResponse(
            status_code=404,
            content={"error": exc.message, "code": exc.code},
        )

    @app.exception_handler(ValidationError)
    async def validation_handler(request: Request, exc: ValidationError):
        logger.warning("validation_error", path=request.url.path, error=exc.message, field=exc.field)
        return JSONResponse(
            status_code=400,
            content={"error": exc.message, "code": exc.code, "field": exc.field},
        )

    @app.exception_handler(UploadValidationError)
    async def upload_validation_handler(request: Request, exc: UploadValidationError):
        logger.warning(
            "upload_validation_error",
            path=request.url.path,
            error=exc.message,
            code=exc.code,
            field=exc.field,
        )
        return JSONResponse(status_code=400, content=exc.to_payload())

    @app.exception_handler(ServiceUnavailableError)
    async def service_unavailable_handler(request: Request, exc: ServiceUnavailableError):
        # Registered as its own handler, not folded into the `ComfyError` one,
        # because `ComfyError` maps to 500 and "the thing you depend on is down"
        # is precisely the case a client must be able to tell apart from a bug.
        # Retries are the right response here and the wrong response to a 500.
        logger.error(
            "service_unavailable",
            path=request.url.path,
            service=exc.service,
            error=exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message, "code": exc.code, "service": exc.service},
        )

    @app.exception_handler(ProviderError)
    async def provider_error_handler(request: Request, exc: ProviderError):
        logger.error("provider_error", path=request.url.path, error=exc.message, code=exc.code)
        return JSONResponse(
            status_code=502,
            content={"error": exc.message, "code": exc.code},
        )

    @app.exception_handler(ContainerError)
    async def container_error_handler(request: Request, exc: ContainerError):
        logger.error("container_error", path=request.url.path, error=exc.message, code=exc.code)
        return JSONResponse(
            status_code=502,
            content={"error": exc.message, "code": exc.code},
        )

    @app.exception_handler(DownloadError)
    async def download_error_handler(request: Request, exc: DownloadError):
        logger.error("download_error", path=request.url.path, error=exc.message, code=exc.code)
        return JSONResponse(
            status_code=502,
            content={"error": exc.message, "code": exc.code},
        )

    @app.exception_handler(JobError)
    async def job_error_handler(request: Request, exc: JobError):
        logger.error("job_error", path=request.url.path, error=exc.message, code=exc.code)
        return JSONResponse(
            status_code=500,
            content={"error": exc.message, "code": exc.code},
        )

    @app.exception_handler(ConfigurationError)
    async def configuration_error_handler(request: Request, exc: ConfigurationError):
        logger.error("configuration_error", path=request.url.path, error=exc.message, code=exc.code)
        return JSONResponse(
            status_code=500,
            content={"error": exc.message, "code": exc.code},
        )

    @app.exception_handler(MissingModelsError)
    async def missing_models_error_handler(request: Request, exc: MissingModelsError):
        logger.error("missing_models_error", path=request.url.path, error=exc.message, code=exc.code)
        return JSONResponse(
            status_code=400,
            content={
                "error": exc.message,
                "code": exc.code,
                "required_models": exc.required_models,
                "global_missing": exc.global_missing,
                "missing_by_provider": exc.missing_by_provider,
                "can_trigger_download": exc.can_trigger_download,
            },
        )

    @app.exception_handler(ComfyError)
    async def comfy_error_handler(request: Request, exc: ComfyError):
        logger.error("comfy_error", path=request.url.path, error=exc.message, code=exc.code)
        return JSONResponse(
            status_code=500,
            content={"error": exc.message, "code": exc.code},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        logger.warning("http_exception", path=request.url.path, detail=exc.detail, status_code=exc.status_code)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.detail, "code": "HTTP_ERROR"},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        # `exc_info=True` used to cost 20+ SECONDS per unhandled exception, and
        # that is a self-inflicted DoS: the handler runs on the event loop, so
        # one bad request froze the whole app. The cause was not this call. It
        # was `infrastructure.logging` never calling `configure_logging()` at
        # import, so every module-level `get_logger(...)` (this one included)
        # bound to structlog's DEFAULT chain, which ends in `ConsoleRenderer`
        # rather than the app's `compact_renderer` — and `ConsoleRenderer`
        # hands `exc_info` to `RichTracebackFormatter`, which pretty-prints the
        # LOCALS of every frame. Walking the locals of a SQLAlchemy
        # Session/Connection is an unbounded object graph, so rendering took
        # ~22s and printed nothing useful. See `infrastructure/logging.py`.
        logger.error("unhandled_exception", path=request.url.path, error=str(exc), exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": "An unexpected error occurred", "code": "INTERNAL_SERVER_ERROR"},
        )
