from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.exceptions import ComfyError, NotFoundError, ValidationError
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

    @app.exception_handler(ComfyError)
    async def comfy_error_handler(request: Request, exc: ComfyError):
        logger.error("comfy_error", path=request.url.path, error=exc.message, code=exc.code)
        return JSONResponse(
            status_code=500,
            content={"error": exc.message, "code": exc.code},
        )