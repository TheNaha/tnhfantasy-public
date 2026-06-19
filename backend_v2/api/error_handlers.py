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
        logger.error("unhandled_exception", path=request.url.path, error=str(exc), exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": "An unexpected error occurred", "code": "INTERNAL_SERVER_ERROR"},
        )